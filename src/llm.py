import base64
import time
from dotenv import load_dotenv
from openai import OpenAI, APITimeoutError, APIConnectionError, RateLimitError
from config import setting
from config_store import get_active, get_key
from providers import resolve_capabilities

load_dotenv()


RETRYABLE_EXCEPTIONS = (APITimeoutError, APIConnectionError, RateLimitError)


def _call_with_retry(fn):
    """带指数退避的重试。仅对可重试异常生效。"""
    max_retries = setting("agent.max_retries")
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except RETRYABLE_EXCEPTIONS as e:
            if attempt == max_retries:
                raise
            wait = 2 ** attempt
            print(f"  [LLM重试 {attempt + 1}/{max_retries}] {type(e).__name__}，{wait}秒后重试")
            time.sleep(wait)


class LLM:
    def __init__(self):
        active = get_active()
        if not active:
            raise RuntimeError("没有可用的模型配置，请在设置页添加一条")

        self.config_id = active["id"]
        self.model = active["model"]
        self.base_url = active["base_url"]

        # 这三个是「应用级偏好」，所有模型配置共享，所以留在 settings_spec
        # 而不是跟着配置卡片走——换个模型不该连带把输出上限也改了
        self.max_tokens = setting("llm.max_tokens")
        self.temperature = setting("llm.temperature")
        self.reasoning_effort = setting("llm.reasoning_effort")

        # **这套配置认什么，一处来源。** 预设打底、卡片可覆盖；
        # 编排层回传 reasoning、带 reasoning_effort、推压缩阈值，
        # 都从这里读，不再各写各的
        self.capabilities = resolve_capabilities(active)

        api_key = get_key(active["id"])
        self.mock = not api_key

        if not self.mock:
            self.client = OpenAI(
                api_key=api_key,
                base_url=active["base_url"],
            )

    def chat(self, system: str, user: str) -> str:
        if self.mock:
            return f"[MOCK] 收到：{user[:50]}"

        resp = _call_with_retry(lambda: self.client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        ))
        content = resp.choices[0].message.content
        if content is None:
            finish_reason = resp.choices[0].finish_reason
            raise RuntimeError(
                f"模型返回空内容（finish_reason={finish_reason}）。"
                f"可能是 max_tokens 不足或模型异常。"
            )
        return content

    def chat_messages(self, messages: list, tools: list = None):
        if self.mock:
            raise RuntimeError("mock 模式不支持 tool calling")

        def _call():
            kwargs = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "messages": messages,
            }
            # 只有推理型模型认这个字段。以前是"填了才带"，现在是
            # "填了**且这套配置认**才带"——能力清单说了算
            if self.reasoning_effort and self.capabilities.get("reasoning_effort"):
                kwargs["reasoning_effort"] = self.reasoning_effort
            # 不认工具调用的模型，给了 tools 会 400。不给它，
            # 它至少还能用文字回答
            if tools and self.capabilities.get("tool_calling", True):
                kwargs["tools"] = tools
            return self.client.chat.completions.create(**kwargs)

        resp = _call_with_retry(_call)

        usage = None
        if getattr(resp, "usage", None):
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
                "total_tokens": resp.usage.total_tokens,
            }

        message = resp.choices[0].message
        reasoning = getattr(message, "reasoning_content", None)
        return message, usage, reasoning

    def describe_images(self, images: list[bytes], prompt: str) -> str:
        """把图片交给模型，返回它读出来的文字。

        只给扫描件 PDF 用。模型不认图片时**在发请求前就拦**——
        服务端返回的 400 往往看不出是"这个模型不支持图片"，用户
        只会看到一串英文。这里统一成一句能照做的提示。
        """
        # mock 态没有 client。不先说清楚，扫描件会以一个 AttributeError
        # 收场，用户看不到问题在哪
        if self.mock:
            raise RuntimeError(
                "当前模型配置还没有填 API key，无法识别扫描件PDF"
            )
        if not self.capabilities.get("vision"):
            raise RuntimeError(
                "您当前使用的模型没有图片识别能力，无法识别扫描件PDF"
            )

        content = [{"type": "text", "text": prompt}]
        for png in images:
            b64 = base64.b64encode(png).decode("ascii")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            })

        try:
            resp = _call_with_retry(lambda: self.client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=0,
                messages=[{"role": "user", "content": content}],
            ))
        except Exception as e:
            text = str(e).lower()
            # 只认和图片输入直接相关的信号。裸的 "400" 太宽：模型名写错、
            # 上下文超长也是 400，按"没有视觉能力"报会把人引到错误方向
            if any(k in text for k in (
                "image", "vision", "unsupported content",
                "does not support image", "invalid content type",
            )):
                raise RuntimeError(
                    "您当前使用的模型没有图片识别能力，无法识别扫描件PDF"
                ) from e
            raise

        return resp.choices[0].message.content or ""
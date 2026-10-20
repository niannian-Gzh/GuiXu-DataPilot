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
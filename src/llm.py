import os
import time
import yaml
from dotenv import load_dotenv
from openai import OpenAI, APITimeoutError, APIConnectionError, RateLimitError
from config import PROJECT_ROOT

load_dotenv()


RETRYABLE_EXCEPTIONS = (APITimeoutError, APIConnectionError, RateLimitError)
MAX_RETRIES = 3


def _call_with_retry(fn):
    """带指数退避的重试。仅对可重试异常生效。"""
    for attempt in range(MAX_RETRIES + 1):
        try:
            return fn()
        except RETRYABLE_EXCEPTIONS as e:
            if attempt == MAX_RETRIES:
                raise
            wait = 2 ** attempt
            print(f"  [LLM重试 {attempt + 1}/{MAX_RETRIES}] {type(e).__name__}，{wait}秒后重试")
            time.sleep(wait)


class LLM:
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = str(PROJECT_ROOT / "config.yaml")

        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)["llm"]

        self.model = cfg["model"]
        self.max_tokens = cfg["max_tokens"]
        self.temperature = cfg["temperature"]

        api_key = os.getenv("DEEPSEEK_API_KEY")
        self.mock = not api_key

        if not self.mock:
            self.client = OpenAI(
                api_key=api_key,
                base_url=cfg["base_url"],
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
            if tools:
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

        return resp.choices[0].message, usage
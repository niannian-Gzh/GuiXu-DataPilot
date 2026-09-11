import os
import yaml
from dotenv import load_dotenv
from openai import OpenAI
from config import PROJECT_ROOT

load_dotenv()


class LLM:
    def __init__(self, config_path: str = str(PROJECT_ROOT / "config.yaml")):
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

        resp = self.client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = resp.choices[0].message.content
        if content is None:
            finish_reason = resp.choices[0].finish_reason
            raise RuntimeError(
                f"模型返回空内容（finish_reason={finish_reason}）。"
                f"可能是 max_tokens 不足或模型异常。"
            )
        return content

    def chat_messages(self, messages: list, tools: list = None):
        """支持完整 messages 数组和工具调用的对话。返回 message 对象。"""
        if self.mock:
            raise RuntimeError("mock 模式不支持 tool calling")

        kwargs = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        resp = self.client.chat.completions.create(**kwargs)

        return resp.choices[0].message

    


if __name__ == "__main__":
    llm = LLM()
    print(llm.chat("你是一个助手", "用一句话介绍你自己"))
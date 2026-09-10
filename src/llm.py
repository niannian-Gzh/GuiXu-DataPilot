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
        return resp.choices[0].message.content


if __name__ == "__main__":
    llm = LLM()
    print(llm.chat("你是一个助手", "用一句话介绍你自己"))
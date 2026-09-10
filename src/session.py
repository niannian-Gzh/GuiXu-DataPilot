class Session:
    def __init__(self):
        self.messages = []

    def add_user(self, text: str):
        self.messages.append({"role": "user", "content": text})

    def add_assistant(self, text: str):
        self.messages.append({"role": "assistant", "content": text})

    def get_history(self) -> list:
        return list(self.messages)

    def clear(self):
        self.messages.clear()

    def __len__(self):
        return len(self.messages)
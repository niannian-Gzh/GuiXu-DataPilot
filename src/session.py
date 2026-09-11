class Session:
    def __init__(self):
        self.messages = []
        self.pending_action = None

    def add_user(self, text: str):
        self.messages.append({"role": "user", "content": text})

    def add_assistant(self, text: str):
        self.messages.append({"role": "assistant", "content": text})

    def get_history(self) -> list:
        return list(self.messages)

    def clear(self):
        self.messages.clear()

    def set_pending(self, action: dict):
        self.pending_action = action

    def get_pending(self) -> dict:
        return self.pending_action

    def clear_pending(self):
        self.pending_action = None

    def __len__(self):
        return len(self.messages)

import json
from datetime import datetime
import typing

class Chat:
    def __init__(self):
        self.messages = []
        self.resume = ""
    def length_in_tokens(self):
        return sum(len(message.content.split()) for message in self.messages)
    def append(self, message):
        self.messages.append(message)
    def __iter__(self):
        return iter(self.messages)
    def __len__(self):
        return len(self.messages)
class Message:
    def __init__(self, role: str, content: str,documents=None):
        self.time = datetime.now()
        self.role = role
        self.content = content
        self.documents = documents if documents is not None else []
    def to_dict(self):
        return {
            "timestamp": self.time.isoformat(),
            "role": self.role,
            "content": self.content,
            "documents": self.documents,
        }
    def __repr__(self):
        return f"[{self.time}] {self.role.capitalize()}: {self.content}\n"

    def __str__(self):
        return f"[{self.time}] {self.role.capitalize()}: {self.content}\n"
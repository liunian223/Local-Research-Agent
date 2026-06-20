from __future__ import annotations

from abc import ABC, abstractmethod


class LLMClient(ABC):
    @abstractmethod
    async def chat(self, messages: list[dict[str, str]], task_type: str = "chat", temperature: float = 0.2) -> str:
        """Return a text answer for chat-style messages."""

    @abstractmethod
    async def vision_chat(self, prompt: str, image_paths: list[str], task_type: str = "vision") -> str:
        """Return an answer grounded in project-local image assets."""


class LLMClientError(RuntimeError):
    def __init__(self, message: str, *, provider: str, task_type: str = "", retryable: bool = False) -> None:
        super().__init__(message)
        self.provider = provider
        self.task_type = task_type
        self.retryable = retryable

    def to_dict(self) -> dict[str, object]:
        return {
            "type": "llm_client_error",
            "provider": self.provider,
            "task_type": self.task_type,
            "retryable": self.retryable,
            "message": str(self)[:500],
        }

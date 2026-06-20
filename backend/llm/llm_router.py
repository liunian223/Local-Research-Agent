from __future__ import annotations

import config
from llm.base import LLMClient
from llm.codex_runtime_client import CodexRuntimeClient

_CLIENT: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _CLIENT
    provider = config.LLM_PROVIDER.lower()
    if _CLIENT is None:
        if provider in {"codex", "codex_cli", "codex_runtime"}:
            _CLIENT = CodexRuntimeClient()
        else:
            raise RuntimeError(f"Unsupported LLM_PROVIDER: {config.LLM_PROVIDER}")
    return _CLIENT


def reset_llm_client_for_tests() -> None:
    global _CLIENT
    _CLIENT = None

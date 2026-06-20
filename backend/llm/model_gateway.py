from __future__ import annotations

import re
from typing import Any, Optional

import config
from deepseek_client import DeepSeekClient, LLMResult
from llm.base import LLMClientError
from llm.codex_runtime_client import CodexRuntimeClient
from llm.llm_router import get_llm_client
from llm.openai_client import OpenAIClient


class ModelGateway:
    def __init__(self) -> None:
        self._openai_client: OpenAIClient | None = None
        self._deepseek_client: DeepSeekClient | None = None
        self._codex_runtime_client: CodexRuntimeClient | None = None

    def generate_text(
        self,
        prompt: str,
        system: str = "",
        purpose: str = "chat",
        temperature: float = 0.2,
        max_output_tokens: Optional[int] = None,
        image_paths: Optional[list[str]] = None,
    ) -> LLMResult:
        provider = config.TEXT_MODEL_PROVIDER.lower()
        if provider in {"codex", "codex_cli", "codex_runtime"}:
            try:
                client = get_llm_client()
                if isinstance(client, CodexRuntimeClient):
                    if image_paths:
                        content = client.vision_chat_sync(prompt if not system else f"{system}\n\n{prompt}", image_paths, task_type=purpose)
                        return LLMResult(ok=True, content=content, model=self._model_for_purpose("vision"), usage_summary=f"provider=codex; images={len(image_paths)}")
                    content = client.chat_sync(_chat_messages(prompt, system), task_type=purpose, temperature=temperature)
                    return LLMResult(ok=True, content=content, model=self._model_for_purpose(purpose), usage_summary="provider=codex; images=0")
                return LLMResult(ok=False, content="", model="codex", error="Configured Codex client does not expose sync chat.")
            except LLMClientError as exc:
                return LLMResult(ok=False, content="", model=self._model_for_purpose(purpose), error=str(exc))
            except Exception as exc:
                return LLMResult(ok=False, content="", model=self._model_for_purpose(purpose), error=str(exc)[:500])
        if provider == "openai":
            if config.DISABLE_OPENAI_API:
                return LLMResult(ok=False, content="", model=self._model_for_purpose(purpose), error="OpenAI API is disabled by configuration.")
            if not config.OPENAI_API_KEY:
                return LLMResult(ok=False, content="", model=self._model_for_purpose(purpose), error="OPENAI_API_KEY is not set.")
            return self._openai().generate_text(
                prompt=prompt,
                system=system,
                model=self._model_for_purpose(purpose),
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
        if provider == "deepseek":
            if not config.DEEPSEEK_API_KEY:
                return LLMResult(ok=False, content="", model=config.DEEPSEEK_MODEL_CHAT, error="DEEPSEEK_API_KEY is not set.")
            return self._deepseek().chat(
                messages=_chat_messages(prompt, system),
                model=config.DEEPSEEK_MODEL_NOTE if purpose == "note" else config.DEEPSEEK_MODEL_CHAT,
                temperature=temperature,
                max_tokens=max_output_tokens,
            )
        if image_paths:
            try:
                client = get_llm_client()
                if isinstance(client, CodexRuntimeClient):
                    content = client.vision_chat_sync(prompt if not system else f"{system}\n\n{prompt}", image_paths, task_type=purpose)
                    return LLMResult(ok=True, content=content, model=self._model_for_purpose("vision"), usage_summary=f"provider=codex; images={len(image_paths)}")
            except Exception as exc:
                return LLMResult(ok=False, content="", model=self._model_for_purpose("vision"), error=str(exc)[:500])
        return LLMResult(ok=False, content="", model="local_fallback", error=f"Local fallback provider selected: {provider}")

    def generate_json(
        self,
        prompt: str,
        system: str = "",
        schema_hint: str = "",
        max_output_tokens: int = 2048,
    ) -> dict[str, Any]:
        provider = config.TEXT_MODEL_PROVIDER.lower()
        if provider in {"codex", "codex_cli", "codex_runtime"}:
            try:
                client = get_llm_client()
                if not isinstance(client, CodexRuntimeClient):
                    return {"_error": "Configured Codex client does not expose sync chat.", "_model": "codex"}
                result = client.chat_sync(_chat_messages(f"{prompt}\n\nReturn only strict JSON.", system), task_type="json", temperature=0)
                try:
                    import json

                    parsed = json.loads(result)
                except Exception:
                    parsed = {"_parse_error": True, "raw": result[:4000]}
                parsed["_model"] = self._model_for_purpose("json")
                return parsed
            except Exception as exc:
                return {"_error": str(exc)[:500], "_model": self._model_for_purpose("json")}
        if provider == "openai":
            if config.DISABLE_OPENAI_API:
                return {"_error": "OpenAI API is disabled by configuration.", "_model": config.OPENAI_JSON_MODEL}
            if not config.OPENAI_API_KEY:
                return {"_error": "OPENAI_API_KEY is not set.", "_model": config.OPENAI_JSON_MODEL}
            return self._openai().generate_json(
                prompt=prompt,
                system=system,
                schema_hint=schema_hint,
                max_output_tokens=max_output_tokens,
            )
        if provider == "deepseek":
            if not config.DEEPSEEK_API_KEY:
                return {"_error": "DEEPSEEK_API_KEY is not set.", "_model": config.DEEPSEEK_MODEL_JSON}
            return self._deepseek().json_chat(
                messages=_chat_messages(f"{prompt}\n\nReturn only JSON.", system),
                model=config.DEEPSEEK_MODEL_JSON,
                max_tokens=max_output_tokens,
            )
        return {"_fallback": True, "_model": "local_fallback", "raw": ""}

    def summarize_figure(
        self,
        image_path: str,
        caption: str = "",
        nearby_text: str = "",
        section_path: str = "",
    ) -> dict[str, Any]:
        provider = config.VISION_MODEL_PROVIDER.lower()
        prompt = (
            "You are helping summarize a scientific paper figure for RAG. "
            "Use the image, caption, nearby text, and section path. Do not invent unclear details.\n\n"
            f"section_path:\n{section_path}\n\ncaption:\n{caption}\n\nnearby_text:\n{nearby_text}\n\n"
            "Return a concise visual summary and mention uncertainty when needed."
        )
        if provider == "openai" and config.ENABLE_OPENAI_VISION:
            if config.DISABLE_OPENAI_API:
                return self._caption_nearby_text_fallback(caption, nearby_text, section_path, "OpenAI API is disabled by configuration.")
            if not config.OPENAI_API_KEY:
                return self._caption_nearby_text_fallback(caption, nearby_text, section_path, "OPENAI_API_KEY is not set.")
            try:
                return self._openai().summarize_image(image_path=image_path, prompt=prompt, model=config.OPENAI_VISION_MODEL)
            except Exception as exc:
                return self._caption_nearby_text_fallback(caption, nearby_text, section_path, str(exc))
        return self._caption_nearby_text_fallback(caption, nearby_text, section_path, f"Vision provider disabled or unsupported: {provider}")

    def create_embeddings(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if config.EMBEDDING_PROVIDER.lower() == "openai":
            if config.DISABLE_OPENAI_API:
                raise RuntimeError("OpenAI API is disabled by configuration.")
            if not config.OPENAI_API_KEY:
                raise RuntimeError("OPENAI_API_KEY is not set.")
            return self._openai().create_embeddings(
                texts=texts,
                model=config.OPENAI_EMBEDDING_MODEL,
                dimensions=config.OPENAI_EMBEDDING_DIMENSIONS,
            )
        raise RuntimeError("Local embedding is handled by the vector backend fallback path.")

    def model_execution_info(self) -> dict[str, Any]:
        embedding_model = config.OPENAI_EMBEDDING_MODEL if config.EMBEDDING_PROVIDER.lower() == "openai" else config.EMBEDDING_MODEL
        text_provider = _effective_text_provider()
        vision_provider = _effective_vision_provider()
        fallbacks = []
        if text_provider == "openai" and (config.DISABLE_OPENAI_API or not config.OPENAI_API_KEY):
            fallbacks.append({"type": "openai_key_missing", "message": "OPENAI_API_KEY is not set. Used fallback provider."})
        return {
            "llm_provider": config.LLM_PROVIDER,
            "text_model_provider": text_provider,
            "text_model": self._model_for_purpose("chat"),
            "codex_cli_command": config.CODEX_CLI_COMMAND if text_provider in {"codex", "codex_cli", "codex_runtime"} else "",
            "codex_text_model": _codex_model_label(config.CODEX_MODEL_TEXT) if text_provider in {"codex", "codex_cli", "codex_runtime"} else "",
            "codex_vision_model": _codex_model_label(config.CODEX_MODEL_VISION) if vision_provider in {"codex", "codex_cli", "codex_runtime"} else "",
            "codex_sandbox": config.CODEX_SANDBOX,
            "codex_timeout_seconds": config.CODEX_TIMEOUT_SECONDS,
            "disable_openai_api": config.DISABLE_OPENAI_API,
            "openai_api_key_configured": bool(config.OPENAI_API_KEY),
            "vision_model_provider": vision_provider,
            "vision_model": config.OPENAI_VISION_MODEL if vision_provider == "openai" else _codex_model_label(config.CODEX_MODEL_VISION),
            "embedding_provider": config.EMBEDDING_PROVIDER,
            "embedding_model": embedding_model,
            "embedding_dimensions": config.OPENAI_EMBEDDING_DIMENSIONS if config.EMBEDDING_PROVIDER.lower() == "openai" else None,
            "deepseek_api_key_configured": bool(config.DEEPSEEK_API_KEY),
            "openai_vision_enabled": config.ENABLE_OPENAI_VISION and vision_provider == "openai" and not config.DISABLE_OPENAI_API,
            "openai_store_responses": config.OPENAI_STORE_RESPONSES,
            "fallbacks": fallbacks,
        }

    def _openai(self) -> OpenAIClient:
        if self._openai_client is None:
            self._openai_client = OpenAIClient()
        return self._openai_client

    def _deepseek(self) -> DeepSeekClient:
        if self._deepseek_client is None:
            self._deepseek_client = DeepSeekClient()
        return self._deepseek_client

    def _model_for_purpose(self, purpose: str) -> str:
        provider = _effective_vision_provider() if purpose == "vision" else _effective_text_provider()
        if provider in {"codex", "codex_cli", "codex_runtime"}:
            if purpose == "vision":
                return _codex_model_label(config.CODEX_MODEL_VISION)
            return _codex_model_label(config.CODEX_MODEL_TEXT)
        if purpose == "note":
            return config.OPENAI_NOTE_MODEL
        if purpose == "json":
            return config.OPENAI_JSON_MODEL
        return config.OPENAI_TEXT_MODEL

    def _caption_nearby_text_fallback(self, caption: str, nearby_text: str, section_path: str, error: str = "") -> dict[str, Any]:
        summary = (
            f"This figure is in section {section_path or 'unknown'}. "
            f"Caption: {caption or 'none'}. "
            f"Nearby text: {(nearby_text or '')[:700]}. "
            "This summary is based on caption and nearby text, not direct visual understanding."
        )
        return {
            "raw": summary,
            "summary_source": "caption_nearby_text",
            "warning": _safe_provider_error(error),
        }


def get_model_gateway() -> ModelGateway:
    return ModelGateway()


def _chat_messages(prompt: str, system: str = "") -> list[dict[str, str]]:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return messages


def _safe_provider_error(error: str) -> str:
    if not error:
        return ""
    for secret in [config.OPENAI_API_KEY, config.DEEPSEEK_API_KEY, config.GEMINI_API_KEY]:
        if secret:
            error = error.replace(secret, "[redacted]")
    error = re.sub(r"sk-[A-Za-z0-9*_-]{8,}", "[redacted-api-key]", error)
    return error[:500]


def _effective_text_provider() -> str:
    provider = config.TEXT_MODEL_PROVIDER.lower()
    if config.DISABLE_OPENAI_API and provider == "openai" and config.LLM_PROVIDER.lower() in {"codex", "codex_cli", "codex_runtime"}:
        return config.LLM_PROVIDER.lower()
    return provider


def _effective_vision_provider() -> str:
    provider = config.VISION_MODEL_PROVIDER.lower()
    if config.DISABLE_OPENAI_API and provider == "openai" and config.LLM_PROVIDER.lower() in {"codex", "codex_cli", "codex_runtime"}:
        return config.LLM_PROVIDER.lower()
    return provider


def _codex_model_label(model: str) -> str:
    return f"codex:{model or 'default'}"

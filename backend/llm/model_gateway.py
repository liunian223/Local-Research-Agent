from __future__ import annotations

import re
import time
from typing import Any, Optional

import config
from deepseek_client import DeepSeekClient, LLMResult, classify_model_error
from llm.base import LLMClientError
from llm.codex_runtime_client import CodexRuntimeClient
from llm.llm_router import get_llm_client
from llm.openai_client import OpenAIClient


_LAST_MODEL_ERROR_SUMMARY: dict[str, Any] = {}


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
                return _record_llm_error(
                    LLMResult(
                        ok=False,
                        content="",
                        model="codex",
                        error="Configured Codex client does not expose sync chat.",
                        provider=provider,
                        stage=purpose,
                        error_type="unknown_model_error",
                    )
                )
            except LLMClientError as exc:
                return _record_exception(exc, provider=provider, stage=purpose, model=self._model_for_purpose(purpose), retryable=exc.retryable)
            except Exception as exc:
                return _record_exception(exc, provider=provider, stage=purpose, model=self._model_for_purpose(purpose))
        if provider == "openai":
            if config.DISABLE_OPENAI_API:
                return _record_llm_error(
                    LLMResult(
                        ok=False,
                        content="",
                        model=self._model_for_purpose(purpose),
                        error="OpenAI API is disabled by configuration.",
                        provider="openai",
                        stage=purpose,
                        error_type="missing_api_key",
                    )
                )
            if not config.OPENAI_API_KEY:
                return _record_llm_error(
                    LLMResult(
                        ok=False,
                        content="",
                        model=self._model_for_purpose(purpose),
                        error="OPENAI_API_KEY is not set.",
                        provider="openai",
                        stage=purpose,
                        error_type="missing_api_key",
                    )
                )
            result = self._openai().generate_text(
                prompt=prompt,
                system=system,
                model=self._model_for_purpose(purpose),
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
            if not result.ok:
                result.provider = result.provider or "openai"
                result.stage = result.stage or purpose
                result.error_type = result.error_type or classify_model_error(None, result.error)[0]
                return _record_llm_error(result)
            return result
        if provider == "deepseek":
            if not config.DEEPSEEK_API_KEY:
                return _record_llm_error(
                    LLMResult(
                        ok=False,
                        content="",
                        model=config.DEEPSEEK_MODEL_CHAT,
                        error="DEEPSEEK_API_KEY is not set.",
                        provider="deepseek",
                        stage=purpose,
                        error_type="missing_api_key",
                    )
                )
            result = self._deepseek().chat(
                messages=_chat_messages(prompt, system),
                model=config.DEEPSEEK_MODEL_NOTE if purpose == "note" else config.DEEPSEEK_MODEL_CHAT,
                temperature=temperature,
                max_tokens=max_output_tokens,
            )
            if not result.ok:
                result.stage = result.stage or purpose
                return _record_llm_error(result)
            return result
        if image_paths:
            try:
                client = get_llm_client()
                if isinstance(client, CodexRuntimeClient):
                    content = client.vision_chat_sync(prompt if not system else f"{system}\n\n{prompt}", image_paths, task_type=purpose)
                    return LLMResult(ok=True, content=content, model=self._model_for_purpose("vision"), usage_summary=f"provider=codex; images={len(image_paths)}")
            except Exception as exc:
                return _record_exception(exc, provider=provider, stage="vision", model=self._model_for_purpose("vision"))
        return _record_llm_error(
            LLMResult(
                ok=False,
                content="",
                model="local_fallback",
                error=f"Local fallback provider selected: {provider}",
                provider=provider,
                stage=purpose,
                error_type="unknown_model_error",
            )
        )

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
                    return _record_json_error({"_error": "Configured Codex client does not expose sync chat.", "_model": "codex"}, provider=provider, stage="json")
                result = client.chat_sync(_chat_messages(f"{prompt}\n\nReturn only strict JSON.", system), task_type="json", temperature=0)
                try:
                    import json

                    parsed = json.loads(result)
                except Exception:
                    parsed = {
                        "_parse_error": True,
                        "raw": result[:4000],
                        "_structured_error": {
                            "ok": False,
                            "provider": provider,
                            "stage": "json",
                            "error_type": "json_parse_error",
                            "error_message": "Model response was not valid JSON.",
                            "retryable": False,
                        },
                    }
                    _record_json_error(parsed, provider=provider, stage="json")
                parsed["_model"] = self._model_for_purpose("json")
                return parsed
            except Exception as exc:
                result = {"_error": _safe_provider_error(str(exc)), "_model": self._model_for_purpose("json")}
                return _record_json_error(result, provider=provider, stage="json")
        if provider == "openai":
            if config.DISABLE_OPENAI_API:
                return _record_json_error({"_error": "OpenAI API is disabled by configuration.", "_model": config.OPENAI_JSON_MODEL}, provider="openai", stage="json")
            if not config.OPENAI_API_KEY:
                return _record_json_error({"_error": "OPENAI_API_KEY is not set.", "_model": config.OPENAI_JSON_MODEL}, provider="openai", stage="json")
            result = self._openai().generate_json(
                prompt=prompt,
                system=system,
                schema_hint=schema_hint,
                max_output_tokens=max_output_tokens,
            )
            if result.get("_error") or result.get("_parse_error"):
                return _record_json_error(result, provider="openai", stage="json")
            return result
        if provider == "deepseek":
            if not config.DEEPSEEK_API_KEY:
                return _record_json_error({"_error": "DEEPSEEK_API_KEY is not set.", "_model": config.DEEPSEEK_MODEL_JSON}, provider="deepseek", stage="json")
            result = self._deepseek().json_chat(
                messages=_chat_messages(f"{prompt}\n\nReturn only JSON.", system),
                model=config.DEEPSEEK_MODEL_JSON,
                max_tokens=max_output_tokens,
            )
            if result.get("_error") or result.get("_parse_error"):
                return _record_json_error(result, provider="deepseek", stage="json")
            return result
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
        if text_provider == "deepseek" and not config.DEEPSEEK_API_KEY:
            fallbacks.append({"type": "deepseek_key_missing", "message": "DEEPSEEK_API_KEY is not set. Used fallback provider."})
        fallback_enabled = True
        return {
            "provider": text_provider,
            "key_present": _key_present(text_provider),
            "key_source": _key_source(text_provider),
            "base_url": _base_url(text_provider),
            "chat_model": self._model_for_purpose("chat"),
            "note_model": self._model_for_purpose("note"),
            "json_model": self._model_for_purpose("json"),
            "last_model_error_summary": _LAST_MODEL_ERROR_SUMMARY,
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
            "deepseek_api_key_configured": bool(config.DEEPSEEK_API_KEY),
            "fallback_enabled": fallback_enabled,
            "fallback_provider": "local_grouped_evidence" if fallback_enabled else "",
            "vision_model_provider": vision_provider,
            "vision_model": config.OPENAI_VISION_MODEL if vision_provider == "openai" else _codex_model_label(config.CODEX_MODEL_VISION),
            "embedding_provider": config.EMBEDDING_PROVIDER,
            "embedding_model": embedding_model,
            "embedding_dimensions": config.OPENAI_EMBEDDING_DIMENSIONS if config.EMBEDDING_PROVIDER.lower() == "openai" else None,
            "openai_vision_enabled": config.ENABLE_OPENAI_VISION and vision_provider == "openai" and not config.DISABLE_OPENAI_API,
            "openai_store_responses": config.OPENAI_STORE_RESPONSES,
            "fallbacks": fallbacks,
        }

    def diagnostics(self, run_probe: bool = False) -> dict[str, Any]:
        provider = _effective_text_provider()
        result = {
            "provider": provider,
            "key_present": _key_present(provider),
            "key_source": _key_source(provider),
            "base_url": _base_url(provider),
            "models": {
                "chat": self._model_for_purpose("chat"),
                "note": self._model_for_purpose("note"),
                "json": self._model_for_purpose("json"),
            },
            "probes": {
                "chat": _probe_not_run(),
                "json": _probe_not_run(),
            },
            "fallback_enabled": self.model_execution_info()["fallback_enabled"],
        }
        if not run_probe:
            return result
        started = time.perf_counter()
        chat_result = self.generate_text(
            "Reply with exactly OK.",
            system="You are a minimal model connectivity probe.",
            purpose="chat",
            temperature=0,
            max_output_tokens=8,
        )
        result["probes"]["chat"] = _probe_result(chat_result, started)
        started = time.perf_counter()
        json_result = self.generate_json(
            'Return JSON {"ok": true}',
            system="Return only strict JSON.",
            max_output_tokens=64,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        structured = json_result.get("_structured_error") or _json_error_summary(json_result, provider)
        result["probes"]["json"] = {
            "ok": bool(json_result.get("ok") is True and not json_result.get("_error") and not json_result.get("_parse_error")),
            "latency_ms": latency_ms,
            "error_type": "" if not structured else structured.get("error_type", "unknown_model_error"),
            "error_message": "" if not structured else structured.get("error_message", ""),
        }
        result["fallback_enabled"] = self.model_execution_info()["fallback_enabled"]
        return result

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
        if provider == "deepseek":
            if purpose == "note":
                return config.DEEPSEEK_MODEL_NOTE
            if purpose == "json":
                return config.DEEPSEEK_MODEL_JSON
            return config.DEEPSEEK_MODEL_CHAT
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


def _record_llm_error(result: LLMResult) -> LLMResult:
    global _LAST_MODEL_ERROR_SUMMARY
    if not result.error_type:
        result.error_type, retryable = classify_model_error(None, result.error)
        result.retryable = result.retryable or retryable
    if not result.provider:
        result.provider = _effective_text_provider()
    if not result.stage:
        result.stage = "chat"
    result.error = _safe_provider_error(result.error)
    _LAST_MODEL_ERROR_SUMMARY = result.structured_error()
    return result


def _record_exception(exc: Exception, provider: str, stage: str, model: str, retryable: bool | None = None) -> LLMResult:
    error = _safe_provider_error(str(exc))
    error_type, classified_retryable = classify_model_error(exc, error)
    return _record_llm_error(
        LLMResult(
            ok=False,
            content="",
            model=model,
            error=error,
            provider=provider,
            stage=stage,
            error_type=error_type,
            retryable=classified_retryable if retryable is None else retryable,
        )
    )


def _record_json_error(result: dict[str, Any], provider: str, stage: str) -> dict[str, Any]:
    global _LAST_MODEL_ERROR_SUMMARY
    structured = result.get("_structured_error")
    if not structured:
        message = _safe_provider_error(str(result.get("_error") or "Model response was not valid JSON."))
        error_type = "json_parse_error" if result.get("_parse_error") else classify_model_error(None, message)[0]
        structured = {
            "ok": False,
            "provider": provider,
            "stage": stage,
            "error_type": error_type,
            "error_message": message,
            "retryable": classify_model_error(None, message)[1],
        }
        result["_structured_error"] = structured
    _LAST_MODEL_ERROR_SUMMARY = structured
    return result


def _json_error_summary(result: dict[str, Any], provider: str) -> dict[str, Any] | None:
    if not (result.get("_error") or result.get("_parse_error")):
        return None
    message = _safe_provider_error(str(result.get("_error") or "Model response was not valid JSON."))
    error_type = "json_parse_error" if result.get("_parse_error") else classify_model_error(None, message)[0]
    return {"provider": provider, "stage": "json", "error_type": error_type, "error_message": message, "retryable": False}


def _probe_not_run() -> dict[str, Any]:
    return {"ok": None, "latency_ms": 0, "error_type": "", "error_message": ""}


def _probe_result(result: LLMResult, started: float) -> dict[str, Any]:
    latency_ms = int((time.perf_counter() - started) * 1000)
    return {
        "ok": result.ok,
        "latency_ms": latency_ms,
        "error_type": "" if result.ok else (result.error_type or "unknown_model_error"),
        "error_message": "" if result.ok else result.error,
    }


def _key_present(provider: str) -> bool:
    if provider == "openai":
        return bool(config.OPENAI_API_KEY)
    if provider == "deepseek":
        return bool(config.DEEPSEEK_API_KEY)
    return False


def _key_source(provider: str) -> str:
    if provider == "openai":
        return config.config_key_source("OPENAI_API_KEY")
    if provider == "deepseek":
        return config.config_key_source("DEEPSEEK_API_KEY")
    return "missing"


def _base_url(provider: str) -> str:
    if provider == "openai":
        return config.OPENAI_BASE_URL
    if provider == "deepseek":
        return config.DEEPSEEK_BASE_URL
    return ""


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

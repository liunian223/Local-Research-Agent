from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any, Optional

import config
from deepseek_client import LLMResult


class OpenAIClient:
    def __init__(self) -> None:
        if not config.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set.")
        from openai import OpenAI

        self.client = OpenAI(
            api_key=config.OPENAI_API_KEY,
            base_url=config.OPENAI_BASE_URL,
            timeout=config.OPENAI_TIMEOUT_SECONDS,
            max_retries=config.OPENAI_MAX_RETRIES,
        )

    def generate_text(
        self,
        prompt: str,
        system: str = "",
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: Optional[int] = None,
    ) -> LLMResult:
        chosen_model = model or config.OPENAI_TEXT_MODEL
        try:
            content, usage = self._responses_text(chosen_model, prompt, system, temperature, max_output_tokens)
            return LLMResult(ok=True, content=content, model=chosen_model, usage_summary=usage)
        except Exception as first_exc:
            try:
                content, usage = self._chat_text(chosen_model, prompt, system, temperature, max_output_tokens)
                return LLMResult(ok=True, content=content, model=chosen_model, usage_summary=usage)
            except Exception as second_exc:
                return LLMResult(ok=False, content="", model=chosen_model, error=_safe_error(second_exc or first_exc))

    def generate_json(
        self,
        prompt: str,
        system: str = "",
        model: Optional[str] = None,
        schema_hint: str = "",
        max_output_tokens: int = 2048,
    ) -> dict[str, Any]:
        chosen_model = model or config.OPENAI_JSON_MODEL
        json_prompt = prompt
        if schema_hint:
            json_prompt = f"{prompt}\n\nReturn strict JSON matching this shape:\n{schema_hint}"
        try:
            response = self.client.responses.create(
                model=chosen_model,
                input=_responses_input(json_prompt, system),
                temperature=0,
                max_output_tokens=max_output_tokens,
                store=config.OPENAI_STORE_RESPONSES,
                text={"format": {"type": "json_object"}},
            )
            content = getattr(response, "output_text", "") or "{}"
        except Exception:
            result = self.generate_text(json_prompt + "\n\nReturn only JSON.", system=system, model=chosen_model, temperature=0, max_output_tokens=max_output_tokens)
            if not result.ok:
                return {"_error": result.error, "_model": chosen_model}
            content = result.content or "{}"
        try:
            parsed = json.loads(content)
        except Exception:
            parsed = {"_parse_error": True, "raw": content[:4000]}
        parsed["_model"] = chosen_model
        return parsed

    def summarize_image(
        self,
        image_path: str,
        prompt: str,
        model: Optional[str] = None,
        mime_type: Optional[str] = None,
        detail: str = "auto",
        max_output_tokens: int = 2048,
    ) -> dict[str, Any]:
        path = Path(image_path)
        chosen_model = model or config.OPENAI_VISION_MODEL
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")
        if path.stat().st_size > config.MAX_OPENAI_IMAGE_MB * 1024 * 1024:
            raise ValueError(f"Image exceeds MAX_OPENAI_IMAGE_MB: {image_path}")
        mime_type = mime_type or _guess_mime_type(path)
        data_url = f"data:{mime_type};base64,{base64.b64encode(path.read_bytes()).decode('utf-8')}"
        response = self.client.responses.create(
            model=chosen_model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": data_url, "detail": detail},
                    ],
                }
            ],
            max_output_tokens=max_output_tokens,
            store=config.OPENAI_STORE_RESPONSES,
        )
        return {"raw": getattr(response, "output_text", "") or "", "summary_source": chosen_model}

    def create_embeddings(
        self,
        texts: list[str],
        model: Optional[str] = None,
        dimensions: Optional[int] = None,
    ) -> list[list[float]]:
        if not texts:
            return []
        kwargs: dict[str, Any] = {
            "model": model or config.OPENAI_EMBEDDING_MODEL,
            "input": texts,
            "encoding_format": "float",
        }
        if dimensions is not None:
            kwargs["dimensions"] = dimensions
        response = self.client.embeddings.create(**kwargs)
        return [item.embedding for item in response.data]

    def _responses_text(
        self,
        model: str,
        prompt: str,
        system: str,
        temperature: float,
        max_output_tokens: Optional[int],
    ) -> tuple[str, str]:
        kwargs: dict[str, Any] = {
            "model": model,
            "input": _responses_input(prompt, system),
            "temperature": temperature,
            "store": config.OPENAI_STORE_RESPONSES,
        }
        if max_output_tokens is not None:
            kwargs["max_output_tokens"] = max_output_tokens
        response = self.client.responses.create(**kwargs)
        return getattr(response, "output_text", "") or "", _usage_summary(getattr(response, "usage", None))

    def _chat_text(
        self,
        model: str,
        prompt: str,
        system: str,
        temperature: float,
        max_output_tokens: Optional[int],
    ) -> tuple[str, str]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if max_output_tokens is not None:
            kwargs["max_tokens"] = max_output_tokens
        response = self.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or "", _usage_summary(getattr(response, "usage", None))


def _responses_input(prompt: str, system: str = "") -> list[dict[str, str]]:
    items = []
    if system:
        items.append({"role": "system", "content": system})
    items.append({"role": "user", "content": prompt})
    return items


def _usage_summary(usage: Any) -> str:
    if not usage:
        return ""
    return (
        f"prompt_tokens={getattr(usage, 'prompt_tokens', 0)}, "
        f"completion_tokens={getattr(usage, 'completion_tokens', 0)}, "
        f"total_tokens={getattr(usage, 'total_tokens', 0)}"
    )


def _guess_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    return "image/png"


def _safe_error(exc: Exception) -> str:
    message = str(exc)
    if config.OPENAI_API_KEY:
        message = message.replace(config.OPENAI_API_KEY, "[redacted]")
    message = re.sub(r"sk-[A-Za-z0-9*_-]{8,}", "[redacted-api-key]", message)
    return message[:500]

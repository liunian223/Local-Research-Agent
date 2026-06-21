from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional

import config


@dataclass
class LLMResult:
    ok: bool
    content: str
    model: str
    usage_summary: str = ""
    error: str = ""
    provider: str = ""
    stage: str = ""
    error_type: str = ""
    retryable: bool = False

    def structured_error(self) -> dict[str, Any]:
        return {
            "ok": False,
            "provider": self.provider or "unknown",
            "stage": self.stage or "chat",
            "error_type": self.error_type or "unknown_model_error",
            "error_message": self.error,
            "retryable": self.retryable,
        }


class DeepSeekClient:
    def __init__(self) -> None:
        if not config.DEEPSEEK_API_KEY:
            raise RuntimeError("DEEPSEEK_API_KEY is not set.")
        from openai import OpenAI

        self.client = OpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
            timeout=config.DEEPSEEK_TIMEOUT_SECONDS,
            max_retries=config.DEEPSEEK_MAX_RETRIES,
        )

    def chat(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
    ) -> LLMResult:
        chosen_model = model or config.DEEPSEEK_MODEL_CHAT
        kwargs: dict[str, Any] = {
            "model": chosen_model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        try:
            response = self.client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content or ""
            usage = getattr(response, "usage", None)
            usage_summary = ""
            if usage:
                usage_summary = (
                    f"prompt_tokens={getattr(usage, 'prompt_tokens', 0)}, "
                    f"completion_tokens={getattr(usage, 'completion_tokens', 0)}, "
                    f"total_tokens={getattr(usage, 'total_tokens', 0)}"
                )
            return LLMResult(ok=True, content=content, model=chosen_model, usage_summary=usage_summary, provider="deepseek", stage="chat")
        except Exception as exc:
            return _llm_error(exc, provider="deepseek", stage="chat", model=chosen_model)

    def json_chat(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        chosen_model = model or config.DEEPSEEK_MODEL_JSON
        base_kwargs: dict[str, Any] = {
            "model": chosen_model,
            "messages": messages,
            "temperature": 0,
            "stream": False,
        }
        if max_tokens is not None:
            base_kwargs["max_tokens"] = max_tokens
        try:
            response = self.client.chat.completions.create(**base_kwargs, response_format={"type": "json_object"})
            return _parse_json_response(response, chosen_model)
        except Exception as exc:
            structured = _structured_error(exc, provider="deepseek", stage="json")
            if _is_response_format_unsupported(exc):
                try:
                    response = self.client.chat.completions.create(**base_kwargs)
                    parsed = _parse_json_response(response, chosen_model)
                    parsed.setdefault("_fallbacks", []).append(
                        {
                            "type": "json_response_format_unsupported",
                            "message": "Provider rejected response_format=json_object; retried with plain chat and local JSON parsing.",
                        }
                    )
                    return parsed
                except Exception as retry_exc:
                    structured = _structured_error(retry_exc, provider="deepseek", stage="json")
            return {"_error": structured["error_message"], "_model": chosen_model, "_structured_error": structured}


def get_deepseek_client() -> Optional[DeepSeekClient]:
    if not config.DEEPSEEK_API_KEY:
        return None
    return DeepSeekClient()


def _parse_json_response(response: Any, chosen_model: str) -> dict[str, Any]:
    content = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(content)
    except Exception:
        parsed = {
            "_parse_error": True,
            "raw": content[:4000],
            "_structured_error": {
                "ok": False,
                "provider": "deepseek",
                "stage": "json",
                "error_type": "json_parse_error",
                "error_message": "Model response was not valid JSON.",
                "retryable": False,
            },
        }
    usage = getattr(response, "usage", None)
    if usage:
        parsed["_usage_summary"] = (
            f"prompt_tokens={getattr(usage, 'prompt_tokens', 0)}, "
            f"completion_tokens={getattr(usage, 'completion_tokens', 0)}, "
            f"total_tokens={getattr(usage, 'total_tokens', 0)}"
        )
    parsed["_model"] = chosen_model
    return parsed


def _llm_error(exc: Exception, provider: str, stage: str, model: str) -> LLMResult:
    structured = _structured_error(exc, provider=provider, stage=stage)
    return LLMResult(
        ok=False,
        content="",
        model=model,
        error=structured["error_message"],
        provider=provider,
        stage=stage,
        error_type=structured["error_type"],
        retryable=structured["retryable"],
    )


def _structured_error(exc: Exception, provider: str, stage: str) -> dict[str, Any]:
    message = _sanitize_error(str(exc))
    error_type, retryable = classify_model_error(exc, message)
    return {
        "ok": False,
        "provider": provider,
        "stage": stage,
        "error_type": error_type,
        "error_message": message,
        "retryable": retryable,
    }


def classify_model_error(exc: Exception | None, message: str = "") -> tuple[str, bool]:
    raw = message or (str(exc) if exc is not None else "")
    lowered = raw.lower()
    class_name = exc.__class__.__name__.lower() if exc is not None else ""
    status_code = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    if "api_key is not set" in lowered or "missing api key" in lowered:
        return "missing_api_key", False
    if status_code in {401, 403} or "authentication" in class_name or "invalid api key" in lowered or "unauthorized" in lowered:
        return "authentication_error", False
    if status_code == 429 or "rate limit" in lowered or "ratelimit" in class_name:
        return "rate_limit_error", True
    if "timeout" in class_name or "timed out" in lowered or "timeout" in lowered:
        return "timeout_error", True
    if "connection" in class_name or "connection" in lowered or "dns" in lowered or "name resolution" in lowered:
        return "connection_error", True
    if "context length" in lowered or "maximum context" in lowered or "too many tokens" in lowered:
        return "context_too_long", False
    if status_code == 400:
        return "bad_request_error", False
    if status_code == 404 or ("model" in lowered and ("not found" in lowered or "invalid" in lowered)):
        return "model_not_found_or_invalid", False
    if "model" in lowered:
        return "unknown_model_error", False
    return "unknown_model_error", False


def _is_response_format_unsupported(exc: Exception) -> bool:
    message = str(exc).lower()
    return "response_format" in message or "json_object" in message or ("json" in message and "support" in message)


def _sanitize_error(error: str) -> str:
    if not error:
        return ""
    for secret in [config.OPENAI_API_KEY, config.DEEPSEEK_API_KEY, config.GEMINI_API_KEY]:
        if secret:
            error = error.replace(secret, "[redacted]")
    error = re.sub(r"sk-[A-Za-z0-9*_-]{8,}", "[redacted-api-key]", error)
    return error[:500]


def build_rag_answer_prompt(question: str, evidence: list[dict[str, Any]]) -> list[dict[str, str]]:
    evidence_lines = []
    for item in evidence[: config.MAX_EVIDENCE_ITEMS]:
        text = (item.get("text") or "")[: config.MAX_EVIDENCE_CHARS]
        location = item.get("section_path") or item.get("section_name") or "Body"
        pages = ""
        if item.get("page_start"):
            pages = f" pages={item.get('page_start')}-{item.get('page_end') or item.get('page_start')}"
        prefix = item.get("context_prefix") or ""
        metadata = item.get("metadata") or {}
        abstract_flag = bool(item.get("is_abstract") or metadata.get("is_abstract"))
        role = item.get("chunk_role") or metadata.get("chunk_role") or ""
        evidence_lines.append(
            f"[{item.get('rank')}] source={item.get('source_type')} section={location}{pages} "
            f"is_abstract={str(abstract_flag).lower()} chunk_role={role}\n{prefix}\n{text}"
        )
    evidence_text = "\n\n".join(evidence_lines)
    return [
        {
            "role": "system",
            "content": (
                "You are the Note Skill Agent in Local Research Agent. Answer in Chinese. "
                "Use only the provided local RAG evidence. If evidence is insufficient, say so clearly. "
                "If evidence is marked is_abstract=true, treat it only as a high-level clue unless the user explicitly asks about the abstract or a whole-paper summary. "
                "Do not use abstract evidence as a substitute for concrete method, experiment, or result evidence."
            ),
        },
        {
            "role": "user",
            "content": f"Question:\n{question}\n\nLocal RAG evidence:\n{evidence_text}",
        },
    ]


def build_rag_answer_prompt_text(question: str, evidence: list[dict[str, Any]]) -> tuple[str, str]:
    messages = build_rag_answer_prompt(question, evidence)
    return messages[0]["content"], messages[1]["content"]


def build_note_generation_prompt(paper: dict[str, Any], evidence: list[dict[str, Any]], full_text: str) -> list[dict[str, str]]:
    evidence_lines = []
    for item in evidence[: config.MAX_EVIDENCE_ITEMS]:
        text = (item.get("text") or "")[: config.MAX_EVIDENCE_CHARS]
        location = item.get("section_path") or item.get("section_name") or "Body"
        pages = ""
        if item.get("page_start"):
            pages = f" pages={item.get('page_start')}-{item.get('page_end') or item.get('page_start')}"
        prefix = item.get("context_prefix") or ""
        evidence_lines.append(
            f"[{item.get('rank')}] source={item.get('source_type')} section={location}{pages}\n{prefix}\n{text}"
        )
    context = full_text[: config.MAX_CONTEXT_CHARS_PER_LLM_CALL]
    title = paper.get("title") or "Untitled Paper"
    authors = paper.get("authors") or "Unknown authors"
    return [
        {
            "role": "system",
            "content": (
                "You are the Deep Paper Note Skill inside Local Research Agent. "
                "Write a high-quality Obsidian-compatible Markdown reading note in Chinese. "
                "Use only the supplied metadata, parsed text, and RAG evidence. "
                "If evidence is weak, mark uncertainty clearly. Do not invent exact experiment numbers."
            ),
        },
        {
            "role": "user",
            "content": f"""请生成一份 Obsidian Markdown 阅读笔记，必须包含以下 14 个二级标题：
## 1. 基本信息
## 2. 一句话总结
## 3. 研究背景
## 4. 研究问题
## 5. 方法概述
## 6. 关键技术细节
## 7. 实验设置
## 8. 实验结果
## 9. 创新点
## 10. 局限性
## 11. 可复现性分析
## 12. 对我课题的启发
## 13. 可链接笔记
## 14. 原文证据片段

论文元数据：
- title: {title}
- authors: {authors}
- year: {paper.get('year') or ''}
- language: {paper.get('language') or ''}
- doi: {paper.get('doi') or ''}
- parse_status: {paper.get('parse_status') or ''}

RAG evidence:
{chr(10).join(evidence_lines) or 'No retrieved evidence.'}

Parsed text excerpt, truncated safely:
{context}
""",
        },
    ]


def build_note_generation_prompt_text(paper: dict[str, Any], evidence: list[dict[str, Any]], full_text: str) -> tuple[str, str]:
    messages = build_note_generation_prompt(paper, evidence, full_text)
    return messages[0]["content"], messages[1]["content"]

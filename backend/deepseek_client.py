from __future__ import annotations

import json
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
        try:
            response = self.client.chat.completions.create(
                model=chosen_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False,
            )
            content = response.choices[0].message.content or ""
            usage = getattr(response, "usage", None)
            usage_summary = ""
            if usage:
                usage_summary = (
                    f"prompt_tokens={getattr(usage, 'prompt_tokens', 0)}, "
                    f"completion_tokens={getattr(usage, 'completion_tokens', 0)}, "
                    f"total_tokens={getattr(usage, 'total_tokens', 0)}"
                )
            return LLMResult(ok=True, content=content, model=chosen_model, usage_summary=usage_summary)
        except Exception as exc:
            return LLMResult(ok=False, content="", model=chosen_model, error=str(exc)[:500])

    def json_chat(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        chosen_model = model or config.DEEPSEEK_MODEL_JSON
        try:
            response = self.client.chat.completions.create(
                model=chosen_model,
                messages=messages,
                temperature=0,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                stream=False,
            )
            content = response.choices[0].message.content or "{}"
            try:
                parsed = json.loads(content)
            except Exception:
                parsed = {"_parse_error": True, "raw": content[:4000]}
            usage = getattr(response, "usage", None)
            if usage:
                parsed["_usage_summary"] = (
                    f"prompt_tokens={getattr(usage, 'prompt_tokens', 0)}, "
                    f"completion_tokens={getattr(usage, 'completion_tokens', 0)}, "
                    f"total_tokens={getattr(usage, 'total_tokens', 0)}"
                )
            parsed["_model"] = chosen_model
            return parsed
        except Exception as exc:
            return {"_error": str(exc)[:500], "_model": chosen_model}


def get_deepseek_client() -> Optional[DeepSeekClient]:
    if not config.DEEPSEEK_API_KEY:
        return None
    return DeepSeekClient()


def build_rag_answer_prompt(question: str, evidence: list[dict[str, Any]]) -> list[dict[str, str]]:
    evidence_lines = []
    for item in evidence[: config.MAX_EVIDENCE_ITEMS]:
        text = (item.get("text") or "")[: config.MAX_EVIDENCE_CHARS]
        evidence_lines.append(
            f"[{item.get('rank')}] source={item.get('source_type')} section={item.get('section_name')}\n{text}"
        )
    evidence_text = "\n\n".join(evidence_lines)
    return [
        {
            "role": "system",
            "content": (
                "You are the Note Skill Agent in Local Research Agent. Answer in Chinese. "
                "Use only the provided local RAG evidence. If evidence is insufficient, say so clearly."
            ),
        },
        {
            "role": "user",
            "content": f"Question:\n{question}\n\nLocal RAG evidence:\n{evidence_text}",
        },
    ]


def build_note_generation_prompt(paper: dict[str, Any], evidence: list[dict[str, Any]], full_text: str) -> list[dict[str, str]]:
    evidence_lines = []
    for item in evidence[: config.MAX_EVIDENCE_ITEMS]:
        text = (item.get("text") or "")[: config.MAX_EVIDENCE_CHARS]
        evidence_lines.append(
            f"[{item.get('rank')}] source={item.get('source_type')} section={item.get('section_name')}\n{text}"
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

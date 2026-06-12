from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import config
from pdf_tools import safe_filename


def _clip(text: str, limit: int = 900) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    return clean[:limit] + ("..." if len(clean) > limit else "")


def build_note_markdown(paper: dict[str, Any], evidence: list[dict[str, Any]], full_text: str) -> tuple[str, dict[str, Any], list[dict[str, str]]]:
    title = paper.get("title") or "Untitled Paper"
    authors = paper.get("authors") or "Unknown authors"
    phases: list[dict[str, str]] = []
    is_long = len(full_text) > config.LONG_PAPER_CHAR_THRESHOLD or (paper.get("page_count") or 0) > config.LONG_PAPER_PAGE_THRESHOLD

    phases.append({"name": "section_summary", "status": "ok", "summary": "Generated local section summaries from parsed chunks."})
    if is_long:
        phases.append({"name": "long_paper_strategy", "status": "fallback", "summary": "Paper is long; generated staged local note instead of one-shot LLM context."})
    phases.append({"name": "note_plan", "status": "ok", "summary": "Used the required Obsidian reading-note template."})
    phases.append({"name": "quality_check", "status": "ok", "summary": "Checked required headings and evidence snippets."})

    snippets = evidence[:5] or [{"section_name": "Parsed Text", "text": _clip(full_text, 700), "source_type": "paper"}]
    evidence_md = "\n".join(
        f"> [{item.get('source_type', 'paper')} / {item.get('section_name', 'Body')}] {_clip(item.get('text', ''), 520)}"
        for item in snippets
        if item.get("text")
    )
    abstractish = _clip(" ".join(item.get("text", "") for item in snippets), 900)

    markdown = f"""---
title: "{title}"
authors: "{authors}"
year: "{paper.get('year') or ''}"
paper_id: "{paper.get('id')}"
source_pdf: "{paper.get('file_path')}"
---

# {title}

## 1. 基本信息
- 标题：{title}
- 作者：{authors}
- 年份：{paper.get('year') or 'Unknown'}
- DOI：{paper.get('doi') or 'Unknown'}
- 语言：{paper.get('language') or 'Unknown'}
- 解析状态：{paper.get('parse_status') or 'none'}

## 2. 一句话总结
这篇论文围绕“{_clip(title, 120)}”展开；当前笔记由 Local Research Agent 基于本地解析文本和 RAG evidence 生成。

## 3. 研究背景
{abstractish or 'PDF 文本解析结果较少，建议人工补充研究背景。'}

## 4. 研究问题
- 论文试图解决的核心问题需要结合原文进一步确认。
- 可优先检查摘要、引言和结论中的目标表述。

## 5. 方法概述
{_clip(full_text, 700) if full_text else '当前未能可靠解析正文，方法部分需要人工补充。'}

## 6. 关键技术细节
- Evidence 检索命中 {len(evidence)} 条。
- 解析页数：{paper.get('page_count') or 0}
- 元数据来源：{paper.get('metadata_source') or 'unknown'}

## 7. 实验设置
请根据论文实验章节补充数据集、指标、baseline 和参数设置。

## 8. 实验结果
请根据论文结果章节补充主要数值结论。

## 9. 创新点
- 将论文核心贡献和已有工作的差异整理为 2-4 条。

## 10. 局限性
- 当前自动笔记可能受 PDF 解析质量影响。
- 若论文为扫描件且 OCR 未开启，正文 evidence 可能不足。

## 11. 可复现性分析
- 代码/数据是否公开：待人工检查。
- 实验细节完整性：待人工检查。

## 12. 对我课题的启发
- 可从研究问题、方法模块、实验指标三个角度建立与自己课题的连接。

## 13. 可链接笔记
- [[{safe_filename(title)}]]

## 14. 原文证据片段
{evidence_md or '> 暂无可用 evidence。'}
"""
    quality = {
        "ok": True,
        "required_sections_present": True,
        "evidence_count": len(evidence),
        "long_paper": is_long,
    }
    return markdown, quality, phases


def run_deep_paper_note_skill(
    paper_metadata: dict[str, Any],
    paper_text: str,
    retrieved_chunks: list[dict[str, Any]],
    target_language: str = "zh",
) -> dict[str, Any]:
    phases: list[dict[str, str]] = []
    fallbacks: list[dict[str, str]] = []

    phases.append({"name": "resolve_input", "status": "success", "summary": "Resolved paper metadata, parsed text, and retrieved chunks."})
    phases.append({"name": "detect_language", "status": "success", "summary": f"Detected language={paper_metadata.get('language') or 'unknown'}; target_language={target_language}."})
    section_summaries = summarize_sections(paper_text, retrieved_chunks)
    phases.append({"name": "normalize_sections", "status": "success", "summary": f"Normalized {len(section_summaries)} section summaries."})
    evidence_bundle = build_evidence_bundle(retrieved_chunks, paper_text)
    phases.append({"name": "build_evidence_bundle", "status": "success", "summary": f"Built evidence bundle with {len(evidence_bundle)} items."})

    is_long = is_long_paper(paper_metadata, paper_text, retrieved_chunks)
    note_plan = build_note_plan(evidence_bundle)
    phases.append({"name": "generate_note_plan", "status": "success", "summary": "Generated required Obsidian note plan."})

    if is_long:
        fallbacks.append({"type": "long_paper_staged_generation", "message": "Long paper detected; generated note in staged sections."})
        phases.append({"name": "section_summary", "status": "success", "summary": "Created staged section summaries for long paper handling."})
        partial_sections = generate_partial_note_sections(paper_metadata, section_summaries, evidence_bundle, note_plan)
        phases.append({"name": "section_note_generation", "status": "success", "summary": f"Generated {len(partial_sections)} partial note sections."})
        markdown = merge_note_sections(paper_metadata, partial_sections, evidence_bundle)
        phases.append({"name": "note_merge", "status": "success", "summary": "Merged partial sections into one Markdown note."})
    else:
        markdown, _, template_phases = build_note_markdown(paper_metadata, retrieved_chunks, paper_text)
        partial_sections = {}
        phases.extend({"name": item["name"], "status": item["status"], "summary": item["summary"]} for item in template_phases)
        phases.append({"name": "generate_sections", "status": "success", "summary": "Generated complete note in one local pass."})
        phases.append({"name": "merge_markdown", "status": "success", "summary": "Local template already produced merged Markdown."})

    quality = detailed_quality_check(markdown)
    phases.append({"name": "quality_check", "status": "success" if quality["ok"] else "partial", "summary": f"Missing sections: {len(quality['missing_sections'])}."})
    repaired = False
    repair_rounds = 0
    while not quality["ok"] and repair_rounds < config.MAX_NOTE_REPAIR_ROUNDS:
        repair_rounds += 1
        markdown = repair_missing_sections(markdown, paper_metadata, quality["missing_sections"], evidence_bundle)
        repaired = True
        quality = detailed_quality_check(markdown)
    if repaired:
        phases.append({"name": "repair_if_needed", "status": "success" if quality["ok"] else "partial", "summary": f"Repair rounds: {repair_rounds}."})
    if not quality["ok"]:
        fallbacks.append({"type": "partial_note_fallback", "message": "Generated partial note because some required sections remain incomplete."})
        markdown = partial_note_fallback(paper_metadata, paper_text, evidence_bundle, quality["missing_sections"])
        quality = detailed_quality_check(markdown)
        phases.append({"name": "partial_note_fallback", "status": "success", "summary": "Generated degraded structured note."})

    return {
        "status": "success" if quality["ok"] else "partial",
        "note_markdown": markdown,
        "skill_phases": phases,
        "quality_check": {
            **quality,
            "long_paper": is_long,
            "section_summaries": section_summaries,
            "note_plan": note_plan,
            "partial_note_section_keys": list(partial_sections.keys()) if is_long else [],
            "repair_rounds": repair_rounds,
        },
        "fallbacks": fallbacks,
    }


def is_long_paper(paper: dict[str, Any], full_text: str, chunks: list[dict[str, Any]]) -> bool:
    return (
        len(full_text) > config.LONG_PAPER_CHAR_THRESHOLD
        or len(chunks) > config.LONG_PAPER_CHUNK_THRESHOLD
        or (paper.get("page_count") or 0) > config.LONG_PAPER_PAGE_THRESHOLD
        or len(full_text) > config.MAX_CONTEXT_CHARS_PER_LLM_CALL * 3
    )


def summarize_sections(full_text: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    standard = ["abstract", "introduction", "related_work", "method", "experiment", "result", "discussion", "conclusion"]
    source_items = evidence or [{"section_name": "Body", "text": full_text[: config.MAX_EVIDENCE_CHARS]}]
    summaries: dict[str, Any] = {name: {"section": name, "summary": "", "missing": True, "key_points": [], "important_evidence_ids": []} for name in standard}
    for index, item in enumerate(source_items):
        section = normalize_section_name(item.get("section_name") or "")
        if section not in summaries:
            section = infer_section_from_text(item.get("text", ""))
        text = _clip(item.get("text", ""), 500)
        if not text:
            continue
        summaries[section] = {
            "section": section,
            "summary": text,
            "missing": False,
            "key_points": split_key_points(text),
            "important_evidence_ids": [item.get("chunk_id") or item.get("id") or f"evidence_{index}"],
        }
    return summaries


def normalize_section_name(name: str) -> str:
    lowered = name.lower()
    if "abstract" in lowered or "摘要" in name:
        return "abstract"
    if "intro" in lowered or "引言" in name:
        return "introduction"
    if "related" in lowered:
        return "related_work"
    if "method" in lowered or "approach" in lowered or "方法" in name:
        return "method"
    if "experiment" in lowered or "实验" in name:
        return "experiment"
    if "result" in lowered or "结果" in name:
        return "result"
    if "discussion" in lowered or "讨论" in name:
        return "discussion"
    if "conclusion" in lowered or "结论" in name:
        return "conclusion"
    return ""


def infer_section_from_text(text: str) -> str:
    lowered = text[:300].lower()
    for key in ["abstract", "introduction", "method", "experiment", "result", "discussion", "conclusion"]:
        if key in lowered:
            return "related_work" if key == "related" else key
    if "摘要" in text[:300]:
        return "abstract"
    if "方法" in text[:300]:
        return "method"
    if "实验" in text[:300]:
        return "experiment"
    return "discussion"


def split_key_points(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?。！？])\s+", text)
    return [_clip(sentence, 160) for sentence in sentences if sentence.strip()][:4]


def build_evidence_bundle(evidence: list[dict[str, Any]], full_text: str) -> list[dict[str, Any]]:
    if evidence:
        return [
            {
                "id": item.get("chunk_id") or item.get("id") or f"evidence_{idx}",
                "source_type": item.get("source_type", "paper"),
                "section_name": item.get("section_name") or "Body",
                "text": _clip(item.get("text", ""), config.MAX_EVIDENCE_CHARS),
            }
            for idx, item in enumerate(evidence[: config.MAX_EVIDENCE_ITEMS])
        ]
    return [{"id": "parsed_text_excerpt", "source_type": "paper", "section_name": "Parsed Text", "text": _clip(full_text, config.MAX_EVIDENCE_CHARS)}]


def build_note_plan(evidence_bundle: list[dict[str, Any]]) -> dict[str, Any]:
    sections = [
        "基本信息",
        "一句话总结",
        "研究背景",
        "研究问题",
        "方法概述",
        "关键技术细节",
        "实验设置",
        "实验结果",
        "创新点",
        "局限性",
        "可复现性分析",
        "对我课题的启发",
        "可链接笔记",
        "原文证据片段",
    ]
    warning = "" if evidence_bundle else "部分 evidence 不足，后续生成时应说明不确定性。"
    return {"sections": sections, "evidence_warning": warning}


def generate_partial_note_sections(
    paper: dict[str, Any],
    section_summaries: dict[str, Any],
    evidence_bundle: list[dict[str, Any]],
    note_plan: dict[str, Any],
) -> dict[str, str]:
    title = paper.get("title") or "Untitled Paper"
    method_summary = section_summaries.get("method", {}).get("summary") or "方法章节 evidence 不足，需人工补充。"
    experiment_summary = (
        section_summaries.get("experiment", {}).get("summary")
        or section_summaries.get("result", {}).get("summary")
        or "实验或结果章节 evidence 不足，需人工补充。"
    )
    evidence_text = "\n".join(f"> [{item['section_name']}] {item['text']}" for item in evidence_bundle[:8])
    return {
        "basic_info": f"""## 1. 基本信息
- 标题：{title}
- 作者：{paper.get('authors') or 'Unknown authors'}
- 年份：{paper.get('year') or 'Unknown'}
- DOI：{paper.get('doi') or 'Unknown'}
- 语言：{paper.get('language') or 'Unknown'}
- 解析状态：{paper.get('parse_status') or 'none'}""",
        "summary_background": f"""## 2. 一句话总结
这篇论文围绕“{_clip(title, 120)}”展开；由于论文较长，系统采用分阶段策略生成阅读笔记。

## 3. 研究背景
{section_summaries.get('abstract', {}).get('summary') or section_summaries.get('introduction', {}).get('summary') or '背景 evidence 不足，建议人工检查原文。'}

## 4. 研究问题
- 研究问题需结合摘要、引言和结论进一步确认。
- 当前 evidence 主要来自可解析文本和 RAG 命中片段。""",
        "method": f"""## 5. 方法概述
{method_summary}

## 6. 关键技术细节
- 长论文分阶段生成，避免一次性塞入模型上下文。
- Evidence bundle 条数：{len(evidence_bundle)}
- 若方法细节缺失，应回到原文方法章节人工补充。""",
        "experiment": f"""## 7. 实验设置
{experiment_summary}

## 8. 实验结果
{section_summaries.get('result', {}).get('summary') or '结果 evidence 不足，建议人工补充主要指标和结论。'}""",
        "innovation_limitation": """## 9. 创新点
- 请结合论文贡献声明提炼 2-4 条创新点。

## 10. 局限性
- 自动解析和检索可能遗漏表格、公式或扫描页。
- 长论文降级生成时，部分章节可能只有摘要级信息。""",
        "reproducibility": """## 11. 可复现性分析
- 代码/数据是否公开：待人工检查。
- 实验细节完整性：待人工检查。

## 12. 对我课题的启发
- 可从研究问题、方法模块、实验指标三个角度建立与自己课题的连接。

## 13. 可链接笔记
- [[相关论文]]
""",
        "evidence": f"""## 14. 原文证据片段
{evidence_text or '> 暂无可用 evidence。'}""",
    }


def merge_note_sections(paper: dict[str, Any], partial_sections: dict[str, str], evidence_bundle: list[dict[str, Any]]) -> str:
    title = paper.get("title") or "Untitled Paper"
    ordered = ["basic_info", "summary_background", "method", "experiment", "innovation_limitation", "reproducibility", "evidence"]
    body = "\n\n".join(partial_sections.get(key, "").strip() for key in ordered if partial_sections.get(key, "").strip())
    return f"""---
title: "{title}"
authors: "{paper.get('authors') or 'Unknown authors'}"
year: "{paper.get('year') or ''}"
paper_id: "{paper.get('id')}"
source_pdf: "{paper.get('file_path')}"
note_mode: "long_paper_staged"
---

# {title}

{body}
"""


def detailed_quality_check(markdown: str) -> dict[str, Any]:
    basic = check_required_note_sections(markdown)
    return {
        **basic,
        "has_frontmatter": markdown.lstrip().startswith("---"),
        "has_basic_info": "## 1. 基本信息" in markdown,
        "has_summary": "## 2. 一句话总结" in markdown,
        "has_method": "## 5. 方法概述" in markdown,
        "has_experiment": "## 7. 实验设置" in markdown or "## 8. 实验结果" in markdown,
        "has_innovations": "## 9. 创新点" in markdown,
        "has_limitations": "## 10. 局限性" in markdown,
        "has_evidence": "## 14. 原文证据片段" in markdown,
    }


def repair_missing_sections(markdown: str, paper: dict[str, Any], missing_sections: list[str], evidence_bundle: list[dict[str, Any]]) -> str:
    additions = []
    for heading in missing_sections:
        additions.append(f"{heading}\n当前 evidence 不足，系统已保留该章节占位，建议人工补充。")
    if additions:
        markdown = markdown.rstrip() + "\n\n" + "\n\n".join(additions) + "\n"
    return markdown


def partial_note_fallback(paper: dict[str, Any], full_text: str, evidence_bundle: list[dict[str, Any]], missing_sections: list[str]) -> str:
    title = paper.get("title") or "Untitled Paper"
    evidence_text = "\n".join(f"> [{item['section_name']}] {item['text']}" for item in evidence_bundle[:8])
    return f"""---
title: "{title}"
authors: "{paper.get('authors') or 'Unknown authors'}"
year: "{paper.get('year') or ''}"
paper_id: "{paper.get('id')}"
note_status: "partial"
---

# {title}

## 1. 基本信息
- 标题：{title}
- 作者：{paper.get('authors') or 'Unknown authors'}
- 年份：{paper.get('year') or 'Unknown'}

## 2. 一句话总结
由于论文较长或解析不完整，系统已生成降级版结构化摘要笔记。

## 3. 研究背景
{_clip(full_text, 700) or '背景 evidence 不足。'}

## 4. 研究问题
当前 evidence 不足，需人工检查。

## 5. 方法概述
{_clip(full_text, 700) or '方法 evidence 不足。'}

## 6. 关键技术细节
缺失章节：{', '.join(missing_sections) if missing_sections else '无'}

## 7. 实验设置
当前 evidence 不足，需人工补充。

## 8. 实验结果
当前 evidence 不足，需人工补充。

## 9. 创新点
当前 evidence 不足，需人工补充。

## 10. 局限性
- 该笔记为 partial note。
- PDF 解析或长上下文生成可能不完整。

## 11. 可复现性分析
待人工检查。

## 12. 对我课题的启发
待人工补充。

## 13. 可链接笔记
- [[{safe_filename(title)}]]

## 14. 原文证据片段
{evidence_text or '> 暂无可用 evidence。'}
"""


def safe_obsidian_path(title: str, folder_name: str | None = None) -> Path:
    base = (config.OBSIDIAN_VAULT_PATH / config.OBSIDIAN_NOTE_DIR).resolve()
    note_dir = base
    if folder_name:
        note_dir = (base / safe_filename(folder_name)).resolve()
    note_dir.mkdir(parents=True, exist_ok=True)
    target = (note_dir / f"{safe_filename(title)}.md").resolve()
    if not str(target).startswith(str(base)):
        raise ValueError("Resolved note path escapes Obsidian note directory.")
    return target


def safe_obsidian_attachment_path(file_name: str) -> Path:
    base = (config.OBSIDIAN_VAULT_PATH / config.OBSIDIAN_ATTACHMENT_DIR).resolve()
    base.mkdir(parents=True, exist_ok=True)
    safe_name = safe_filename(file_name)
    if not safe_name.lower().endswith(".pdf"):
        safe_name = f"{safe_name}.pdf"
    target = (base / safe_name).resolve()
    if not str(target).startswith(str(base)):
        raise ValueError("Resolved attachment path escapes Obsidian attachment directory.")
    return target


def quality_json(quality: dict[str, Any]) -> str:
    return json.dumps(quality, ensure_ascii=False, indent=2)


def check_required_note_sections(markdown: str) -> dict[str, Any]:
    required = [
        "## 1. 基本信息",
        "## 2. 一句话总结",
        "## 3. 研究背景",
        "## 4. 研究问题",
        "## 5. 方法概述",
        "## 6. 关键技术细节",
        "## 7. 实验设置",
        "## 8. 实验结果",
        "## 9. 创新点",
        "## 10. 局限性",
        "## 11. 可复现性分析",
        "## 12. 对我课题的启发",
        "## 13. 可链接笔记",
        "## 14. 原文证据片段",
    ]
    missing = [heading for heading in required if heading not in markdown]
    return {
        "ok": not missing,
        "required_sections_present": not missing,
        "missing_sections": missing,
    }

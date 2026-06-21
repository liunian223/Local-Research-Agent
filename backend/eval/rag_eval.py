from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from adaptive_rag.adaptive_retriever import adaptive_retrieve
from database import connect, rows_to_dicts


def load_cases(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return [{"id": "missing_eval_file", "skip_reason": f"eval_file_not_found:{path}"}]
    cases: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            cases.append(json.loads(line))
        except json.JSONDecodeError as exc:
            cases.append({"id": f"line_{line_number}", "skip_reason": f"invalid_json:{exc.msg}"})
    return cases or [{"id": "empty_eval_file", "skip_reason": "no_eval_cases"}]


def evaluate_case(conn: Any, case: dict[str, Any], top_k: int) -> dict[str, Any]:
    case_id = case.get("id") or "unknown"
    if case.get("skip_reason"):
        return {"id": case_id, "status": "skipped", "skip_reason": case["skip_reason"]}

    paper_id = case.get("paper_id") or ""
    if paper_id:
        row = conn.execute("SELECT id FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if row is None:
            return {"id": case_id, "status": "skipped", "skip_reason": f"paper_id_not_found:{paper_id}"}
    else:
        row = conn.execute("SELECT id FROM papers LIMIT 1").fetchone()
        if row is None:
            return {"id": case_id, "status": "skipped", "skip_reason": "no_papers_in_library"}

    query = case.get("query") or ""
    if not query:
        return {"id": case_id, "status": "skipped", "skip_reason": "missing_query"}

    scope = case.get("scope") or "paper_only"
    evidence, meta = adaptive_retrieve(conn, scope, paper_id or None, query, top_k)
    evidence = evidence[:top_k]
    relevance = [_item_relevance(item, case) for item in evidence]
    first_rank = next((idx + 1 for idx, item in enumerate(relevance) if item["is_relevant"]), None)

    return {
        "id": case_id,
        "status": "ok",
        "query": query,
        "scope": scope,
        "paper_id": paper_id,
        "retrieved_count": len(evidence),
        "recall@3": _recall_at(evidence[:3], case),
        "recall@5": _recall_at(evidence[:5], case),
        "mrr": round(1 / first_rank, 4) if first_rank else 0.0,
        "evidence_hit": bool(first_rank),
        "first_relevant_rank": first_rank,
        "relevance": relevance,
        "top_evidence_section": _top_evidence_value(evidence, "section_name") or _top_evidence_value(evidence, "section_path"),
        "top_evidence_score": _top_evidence_value(evidence, "score"),
        "actual_backend": meta.get("backend"),
        "selected_mode": meta.get("retrieval_mode"),
        "fallback_reason": meta.get("fallback_reason") or "",
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [item for item in results if item.get("status") == "ok"]
    return {
        "case_count": len(results),
        "ok_count": len(ok),
        "skipped_count": len(results) - len(ok),
        "recall@3": _avg(ok, "recall@3"),
        "recall@5": _avg(ok, "recall@5"),
        "mrr": _avg(ok, "mrr"),
        "evidence_hit_rate": _avg([{"hit": 1.0 if item.get("evidence_hit") else 0.0} for item in ok], "hit"),
    }


def write_markdown_report(report_path: Path, summary: dict[str, Any], results: list[dict[str, Any]], eval_file: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    title = "# RAG Evaluation Report"
    if summary["ok_count"] == 0:
        title = "# RAG Evaluation Report - 未产生有效指标"
    lines = [
        title,
        "",
        f"- Eval file: `{eval_file}`",
        f"- Cases: {summary['case_count']}",
        f"- Runnable cases: {summary['ok_count']}",
        f"- Skipped cases: {summary['skipped_count']}",
        "",
    ]
    if summary["ok_count"] == 0:
        lines.extend(
            [
                "## Status",
                "",
                "Not enough local data to compute retrieval metrics. Import papers and replace example `paper_id` values with real IDs, then rerun this script.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "## Metrics",
                "",
                f"- Recall@3: {summary['recall@3']}",
                f"- Recall@5: {summary['recall@5']}",
                f"- MRR: {summary['mrr']}",
                f"- Evidence Hit Rate: {summary['evidence_hit_rate']}",
                "",
            ]
        )
    ok_results = [item for item in results if item.get("status") == "ok"]
    skipped_results = [item for item in results if item.get("status") != "ok"]
    lines.extend(["## Cases", ""])
    for item in ok_results:
        lines.extend(
            [
                f"### {item['id']}",
                "",
                f"- Query: {item.get('query') or ''}",
                f"- Paper ID: `{item.get('paper_id') or ''}`",
                f"- Hit: {item.get('evidence_hit')}",
                f"- First relevant rank: {item.get('first_relevant_rank') or 'none'}",
                f"- Recall@3: {item.get('recall@3')}",
                f"- Recall@5: {item.get('recall@5')}",
                f"- MRR: {item.get('mrr')}",
                f"- Top evidence section: {item.get('top_evidence_section') or '-'}",
                f"- Top evidence score: {item.get('top_evidence_score') if item.get('top_evidence_score') is not None else '-'}",
                "",
            ]
        )
    lines.extend(["## Skipped Cases", ""])
    if skipped_results:
        for item in skipped_results:
            lines.append(f"- `{item.get('id')}`: {item.get('skip_reason')}")
    else:
        lines.append("No skipped cases.")
    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")


def list_papers(conn: Any, limit: int = 50) -> list[dict[str, Any]]:
    return rows_to_dicts(
        conn.execute(
            """
            SELECT id, title, authors, parse_status, vector_status
            FROM papers
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    )


def generate_local_eval_set(conn: Any, output_path: Path, cases_per_paper: int = 3) -> list[dict[str, Any]]:
    papers = list_papers(conn, limit=20)
    cases: list[dict[str, Any]] = []
    for paper in papers:
        chunks = rows_to_dicts(
            conn.execute(
                """
                SELECT id, section_name, section_path, source_type, text, chunk_role, is_abstract
                FROM paper_chunks
                WHERE paper_id = ? AND COALESCE(text, '') <> ''
                ORDER BY is_abstract DESC, chunk_index ASC
                LIMIT 60
                """,
                (paper["id"],),
            ).fetchall()
        )
        for index, chunk in enumerate(_select_eval_chunks(chunks, cases_per_paper), start=1):
            section = chunk.get("section_name") or chunk.get("section_path") or "Body"
            keyword = _keyword_from_text(chunk.get("text") or "")
            source_type = chunk.get("source_type") or "text"
            case = {
                "id": f"{paper['id']}_{index}",
                "scope": "paper_only",
                "paper_id": paper["id"],
                "query": _query_for_section(section, keyword),
                "gold_chunk_ids": [chunk["id"]],
                "gold_sections": [section],
                "gold_keywords": [keyword] if keyword else [],
            }
            if source_type not in {"text", "section_summary"}:
                case["gold_evidence_types"] = [source_type]
            cases.append(case)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if cases:
        output_path.write_text("\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n", encoding="utf-8")
    else:
        output_path.write_text("", encoding="utf-8")
    return cases


def _recall_at(evidence: list[dict[str, Any]], case: dict[str, Any]) -> float | None:
    signals = _gold_signals(case)
    if not signals:
        return None
    hit_count = 0
    for signal_type, expected in signals:
        if any(_matches_signal(item, signal_type, expected) for item in evidence):
            hit_count += 1
    return round(hit_count / len(signals), 4)


def _item_relevance(item: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    hits = [f"{signal_type}:{expected}" for signal_type, expected in _gold_signals(case) if _matches_signal(item, signal_type, expected)]
    return {
        "chunk_id": item.get("chunk_id") or item.get("id") or "",
        "section": item.get("section_name") or item.get("section_path") or "",
        "source_type": item.get("source_type") or "",
        "score": item.get("score"),
        "is_relevant": bool(hits),
        "hits": hits,
    }


def _select_eval_chunks(chunks: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    preferred: list[dict[str, Any]] = []
    section_tokens = ["abstract", "intro", "method", "approach", "encoding", "framework", "experiment", "result"]
    for token in section_tokens:
        match = next((chunk for chunk in chunks if token in f"{chunk.get('section_name', '')} {chunk.get('section_path', '')}".lower() and chunk not in preferred), None)
        if match:
            preferred.append(match)
        if len(preferred) >= limit:
            break
    for chunk in chunks:
        if len(preferred) >= limit:
            break
        if chunk not in preferred:
            preferred.append(chunk)
    return preferred[:limit]


def _query_for_section(section: str, keyword: str) -> str:
    section_lower = section.lower()
    if "abstract" in section_lower:
        return f"What is the paper about and how does it mention {keyword or 'the main contribution'}?"
    if "method" in section_lower or "approach" in section_lower or "encoding" in section_lower:
        return f"What method or approach does the paper use for {keyword or 'the system'}?"
    if "experiment" in section_lower or "result" in section_lower:
        return f"What experiments or results are reported about {keyword or 'performance'}?"
    return f"What does the paper say about {keyword or section}?"


def _keyword_from_text(text: str) -> str:
    if "\n\n" in text:
        text = text.split("\n\n", 1)[1]
    words = [word.lower().strip("-") for word in re.findall(r"[A-Za-z][A-Za-z-]{4,}", text)]
    stop = {
        "paper",
        "section",
        "source",
        "chunk",
        "role",
        "abstract",
        "introduction",
        "encodingapproach",
        "frameworkimplementation",
        "pages",
        "figure",
        "table",
        "their",
        "which",
        "these",
        "those",
        "using",
        "therefore",
    }
    return next((word for word in words if word not in stop and not word.startswith("paper:")), "")


def _top_evidence_value(evidence: list[dict[str, Any]], key: str) -> Any:
    if not evidence:
        return None
    return evidence[0].get(key)


def _gold_signals(case: dict[str, Any]) -> list[tuple[str, str]]:
    signals: list[tuple[str, str]] = []
    for key, signal_type in [
        ("gold_chunk_ids", "chunk_id"),
        ("gold_sections", "section"),
        ("gold_keywords", "keyword"),
        ("gold_evidence_types", "source_type"),
    ]:
        signals.extend((signal_type, str(value).lower()) for value in case.get(key) or [] if str(value).strip())
    return signals


def _matches_signal(item: dict[str, Any], signal_type: str, expected: str) -> bool:
    if signal_type == "chunk_id":
        return expected in {str(item.get("chunk_id") or "").lower(), str(item.get("id") or "").lower()}
    if signal_type == "section":
        return expected in f"{item.get('section_name', '')} {item.get('section_path', '')}".lower()
    if signal_type == "keyword":
        return expected in str(item.get("text") or item.get("content") or "").lower()
    if signal_type == "source_type":
        return expected == str(item.get("source_type") or "").lower()
    return False


def _avg(items: list[dict[str, Any]], key: str) -> float | None:
    values = [float(item[key]) for item in items if isinstance(item.get(key), (int, float))]
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local RAG retrieval evaluation.")
    subparsers = parser.add_subparsers(dest="command")

    list_parser = subparsers.add_parser("list-papers", description="List local papers available for RAG evaluation.")
    list_parser.add_argument("--limit", type=int, default=50)

    gen_parser = subparsers.add_parser("generate-local", description="Generate backend/eval/rag_eval_set.local.jsonl from local papers.")
    gen_parser.add_argument("--output", type=Path, default=BACKEND_DIR / "eval" / "rag_eval_set.local.jsonl")
    gen_parser.add_argument("--cases-per-paper", type=int, default=3)

    run_parser = subparsers.add_parser("run", description="Run local RAG retrieval evaluation.")
    run_parser.add_argument("--eval-file", type=Path, default=BACKEND_DIR / "eval" / "rag_eval_set.local.jsonl")
    run_parser.add_argument("--top-k", type=int, default=10)
    run_parser.add_argument("--report-file", type=Path, default=ROOT_DIR / "docs" / "rag_eval_report.md")

    parser.set_defaults(command="run")
    argv = sys.argv[1:]
    if not argv:
        argv = ["run"]
    elif argv[0] not in {"list-papers", "generate-local", "run", "-h", "--help"}:
        argv = ["run", *argv]
    args = parser.parse_args(argv)

    with connect() as conn:
        if args.command == "list-papers":
            papers = list_papers(conn, args.limit)
            if not papers:
                print("No papers found in the local database. Import PDFs before running RAG eval.")
            else:
                print(json.dumps({"paper_count": len(papers), "papers": papers}, ensure_ascii=False, indent=2))
            return
        if args.command == "generate-local":
            cases = generate_local_eval_set(conn, args.output, args.cases_per_paper)
            if not cases:
                print(f"No papers/chunks found. Created empty eval set at {args.output}. Import PDFs before running RAG eval.")
            else:
                print(json.dumps({"case_count": len(cases), "output": str(args.output), "cases": cases}, ensure_ascii=False, indent=2))
            return

        cases = load_cases(args.eval_file)
        results = [evaluate_case(conn, case, args.top_k) for case in cases]
    summary = summarize(results)
    write_markdown_report(args.report_file, summary, results, args.eval_file)
    print(json.dumps({"summary": summary, "results": results, "report_file": str(args.report_file)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

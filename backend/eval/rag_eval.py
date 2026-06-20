from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from adaptive_rag.adaptive_retriever import adaptive_retrieve
from database import connect


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            cases.append(json.loads(line))
        except json.JSONDecodeError as exc:
            cases.append({"id": f"line_{line_number}", "skip_reason": f"invalid_json:{exc.msg}"})
    return cases


def evaluate_case(conn: Any, case: dict[str, Any], top_k: int) -> dict[str, Any]:
    case_id = case.get("id") or "unknown"
    paper_id = case.get("paper_id") or ""
    if case.get("skip_reason"):
        return {"id": case_id, "status": "skipped", "skip_reason": case["skip_reason"]}
    if paper_id:
        row = conn.execute("SELECT id FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if row is None:
            return {"id": case_id, "status": "skipped", "skip_reason": f"paper_id_not_found:{paper_id}"}

    scope = case.get("scope") or "paper_only"
    query = case.get("query") or ""
    evidence, meta = adaptive_retrieve(conn, scope, paper_id or None, query, top_k)
    evidence = evidence[:top_k]
    text_blob = "\n".join(str(item.get("text") or "") for item in evidence).lower()
    section_blob = "\n".join(f"{item.get('section_name', '')} {item.get('section_path', '')}" for item in evidence).lower()
    evidence_types = {str(item.get("source_type") or "text") for item in evidence}

    gold_sections = [str(item).lower() for item in case.get("gold_sections") or []]
    gold_keywords = [str(item).lower() for item in case.get("gold_keywords") or []]
    gold_types = {str(item) for item in case.get("gold_evidence_types") or []}

    section_hits = [section for section in gold_sections if section in section_blob]
    keyword_hits = [keyword for keyword in gold_keywords if keyword in text_blob]
    type_hits = sorted(gold_types & evidence_types)

    return {
        "id": case_id,
        "status": "ok",
        "query": query,
        "scope": scope,
        "paper_id": paper_id,
        "section_hit@k": _ratio(len(section_hits), len(gold_sections)),
        "keyword_hit@k": _ratio(len(keyword_hits), len(gold_keywords)),
        "evidence_type_hit@k": _ratio(len(type_hits), len(gold_types)),
        "section_hits": section_hits,
        "keyword_hits": keyword_hits,
        "evidence_type_hits": type_hits,
        "retrieved_count": len(evidence),
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
        "avg_section_hit@k": _avg(ok, "section_hit@k"),
        "avg_keyword_hit@k": _avg(ok, "keyword_hit@k"),
        "avg_evidence_type_hit@k": _avg(ok, "evidence_type_hit@k"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a minimal local RAG retrieval evaluation.")
    parser.add_argument("--eval-file", required=True, type=Path)
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()

    cases = load_cases(args.eval_file)
    with connect() as conn:
        results = [evaluate_case(conn, case, args.top_k) for case in cases]
    print(json.dumps({"summary": summarize(results), "results": results}, ensure_ascii=False, indent=2))


def _ratio(hit_count: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(hit_count / total, 4)


def _avg(items: list[dict[str, Any]], key: str) -> float | None:
    values = [float(item[key]) for item in items if isinstance(item.get(key), (int, float))]
    if not values:
        return None
    return round(sum(values) / len(values), 4)


if __name__ == "__main__":
    main()

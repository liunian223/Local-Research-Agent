# RAG Optimization Report

Date: 2026-06-18

## Local Investigation Summary

The project is using Adaptive Layout-Aware RAG v2 rather than naive PDF chunk top-k retrieval.

Key code paths:

- Chat retrieval entry: `backend/app.py::retrieve_evidence`
- Adaptive retrieval: `backend/adaptive_rag/adaptive_retriever.py::adaptive_retrieve`
- Hybrid candidate collection: `backend/adaptive_rag/hybrid_retriever.py::collect_candidates`
- Rule reranking: `backend/adaptive_rag/reranker.py::rerank`
- Semantic layout chunks: `backend/semantic_chunker.py::build_semantic_chunks`
- Structured evidence and RAG pipeline summary: `backend/structured_retriever.py`
- Vector backend initialization: `backend/vector_store.py::VectorStore.__init__`
- Execution payload assembly: `backend/harness/execution_builder.py`
- Execution panel: `frontend/src/components/ExecutionPanel.vue`

Findings:

- Chroma initialization happens in `backend/vector_store.py`.
- The configured backend is `chroma`, but the current runtime falls back to `local_keyword`.
- Current local check shows `chromadb_available=False` and `sentence_transformers_available=False`.
- The Chroma persist directory exists and is writable: `data/vector_store`.
- Before this change, Chroma initialization failures were swallowed without preserving the exception reason.
- Table, figure, and page evidence can enter the final prompt through `evidence_bundle` and `format_grouped_evidence_for_prompt`.
- Abstract downweight affects reranking, final evidence selection, and evidence bundle composition through abstract limiting.

Current backend diagnostic evidence:

```json
{
  "configured_backend": "chroma",
  "actual_backend": "local_keyword",
  "embedding_provider": "local",
  "embedding_model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
  "fallback_reason": "chroma_init_failed:ModuleNotFoundError",
  "exception_class": "ModuleNotFoundError",
  "exception_message": "No module named 'chromadb'"
}
```

## Modified Files

- `backend/vector_store.py`
- `backend/structured_retriever.py`
- `backend/adaptive_rag/adaptive_retriever.py`
- `backend/adaptive_rag/reranker.py`
- `backend/requirements.txt`
- `backend/eval/__init__.py`
- `backend/eval/rag_eval.py`
- `backend/eval/rag_eval_set.example.jsonl`
- `backend/tests/test_vector_store_status.py`
- `backend/tests/test_rag_adaptive_retriever.py`
- `backend/tests/test_rag_complex_retrieval.py`
- `backend/tests/test_rag_execution_payload.py`
- `frontend/src/types.ts`
- `frontend/src/components/ExecutionPanel.vue`
- `docs/rag_optimization_report.md`

Note: the worktree already contained unrelated modified/deleted files before this task. They were not reverted or folded into this RAG change.

## Change Rationale

### Vector backend observability

`VectorStore` now records:

- configured backend
- actual backend
- embedding provider
- embedding model
- Chroma persist directory
- persist directory existence and writability
- fallback flag
- fallback reason
- exception class
- exception message

This keeps local keyword fallback behavior intact while making Chroma failures visible.

### Execution payload fields

`execution.rag_pipeline` now includes:

- `backend_config`
- `backend_status`

`execution.retrieval` now includes:

- enriched `query_analysis` with `query_type`, `is_complex`, and `scope`
- enriched `retrieval_plan` with `mode`, `top_k`, `candidate_top_k`, and `reason`
- `backend_diagnostics`
- `fallback_reason`
- `retrieval_error`
- `evidence_stats`
- reranker metadata with `weight_rules` and `score_breakdown_available`

Each final evidence item from adaptive rerank now carries:

- `final_score`
- `score_breakdown.base_score`
- `score_breakdown.lexical_hit_score`
- `score_breakdown.section_bonus`
- `score_breakdown.table_bonus`
- `score_breakdown.figure_bonus`
- `score_breakdown.page_bonus`
- `score_breakdown.section_summary_bonus`
- `score_breakdown.retrieval_weight`
- `score_breakdown.abstract_penalty`
- `score_breakdown.final_score`

### Reranker optimization

The reranker remains rule-based as `rule_weighted_v1`; no LLM reranking was introduced.

Weight rules added:

- Method queries boost method / approach / model sections.
- Experiment and result queries boost experiment / evaluation / result sections.
- Table queries boost table evidence.
- Figure queries boost figure evidence.
- Summary queries boost section summaries and conclusion/discussion sections.
- Comparison, reproduction, and critique queries boost method, experiment, and result sections.
- Abstract evidence still receives abstract policy penalties and should not replace body method / experiment / result evidence.

### Requirements

`backend/requirements.txt` already listed `chromadb` and `sentence-transformers`; `numpy` is now explicit.

### Frontend execution panel

The existing execution panel now shows:

- actual backend
- fallback reason

The raw Structured RAG JSON also exposes the full backend status, retrieval plan, evidence stats, and score breakdown fields.

## Chroma Fallback Status

Chroma fallback observability is fixed.

Chroma itself is not active in the current environment because `chromadb` and `sentence_transformers` are not importable by the Python interpreter used in this workspace. The code path remains:

- use Chroma when it initializes successfully
- automatically fall back to `local_keyword` when Chroma is unavailable
- expose the fallback reason in execution output

No dependency installation was performed.

## Eval Harness

New files:

- `backend/eval/rag_eval.py`
- `backend/eval/rag_eval_set.example.jsonl`

Usage:

```bash
python -m backend.eval.rag_eval --eval-file backend/eval/rag_eval_set.example.jsonl --top-k 10
```

Metrics:

- `section_hit@k`
- `keyword_hit@k`
- `evidence_type_hit@k`
- `retrieved_count`
- `actual_backend`
- `selected_mode`

If a `paper_id` does not exist, the case is skipped with a `skip_reason` instead of failing.

Example verification result with the placeholder eval set:

```json
{
  "case_count": 3,
  "ok_count": 0,
  "skipped_count": 3
}
```

## Verification

Commands run:

```bash
python -m pytest backend/tests/test_vector_store_status.py backend/tests/test_rag_complex_retrieval.py backend/tests/test_rag_adaptive_retriever.py backend/tests/test_rag_execution_payload.py -q
```

Result:

```text
9 passed
```

```bash
python -m backend.eval.rag_eval --eval-file backend/eval/rag_eval_set.example.jsonl --top-k 10
```

Result:

```text
3 cases skipped because the example paper_id placeholder does not exist
```

```bash
python -m pytest backend/tests -q
```

Result:

```text
47 passed
```

```bash
npm run build
```

Result:

```text
vue-tsc --noEmit and vite build completed successfully
```

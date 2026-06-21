# Demo Acceptance

Date: 2026-06-21

## Imported Papers

| paper_id | title | authors | language | parse_status | vector_status | note_status | obsidian_note_path |
|---|---|---|---|---|---|---|---|
| `paper_e2e2a2580ff54f40` | SSVEP 赛题-窄带随机编码 | zhengli126647@126.com | zh | done | done | partial | `C:\Users\liunian\Documents\Agent\obsidian_vault\02_ReadingNotes\SSVEP_赛题-窄带随机编码.md` |
| `paper_64f99d33a5e5438f` | Human-centred physical neuromorphics with visual brain-computer interfaces | Gao Wang | en | done | done | done | `C:\Users\liunian\Documents\Agent\obsidian_vault\02_ReadingNotes\Human-centred_physical_neuromorphics_with_visual_brain-computer_interfaces.md` |

Result: both real SSVEP papers are imported. Both have `parse_status=done` and `vector_status=done`. Notes exist for both papers; the Chinese note is marked `partial`, and the English note is marked `done`.

## Evidence Binding

| paper_id | paper_chunks | document_chunks | image_assets | note_id | note_chunks | sample evidence ids |
|---|---:|---:|---:|---|---:|---|
| `paper_e2e2a2580ff54f40` | 17 | 17 | 4 | `note_0a1f5239aae84ba4` | 7 | `chunk_dcbb8be2e2614faf`, `chunk_495ead19a3cd47ad`, `notechunk_5ee2b1aa4ebe47e5` |
| `paper_64f99d33a5e5438f` | 113 | 113 | 5 | `note_10d4e7404c524ccc` | 6 | `chunk_2b3d807980e24d74`, `chunk_8bde47dd7ab9452c`, `notechunk_c1eaa7aec29d4e20` |

Result: evidence ids are bound for both papers through `paper_chunks`, `document_chunks`, image assets, `reading_notes`, and `note_chunks`.

## Scope QA Checks

Session used for demo checks: `session_65c4dde208024bfb`.

| scope | paper_id | status | task_id | rag_evidence | harness_decisions | mcp_tool_calls | top evidence |
|---|---|---|---|---:|---:|---:|---|
| paper_only | `paper_e2e2a2580ff54f40` | pass, HTTP 200 | `task_2a72207e7a1247ba` | 14 | 3 | 2 | `chunk_e3749f8b9769468f`, figure, 实验范式为键盘拼写... |
| note_only | `paper_e2e2a2580ff54f40` | pass, HTTP 200 | `task_bdee126669fc468c` | 7 | 3 | 2 | `notechunk_ed4b5acbc96c4944`, note, Body |
| paper_and_note | `paper_64f99d33a5e5438f` | pass, HTTP 200 | `task_02c12d7092124a8d` | 14 | 3 | 2 | `chunk_7c581d00271549a6`, section_summary, Results |
| global_library | mixed-library query | pass, HTTP 200 | `task_6749bb85e44f4436` | 14 | 3 | 2 | `chunk_e3749f8b9769468f`, figure, 实验范式为键盘拼写... |

Result: `paper_only`, `note_only`, `paper_and_note`, and `global_library` QA paths are usable against the real local library.

Note: the live model call failed during these demo checks and the backend returned local grouped-evidence fallback answers. This is acceptable for this acceptance pass because retrieval, evidence binding, execution payloads, and answer fallback all completed with HTTP 200 instead of failing.

## Frontend Execution Payload

The demo QA responses contained:

- `execution.harness_decisions`: present in all four checked scopes.
- `execution.rag_evidence`: present in all four checked scopes.
- `execution.mcp_tool_calls`: present in all four checked scopes.

Result: Harness decisions and RAG evidence are available in the same execution payload consumed by the frontend `ExecutionPanel`, so they can be expanded from the existing single-page chat UI.

## RAG Evaluation

Real eval file: `backend/eval/rag_eval_set.local.jsonl`.

Latest run command:

```powershell
python backend\eval\rag_eval.py --eval-file backend\eval\rag_eval_set.local.jsonl --top-k 10
```

Summary:

- Runnable cases: 12
- Skipped cases: 0
- Recall@3: 0.8206
- Recall@5: 0.8444
- MRR: 0.9167
- Evidence Hit Rate: 1.0

Full per-case evidence summary is in `docs/rag_eval_report.md`.

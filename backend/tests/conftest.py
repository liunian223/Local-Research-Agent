from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_ROOT = Path(tempfile.mkdtemp(prefix="local_research_agent_rag_tests_"))
os.environ.setdefault("LOCAL_RESEARCH_AGENT_ENV", "test")
os.environ.setdefault("DATABASE_PATH", str(TEST_ROOT / "test.db"))
os.environ.setdefault("DATA_DIR", str(TEST_ROOT / "data"))
os.environ.setdefault("PAPER_DIR", str(TEST_ROOT / "data" / "papers"))
os.environ.setdefault("PARSED_DIR", str(TEST_ROOT / "data" / "parsed"))
os.environ.setdefault("VECTOR_DIR", str(TEST_ROOT / "data" / "vector_store"))
os.environ.setdefault("OBSIDIAN_VAULT_PATH", str(TEST_ROOT / "vault"))
os.environ.setdefault("VECTOR_BACKEND", "local_keyword")
os.environ.setdefault("TEXT_MODEL_PROVIDER", "local_fallback")
os.environ.setdefault("VISION_MODEL_PROVIDER", "none")
os.environ.setdefault("EMBEDDING_PROVIDER", "local")
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("DEEPSEEK_API_KEY", "")

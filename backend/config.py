import os
from pathlib import Path


PROJECT_NAME = "Local Research Agent"

BACKEND_DIR = Path(__file__).resolve().parent
ROOT_DIR = BACKEND_DIR.parent

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL_CHAT = os.getenv("DEEPSEEK_MODEL_CHAT", "deepseek-v4-flash")
DEEPSEEK_MODEL_NOTE = os.getenv("DEEPSEEK_MODEL_NOTE", "deepseek-v4-pro")
DEEPSEEK_MODEL_JSON = os.getenv("DEEPSEEK_MODEL_JSON", "deepseek-v4-pro")
DEEPSEEK_TIMEOUT_SECONDS = int(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "90"))
DEEPSEEK_MAX_RETRIES = int(os.getenv("DEEPSEEK_MAX_RETRIES", "2"))

DATABASE_PATH = Path(os.getenv("DATABASE_PATH", ROOT_DIR / "data" / "local_research_agent.db"))
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT_DIR / "data"))
PAPER_DIR = Path(os.getenv("PAPER_DIR", DATA_DIR / "papers"))
PARSED_DIR = Path(os.getenv("PARSED_DIR", DATA_DIR / "parsed"))
VECTOR_DIR = Path(os.getenv("VECTOR_DIR", DATA_DIR / "vector_store"))
OBSIDIAN_VAULT_PATH = Path(os.getenv("OBSIDIAN_VAULT_PATH", ROOT_DIR / "obsidian_vault"))
OBSIDIAN_NOTE_DIR = os.getenv("OBSIDIAN_NOTE_DIR", "02_ReadingNotes")
OBSIDIAN_ATTACHMENT_DIR = os.getenv("OBSIDIAN_ATTACHMENT_DIR", "attachments/papers")

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "80"))
ALLOWED_UPLOAD_EXTENSIONS = {".pdf"}

VECTOR_BACKEND = os.getenv("VECTOR_BACKEND", "chroma")
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "8"))
CHUNK_SIZE_ZH = int(os.getenv("CHUNK_SIZE_ZH", "900"))
CHUNK_SIZE_EN = int(os.getenv("CHUNK_SIZE_EN", "900"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "120"))

LONG_PAPER_CHAR_THRESHOLD = int(os.getenv("LONG_PAPER_CHAR_THRESHOLD", "60000"))
LONG_PAPER_CHUNK_THRESHOLD = int(os.getenv("LONG_PAPER_CHUNK_THRESHOLD", "80"))
LONG_PAPER_PAGE_THRESHOLD = int(os.getenv("LONG_PAPER_PAGE_THRESHOLD", "30"))
MAX_CONTEXT_CHARS_PER_LLM_CALL = int(os.getenv("MAX_CONTEXT_CHARS_PER_LLM_CALL", "16000"))
MAX_EVIDENCE_ITEMS = int(os.getenv("MAX_EVIDENCE_ITEMS", "20"))
MAX_EVIDENCE_CHARS = int(os.getenv("MAX_EVIDENCE_CHARS", "1200"))
MAX_NOTE_REPAIR_ROUNDS = int(os.getenv("MAX_NOTE_REPAIR_ROUNDS", "2"))

ENABLE_OCR_FALLBACK = os.getenv("ENABLE_OCR_FALLBACK", "false").lower() == "true"


def ensure_directories() -> None:
    for path in [DATA_DIR, PAPER_DIR, PARSED_DIR, VECTOR_DIR, OBSIDIAN_VAULT_PATH / OBSIDIAN_NOTE_DIR]:
        path.mkdir(parents=True, exist_ok=True)

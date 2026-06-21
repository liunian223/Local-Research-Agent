import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv


PROJECT_NAME = "Local Research Agent"

BACKEND_DIR = Path(__file__).resolve().parent
ROOT_DIR = BACKEND_DIR.parent

ENV_NAME = os.getenv("LOCAL_RESEARCH_AGENT_ENV", "development")
BACKEND_ENV_FILE = BACKEND_DIR / ".env"
_ENV_BEFORE_DOTENV = dict(os.environ)
_BACKEND_ENV_VALUES = dotenv_values(BACKEND_ENV_FILE)

# Prefer the project-local .env over stale shell/user environment variables in
# normal runs. Tests set environment values directly and should keep priority.
load_dotenv(BACKEND_ENV_FILE, override=ENV_NAME != "test")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "codex")
DISABLE_OPENAI_API = os.getenv("DISABLE_OPENAI_API", "true").lower() == "true"
TEXT_MODEL_PROVIDER = os.getenv("TEXT_MODEL_PROVIDER", LLM_PROVIDER)
VISION_MODEL_PROVIDER = os.getenv("VISION_MODEL_PROVIDER", LLM_PROVIDER)
if DISABLE_OPENAI_API:
    if LLM_PROVIDER.lower() in {"codex", "codex_cli", "codex_runtime"} and TEXT_MODEL_PROVIDER.lower() == "openai":
        TEXT_MODEL_PROVIDER = LLM_PROVIDER
    if LLM_PROVIDER.lower() in {"codex", "codex_cli", "codex_runtime"} and VISION_MODEL_PROVIDER.lower() == "openai":
        VISION_MODEL_PROVIDER = LLM_PROVIDER
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "local")
CODEX_CLI_COMMAND = os.getenv("CODEX_CLI_COMMAND", "codex")
CODEX_MODEL_TEXT = os.getenv("CODEX_MODEL_TEXT", os.getenv("CODEX_CLI_MODEL", ""))
CODEX_MODEL_VISION = os.getenv("CODEX_MODEL_VISION", CODEX_MODEL_TEXT)
CODEX_SANDBOX = os.getenv("CODEX_SANDBOX", "read_only")
CODEX_TIMEOUT_SECONDS = int(os.getenv("CODEX_TIMEOUT_SECONDS", os.getenv("CODEX_CLI_TIMEOUT_SECONDS", "180")))
CODEX_MAX_CONCURRENCY = int(os.getenv("CODEX_MAX_CONCURRENCY", "1"))
CODEX_PROBE_TIMEOUT_SECONDS = int(os.getenv("CODEX_PROBE_TIMEOUT_SECONDS", "45"))
CODEX_PROBE_MODEL = os.getenv("CODEX_PROBE_MODEL", "")
CODEX_CLI_MODEL = CODEX_MODEL_TEXT
CODEX_CLI_TIMEOUT_SECONDS = CODEX_TIMEOUT_SECONDS

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_TEXT_MODEL = os.getenv("OPENAI_TEXT_MODEL", "gpt-4o-mini")
OPENAI_JSON_MODEL = os.getenv("OPENAI_JSON_MODEL", "gpt-4o-mini")
OPENAI_NOTE_MODEL = os.getenv("OPENAI_NOTE_MODEL", "gpt-4o-mini")
OPENAI_VISION_MODEL = os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini")
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
OPENAI_EMBEDDING_DIMENSIONS = int(os.getenv("OPENAI_EMBEDDING_DIMENSIONS", "1536"))
OPENAI_TIMEOUT_SECONDS = int(os.getenv("OPENAI_TIMEOUT_SECONDS", "90"))
OPENAI_MAX_RETRIES = int(os.getenv("OPENAI_MAX_RETRIES", "2"))
ENABLE_OPENAI_VISION = os.getenv("ENABLE_OPENAI_VISION", "true").lower() == "true" and not DISABLE_OPENAI_API
MAX_OPENAI_IMAGE_MB = int(os.getenv("MAX_OPENAI_IMAGE_MB", "10"))
OPENAI_STORE_RESPONSES = os.getenv("OPENAI_STORE_RESPONSES", "false").lower() == "true"

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL_CHAT = os.getenv("DEEPSEEK_MODEL_CHAT", "deepseek-chat")
DEEPSEEK_MODEL_NOTE = os.getenv("DEEPSEEK_MODEL_NOTE", "deepseek-chat")
DEEPSEEK_MODEL_JSON = os.getenv("DEEPSEEK_MODEL_JSON", "deepseek-chat")
DEEPSEEK_TIMEOUT_SECONDS = int(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "90"))
DEEPSEEK_MAX_RETRIES = int(os.getenv("DEEPSEEK_MAX_RETRIES", "2"))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_VISION_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-flash")
ENABLE_GEMINI_VISION = os.getenv("ENABLE_GEMINI_VISION", "false").lower() == "true"

DATABASE_PATH = Path(os.getenv("DATABASE_PATH", ROOT_DIR / "data" / "local_research_agent.db"))
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT_DIR / "data"))
PAPER_DIR = Path(os.getenv("PAPER_DIR", DATA_DIR / "papers"))
PARSED_DIR = Path(os.getenv("PARSED_DIR", DATA_DIR / "parsed"))
VECTOR_DIR = Path(os.getenv("VECTOR_DIR", DATA_DIR / "vector_store"))
VISION_DIR = Path(os.getenv("VISION_DIR", DATA_DIR / "vision"))
PDF_IMAGE_DIR = Path(os.getenv("PDF_IMAGE_DIR", VISION_DIR / "pdf_images"))
PDF_RENDERED_PAGE_DIR = Path(os.getenv("PDF_RENDERED_PAGE_DIR", VISION_DIR / "rendered_pages"))
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
MAX_NOTE_IMAGE_ATTACHMENTS = int(os.getenv("MAX_NOTE_IMAGE_ATTACHMENTS", "6"))
PDF_IMAGE_EXTRACT_ENABLED = os.getenv("PDF_IMAGE_EXTRACT_ENABLED", "true").lower() == "true"
PDF_PAGE_RENDER_ENABLED = os.getenv("PDF_PAGE_RENDER_ENABLED", "true").lower() == "true"
PDF_IMAGE_MIN_WIDTH = int(os.getenv("PDF_IMAGE_MIN_WIDTH", "120"))
PDF_IMAGE_MIN_HEIGHT = int(os.getenv("PDF_IMAGE_MIN_HEIGHT", "120"))
PDF_RENDER_DPI = int(os.getenv("PDF_RENDER_DPI", "160"))
MAX_PDF_IMAGES_PER_PAPER = int(os.getenv("MAX_PDF_IMAGES_PER_PAPER", "40"))
MAX_VISION_IMAGES_PER_CALL = int(os.getenv("MAX_VISION_IMAGES_PER_CALL", "4"))

LAYOUT_RAG_PARSER_VERSION = os.getenv("LAYOUT_RAG_PARSER_VERSION", "layout-rag-v1")
SEMANTIC_CHUNK_MAX_CHARS = int(os.getenv("SEMANTIC_CHUNK_MAX_CHARS", "1800"))
SEMANTIC_CHUNK_MIN_CHARS = int(os.getenv("SEMANTIC_CHUNK_MIN_CHARS", "200"))
SEMANTIC_CHUNK_SOFT_OVERLAP = int(os.getenv("SEMANTIC_CHUNK_SOFT_OVERLAP", "120"))

RAG_ADAPTIVE_ENABLED = os.getenv("RAG_ADAPTIVE_ENABLED", "true").lower() == "true"
RAG_QUERY_ANALYZER_USE_LLM = os.getenv("RAG_QUERY_ANALYZER_USE_LLM", "false").lower() == "true"
RAG_ABSTRACT_DETECTION_ENABLED = os.getenv("RAG_ABSTRACT_DETECTION_ENABLED", "true").lower() == "true"
RAG_ABSTRACT_DEFAULT_MODE = os.getenv("RAG_ABSTRACT_DEFAULT_MODE", "downweight")
RAG_ABSTRACT_DOWNWEIGHT_FACTOR = float(os.getenv("RAG_ABSTRACT_DOWNWEIGHT_FACTOR", "0.75"))
RAG_ABSTRACT_MAX_COMPLEX_EVIDENCE = int(os.getenv("RAG_ABSTRACT_MAX_COMPLEX_EVIDENCE", "1"))
RAG_SIMPLE_VECTOR_TOP_K = int(os.getenv("RAG_SIMPLE_VECTOR_TOP_K", "20"))
RAG_SIMPLE_KEYWORD_TOP_K = int(os.getenv("RAG_SIMPLE_KEYWORD_TOP_K", "20"))
RAG_SIMPLE_FINAL_TOP_K = int(os.getenv("RAG_SIMPLE_FINAL_TOP_K", "6"))
RAG_COMPLEX_SECTION_TOP_K = int(os.getenv("RAG_COMPLEX_SECTION_TOP_K", "5"))
RAG_COMPLEX_MAX_EVIDENCE = int(os.getenv("RAG_COMPLEX_MAX_EVIDENCE", "14"))
RAG_COMPLEX_MAX_RETRIEVAL_ROUNDS = int(os.getenv("RAG_COMPLEX_MAX_RETRIEVAL_ROUNDS", "2"))
RAG_RERANKER = os.getenv("RAG_RERANKER", "rule_weighted_v1")
RAG_ENABLE_OPTIONAL_CROSS_ENCODER = os.getenv("RAG_ENABLE_OPTIONAL_CROSS_ENCODER", "false").lower() == "true"

ENABLE_OCR_FALLBACK = os.getenv("ENABLE_OCR_FALLBACK", "false").lower() == "true"


def ensure_directories() -> None:
    for path in [
        DATA_DIR,
        PAPER_DIR,
        PARSED_DIR,
        VECTOR_DIR,
        VISION_DIR,
        PDF_IMAGE_DIR,
        PDF_RENDERED_PAGE_DIR,
        OBSIDIAN_VAULT_PATH / OBSIDIAN_NOTE_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def config_key_source(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        return "missing"
    if name in _ENV_BEFORE_DOTENV:
        return "env"
    if _BACKEND_ENV_VALUES.get(name):
        return "backend_env_file"
    return "env"

CREATE TABLE IF NOT EXISTS folders (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  is_system INTEGER DEFAULT 0,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS papers (
  id TEXT PRIMARY KEY,
  title TEXT,
  authors TEXT,
  year TEXT,
  language TEXT,
  doi TEXT,
  file_path TEXT NOT NULL,
  file_name TEXT,
  file_sha256 TEXT UNIQUE,
  page_count INTEGER DEFAULT 0,
  folder_id TEXT,
  parse_status TEXT DEFAULT 'none',
  vector_status TEXT DEFAULT 'none',
  note_status TEXT DEFAULT 'none',
  obsidian_note_path TEXT,
  metadata_source TEXT,
  metadata_confidence REAL DEFAULT 0.0,
  metadata_warning TEXT,
  parse_warning TEXT,
  created_at TEXT,
  updated_at TEXT,
  FOREIGN KEY(folder_id) REFERENCES folders(id)
);

CREATE INDEX IF NOT EXISTS idx_papers_folder_id ON papers(folder_id);
CREATE INDEX IF NOT EXISTS idx_papers_title ON papers(title);
CREATE INDEX IF NOT EXISTS idx_papers_authors ON papers(authors);

CREATE TABLE IF NOT EXISTS chat_sessions (
  id TEXT PRIMARY KEY,
  title TEXT,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS paper_chunks (
  id TEXT PRIMARY KEY,
  paper_id TEXT NOT NULL,
  section_name TEXT,
  chunk_index INTEGER,
  text TEXT,
  vector_id TEXT,
  source_type TEXT DEFAULT 'text',
  section_id TEXT,
  section_path TEXT,
  page_start INTEGER,
  page_end INTEGER,
  context_prefix TEXT,
  metadata_json TEXT,
  is_abstract INTEGER DEFAULT 0,
  retrieval_weight REAL DEFAULT 1.0,
  chunk_role TEXT DEFAULT '',
  section_role TEXT DEFAULT '',
  created_at TEXT,
  FOREIGN KEY(paper_id) REFERENCES papers(id)
);

CREATE INDEX IF NOT EXISTS idx_paper_chunks_paper_id ON paper_chunks(paper_id);
CREATE INDEX IF NOT EXISTS idx_paper_chunks_section ON paper_chunks(section_name);
CREATE INDEX IF NOT EXISTS idx_paper_chunks_source_type ON paper_chunks(source_type);
CREATE INDEX IF NOT EXISTS idx_paper_chunks_page ON paper_chunks(page_start, page_end);

CREATE TABLE IF NOT EXISTS document_pages (
  id TEXT PRIMARY KEY,
  paper_id TEXT NOT NULL,
  page_number INTEGER,
  width REAL,
  height REAL,
  header_text TEXT,
  footer_text TEXT,
  main_text TEXT,
  metadata_json TEXT,
  created_at TEXT,
  FOREIGN KEY(paper_id) REFERENCES papers(id)
);

CREATE INDEX IF NOT EXISTS idx_document_pages_paper_id ON document_pages(paper_id);
CREATE INDEX IF NOT EXISTS idx_document_pages_page ON document_pages(paper_id, page_number);

CREATE TABLE IF NOT EXISTS document_sections (
  id TEXT PRIMARY KEY,
  paper_id TEXT NOT NULL,
  title TEXT,
  normalized_name TEXT,
  level INTEGER,
  parent_section_id TEXT,
  section_path TEXT,
  page_start INTEGER,
  page_end INTEGER,
  summary TEXT,
  metadata_json TEXT,
  is_abstract INTEGER DEFAULT 0,
  section_role TEXT DEFAULT '',
  detection_confidence REAL DEFAULT 0.0,
  boundary_source TEXT DEFAULT '',
  created_at TEXT,
  FOREIGN KEY(paper_id) REFERENCES papers(id)
);

CREATE INDEX IF NOT EXISTS idx_document_sections_paper_id ON document_sections(paper_id);
CREATE INDEX IF NOT EXISTS idx_document_sections_normalized ON document_sections(normalized_name);

CREATE TABLE IF NOT EXISTS document_blocks (
  id TEXT PRIMARY KEY,
  paper_id TEXT NOT NULL,
  page_number INTEGER,
  block_type TEXT,
  text TEXT,
  bbox_json TEXT,
  section_id TEXT,
  reading_order INTEGER,
  is_header INTEGER DEFAULT 0,
  is_footer INTEGER DEFAULT 0,
  metadata_json TEXT,
  created_at TEXT,
  FOREIGN KEY(paper_id) REFERENCES papers(id)
);

CREATE INDEX IF NOT EXISTS idx_document_blocks_paper_id ON document_blocks(paper_id);
CREATE INDEX IF NOT EXISTS idx_document_blocks_page ON document_blocks(paper_id, page_number);
CREATE INDEX IF NOT EXISTS idx_document_blocks_section ON document_blocks(section_id);

CREATE TABLE IF NOT EXISTS document_tables (
  id TEXT PRIMARY KEY,
  paper_id TEXT NOT NULL,
  page_number INTEGER,
  section_id TEXT,
  section_path TEXT,
  caption TEXT,
  bbox_json TEXT,
  columns_json TEXT,
  row_count INTEGER,
  structured_text TEXT,
  summary TEXT,
  nearby_text TEXT,
  extraction_status TEXT,
  warnings_json TEXT,
  metadata_json TEXT,
  created_at TEXT,
  FOREIGN KEY(paper_id) REFERENCES papers(id)
);

CREATE INDEX IF NOT EXISTS idx_document_tables_paper_id ON document_tables(paper_id);
CREATE INDEX IF NOT EXISTS idx_document_tables_page ON document_tables(paper_id, page_number);

CREATE TABLE IF NOT EXISTS document_figures (
  id TEXT PRIMARY KEY,
  paper_id TEXT NOT NULL,
  page_number INTEGER,
  section_id TEXT,
  section_path TEXT,
  caption TEXT,
  bbox_json TEXT,
  image_path TEXT,
  nearby_text TEXT,
  visual_summary TEXT,
  summary_source TEXT,
  extraction_status TEXT,
  warnings_json TEXT,
  metadata_json TEXT,
  created_at TEXT,
  FOREIGN KEY(paper_id) REFERENCES papers(id)
);

CREATE INDEX IF NOT EXISTS idx_document_figures_paper_id ON document_figures(paper_id);
CREATE INDEX IF NOT EXISTS idx_document_figures_page ON document_figures(paper_id, page_number);

CREATE TABLE IF NOT EXISTS document_chunks (
  id TEXT PRIMARY KEY,
  paper_id TEXT NOT NULL,
  source_type TEXT,
  title TEXT,
  authors TEXT,
  section_id TEXT,
  section_title TEXT,
  section_path TEXT,
  page_start INTEGER,
  page_end INTEGER,
  block_ids_json TEXT,
  table_ids_json TEXT,
  figure_ids_json TEXT,
  prev_chunk_id TEXT,
  next_chunk_id TEXT,
  context_prefix TEXT,
  content TEXT,
  summary TEXT,
  parser_version TEXT,
  indexed_at TEXT,
  metadata_json TEXT,
  is_abstract INTEGER DEFAULT 0,
  retrieval_weight REAL DEFAULT 1.0,
  chunk_role TEXT DEFAULT '',
  parent_section_role TEXT DEFAULT '',
  created_at TEXT,
  FOREIGN KEY(paper_id) REFERENCES papers(id)
);

CREATE INDEX IF NOT EXISTS idx_document_chunks_paper_id ON document_chunks(paper_id);
CREATE INDEX IF NOT EXISTS idx_document_chunks_section ON document_chunks(section_id);
CREATE INDEX IF NOT EXISTS idx_document_chunks_source_type ON document_chunks(source_type);
CREATE INDEX IF NOT EXISTS idx_document_chunks_page ON document_chunks(page_start, page_end);

CREATE TABLE IF NOT EXISTS chunk_links (
  id TEXT PRIMARY KEY,
  paper_id TEXT NOT NULL,
  chunk_id TEXT NOT NULL,
  linked_type TEXT,
  linked_id TEXT,
  created_at TEXT,
  FOREIGN KEY(paper_id) REFERENCES papers(id)
);

CREATE INDEX IF NOT EXISTS idx_chunk_links_chunk_id ON chunk_links(chunk_id);

CREATE TABLE IF NOT EXISTS reading_notes (
  id TEXT PRIMARY KEY,
  paper_id TEXT NOT NULL,
  content_markdown TEXT,
  obsidian_path TEXT,
  quality_check_json TEXT,
  created_at TEXT,
  updated_at TEXT,
  FOREIGN KEY(paper_id) REFERENCES papers(id)
);

CREATE INDEX IF NOT EXISTS idx_reading_notes_paper_id ON reading_notes(paper_id);

CREATE TABLE IF NOT EXISTS note_chunks (
  id TEXT PRIMARY KEY,
  note_id TEXT NOT NULL,
  paper_id TEXT NOT NULL,
  section_name TEXT,
  chunk_index INTEGER,
  text TEXT,
  vector_id TEXT,
  created_at TEXT,
  FOREIGN KEY(note_id) REFERENCES reading_notes(id),
  FOREIGN KEY(paper_id) REFERENCES papers(id)
);

CREATE INDEX IF NOT EXISTS idx_note_chunks_note_id ON note_chunks(note_id);
CREATE INDEX IF NOT EXISTS idx_note_chunks_paper_id ON note_chunks(paper_id);

CREATE TABLE IF NOT EXISTS agent_tasks (
  id TEXT PRIMARY KEY,
  task_type TEXT,
  user_input TEXT,
  status TEXT,
  current_paper_id TEXT,
  current_folder_id TEXT,
  session_id TEXT,
  run_id TEXT,
  chat_scope TEXT,
  answer TEXT,
  execution_json TEXT DEFAULT '{}',
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_traces (
  id TEXT PRIMARY KEY,
  task_id TEXT,
  step_index INTEGER,
  node_name TEXT,
  agent_name TEXT,
  action_type TEXT,
  summary TEXT,
  status TEXT,
  created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_traces_task_id ON agent_traces(task_id);

CREATE TABLE IF NOT EXISTS a2a_messages (
  id TEXT PRIMARY KEY,
  task_id TEXT,
  from_agent TEXT,
  to_agent TEXT,
  message_type TEXT,
  payload TEXT,
  status TEXT,
  created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_a2a_task_id ON a2a_messages(task_id);

CREATE TABLE IF NOT EXISTS mcp_tool_calls (
  id TEXT PRIMARY KEY,
  task_id TEXT,
  server_name TEXT,
  tool_name TEXT,
  input_summary TEXT,
  output_summary TEXT,
  status TEXT,
  error TEXT,
  latency_ms INTEGER,
  created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_mcp_tool_calls_task_id ON mcp_tool_calls(task_id);

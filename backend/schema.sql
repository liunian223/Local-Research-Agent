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

CREATE TABLE IF NOT EXISTS paper_chunks (
  id TEXT PRIMARY KEY,
  paper_id TEXT NOT NULL,
  section_name TEXT,
  chunk_index INTEGER,
  text TEXT,
  vector_id TEXT,
  created_at TEXT,
  FOREIGN KEY(paper_id) REFERENCES papers(id)
);

CREATE INDEX IF NOT EXISTS idx_paper_chunks_paper_id ON paper_chunks(paper_id);
CREATE INDEX IF NOT EXISTS idx_paper_chunks_section ON paper_chunks(section_name);

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
  chat_scope TEXT,
  answer TEXT,
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

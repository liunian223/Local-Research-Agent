export interface Folder {
  id: string;
  name: string;
  is_system: boolean;
}

export interface Paper {
  id: string;
  title: string;
  authors: string;
  year: string;
  language: string;
  file_name: string;
  parse_status: string;
  vector_status: string;
  note_status: string;
  obsidian_note_path: string;
  latest_note?: {
    id: string;
    obsidian_path: string;
    created_at: string;
    updated_at: string;
  } | null;
  metadata_warning: string;
  parse_warning: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  execution?: any;
  task_id?: string;
}

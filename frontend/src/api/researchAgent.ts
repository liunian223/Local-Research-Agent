import axios from "axios";
import type { ChatMessage, ChatSession, ExecutionPayload, Folder, Paper } from "../types";

export interface FoldersResponse {
  folders: Folder[];
}

export interface PapersResponse {
  papers: Paper[];
}

export interface ChatSessionsResponse {
  sessions: ChatSession[];
}

export interface ChatHistoryResponse {
  session_id?: string;
  messages?: ChatMessage[];
  current_folder_id?: string;
  chat_scope?: string;
  current_paper?: Paper | null;
}

export interface DeleteChatSessionResponse {
  deleted_tasks: number;
  next_session_id?: string;
}

export interface TaskResponse {
  task_id: string;
  answer: string;
  message_type: string;
  current_paper?: {
    paper_id: string;
    title: string;
  } | null;
  execution?: ExecutionPayload;
}

export interface SendMessagePayload {
  message: string;
  current_paper_id: string | null;
  current_folder_id: string;
  session_id: string;
  chat_scope: string;
}

export function apiMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    return err.response?.data?.detail?.error?.message || err.response?.data?.detail || err.message;
  }
  return String(err);
}

export async function listFolders(): Promise<FoldersResponse> {
  const response = await axios.get<FoldersResponse>("/api/folders");
  return response.data;
}

export async function listPapers(folderId: string): Promise<PapersResponse> {
  const response = await axios.get<PapersResponse>("/api/papers", { params: { folder_id: folderId } });
  return response.data;
}

export async function searchPapersByKeyword(keyword: string, folderId: string): Promise<PapersResponse> {
  const response = await axios.get<PapersResponse>("/api/papers/search", { params: { keyword, folder_id: folderId } });
  return response.data;
}

export async function deletePaperById(paperId: string): Promise<void> {
  await axios.delete(`/api/papers/${paperId}`);
}

export async function listChatSessions(): Promise<ChatSessionsResponse> {
  const response = await axios.get<ChatSessionsResponse>("/api/chat/sessions");
  return response.data;
}

export async function createChatSession(title: string): Promise<{ session: ChatSession }> {
  const response = await axios.post<{ session: ChatSession }>("/api/chat/sessions", { title });
  return response.data;
}

export async function deleteChatSessionById(sessionId: string): Promise<DeleteChatSessionResponse> {
  const response = await axios.delete<DeleteChatSessionResponse>(`/api/chat/sessions/${sessionId}`);
  return response.data;
}

export async function getChatHistory(sessionId: string): Promise<ChatHistoryResponse> {
  const response = await axios.get<ChatHistoryResponse>("/api/chat/history", { params: { session_id: sessionId } });
  return response.data;
}

export async function uploadChatPdf(file: File, folderId: string, sessionId: string, message: string): Promise<TaskResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("current_folder_id", folderId);
  form.append("session_id", sessionId);
  form.append("message", message);
  const response = await axios.post<TaskResponse>("/api/chat/upload", form, { headers: { "Content-Type": "multipart/form-data" } });
  return response.data;
}

export async function sendChatMessage(payload: SendMessagePayload): Promise<TaskResponse> {
  const response = await axios.post<TaskResponse>("/api/chat/message", payload);
  return response.data;
}

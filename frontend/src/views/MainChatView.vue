<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="brand">Local Research Agent</div>
      <div class="muted">Knowledge RAG Agent + Note Skill Agent</div>
    </header>

    <div class="workspace">
      <aside class="sidebar">
        <div class="section-title">个人知识库</div>

        <div class="stack folder-list">
          <button
            v-for="folder in folders"
            :key="folder.id"
            class="folder"
            :class="{ active: folder.id === currentFolderId }"
            @click="selectFolder(folder.id)"
          >
            <div class="row">
              <span>{{ displayFolderName(folder) }}</span>
              <span v-if="folder.is_system" class="pill">system</span>
            </div>
          </button>
        </div>

        <div class="section-title compact-title">对话</div>
        <button class="new-chat-button" @click="createSession">新建对话</button>
        <div class="stack conversation-list">
          <button
            v-for="session in sessions"
            :key="session.id"
            class="conversation"
            :class="{ active: session.id === currentSessionId }"
            @click="selectSession(session.id)"
          >
            <span class="conversation-title">{{ sessionTitle(session) }}</span>
            <span v-if="session.has_messages" class="conversation-meta">{{ session.task_count }} 条</span>
            <button v-if="canDeleteSession(session)" class="danger-button" title="删除对话" @click.stop="deleteSession(session)">删除</button>
          </button>
        </div>

        <div class="section-title">论文</div>
        <input v-model="keyword" class="input" placeholder="搜索标题 / 作者" @input="searchPapers" />
        <div class="stack" style="margin-top: 10px">
          <button
            v-for="paper in papers"
            :key="paper.id"
            class="paper"
            :class="{ active: paper.id === currentPaper?.id }"
            @click="selectPaper(paper)"
          >
            <div class="paper-header">
              <div class="paper-title">{{ paper.title || "Untitled Paper" }}</div>
              <button class="danger-button" title="删除论文" @click.stop="deletePaper(paper)">删除</button>
            </div>
          </button>
        </div>
      </aside>

      <main class="main">
        <section class="chat-scroll">
          <div v-if="currentPaper" class="message assistant">
            <strong>Current paper</strong>
            <div>{{ currentPaper.title }}</div>
            <div class="muted">{{ currentPaper.authors }}</div>
            <div class="status-line">
              <span class="pill">{{ currentPaper.language || "unknown" }}</span>
              <span class="pill">parse {{ currentPaper.parse_status }}</span>
              <span class="pill">note {{ currentPaper.note_status }}</span>
            </div>
            <div v-if="currentPaper.obsidian_note_path" class="muted note-path-full">Note: {{ currentPaper.obsidian_note_path }}</div>
          </div>

          <article v-for="(message, index) in messages" :key="index" class="message" :class="message.role">
            <div>{{ message.text }}</div>
            <ExecutionPanel v-if="message.execution" :execution="message.execution" />
          </article>
        </section>

        <section class="composer">
          <div class="dropzone" :class="{ dragging }" @dragenter.prevent="dragging = true" @dragover.prevent @dragleave.prevent="dragging = false" @drop.prevent="handleDrop">
            <div>
              <strong>PDF 上传</strong>
              <div class="muted">拖入 PDF，或点击选择文件</div>
            </div>
            <input ref="fileInput" type="file" accept="application/pdf,.pdf" hidden @change="handleFileChange" />
            <button @click="fileInput?.click()">选择 PDF</button>
          </div>

          <div class="row" style="margin-top: 10px">
            <select v-model="chatScope" class="select" style="max-width: 260px">
              <option value="paper_and_note">当前论文 + 当前笔记</option>
              <option value="paper_only">当前论文</option>
              <option value="note_only">当前笔记</option>
              <option value="global_library">全知识库</option>
            </select>
            <button :disabled="busy || !currentPaper" @click="quickNote">生成 Obsidian 笔记</button>
          </div>
          <div class="row" style="align-items: flex-end; margin-top: 10px">
            <textarea v-model="draft" class="textarea" placeholder="输入科研问题或任务" @keydown.ctrl.enter.prevent="sendMessage"></textarea>
            <button class="send-button" :disabled="busy || !draft.trim()" @click="sendMessage">发送</button>
          </div>
          <div v-if="error" class="muted" style="margin-top: 8px">{{ error }}</div>
        </section>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import axios from "axios";
import { onMounted, ref } from "vue";
import ExecutionPanel from "../components/ExecutionPanel.vue";
import type { ChatMessage, ChatSession, Folder, Paper } from "../types";

const readyMessage = "系统已就绪。请上传 PDF，或选择论文后提问。";

const folders = ref<Folder[]>([]);
const papers = ref<Paper[]>([]);
const sessions = ref<ChatSession[]>([]);
const messages = ref<ChatMessage[]>([{ role: "assistant", text: readyMessage }]);
const keyword = ref("");
const currentFolderId = ref("folder_all");
const currentSessionId = ref("session_default");
const currentPaper = ref<Paper | null>(null);
const draft = ref("");
const chatScope = ref("paper_and_note");
const dragging = ref(false);
const busy = ref(false);
const error = ref("");
const fileInput = ref<HTMLInputElement | null>(null);

function displayFolderName(folder: Folder): string {
  return folder.id === "folder_all" ? "论文库" : folder.name;
}

function canDeleteSession(session: ChatSession): boolean {
  return session.id !== "session_default" || Boolean(session.has_messages);
}

function sessionTitle(session: ChatSession): string {
  return session.display_title || session.title || "新对话";
}

function apiMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    return err.response?.data?.detail?.error?.message || err.response?.data?.detail || err.message;
  }
  return String(err);
}

async function loadFolders() {
  const response = await axios.get("/api/folders");
  folders.value = response.data.folders;
}

async function loadPapers() {
  const response = await axios.get("/api/papers", { params: { folder_id: currentFolderId.value } });
  papers.value = response.data.papers;
}

async function loadSessions() {
  const response = await axios.get("/api/chat/sessions");
  sessions.value = response.data.sessions;
  if (!sessions.value.some((session) => session.id === currentSessionId.value) && sessions.value.length) {
    currentSessionId.value = sessions.value[0].id;
  }
}

async function loadChatHistory() {
  const response = await axios.get("/api/chat/history", { params: { session_id: currentSessionId.value } });
  currentSessionId.value = response.data.session_id || currentSessionId.value;
  if (response.data.messages?.length) {
    messages.value = response.data.messages;
  } else {
    messages.value = [{ role: "assistant", text: readyMessage }];
  }
  if (response.data.current_folder_id) {
    currentFolderId.value = response.data.current_folder_id;
  }
  if (response.data.chat_scope) {
    chatScope.value = response.data.chat_scope;
  }
  if (response.data.current_paper) {
    currentPaper.value = response.data.current_paper;
  }
}

async function createSession() {
  const response = await axios.post("/api/chat/sessions", { title: "新对话" });
  await loadSessions();
  await selectSession(response.data.session.id);
}

async function deleteSession(session: ChatSession) {
  try {
    const response = await axios.delete(`/api/chat/sessions/${session.id}`);
    await loadSessions();
    await selectSession(response.data.next_session_id || sessions.value[0]?.id || "session_default");
  } catch (err) {
    error.value = apiMessage(err);
  }
}

async function selectSession(id: string) {
  currentSessionId.value = id;
  currentPaper.value = null;
  await loadChatHistory();
  await loadPapers();
  if (currentPaper.value) {
    const refreshed = papers.value.find((paper) => paper.id === currentPaper.value?.id);
    if (refreshed) currentPaper.value = refreshed;
  }
}

async function deletePaper(paper: Paper) {
  try {
    await axios.delete(`/api/papers/${paper.id}`);
    if (currentPaper.value?.id === paper.id) {
      currentPaper.value = null;
    }
    await loadPapers();
  } catch (err) {
    error.value = apiMessage(err);
  }
}

async function selectFolder(id: string) {
  currentFolderId.value = id;
  keyword.value = "";
  await loadPapers();
}

async function searchPapers() {
  if (!keyword.value.trim()) {
    await loadPapers();
    return;
  }
  const response = await axios.get("/api/papers/search", { params: { keyword: keyword.value, folder_id: currentFolderId.value } });
  papers.value = response.data.papers;
}

function selectPaper(paper: Paper) {
  currentPaper.value = paper;
}

async function uploadFile(file: File) {
  busy.value = true;
  error.value = "";
  messages.value.push({ role: "user", text: `上传 PDF：${file.name}` });
  try {
    const form = new FormData();
    form.append("file", file);
    form.append("current_folder_id", currentFolderId.value);
    form.append("session_id", currentSessionId.value);
    form.append("message", draft.value);
    const response = await axios.post("/api/chat/upload", form, { headers: { "Content-Type": "multipart/form-data" } });
    messages.value.push({ role: "assistant", text: response.data.answer, execution: response.data.execution });
    await loadPapers();
    const paper = papers.value.find((item) => item.id === response.data.current_paper?.paper_id);
    if (paper) currentPaper.value = paper;
    await loadSessions();
  } catch (err) {
    error.value = apiMessage(err);
    messages.value.push({ role: "assistant", text: error.value });
  } finally {
    dragging.value = false;
    busy.value = false;
  }
}

function handleDrop(event: DragEvent) {
  const file = event.dataTransfer?.files?.[0];
  if (file) void uploadFile(file);
}

function handleFileChange(event: Event) {
  const target = event.target as HTMLInputElement;
  const file = target.files?.[0];
  if (file) void uploadFile(file);
  target.value = "";
}

async function sendMessage() {
  const text = draft.value.trim();
  if (!text) return;
  busy.value = true;
  error.value = "";
  draft.value = "";
  messages.value.push({ role: "user", text });
  try {
    const response = await axios.post("/api/chat/message", {
      message: text,
      current_paper_id: currentPaper.value?.id || null,
      current_folder_id: currentFolderId.value,
      session_id: currentSessionId.value,
      chat_scope: chatScope.value
    });
    messages.value.push({ role: "assistant", text: response.data.answer, execution: response.data.execution });
    await loadPapers();
    if (currentPaper.value) {
      const refreshed = papers.value.find((paper) => paper.id === currentPaper.value?.id);
      if (refreshed) currentPaper.value = refreshed;
    }
    await loadSessions();
  } catch (err) {
    error.value = apiMessage(err);
    messages.value.push({ role: "assistant", text: error.value });
  } finally {
    busy.value = false;
  }
}

function quickNote() {
  draft.value = "请为当前论文生成 Obsidian 阅读笔记";
  void sendMessage();
}

onMounted(async () => {
  try {
    await Promise.all([loadFolders(), loadSessions()]);
    await loadChatHistory();
    await loadPapers();
    if (currentPaper.value) {
      const refreshed = papers.value.find((paper) => paper.id === currentPaper.value?.id);
      if (refreshed) currentPaper.value = refreshed;
    }
  } catch (err) {
    error.value = apiMessage(err);
  }
});
</script>

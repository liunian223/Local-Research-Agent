<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="brand">Local Research Agent</div>
      <div class="muted">Knowledge RAG Agent + Note Skill Agent</div>
    </header>

    <div class="workspace">
      <aside class="sidebar">
        <div class="section-title">Personal Library</div>
        <div class="row">
          <input v-model="folderName" class="input" placeholder="新建文件夹" @keyup.enter="createFolder" />
          <button title="Create folder" @click="createFolder">+</button>
        </div>

        <div class="section-title">Folders</div>
        <div class="stack">
          <button
            v-for="folder in folders"
            :key="folder.id"
            class="folder"
            :class="{ active: folder.id === currentFolderId }"
            @click="selectFolder(folder.id)"
          >
            <div class="row">
              <span>{{ folder.name }}</span>
              <span v-if="folder.is_system" class="pill">system</span>
            </div>
          </button>
        </div>
        <div class="row" style="margin-top: 8px">
          <button :disabled="currentFolder?.is_system" @click="deleteFolder">删除空文件夹</button>
        </div>

        <div class="section-title">Papers</div>
        <input v-model="keyword" class="input" placeholder="搜索标题 / 作者" @input="searchPapers" />
        <div class="stack" style="margin-top: 10px">
          <button
            v-for="paper in papers"
            :key="paper.id"
            class="paper"
            :class="{ active: paper.id === currentPaper?.id }"
            @click="selectPaper(paper)"
          >
            <div class="paper-title">{{ paper.title || "Untitled Paper" }}</div>
            <div class="muted">{{ paper.authors || "Unknown authors" }}</div>
            <div class="status-line">
              <span class="pill">parse {{ paper.parse_status }}</span>
              <span class="pill">rag {{ paper.vector_status }}</span>
              <span class="pill">note {{ paper.note_status }}</span>
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
            <div v-if="currentPaper.obsidian_note_path" class="muted">Note: {{ currentPaper.obsidian_note_path }}</div>
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
            <button :disabled="busy || !draft.trim()" @click="sendMessage">发送</button>
          </div>
          <div v-if="error" class="muted" style="margin-top: 8px">{{ error }}</div>
        </section>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import axios from "axios";
import { computed, onMounted, ref } from "vue";
import ExecutionPanel from "../components/ExecutionPanel.vue";
import type { ChatMessage, Folder, Paper } from "../types";

const folders = ref<Folder[]>([]);
const papers = ref<Paper[]>([]);
const messages = ref<ChatMessage[]>([
  { role: "assistant", text: "系统已就绪。请创建文件夹、上传 PDF，或选择论文后提问。" }
]);
const folderName = ref("");
const keyword = ref("");
const currentFolderId = ref("folder_all");
const currentPaper = ref<Paper | null>(null);
const draft = ref("");
const chatScope = ref("paper_and_note");
const dragging = ref(false);
const busy = ref(false);
const error = ref("");
const fileInput = ref<HTMLInputElement | null>(null);

const currentFolder = computed(() => folders.value.find((folder) => folder.id === currentFolderId.value));

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

async function createFolder() {
  if (!folderName.value.trim()) return;
  try {
    await axios.post("/api/folders", { name: folderName.value.trim() });
    folderName.value = "";
    await loadFolders();
  } catch (err) {
    error.value = apiMessage(err);
  }
}

async function deleteFolder() {
  if (!currentFolder.value || currentFolder.value.is_system) return;
  try {
    await axios.delete(`/api/folders/${currentFolder.value.id}`);
    currentFolderId.value = "folder_all";
    await Promise.all([loadFolders(), loadPapers()]);
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
  const response = await axios.get("/api/papers/search", { params: { keyword: keyword.value } });
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
    form.append("message", draft.value);
    const response = await axios.post("/api/chat/upload", form, { headers: { "Content-Type": "multipart/form-data" } });
    messages.value.push({ role: "assistant", text: response.data.answer, execution: response.data.execution });
    await loadPapers();
    const paper = papers.value.find((item) => item.id === response.data.current_paper?.paper_id);
    if (paper) currentPaper.value = paper;
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
      chat_scope: chatScope.value
    });
    messages.value.push({ role: "assistant", text: response.data.answer, execution: response.data.execution });
    await loadPapers();
    if (currentPaper.value) {
      const refreshed = papers.value.find((paper) => paper.id === currentPaper.value?.id);
      if (refreshed) currentPaper.value = refreshed;
    }
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
    await Promise.all([loadFolders(), loadPapers()]);
  } catch (err) {
    error.value = apiMessage(err);
  }
});
</script>

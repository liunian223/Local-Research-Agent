<template>
  <div class="execution">
    <details>
      <summary>执行详情 / Graph / MCP / RAG / Skill</summary>

      <div class="section-title">Harness Runtime</div>
      <div class="rag-summary">
        <div><span>task_id</span><strong>{{ harness.task_id || "-" }}</strong></div>
        <div><span>run_id</span><strong>{{ harness.run_id || "-" }}</strong></div>
        <div><span>task_type</span><strong>{{ harness.task_type || "-" }}</strong></div>
        <div><span>runtime_status</span><strong>{{ harness.runtime_status || "-" }}</strong></div>
        <div><span>context strategy</span><strong>{{ harness.context_pack_strategy || "-" }}</strong></div>
        <div><span>latency_ms</span><strong>{{ harness.latency_ms ?? "-" }}</strong></div>
      </div>

      <div class="section-title">ToolGateway Summary</div>
      <div class="rag-summary">
        <div><span>total calls</span><strong>{{ toolSummary.total_calls ?? 0 }}</strong></div>
        <div><span>failed calls</span><strong>{{ toolSummary.failed_calls ?? 0 }}</strong></div>
        <div><span>MCP servers</span><strong>{{ (toolSummary.mcp_servers || []).join(", ") || "-" }}</strong></div>
        <div><span>redaction</span><strong>{{ harness.redaction?.enabled ? "enabled" : "disabled" }}</strong></div>
      </div>

      <div class="section-title">RAG 检索策略</div>
      <div class="rag-summary">
        <div><span>问题复杂度</span><strong>{{ textValue(queryAnalysis.complexity) }}</strong></div>
        <div><span>问题意图</span><strong>{{ textValue(queryAnalysis.intent) }}</strong></div>
        <div><span>检索模式</span><strong>{{ retrieval.retrieval_mode || "-" }}</strong></div>
        <div><span>摘要策略</span><strong>{{ textValue(queryAnalysis.abstract_mode || abstractControl.abstract_mode) }}</strong></div>
        <div><span>候选数量</span><strong>{{ numberValue(rerank.candidate_count) }}</strong></div>
        <div><span>最终证据</span><strong>{{ numberValue(rerank.final_count, evidenceCount) }}</strong></div>
      </div>

      <div v-if="hasAbstractControl" class="section-title">摘要控制</div>
      <div v-if="hasAbstractControl" class="rag-summary">
        <div><span>检测到摘要</span><strong>{{ boolText(abstractControl.has_abstract) }}</strong></div>
        <div><span>召回摘要片段</span><strong>{{ numberValue(abstractControl.abstract_chunks_recalled, 0) }}</strong></div>
        <div><span>最终使用摘要</span><strong>{{ numberValue(abstractControl.abstract_chunks_used, 0) }}</strong></div>
        <div><span>是否降权</span><strong>{{ boolText(abstractControl.abstract_penalty_applied) }}</strong></div>
      </div>

      <div v-if="hasCoverage" class="section-title">Evidence coverage</div>
      <div v-if="hasCoverage" class="coverage-list">
        <div v-for="section in coverageRows" :key="section.name">
          <span>{{ section.name }}</span>
          <strong>{{ section.covered ? "已覆盖" : "证据不足" }}</strong>
        </div>
      </div>

      <div class="section-title">Evidence 分组</div>
      <div class="evidence-groups">
        <details v-for="group in evidenceGroups" :key="group.key" :open="group.items.length > 0">
          <summary>{{ group.label }} ({{ group.items.length }})</summary>
          <pre>{{ stringify(group.items) }}</pre>
        </details>
      </div>

      <div v-if="hasNoteGeneration" class="section-title">Deep Paper Note Skill</div>
      <div v-if="hasNoteGeneration" class="rag-summary">
        <div><span>生成模式</span><strong>{{ noteGeneration.mode || "-" }}</strong></div>
        <div><span>模板版本</span><strong>{{ noteGeneration.template_version || "-" }}</strong></div>
        <div><span>Repair 轮次</span><strong>{{ noteGeneration.repair_rounds ?? 0 }}</strong></div>
        <div><span>Note chunks</span><strong>{{ noteGeneration.note_chunks ?? "-" }}</strong></div>
        <div><span>Note RAG 入库</span><strong>{{ noteGeneration.note_vector_status || "-" }}</strong></div>
        <div><span>Vector backend</span><strong>{{ noteGeneration.vector_backend || "-" }}</strong></div>
      </div>

      <div v-if="hasNoteGeneration" class="section-title">Note 质量检查</div>
      <pre v-if="hasNoteGeneration">{{ stringify(noteGeneration.quality_check) }}</pre>
      <div v-if="hasNoteGeneration" class="section-title">Note 写入 / Repair</div>
      <pre v-if="hasNoteGeneration">{{ stringify(noteWriteSummary) }}</pre>

      <div class="section-title">Graph state</div>
      <pre>{{ stringify(execution.graph_state) }}</pre>
      <div class="section-title">LangGraph</div>
      <pre>{{ stringify(execution.langgraph_nodes) }}</pre>
      <div class="section-title">MCP tool calls</div>
      <pre>{{ stringify(execution.mcp_tool_calls) }}</pre>
      <div class="section-title">A2A-style messages</div>
      <pre>{{ stringify(execution.a2a_messages) }}</pre>
      <div class="section-title">Model execution</div>
      <pre>{{ stringify(execution.model_execution) }}</pre>
      <div class="section-title">Policy Checks</div>
      <pre>{{ stringify(harness.policy_checks) }}</pre>
      <div class="section-title">Structured RAG</div>
      <pre>{{ stringify({ pipeline: execution.rag_pipeline, retrieval: execution.retrieval }) }}</pre>
      <div class="section-title">Evidence bundle</div>
      <pre>{{ stringify(execution.evidence_bundle) }}</pre>
      <div class="section-title">RAG evidence</div>
      <pre>{{ stringify(execution.rag_evidence) }}</pre>
      <div class="section-title">Skill phases</div>
      <pre>{{ stringify(execution.skill_phases) }}</pre>
      <div class="section-title">Fallbacks</div>
      <pre>{{ stringify(execution.fallbacks) }}</pre>
    </details>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type {
  EvidenceBundle,
  ExecutionPayload,
  JsonObject,
  JsonValue,
  NoteGenerationSummary,
  RetrievalSummary
} from "../types";

const props = defineProps<{ execution: ExecutionPayload }>();

const execution = computed(() => props.execution || {});
const retrieval = computed<RetrievalSummary>(() => execution.value.retrieval || {});
const harness = computed(() => execution.value.harness || {});
const toolSummary = computed(() => harness.value.tool_summary || {});
const queryAnalysis = computed<JsonObject>(() => retrieval.value.query_analysis || {});
const abstractControl = computed<JsonObject>(() => retrieval.value.abstract_control || {});
const rerank = computed<JsonObject>(() => retrieval.value.rerank || {});
const coverage = computed<JsonObject>(() => retrieval.value.coverage_check || {});
const bundle = computed<EvidenceBundle>(() => execution.value.evidence_bundle || {});
const noteGeneration = computed<NoteGenerationSummary>(() => execution.value.note_generation || {});
const evidenceCount = computed(() => execution.value.rag_evidence?.length || 0);
const hasAbstractControl = computed(() => Object.keys(abstractControl.value).length > 0);
const hasCoverage = computed(() => Object.keys(coverage.value).length > 0);
const hasNoteGeneration = computed(() => Object.keys(noteGeneration.value).length > 0);
const coverageRows = computed(() => {
  const covered = objectValue(coverage.value.covered_sections) as Record<string, JsonValue>;
  const missing = arrayValue(coverage.value.missing_sections).map(String);
  const missingSet = new Set<string>(missing);
  const names = Array.from(new Set<string>([...Object.keys(covered), ...missing]));
  return names.map((name) => ({ name, covered: Boolean(covered[name]) && !missingSet.has(name) }));
});
const evidenceGroups = computed(() => [
  { key: "text", label: "正文证据", items: bundle.value.text_chunks || [] },
  { key: "sections", label: "章节摘要", items: bundle.value.section_summaries || [] },
  { key: "abstract", label: "摘要线索", items: bundle.value.abstract_chunks || [] },
  { key: "tables", label: "表格证据", items: bundle.value.tables || [] },
  { key: "figures", label: "图像/图注证据", items: bundle.value.figures || [] },
  { key: "pages", label: "页面证据", items: bundle.value.pages || [] },
]);
const noteWriteSummary = computed(() => ({
  markdown_path: noteGeneration.value.markdown_path,
  pdf_attachment_path: noteGeneration.value.pdf_attachment_path,
  repair_log: noteGeneration.value.repair_log,
  evidence_group_counts: noteGeneration.value.evidence_group_counts
}));

function objectValue(value: unknown): JsonObject {
  return value && !Array.isArray(value) && typeof value === "object" ? (value as JsonObject) : {};
}

function arrayValue(value: unknown): JsonValue[] {
  return Array.isArray(value) ? value : [];
}

function textValue(value: unknown): string {
  if (value === undefined || value === null || value === "") return "-";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function numberValue(value: unknown, fallback: number | string = "-"): number | string {
  return typeof value === "number" || typeof value === "string" ? value : fallback;
}

function boolText(value: unknown): string {
  if (value === undefined || value === null) return "-";
  return value ? "是" : "否";
}

function stringify(value: unknown) {
  return JSON.stringify(value ?? [], null, 2);
}
</script>

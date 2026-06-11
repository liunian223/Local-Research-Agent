<template>
  <div class="execution">
    <details>
      <summary>LangGraph / MCP / A2A / RAG / Skill / fallback</summary>
      <div class="section-title">Graph state</div>
      <pre>{{ stringify(execution.graph_state) }}</pre>
      <div class="section-title">LangGraph</div>
      <pre>{{ stringify(execution.langgraph_nodes) }}</pre>
      <div class="section-title">MCP tool calls</div>
      <pre>{{ stringify(execution.mcp_tool_calls) }}</pre>
      <div class="section-title">A2A-style messages</div>
      <pre>{{ stringify(execution.a2a_messages) }}</pre>
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
defineProps<{ execution: any }>();

function stringify(value: unknown) {
  return JSON.stringify(value || [], null, 2);
}
</script>

<script setup>
import { ref, computed, onMounted } from 'vue'
import UploadView from './views/UploadView.vue'
import ResultView from './views/ResultView.vue'
import BatchView from './views/BatchView.vue'
import HistoryView from './views/HistoryView.vue'
import SetupView from './views/SetupView.vue'
import { api, fetchConfig } from './api'

const view = ref('upload')
const currentTask = ref(null)
const batchIds = ref([])
const cameFromBatch = ref(false)   // 从批量列表进入详情 → 返回时回到列表而非主页

const isBatch = computed(() => view.value === 'batch' && batchIds.value.length > 1)
// 未配置 LLM Key → 强制显示设置页（其余视图无意义）
const needSetup = computed(() => api.loaded && api.needsSetup)

function openSetup() {
  view.value = 'setup'
}

function onAnalyzed(taskIds) {
  batchIds.value = taskIds
  cameFromBatch.value = false
  if (taskIds.length === 1) {
    currentTask.value = taskIds[0]
    view.value = 'result'
  } else {
    view.value = 'batch'
  }
}

function onViewTask(taskId) {
  currentTask.value = taskId
  cameFromBatch.value = isBatch.value   // 从批量列表进入详情
  view.value = 'result'
}

// 一键重试成功 → 直接查看新任务结果
function onRetried(newTaskId) {
  currentTask.value = newTaskId
  batchIds.value = []
  view.value = 'result'
}

function onBack() {
  // 从批量列表进入的详情 → 返回列表（可继续点其他照片），不回主页
  if (cameFromBatch.value && batchIds.value.length > 1) {
    cameFromBatch.value = false
    view.value = 'batch'
    return
  }
  view.value = 'upload'
  currentTask.value = null
  batchIds.value = []
}

async function onSetupSaved() {
  await fetchConfig()
  view.value = 'upload'
}

let pollTimer = null

onMounted(() => {
  fetchConfig()
  // 预热轮询：本地模型未就绪时每 2s 刷新 config，就绪后停止
  pollTimer = setInterval(async () => {
    await fetchConfig()
    if (!api.warmingUp) clearInterval(pollTimer)
  }, 2000)
})
</script>

<template>
  <header class="header">
    <h1 style="cursor:pointer" @click="onBack">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 21s-7-5.5-7-11a7 7 0 0 1 14 0c0 5.5-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/></svg>
      Street Geolocator
    </h1>
    <div class="header-right">
      <template v-if="api.loaded">
        <span class="badge">{{ api.model }}</span>
      </template>
      <span v-else class="badge country">未连接</span>
      <button class="btn btn-ghost icon-btn" title="历史记录" @click="view = 'history'">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/></svg>
      </button>
      <button class="btn btn-ghost icon-btn" title="设置" @click="openSetup">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.01a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h.01a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.01a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
      </button>
    </div>
  </header>

  <main class="main">
    <SetupView v-if="needSetup || view === 'setup'" @saved="onSetupSaved" @back="onBack" />
    <ResultView v-else-if="view === 'result'" :task-id="currentTask" @back="onBack" @retried="onRetried" />
    <BatchView v-else-if="isBatch" :task-ids="batchIds" @view="onViewTask" @back="onBack" @retry="onRetried" />
    <HistoryView v-else-if="view === 'history'" @view="onViewTask" @back="onBack" @retry="onRetried" />
    <UploadView v-else @analyzed="onAnalyzed" />
  </main>
</template>

<style scoped>
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  background: #fff;
  border-bottom: 1px solid #e5e7eb;
}
.header h1 { font-size: 20px; display: flex; align-items: center; gap: 8px; }
.header-right { display: flex; gap: 8px; align-items: center; }
.btn-ghost { background: #e5e7eb; color: #374151; padding: 6px 12px; font-size: 13px; }
.btn-ghost:hover { background: #d1d5db; }
.icon-btn { display: flex; align-items: center; justify-content: center; width: 32px; height: 32px; padding: 0; }
.main { max-width: 1100px; margin: 24px auto; padding: 0 16px; }
.footer { text-align: center; padding: 16px; }

/* 竖屏/窄屏适配（16:9 → 9:16） */
@media (max-width: 640px) {
  .header { padding: 12px 16px; flex-wrap: wrap; gap: 8px; }
  .header h1 { font-size: 17px; }
  .main { margin: 12px auto; padding: 0 10px; }
}
</style>

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

// 深色模式（localStorage 持久化，作用于 html.dark）
const dark = ref(localStorage.getItem('theme') === 'dark')
function applyTheme() {
  document.documentElement.dataset.theme = dark.value ? 'dark' : 'light' 
  localStorage.setItem('theme', dark.value ? 'dark' : 'light')
}
function toggleTheme() {
  dark.value = !dark.value
  applyTheme()
}

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
  applyTheme()   // 恢复深色/亮色主题
  // 支持 ?task=<id> 直达（浏览器插件/分享链接）
  const qid = new URLSearchParams(location.search).get('task')
  if (qid) {
    currentTask.value = qid
    view.value = 'result'
  }
  fetchConfig()
  // 预热轮询：本地模型未就绪时每 2s 刷新 config，就绪后停止
  pollTimer = setInterval(async () => {
    await fetchConfig()
    if (!api.warmingUp) clearInterval(pollTimer)
  }, 2000)
})
</script>

<template>
  <div class="nav">
    <button v-if="view !== 'upload'" class="nav-btn" title="返回" @click="onBack">‹</button>
    <h1>{{ view === 'setup' ? '设置' : view === 'history' ? '历史记录' : view === 'result' ? '结果' : view === 'batch' ? '批量结果' : '街景定位' }}</h1>
    <button v-if="view === 'upload'" class="nav-btn" title="历史记录" @click="view = 'history'">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/></svg>
    </button>
    <button v-if="view === 'upload'" class="nav-btn" :title="dark ? '切换浅色' : '切换深色'" @click="toggleTheme">
      <svg v-if="!dark" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
      <svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.41 1.41m11.32 11.32 1.41 1.41M2 12h2m16 0h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>
    </button>
    <button v-if="view === 'upload'" class="nav-btn" title="设置" @click="openSetup">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.01a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h.01a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.01a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
    </button>
  </div>

  <main class="wrap" style="padding-bottom:24px">
    <SetupView v-if="needSetup || view === 'setup'" @saved="onSetupSaved" @back="onBack" />
    <ResultView v-else-if="view === 'result'" :task-id="currentTask" @back="onBack" @retried="onRetried" />
    <BatchView v-else-if="isBatch" :task-ids="batchIds" @view="onViewTask" @back="onBack" @retry="onRetried" />
    <HistoryView v-else-if="view === 'history'" @view="onViewTask" @back="onBack" @retry="onRetried" />
    <UploadView v-else @analyzed="onAnalyzed" />
  </main>
</template>




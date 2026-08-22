<script setup>
import { ref, onMounted } from 'vue'
import { confidenceLabel, retryTask } from '../api'

const emit = defineEmits(['view', 'back', 'retry'])

const tasks = ref([])
const error = ref('')
const retryingId = ref('')

async function load() {
  try {
    const res = await fetch('/api/tasks')
    const data = await res.json()
    tasks.value = data.tasks || []
  } catch (e) {
    error.value = e.message
  }
}

async function onRetry(taskId) {
  if (retryingId.value) return
  retryingId.value = taskId
  try {
    const newId = await retryTask(taskId)
    emit('retry', newId)
  } catch (e) {
    alert(`重试失败：${e.message}`)
  } finally {
    retryingId.value = ''
  }
}

function fmtTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', { hour12: false })
}

onMounted(load)
</script>

<template>
  <div class="hist-wrap">
    <div class="card hist-head">
      <h2>📜 历史记录（{{ tasks.length }} 条）</h2>
      <button class="btn btn-ghost" @click="emit('back')">← 返回上传</button>
    </div>

    <div v-if="error" class="card error-card">{{ error }}</div>

    <div class="card-list">
      <div v-for="t in tasks" :key="t.task_id" class="card row" @click="emit('view', t.task_id)">
        <div class="row-main">
          <div class="fname">{{ t.filename }}</div>
          <div class="muted">
            <span class="badge" :class="t.confidence_level">{{ confidenceLabel(t.confidence_level) }}</span>
            <template v-if="t.status === 'succeeded'">
              · {{ t.mode || 'balanced' }}模式 · {{ (t.elapsed_ms / 1000).toFixed(1) }}s
            </template>
            <template v-else-if="t.status === 'failed'"> · ❌ {{ t.error }}</template>
          </div>
          <div class="muted" v-if="t.candidates?.length">
            🏙️ {{ t.candidates[0].city_zh || t.candidates[0].city || '候选点' }}
            <template v-if="t.scene?.country_hypotheses?.length">
              · 🌍 {{ t.scene.country_hypotheses[0].country_zh || t.scene.country_hypotheses[0].country }}
            </template>
          </div>
        </div>
        <div class="row-actions">
          <button
            v-if="t.status === 'failed' && t.has_image"
            class="btn btn-sm"
            @click.stop="onRetry(t.task_id)"
          >
            {{ retryingId === t.task_id ? '重试中…' : '🔄 重试' }}
          </button>
          <div class="time muted">{{ fmtTime(t.created_at) }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.hist-wrap { max-width: 720px; margin: 0 auto; }
.hist-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.btn-ghost { background: #e5e7eb; color: #374151; }
.btn-ghost:hover { background: #d1d5db; }
.card-list { display: flex; flex-direction: column; gap: 8px; }
.row {
  display: flex; justify-content: space-between; align-items: center; gap: 12px;
  padding: 12px 16px; cursor: pointer; text-align: left;
  border: 1px solid #e5e7eb; transition: border-color 0.15s;
}
.row:hover { border-color: #2563eb; }
.row-main { flex: 1; min-width: 0; }
.fname { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row-actions { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; }
.btn-sm { padding: 5px 10px; font-size: 12px; }
.time { font-size: 12px; flex-shrink: 0; }
.error-card { color: #dc2626; }
</style>

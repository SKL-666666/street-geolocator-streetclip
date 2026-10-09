<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { fetchTask, retryTask, confidenceLabel } from '../api'

const props = defineProps({ taskIds: { type: Array, required: true } })
const emit = defineEmits(['view', 'back', 'retry'])

const tasks = ref(new Map())
const retryingId = ref('')
let timer = null

async function poll() {
  let allDone = true
  for (const id of props.taskIds) {
    const t = tasks.value.get(id)
    if (t && ['succeeded', 'failed'].includes(t.status)) continue
    allDone = false
    try {
      tasks.value.set(id, await fetchTask(id))
    } catch {
      /* 下次轮询重试 */
    }
  }
  if (!allDone) timer = setTimeout(poll, 1500)
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

const sorted = () => props.taskIds.map((id) => tasks.value.get(id)).filter(Boolean)

onMounted(poll)
onUnmounted(() => timer && clearTimeout(timer))
</script>

<template>
  <div class="batch-wrap">
    <div class="card batch-head">
      <h2>批量分析（{{ taskIds.length }} 张）</h2>
      <button class="btn btn-ghost" @click="emit('back')">← 继续上传</button>
    </div>

    <div class="card-list">
      <div v-for="t in sorted()" :key="t.task_id" class="card row">
        <div class="row-main">
          <div class="fname">{{ t.filename }}</div>
          <div class="muted">
            <span class="badge" :class="t.confidence_level">{{ confidenceLabel(t.confidence_level) }}</span>
            <template v-if="t.status === 'succeeded'"> · {{ t.message }}</template>
            <template v-else-if="t.status === 'failed'"> · ❌ {{ t.error }}</template>
            <template v-else>{{ t.message || '排队中…' }}</template>
          </div>
          <!-- 任务进度条（与结果页同风格） -->
          <div v-if="!['succeeded', 'failed'].includes(t.status)" class="row-progress">
            <div class="progress-bar">
              <div class="progress-fill" :style="{ width: (t.progress || 0) + '%' }"></div>
            </div>
            <span class="progress-pct">{{ t.progress || 0 }}%</span>
          </div>
          <template v-if="t.scene">
            <div class="muted hyp" v-for="h in t.scene.country_hypotheses.slice(0, 2)" :key="h.country">
              🌍 {{ h.country_zh || h.country }} {{ (h.confidence * 100).toFixed(0) }}%
            </div>
          </template>
          <template v-if="t.gps">
            <div class="muted hyp">📍 {{ t.gps.lat.toFixed(5) }}, {{ t.gps.lon.toFixed(5) }}（EXIF）</div>
          </template>
        </div>
        <div class="row-actions">
          <button
            v-if="t.status === 'failed' && t.has_image"
            class="btn btn-sm"
            @click="onRetry(t.task_id)"
          >
            {{ retryingId === t.task_id ? '重试中…' : '🔄 重试' }}
          </button>
          <button class="btn btn-sm" @click="emit('view', t.task_id)">查看详情</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.batch-wrap { max-width: 720px; margin: 0 auto; }
.batch-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.btn-ghost { background: var(--border); color: var(--text-muted); }
.btn-ghost:hover { background: var(--border); }
.card-list { display: flex; flex-direction: column; gap: 10px; }
.row { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 14px 16px; }
.row-main { flex: 1; min-width: 0; }
.row-actions { display: flex; gap: 8px; align-items: center; }
.fname { font-weight: 600; margin-bottom: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hyp { font-size: 12px; margin-top: 2px; }
.btn-sm { padding: 8px 14px; font-size: 13px; flex-shrink: 0; }
.row-progress { display: flex; align-items: center; gap: 10px; margin-top: 8px; }
.progress-bar { flex: 1; height: 8px; background: var(--border); border-radius: 999px; overflow: hidden; }
.progress-fill { height: 100%; background: linear-gradient(90deg, var(--primary), #3b82f6); transition: width 0.3s linear; }
.progress-pct { font-size: 12px; font-weight: 600; color: var(--text-muted); min-width: 36px; text-align: right; }
</style>

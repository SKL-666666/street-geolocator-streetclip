<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { fetchTask, retryTask, confidenceLabel } from '../api'
import MapPanel from '../components/MapPanel.vue'

const props = defineProps({ taskId: String })
const emit = defineEmits(['back', 'retried'])

const task = ref(null)
const error = ref('')
const retrying = ref(false)
const retryError = ref('')
const shownProgress = ref(0)
let timer = null
let smoothTimer = null

const MODE_LABEL = { fast: '快速', balanced: '平衡', deep: '深度' }
const SRC_LABEL = {
  exif: 'EXIF GPS', llm: 'LLM 假设', prior: '视觉先验', geocode: '地理编码',
  streetview: '街景', kartaview: 'KartaView 街景', country: '国家级示意（几何中心）',
  fallback: '默认示意点（无证据）',
}

async function poll() {
  if (!props.taskId) return
  try {
    task.value = await fetchTask(props.taskId)
    if (!['succeeded', 'failed'].includes(task.value.status)) {
      timer = setTimeout(poll, 600)
    }
  } catch (e) {
    error.value = e.message
    timer = setTimeout(poll, 2000)
  }
}

// 一键重试：后端用保存的原图重新分析（沿用原任务模式/范围）
async function onRetry() {
  if (retrying.value || !task.value) return
  retrying.value = true
  retryError.value = ''
  try {
    const newId = await retryTask(task.value.task_id)
    emit('retried', newId)
  } catch (e) {
    retryError.value = e.message
  } finally {
    retrying.value = false
  }
}

// 平滑进度：基本匀速推进（每 120ms 固定步长，不追后端跳变值），完成时冲到 100
// STEP=0.55 → 0→95 约 20.8 秒（覆盖 local 模式 7~20s 典型耗时）
const STEP = 0.55
function smoothLoop() {
  const t = task.value
  if (!t) return
  const done = ['succeeded', 'failed'].includes(t.status)
  if (done) {
    shownProgress.value = 100
  } else {
    shownProgress.value = Math.min(95, shownProgress.value + STEP)
  }
}

const finished = computed(() => task.value && ['succeeded', 'failed'].includes(task.value.status))
const pct = computed(() => Math.round(shownProgress.value))
const hasCountryCentroid = computed(() =>
  (task.value?.candidates || []).some((c) => c.source === 'country')
)
const sortedCandidates = computed(() =>
  [...(task.value?.candidates || [])]
    .map((c, idx) => ({ c, idx }))          // 记住原始下标（地图 markers 按原始数组对齐）
    .sort((a, b) => b.c.score - a.c.score)
)

// 降级/超时判断：LLM 超时降级时提示重试
const llmTimeout = computed(() =>
  task.value?.meta?.degraded === true || (task.value?.message || '').includes('超时')
)

// 余额不足：明确提示充值/换 Key（重试无意义）
const balanceIssue = computed(() => task.value?.meta?.insufficient_balance === true)

const focusCandidate = ref(null)  // 地图要聚焦的候选对象（不依赖下标，杜绝错位）

// 准确度短标签：去掉括号及内容，只留"城市级/国家级"等主标签
function shortHint(c) {
  const h = c.accuracy_hint || ''
  const idx = h.indexOf('（')
  return idx > 0 ? h.slice(0, idx) : h
}

function onPickCandidate(index) {
  const item = sortedCandidates.value[index]
  focusCandidate.value = item ? item.c : null
}

onMounted(() => {
  smoothTimer = setInterval(smoothLoop, 120)
  poll()
})
onUnmounted(() => {
  timer && clearTimeout(timer)
  smoothTimer && clearInterval(smoothTimer)
})
</script>

<template>
  <div v-if="!task && !error" class="card loading">
    <div class="spinner"></div>
    <div>任务 {{ taskId }} 加载中…</div>
  </div>

  <!-- 轮询失败：显示错误与重试（不无限转圈） -->
  <div v-else-if="error" class="card error-card">
    <h2>❌ 结果加载失败</h2>
    <div class="mono">{{ error }}</div>
    <button class="btn" style="margin-top: 16px" @click="error = ''; poll()">重试</button>
  </div>

  <div v-else>
    <!-- 进度条 -->
    <div v-if="!finished" class="card progress-card">
      <div class="progress-head">
        <span>{{ task.message || '处理中' }}</span>
        <span class="muted">{{ pct }}%</span>
      </div>
      <div class="progress-bar"><div class="progress-fill" :style="{ width: pct + '%' }"></div></div>
      <div class="muted" style="margin-top: 8px">
        阶段：{{ task.stage }} · 模式：{{ MODE_LABEL[task.mode] || task.mode }} · 请稍候
      </div>
    </div>

    <!-- 失败 -->
    <div v-else-if="task.status === 'failed'" class="card error-card">
      <h2>❌ 分析失败</h2>
      <div class="mono">{{ task.error }}</div>
      <div class="retry-row">
        <button class="btn" style="margin-top: 16px" :disabled="retrying" @click="onRetry">
          {{ retrying ? '重试中…' : '🔄 重试此图（无需重新上传）' }}
        </button>
        <button class="btn btn-ghost" style="margin-top: 16px" @click="emit('back')">返回上传页</button>
      </div>
      <div v-if="retryError" class="muted" style="margin-top: 8px; color: #dc2626">{{ retryError }}</div>
    </div>

    <!-- 成功 -->
    <div v-else>
      <div class="card result-head">
        <div class="result-title">
          <h2>定位结果</h2>
          <span class="badge" :class="task.confidence_level">
            {{ confidenceLabel(task.confidence_level) }}
          </span>
          <span class="badge">{{ MODE_LABEL[task.mode] || task.mode }}模式</span>
          <span class="badge" :class="{ exact: task.meta?.scope === 'world' }">
            {{ task.meta?.scope === 'cn' ? '🇨🇳 中国模式' : task.meta?.scope === 'no-cn' ? '除中国大陆' : '全世界' }}
          </span>
        </div>
        <div class="muted">
          耗时 {{ (task.elapsed_ms / 1000).toFixed(1) }}s ·
          <template v-if="task.meta?.tokens">
            LLM 消耗 {{ (task.meta.tokens.prompt / 1000).toFixed(1) }}k 输入 + {{ (task.meta.tokens.completion / 1000).toFixed(1) }}k 输出（{{ task.meta.tokens.calls }} 次调用）·
          </template>
          {{ task.message }}<template v-if="task.gps"> · 📍 {{ task.gps.lat.toFixed(5) }}, {{ task.gps.lon.toFixed(5) }}</template>
        </div>
        <button class="btn btn-ghost" @click="emit('back')">← 分析另一张</button>
        <div v-if="llmTimeout && !balanceIssue" class="timeout-note" style="margin-top: 10px">
          ⏱️ LLM 服务繁忙/超时，本次为降级结果（可稍后重传分析）。
        </div>
        <div v-if="balanceIssue" class="balance-note">
          💳 <b>LLM 账号余额不足</b>：请到智谱开放平台（open.bigmodel.cn）充值，或在设置页更换自己的 API Key。
          当前结果已降级为本地先验/检索定位。
        </div>
        <div class="export-row">
          <a class="btn btn-sm" :href="`/api/tasks/${task.task_id}/export?format=geojson`" download>导出 GeoJSON</a>
          <a class="btn btn-sm" :href="`/api/tasks/${task.task_id}/export?format=kml`" download>导出 KML</a>
          <a class="btn btn-sm" :href="`/api/tasks/${task.task_id}/export?format=csv`" download>导出 CSV</a>
        </div>
      </div>

      <!-- EXIF GPS 参考信息（已移除"直接定位"：仅供对比，定位基于图像分析） -->
      <div v-if="task.gps" class="card">
        <div class="exif-note">📷 {{ task.meta?.exif_note || `照片自带 EXIF GPS：${task.gps.lat.toFixed(5)}, ${task.gps.lon.toFixed(5)}` }}（仅参考，本次定位基于图像分析）</div>
      </div>

      <!-- LLM 路径 -->
      <div v-if="task.scene">
        <div v-if="task.scene.is_street_view === false" class="card">
          <h3>⚠️ 这不是街景图片</h3>
          <div class="muted">
            场景类型：{{ task.scene.scene_type }} ·
            <template v-if="sortedCandidates.length">以下位置为按地理线索的<b>近似定位</b>（非街道画面）</template>
            <template v-else>{{ task.scene.summary || 'LLM 判断无法定位' }}</template>
          </div>
        </div>

        <!-- 地图（全宽） -->
        <div class="card map-card">
          <MapPanel :candidates="task.candidates" :focus-candidate="focusCandidate" />
          <div v-if="hasCountryCentroid" class="country-note">
            🧭 <b>国家级示意</b>：黄圈表示真实位置可能在此国家范围内，红点为该国首都城市（示意）。
          </div>
        </div>

        <!-- 底部单栏：国家-城市-概率（点击切换地图）+ 推理依据 -->
        <div class="card results-bar">
          <!-- 空结果兜底：无论如何都给用户可读的结论 -->
          <div v-if="!sortedCandidates.length" class="empty-result">
            <div class="empty-title">❌ 无法定位：未找到足够证据</div>
            <div class="muted" v-if="task.scene?.summary">「{{ task.scene.summary }}」</div>
            <div class="muted" v-if="task.scene?.visible_text?.length">
              可见文字：{{ task.scene.visible_text.join(' · ').slice(0, 120) }}
            </div>
            <div class="muted" v-if="task.scene?.languages?.length">
              语言线索：{{ task.scene.languages.join(' · ') }}
            </div>
            <div class="muted" v-if="task.message">{{ task.message }}</div>
            <template v-if="llmTimeout">
              <div class="timeout-note">
                ⏱️ LLM 服务超时，未生成定位结果（LLM 繁忙时可稍后重传分析）。
              </div>
            </template>
            <div v-else class="muted" style="margin-top: 8px">
              这张图确实缺乏可定位特征；可尝试「深度」模式，或裁剪局部（路牌/招牌）后重传。
            </div>
          </div>

          <div
            v-for="(item, i) in sortedCandidates"
            :key="item.c.rank + '-' + i"
            class="bar-row"
            :class="{ top: i === 0 }"
            @click="onPickCandidate(i)"
          >
            <span class="bar-country">
              {{ item.c.country || '—' }}<span v-if="item.c.country_zh && item.c.country_zh !== item.c.country" class="zh-tag">{{ item.c.country_zh }}</span>
            </span>
            <span class="bar-city">
              {{ item.c.city || '—' }}<span v-if="item.c.city_zh && item.c.city_zh !== item.c.city" class="zh-tag">{{ item.c.city_zh }}</span>
            </span>
            <span class="bar-prob">{{ (item.c.score * 100).toFixed(0) }}%</span>
            <span class="bar-hint" v-if="shortHint(item.c)">⚠ {{ shortHint(item.c) }}</span>
          </div>
        </div>

        <!-- OCR 文字识别 + 搜索验证 + 百度识图 -->
        <div v-if="task.facts && task.facts.length" class="card enhance-card">
          <h3>🔬 增强分析</h3>
          <div v-for="f in task.facts" :key="f.tool + f.query" class="enhance-row">
            <span class="badge enhance-badge">{{ f.tool === 'ocr' ? '📝 OCR' : f.tool === 'tavily' ? '🔍 Tavily' : f.tool === 'baidu' ? '📷 百度' : f.tool }}</span>
            <div class="enhance-body">
              <div class="enhance-summary">{{ f.summary }}</div>
              <div v-if="f.ok" class="enhance-detail muted">✅ 有效信号，已参与加权</div>
              <div v-else class="enhance-detail muted warn">⚠ 未产生有效信号</div>
            </div>
          </div>
        </div>

        <!-- 判断理由 -->
        <div v-if="task.candidates && task.candidates.length" class="card reason-card">
          <h3>💡 判断理由</h3>
          <div v-for="c in task.candidates.slice(0, 3)" :key="c.rank" class="reason-row">
            <div class="reason-rank">#{{ c.rank }}</div>
            <div class="reason-content">
              <div class="reason-location"><b>{{ c.country_zh || c.country }}</b> {{ c.city_zh || c.city || '' }}</div>
              <div class="reason-score">置信度: {{ (c.score * 100).toFixed(0) }}% · {{ c.accuracy_hint || '' }}</div>
              <div v-for="(e, i) in (c.evidence || [])" :key="i" class="reason-evidence muted">· {{ e }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.loading { display: flex; flex-direction: column; align-items: center; gap: 16px; padding: 60px; }
.spinner {
  width: 36px; height: 36px;
  border: 4px solid #e5e7eb; border-top-color: #2563eb;
  border-radius: 50%;
  animation: spin 0.9s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.progress-card { margin-bottom: 16px; }
.progress-head { display: flex; justify-content: space-between; margin-bottom: 8px; }
.progress-bar { height: 8px; background: #e5e7eb; border-radius: 999px; overflow: hidden; }
.progress-fill { height: 100%; background: linear-gradient(90deg, #2563eb, #3b82f6); transition: width 0.2s linear; }

.error-card h2 { margin-bottom: 12px; }

.result-head { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; }
.result-title { display: flex; align-items: center; gap: 12px; }
.btn-ghost { background: #e5e7eb; color: #374151; align-self: flex-start; }
.btn-ghost:hover { background: #d1d5db; }
.retry-row { display: flex; align-items: center; gap: 10px; }
.export-row { display: flex; gap: 8px; }
.btn-sm { padding: 6px 12px; font-size: 13px; text-decoration: none; }
.enhance-card h3 { margin-bottom: 10px; }
.enhance-row { display: flex; gap: 10px; padding: 8px 0; border-bottom: 1px solid #f1f5f9; align-items: flex-start; }
.enhance-badge { white-space: nowrap; font-size: 12px; padding: 3px 8px; }
.enhance-body { flex: 1; }
.enhance-summary { font-size: 13px; color: #374151; }
.enhance-detail { font-size: 12px; margin-top: 2px; }
.enhance-detail.warn { color: #92400e; }
.reason-card h3 { margin-bottom: 10px; }
.reason-row { display: flex; gap: 10px; padding: 6px 0; }
.reason-rank { font-weight: 700; color: #2563eb; font-size: 14px; min-width: 24px; }
.reason-content { flex: 1; }
.reason-location { font-size: 14px; margin-bottom: 2px; }
.reason-score { font-size: 12px; color: #6b7280; }
.reason-evidence { font-size: 12px; color: #4b5563; margin-top: 2px; line-height: 1.4; }
.exact-banner {
  background: #d1fae5; color: #065f46;
  padding: 10px 14px; border-radius: 8px; margin-bottom: 12px;
}
.exif-note {
  background: #eff6ff; color: #1e40af;
  padding: 10px 14px; border-radius: 8px; font-size: 13px;
}
.balance-note {
  background: #fef2f2; color: #991b1b;
  border: 1px solid #fca5a5; border-radius: 8px;
  padding: 10px 14px; font-size: 13px;
}

.map-card { padding: 12px; }
.country-note {
  margin-top: 10px;
  background: #fffbeb; color: #92400e;
  border: 1px solid #fcd34d;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 12px;
}

/* 底部单栏 */
.results-bar { margin-top: 16px; padding: 8px 12px; }
.bar-row {
  display: grid;
  grid-template-columns: 1.4fr 1.2fr 64px auto;
  gap: 10px;
  align-items: center;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
}
.bar-row:hover { background: #eff6ff; }
.bar-row.top { background: #fef2f2; }
.bar-country { font-weight: 700; font-size: 14px; }
.bar-city { font-size: 14px; }
.zh-tag { font-size: 12px; color: #6b7280; margin-left: 4px; }
.bar-prob { font-weight: 700; color: #b45309; text-align: right; }
.bar-hint { font-size: 11px; color: #b45309; }

.empty-result { padding: 6px 2px 10px; }
.empty-title { font-weight: 700; font-size: 15px; color: #b91c1c; margin-bottom: 6px; }
.empty-result .muted { margin-top: 3px; }
.timeout-note {
  margin-top: 10px; padding: 8px 12px;
  background: #fef3c7; color: #92400e;
  border-radius: 8px; font-size: 13px;
}

.card + .card { margin-top: 16px; }

/* 竖屏/窄屏适配（16:9 → 9:16）：候选行换行堆叠，地图高度随可用高度缩放 */
@media (max-width: 640px) {
  .bar-row {
    grid-template-columns: 1fr auto;
    grid-template-areas:
      "country prob"
      "city hint";
    row-gap: 4px;
  }
  .bar-country { grid-area: country; }
  .bar-city { grid-area: city; }
  .bar-prob { grid-area: prob; }
  .bar-hint { grid-area: hint; }
}
@media (max-height: 700px) {
  .map-card .map-panel { height: 300px; }
}
h3 { margin-bottom: 8px; }
</style>

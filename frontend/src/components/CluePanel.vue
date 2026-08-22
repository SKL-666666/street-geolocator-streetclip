<script setup>
import { computed } from 'vue'

const props = defineProps({ scene: { type: Object, required: true } })

const rows = computed(() => {
  const s = props.scene
  return [
    { label: '可见文字', value: s.visible_text?.length ? s.visible_text.join(' · ') : '—' },
    { label: '语言', value: s.languages?.length ? s.languages.join(', ') : '—' },
    { label: '交通标志', value: s.traffic_signs?.length ? s.traffic_signs.join(' · ') : '—' },
    { label: '建筑风格', value: s.architecture?.length ? s.architecture.join(' · ') : '—' },
    { label: '植被', value: s.vegetation?.length ? s.vegetation.join(' · ') : '—' },
    { label: '地形', value: s.terrain?.length ? s.terrain.join(' · ') : '—' },
    { label: '天气', value: s.weather?.length ? s.weather.join(' · ') : '—' },
    { label: '行驶方向', value: s.driving_side === 'unknown' ? '—' : (s.driving_side === 'left' ? '左侧通行' : '右侧通行') },
    { label: '高辨识度特征', value: s.unique_features?.length ? s.unique_features.join(' · ') : '—' },
  ]
})
</script>

<template>
  <div class="card">
    <h3>🧠 LLM 推理依据</h3>
    <div v-if="scene.summary" class="summary">「{{ scene.summary }}」</div>

    <div v-if="scene.country_hypotheses?.length || scene.city_hypotheses?.length" class="hypos">
      <div class="hypo-row" v-for="h in scene.country_hypotheses" :key="'c' + h.country">
        <span class="hypo-name">🌍 {{ h.country_zh || h.country }}</span>
        <span class="muted hypo-en" v-if="h.country_zh && h.country_zh !== h.country">{{ h.country }}</span>
        <span class="hypo-bar"><span :style="{ width: (h.confidence * 100) + '%' }"></span></span>
        <span class="hypo-pct">{{ (h.confidence * 100).toFixed(0) }}%</span>
        <span class="muted hypo-reason">{{ h.reasoning }}</span>
      </div>
      <div class="hypo-row" v-for="h in scene.city_hypotheses" :key="'city' + h.city">
        <span class="hypo-name">🏙️ {{ h.city }}</span>
        <span class="muted hypo-en" v-if="h.country_zh || h.country">（{{ h.country_zh || h.country }}）</span>
        <span class="hypo-bar"><span :style="{ width: (h.confidence * 100) + '%' }"></span></span>
        <span class="hypo-pct">{{ (h.confidence * 100).toFixed(0) }}%</span>
        <span class="muted hypo-reason">{{ h.reasoning }}</span>
      </div>
    </div>

    <table class="clue-table">
      <tr v-for="row in rows" :key="row.label">
        <td class="clue-label">{{ row.label }}</td>
        <td>{{ row.value }}</td>
      </tr>
    </table>
    <div class="muted" style="margin-top: 8px">
      整体置信度 {{ (scene.overall_confidence * 100).toFixed(0) }}% ·
      LLM 输出可能包含推测（inferred），请以地图候选与街景影像为准
    </div>
  </div>
</template>

<style scoped>
h3 { margin-bottom: 10px; }
.summary {
  background: #eff6ff; color: #1e40af;
  padding: 8px 12px; border-radius: 8px; margin-bottom: 12px; font-size: 14px;
}
.hypos { margin-bottom: 14px; }
.hypo-row { display: grid; grid-template-columns: 140px auto 1fr 48px; gap: 8px; align-items: center; padding: 5px 0; }
.hypo-name { font-weight: 600; font-size: 14px; }
.hypo-en { font-size: 11px; grid-column: 2; }
.hypo-bar { height: 8px; background: #e5e7eb; border-radius: 999px; overflow: hidden; }
.hypo-bar span { display: block; height: 100%; background: #2563eb; }
.hypo-pct { font-size: 12px; color: #374151; }
.hypo-reason { grid-column: 1 / -1; padding-left: 148px; }

.clue-table { width: 100%; border-collapse: collapse; font-size: 14px; }
.clue-table td { padding: 7px 8px; border-bottom: 1px solid #f1f5f9; vertical-align: top; }
.clue-label { width: 100px; color: #6b7280; font-weight: 500; white-space: nowrap; }
</style>

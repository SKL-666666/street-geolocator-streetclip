<script setup>
import { computed } from 'vue'

const props = defineProps({
  geoKb: { type: Object, default: null },   // { countries: [KBEvidence] }
  facts: { type: Array, default: () => [] }, // [ToolFact]
})

const topCountries = computed(() =>
  (props.geoKb?.countries || []).filter((c) => c.final_score > 0).slice(0, 6)
)

const okFacts = computed(() => props.facts.filter((f) => f.ok))
const failFacts = computed(() => props.facts.filter((f) => !f.ok))

const TOOL_LABEL = { geocode: '📍 地理编码', wiki: '📚 百科查证', timezone: '🕐 时区', streetview: '🛣️ 街景',
  ocr: '📝 OCR 文字识别', tavily: '🔍 搜索验证', baidu: '📷 百度识图' }
</script>

<template>
  <div class="card">
    <h3>🔍 事实核查（超越纯 LLM）</h3>

    <!-- 方案 B：证据矩阵 -->
    <template v-if="topCountries.length">
      <div class="section-title">证据矩阵（知识库 × LLM 融合）</div>
      <table class="kb-table">
        <thead>
          <tr><th>国家</th><th>LLM</th><th>知识库</th><th>融合</th><th>证据</th></tr>
        </thead>
        <tbody>
          <tr v-for="c in topCountries" :key="c.country">
            <td class="country-name">
              {{ c.country_zh || c.country }}
              <span class="muted" style="font-size:11px" v-if="c.country_zh && c.country_zh !== c.country">{{ c.country }}</span>
              <span v-if="c.unverified" class="unverified" title="不在知识库中，LLM 声称无法核实（已降信）">⚠ 未核实</span>
            </td>
            <td>
              <div class="mini-bar"><span :style="{ width: (c.llm_confidence * 100) + '%' }"></span></div>
              <span class="pct">{{ (c.llm_confidence * 100).toFixed(0) }}%</span>
            </td>
            <td>
              <div class="mini-bar kb"><span :style="{ width: (c.kb_score * 100) + '%' }"></span></div>
              <span class="pct">{{ (c.kb_score * 100).toFixed(0) }}%</span>
            </td>
            <td class="final-score">{{ (c.final_score * 100).toFixed(0) }}%</td>
            <td>
              <div v-for="s in c.supporting_clues" :key="s" class="clue support">✓ {{ s }}</div>
              <div v-for="s in c.contradicting_clues" :key="s" class="clue conflict">✗ {{ s }}</div>
            </td>
          </tr>
        </tbody>
      </table>
    </template>
    <div v-else-if="geoKb" class="muted">知识库未命中强线索（无匹配维度），保持 LLM 判断。</div>

    <!-- 方案 D：外部查证记录 -->
    <template v-if="okFacts.length">
      <div class="section-title">外部查证（工具调用）</div>
      <div v-for="f in okFacts" :key="f.tool + f.query" class="fact-row">
        <span class="badge">{{ TOOL_LABEL[f.tool] || f.tool }}</span>
        <div class="fact-body">
          <div class="fact-summary">{{ f.summary }}</div>
          <div v-for="r in f.results.slice(0, 2)" :key="r.url || r.name" class="fact-detail muted">
            · {{ r.title || r.name }}
            <template v-if="r.snippet"> — {{ r.snippet }}</template>
            <template v-else-if="r.display_name">（{{ r.display_name }}）</template>
          </div>
        </div>
      </div>
    </template>
    <div v-if="failFacts.length" class="muted" style="margin-top: 8px">
      查证受限：{{ failFacts.map((f) => f.summary).join('；') }}
    </div>
  </div>
</template>

<style scoped>
h3 { margin-bottom: 12px; }
.section-title { font-size: 13px; color: #374151; font-weight: 600; margin: 12px 0 8px; }

.kb-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.kb-table th, .kb-table td { padding: 6px 8px; border-bottom: 1px solid #f1f5f9; text-align: left; vertical-align: top; }
.kb-table th { color: #6b7280; font-weight: 500; }
.country-name { font-weight: 600; white-space: nowrap; }
.unverified { font-size: 11px; color: #b45309; background: #fef3c7; border-radius: 4px; padding: 1px 5px; margin-left: 4px; }
.mini-bar { width: 70px; height: 6px; background: #e5e7eb; border-radius: 999px; overflow: hidden; display: inline-block; vertical-align: middle; }
.mini-bar span { display: block; height: 100%; background: #2563eb; }
.mini-bar.kb span { background: #059669; }
.pct { font-size: 11px; color: #6b7280; margin-left: 4px; }
.final-score { font-weight: 700; color: #b45309; }
.clue { font-size: 12px; margin: 2px 0; }
.clue.support { color: #065f46; }
.clue.conflict { color: #b91c1c; }

.fact-row { display: flex; gap: 10px; padding: 8px 0; border-bottom: 1px solid #f1f5f9; }
.fact-body { flex: 1; }
.fact-summary { font-size: 14px; }
.fact-detail { font-size: 12px; margin-top: 2px; }
</style>

<template>
  <div class="gainers-page">
    <header class="gp-hero">
      <button type="button" class="gp-back" @click="$emit('back')" aria-label="返回首页">
        <span class="gp-back-icon" aria-hidden="true">←</span>
        首页
      </button>
      <div class="gp-hero-main">
        <div class="gp-hero-kicker">市场 · 强势股</div>
        <h1 class="gp-title">股票涨幅榜</h1>
        <p class="gp-subtitle">完整榜单 · 点击任意一行查看简要分析与行情入口</p>
      </div>
      <div class="gp-hero-meta">
        <span class="gp-pulse" aria-hidden="true"></span>
        <span>数据定时刷新</span>
      </div>
    </header>

    <section v-if="displayBoardBullets.length" class="gp-insights" aria-label="盘面综述">
      <div v-if="boardInsightLoading" class="gp-ai-hint">
        <span class="gp-ai-spinner" aria-hidden="true" />
        正在生成盘面综述…
      </div>
      <div
        v-for="(b, i) in displayBoardBullets"
        :key="i"
        class="gp-insight"
      >
        <span class="gp-insight-dot" aria-hidden="true" />
        <span class="gp-insight-text">{{ b }}</span>
      </div>
      <div v-if="boardInsightTag" class="gp-ai-tag">{{ boardInsightTag }}</div>
    </section>

    <div class="gp-layout">
      <section class="gp-board" aria-label="涨幅排行榜">
        <div class="gp-board-head">
          <h2 class="gp-board-title">排行榜</h2>
          <span class="gp-board-count">{{ items.length }} 只</span>
        </div>

        <div v-if="!items.length" class="gp-empty">
          <div class="gp-empty-icon" aria-hidden="true">📊</div>
          <p>暂无榜单数据</p>
          <p class="gp-empty-hint">请稍候自动刷新，或返回首页查看 Top10</p>
        </div>

        <template v-else>
          <div class="gp-table-head" aria-hidden="true">
            <span class="gp-col-rank">排名</span>
            <span class="gp-col-name">标的</span>
            <span class="gp-col-pct">涨跌幅</span>
          </div>
          <ul class="gp-rows" role="list">
            <li
              v-for="(t, idx) in items"
              :key="t.name + idx"
              role="listitem"
              class="gp-row"
              :class="{
                'gp-row--selected': isSelected(t),
                [`gp-row--medal-${idx + 1}`]: idx < 3,
              }"
              tabindex="0"
              @click="selected = t"
              @keydown.enter.prevent="selected = t"
              @keydown.space.prevent="selected = t"
            >
              <div class="gp-col-rank">
                <span class="gp-rank-badge" :class="rankBadgeClass(idx)">{{ idx + 1 }}</span>
              </div>
              <div class="gp-col-name">
                <div class="gp-stock-name">{{ t.name }}</div>
                <div v-if="t.leader" class="gp-stock-code">{{ t.leader }}</div>
              </div>
              <div class="gp-col-pct">
                <span
                  class="gp-pct-pill"
                  :class="pctClass(t.pct_chg)"
                >
                  {{ formatPctDisplay(t.pct_chg) }}
                </span>
              </div>
            </li>
          </ul>
        </template>
      </section>

      <aside class="gp-side" aria-label="个股分析">
        <div class="gp-side-inner">
          <div class="gp-side-header">
            <h3 class="gp-side-title">{{ selected ? '个股透视' : '尚未选择' }}</h3>
            <span v-if="selected" class="gp-side-rank">第 {{ selectedRank }} 名</span>
          </div>

          <template v-if="selected">
            <div class="gp-side-stock">
              <div class="gp-side-name">{{ selected.name }}</div>
              <div v-if="selected.leader" class="gp-side-code">{{ selected.leader }}</div>
            </div>
            <div class="gp-metric">
              <span class="gp-metric-label">当前涨幅（榜单）</span>
              <span class="gp-metric-value" :class="pctClass(selected.pct_chg)">
                {{ fmtPct(selected.pct_chg) }}
              </span>
            </div>
            <div v-if="stockQuoteFacts" class="gp-quote-strip">
              <span class="gp-quote-strip-label">公开市场行情（数据来源：新浪财经）</span>
              {{ stockQuoteFacts }}
            </div>

            <div class="gp-side-analysis">
              <div class="gp-side-analysis-head">
                <span class="gp-side-analysis-title">分析要点</span>
                <span v-if="stockInsightSourceTag" class="gp-side-analysis-tag">{{ stockInsightSourceTag }}</span>
              </div>
              <div v-if="stockInsightLoading" class="gp-ai-hint gp-ai-hint--side">
                <span class="gp-ai-spinner" aria-hidden="true" />
                正在汇总行情与榜单数据并生成文字说明…
              </div>
              <template v-else-if="stockInsightError">
                <p class="gp-side-copy gp-side-error">{{ stockInsightError }}</p>
                <p class="gp-side-foot">请确认已启动后端（端口 5000）、浏览器控制台与 Network 里 <code>/api/topics/stock-insight</code> 是否报错。</p>
              </template>
              <template v-else-if="stockInsightLines.length">
                <p
                  v-for="(line, i) in stockInsightLines"
                  :key="i"
                  class="gp-side-copy"
                >
                  {{ line }}
                </p>
                <p v-if="stockInsightDisclaimer" class="gp-side-foot">
                  {{ stockInsightDisclaimer }}
                </p>
              </template>
              <p v-else class="gp-side-copy gp-side-muted">
                暂无解读内容。请点击左侧其他股票重试；若持续为空，多为接口未返回数据或网络异常。
              </p>
            </div>

            <button type="button" class="gp-cta" @click.stop="$emit('pick', selected)">
              查看该股行情
            </button>
          </template>
          <div v-else class="gp-side-placeholder">
            <div class="gp-placeholder-graphic" aria-hidden="true">
              <span></span><span></span><span></span>
            </div>
            <p>在左侧列表中点击任意股票，</p>
            <p>即可查看简要分析与打开行情。</p>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { postTopicsBoardInsight, postTopicsStockInsight } from './api/client'

const props = defineProps({
  items: {
    type: Array,
    default: () => [],
  },
  analysis: {
    type: Object,
    default: () => ({ title: '盘面分析', bullets: [] }),
  },
})

defineEmits(['back', 'pick'])

const selected = ref(null)

/** 盘面：大模型返回的要点；null 表示尚未拉到，用 props.analysis 顶一下 */
const boardBulletsLlm = ref(null)
const boardInsightSource = ref('')
const boardInsightLoading = ref(false)

const displayBoardBullets = computed(() => {
  if (boardBulletsLlm.value && boardBulletsLlm.value.length) return boardBulletsLlm.value
  return props.analysis?.bullets || []
})

const boardInsightTag = computed(() => {
  if (boardInsightLoading.value) return ''
  if (boardInsightSource.value === 'llm') return '盘面综述 · 语言模型辅助撰写'
  if (boardInsightSource.value === 'template') {
    return '盘面综述 · 统计归纳（未启用语言模型或已达当日调用上限）'
  }
  return ''
})

const avgPct = computed(() => {
  const arr = (props.items || [])
    .map((x) => Number(x?.pct_chg))
    .filter(Number.isFinite)
  if (!arr.length) return 0
  return arr.reduce((a, b) => a + b, 0) / arr.length
})

/** 个股解读 */
const stockInsightLines = ref([])
const stockInsightDisclaimer = ref('')
const stockInsightLoading = ref(false)
const stockQuoteFacts = ref('')
const stockInsightError = ref('')
const stockInsightSource = ref('')
const stockInsightSourceTag = computed(() => {
  if (stockInsightLoading.value || stockInsightError.value) return ''
  const s = stockInsightSource.value
  if (s === 'llm') return '语言模型辅助'
  if (s === 'template') return '统计归纳'
  return ''
})
let stockInsightTimer = null
let stockAbort = null

async function refreshBoardInsight() {
  const arr = props.items || []
  if (!arr.length) {
    boardBulletsLlm.value = null
    boardInsightSource.value = ''
    return
  }
  boardInsightLoading.value = true
  try {
    const payload = {
      items: arr.slice(0, 40).map((x) => ({
        name: x?.name,
        leader: x?.leader,
        pct_chg: x?.pct_chg,
      })),
    }
    const json = await postTopicsBoardInsight(payload)
    if (json.code === 200 && json.data?.bullets?.length) {
      boardBulletsLlm.value = json.data.bullets
      boardInsightSource.value = json.data.source || ''
    }
  } catch (e) {
    console.error('盘面 AI 解读失败', e)
  } finally {
    boardInsightLoading.value = false
  }
}

watch(
  () => props.items,
  () => {
    void refreshBoardInsight()
  },
  { deep: true, immediate: true },
)

async function runStockInsight(s) {
  stockAbort?.abort()
  if (!s) {
    stockInsightLines.value = []
    stockInsightDisclaimer.value = ''
    stockQuoteFacts.value = ''
    stockInsightError.value = ''
    stockInsightSource.value = ''
    return
  }
  const ac = new AbortController()
  stockAbort = ac
  stockInsightLoading.value = true
  stockInsightLines.value = []
  stockInsightDisclaimer.value = ''
  stockQuoteFacts.value = ''
  stockInsightError.value = ''
  stockInsightSource.value = ''
  const idx = (props.items || []).findIndex(
    (x) => x?.leader === s?.leader && x?.name === s?.name,
  )
  const rank = idx >= 0 ? idx + 1 : 0
  const board_top = (props.items || []).slice(0, 12).map((x) => ({
    name: x?.name,
    leader: x?.leader,
    pct_chg: x?.pct_chg,
  }))
  try {
    const json = await postTopicsStockInsight(
      {
        name: s.name,
        leader: s.leader,
        pct_chg: s.pct_chg,
        rank,
        avg_pct: avgPct.value,
        board_top,
      },
      { signal: ac.signal },
    )
    if (ac.signal.aborted) return
    if (json.code === 200 && json.data?.lines?.length) {
      stockInsightLines.value = json.data.lines
      stockInsightDisclaimer.value = json.data.disclaimer || ''
      stockInsightSource.value = json.data.source || ''
      const q = json.data.quote_snapshot
      if (q && q.price != null) {
        stockQuoteFacts.value = `现价 ${q.price} · 开 ${q.open} 高 ${q.high} 低 ${q.low} · 较昨收 ${q.pct_chg}% · ${q.update_time || ''}`
      } else {
        stockQuoteFacts.value = '（本次未拉到该股新浪快照，解读仅依据涨幅榜统计）'
      }
    } else {
      stockInsightError.value =
        json?.msg ||
        (json?.code === 200 ? '接口未返回解读段落（lines 为空）' : `解读接口异常（code=${json?.code ?? '?' }）`)
    }
  } catch (e) {
    if (e?.name === 'AbortError') return
    console.error('个股 AI 解读失败', e)
    stockInsightError.value = `请求失败：${e?.message || e || '未知错误'}`
  } finally {
    if (!ac.signal.aborted) stockInsightLoading.value = false
  }
}

watch(
  selected,
  (s) => {
    clearTimeout(stockInsightTimer)
    if (!s) {
      stockInsightLines.value = []
      stockInsightDisclaimer.value = ''
      stockQuoteFacts.value = ''
      stockInsightError.value = ''
      stockInsightSource.value = ''
      stockInsightLoading.value = false
      return
    }
    stockInsightTimer = setTimeout(() => void runStockInsight(s), 320)
  },
  { flush: 'post' },
)

onBeforeUnmount(() => {
  clearTimeout(stockInsightTimer)
  stockAbort?.abort()
})

function isSelected(t) {
  if (!selected.value || !t) return false
  return (
    selected.value.leader === t.leader &&
    selected.value.name === t.name
  )
}

function pctClass(pct) {
  const n = Number(pct)
  if (!Number.isFinite(n) || pct === null) return 'gp-neutral'
  if (n > 0) return 'gp-up'
  if (n < 0) return 'gp-down'
  return 'gp-neutral'
}

function formatPctDisplay(pct) {
  if (pct === null || pct === undefined || !Number.isFinite(Number(pct))) return '—'
  const n = Number(pct)
  const sign = n > 0 ? '+' : ''
  return `${sign}${n}%`
}

function rankBadgeClass(idx) {
  if (idx === 0) return 'gp-rank-badge--gold'
  if (idx === 1) return 'gp-rank-badge--silver'
  if (idx === 2) return 'gp-rank-badge--bronze'
  return ''
}

const selectedRank = computed(() => {
  if (!selected.value) return '-'
  const idx = (props.items || []).findIndex(
    (x) => x?.leader === selected.value?.leader && x?.name === selected.value?.name,
  )
  return idx >= 0 ? idx + 1 : '-'
})

function fmtPct(v) {
  const n = Number(v || 0)
  return `${n > 0 ? '+' : ''}${n.toFixed(2)}%`
}
</script>

<style scoped>
.gainers-page { display: grid; gap: var(--space-5); }
.gp-hero, .gp-insights, .gp-board, .gp-side-inner { background: var(--surface); border: 1px solid var(--line); border-radius: 2px; box-shadow: none; }
.gp-hero { padding: 18px 20px; display: grid; gap: var(--space-3); border-left: 4px solid var(--brand); }
.gp-back {
  width: fit-content;
  border: 1px solid var(--line-strong);
  border-radius: 2px;
  background: var(--surface-soft);
  color: var(--text);
  padding: 8px 12px;
  font-size: var(--fs-12);
  font-weight: 800;
  cursor: pointer;
}
.gp-back:hover {
  border-color: var(--brand);
  background: var(--brand-soft);
}
.gp-hero-kicker { font-size: var(--fs-11); color: var(--text-muted); letter-spacing: .1em; text-transform: uppercase; font-weight: 800; }
.gp-title { margin: 0; font-size: clamp(26px, 4vw, 34px); font-weight: 900; line-height: 1.2; }
.gp-subtitle { margin: 6px 0 0; color: var(--text-muted); line-height: 1.7; font-size: var(--fs-14); }
.gp-hero-meta { color: var(--text-muted); font-size: var(--fs-12); font-weight: 700; display: inline-flex; align-items: center; gap: 8px; }
.gp-pulse { width: 8px; height: 8px; border-radius: 999px; background: var(--brand); }
.gp-insights { padding: var(--space-4); display: grid; gap: var(--space-3); }
.gp-insight { border: 1px solid var(--line); border-radius: 12px; background: var(--surface-soft); padding: 10px 12px; display: flex; gap: 10px; font-size: var(--fs-13); line-height: 1.65; }
.gp-insight-dot { width: 6px; height: 6px; margin-top: 8px; border-radius: 999px; background: var(--brand); }
.gp-layout { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: var(--space-5); align-items: start; }
.gp-board { overflow: hidden; padding: 8px; }
.gp-board-head { display: flex; justify-content: space-between; align-items: center; padding: 12px; }
.gp-board-title { font-size: var(--fs-16); font-weight: 900; }
.gp-board-count { font-size: var(--fs-12); color: var(--text-muted); background: var(--surface-soft); border: 1px solid var(--line); border-radius: 2px; padding: 3px 10px; font-weight: 700; }
.gp-table-head { display: grid; grid-template-columns: 56px 1fr 100px; gap: 8px; color: var(--text-muted); font-size: var(--fs-11); font-weight: 800; letter-spacing: .04em; text-transform: uppercase; padding: 8px 12px; }
.gp-rows { list-style: none; margin: 0; padding: 0; }
.gp-row { display: grid; grid-template-columns: 56px 1fr 100px; gap: 8px; align-items: center; margin: 0 0 8px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 2px; background: var(--surface-soft); cursor: pointer; }
.gp-row--selected { border-color: color-mix(in oklab, var(--brand) 45%, var(--line)); box-shadow: 0 8px 20px rgba(15,23,42,.08); }
.gp-rank-badge { width: 32px; height: 32px; border-radius: 2px; display: inline-flex; align-items: center; justify-content: center; border: 1px solid var(--line); font-weight: 900; }
.gp-stock-name { font-weight: 800; }
.gp-stock-code { font-size: var(--fs-12); color: var(--text-muted); margin-top: 2px; }
.gp-pct-pill { display: inline-flex; min-width: 78px; justify-content: center; border-radius: 2px; padding: 6px 10px; font-size: var(--fs-13); font-weight: 900; }
.gp-up { color: var(--danger); background: color-mix(in oklab, var(--danger) 12%, transparent); }
.gp-down { color: var(--success); background: color-mix(in oklab, var(--success) 12%, transparent); }
.gp-neutral { color: var(--text-muted); background: var(--surface-soft); }
.gp-side { position: sticky; top: 84px; }
.gp-side-inner { padding: var(--space-5); }
.gp-side-header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--line); padding-bottom: 10px; margin-bottom: var(--space-3); }
.gp-side-title { font-weight: 900; font-size: var(--fs-14); }
.gp-side-rank { border: 1px solid var(--line); background: var(--surface-soft); border-radius: 2px; font-size: var(--fs-11); font-weight: 800; padding: 3px 8px; color: var(--text-muted); }
.gp-side-name { font-size: var(--fs-18); font-weight: 900; }
.gp-side-code { font-size: var(--fs-12); color: var(--text-muted); margin-top: 3px; }
.gp-metric { display: flex; justify-content: space-between; align-items: center; border: 1px solid var(--line); border-radius: 2px; background: var(--surface-soft); padding: 10px 12px; margin: 10px 0 12px; }
.gp-metric-label { font-size: var(--fs-12); color: var(--text-muted); font-weight: 700; }
.gp-metric-value { font-size: var(--fs-18); font-weight: 900; }
.gp-quote-strip { border: 1px solid var(--line); border-radius: 2px; background: var(--surface-soft); padding: 10px 12px; font-size: var(--fs-12); color: var(--text-muted); line-height: 1.6; margin-bottom: 10px; }
.gp-quote-strip-label { display: block; margin-bottom: 4px; font-size: var(--fs-11); font-weight: 800; }
.gp-side-analysis { border: 1px solid var(--line); border-radius: 2px; background: var(--surface-soft); padding: 12px; margin-bottom: 10px; }
.gp-side-analysis-head { display: flex; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
.gp-side-analysis-title { font-size: var(--fs-13); font-weight: 900; }
.gp-side-analysis-tag { font-size: var(--fs-11); border: 1px solid var(--line); border-radius: 2px; padding: 2px 8px; color: var(--text-muted); }
.gp-side-copy { font-size: var(--fs-13); line-height: 1.7; margin: 0 0 8px; }
.gp-side-foot { color: var(--text-muted); font-size: var(--fs-12); line-height: 1.6; }
.gp-cta { width: 100%; border: 1px solid color-mix(in oklab, var(--brand) 80%, black); background: linear-gradient(135deg, var(--brand), var(--brand-strong)); color: #fff; border-radius: 2px; padding: 11px 12px; font-size: var(--fs-13); font-weight: 900; cursor: pointer; }
.gp-side-placeholder { text-align: center; color: var(--text-muted); font-size: var(--fs-13); line-height: 1.7; padding: 24px 0; }
.gp-placeholder-graphic { display: flex; gap: 8px; justify-content: center; margin-bottom: 12px; opacity: .6; }
.gp-placeholder-graphic span { width: 10px; border-radius: 4px; background: var(--brand); }
.gp-placeholder-graphic span:nth-child(1) { height: 28px; }
.gp-placeholder-graphic span:nth-child(2) { height: 46px; }
.gp-placeholder-graphic span:nth-child(3) { height: 36px; }
.gp-empty { text-align: center; color: var(--text-muted); padding: 40px 12px; }
.gp-ai-hint { display: inline-flex; align-items: center; gap: 8px; color: var(--text-muted); font-size: var(--fs-12); font-weight: 700; margin-bottom: 6px; }
.gp-ai-spinner { width: 14px; height: 14px; border: 2px solid color-mix(in oklab, var(--brand) 30%, transparent); border-top-color: var(--brand); border-radius: 999px; animation: gp-spin .8s linear infinite; }
@keyframes gp-spin { to { transform: rotate(360deg); } }
@media (max-width: 1024px) { .gp-layout { grid-template-columns: 1fr; } .gp-side { position: static; } }
</style>

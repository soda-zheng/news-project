<template>
  <div
    class="modal-mask"
    :style="{ display: open ? 'flex' : 'none' }"
    @click.self="close"
  >
    <div class="modal" role="dialog" aria-modal="true" aria-label="行情查询">
      <div class="modal-hd">
        <div class="modal-title">
          <span>📈</span><span>行情查询</span>
        </div>
        <button class="modal-close" @click="close" aria-label="关闭">✕</button>
      </div>

      <div class="modal-bd">
        <div class="field fx-field">
          <label>标的代码/中文名（例：贵州茅台 / 600519 / sh600519 / hf_CL）</label>
          <input
            class="input-strong"
            v-model.trim="symbol"
            type="text"
            autocomplete="off"
            placeholder="输入关键词可匹配多候选：黄金 / 白银 / 原油 / 贵州茅台"
            @focus="onSymbolFocus"
            @input="onSymbolInput"
          />
          <div v-if="pickerOpen" class="fx-menu">
            <button
              v-for="it in candidates"
              :key="`${it.symbol}-${it.name}`"
              type="button"
              class="fx-item"
              @click="selectCandidate(it)"
            >
              {{ it.name }}（{{ it.symbol }}）
            </button>
            <div v-if="showNoCandidates" class="fx-empty">暂无候选，继续输入更具体关键词</div>
          </div>
        </div>

        <div class="modal-actions">
          <button class="ghost-btn" @click="close">取消</button>
          <button class="primary-btn" @click="onQuery">查询</button>
        </div>

        <div class="result" v-if="resultObj">
          <div><b>{{ resultObj.name }}</b> <span class="muted">({{ resultObj.symbol }})</span></div>
          <div style="margin-top:6px;">
            <b>{{ resultObj.price }}</b>
            <span :class="changeClass">{{ sign }}{{ resultObj.chg }} ({{ sign }}{{ resultObj.pct_chg }}%)</span>
          </div>
          <div class="muted">
            开：{{ resultObj.open }} · 昨收：{{ resultObj.prev_close }} · 高：{{ resultObj.high }} · 低：{{ resultObj.low }} · 更新时间：{{ resultObj.update_time }}
          </div>
        </div>

        <div class="result result-error" v-if="errMsg">
          {{ errMsg }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { getQuoteCandidates, queryQuote } from './api/client'

const props = defineProps({
  open: { type: Boolean, default: false },
  initialSymbol: { type: String, default: '' }
})
const emit = defineEmits(['update:open'])

const symbol = ref('')
const resultObj = ref(null)
const errMsg = ref('')
const candidates = ref([])
const pickerOpen = ref(false)
const hasCandidateSearched = ref(false)
let candidateBusy = false

let timer = null
let busy = false
let inputTimer = null

function stop() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

function close() {
  stop()
  pickerOpen.value = false
  emit('update:open', false)
}

function openPicker() {
  pickerOpen.value = true
  void refreshCandidates()
}

function onSymbolFocus() {
  // 默认不打扰用户：空输入时不弹“暂无候选”
  const q = String(symbol.value || '').trim()
  if (!q) {
    pickerOpen.value = false
    return
  }
  pickerOpen.value = true
  if (!hasCandidateSearched.value) void refreshCandidates()
}

async function refreshCandidates() {
  if (candidateBusy) return
  candidateBusy = true
  try {
    const q = String(symbol.value || '').trim()
    if (!q) {
      candidates.value = []
      return
    }
    const json = await getQuoteCandidates(q)
    candidates.value = Array.isArray(json?.data?.items) ? json.data.items : []
    hasCandidateSearched.value = true
  } catch {
    candidates.value = []
    hasCandidateSearched.value = true
  } finally {
    candidateBusy = false
  }
}

function onSymbolInput() {
  const q = String(symbol.value || '').trim()
  if (!q) {
    pickerOpen.value = false
    candidates.value = []
    hasCandidateSearched.value = false
    return
  }
  pickerOpen.value = true
  if (inputTimer) clearTimeout(inputTimer)
  inputTimer = setTimeout(() => { void refreshCandidates() }, 220)
}

function selectCandidate(it) {
  symbol.value = String(it?.symbol || '').trim()
  pickerOpen.value = false
}

async function doQuery() {
  if (busy) return
  const sym = String(symbol.value || '').trim().replace(/^['"]|['"]$/g, '')
  if (!sym) return
  busy = true
  errMsg.value = ''
  try {
    const json = await queryQuote(sym)
    if (json.code !== 200) throw new Error(json.msg || '查询失败')
    resultObj.value = json.data
  } catch (e) {
    const msg = String(e?.message || e || '查询失败')
    errMsg.value = msg.startsWith('查询失败') ? msg : `查询失败：${msg}`
  } finally {
    busy = false
  }
}

async function onQuery() {
  await doQuery()
  stop()
  timer = setInterval(() => {
    void doQuery()
  }, 3000)
}

watch(
  () => props.open,
  (v) => {
    if (!v) {
      stop()
      pickerOpen.value = false
      hasCandidateSearched.value = false
      return
    }
    const s = String(props.initialSymbol || '').trim()
    if (s) symbol.value = s
    if (s) void refreshCandidates()
  }
)

const sign = computed(() => {
  const v = Number(resultObj.value?.chg ?? 0)
  return v > 0 ? '+' : ''
})
const showNoCandidates = computed(() => {
  return hasCandidateSearched.value && candidates.value.length === 0 && String(symbol.value || '').trim().length > 0
})
const changeClass = computed(() => {
  const v = Number(resultObj.value?.chg ?? 0)
  return v > 0 ? 'up' : (v < 0 ? 'down' : '')
})

onBeforeUnmount(() => {
  stop()
  if (inputTimer) clearTimeout(inputTimer)
})
</script>


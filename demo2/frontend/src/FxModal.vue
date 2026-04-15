<template>
  <div
    class="modal-mask"
    :style="{ display: open ? 'flex' : 'none' }"
    @click.self="close"
  >
    <div class="modal fx-modal" role="dialog" aria-modal="true" aria-label="汇率换算" @click.stop>
      <div class="modal-hd">
        <div class="modal-title">
          <span>💱</span><span>汇率换算</span>
        </div>
        <button class="modal-close" @click="close" aria-label="关闭">✕</button>
      </div>

      <div class="modal-bd fx-modal-bd">
        <div class="field fx-amount-field">
          <label>金额</label>
          <input class="input-strong" v-model.number="amount" type="number" min="0" step="0.01" placeholder="请输入金额" />
        </div>

        <div class="fx-currency-row">
          <div class="field fx-field">
            <label>从（可搜索）</label>
            <input
              v-model.trim="from"
              class="input-strong"
              inputmode="latin"
              autocomplete="off"
              placeholder="输入 USD / 美元"
              @focus="openPicker('from')"
              @input="openPicker('from')"
            />
            <div v-if="pickerOpen === 'from'" class="fx-menu">
              <button
                v-for="c in filteredCurrencies(from)"
                :key="'f-' + c"
                type="button"
                class="fx-item"
                @click="selectCurrency('from', c)"
              >
                {{ currencyLabel(c) }}
              </button>
              <div v-if="filteredCurrencies(from).length > 0" class="fx-menu-end">—— 已到底 ——</div>
              <div v-if="filteredCurrencies(from).length === 0" class="fx-empty">没有匹配币种</div>
            </div>
          </div>

          <div class="field fx-field">
            <label>到（可搜索）</label>
            <input
              v-model.trim="to"
              class="input-strong"
              inputmode="latin"
              autocomplete="off"
              placeholder="输入 CNY / 人民币"
              @focus="openPicker('to')"
              @input="openPicker('to')"
            />
            <div v-if="pickerOpen === 'to'" class="fx-menu">
              <button
                v-for="c in filteredCurrencies(to)"
                :key="'t-' + c"
                type="button"
                class="fx-item"
                @click="selectCurrency('to', c)"
              >
                {{ currencyLabel(c) }}
              </button>
              <div v-if="filteredCurrencies(to).length > 0" class="fx-menu-end">—— 已到底 ——</div>
              <div v-if="filteredCurrencies(to).length === 0" class="fx-empty">没有匹配币种</div>
            </div>
          </div>
        </div>

        <div class="result fx-result" v-if="resultObj">
          <div>
            <b>{{ resultObj.amount }}</b> {{ resultObj.from }} ≈ <b>{{ resultObj.result }}</b> {{ resultObj.to }}
          </div>
          <div class="muted">
            汇率：{{ resultObj.rate }} · 更新时间：{{ resultObj.update_time }}
          </div>
        </div>

        <div
          class="result result-error fx-result"
          v-if="errMsg"
        >
          {{ errMsg }}
        </div>

      </div>

      <!-- 底部固定操作栏 -->
      <div class="modal-ft">
        <div class="modal-actions">
          <button class="ghost-btn" @click="close">取消</button>
          <button class="primary-btn" @click="onQuery">查询</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { convertFx, getFxCurrencies } from './api/client'

const props = defineProps({
  open: { type: Boolean, default: false }
})
const emit = defineEmits(['update:open'])

const amount = ref(1)
const from = ref('USD')
const to = ref('CNY')
const currencies = ref(['USD', 'CNY', 'EUR', 'JPY', 'HKD'])
const pickerOpen = ref(null) // 'from' | 'to' | null

const resultObj = ref(null)
const errMsg = ref('')

let timer = null
let busy = false
const CURRENCY_PRIORITY = ['USD', 'CNY', 'EUR', 'JPY', 'KRW', 'HKD', 'GBP', 'AUD', 'CAD', 'CHF', 'SGD']
const displayNames = typeof Intl !== 'undefined' && Intl.DisplayNames
  ? new Intl.DisplayNames(['zh-Hans', 'zh-CN'], { type: 'currency' })
  : null

const CURRENCY_CN = {
  USD: '美元',
  CNY: '人民币',
  EUR: '欧元',
  JPY: '日元',
  HKD: '港元',
  GBP: '英镑',
  AUD: '澳元',
  CAD: '加元',
  CHF: '瑞士法郎',
  SGD: '新加坡元',
  KRW: '韩元',
  RUB: '卢布',
  THB: '泰铢',
  MYR: '马来西亚林吉特',
  IDR: '印尼盾',
  PHP: '菲律宾比索',
  INR: '印度卢比',
  NZD: '新西兰元',
  SEK: '瑞典克朗',
  NOK: '挪威克朗',
  DKK: '丹麦克朗',
  AED: '阿联酋迪拉姆',
  SAR: '沙特里亚尔',
}

function stop() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

function close() {
  stop()
  pickerOpen.value = null
  emit('update:open', false)
}

function openPicker(which) {
  pickerOpen.value = which
}

function filteredCurrencies(valRef) {
  const raw = String(valRef?.value ?? valRef ?? '').trim()
  const q = raw.toUpperCase()
  if (!q) return currencies.value
  // 若当前值就是一个完整币种代码（如默认 USD/CNY），展开完整列表方便继续选择其他币种
  if (currencies.value.includes(q)) return currencies.value
  return currencies.value
    .filter((c) => {
      const label = currencyLabel(c)
      return c.includes(q) || label.includes(raw) || label.toUpperCase().includes(q)
    })
}

function currencyLabel(code) {
  const c = String(code || '').toUpperCase()
  const zhFromIntl = displayNames?.of?.(c)
  if (zhFromIntl && zhFromIntl !== c) return `${c}（${zhFromIntl}）`
  const zh = CURRENCY_CN[c]
  return zh ? `${c}（${zh}）` : `${c}（未收录中文）`
}

function selectCurrency(which, code) {
  const v = String(code || '').toUpperCase()
  if (which === 'from') from.value = v
  if (which === 'to') to.value = v
  pickerOpen.value = null
}

async function doQuery() {
  if (busy) return
  busy = true
  errMsg.value = ''
  try {
    const f = String(from.value || '').trim().toUpperCase()
    const t = String(to.value || '').trim().toUpperCase()
    from.value = f
    to.value = t
    const json = await convertFx({ amount: amount.value, from: f, to: t })
    if (json.code !== 200) throw new Error(json.msg || '查询失败')
    resultObj.value = json.data
  } catch (e) {
    errMsg.value = `查询失败：${e?.message || e}`
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
  async (v) => {
    if (!v) {
      stop()
      pickerOpen.value = null
      return
    }
    // 打开弹窗时加载一次币种列表（失败就保留默认常用币种）
    try {
      const json = await getFxCurrencies()
      if (json.code === 200 && Array.isArray(json.data?.items) && json.data.items.length) {
        const raw = Array.from(new Set(json.data.items.map((x) => String(x || '').toUpperCase()).filter(Boolean)))
        if (!raw.includes('USD')) raw.push('USD')
        currencies.value = raw.sort((a, b) => {
          const ia = CURRENCY_PRIORITY.indexOf(a)
          const ib = CURRENCY_PRIORITY.indexOf(b)
          if (ia >= 0 && ib >= 0) return ia - ib
          if (ia >= 0) return -1
          if (ib >= 0) return 1
          return a.localeCompare(b)
        })
      }
    } catch {
      // ignore
    }
  }
)

onBeforeUnmount(() => stop())
</script>


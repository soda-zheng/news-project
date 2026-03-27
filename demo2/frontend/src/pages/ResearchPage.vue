<template>
  <div class="research-page">
    <header class="rp-hero">
      <button type="button" class="rp-back" @click="$emit('go-home')" aria-label="返回首页">
        <span class="rp-back-icon" aria-hidden="true">←</span>
        首页
      </button>

      <div class="rp-hero-main">
        <div class="rp-kicker">智能投研 · 研判助理</div>
        <h1 class="rp-title">智能投研</h1>
        <p class="rp-subtitle">基于实时行情与公开资讯，围绕你的问题输出可读、可执行的分析结论（不构成投资建议）。</p>
      </div>
    </header>

    <div class="rp-layout">
      <aside class="rp-left">
        <div class="rp-card">
          <div class="rp-section">
            <div class="rp-label">历史会话</div>
            <div v-if="chatSessions.length" class="rp-sessions">
              <div
                v-for="s in chatSessions"
                :key="s.session_id"
                class="rp-session-item"
                :class="{ 'rp-session-item--active': currentSessionId === s.session_id }"
                @click="switchSession(s.session_id)"
              >
                <div class="rp-session-main">
                  <div class="rp-session-title">{{ s.title || '投研会话' }}</div>
                  <div class="rp-session-meta">{{ s.updated_at }} · {{ s.message_count || 0 }} 条</div>
                </div>
                <button type="button" class="rp-session-del" @click.stop="removeSession(s.session_id)">删</button>
              </div>
            </div>
            <p v-else class="rp-hint">暂无历史会话</p>
          </div>

          <div class="rp-section">
            <div class="rp-label">股票代码/中文名（可选）</div>
            <div class="rp-input-row">
              <input
                v-model.trim="stockSymbol"
                class="rp-input"
                type="text"
                placeholder="例如：贵州茅台 / sh600519 / sz000001 / bj920028 / 黄金"
              />
              <button type="button" class="rp-clear" @click="stockSymbol = ''">清空</button>
            </div>
            <p class="rp-hint">填写股票代码或中文股票名后，会自动识别并带入新浪行情快照，增强研判的“可核实性”。</p>
          </div>

          <div class="rp-section">
            <div class="rp-label">关键词/主题（可选）</div>
            <div class="rp-input-row">
              <input
                v-model.trim="keyword"
                class="rp-input"
                type="text"
                placeholder="例如：半导体、机器人、消费电子"
              />
              <button type="button" class="rp-clear" @click="keyword = ''">清空</button>
            </div>
          </div>

          <div class="rp-section">
            <div class="rp-label">问题</div>
            <textarea
              v-model.trim="question"
              class="rp-textarea"
              rows="4"
              placeholder="例如：今天某股票的走势如何？该关注哪些风险点？"
            />

            <div class="rp-preset-row">
              <button
                v-for="t in presetTags"
                :key="t.label"
                type="button"
                class="rp-preset"
                @click="applyPreset(t)"
              >
                {{ t.label }}
              </button>
            </div>
          </div>

          <p v-if="error" class="rp-error">{{ error }}</p>

          <div v-if="chatMessages.length" class="rp-tools">
            <button type="button" class="rp-clear" @click="clearConversation">清空对话</button>
          </div>

          <button
            type="button"
            class="rp-primary"
            :disabled="!canSubmit || loading"
            @click="startAnalyze"
          >
            {{ loading ? '研判中…' : '开始研判' }}
          </button>
        </div>
      </aside>

      <section class="rp-right">
        <div v-if="chatMessages.length > 0" class="rp-chat">
          <div
            v-for="(m, idx) in chatMessages"
            :key="`${m.role}-${idx}`"
            class="rp-msg"
            :class="m.role === 'user' ? 'rp-msg--user' : 'rp-msg--assistant'"
          >
            <div class="rp-msg-role">{{ m.role === 'user' ? '你' : '投研助手' }}</div>
            <div class="rp-msg-content">{{ m.content }}</div>
          </div>
        </div>

        <div v-if="loading" class="rp-result rp-result--loading">
          <div class="rp-spinner" aria-hidden="true" />
          <div class="rp-result-title">任务进行中…</div>
          <div class="rp-result-sub">{{ taskHint || '请稍候，首次请求可能稍慢。' }}</div>
        </div>

        <div v-else-if="result" class="rp-result">
          <div class="rp-result-head">
            <div>
              <div class="rp-result-title">{{ result.title }}</div>
              <div class="rp-result-badge" v-if="result.source">{{ result.source === 'llm' ? '模型直答' : '多源分析' }}</div>
            </div>
          </div>

          <div class="rp-summary">
            {{ result.summary }}
          </div>

          <template v-if="Array.isArray(result.blocks) && result.blocks.length > 0">
            <div class="rp-block" v-for="(blk, idx) in nonRiskBlocks" :key="idx">
              <div class="rp-block-title">
                {{ blk.title || '观点' }}
              </div>
              <ul v-if="blk.mode === 'list'" class="rp-bullets">
                <li v-for="(it, i) in (blk.items || [])" :key="i">{{ it }}</li>
              </ul>
              <div v-else class="rp-paragraph">{{ blk.text }}</div>
            </div>
          </template>
          <template v-else>
            <div class="rp-block">
              <div class="rp-block-title">核心观点</div>
              <ul class="rp-bullets">
                <li v-for="(b, i) in result.bullets" :key="i">
                  {{ b }}
                </li>
              </ul>
            </div>

          </template>

          <div class="rp-block" v-if="displayRisk.length > 0">
            <div class="rp-block-title rp-block-title--risk">风险提示</div>
            <ul class="rp-bullets rp-bullets--risk">
              <li v-for="(r, i) in displayRisk" :key="i">
                {{ r }}
              </li>
            </ul>
          </div>

          <div class="rp-disclaimer">
            {{ result.disclaimer }}
          </div>
        </div>

        <div v-else class="rp-result rp-result--empty">
          <div class="rp-empty-title">准备开始研判</div>
          <div class="rp-empty-sub">输入问题并点击“开始研判”，将自动结合行情快照（如提供股票代码）与热点榜样本生成结构化结论。</div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  createResearchTaskStream,
  deleteResearchChatSession,
  getResearchChatSessionMessages,
  getResearchChatSessions,
  getResearchTask,
  postResearchAnalyze,
} from '../api/client'

defineEmits(['go-home'])

const question = ref('')
const keyword = ref('')
const category = ref('')
const stockSymbol = ref('')

const loading = ref(false)
const error = ref('')
const result = ref(null)
const chatMessages = ref([])
const chatSessions = ref([])
const taskHint = ref('')
const currentTaskId = ref('')
const currentSessionId = ref('')
const pendingQuestion = ref('')
let stream = null
let taskPollTimer = null

const canSubmit = computed(() => (question.value || '').trim().length > 0)
const nonRiskBlocks = computed(() => {
  const arr = Array.isArray(result.value?.blocks) ? result.value.blocks : []
  return arr.filter((b) => !String(b?.title || '').includes('风险'))
})
const displayRisk = computed(() => {
  const direct = Array.isArray(result.value?.risk) ? result.value.risk.filter(Boolean) : []
  if (direct.length > 0) return direct
  const arr = Array.isArray(result.value?.blocks) ? result.value.blocks : []
  const riskBlock = arr.find((b) => String(b?.title || '').includes('风险'))
  if (!riskBlock) return []
  if (riskBlock.mode === 'list' && Array.isArray(riskBlock.items)) return riskBlock.items.filter(Boolean)
  if (riskBlock.mode === 'paragraph' && riskBlock.text) return [riskBlock.text]
  return []
})

// 预设问题模板（复用你原来的交互方式，但更偏研判表达）
const presetTags = [
  { label: '今日热点', q: '今天有哪些值得关注的市场热点？背后的驱动可能从哪些维度观察？', cat: '热点' },
  { label: '行情研判', q: '就当前涨幅榜与行情快照，给出简明的市场研判与需要关注的风险点。', cat: '行情' },
  { label: '个股解读', q: '结合行情快照与榜单位置，分析该股票今日走势的观察要点与风险。', cat: '个股' },
  { label: '板块轮动', q: '根据热点样本的强弱变化，推断短期可能的板块轮动方向与验证方法（不编造具体消息）。', cat: '板块' },
  { label: '风险清单', q: '给出一份风险清单：若市场情绪转弱/流动性收缩，应该优先留意哪些风险信号？', cat: '风险' },
]

function applyPreset(t) {
  question.value = t.q
  category.value = t.cat || ''
}

function clearConversation() {
  chatMessages.value = []
  result.value = null
  error.value = ''
  taskHint.value = ''
  currentSessionId.value = ''
}

function buildAssistantText(data) {
  const summary = String(data?.summary || '').trim()
  const bullets = Array.isArray(data?.bullets) ? data.bullets.filter(Boolean).slice(0, 3) : []
  const compactBullets = bullets.map((x) => `- ${x}`).join('\n')
  if (summary && compactBullets) return `${summary}\n${compactBullets}`
  if (summary) return summary
  if (compactBullets) return compactBullets
  return '已完成本次分析。'
}

function clearTaskPolling() {
  if (taskPollTimer) {
    clearTimeout(taskPollTimer)
    taskPollTimer = null
  }
}

function applyAnalyzeSuccess(data, q) {
  result.value = data
  chatMessages.value.push({ role: 'user', content: q })
  chatMessages.value.push({ role: 'assistant', content: buildAssistantText(data) })
  question.value = ''
}

async function pollTaskOnce(taskId, q) {
  const json = await getResearchTask(taskId)
  if (json.code !== 200 || !json.data) return false
  const t = json.data
  taskHint.value = t.message || ''
  if (t.status === 'completed') {
    loading.value = false
    currentTaskId.value = ''
    clearTaskPolling()
    applyAnalyzeSuccess(t.result, q)
    pendingQuestion.value = ''
    return true
  }
  if (t.status === 'failed') {
    loading.value = false
    currentTaskId.value = ''
    clearTaskPolling()
    pendingQuestion.value = ''
    throw new Error(t.error || t.message || '研判失败')
  }
  return false
}

function schedulePollTask(taskId, q) {
  clearTaskPolling()
  taskPollTimer = setTimeout(async () => {
    try {
      const done = await pollTaskOnce(taskId, q)
      if (!done && loading.value && currentTaskId.value === taskId) {
        schedulePollTask(taskId, q)
      }
    } catch (e) {
      error.value = e?.message || '研判失败，请稍后重试'
    }
  }, 1200)
}

async function startAnalyze() {
  if (!canSubmit.value || loading.value) return
  const q = question.value.trim()
  pendingQuestion.value = q
  loading.value = true
  error.value = ''
  taskHint.value = '正在创建任务…'

  try {
    const payload = {
      question: q,
      keyword: keyword.value.trim() || '',
      category: category.value || '',
      stockSymbol: stockSymbol.value.trim() || '',
      history: chatMessages.value.slice(-8).map((x) => ({ role: x.role, content: x.content })),
      session_id: currentSessionId.value || '',
      async_mode: true,
    }
    const json = await postResearchAnalyze(payload)
    if (json.code !== 202 || !json?.data?.task_id) {
      throw new Error(json.msg || '研判失败')
    }
    const tid = String(json.data.task_id)
    currentSessionId.value = String(json?.data?.session_id || currentSessionId.value || '')
    currentTaskId.value = tid
    taskHint.value = json?.data?.message || '任务已提交，等待执行'
    schedulePollTask(tid, q)
  } catch (e) {
    error.value = e?.message || '研判失败，请稍后重试'
    loading.value = false
  } finally {
    // 异步任务在完成时再置 false
  }
}

async function refreshSessions() {
  const json = await getResearchChatSessions({ limit: 60 })
  if (json.code === 200) {
    chatSessions.value = json?.data?.sessions || []
  }
}

async function switchSession(sessionId) {
  const sid = String(sessionId || '').trim()
  if (!sid) return
  const json = await getResearchChatSessionMessages(sid)
  if (json.code !== 200) return
  currentSessionId.value = sid
  const msgs = (json?.data?.messages || []).map((x) => ({
    role: x.role === 'assistant' ? 'assistant' : 'user',
    content: String(x.content || ''),
  }))
  chatMessages.value = msgs
  result.value = null
  error.value = ''
}

async function removeSession(sessionId) {
  const sid = String(sessionId || '').trim()
  if (!sid) return
  const json = await deleteResearchChatSession(sid)
  if (json.code === 200) {
    if (currentSessionId.value === sid) {
      clearConversation()
    }
    await refreshSessions()
  }
}

onMounted(() => {
  void refreshSessions()
  stream = createResearchTaskStream()
  const onTaskUpdate = async (evt) => {
    if (!loading.value || !currentTaskId.value) return
    try {
      const data = JSON.parse(evt?.data || '{}')
      if (String(data?.task_id || '') !== currentTaskId.value) return
      if (evt.type === 'task_started') {
        taskHint.value = '任务已开始执行，正在调用模型…'
      } else if (evt.type === 'task_failed') {
        loading.value = false
        clearTaskPolling()
        currentTaskId.value = ''
        error.value = data?.error || '研判失败'
      } else if (evt.type === 'task_completed') {
        loading.value = false
        clearTaskPolling()
        currentTaskId.value = ''
        applyAnalyzeSuccess(data?.result, pendingQuestion.value || '追问')
        pendingQuestion.value = ''
        void refreshSessions()
      }
    } catch {
      // ignore malformed sse event
    }
  }
  stream.addEventListener('task_started', onTaskUpdate)
  stream.addEventListener('task_failed', onTaskUpdate)
  stream.addEventListener('task_completed', onTaskUpdate)
})

onBeforeUnmount(() => {
  clearTaskPolling()
  if (stream) {
    stream.close()
    stream = null
  }
})
</script>

<style scoped>
.research-page { display: grid; gap: var(--space-5); }
.rp-hero,
.rp-card,
.rp-result {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 2px;
  box-shadow: none;
}
.rp-hero {
  padding: 18px 20px;
  display: grid;
  gap: var(--space-3);
  border-left: 4px solid var(--brand);
}
.rp-back {
  width: fit-content;
  border: 1px solid var(--line-strong);
  background: var(--surface-soft);
  color: var(--text);
  border-radius: 2px;
  padding: 8px 12px;
  font-size: var(--fs-12);
  font-weight: 800;
  cursor: pointer;
}
.rp-back:hover {
  border-color: var(--brand);
  background: var(--brand-soft);
}
.rp-kicker { font-size: var(--fs-11); color: var(--text-muted); letter-spacing: .1em; text-transform: uppercase; font-weight: 800; }
.rp-title { margin: 0; font-size: clamp(24px, 4vw, 32px); font-weight: 900; }
.rp-subtitle { margin: 0; color: var(--text-muted); line-height: 1.7; font-size: var(--fs-14); max-width: 880px; }
.rp-layout { display: grid; grid-template-columns: minmax(340px, 420px) 1fr; gap: var(--space-5); align-items: start; }
.rp-card { padding: var(--space-5); }
.rp-section { margin-bottom: var(--space-4); }
.rp-label { font-size: var(--fs-13); font-weight: 800; margin-bottom: 8px; }
.rp-input-row { display: grid; grid-template-columns: 1fr auto; gap: var(--space-2); }
.rp-input, .rp-textarea { width: 100%; border: 1px solid var(--line); border-radius: 10px; background: var(--surface-soft); color: var(--text); padding: 10px 12px; font-size: var(--fs-14); }
.rp-textarea { min-height: 120px; resize: vertical; line-height: 1.7; }
.rp-clear, .rp-preset { border: 1px solid var(--line); background: var(--surface); color: var(--text-muted); border-radius: 2px; font-size: var(--fs-12); font-weight: 700; padding: 8px 10px; cursor: pointer; }
.rp-hint { color: var(--text-muted); font-size: var(--fs-12); line-height: 1.6; margin-top: 8px; }
.rp-preset-row { display: flex; flex-wrap: wrap; gap: var(--space-2); margin-top: var(--space-2); }
.rp-error { border: 1px solid color-mix(in oklab, var(--danger) 45%, transparent); background: color-mix(in oklab, var(--danger) 10%, transparent); color: var(--danger); border-radius: 10px; padding: 10px 12px; font-size: var(--fs-12); font-weight: 700; margin-bottom: var(--space-3); }
.rp-primary { width: 100%; border: 1px solid color-mix(in oklab, var(--brand) 80%, black); background: linear-gradient(135deg, var(--brand), var(--brand-strong)); color: #fff; font-size: var(--fs-14); font-weight: 900; border-radius: 2px; padding: 12px 14px; cursor: pointer; }
.rp-primary:disabled { opacity: .55; cursor: not-allowed; }
.rp-tools { margin-bottom: var(--space-3); display: flex; justify-content: flex-end; }
.rp-sessions { display: grid; gap: 8px; max-height: 200px; overflow: auto; padding-right: 2px; }
.rp-session-item { border: 1px solid var(--line); background: var(--surface-soft); border-radius: 8px; padding: 8px 10px; display: flex; justify-content: space-between; align-items: center; gap: 8px; cursor: pointer; }
.rp-session-item--active { border-color: var(--brand); background: color-mix(in oklab, var(--brand) 10%, var(--surface)); }
.rp-session-main { min-width: 0; }
.rp-session-title { font-size: var(--fs-12); font-weight: 800; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rp-session-meta { font-size: var(--fs-11); color: var(--text-muted); margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rp-session-del { border: 1px solid var(--line); background: var(--surface); color: var(--text-muted); border-radius: 2px; font-size: var(--fs-11); padding: 4px 8px; cursor: pointer; }
.rp-chat { display: grid; gap: var(--space-2); margin-bottom: var(--space-3); }
.rp-msg { border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; line-height: 1.7; }
.rp-msg--user { background: color-mix(in oklab, var(--brand) 9%, var(--surface)); }
.rp-msg--assistant { background: var(--surface-soft); }
.rp-msg-role { font-size: var(--fs-11); color: var(--text-muted); font-weight: 800; margin-bottom: 4px; }
.rp-msg-content { white-space: pre-line; font-size: var(--fs-13); }
.rp-result { padding: var(--space-5); }
.rp-result-title { font-size: var(--fs-18); font-weight: 900; margin-bottom: 6px; }
.rp-result-badge { display: inline-flex; padding: 4px 10px; border-radius: 2px; font-size: var(--fs-11); border: 1px solid var(--line); background: var(--surface-soft); color: var(--text-muted); font-weight: 800; }
.rp-summary { margin-top: var(--space-3); background: var(--surface-soft); border: 1px solid var(--line); border-radius: 2px; padding: 12px 14px; line-height: 1.8; }
.rp-block { margin-top: var(--space-4); }
.rp-block-title { font-size: var(--fs-13); font-weight: 900; margin-bottom: 8px; }
.rp-block-title--risk { color: var(--danger); }
.rp-bullets { margin: 0; padding-left: 18px; display: grid; gap: 8px; line-height: 1.7; }
.rp-bullets--risk { color: color-mix(in oklab, var(--danger) 70%, var(--text)); }
.rp-paragraph { border: 1px solid var(--line); background: var(--surface-soft); border-radius: 2px; padding: 12px 14px; line-height: 1.8; }
.rp-disclaimer { margin-top: var(--space-4); padding-top: var(--space-3); border-top: 1px dashed var(--line-strong); color: var(--text-muted); font-size: var(--fs-12); line-height: 1.7; }
.rp-result--empty, .rp-result--loading { text-align: center; padding: 54px 18px; color: var(--text-muted); }
.rp-empty-title { font-size: var(--fs-18); font-weight: 900; color: var(--text); margin-bottom: 8px; }
.rp-empty-sub { line-height: 1.7; font-size: var(--fs-13); }
.rp-spinner { width: 24px; height: 24px; border-radius: 999px; border: 3px solid color-mix(in oklab, var(--brand) 35%, transparent); border-top-color: var(--brand); margin: 0 auto 12px; animation: rp-spin .8s linear infinite; }
@keyframes rp-spin { to { transform: rotate(360deg); } }
@media (max-width: 1024px) { .rp-layout { grid-template-columns: 1fr; } }
</style>


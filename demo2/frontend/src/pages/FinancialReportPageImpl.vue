<script setup>
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { marked } from 'marked'
import { getTask, regenPage, startAnalyze, uploadPdf } from '../api/client.js'
import { useRouter } from 'vue-router'

// 迁移自 analystgpt-demo 的 theme 样式（确保该页面样式一致）
import '../styles/analystgpt-financial-report.css'

const router = useRouter()

const uiState = ref('idle') // idle|uploading|ready|running|done|error
const errorMsg = ref('')

const sessionId = ref('')
const fileName = ref('')
const fileSize = ref(0)

const taskId = ref('')
const stage = ref('')

const pages = ref([])
const pageIndex = ref(0)
const facts = ref([])

const showEdit = ref(false)
const editQuestion = ref('')
const editChoice = ref('')
const isRegenerating = ref(false)
const toastMsg = ref('')

function showToast(msg) {
  toastMsg.value = msg
  window.setTimeout(() => {
    if (toastMsg.value === msg) toastMsg.value = ''
  }, 1800)
}

let pollTimer

function stopPoll() {
  if (pollTimer) {
    window.clearTimeout(pollTimer)
    pollTimer = undefined
  }
}

onBeforeUnmount(stopPoll)

function normalizePageMd(md) {
  const t = String(md || '')
  // 修复标题重复编号（例如：### 1. 1. xxx）
  let out = t.replace(/^###\s+(\d+)\.\s+(?:\1\.\s+)+/m, '### $1. ')

  // 让“核心结论/细节1/细节2/关键数字/概念”在 Markdown 里强制分段，避免被渲染成同一段
  // 1) 若这些标签前面不是换行，则补一个空行
  out = out.replace(/([^\n])\n?(核心结论：)/g, '$1\n\n$2')
  out = out.replace(/([^\n])\n?(细节1：)/g, '$1\n\n$2')
  out = out.replace(/([^\n])\n?(细节2：)/g, '$1\n\n$2')
  out = out.replace(/([^\n])\n?(关键数字\/概念：)/g, '$1\n\n$2')

  // 2) 常见情况：细节1/细节2 被模型写在同一段里（中间只有空格/全角空格），强制断行
  out = out.replace(/(细节1：[\s\S]*?来源：财报\s*P\d+\s*)[ \t\u3000]+(细节2：)/g, '$1\n\n$2')

  // 3) 用户侧展示不需要出现 Markdown 加粗标记 **...**，统一剥离，仅保留文字内容
  out = out.replace(/\*\*([^*]+)\*\*/g, '$1')
  out = out.replace(/\*\*/g, '')

  // 3.5) 关键数字/概念：有些输出会把多个条目写在同一行，用 " - " 串起来，导致渲染成一行很难读
  // 这里把 "） - " 形式强制拆成多行列表项：")\n- "
  out = out.replace(/([)）]\s*)-\s+/g, '$1\n- ')

  // 4) 将分段标题转换为图中“橙色小标题 + 冒号”的样式
  // - 兼容：有的模型把标签写成独立一行，有的写在行首后面跟正文
  // - 仅在行首匹配，避免正文里出现同名词被误替换
  const labelMap = [
    ['核心结论：', '核心结论：'],
    ['细节1：', '细节1：'],
    ['细节2：', '细节2：'],
    ['关键数字/概念：', '关键数字/概念：'],
  ]
  for (const [raw, shown] of labelMap) {
    const re = new RegExp(`(^|\\n)\\s*${raw.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')}\\s*`, 'g')
    // 用空行把后续内容（尤其是列表）与标题分开，确保 markdown 列表能被正确渲染为 <ul><li>
    out = out.replace(re, `$1<div class="sec-label">${shown}</div>\n\n`)
  }

  return out
}

const currentPageMd = computed(() => normalizePageMd(pages.value[pageIndex.value] ?? ''))
const currentPageHtml = computed(() => marked.parse(currentPageMd.value || ''))

const factChoices = computed(() => {
  const out = []
  for (const f of facts.value || []) {
    const ind = (f.indicator || '').trim()
    if (!ind) continue
    const parts = [ind]
    if (f.value) parts.push(String(f.value).trim())
    if (f.page) parts.push(String(f.page).trim())
    out.push(parts.join('｜'))
  }
  return Array.from(new Set(out)).slice(0, 240)
})

function formatBytes(n) {
  if (!Number.isFinite(n) || n <= 0) return '0 B'
  if (n < 1024) return `${n} B`
  const kb = n / 1024
  if (kb < 1024) return `${kb.toFixed(1)} KB`
  const mb = kb / 1024
  return `${mb.toFixed(1)} MB`
}

async function onPickFile(e) {
  const input = e.target
  const f = input.files?.[0]
  if (!f) return
  uiState.value = 'uploading'
  errorMsg.value = ''
  try {
    const resp = await uploadPdf(f)
    sessionId.value = resp.sessionId
    fileName.value = resp.fileInfo.name
    fileSize.value = resp.fileInfo.size
    uiState.value = 'ready'
  } catch (err) {
    uiState.value = 'error'
    errorMsg.value = err instanceof Error ? err.message : String(err)
  } finally {
    input.value = ''
  }
}

function resetFile() {
  stopPoll()
  uiState.value = 'idle'
  errorMsg.value = ''
  sessionId.value = ''
  fileName.value = ''
  fileSize.value = 0
  taskId.value = ''
  stage.value = ''
  pages.value = []
  facts.value = []
  pageIndex.value = 0
  showEdit.value = false
  editQuestion.value = ''
  editChoice.value = ''
}

async function start() {
  if (!sessionId.value) return
  uiState.value = 'running'
  errorMsg.value = ''
  stage.value = '准备中'
  pages.value = []
  facts.value = []
  pageIndex.value = 0
  stopPoll()
  try {
    const resp = await startAnalyze(sessionId.value)
    taskId.value = resp.taskId
    await poll()
  } catch (err) {
    uiState.value = 'error'
    errorMsg.value = err instanceof Error ? err.message : String(err)
  }
}

async function poll() {
  const id = taskId.value
  if (!id) return
  let payload
  try {
    payload = await getTask(id)
  } catch (err) {
    uiState.value = 'error'
    errorMsg.value = err instanceof Error ? err.message : String(err)
    return
  }

  stage.value = payload.stage || stage.value

  if (payload.status === 'failed') {
    uiState.value = 'error'
    errorMsg.value = payload.error || '任务失败'
    return
  }

  if (payload.status === 'succeeded') {
    pages.value = payload.result?.pages || []
    facts.value = payload.result?.facts || []
    pageIndex.value = 0
    uiState.value = 'done'
    stage.value = '生成完毕'
    showToast('生成完毕')
    return
  }

  pollTimer = window.setTimeout(poll, 900)
}

function prev() {
  pageIndex.value = Math.max(0, pageIndex.value - 1)
  nextTick(() => {
    window.scrollTo({ top: 0, behavior: 'smooth' })
  })
}

function next() {
  if (!pages.value.length) return
  pageIndex.value = Math.min(pages.value.length - 1, pageIndex.value + 1)
  nextTick(() => {
    window.scrollTo({ top: 0, behavior: 'smooth' })
  })
}

function openEdit() {
  showEdit.value = true
  editQuestion.value = ''
  editChoice.value = ''
}

function closeEdit() {
  showEdit.value = false
}

async function saveEdit() {
  if (!sessionId.value) return
  const idx = pageIndex.value
  if (isRegenerating.value) return
  isRegenerating.value = true
  try {
    const resp = await regenPage({
      sessionId: sessionId.value,
      pageIndex: idx,
      customQuestion: editQuestion.value.trim() || undefined,
      choice: editChoice.value.trim() || undefined,
    })
    pages.value = resp.pages || pages.value
    pageIndex.value = resp.pageIndex ?? idx
    showEdit.value = false
    showToast('已重新生成')
  } catch (err) {
    errorMsg.value = err instanceof Error ? err.message : String(err)
  } finally {
    isRegenerating.value = false
  }
}

function goMain() {
  router.push({ name: 'home' })
}
</script>

<template>
  <div class="financial-report-wrap">
    <header class="vp-hero">
      <button type="button" class="vp-back" @click="goMain" aria-label="返回首页">
        <span class="vp-back-icon" aria-hidden="true">←</span>
        首页
      </button>
      <div class="vp-hero-main">
        <div class="vp-hero-kicker">财报 · 自动投研</div>
        <h1 class="vp-title">财报分析</h1>
        <p class="vp-subtitle">上传 PDF 后自动生成提纲，支持逐题重算与重点追问</p>
      </div>
    </header>

    <div class="page-container">
      <div class="grid-2col">
        <div class="left-stack">
          <div class="card">
            <div class="card-title-row">
              <div class="card-title">上传财报 PDF</div>
              <span class="pill">🔒 加密</span>
            </div>

            <div class="muted card-subtitle">
              上传后点击“开始自动调研”，生成 5 问 5 解
            </div>

            <div class="upload-center">
              <label class="upload-drop">
                <input class="upload-input" type="file" accept="application/pdf" @change="onPickFile" />
                <div class="upload-drop-inner">
                  <div class="upload-icon">📄</div>
                  <div class="upload-main">将文件拖放到此处</div>
                  <div class="upload-sub">或点击上传（PDF，最大 10MB）</div>
                </div>
              </label>
            </div>

            <div v-if="fileName" style="margin-top: 12px" class="card file-preview-card">
              <button class="file-remove-x" type="button" @click="resetFile" aria-label="删除文件">×</button>
              <div class="file-title">{{ fileName }}</div>
              <div class="muted file-sub">{{ formatBytes(fileSize) }}</div>
            </div>

            <div style="margin-top: 14px; display: flex; gap: 10px; align-items: center">
              <button
                class="btn-start"
                :disabled="uiState === 'uploading' || uiState === 'running' || !sessionId"
                @click="start"
              >
                开始自动调研
              </button>
              <span class="muted" style="font-size: 13px" v-if="uiState === 'running'">
                {{ stage || '处理中...' }}
              </span>
            </div>

            <div v-if="uiState === 'error' && errorMsg" style="margin-top: 12px; color: #f53f3f; font-weight: 700">
              {{ errorMsg }}
            </div>
          </div>

          <!-- 生成解析后：三张说明卡片放左侧并竖排 -->
          <div v-if="pages.length" class="fill-col">
            <div class="card fill-card">
              <div class="fill-title">你将获得</div>
              <ul class="fill-list">
                <li><span class="dot"></span> 5 个高价值问题（避免模板化套话）</li>
                <li><span class="dot"></span> 每题给出“核心结论/细节/关键数字”</li>
                <li><span class="dot"></span> 可编辑单题重算，快速迭代提纲</li>
              </ul>
            </div>
            <div class="card fill-card">
              <div class="fill-title">使用建议</div>
              <ul class="fill-list">
                <li><span class="dot"></span> 优先上传可复制文字的 PDF（非扫描件）</li>
                <li><span class="dot"></span> 先跑一遍，再用“编辑本题”精修重点问题</li>
                <li><span class="dot"></span> 若进度停在某一步超过 2 分钟，可点击“删除文件”后重新上传再试</li>
              </ul>
            </div>
            <div class="card fill-card">
              <div class="fill-title">隐私与安全</div>
              <div class="fill-text muted">
                本地前后端运行；上传文件仅用于生成本次结果。你可以随时删除文件并重新上传。
              </div>
              <div class="fill-badges">
                <span class="pill">🔒 加密传输</span>
                <span class="pill">🧾 可溯源页码</span>
              </div>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-title-row">
            <div class="card-title">投研提纲</div>
            <span class="pill">✨ 自动生成</span>
          </div>
          <div v-if="toastMsg" class="toast-tip">{{ toastMsg }}</div>

          <div v-if="!pages.length" class="muted" style="font-size: 14px">
            <div class="right-hint">
              请先在左侧上传一份财报 PDF，然后点击「开始自动调研」。
            </div>
            <ul class="right-checklist">
              <li><span class="ck">✓</span> 核心财务指标分析</li>
              <li><span class="ck">✓</span> 营收/利润趋势拆解</li>
              <li><span class="ck">✓</span> 风险点与机会点提示</li>
              <li><span class="ck">✓</span> 同行业对比分析</li>
            </ul>
          </div>

          <div v-else>
            <div style="display: flex; align-items: center; justify-content: space-between; gap: 10px">
              <div class="muted" style="font-size: 13px">
                第 <b class="mono">{{ pageIndex + 1 }}</b> / <b class="mono">{{ pages.length }}</b> 题
              </div>
              <button class="btn-secondary" @click="openEdit">编辑本题</button>
            </div>

            <div class="analysis-content" style="margin-top: 12px" v-html="currentPageHtml"></div>

            <div class="pager-row">
              <button class="btn-secondary btn-prev" @click="prev" :disabled="pageIndex <= 0">← 上一题</button>
              <button class="btn-secondary btn-next" @click="next" :disabled="!pages.length || pageIndex >= pages.length - 1">
                下一题 →
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 生成解析前：三张说明卡片横向排列（页面底部） -->
      <div v-if="!pages.length" class="below-fill">
        <div class="fill-grid">
          <div class="card fill-card">
            <div class="fill-title">你将获得</div>
            <ul class="fill-list">
              <li><span class="dot"></span> 5 个高价值问题（避免模板化套话）</li>
              <li><span class="dot"></span> 每题给出“核心结论/细节/关键数字”</li>
              <li><span class="dot"></span> 可编辑单题重算，快速迭代提纲</li>
            </ul>
          </div>
          <div class="card fill-card">
            <div class="fill-title">使用建议</div>
            <ul class="fill-list">
              <li><span class="dot"></span> 优先上传可复制文字的 PDF（非扫描件）</li>
              <li><span class="dot"></span> 先跑一遍，再用“编辑本题”精修重点问题</li>
              <li><span class="dot"></span> 若进度停在某一步超过 2 分钟，可点击“删除文件”后重新上传再试</li>
            </ul>
          </div>
          <div class="card fill-card">
            <div class="fill-title">隐私与安全</div>
            <div class="fill-text muted">
              本地前后端运行；上传文件仅用于生成本次结果。你可以随时删除文件并重新上传。
            </div>
            <div class="fill-badges">
              <span class="pill">🔒 加密传输</span>
              <span class="pill">🧾 可溯源页码</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="showEdit" style="position: fixed; inset: 0; background: rgba(0,0,0,0.35); z-index: 9999">
      <div
        class="card"
        style="
          max-width: 760px;
          margin: 8vh auto;
          border-radius: 18px;
          border: 1px solid rgba(183,148,71,0.45);
          box-shadow: 0 30px 70px rgba(0, 0, 0, 0.25);
        "
      >
        <div style="font-size: 16px; font-weight: 900; margin-bottom: 10px">编辑当前题目（保存后仅重生成本题解析）</div>

        <div class="muted" style="font-size: 13px; margin: 8px 0">自定义问题（可选）</div>
        <input
          v-model="editQuestion"
          type="text"
          placeholder="例如：三季度收入环比+14%背后的主要驱动拆解？"
          class="edit-text"
          :disabled="isRegenerating"
          style="
            width: 100%;
            height: 44px;
            border-radius: 16px;
            padding: 0 12px;
            outline: none;
          "
        />

        <div class="muted" style="font-size: 13px; margin: 12px 0 8px">换一个数据点（可选）</div>
        <select
          v-model="editChoice"
          class="edit-select"
          :disabled="isRegenerating"
          style="
            width: 100%;
            height: 44px;
            border-radius: 16px;
            padding: 0 12px;
            outline: none;
          "
        >
          <option value="">不选择</option>
          <option v-for="c in factChoices" :key="c" :value="c">{{ c }}</option>
        </select>

        <div class="edit-actions">
          <div v-if="isRegenerating" class="edit-loading">
            <span class="spin"></span>
            正在重新生成…
          </div>
          <div style="display: flex; justify-content: flex-end; gap: 10px">
            <button class="btn-secondary" @click="closeEdit" :disabled="isRegenerating">取消</button>
            <button class="btn-primary" @click="saveEdit" :disabled="isRegenerating">
              {{ isRegenerating ? '生成中…' : '保存并重生成' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>


function normalizeText(s) {
  return String(s || '')
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .replace(/[ \t]+\n/g, '\n')
    .trim()
}

/** 去掉模型偶发的 ** 加粗标记，避免正文里露出星号 */
function stripInlineBoldMarkers(s) {
  return String(s || '')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*\*/g, '')
    .trim()
}

/** 去掉行首「1. 」「2、」「3）」等序号（关键数字区常见，与圆点列表重复） */
function stripLeadingOrderedMark(s) {
  return String(s || '')
    .replace(/^\d{1,2}[\.\、．)）]\s*/, '')
    .trim()
}

/**
 * 将后端返回的 markdown（固定结构）解析成可渲染 blocks：
 * - h3: "### x. 问题"
 * - sec: "核心结论：" / "细节1：" / "细节2：" / "关键数字/概念："
 * - p: 段落
 * - ul: 列表
 */
function parsePageToBlocks(md) {
  let text = normalizeText(md)
  if (!text) return []
  // 与后端一致：全文不出现「未披露」；旧缓存兜底
  text = text.replace(/未披露/g, '需对照年报核实')
  const lines = text.split('\n')
  const out = []
  let curList = null

  function flushList() {
    if (curList && curList.items && curList.items.length) out.push(curList)
    curList = null
  }

  for (const raw of lines) {
    const ln = String(raw || '').trim()
    if (!ln) {
      flushList()
      continue
    }
    const mH3 = ln.match(/^###\s+(.*)$/)
    if (mH3) {
      flushList()
      let h3t = mH3[1].trim()
      h3t = h3t.replace(/\s*[（(]\s*P\d+\s*[）)]\s*$/i, '').trim()
      h3t = h3t.replace(/\s*[（(]\s*第\s*\d+\s*页\s*[）)]\s*$/, '').trim()
      out.push({ type: 'h3', text: h3t })
      continue
    }
    // 须匹配「标签+正文」同一行（模型常写成「核心结论：根据P5…」），否则整行会变成 p，标题无蓝色样式
    const mSec = ln.match(
      /^\*{0,2}(核心结论|细节1|细节2|关键数字\/概念)\*{0,2}[：:]\s*(.*)$/
    )
    if (mSec) {
      flushList()
      const title = `${mSec[1]}：`
      out.push({ type: 'sec', text: title })
      const rest = stripLeadingOrderedMark(stripInlineBoldMarkers(mSec[2] || ''))
      if (rest) {
        out.push({ type: 'p', text: rest })
      }
      continue
    }
    const mLi = ln.match(/^[-*]\s+(.*)$/)
    if (mLi) {
      if (!curList) curList = { type: 'ul', items: [] }
      curList.items.push(stripLeadingOrderedMark(mLi[1].trim()))
      continue
    }
    flushList()
    out.push({ type: 'p', text: stripLeadingOrderedMark(ln) })
  }
  flushList()
  return out
}

module.exports = {
  parsePageToBlocks
}

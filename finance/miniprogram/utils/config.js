/**
 * 后端服务地址（与 finance/backend Flask 一致）
 *
 * - 微信开发者工具 + 本机后端：可用 http://127.0.0.1:5000
 * - 真机预览 / 体验版：必须改为电脑的局域网 IP，例如 http://192.168.1.100:5000
 *   （电脑与手机同一 WiFi；后端需 host=0.0.0.0 监听）
 *
 * 也可在启动后执行（仅当前设备有效）：
 * wx.setStorageSync('finance_api_base', 'http://192.168.x.x:5000')
 */
const DEFAULT_API_BASE = 'http://127.0.0.1:5000'

function getApiBase() {
  try {
    const v = wx.getStorageSync('finance_api_base')
    if (v && typeof v === 'string' && /^https?:\/\//i.test(v)) {
      return String(v).replace(/\/$/, '')
    }
  } catch (e) {}
  return DEFAULT_API_BASE
}

module.exports = {
  DEFAULT_API_BASE,
  getApiBase
}

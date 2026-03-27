const { reportTips } = require('../../utils/data')
const { uploadPdf, startAnalyze, getTask } = require('../../utils/api')

Page({
  data: {
    reportTips,
    fileInfo: null,
    sessionId: '',
    taskId: '',
    taskStatus: '',
    stage: '',
    resultText: '',
    loading: false
  },
  showTip() {
    wx.showToast({ title: '目前是静态演示版', icon: 'none' })
  },
  choosePdf() {
    wx.chooseMessageFile({
      count: 1,
      type: 'file',
      extension: ['pdf'],
      success: async (res) => {
        const file = (res.tempFiles || [])[0]
        if (!file || !file.path) return
        this.setData({ loading: true, resultText: '', taskStatus: '', stage: '' })
        try {
          const out = await uploadPdf(file.path, file.name || 'report.pdf')
          this.setData({
            fileInfo: out.fileInfo || { name: file.name || 'report.pdf', size: file.size || 0 },
            sessionId: out.sessionId || '',
            loading: false
          })
          wx.showToast({ title: '上传成功', icon: 'success' })
        } catch (e) {
          this.setData({ loading: false })
          wx.showToast({ title: '上传失败', icon: 'none' })
        }
      }
    })
  },
  async runAnalyze() {
    const sessionId = this.data.sessionId
    if (!sessionId) {
      wx.showToast({ title: '请先上传PDF', icon: 'none' })
      return
    }
    this.setData({ loading: true, resultText: '', taskStatus: 'queued', stage: '任务已创建' })
    try {
      const out = await startAnalyze(sessionId)
      const taskId = out.taskId || ''
      this.setData({ taskId, taskStatus: 'running', stage: '分析中...' })
      this.pollTask(taskId)
    } catch (e) {
      this.setData({ loading: false, taskStatus: 'failed', stage: '启动失败' })
      wx.showToast({ title: '启动分析失败', icon: 'none' })
    }
  },
  pollTask(taskId) {
    const run = async () => {
      try {
        const out = await getTask(taskId)
        const status = out.status || ''
        const stage = out.stage || ''
        this.setData({ taskStatus: status, stage })
        if (status === 'succeeded') {
          const result = out.result || {}
          const text = String(result.summary || result.answer || '分析完成，请在后端查看完整结构化结果。')
          this.setData({ loading: false, resultText: text })
          return
        }
        if (status === 'failed') {
          this.setData({ loading: false, resultText: out.error || '分析失败' })
          return
        }
      } catch (e) {
        this.setData({ loading: false, taskStatus: 'failed', stage: '轮询失败' })
        return
      }
      setTimeout(run, 1500)
    }
    void run()
  }
})


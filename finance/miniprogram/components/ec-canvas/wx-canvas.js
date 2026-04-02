class WxCanvas {
  constructor(ctx, canvasId, isNew, canvasNode) {
    this.ctx = ctx
    this.canvasId = canvasId
    this.chart = null
    this.isNew = isNew
    if (isNew) {
      this.canvasNode = canvasNode
    } else {
      this._initStyle(ctx)
    }
    this._initEvent()
  }

  getContext(contextType) {
    if (contextType === '2d') {
      return this.ctx
    }
  }

  setChart(chart) {
    this.chart = chart
  }

  addEventListener() {}
  attachEvent() {}
  detachEvent() {}

  _initStyle(ctx) {
    ctx.createRadialGradient = () => ctx.createCircularGradient(arguments)
  }

  _initEvent() {
    this.event = {}
  }

  set width(w) {
    if (this.canvasNode) this.canvasNode.width = w
  }
  set height(h) {
    if (this.canvasNode) this.canvasNode.height = h
  }

  get width() {
    if (this.canvasNode) return this.canvasNode.width
    return 0
  }
  get height() {
    if (this.canvasNode) return this.canvasNode.height
    return 0
  }
}

module.exports = WxCanvas

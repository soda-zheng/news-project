# Frontend (Vue)

当前仓库里暂存了旧版 `new_file.html`（原生 HTML + 内联 JS/CSS），后续会迁移为 Vue3 项目。

建议下一步（前端）：
1. 使用 Vite 创建 Vue3 项目：`frontend/`
2. 在 `src/` 中实现：
   - `MarketStrip`：轮询 `/api/core-quotes`
   - `FxModal`：查询 `/api/convert`，结果显示后每 3 秒自动刷新
   - `StockModal`：查询 `/api/stock`，结果显示后每 3 秒自动刷新

后端默认在 **`http://127.0.0.1:5000`**。前端 `src/api/client.js` **默认直连该地址**（不依赖 Vite 代理），请先启动 Flask 再开 `npm run dev`。

自测：浏览器直接打开 `http://127.0.0.1:5000/api/topics/stock-insight`（GET）应返回 JSON；若连接失败说明后端未启动。

可选：`vite.config.js` 仍保留 `/api` 代理；若坚持走代理，可在 `frontend/.env.local` 设置 `VITE_API_RELATIVE=1`。

部署线上时构建前设置 `VITE_API_BASE_URL` 指向真实后端域名。


# d-demo2

## 结构说明（前后端分离）
- `backend/`：Python Flask 后端（行情/换算/股票查询 API）
- `frontend/`：Vue 前端（当前仅有迁移说明，后续把旧页面迁移为 Vue 组件）
- 根目录仍保留 `app.py` / `new_file.html` 作为历史参考（后续可删除或迁移到 `frontend/legacy/`）

## 后端启动
进入 `backend/`：
```bash
pip install -r requirements.txt
python app.py
```

后端默认监听 `http://localhost:5000`

## API
- `GET /api/core-quotes`
- `GET /api/convert?amount=...&from=...&to=...`
- `GET /api/stock?symbol=...`


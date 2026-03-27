# finance backend

用于 `finance/miniprogram` 的本地后端（先跑通接口联调，不依赖第三方服务）。

## 启动

```bash
cd finance/backend
python -m pip install -r requirements.txt
python app.py
```

默认监听：`http://127.0.0.1:5000`

## 已提供接口

- `GET /api/ping`
- `GET /api/topics/hot?limit=10`
- `GET /api/news/home?page=1&num=20`
- `GET /api/stock?symbol=300750`
- `POST /api/topics/stock-insight`
- `POST /api/research/analyze`
- `POST /api/upload`
- `POST /api/analyze`
- `GET /api/tasks/<taskId>`

## 说明

- 财报分析相关为任务模拟流程（upload -> analyze -> tasks 轮询），用于前端联调。
- 目前数据为本地样例；后续可替换为数据库或外部行情源。

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
- `GET /api/news/home?page=1&num=20`（首页热点新闻：优先 **AkShare `stock_info_global_sina`** 新浪财经全球财经快讯；失败时回退新浪滚动接口）
- `GET /api/news/sina-global?limit=20`（仅全球快讯，便于联调）
- `GET /api/stock?symbol=300750`
- `POST /api/topics/stock-insight`
- `POST /api/research/analyze`
- `POST /api/upload`
- `POST /api/analyze`
- `GET /api/tasks/<taskId>`

## 说明

- 财报分析相关为任务模拟流程（upload -> analyze -> tasks 轮询），用于前端联调。
- 热点新闻依赖 **akshare** 拉取 `https://finance.sina.com.cn/7x24` 同源快讯数据；需本机可访问外网。
- 若 akshare 未安装或请求失败，`/api/news/home` 会自动回退为原有新浪滚动新闻筛选逻辑。

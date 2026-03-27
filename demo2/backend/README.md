# Backend (Flask)

## 运行
```bash
pip install -r requirements.txt
python app.py
```
服务端默认监听 `0.0.0.0:5000`

## 目录（模块化）
- `app.py`：应用入口与路由注册（兼容现有 API）
- `core/env.py`：`.env` / `.env.local` 加载
- `modules/videos/service.py`：视频数据读取（`data/videos.json`）
- `modules/topics/service.py`：涨幅榜返回结构组装
- `data/videos.json`：视频配置数据源

## 接口契约

### 1. 实时核心行情
`GET /api/core-quotes`

返回：
```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "update_time": "YYYY-MM-DD HH:mm:ss",
    "quotes": [
      { "name": "人民币/美元", "price": 7.1852, "chg": 0.0123, "pct_chg": 0.17, "update_time": "..." },
      { "name": "现货黄金", "price": 2650.12, "chg": -16.14, "pct_chg": -0.32, "update_time": "..." },
      { "name": "WTI原油",    "price": 93.6,    "chg": -1.93, "pct_chg": -2.02, "update_time": "..." }
    ]
  }
}
```

### 2. 货币换算
`GET /api/convert?amount=1&from=USD&to=CNY`

返回：
```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "amount": 1,
    "from": "USD",
    "to": "CNY",
    "rate": 7.18,
    "result": 7.18,
    "update_time": "..."
  }
}
```

### 3. 股票查询
`GET /api/stock?symbol=sh600519`

返回：
```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "symbol": "sh600519",
    "name": "贵州茅台",
    "price": 100.00,
    "chg": 1.23,
    "pct_chg": 1.23,
    "open": 98.00,
    "prev_close": 98.77,
    "high": 101.00,
    "low": 97.50,
    "update_time": "..."
  }
}
```

### 4. 涨幅榜 AI 解读（可选大模型）

与新闻摘要共用环境变量：`LLM_API_BASE`、`LLM_API_KEY`、`LLM_MODEL`（见 `.env.example`）。  
可设置 `TOPICS_LLM_DAILY_LIMIT`（默认 40）限制「个股+盘面」合计调用次数；超限或未配置时回退规则模板。

- **盘面要点** `POST /api/topics/board-insight`  
  Body：`{ "items": [ { "name", "leader", "pct_chg" }, ... ] }`（建议 ≤40 条）  
  返回：`data.bullets`、`data.source`（`llm` | `template`）

- **个股解读** `POST /api/topics/stock-insight`  
  Body：`{ "name", "leader", "pct_chg", "rank", "avg_pct", "board_top": [ ... ] }`  
  返回：`data.lines`、`data.disclaimer`、`data.source`


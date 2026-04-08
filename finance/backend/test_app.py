from app import app

print('✅ Flask app 导入成功')
print('测试 /api/news/home-enhanced 路由...')

# 模拟请求
from flask.testing import FlaskClient
client = app.test_client()

response = client.get('/api/news/home-enhanced?limit=3')
print('状态码:', response.status_code)
print('响应:', response.data[:500])

from app import news_home_enhanced
from flask.testing import FlaskClient
from app import app

print('✅ 测试 news_home_enhanced 函数...')

# 模拟请求
client = app.test_client()

response = client.get('/api/news/home-enhanced?limit=3')
print('状态码:', response.status_code)
print('响应:', response.data[:500])

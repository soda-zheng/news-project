from app import app

print('✅ Flask app 导入成功')

print('\n所有路由:')
for rule in app.url_map.iter_rules():
    print('  -', rule.rule, '->', rule.endpoint)

print('\n新闻相关路由:')
for rule in app.url_map.iter_rules():
    if '/api/news' in rule.rule:
        print('  -', rule.rule, '->', rule.endpoint)

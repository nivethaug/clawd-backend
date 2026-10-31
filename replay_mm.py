import json, urllib.request

msgs = json.load(open('/tmp/replay_msgs.json'))
login_req = urllib.request.Request(
    'https://api.dreamagent.cloud/auth/login',
    data=json.dumps({"email": "support@dreambigwithai.com", "password": "Nivetha@3117"}).encode(),
    method='POST', headers={'Content-Type': 'application/json'})
with urllib.request.urlopen(login_req, timeout=30) as r:
    token = json.loads(r.read().decode()).get('token') or ''

payload = json.dumps({
    'messages': msgs,
    'context': {
        'detected_kind': 'agent',
        'project_name': 'market-morning',
        'connected_env_names': ['TELEGRAM_BOT_TOKEN'],
        'bot_token_verified': True,
        'saved_integration_keys': ['OPENROUTER_API_KEY', 'TELEGRAM_BOT_TOKEN'],
    },
}).encode()
req = urllib.request.Request(
    'http://127.0.0.1:8002/api/projects/create-assistant',
    data=payload, method='POST',
    headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
with urllib.request.urlopen(req, timeout=150) as r:
    d = json.loads(r.read().decode())
print('reply:', (d.get('reply') or '')[:120])
print('brief kind:', (d.get('brief') or {}).get('kind'))
print('brief prompt len:', len((d.get('brief') or {}).get('prompt') or ''))
print('required_tokens:', d.get('required_tokens'))
print('required_env:', d.get('required_env'))

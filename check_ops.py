import psycopg2

env = {}
for line in open('/root/clawd-backend/.env'):
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        env[k.strip()] = v.strip()
conn = psycopg2.connect(host=env['DB_HOST'], port=env['DB_PORT'], dbname=env['DB_NAME'],
                        user=env['DB_USER'], password=env['DB_PASSWORD'])
cur = conn.cursor()
cur.execute("SELECT id, name, status FROM projects WHERE name LIKE 'sp-%%' OR name LIKE '%%pulse%%' ORDER BY id DESC LIMIT 10")
for r in cur.fetchall():
    print(r)
conn.close()

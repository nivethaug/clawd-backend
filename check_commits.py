import os
import psycopg2
from psycopg2.extras import RealDictCursor

conn = psycopg2.connect(
    host='localhost', port=5432, dbname='dreampilot',
    user='admin', password=os.getenv('DB_PASSWORD', '')
)
cur = conn.cursor(cursor_factory=RealDictCursor)

# Check commit_log table
cur.execute("""
    SELECT id, project_id, session_id, message_id,
           substring(commit_hash, 1, 8) as hash,
           commit_message, status, created_at
    FROM commit_log
    ORDER BY created_at DESC
    LIMIT 20
""")
rows = cur.fetchall()

print("=" * 80)
print("commit_log table")
print("=" * 80)

if not rows:
    print("Table is EMPTY - no commits logged yet\n")
else:
    for r in rows:
        print(f"  id={r['id']}  proj={r['project_id']}  sess={r['session_id']}  msg={r['message_id']}")
        print(f"  hash={r['hash']}  status={r['status']}  created={r['created_at']}")
        print(f"  message: {r['commit_message'][:80]}")
        print()
    print(f"Total entries shown: {len(rows)}")

# Also check total count
cur.execute("SELECT COUNT(*) as cnt FROM commit_log")
total = cur.fetchone()['cnt']
print(f"Total rows in commit_log: {total}")

# Check messages with commit_hash
print("\n" + "=" * 80)
print("messages with commit_hash")
print("=" * 80)
cur.execute("""
    SELECT id, session_id, role, substring(commit_hash, 1, 8) as hash,
           commit_status, reverted_message_id
    FROM messages
    WHERE commit_hash IS NOT NULL
    ORDER BY id DESC
    LIMIT 10
""")
msg_rows = cur.fetchall()
if not msg_rows:
    print("No messages with commit_hash found\n")
else:
    for r in msg_rows:
        print(f"  msg_id={r['id']}  sess={r['session_id']}  role={r['role']}  hash={r['hash']}  status={r['commit_status']}  reverted={r['reverted_message_id']}")
    print(f"\nTotal: {len(msg_rows)}")

cur.close()
conn.close()

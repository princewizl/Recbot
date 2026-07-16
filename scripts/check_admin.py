import sqlite3

conn = sqlite3.connect('bot.db')
cur = conn.cursor()
try:
    cur.execute('SELECT id, email, role, business_id FROM users')
    rows = cur.fetchall()
    if not rows:
        print('NO_USERS')
    else:
        for r in rows:
            print(r)
finally:
    conn.close()

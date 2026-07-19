import sqlite3
import hashlib

EMAIL = 'olufemi.mohammed11@gmail.com'
PASSWORD = 'Pass@12345'
DB = 'bot.db'

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

conn = sqlite3.connect(DB)
cur = conn.cursor()
try:
    cur.execute('SELECT id FROM users WHERE email = ?', (EMAIL,))
    if cur.fetchone():
        print('ALREADY_EXISTS')
    else:
        pw_hash = hash_password(PASSWORD)
        cur.execute('INSERT INTO users (email, password_hash, role, business_id) VALUES (?, ?, ?, ?)', (EMAIL, pw_hash, 'admin', None))
        conn.commit()
        print('CREATED', EMAIL)
finally:
    conn.close()

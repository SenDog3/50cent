import os
import psycopg2

url = os.getenv("DATABASE_URL")
if not url:
    print("❌ DATABASE_URL отсутствует!")
    exit(1)

print("✅ DATABASE_URL найден, подключаемся...")
conn = psycopg2.connect(url)
cur = conn.cursor()

cur.execute("""
    INSERT INTO shared_settings (key, value)
    VALUES (%s, %s)
    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP;
""", ("check_db_run", "test"))
conn.commit()

cur.execute("SELECT key, value FROM shared_settings WHERE key = %s", ("check_db_run",))
row = cur.fetchone()

if row:
    print(f"✅ УСПЕХ: прочитали из БД -> {row}")
else:
    print("❌ Не удалось прочитать строку")

cur.close()
conn.close()


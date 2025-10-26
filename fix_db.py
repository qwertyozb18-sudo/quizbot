import sqlite3

conn = sqlite3.connect("quiz_bot.db")
cur = conn.cursor()

# Faqat coins ustunini qo‘shamiz
try:
    cur.execute("ALTER TABLE users ADD COLUMN coins INTEGER DEFAULT 0")
    print("✅ coins ustuni qo‘shildi.")
except sqlite3.OperationalError:
    print("ℹ️ coins ustuni allaqachon mavjud.")

conn.commit()
conn.close()

print("✅ Baza yangilandi.")

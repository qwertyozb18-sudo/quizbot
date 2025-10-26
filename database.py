import aiosqlite
import logging
from typing import Optional

DB_NAME = "quiz_bot.db"


# --- Logging setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Database fayl nomi ---
DB_NAME = "quiz_bot.db"


# === DASTLABKI INITSIALIZATSIYA ===
async def init_db():
    """Ma'lumotlar bazasini yaratish va jadvallarni sozlash"""
    async with aiosqlite.connect(DB_NAME) as db:
        # --- USERS ---
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                total_score INTEGER DEFAULT 0,
                coins INTEGER DEFAULT 0
            )
        ''')

        # --- QUIZ_SESSIONS ---
        await db.execute('''
            CREATE TABLE IF NOT EXISTS quiz_sessions (
                session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # --- USER_ANSWERS ---
        await db.execute('''
            CREATE TABLE IF NOT EXISTS user_answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                user_id INTEGER,
                question_number INTEGER,
                is_correct INTEGER,
                score INTEGER DEFAULT 0,
                FOREIGN KEY (session_id) REFERENCES quiz_sessions(session_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                UNIQUE(session_id, user_id, question_number)
            )
        ''')

        # --- QUESTIONS ---
        await db.execute('''
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                question TEXT NOT NULL,
                option1 TEXT NOT NULL,
                option2 TEXT NOT NULL,
                option3 TEXT NOT NULL,
                option4 TEXT NOT NULL,
                correct_option_id INTEGER NOT NULL,
                image_url TEXT,              -- 🖼️ YANGI USTUN (rasm file_id yoki URL saqlanadi)
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        await db.commit()
        logger.info("✅ Ma'lumotlar bazasi muvaffaqiyatli yaratildi (image_url qo‘llab-quvvatlanadi).")

# === USER FUNKSIYALARI ===
async def get_or_create_user(
    user_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None
):
    """Foydalanuvchini olish yoki yaratish"""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = await cursor.fetchone()

        if not user:
            await db.execute(
                'INSERT INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)',
                (user_id, username, first_name, last_name)
            )
            await db.commit()
            logger.info(f"🆕 Yangi foydalanuvchi yaratildi: {user_id}")

            # Yangi foydalanuvchini qayta o‘qish
            cursor = await db.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            user = await cursor.fetchone()

        return user


# === QUIZ SESSION FUNKSIYALARI ===
async def create_quiz_session(chat_id: int):
    """Yangi quiz sessiyasini yaratish"""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute('INSERT INTO quiz_sessions (chat_id) VALUES (?)', (chat_id,))
        await db.commit()
        session_id = cursor.lastrowid
        logger.info(f"🟢 Yangi sessiya yaratildi: ID={session_id}")
        return session_id


async def close_session(session_id: int):
    """Sessiyani yopish"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('UPDATE quiz_sessions SET is_active = 0 WHERE session_id = ?', (session_id,))
        await db.commit()
        logger.info(f"🔴 Sessiya yopildi: ID={session_id}")


# === ANSWER / SCORE FUNKSIYALARI ===
async def save_user_answer(session_id: int, user_id: int, question_number: int, is_correct: bool):
    """Foydalanuvchi javobini saqlash yoki yangilash"""
    score = 1 if is_correct else 0
    await get_or_create_user(user_id)

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute('''
            SELECT is_correct, score FROM user_answers
            WHERE session_id = ? AND user_id = ? AND question_number = ?
        ''', (session_id, user_id, question_number))
        existing = await cursor.fetchone()

        if existing:
            old_is_correct, old_score = existing
            await db.execute('''
                UPDATE user_answers
                SET is_correct = ?, score = ?
                WHERE session_id = ? AND user_id = ? AND question_number = ?
            ''', (is_correct, score, session_id, user_id, question_number))
            score_diff = score - old_score
        else:
            await db.execute('''
                INSERT INTO user_answers (session_id, user_id, question_number, is_correct, score)
                VALUES (?, ?, ?, ?, ?)
            ''', (session_id, user_id, question_number, is_correct, score))
            score_diff = score

        if score_diff != 0:
            await db.execute('''
                UPDATE users
                SET total_score = total_score + ?, coins = coins + ?
                WHERE user_id = ?
            ''', (score_diff, score_diff, user_id))

        await db.commit()

# === REYTING / STATISTIKA FUNKSIYALARI ===
async def get_session_results(session_id: int):
    """Sessiya natijalarini olish"""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute('''
            SELECT u.user_id, u.username, u.first_name, SUM(ua.score) AS total_score
            FROM user_answers ua
            JOIN users u ON ua.user_id = u.user_id
            WHERE ua.session_id = ?
            GROUP BY u.user_id
            ORDER BY total_score DESC
        ''', (session_id,))
        return await cursor.fetchall()


# ==============================================
# 🔝 REYTING (GLOBAL VA GROUP)
# ==============================================

async def get_global_rating(limit: int = 10):
    """Barcha foydalanuvchilar bo‘yicha umumiy reyting"""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute('''
            SELECT user_id, username, first_name, total_score
            FROM users
            ORDER BY total_score DESC
            LIMIT ?
        ''', (limit,))
        return await cursor.fetchall()


# === SAVOL QO‘SHISH (rasm bilan yoki rasmsiz) ===
async def add_question(
    subject: str,
    question: str,
    options: list,
    correct_option_id: int,
    created_by: Optional[int] = None,
    image_url: Optional[str] = None
):
    """Yangi savol qo'shish (rasmli yoki rasmsiz)"""
    if len(options) != 4:
        raise ValueError("❌ 4 ta variant bo'lishi kerak!")

    async with aiosqlite.connect(DB_NAME) as db:
        try:
            # Agar jadvalda image_url ustuni mavjud bo‘lsa — shu orqali yozamiz
            await db.execute('''
                INSERT INTO questions (
                    subject, question, option1, option2, option3, option4,
                    correct_option_id, created_by, image_url
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                subject,
                question,
                options[0],
                options[1],
                options[2],
                options[3],
                correct_option_id,
                created_by,
                image_url
            ))
        except aiosqlite.OperationalError:
            # Agar image_url ustuni hali qo‘shilmagan bo‘lsa — eski formatda yozadi
            await db.execute('''
                INSERT INTO questions (
                    subject, question, option1, option2, option3, option4,
                    correct_option_id, created_by
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                subject,
                question,
                options[0],
                options[1],
                options[2],
                options[3],
                correct_option_id,
                created_by
            ))

        await db.commit()
        logger.info(f"➕ Yangi savol qo‘shildi: {subject} | {question}")


# === SAVOLLARNI O‘QISH ===
async def get_questions(subject: Optional[str] = None, limit: int = 20):
    """Savollarni olish (fan bo'yicha yoki barchasi)"""
    async with aiosqlite.connect(DB_NAME) as db:
        if subject:
            cursor = await db.execute('''
                SELECT id, subject, question, option1, option2, option3, option4, correct_option_id, image_url
                FROM questions WHERE subject = ? ORDER BY RANDOM() LIMIT ?
            ''', (subject, limit))
        else:
            cursor = await db.execute('''
                SELECT id, subject, question, option1, option2, option3, option4, correct_option_id, image_url
                FROM questions ORDER BY RANDOM() LIMIT ?
            ''', (limit,))
        rows = await cursor.fetchall()

        return [
            {
                "id": row[0],
                "subject": row[1],
                "question": row[2],
                "options": [row[3], row[4], row[5], row[6]],
                "correct_option_id": row[7],
                "image_url": row[8] if len(row) > 8 else None
            }
            for row in rows
        ]


# === SAVOLLAR SONINI O‘LCHASH ===
async def get_questions_count(subject: Optional[str] = None):
    """Savollar sonini olish"""
    async with aiosqlite.connect(DB_NAME) as db:
        if subject:
            cursor = await db.execute('SELECT COUNT(*) FROM questions WHERE subject = ?', (subject,))
        else:
            cursor = await db.execute('SELECT COUNT(*) FROM questions')
        (count,) = await cursor.fetchone()
        return count
    
    # === GURUH REYTINGI FUNKSIYASI ===
async def get_group_rating(chat_id: int, limit: int = 10):
    """Berilgan chat (guruh) uchun reyting — eng ko‘p to‘g‘ri javob bergan foydalanuvchilar"""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute('''
            SELECT 
                u.user_id, 
                u.username, 
                u.first_name, 
                SUM(ua.score) AS group_score
            FROM user_answers ua
            JOIN users u ON ua.user_id = u.user_id
            JOIN quiz_sessions qs ON ua.session_id = qs.session_id
            WHERE qs.chat_id = ?
            GROUP BY u.user_id
            ORDER BY group_score DESC
            LIMIT ?
        ''', (chat_id, limit))
        return await cursor.fetchall()
    
# === WEEKLY RATING FUNKSIYALARI ===
async def get_top_users(limit=10):
    """TOP foydalanuvchilarni olish"""
    async with aiosqlite.connect(DB_NAME) as db:   # ← to‘g‘rilandi
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT user_id, username, coins FROM users ORDER BY coins DESC LIMIT ?",
            (limit,)
        )
        users = await cursor.fetchall()
        return users


async def reset_all_coins():
    """Barcha foydalanuvchilarning tangalarini 0 ga tushirish"""
    async with aiosqlite.connect(DB_NAME) as db:   # ← to‘g‘rilandi
        await db.execute("UPDATE users SET coins = 0")
        await db.commit()
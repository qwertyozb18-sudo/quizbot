import asyncpg
import logging
import os
from typing import Optional
from bot.config import DATABASE_URL

# Global connection pool
pool: Optional[asyncpg.Pool] = None

# --- Logging setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === DASTLABKI INITSIALIZATSIYA ===
async def init_db():
    """Ma'lumotlar bazasini yaratish va jadvallarni sozlash (PostgreSQL)"""
    global pool
    if not DATABASE_URL:
        logger.error("❌ DATABASE_URL topilmadi! .env ni tekshiring.")
        return

    # Create pool if not exists
    if pool is None:
        pool = await asyncpg.create_pool(DATABASE_URL)
        logger.info("✅ PostgreSQL connection pool created.")

    async with pool.acquire() as conn:
        # --- USERS ---
        # user_id BIGINT (Telegram IDs > 2^31)
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                total_score INTEGER DEFAULT 0,
                coins INTEGER DEFAULT 0
            )
        ''')

        # --- QUIZ_SESSIONS ---
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS quiz_sessions (
                session_id SERIAL PRIMARY KEY,
                chat_id BIGINT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT NOW()
            )
        ''')

        # --- USER_ANSWERS ---
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS user_answers (
                id SERIAL PRIMARY KEY,
                session_id INTEGER REFERENCES quiz_sessions(session_id),
                user_id BIGINT REFERENCES users(user_id),
                question_number INTEGER,
                is_correct INTEGER,
                score INTEGER DEFAULT 0,
                UNIQUE(session_id, user_id, question_number)
            )
        ''')

        # --- QUESTIONS ---
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS questions (
                id SERIAL PRIMARY KEY,
                subject TEXT NOT NULL,
                question TEXT NOT NULL,
                option1 TEXT NOT NULL,
                option2 TEXT NOT NULL,
                option3 TEXT NOT NULL,
                option4 TEXT NOT NULL,
                correct_option_id INTEGER NOT NULL,
                image_url TEXT,
                created_by BIGINT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        ''')

        # --- WITHDRAWALS ---
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS withdrawals (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                amount_coins INTEGER,
                amount_money REAL,
                status TEXT DEFAULT 'pending', 
                created_at TIMESTAMP DEFAULT NOW()
            )
        ''')

        # --- SETTINGS ---
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')

        # --- SUBJECTS ---
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS subjects (
                name TEXT PRIMARY KEY
            )
        ''')
        
        # Default exchange rate
        await conn.execute("INSERT INTO settings (key, value) VALUES ('exchange_rate', '100') ON CONFLICT DO NOTHING")

        logger.info("✅ Database tables checked/created.")

# === SUBJECTS FUNKSIYALARI ===
async def get_custom_subjects_list():
    global pool
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT name FROM subjects")
        return [r['name'] for r in rows]

async def add_custom_subject(name: str):
    global pool
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO subjects (name) VALUES ($1) ON CONFLICT DO NOTHING", name)

async def remove_custom_subject(name: str):
    global pool
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM subjects WHERE name = $1", name)

# === USER FUNKSIYALARI ===
async def get_or_create_user(
    user_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None
):
    global pool
    if not pool: await init_db()
    
    async with pool.acquire() as conn:
        # Try updating first (if exists) or insert
        # We want to return the user.
        # Postgres UPSERT:
        await conn.execute('''
            INSERT INTO users (user_id, username, first_name, last_name)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id) DO UPDATE 
            SET username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name
        ''', user_id, username, first_name, last_name)
        
        row = await conn.fetchrow('SELECT * FROM users WHERE user_id = $1', user_id)
        return row

# === QUIZ SESSION FUNKSIYALARI ===
async def create_quiz_session(chat_id: int):
    global pool
    async with pool.acquire() as conn:
        session_id = await conn.fetchval('INSERT INTO quiz_sessions (chat_id) VALUES ($1) RETURNING session_id', chat_id)
        logger.info(f"🟢 Yangi sessiya yaratildi: ID={session_id}")
        return session_id

async def close_session(session_id: int):
    global pool
    async with pool.acquire() as conn:
        await conn.execute('UPDATE quiz_sessions SET is_active = 0 WHERE session_id = $1', session_id)
        logger.info(f"🔴 Sessiya yopildi: ID={session_id}")

# === ANSWER / SCORE FUNKSIYALARI ===
async def save_user_answer(session_id: int, user_id: int, question_number: int, is_correct: bool):
    """Foydalanuvchi javobini saqlash yoki yangilash"""
    global pool
    score = 1 if is_correct else 0
    await get_or_create_user(user_id) # Ensure user exists

    async with pool.acquire() as conn:
        # Check existing
        existing = await conn.fetchrow('''
            SELECT is_correct, score FROM user_answers
            WHERE session_id = $1 AND user_id = $2 AND question_number = $3
        ''', session_id, user_id, question_number)

        score_diff = 0
        if existing:
            old_is_correct, old_score = existing
            await conn.execute('''
                UPDATE user_answers
                SET is_correct = $1, score = $2
                WHERE session_id = $3 AND user_id = $4 AND question_number = $5
            ''', 1 if is_correct else 0, score, session_id, user_id, question_number)
            score_diff = score - old_score
        else:
            await conn.execute('''
                INSERT INTO user_answers (session_id, user_id, question_number, is_correct, score)
                VALUES ($1, $2, $3, $4, $5)
            ''', session_id, user_id, question_number, 1 if is_correct else 0, score)
            score_diff = score

        if score_diff != 0:
            await conn.execute('''
                UPDATE users
                SET total_score = total_score + $1, coins = coins + $2
                WHERE user_id = $3
            ''', score_diff, score_diff, user_id)

# === REYTING / STATISTIKA FUNKSIYALARI ===
async def get_session_results(session_id: int):
    global pool
    async with pool.acquire() as conn:
        rows = await conn.fetch('''
            SELECT u.user_id, u.username, u.first_name, SUM(ua.score) AS total_score
            FROM user_answers ua
            JOIN users u ON ua.user_id = u.user_id
            WHERE ua.session_id = $1
            GROUP BY u.user_id, u.username, u.first_name
            ORDER BY total_score DESC
        ''', session_id)
        return rows

async def get_global_rating(limit: int = 10):
    global pool
    async with pool.acquire() as conn:
        rows = await conn.fetch('''
            SELECT user_id, username, first_name, total_score
            FROM users
            ORDER BY total_score DESC
            LIMIT $1
        ''', limit)
        return rows

async def get_user_rank(user_id: int):
    global pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow('SELECT total_score FROM users WHERE user_id = $1', user_id)
        if row:
            user_score = row['total_score']
            count = await conn.fetchval('SELECT COUNT(*) FROM users WHERE total_score > $1', user_score)
            return count + 1
        return None

# === SAVOL QO‘SHISH ===
async def add_question(
    subject: str,
    question: str,
    options: list,
    correct_option_id: int,
    created_by: Optional[int] = None,
    image_url: Optional[str] = None
):
    global pool
    if len(options) != 4:
        raise ValueError("❌ 4 ta variant bo'lishi kerak!")

    async with pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO questions (
                subject, question, option1, option2, option3, option4,
                correct_option_id, created_by, image_url
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ''', subject, question, options[0], options[1], options[2], options[3], correct_option_id, created_by, image_url)
        logger.info(f"➕ Yangi savol qo‘shildi: {subject} | {question}")

async def search_questions(text: str = "", subject: Optional[str] = None, question_id: Optional[int] = None):
    global pool
    async with pool.acquire() as conn:
        query = "SELECT id, subject, question, option1, option2, option3, option4, correct_option_id FROM questions WHERE 1=1"
        args = []
        i = 1

        if question_id:
            query += f" AND id = ${i}"
            args.append(question_id)
            i += 1
        
        if subject:
            query += f" AND subject = ${i}"
            args.append(subject)
            i += 1

        if text:
            query += f" AND question ILIKE ${i}" # ILIKE for case-insensitive
            args.append(f"%{text}%")
            i += 1
            
        return await conn.fetch(query, *args)

async def get_admin_dashboard_stats():
    global pool
    async with pool.acquire() as conn:
        total_questions = await conn.fetchval("SELECT COUNT(*) FROM questions")
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        
        # Postgres date math
        active_users = await conn.fetchval('''
            SELECT COUNT(DISTINCT ua.user_id) 
            FROM user_answers ua
            JOIN quiz_sessions qs ON ua.session_id = qs.session_id
            WHERE qs.created_at >= NOW() - INTERVAL '7 days'
        ''')
        
        inactive_users = total_users - active_users

        return {
            "total_questions": total_questions,
            "total_users": total_users,
            "active_users": active_users,
            "inactive_users": inactive_users
        }

async def delete_question(question_id: int):
    global pool
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM questions WHERE id = $1", question_id)

async def get_questions(subject: Optional[str] = None, limit: int = 20):
    global pool
    async with pool.acquire() as conn:
        if subject:
            rows = await conn.fetch('''
                SELECT id, subject, question, option1, option2, option3, option4, correct_option_id, image_url
                FROM questions WHERE subject = $1 ORDER BY RANDOM() LIMIT $2
            ''', subject, limit)
        else:
            rows = await conn.fetch('''
                SELECT id, subject, question, option1, option2, option3, option4, correct_option_id, image_url
                FROM questions ORDER BY RANDOM() LIMIT $1
            ''', limit)

        return [
            {
                "id": row['id'],
                "subject": row['subject'],
                "question": row['question'],
                "options": [row['option1'], row['option2'], row['option3'], row['option4']],
                "correct_option_id": row['correct_option_id'],
                "image_url": row['image_url']
            }
            for row in rows
        ]

async def get_questions_count(subject: Optional[str] = None):
    global pool
    async with pool.acquire() as conn:
        if subject:
            return await conn.fetchval('SELECT COUNT(*) FROM questions WHERE subject = $1', subject)
        else:
            return await conn.fetchval('SELECT COUNT(*) FROM questions')

async def get_group_rating(chat_id: int, limit: int = 10):
    global pool
    async with pool.acquire() as conn:
        return await conn.fetch('''
            SELECT 
                u.user_id, 
                u.username, 
                u.first_name, 
                SUM(ua.score) AS group_score
            FROM user_answers ua
            JOIN users u ON ua.user_id = u.user_id
            JOIN quiz_sessions qs ON ua.session_id = qs.session_id
            WHERE qs.chat_id = $1
            GROUP BY u.user_id, u.username, u.first_name
            ORDER BY group_score DESC
            LIMIT $2
        ''', chat_id, limit)

async def get_top_users(limit=10):
    global pool
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT user_id, username, coins FROM users ORDER BY coins DESC LIMIT $1", limit)

async def reset_all_coins():
    global pool
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET coins = 0")

async def get_user_stats(user_id: int):
    global pool
    async with pool.acquire() as conn:
        correct = await conn.fetchval("SELECT COUNT(*) FROM user_answers WHERE user_id = $1 AND is_correct = 1", user_id)
        incorrect = await conn.fetchval("SELECT COUNT(*) FROM user_answers WHERE user_id = $1 AND is_correct = 0", user_id)
        return {"total": correct + incorrect, "correct": correct, "incorrect": incorrect}

async def get_ranking_by_period(period: str = "all", limit: int = 10):
    global pool
    async with pool.acquire() as conn:
        if period == "all":
            return await conn.fetch('''
                SELECT user_id, username, first_name, total_score 
                FROM users 
                ORDER BY total_score DESC 
                LIMIT $1
            ''', limit)
        else:
            interval = "7 days" if period == "week" else "1 month"
            # In prepared statements we can't inject variable interval directly into string easily
            # Best to use logic or safe string format since interval is controlled by us
            
            # Using parameter for interval in Postgres is tricky: NOW() - $2::INTERVAL
            
            query = f'''
                SELECT u.user_id, u.username, u.first_name, SUM(ua.score) as period_score
                FROM user_answers ua
                JOIN users u ON ua.user_id = u.user_id
                JOIN quiz_sessions qs ON ua.session_id = qs.session_id
                WHERE qs.created_at >= NOW() - INTERVAL '{interval}'
                GROUP BY u.user_id, u.username, u.first_name
                ORDER BY period_score DESC
                LIMIT $1
            '''
            return await conn.fetch(query, limit)

async def get_exchange_rate():
    global pool
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT value FROM settings WHERE key = 'exchange_rate'")
        return float(val) if val else 100.0

async def set_exchange_rate(rate: float):
    global pool
    async with pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO settings (key, value) VALUES ('exchange_rate', $1)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        ''', str(rate))

async def create_withdrawal(user_id: int, coins: int, money: float):
    global pool
    async with pool.acquire() as conn:
        # Check current coins
        current_coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", user_id)
        if not current_coins or current_coins < coins:
            return False, "Hisobda yetarli tanga yo'q."
        
        # Deduct coins
        await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", coins, user_id)
        
        # Create record
        await conn.execute(
            "INSERT INTO withdrawals (user_id, amount_coins, amount_money) VALUES ($1, $2, $3)", 
            user_id, coins, money
        )
        return True, "So'rov muvaffaqiyatli yuborildi."

async def get_pending_withdrawals():
    global pool
    async with pool.acquire() as conn:
        return await conn.fetch('''
            SELECT w.id, w.user_id, u.username, w.amount_coins, w.amount_money, w.created_at
            FROM withdrawals w
            JOIN users u ON w.user_id = u.user_id
            WHERE w.status = 'pending'
        ''')

async def update_withdrawal_status(withdrawal_id: int, status: str):
    global pool
    async with pool.acquire() as conn:
        if status == 'rejected':
            row = await conn.fetchrow("SELECT user_id, amount_coins FROM withdrawals WHERE id = $1", withdrawal_id)
            if row:
                await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", row['amount_coins'], row['user_id'])
        
        await conn.execute("UPDATE withdrawals SET status = $1 WHERE id = $2", status, withdrawal_id)
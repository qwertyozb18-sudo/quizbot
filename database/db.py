import asyncpg
import aiosqlite
import logging
import os
import re
from typing import Optional, Any, List, Dict
from bot.config import DATABASE_URL

# Global connection handlers
pg_pool: Optional[asyncpg.Pool] = None
sqlite_db: Optional[str] = 'quiz_bot.db'
DB_TYPE = 'pg'  # 'pg' or 'sqlite'

# --- Logging setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === ABSTRACTION LAYER ===

async def get_connection():
    """Returns a connection context manager appropriate for the DB_TYPE"""
    pass # Not used directly, specific helpers used below

def _convert_to_sqlite(query: str, args: tuple) -> (str, tuple):
    """Converts Postgres query syntax to SQLite compatible syntax on the fly"""
    # Replace $n with ?
    new_query = re.sub(r'\$\d+', '?', query)
    
    # Replace ILIKE with LIKE
    new_query = new_query.replace('ILIKE', 'LIKE')
    
    # Replace SERIAL with INTEGER PRIMARY KEY AUTOINCREMENT in CREATE TABLE
    if 'CREATE TABLE' in new_query:
        new_query = new_query.replace('SERIAL PRIMARY KEY', 'INTEGER PRIMARY KEY AUTOINCREMENT')
        new_query = new_query.replace('BIGINT', 'INTEGER') # SQLite uses INTEGER for everything
        
    # Replace NOW() with CURRENT_TIMESTAMP for defaults
    # But for comparisons NOW() - INTERVAL is harder.
    # Simple regex for interval replacement:
    # NOW() - INTERVAL '7 days' -> datetime('now', '-7 days')
    
    # PostgreSQL: qs.created_at >= NOW() - INTERVAL '7 days'
    # SQLite: qs.created_at >= datetime('now', '-7 days')
    
    # Handling specific generic interval
    # We will try to catch specific patterns used in this project
    new_query = re.sub(r"NOW\(\)\s*-\s*INTERVAL\s*'(\d+\s+\w+)'", r"datetime('now', '-\1')", new_query, flags=re.IGNORECASE)
    new_query = re.sub(r"NOW\(\)", "CURRENT_TIMESTAMP", new_query, flags=re.IGNORECASE)
    
    return new_query, args

async def execute(query: str, *args):
    global DB_TYPE, pg_pool
    try:
        if DB_TYPE == 'pg':
            async with pg_pool.acquire() as conn:
                return await conn.execute(query, *args)
        else:
            q, a = _convert_to_sqlite(query, args)
            async with aiosqlite.connect(sqlite_db) as db:
                await db.execute(q, a)
                await db.commit()
    except Exception as e:
        logger.error(f"DB Error (Execute): {e} | Query: {query}")
        raise e

async def fetch(query: str, *args):
    global DB_TYPE, pg_pool
    try:
        if DB_TYPE == 'pg':
            async with pg_pool.acquire() as conn:
                return await conn.fetch(query, *args)
        else:
            q, a = _convert_to_sqlite(query, args)
            async with aiosqlite.connect(sqlite_db) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(q, a) as cursor:
                    rows = await cursor.fetchall()
                    return rows
    except Exception as e:
        logger.error(f"DB Error (Fetch): {e} | Query: {query}")
        return []

async def fetchrow(query: str, *args):
    global DB_TYPE, pg_pool
    try:
        if DB_TYPE == 'pg':
            async with pg_pool.acquire() as conn:
                return await conn.fetchrow(query, *args)
        else:
            q, a = _convert_to_sqlite(query, args)
            async with aiosqlite.connect(sqlite_db) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(q, a) as cursor:
                    row = await cursor.fetchone()
                    return row
    except Exception as e:
        logger.error(f"DB Error (Fetchrow): {e} | Query: {query}")
        return None

async def fetchval(query: str, *args):
    global DB_TYPE, pg_pool
    try:
        if DB_TYPE == 'pg':
            async with pg_pool.acquire() as conn:
                return await conn.fetchval(query, *args)
        else:
            q, a = _convert_to_sqlite(query, args)
            async with aiosqlite.connect(sqlite_db) as db:
                # fetchval equivalent
                async with db.execute(q, a) as cursor:
                    row = await cursor.fetchone()
                    return row[0] if row else None
    except Exception as e:
        logger.error(f"DB Error (Fetchval): {e} | Query: {query}")
        return None

# for INSERT RETURNING id substitute in SQLite
async def insert_returning_id(query: str, *args, id_column: str = 'id') -> int:
    global DB_TYPE, pg_pool
    if DB_TYPE == 'pg':
        async with pg_pool.acquire() as conn:
            return await conn.fetchval(query, *args)
    else:
        # Remove RETURNING clause for SQLite and require explicit commit + lastrowid
        # Assuming standard "INSERT INTO ... VALUES ... RETURNING id"
        q, a = _convert_to_sqlite(query, args)
        q = re.sub(r'RETURNING\s+\w+', '', q, flags=re.IGNORECASE).strip()
        
        async with aiosqlite.connect(sqlite_db) as db:
            cursor = await db.execute(q, a)
            await db.commit()
            return cursor.lastrowid

# === DASTLABKI INITSIALIZATSIYA ===
async def init_db():
    """Ma'lumotlar bazasini yaratish va jadvallarni sozlash (PG -> SQLite Fallback)"""
    global pg_pool, DB_TYPE

    # 1. Try PostgreSQL
    if DATABASE_URL:
        try:
            pg_pool = await asyncpg.create_pool(DATABASE_URL)
            logger.info("✅ PostgreSQL connected successfully.")
            DB_TYPE = 'pg'
        except Exception as e:
            logger.warning(f"⚠️ PostgreSQL connection failed: {e}. Switching to SQLite.")
            DB_TYPE = 'sqlite'
    else:
        logger.warning("⚠️ DATABASE_URL not set. Using SQLite.")
        DB_TYPE = 'sqlite'

    logger.info(f"💾 Using Database: {DB_TYPE}")

    # Create Tables
    # Note: Using abstraction functions allows single definition, 
    # but CREATE TABLE syntax differs enough that we rely on _convert_to_sqlite's basic replacement

    queries = [
        # USERS
        '''CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            total_score INTEGER DEFAULT 0,
            coins INTEGER DEFAULT 0
        )''',
        # QUIZ_SESSIONS
        '''CREATE TABLE IF NOT EXISTS quiz_sessions (
            session_id SERIAL PRIMARY KEY,
            chat_id BIGINT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT NOW()
        )''',
        # USER_ANSWERS
        # Foreign keys syntax is generally compatible standard SQL
        '''CREATE TABLE IF NOT EXISTS user_answers (
            id SERIAL PRIMARY KEY,
            session_id INTEGER REFERENCES quiz_sessions(session_id),
            user_id BIGINT REFERENCES users(user_id),
            question_number INTEGER,
            is_correct INTEGER,
            score INTEGER DEFAULT 0,
            UNIQUE(session_id, user_id, question_number)
        )''',
        # QUESTIONS
        '''CREATE TABLE IF NOT EXISTS questions (
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
        )''',
        # WITHDRAWALS
        '''CREATE TABLE IF NOT EXISTS withdrawals (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id),
            amount_coins INTEGER,
            amount_money REAL,
            status TEXT DEFAULT 'pending', 
            created_at TIMESTAMP DEFAULT NOW()
        )''',
        # SETTINGS
        '''CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )''',
        # SUBJECTS
        '''CREATE TABLE IF NOT EXISTS subjects (
            name TEXT PRIMARY KEY
        )'''
    ]

    for q in queries:
        await execute(q)

    # Values
    await execute("INSERT INTO settings (key, value) VALUES ($1, $2) ON CONFLICT(key) DO NOTHING", 'exchange_rate', '100')
    
    logger.info("✅ Database tables checked/created.")


# === SUBJECTS FUNKSIYALARI ===
async def get_custom_subjects_list():
    rows = await fetch("SELECT name FROM subjects")
    return [r['name'] for r in rows]

async def add_custom_subject(name: str):
    # ON CONFLICT DO NOTHING is Postgres syntax
    # SQLite supports it since 3.24. For older versions "INSERT OR IGNORE"
    if DB_TYPE == 'sqlite':
        await execute("INSERT OR IGNORE INTO subjects (name) VALUES (?)", name)
    else:
        await execute("INSERT INTO subjects (name) VALUES ($1) ON CONFLICT DO NOTHING", name)

async def remove_custom_subject(name: str):
    await execute("DELETE FROM subjects WHERE name = $1", name)

# === USER FUNKSIYALARI ===
async def get_or_create_user(user_id: int, username: str=None, first_name: str=None, last_name: str=None):
    if DB_TYPE == 'sqlite':
        # SQLite Upsert
        await execute('''
            INSERT INTO users (user_id, username, first_name, last_name)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE 
            SET username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name
        ''', user_id, username, first_name, last_name)
    else:
         await execute('''
            INSERT INTO users (user_id, username, first_name, last_name)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id) DO UPDATE 
            SET username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name
        ''', user_id, username, first_name, last_name)
        
    return await fetchrow('SELECT * FROM users WHERE user_id = $1', user_id)

# === QUIZ SESSION FUNKSIYALARI ===
async def create_quiz_session(chat_id: int):
    # RETURNING session_id handler
    # Note: we use INSERT RETURNING syntax
    if DB_TYPE == 'sqlite':
        # Custom logic for fallback
        sid = await insert_returning_id("INSERT INTO quiz_sessions (chat_id) VALUES ($1) RETURNING session_id", chat_id)
    else:
        sid = await fetchval("INSERT INTO quiz_sessions (chat_id) VALUES ($1) RETURNING session_id", chat_id)
        
    logger.info(f"🟢 Yangi sessiya yaratildi: ID={sid}")
    return sid

async def close_session(session_id: int):
    await execute('UPDATE quiz_sessions SET is_active = 0 WHERE session_id = $1', session_id)
    logger.info(f"🔴 Sessiya yopildi: ID={session_id}")

# === ANSWER / SCORE FUNKSIYALARI ===
async def save_user_answer(session_id: int, user_id: int, question_number: int, is_correct: bool):
    await get_or_create_user(user_id)
    score = 1 if is_correct else 0
    
    existing = await fetchrow('''
        SELECT is_correct, score FROM user_answers
        WHERE session_id = $1 AND user_id = $2 AND question_number = $3
    ''', session_id, user_id, question_number)
    
    score_diff = 0
    if existing:
        # SQLite returns Row object, can be indexed by name or integer
        # AsyncPG returns Record, also flex.
        # Ensure we handle checking correctly
        old_is_correct = existing['is_correct']
        old_score = existing['score']
        
        await execute('''
            UPDATE user_answers
            SET is_correct = $1, score = $2
            WHERE session_id = $3 AND user_id = $4 AND question_number = $5
        ''', 1 if is_correct else 0, score, session_id, user_id, question_number)
        score_diff = score - old_score
    else:
        await execute('''
            INSERT INTO user_answers (session_id, user_id, question_number, is_correct, score)
            VALUES ($1, $2, $3, $4, $5)
        ''', session_id, user_id, question_number, 1 if is_correct else 0, score)
        score_diff = score

    if score_diff != 0:
        await execute('''
            UPDATE users
            SET total_score = total_score + $1, coins = coins + $2
            WHERE user_id = $3
        ''', score_diff, score_diff, user_id)

# === REYTING / STATISTIKA FUNKSIYALARI ===
async def get_session_results(session_id: int):
    return await fetch('''
        SELECT u.user_id, u.username, u.first_name, SUM(ua.score) AS total_score
        FROM user_answers ua
        JOIN users u ON ua.user_id = u.user_id
        WHERE ua.session_id = $1
        GROUP BY u.user_id, u.username, u.first_name
        ORDER BY total_score DESC
    ''', session_id)

async def get_global_rating(limit: int = 10):
    return await fetch('''
        SELECT user_id, username, first_name, total_score
        FROM users
        ORDER BY total_score DESC
        LIMIT $1
    ''', limit)

async def get_user_rank(user_id: int):
    row = await fetchrow('SELECT total_score FROM users WHERE user_id = $1', user_id)
    if row:
        user_score = row['total_score']
        count = await fetchval('SELECT COUNT(*) FROM users WHERE total_score > $1', user_score)
        return count + 1
    return None

# === SAVOL QO‘SHISH ===
async def add_question(subject: str, question: str, options: list, correct_option_id: int, created_by: Optional[int] = None, image_url: Optional[str] = None):
    if len(options) != 4:
        raise ValueError("❌ 4 ta variant bo'lishi kerak!")

    await execute('''
        INSERT INTO questions (
            subject, question, option1, option2, option3, option4,
            correct_option_id, created_by, image_url
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
    ''', subject, question, options[0], options[1], options[2], options[3], correct_option_id, created_by, image_url)
    
    logger.info(f"➕ Yangi savol qo‘shildi: {subject} | {question}")

async def search_questions(text: str = "", subject: Optional[str] = None, question_id: Optional[int] = None):
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
        # ILIKE substitution handled in _convert_to_sqlite
        query += f" AND question ILIKE ${i}" 
        args.append(f"%{text}%")
        i += 1
        
    return await fetch(query, *args)

async def get_admin_dashboard_stats():
    total_questions = await fetchval("SELECT COUNT(*) FROM questions")
    total_users = await fetchval("SELECT COUNT(*) FROM users")
    
    # Date logic abstracted via _convert_to_sqlite regex for NOW() - INTERVAL
    active_users = await fetchval('''
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
    await execute("DELETE FROM questions WHERE id = $1", question_id)

async def get_questions(subject: Optional[str] = None, limit: int = 20):
    if subject:
        rows = await fetch('''
            SELECT id, subject, question, option1, option2, option3, option4, correct_option_id, image_url
            FROM questions WHERE subject = $1 ORDER BY RANDOM() LIMIT $2
        ''', subject, limit)
    else:
        rows = await fetch('''
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
    if subject:
        return await fetchval('SELECT COUNT(*) FROM questions WHERE subject = $1', subject)
    else:
        return await fetchval('SELECT COUNT(*) FROM questions')

async def get_group_rating(chat_id: int, limit: int = 10):
    return await fetch('''
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
    return await fetch("SELECT user_id, username, coins FROM users ORDER BY coins DESC LIMIT $1", limit)

async def reset_all_coins():
    await execute("UPDATE users SET coins = 0")

async def get_user_stats(user_id: int):
    correct = await fetchval("SELECT COUNT(*) FROM user_answers WHERE user_id = $1 AND is_correct = 1", user_id)
    incorrect = await fetchval("SELECT COUNT(*) FROM user_answers WHERE user_id = $1 AND is_correct = 0", user_id)
    return {"total": correct + incorrect, "correct": correct, "incorrect": incorrect}

async def get_ranking_by_period(period: str = "all", limit: int = 10):
    if period == "all":
        return await fetch('''
            SELECT user_id, username, first_name, total_score 
            FROM users 
            ORDER BY total_score DESC 
            LIMIT $1
        ''', limit)
    else:
        interval = "7 days" if period == "week" else "1 month"
        
        # We use explicit string formatting for interval to let _convert_to_sqlite handle regex
        query = f'''
            SELECT u.user_id, u.username, u.first_name, SUM(ua.score) as period_score
            FROM user_answers ua
            JOIN users u ON ua.user_id = u.user_id
            JOIN quiz_sessions qs ON ua.session_id = qs.session_id
            WHERE qs.created_at >= NOW() - INTERVAL '{interval}'
            GROUP BY u.user_id, u.username, u.first_name
            ORDER BY period_score DESC
            LIMIT {limit}
        '''
        return await fetch(query)

async def get_exchange_rate():
    val = await fetchval("SELECT value FROM settings WHERE key = 'exchange_rate'")
    return float(val) if val else 100.0

async def set_exchange_rate(rate: float):
    # SQLite fallback for upsert handled?
    # Simple INSERT OR REPLACE works for simple KV
    if DB_TYPE == 'sqlite':
        await execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", 'exchange_rate', str(rate))
    else:
        await execute('''
            INSERT INTO settings (key, value) VALUES ('exchange_rate', $1)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        ''', str(rate))

async def create_withdrawal(user_id: int, coins: int, money: float):
    current_coins = await fetchval("SELECT coins FROM users WHERE user_id = $1", user_id)
    if not current_coins or current_coins < coins:
        return False, "Hisobda yetarli tanga yo'q."
    
    await execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", coins, user_id)
    
    await execute(
        "INSERT INTO withdrawals (user_id, amount_coins, amount_money) VALUES ($1, $2, $3)", 
        user_id, coins, money
    )
    return True, "So'rov muvaffaqiyatli yuborildi."

async def get_pending_withdrawals():
    return await fetch('''
        SELECT w.id, w.user_id, u.username, w.amount_coins, w.amount_money, w.created_at
        FROM withdrawals w
        JOIN users u ON w.user_id = u.user_id
        WHERE w.status = 'pending'
    ''')

async def update_withdrawal_status(withdrawal_id: int, status: str):
    if status == 'rejected':
        row = await fetchrow("SELECT user_id, amount_coins FROM withdrawals WHERE id = $1", withdrawal_id)
        if row:
            await execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", row['amount_coins'], row['user_id'])
    
    await execute("UPDATE withdrawals SET status = $1 WHERE id = $2", status, withdrawal_id)
import aiosqlite
import asyncio

async def check_questions():
    async with aiosqlite.connect("quiz_bot.db") as db:
        cursor = await db.execute("SELECT subject, COUNT(*) FROM questions GROUP BY subject;")
        rows = await cursor.fetchall()
        print(rows)

asyncio.run(check_questions())

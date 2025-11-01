from __future__ import annotations


import asyncio
import logging
import os
import json
from pathlib import Path
from datetime import datetime

import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import PollAnswer
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

# Import database functions (kerakli funksiyalar database.py da bo'lishi kerak)
from database import (
    init_db, get_or_create_user, create_quiz_session, save_user_answer,
    get_session_results, close_session, get_questions, add_question,
    get_questions_count, get_group_rating, get_global_rating,
    get_top_users, reset_all_coins
)

# ==== CONFIG & SETUP ====
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS_ENV = os.getenv("ADMIN_IDS", "")
CHANNEL_ID_ENV = os.getenv("CHANNEL_ID")

# convert ADMIN_ID to str for safe comparison
ADMIN_IDS = [aid.strip() for aid in ADMIN_IDS_ENV.split(",") if aid.strip()]
CHANNEL_ID = int(CHANNEL_ID_ENV) if CHANNEL_ID_ENV else None

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN topilmadi! .env faylida BOT_TOKEN ni sozlang.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# DB filename used locally in some handlers
DB_NAME = "quiz_bot.db"

# ==== Files ====
CUSTOM_SUBJECTS_FILE = Path(__file__).parent / "custom_subjects.json"

def load_custom_subjects() -> dict:
    if not CUSTOM_SUBJECTS_FILE.exists():
        return {}
    try:
        with open(CUSTOM_SUBJECTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_custom_subjects(data: dict):
    with open(CUSTOM_SUBJECTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

custom_subjects = load_custom_subjects()  # could be {cmd: subject_key} or {subject_key: meta}

# helper: collect all subject keys (supporting both saving styles)
def get_all_subjects():
    subjects = set(["english", "russian", "math", "physics"])  # defaults
    # if mapping is cmd->subject_key
    for k, v in custom_subjects.items():
        if isinstance(v, str):
            subjects.add(v)
        elif isinstance(v, dict):
            # if saved as subject_key: {meta...}
            subjects.add(k)
    # also add keys if they are plain subject names
    for k in custom_subjects.keys():
        if k and isinstance(k, str) and k.isalpha():
            subjects.add(k)
    return sorted(subjects)

# ==== FSM states ====
class AddQuestionStates(StatesGroup):
    waiting_for_subject = State()
    waiting_for_question = State()
    waiting_for_options = State()
    waiting_for_correct = State()

class AddProjectStates(StatesGroup):
    waiting_for_subject_key = State()
    waiting_for_command = State()

class AddQuestionsStates(StatesGroup):
    waiting_for_subject = State()
    waiting_for_questions = State()

class DeleteQuestionStates(StatesGroup):
    waiting_for_question_text = State()
    confirm_delete = State()

class DeleteProjectStates(StatesGroup):
    waiting_for_project_name = State()
    confirm_delete = State()

# ==== START ====
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    text = (
        "👋 <b>Assalomu alaykum!</b>\n\n"
        "Men test botman. Quyidagi komandalar mavjud:\n\n"
        "📚 <b>Fanlar:</b>\n"
        "/quizeng - Ingliz tili\n"
        "/quizru - Rus tili\n"
        "/quizmath - Matematika\n"
        "/quizfiz - Fizika\n"
        "/quiz - Barcha fanlardan random\n\n"
        "🏆 <b>Reyting:</b>\n"
        "/globalrating - Umumiy reyting\n"
        "/grouprating - Guruh reytingi\n\n"
        "Har bir to‘g‘ri javob uchun 1 🪙tanga olasiz!"
    )
    if ADMIN_IDS and message.from_user and str(message.from_user.id) in ADMIN_IDS:
        text += "\n\n🔧 <b>Admin komandalar:</b>\n/addquestion - Savol qo‘shish\n/addquestions - Bir nechta savol qo‘shish\n/addproject - Yangi fan qo‘shish\n/deletequestion - Savol o‘chirish\n/deleteproject - Fan o‘chirish"
    await message.answer(text, parse_mode="HTML")

# ==== QUIZ handlers (unchanged behaviour) ====
@dp.message(Command("quiz"))
async def cmd_quiz(message: types.Message):
    await start_quiz(message, None)

@dp.message(Command("quizeng"))
async def cmd_quiz_eng(message: types.Message):
    await start_quiz(message, "english")

@dp.message(Command("quizru"))
async def cmd_quiz_ru(message: types.Message):
    await start_quiz(message, "russian")

@dp.message(Command("quizmath"))
async def cmd_quiz_math(message: types.Message):
    await start_quiz(message, "math")

@dp.message(Command("quizfiz"))
async def cmd_quiz_fiz(message: types.Message):
    await start_quiz(message, "physics")

active_quizzes: dict = {}

async def start_quiz(message: types.Message, subject: str | None):
    chat_id = message.chat.id
    if chat_id in active_quizzes and active_quizzes[chat_id]["active"]:
        await message.answer("❌ Test allaqachon boshlangan!")
        return

    questions = await get_questions(subject=subject, limit=20)
    if not questions:
        await message.answer("❌ Bu fan uchun savollar topilmadi.")
        return

    session_id = await create_quiz_session(chat_id)
    active_quizzes[chat_id] = {
        "active": True,
        "session_id": session_id,
        "current_question": 0,
        "questions": questions,
        "poll_ids": {}
    }

    await message.answer(
        f"🎯 Test boshlandi!\nFan: {subject or 'Barcha fanlar'}\nSavollar soni: {len(questions)}\n⏱ Har biriga 15 soniya",
        parse_mode="HTML"
    )
    await send_next_question(chat_id)

async def send_next_question(chat_id: int):
    quiz = active_quizzes.get(chat_id)
    if not quiz or not quiz["active"]:
        return

    i = quiz["current_question"]
    questions = quiz["questions"]

    if i >= len(questions):
        await finish_quiz(chat_id)
        return

    q = questions[i]
    try:
        poll = await bot.send_poll(
            chat_id=chat_id,
            question=f"❓ {i + 1}/{len(questions)}: {q['question']}",
            options=q["options"],
            type="quiz",
            correct_option_id=q["correct_option_id"],
            is_anonymous=False,
            open_period=15
        )
    except Exception as e:
        logger.exception("Poll yuborishda xato (savol #%s): %s", i, e)
        # skip this question
        quiz["current_question"] += 1
        await asyncio.sleep(1)
        await send_next_question(chat_id)
        return

    if poll.poll:
        quiz["poll_ids"][poll.poll.id] = {"question_num": i, "correct": q["correct_option_id"]}

    # wait and go next
    await asyncio.sleep(17)
    if not quiz.get("active", False):
        return
    quiz["current_question"] += 1
    await send_next_question(chat_id)

@dp.poll_answer()
async def handle_poll_answer(poll_answer: PollAnswer):
    user = poll_answer.user
    if not user:
        return

    poll_id = poll_answer.poll_id
    option = poll_answer.option_ids[0] if poll_answer.option_ids else None

    await get_or_create_user(user.id, user.username, user.first_name, user.last_name)

    for chat_id, quiz in active_quizzes.items():
        if poll_id in quiz["poll_ids"]:
            q_info = quiz["poll_ids"][poll_id]
            is_correct = option == q_info["correct"]
            await save_user_answer(quiz["session_id"], user.id, q_info["question_num"], is_correct)
            break

async def finish_quiz(chat_id: int):
    quiz = active_quizzes.get(chat_id)
    if not quiz:
        return

    session_id = quiz["session_id"]
    results = await get_session_results(session_id)
    active_quizzes[chat_id]["active"] = False

    if not results:
        try:
            await bot.send_message(chat_id, "❌ Test tugadi, hech kim javob bermadi.")
        except Exception:
            pass
        await close_session(session_id)
        active_quizzes.pop(chat_id, None)
        return

    text = "🏆 <b>Natijalar:</b>\n\n"
    for i, (uid, username, fname, score) in enumerate(results, 1):
        name = f"@{username}" if username else (fname or str(uid))
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "▫️"
        text += f"{medal} {i}. {name} — {score} 🪙tanga\n"

    try:
        await bot.send_message(chat_id, text, parse_mode="HTML")
    except Exception as e:
        logger.exception("Natijani yuborishda xato: %s", e)

    await close_session(session_id)
    active_quizzes.pop(chat_id, None)

@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message):
    chat_id = message.chat.id
    quiz = active_quizzes.get(chat_id)
    if not quiz or not quiz.get("active", False):
        await message.answer("❌ Hech qanday test faol emas.", parse_mode="HTML")
        return

    active_quizzes[chat_id]["active"] = False
    await message.answer("❗ Test bekor qilinyapti... Natijalar hisoblanadi.", parse_mode="HTML")
    await finish_quiz(chat_id)

# ==== REYTING ====
@dp.message(Command("globalrating"))
async def cmd_global_rating(message: types.Message):
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            # top 10
            cursor = await db.execute('''
                SELECT user_id, username, first_name, total_score
                FROM users
                ORDER BY total_score DESC
                LIMIT 10
            ''')
            top_users = await cursor.fetchall()

            # find user's rank (if exists)
            cursor = await db.execute('SELECT total_score FROM users WHERE user_id = ?', (message.from_user.id,))
            row = await cursor.fetchone()
            if row:
                user_score = row[0]
                cursor = await db.execute('SELECT COUNT(*) FROM users WHERE total_score > ?', (user_score,))
                r = await cursor.fetchone()
                user_rank = r[0] + 1 if r else 1
            else:
                user_rank = None

        if not top_users:
            await message.answer("❌ Hozircha reyting mavjud emas.", parse_mode="HTML")
            return

        text = "🌍 <b>Umumiy reyting (TOP 10):</b>\n\n"
        for i, (uid, username, fname, score) in enumerate(top_users, 1):
            name = f"@{username}" if username else (fname or str(uid))
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "▫️"
            text += f"{medal} {i}. {name} — {score} 🪙 tanga\n"

        if user_rank:
            text += f"\n📍 <b>Sizning o‘rningiz: #{user_rank}</b>"
        else:
            text += "\n📍 Siz hali reytingda yo‘qsiz."

        await message.answer(text, parse_mode="HTML")
    except Exception as e:
        logger.exception("globalrating xato")
        await message.answer(f"⚠️ Xato: {e}")

@dp.message(Command("grouprating"))
async def cmd_group_rating(message: types.Message):
    data = await get_group_rating(message.chat.id)
    if not data:
        await message.answer("❌ Bu guruhda hali hech kim testda qatnashmagan.", parse_mode="HTML")
        return

    text = "👥 <b>Guruh reytingi:</b>\n\n"
    for i, (uid, username, fname, score) in enumerate(data, 1):
        name = f"@{username}" if username else (fname or str(uid))
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "▫️"
        text += f"{medal} {i}. {name} — {score} 🪙tanga\n"
    await message.answer(text, parse_mode="HTML")

# ==== WEEKLY RATING ====
async def send_weekly_rating():
    if CHANNEL_ID is None:
        logger.warning("CHANNEL_ID not set; weekly rating skipped.")
        return

    top_users = await get_top_users(limit=10)
    if not top_users:
        await bot.send_message(CHANNEL_ID, "❌ Bu hafta reyting uchun ma'lumot topilmadi.")
        return

    message = "🏆 *Haftalik TOP-10 reyting!*\n\n"
    for i, row in enumerate(top_users, start=1):
        # row may be a Row or tuple
        try:
            uid = row["user_id"] if isinstance(row, aiosqlite.Row) else row[0]
            username = row["username"] if isinstance(row, aiosqlite.Row) else row[1]
            coins = row["coins"] if isinstance(row, aiosqlite.Row) else row[2]
        except Exception:
            uid, username, coins = (row[0], row[1], row[2])
        name = f"@{username}" if username else f"ID:{uid}"
        message += f"{i}. {name} — {coins} 🪙\n"

    message += "\nYangi hafta boshlandi, hammaga omad! 🍀"
    await bot.send_message(CHANNEL_ID, message, parse_mode="Markdown")
    await reset_all_coins()
    logger.info(f"[{datetime.now()}] ✅ Haftalik reyting yuborildi va tanga qayta tiklandi.")

@dp.message(Command("haftarating"))
async def haftalik_reyting_komanda(message: types.Message):
    top_users = await get_top_users(limit=10)
    if not top_users:
        await message.answer("❌ Hozircha reyting ma'lumotlari yo‘q.")
        return

    message_text = "🏆 *Haftalik TOP-10 Reyting:*\n\n"
    for i, row in enumerate(top_users, start=1):
        try:
            uid = row["user_id"] if isinstance(row, aiosqlite.Row) else row[0]
            username = row["username"] if isinstance(row, aiosqlite.Row) else row[1]
            coins = row["coins"] if isinstance(row, aiosqlite.Row) else row[2]
        except Exception:
            uid, username, coins = (row[0], row[1], row[2])
        name = f"@{username}" if username else f"ID:{uid}"
        message_text += f"{i}. {name} — {coins} 🪙\n"

    await message.answer(message_text, parse_mode="Markdown")

# ==== ADMIN: addproject, addquestion (single), addquestions (bulk) ====
@dp.message(Command("addproject"))
async def cmd_add_project(message: types.Message, state: FSMContext):
    if not ADMIN_IDS or not message.from_user or str(message.from_user.id) not in ADMIN_IDS:
        await message.answer("❌ Bu komanda faqat admin uchun!")
        return

    await state.set_state(AddProjectStates.waiting_for_subject_key)
    await message.answer("📚 Yangi fan kalitini kiriting (masalan: biology).")

@dp.message(AddProjectStates.waiting_for_subject_key)
async def process_project_subject_key(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Iltimos, fan kalitini kiriting.")
        return
    key = message.text.strip().lower()
    # store as cmd->subject mapping by default
    # We try to avoid collisions: if key already exists, warn
    if key in custom_subjects:
        await message.answer("❌ Bu fan yoki buyruq allaqachon mavjud.")
        await state.clear()
        return
    # store simple
    custom_subjects[key] = key
    save_custom_subjects(custom_subjects)
    await message.answer(f"✅ Fan qo‘shildi: {key}")
    await state.clear()

# --- /addquestion (single) ---
@dp.message(Command("addquestion"))
async def cmd_add_question(message: types.Message, state: FSMContext):
    if not ADMIN_IDS or not message.from_user or str(message.from_user.id) not in ADMIN_IDS:
        await message.answer("❌ Bu komanda faqat admin uchun!")
        return

    subjects = get_all_subjects()
    txt = "📘 Qaysi fan uchun savol qo‘shmoqchisiz?\n\n" + "\n".join(f"- {s}" for s in subjects)
    await message.answer(txt)
    await state.set_state(AddQuestionStates.waiting_for_subject)

@dp.message(AddQuestionStates.waiting_for_subject)
async def process_subject_for_single(message: types.Message, state: FSMContext):
    subject = message.text.strip().lower()
    if subject not in get_all_subjects():
        await message.answer("❌ Bunday fan topilmadi. Mavjud fanlardan birini kiriting.")
        return
    await state.update_data(subject=subject)
    await message.answer("✍️ Savol matnini yuboring (yoki rasm yuborishingiz mumkin).")
    await state.set_state(AddQuestionStates.waiting_for_question)

@dp.message(AddQuestionStates.waiting_for_question, F.photo)
async def process_question_photo(message: types.Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await state.update_data(image_url=file_id)
    await message.answer("📝 Endi savol matnini ham yuboring (ixtiyoriy, yoki 'skip' deb yozing).")

@dp.message(AddQuestionStates.waiting_for_question, F.text)
async def process_question_text(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if text.lower() == "skip":
        # leave question empty if user wants only image
        await state.update_data(question="❓Rasmdagi savol")
    else:
        await state.update_data(question=text)
    await message.answer("🔢 4 ta variantni har bir qatorda yuboring (4 qator):")
    await state.set_state(AddQuestionStates.waiting_for_options)

@dp.message(AddQuestionStates.waiting_for_options)
async def process_options_single(message: types.Message, state: FSMContext):
    # options can be sent as newline separated (4 lines)
    options = [opt.strip() for opt in message.text.replace('\r', '').split('\n') if opt.strip()]
    if len(options) != 4:
        await message.answer("❌ 4 ta variant bo‘lishi kerak! Har bir variantni yangi qatorda yuboring.")
        return
    await state.update_data(options=options)
    await message.answer("✅ To‘g‘ri variant raqamini kiriting (1-4):")
    await state.set_state(AddQuestionStates.waiting_for_correct)

@dp.message(AddQuestionStates.waiting_for_correct)
async def process_correct_option(message: types.Message, state: FSMContext):
    try:
        correct_option = int(message.text.strip())
        if correct_option < 1 or correct_option > 4:
            raise ValueError()
    except Exception:
        await message.answer("❌ Faqat 1-4 oraligʻida raqam kiriting.")
        return
    data = await state.get_data()
    subject = data.get("subject")
    question = data.get("question", "❓Rasmdagi savol")
    options = data.get("options")
    image_url = data.get("image_url", None)
    correct_option = correct_option - 1
    await add_question(subject, question, options, correct_option, message.from_user.id, image_url=image_url)
    await message.answer(f"✅ Savol '{subject}' faniga qo‘shildi!")
    await state.clear()

# --- /addquestions (bulk) ---
@dp.message(Command("addquestions"))
async def cmd_addquestions(message: types.Message, state: FSMContext):
    if not ADMIN_IDS or not message.from_user or str(message.from_user.id) not in ADMIN_IDS:
        await message.answer("❌ Bu komanda faqat admin uchun!")
        return
    await message.answer("📚 Qaysi fan uchun savollar qo‘shmoqchisiz? (fan nomini yozing):")
    await state.set_state(AddQuestionsStates.waiting_for_subject)

@dp.message(AddQuestionsStates.waiting_for_subject)
async def process_subject_bulk(message: types.Message, state: FSMContext):
    subject = message.text.strip().lower()
    if subject not in get_all_subjects():
        await message.answer("❌ Bunday fan topilmadi. Mavjud fanlardan birini kiriting:\n" + ", ".join(get_all_subjects()))
        return
    await state.update_data(subject=subject)
    await message.answer(
        "📋 Endi savollarni quyidagi formatda yuboring:\n\n"
        "Savol matni | variant1, variant2, variant3, variant4 | to‘g‘ri_javob_raqami\n\n"
        "Har bir savolni yangi qatorda yozing."
    )
    await state.set_state(AddQuestionsStates.waiting_for_questions)

@dp.message(AddQuestionsStates.waiting_for_questions)
async def process_questions_bulk(message: types.Message, state: FSMContext):
    data = await state.get_data()
    subject = data["subject"]
    created_by = message.from_user.id

    lines = [ln.strip() for ln in message.text.replace('\r','').split('\n') if ln.strip()]
    success = 0
    errors = 0

    for line in lines:
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 3:
            errors += 1
            continue
        q_text = parts[0]
        options = [o.strip() for o in parts[1].split(",")]
        try:
            correct = int(parts[2]) - 1
        except Exception:
            errors += 1
            continue
        if len(options) != 4 or not (1 <= correct <= 4):
            errors += 1
            continue
        try:
            await add_question(subject, q_text, options, correct, created_by)
            success += 1
        except Exception as e:
            logger.exception("add_question xato")
            errors += 1

    await message.answer(f"✅ {success} ta savol qo‘shildi.\n⚠️ {errors} ta savolda xato bor.")
    await state.clear()

# ==== DELETE handlers ====
@dp.message(Command("deletequestion"))
async def cmd_delete_question(message: types.Message, state: FSMContext):
    if not ADMIN_IDS or not message.from_user or str(message.from_user.id) not in ADMIN_IDS:
        await message.answer("❌ Bu komanda faqat admin uchun!")
        return
    await message.answer("🧾 O‘chirmoqchi bo‘lgan savol matnini yuboring (qism matn):")
    await state.set_state(DeleteQuestionStates.waiting_for_question_text)

@dp.message(DeleteQuestionStates.waiting_for_question_text)
async def process_question_to_delete(message: types.Message, state: FSMContext):
    qtxt = message.text.strip()
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT id, subject, question FROM questions WHERE question LIKE ?", (f"%{qtxt}%",))
        rows = await cursor.fetchall()
    if not rows:
        await message.answer("❌ Bunday savol topilmadi.")
        await state.clear()
        return
    if len(rows) > 1:
        text = "⚠️ Bir nechta o‘xshash savollar topildi:\n\n"
        for r in rows:
            text += f"ID:{r[0]} | Fan:{r[1]} | {r[2][:50]}...\n"
        text += "\nAniq ID raqamini yuboring yoki bekor qilish uchun 'cancel' deb yozing."
        await state.update_data(found_questions=rows)
        await state.set_state(DeleteQuestionStates.confirm_delete)
        await message.answer(text)
        return
    qid, subj, qshort = rows[0]
    await state.update_data(question_id=qid)
    await message.answer(f"🗑 Savol:\n<b>{qshort}</b>\n\nAniq o‘chirmoqchimisiz? (ha/yo‘q)", parse_mode="HTML")
    await state.set_state(DeleteQuestionStates.confirm_delete)

@dp.message(DeleteQuestionStates.confirm_delete)
async def confirm_delete_question(message: types.Message, state: FSMContext):
    txt = message.text.strip().lower()
    data = await state.get_data()
    if txt in ("ha", "xa", "yes"):
        qid = data.get("question_id")
        if not qid and txt.isdigit():
            qid = int(txt)
        if not qid:
            await message.answer("⚠️ ID topilmadi. Jarayon bekor qilindi.")
            await state.clear()
            return
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("DELETE FROM questions WHERE id = ?", (qid,))
            await db.commit()
        await message.answer("✅ Savol muvaffaqiyatli o‘chirildi!")
    else:
        await message.answer("❎ Jarayon bekor qilindi.")
    await state.clear()

@dp.message(Command("deleteproject"))
async def cmd_delete_project(message: types.Message, state: FSMContext):
    if not ADMIN_IDS or not message.from_user or str(message.from_user.id) not in ADMIN_IDS:
        await message.answer("❌ Bu komanda faqat admin uchun!")
        return
    subjects = list(custom_subjects.keys()) or []
    if not subjects:
        await message.answer("❌ Hozircha hech qanday custom fan yo‘q.")
        return
    txt = "🧾 Qaysi fanni o‘chirmoqchisiz?\n" + "\n".join(f"- {s}" for s in subjects)
    await message.answer(txt)
    await state.set_state(DeleteProjectStates.waiting_for_project_name)

@dp.message(DeleteProjectStates.waiting_for_project_name)
async def process_project_to_delete(message: types.Message, state: FSMContext):
    project_name = message.text.strip().lower()
    if project_name not in custom_subjects:
        await message.answer("❌ Bunday fan topilmadi.")
        await state.clear()
        return
    await state.update_data(project_name=project_name)
    await message.answer(f"🗑 Fan '{project_name}'ni aniq o‘chirmoqchimisiz? (ha/yo‘q)")
    await state.set_state(DeleteProjectStates.confirm_delete)

@dp.message(DeleteProjectStates.confirm_delete)
async def confirm_delete_project(message: types.Message, state: FSMContext):
    txt = message.text.strip().lower()
    data = await state.get_data()
    if txt in ("ha", "xa", "yes"):
        project_name = data.get("project_name")
        custom_subjects.pop(project_name, None)
        save_custom_subjects(custom_subjects)
        await message.answer(f"✅ Fan '{project_name}' o‘chirildi!")
    else:
        await message.answer("❎ Jarayon bekor qilindi.")
    await state.clear()

# ==== START BOT & SCHEDULER ====
async def main():
    # init db and seed questions if necessary
    await init_db()
    # init_questions may exist in your project to seed default questions
    try:
        from init_questions import init_questions
        await init_questions()
    except Exception:
        # ignore if not present
        pass

    logger.info("Bot ishga tushdi ✅")
    await dp.start_polling(bot)
# ==== DINAMIK FANLAR UCHUN QUIZ HANDLER ====
@dp.message(F.text.startswith("/quiz"))
async def handle_dynamic_quiz(message: types.Message):
    cmd = message.text.strip().lower()
    subject = cmd.replace("/quiz", "").strip()

    # Agar foydalanuvchi shunchaki /quiz yozsa
    if not subject:
        await start_quiz(message, None)
        return

    # Custom subjectlar ichidan qidirish
    custom_subjects = load_custom_subjects()
    if subject not in custom_subjects:
        await message.answer(f"❌ '{subject}' nomli fan topilmadi.")
        return

    # Shu fan bo‘yicha testni boshlash
    await start_quiz(message, subject)

if __name__ == "__main__":
    # run scheduler and bot inside running loop
    async def start_bot():
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")
        # weekly job
        scheduler.add_job(send_weekly_rating, "cron", day_of_week="sun", hour=23, minute=0)
        scheduler.start()
        logger.info(f"[{datetime.now()}] Scheduler ishga tushdi.")
        await main()

    asyncio.run(start_bot())

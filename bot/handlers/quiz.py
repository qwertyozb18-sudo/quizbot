import asyncio
import logging
from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.types import PollAnswer
from bot.loader import bot
from bot.session import active_quizzes
from database import get_custom_subjects_list
from database import (
    get_questions, create_quiz_session, save_user_answer,
    get_session_results, close_session, get_or_create_user
)

router = Router()
logger = logging.getLogger(__name__)

# ==== QUIZ START ====
@router.message(Command("quiz"))
async def cmd_quiz(message: types.Message):
    tokens = (message.text or "").strip().split()
    limit = 20
    seconds = 15
    if len(tokens) >= 3 and tokens[0].startswith("/quiz"):
        if tokens[1].isdigit() and tokens[2].isdigit():
            limit = max(1, min(50, int(tokens[1])))
            seconds = max(5, min(600, int(tokens[2])))
    await start_quiz(message, None, limit=limit, seconds=seconds)

@router.message(Command("quizeng"))
async def cmd_quiz_eng(message: types.Message):
    await start_quiz(message, "english")

@router.message(Command("quizru"))
async def cmd_quiz_ru(message: types.Message):
    await start_quiz(message, "russian")

@router.message(Command("quizmath"))
async def cmd_quiz_math(message: types.Message):
    await start_quiz(message, "math")

@router.message(Command("quizfiz"))
async def cmd_quiz_fiz(message: types.Message):
    await start_quiz(message, "physics")

@router.message(F.text.regexp(r'^/quiz\w*(?:@\w+)?(?:\s+\d+(?:\s+\d+)?)?$'))
async def handle_dynamic_quiz(message: types.Message):
    parts = message.text.strip().lower().split()
    cmd = parts[0].split('@')[0]
    
    subject = None
    limit = 20
    seconds = 15
    
    if cmd != "/quiz":
        subject = cmd.replace("/quiz", "")
        custom_subjects = await get_custom_subjects_list()
        if subject not in ["eng", "ru", "math", "fiz"] and subject not in custom_subjects:
            subjects = ["eng", "ru", "math", "fiz"] + custom_subjects
            await message.answer(f"❌ Fan topilmadi: {subject}\nMavjud fanlar: {', '.join(subjects)}")
            return
        
        subject_map = {
            "eng": "english",
            "ru": "russian",
            "math": "math",
            "fiz": "physics"
        }
        subject = subject_map.get(subject, subject)
    
    if len(parts) >= 2 and parts[1].isdigit():
        limit = max(1, min(50, int(parts[1])))
    
    if len(parts) >= 3 and parts[2].isdigit():
        seconds = max(5, min(300, int(parts[2])))
    
    await message.answer(
        f"🎯 Test parametrlari:\nFan: {subject or 'Barcha fanlar'}\nSavollar soni: {limit}\nHar bir savol uchun vaqt: {seconds} soniya"
    )
    await start_quiz(message, subject, limit=limit, seconds=seconds)

async def start_quiz(message: types.Message, subject: str | None, *, limit: int = 20, seconds: int = 15):
    chat_id = message.chat.id
    if chat_id in active_quizzes and active_quizzes[chat_id]["active"]:
        await message.answer("❌ Test allaqachon boshlangan!")
        return

    questions = await get_questions(subject=subject, limit=limit)
    if not questions:
        await message.answer("❌ Bu fan uchun savollar topilmadi.")
        return

    session_id = await create_quiz_session(chat_id)
    active_quizzes[chat_id] = {
        "active": True,
        "session_id": session_id,
        "current_question": 0,
        "questions": questions,
        "poll_ids": {},
        "seconds": seconds
    }

    await message.answer(
        f"🎯 Test boshlandi!\nFan: {subject or 'Barcha fanlar'}\nSavollar soni: {len(questions)}\n⏱ Har biriga {seconds} soniya",
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
        image = q.get("image_url") or q.get("image")
        if image:
            try:
                await bot.send_photo(chat_id=chat_id, photo=image)
                await asyncio.sleep(0.6)
            except Exception as e:
                logger.warning("Rasm yuborishda xato: %s", e)

        raw_question = q.get("question") or ""
        if raw_question.strip() == "" or raw_question.strip().lower() in ("❓rasmdagi savol", "rasmdagi savol"):
            question_text = "Rasmda nima aks etilgan?"
        else:
            question_text = raw_question

        poll = await bot.send_poll(
            chat_id=chat_id,
            question=f"❓ {i + 1}/{len(questions)}: {question_text}",
            options=q["options"],
            type="quiz",
            correct_option_id=q["correct_option_id"],
            is_anonymous=False,
            open_period=quiz.get("seconds", 15)
        )
    except Exception as e:
        logger.exception("Poll yuborishda xato (savol #%s): %s", i, e)
        quiz["current_question"] += 1
        await asyncio.sleep(1)
        await send_next_question(chat_id)
        return

    if poll.poll:
        quiz["poll_ids"][poll.poll.id] = {"question_num": i, "correct": q["correct_option_id"]}

    await asyncio.sleep(quiz.get("seconds", 15) + 2)
    if not quiz.get("active", False):
        return
    quiz["current_question"] += 1
    await send_next_question(chat_id)

@router.poll_answer()
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

@router.message(Command("cancel"))
async def cmd_cancel(message: types.Message):
    chat_id = message.chat.id
    quiz = active_quizzes.get(chat_id)
    if not quiz or not quiz.get("active", False):
        await message.answer("❌ Hech qanday test faol emas.", parse_mode="HTML")
        return

    active_quizzes[chat_id]["active"] = False
    await message.answer("❗ Test bekor qilinyapti... Natijalar hisoblanadi.", parse_mode="HTML")
    await finish_quiz(chat_id)

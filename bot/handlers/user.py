import logging
import aiosqlite
from datetime import datetime
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import (
    get_group_rating, get_global_rating, get_top_users, reset_all_coins, get_user_rank,
    get_user_stats, get_ranking_by_period, get_exchange_rate, create_withdrawal, get_or_create_user
)
from bot.config import ADMIN_IDS, CHANNEL_ID
from bot.loader import bot

router = Router()
logger = logging.getLogger(__name__)

class ExchangeStates(StatesGroup):
    waiting_for_amount = State()

# ==== START ====
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    # Ensure user exists
    await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name, message.from_user.last_name or "")
    
    text = (
        "👋 <b>Assalomu alaykum!</b>\n\n"
        "Men test botman.\n\n"
        "🧠 <b>Test ishlash uchun:</b>\n"
        "/quiz - Tasodifiy test\n"
        "/quizeng, /quizru, /quizmath ... - Fanlar bo'yicha\n\n"
        "📊 <b>Statistika va Reyting</b> uchun pastdagi tugmani bosing:"
    )
    
    # Mini App Button
    # Note: Telegram requires https URL for WebApp. 
    # For local test: use ngrok or similar, OR just a placeholder if user plans to deploy.
    # Provided URL: https://example.com/quizbot-app (PLACEHOLDER)
    # If running locally, you must tunnel localhost:8080 or the button won't open anything valid.
    
    # However, user just said "web ga qosh". 
    # Let's assume they will configure the URL in BotFather.
    # We just provide the button request.
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Kabinet & Reyting (Mini App)", web_app=WebAppInfo(url="https://google.com"))],
        [InlineKeyboardButton(text="📚 Fanlar ro'yxati (Info)", callback_data="info_btn")]
    ])

    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

@router.callback_query(F.data == "info_btn")
async def show_info_callback(call: CallbackQuery):
    await cmd_info(call.message)
    await call.answer()

@router.message(Command("info"))
async def cmd_info(message: types.Message):
    from database import get_custom_subjects_list
    
    default_subjects = {
        "eng": "Ingliz tili 🇬🇧",
        "ru": "Rus tili 🇷🇺",
        "math": "Matematika 📐",
        "fiz": "Fizika ⚡"
    }
    
    custom = await get_custom_subjects_list()
    
    text = "📚 <b>Mavjud fanlar:</b>\n\n"
    for cmd, name in default_subjects.items():
        text += f"▫️ /quiz{cmd} - {name}\n"
    
    if custom:
        text += "\n<b>Qo'shimcha:</b>\n"
        for subject in custom:
            text += f"▫️ /quiz{subject}\n"
            
    await message.answer(text, parse_mode="HTML")

# Rating commands (text fallback optional, but requested to remove? 
# "botda faqat test ishlash qolsa yetadi". 
# So I will remove /globalrating etc handlers.)

# Schedule helper remains for weekly reset
async def send_weekly_rating():
    if CHANNEL_ID is None:
        logger.warning("CHANNEL_ID not set; weekly rating skipped.")
        return

    top_users = await get_ranking_by_period("week", limit=10)
    if not top_users:
        await bot.send_message(CHANNEL_ID, "❌ Bu hafta reyting uchun ma'lumot topilmadi.")
        return

    message = "🏆 *Haftalik TOP-10 reyting (To'g'ri javoblar bo'yicha)!*\n\n"
    for i, row in enumerate(top_users, start=1):
        # row structure from get_ranking_by_period: (user_id, username, first_name, period_score)
        try:
            uid = row["user_id"] if isinstance(row, aiosqlite.Row) else row[0]
            username = row["username"] if isinstance(row, aiosqlite.Row) else row[1]
            score = row["period_score"] if isinstance(row, aiosqlite.Row) else row[3]
        except Exception:
            uid, username, score = (row[0], row[1], row[3])
        
        name = f"@{username}" if username else f"ID:{uid}"
        message += f"{i}. {name} — {score} ball 🎯\n"

    message += "\nYangi hafta boshlandi, hammaga omad! 🍀"
    await bot.send_message(CHANNEL_ID, message, parse_mode="Markdown")
    # await reset_all_coins()
    # logger.info(f"[{datetime.now()}] ✅ Haftalik reyting yuborildi va tanga qayta tiklandi.")
    logger.info(f"[{datetime.now()}] ✅ Haftalik reyting yuborildi.")

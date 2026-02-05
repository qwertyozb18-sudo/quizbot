import logging
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup 
import aiosqlite

from bot.config import ADMIN_IDS, BOT_TOKEN, ADMIN_PASSWORD, WEBAPP_URL
from bot.states import (
    AddProjectStates, AddQuestionStates, AddQuestionsStates,
    DeleteQuestionStates, DeleteProjectStates, AdminAuthStates
)
from bot.utils import get_all_subjects
from database import (
    set_exchange_rate, get_pending_withdrawals, update_withdrawal_status,
    get_custom_subjects_list, add_custom_subject, remove_custom_subject,
    check_is_admin_db
)

router = Router()
logger = logging.getLogger(__name__)

# ==== EXCHANGE ADMIN ====
@router.message(Command("setrate"))
async def cmd_set_rate(message: types.Message):
    if str(message.from_user.id) not in ADMIN_IDS:
        return
    
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("❌ Format: /setrate [rate]\nMasalan: /setrate 100 (100 tanga = 1 so'm)")
        return
    
    try:
        rate = float(parts[1])
        await set_exchange_rate(rate)
        await message.answer(f"✅ Yangi kurs o'rnatildi: {rate} tanga = 1 birlik")
    except ValueError:
        await message.answer("❌ Raqam kiriting.")

@router.message(Command("withdrawals"))
async def cmd_withdrawals(message: types.Message):
    if str(message.from_user.id) not in ADMIN_IDS:
        return
    
    pendings = await get_pending_withdrawals()
    if not pendings:
        await message.answer("✅ To'lov so'rovlari yo'q.")
        return
    
    text = "📋 <b>Kutilayotgan to'lovlar:</b>\n\n"
    for w in pendings:
        # id, user_id, username, amount_coins, amount_money, created_at
        wid, uid, uname, coins, money, date = w
        text += f"🆔 #{wid} | 👤 @{uname or uid}\n💰 {coins} tanga -> 💵 {money:.2f}\n📅 {date}\n"
        text += f"Tasdiqlash: /approve_{wid}\nBekor qilish: /reject_{wid}\n\n"
    
    await message.answer(text, parse_mode="HTML")

@router.message(F.text.regexp(r'^/(approve|reject)_(\d+)$'))
async def process_withdrawal_decision(message: types.Message):
    if str(message.from_user.id) not in ADMIN_IDS:
        return
    
    cmd = message.text.split('_')[0][1:] # approve or reject
    try:
        wid = int(message.text.split('_')[1])
    except:
        return

    status = "approved" if cmd == "approve" else "rejected"
    await update_withdrawal_status(wid, status)
    
    action = "Tasdiqlandi ✅" if status == "approved" else "Bekor qilindi ❌"
    await message.answer(f"🆔 #{wid} so'rov {action}")
    
    # Notify user (optional, requires storing user_id from msg logic or fetching from db again)
    # Ideally update_withdrawal_status should return user_id to notify. 
    # For now, simplistic.
    # For now, simplistic.

# ==== ADMIN AUTH ====
@router.message(Command("adminpanel"))
async def cmd_admin_panel_auth(message: types.Message, state: FSMContext):
    # Always respond with the generic message to hide existence, 
    # but strictly speaking if it's not for "all", we might want to check admin first?
    # User said: "barcha user uchun... ammo shu sozdan song admin password..."
    # So everyone sees the prompt.
    
    await message.answer("Bu buyruq faqat adminlar uchun!")
    await state.set_state(AdminAuthStates.waiting_for_password)

@router.message(AdminAuthStates.waiting_for_password)
async def process_admin_password(message: types.Message, state: FSMContext):
    password = message.text.strip()
    uid = message.from_user.id
    
    # Check Admin permission (Environment or DB)
    is_admin_env = str(uid) in ADMIN_IDS
    is_admin_db = await check_is_admin_db(uid)
    
    if (is_admin_env or is_admin_db) and password == ADMIN_PASSWORD:
        # Success
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="Admin Panel", web_app=types.WebAppInfo(url=f"{WEBAPP_URL}/admin"))]
        ])
        await message.answer("✅ Admin Panel Web App:", reply_markup=kb)
    else:
        # Failed - silent or error? User requirement implies prompt -> result.
        # "password kiritsa admin panel ... chiqishi kerak"
        # If wrong password, maybe just nothing or "Xato".
        await message.answer("❌ Parol yoki ruxsat xato.")
    
    await state.clear()

# ==== ADMIN: addproject, addquestion (single), addquestions (bulk) ====
@router.message(Command("addproject"))
async def cmd_add_project(message: types.Message, state: FSMContext):
    if not ADMIN_IDS or not message.from_user or str(message.from_user.id) not in ADMIN_IDS:
        await message.answer("❌ Bu komanda faqat admin uchun!")
        return

    await state.set_state(AddProjectStates.waiting_for_subject_key)
    await message.answer("📚 Yangi fan kalitini kiriting (masalan: biology).")

@router.message(AddProjectStates.waiting_for_subject_key)
async def process_project_subject_key(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Iltimos, fan kalitini kiriting.")
        return
    key = message.text.strip().lower()
    custom_subjects = await get_custom_subjects_list()
    if key in custom_subjects:
        await message.answer("❌ Bu fan yoki buyruq allaqachon mavjud.")
        await state.clear()
        return
    await add_custom_subject(key)
    await message.answer(f"✅ Fan qo‘shildi: {key}")
    await state.clear()

# --- /addquestion (single) ---
@router.message(Command("addquestion"))
async def cmd_add_question(message: types.Message, state: FSMContext):
    if not ADMIN_IDS or not message.from_user or str(message.from_user.id) not in ADMIN_IDS:
        await message.answer("❌ Bu komanda faqat admin uchun!")
        return

    subjects = await get_all_subjects()
    txt = "📘 Qaysi fan uchun savol qo‘shmoqchisiz?\n\n" + "\n".join(f"- {s}" for s in subjects)
    await message.answer(txt)
    await state.set_state(AddQuestionStates.waiting_for_subject)

@router.message(AddQuestionStates.waiting_for_subject)
async def process_subject_for_single(message: types.Message, state: FSMContext):
    subject = message.text.strip().lower()
    all_subs = await get_all_subjects()
    if subject not in all_subs:
        await message.answer("❌ Bunday fan topilmadi. Mavjud fanlardan birini kiriting.")
        return
    await state.update_data(subject=subject)
    await message.answer("✍️ Savol matnini yuboring (yoki rasm yuborishingiz mumkin).")
    await state.set_state(AddQuestionStates.waiting_for_question)

@router.message(AddQuestionStates.waiting_for_question, F.photo)
async def process_question_photo(message: types.Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await state.update_data(image_url=file_id)
    await message.answer("📝 Endi savol matnini ham yuboring (ixtiyoriy, yoki 'skip' deb yozing).")

@router.message(AddQuestionStates.waiting_for_question, F.text)
async def process_question_text(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if text.lower() == "skip":
        await state.update_data(question="❓Rasmdagi savol")
    else:
        await state.update_data(question=text)
    await message.answer("🔢 4 ta variantni har bir qatorda yuboring (4 qator):")
    await state.set_state(AddQuestionStates.waiting_for_options)

@router.message(AddQuestionStates.waiting_for_options)
async def process_options_single(message: types.Message, state: FSMContext):
    options = [opt.strip() for opt in message.text.replace('\r', '').split('\n') if opt.strip()]
    if len(options) != 4:
        await message.answer("❌ 4 ta variant bo‘lishi kerak! Har bir variantni yangi qatorda yuboring.")
        return
    await state.update_data(options=options)
    await message.answer("✅ To‘g‘ri variant raqamini kiriting (1-4):")
    await state.set_state(AddQuestionStates.waiting_for_correct)

@router.message(AddQuestionStates.waiting_for_correct)
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
@router.message(Command("addquestions"))
async def cmd_addquestions(message: types.Message, state: FSMContext):
    if not ADMIN_IDS or not message.from_user or str(message.from_user.id) not in ADMIN_IDS:
        await message.answer("❌ Bu komanda faqat admin uchun!")
        return
    await message.answer("📚 Qaysi fan uchun savollar qo‘shmoqchisiz? (fan nomini yozing):")
    await state.set_state(AddQuestionsStates.waiting_for_subject)

@router.message(AddQuestionsStates.waiting_for_subject)
async def process_subject_bulk(message: types.Message, state: FSMContext):
    subject = message.text.strip().lower()
    all_subs = await get_all_subjects()
    if subject not in all_subs:
        await message.answer("❌ Bunday fan topilmadi. Mavjud fanlardan birini kiriting:\n" + ", ".join(all_subs))
        return
    await state.update_data(subject=subject)
    await message.answer(
        "📋 Endi savollarni quyidagi formatda yuboring:\n\n"
        "Savol matni | variant1, variant2, variant3, variant4 | to‘g‘ri_javob_raqami\n\n"
        "Har bir savolni yangi qatorda yozing."
    )
    await state.set_state(AddQuestionsStates.waiting_for_questions)

@router.message(AddQuestionsStates.waiting_for_questions)
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
        if len(options) != 4 or not (0 <= correct <= 3):
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
@router.message(Command("deletequestion"))
async def cmd_delete_question(message: types.Message, state: FSMContext):
    if not ADMIN_IDS or not message.from_user or str(message.from_user.id) not in ADMIN_IDS:
        await message.answer("❌ Bu komanda faqat admin uchun!")
        return
    await message.answer("🧾 O‘chirmoqchi bo‘lgan savol matnini yuboring (qism matn):")
    await state.set_state(DeleteQuestionStates.waiting_for_question_text)

@router.message(DeleteQuestionStates.waiting_for_question_text)
async def process_question_to_delete(message: types.Message, state: FSMContext):
    qtxt = message.text.strip()

    rows = await search_questions(qtxt)
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

@router.message(DeleteQuestionStates.confirm_delete)
async def confirm_delete_question(message: types.Message, state: FSMContext):
    txt = message.text.strip().lower()
    data = await state.get_data()

    if txt.isdigit():
        qid = int(txt)
        await delete_question(qid)
        await message.answer("✅ Savol muvaffaqiyatli o‘chirildi!")
        await state.clear()
        return

    if txt in ("ha", "xa", "yes"):
        qid = data.get("question_id")
        if not qid:
            await message.answer("⚠️ ID topilmadi. Jarayon bekor qilindi.")
            await state.clear()
            return
        await delete_question(qid)
        await message.answer("✅ Savol muvaffaqiyatli o‘chirildi!")
        await state.clear()
        return

    await message.answer("❎ Jarayon bekor qilindi.")
    await state.clear()

@router.message(Command("deleteproject"))
async def cmd_delete_project(message: types.Message, state: FSMContext):
    if not ADMIN_IDS or not message.from_user or str(message.from_user.id) not in ADMIN_IDS:
        await message.answer("❌ Bu komanda faqat admin uchun!")
        return
    subjects = await get_custom_subjects_list()
    if not subjects:
        await message.answer("❌ Hozircha hech qanday custom fan yo‘q.")
        return
    txt = "🧾 Qaysi fanni o‘chirmoqchisiz?\n" + "\n".join(f"- {s}" for s in subjects)
    await message.answer(txt)
    await state.set_state(DeleteProjectStates.waiting_for_project_name)

@router.message(DeleteProjectStates.waiting_for_project_name)
async def process_project_to_delete(message: types.Message, state: FSMContext):
    project_name = message.text.strip().lower()
    custom_subjects = await get_custom_subjects_list()
    if project_name not in custom_subjects:
        await message.answer("❌ Bunday fan topilmadi.")
        await state.clear()
        return
    await state.update_data(project_name=project_name)
    await message.answer(f"🗑 Fan '{project_name}'ni aniq o‘chirmoqchimisiz? (ha/yo‘q)")
    await state.set_state(DeleteProjectStates.confirm_delete)

@router.message(DeleteProjectStates.confirm_delete)
async def confirm_delete_project(message: types.Message, state: FSMContext):
    txt = message.text.strip().lower()
    data = await state.get_data()
    if txt in ("ha", "xa", "yes"):
        project_name = data.get("project_name")
        await remove_custom_subject(project_name)
        await message.answer(f"✅ Fan '{project_name}' o‘chirildi!")
    else:
        await message.answer("❎ Jarayon bekor qilindi.")
    await state.clear()

import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS_ENV = os.getenv("ADMIN_IDS", "")
CHANNEL_ID_ENV = os.getenv("CHANNEL_ID")

ADMIN_IDS = [aid.strip() for aid in ADMIN_IDS_ENV.split(",") if aid.strip()]
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "1234")
CHANNEL_ID = int(CHANNEL_ID_ENV) if CHANNEL_ID_ENV else None

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN topilmadi! .env faylida BOT_TOKEN ni sozlang.")

DATABASE_URL = os.getenv("DATABASE_URL")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://quizbot-production-7f50.up.railway.app") # Default/Fallback

if WEBAPP_URL and not WEBAPP_URL.startswith("https://"):
    WEBAPP_URL = "https://" + WEBAPP_URL
if not DATABASE_URL:
    # Fallback for local testing or raise error? Use sqlite path as default? No, migrating to pg directly.
    # But for now let's just warn or default to None if we handle it in db.py
    pass

#!/usr/bin/env python3
import logging

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from telegram.ext import ApplicationBuilder, Application
from telegram import Update
import db
from handlers import registerHandlers
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_ID, TELEGRAM_ALLOWED_USERS, APP_LOG_LEVEL, APP_DB_PATH

# Set up logging
logLevel = getattr(logging, APP_LOG_LEVEL)
logging.basicConfig(level=logLevel, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

async def onStartup(app: Application):
    from i18n import loadLang
    loadLang("lang.json")
    await db.ensureSchema()
    for uid in TELEGRAM_ALLOWED_USERS:
        await db.allowUser(uid)

def main():
    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(onStartup)
        .build()
    )
    registerHandlers(app, TELEGRAM_ADMIN_ID)
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

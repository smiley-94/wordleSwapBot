# bot.py
#!/usr/bin/env python3
import logging
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from telegram.ext import ApplicationBuilder, Application
from telegram import Update
from i18n import loadLang
import db
from handlers import registerHandlers

import json

logLevel = getattr(logging, os.environ["logLevel"])
logging.basicConfig(level=logLevel, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

botToken = os.environ["botToken"]
adminUserId = os.environ["adminUserId"]

allowedUsers = os.environ.get("allowedUserArray", "").strip()
presetUsers: list[int] = json.loads(allowedUsers) if allowedUsers else []

async def onStartup(app: Application):
    loadLang("lang.json")
    await db.ensureSchema()
    for uid in presetUsers:
        await db.allowUser(uid)

def main():
    app = (
        ApplicationBuilder()
        .token(botToken)
        .post_init(onStartup)
        .build()
    )
    registerHandlers(app, int(adminUserId) if adminUserId and adminUserId.isdigit() else None)
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
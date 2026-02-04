#!/usr/bin/env python3
import logging
import os

try:
	from dotenv import load_dotenv
except ModuleNotFoundError:
	pass
else:
	load_dotenv()

from telegram.ext import ApplicationBuilder, Application, ContextTypes
from telegram import Update
from telegram.request import HTTPXRequest
from i18n import loadLang
import db
from handlers import registerHandlers

logLevel = getattr(logging, os.environ["APP_LOG_LEVEL"])
logging.basicConfig(
	level=logLevel,
	format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

logger = logging.getLogger(__name__)

botToken = os.environ["TELEGRAM_BOT_TOKEN"]
adminUserId = os.environ["TELEGRAM_ADMIN_ID"]

async def onStartup(_: Application):
	loadLang("lang.json")
	await db.ensureSchema()

async def errorHandler(_: object, context: ContextTypes.DEFAULT_TYPE):
	logger.error("Exception while handling an update:", exc_info=context.error)

def main():
	request = HTTPXRequest(
		connect_timeout=60.0,
		read_timeout=75.0,
		write_timeout=60.0,
		pool_timeout=60.0,
		connection_pool_size=8
	)

	app = (
		ApplicationBuilder()
		.token(botToken)
		.request(request)
		.get_updates_request(request)
		.post_init(onStartup)
		.build()
	)

	app.add_error_handler(errorHandler)

	registerHandlers(
		app,
		int(adminUserId) if adminUserId and adminUserId.isdigit() else None
	)

	app.run_polling(
		allowed_updates=Update.ALL_TYPES,
		drop_pending_updates=True,
		timeout=60,
		bootstrap_retries=-1
	)

if __name__ == "__main__":
	main()

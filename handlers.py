import asyncio
import html
import logging
from typing import Set
from urllib.parse import urlencode
from sqlite3 import IntegrityError
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, Application, CommandHandler, MessageHandler, filters
from telegram.error import Forbidden, BadRequest, TimedOut, NetworkError
from i18n import pickLang, tr
from util import romeDayBoundsUtc, iso, romeDayKey
import db
import random
from ocr import run_ocr, get_nyt_solution, preprocess_image, encode_image_b64
import io
from PIL import Image
from config import IMAGE_MAX_BYTES, IMAGE_MAX_WIDTH, ANALYZER_BASE_URL, ANALYZER_LINK_LABEL

logger = logging.getLogger(__name__)

ADMIN_USER_ID = None


def userLang(update: Update) -> str:
	return pickLang(getattr(getattr(update, "effective_user", None), "language_code", None))


def displayName(update: Update) -> str:
	u = update.effective_user
	if not u:
		return "someone"
	if u.username:
		return f"@{u.username}"
	full = " ".join(filter(None, [u.first_name, u.last_name]))
	return full.strip() or "someone"


def isAdmin(userId: int) -> bool:
	global ADMIN_USER_ID
	if ADMIN_USER_ID is None:
		return False
	try:
		return ADMIN_USER_ID == int(userId)
	except Exception:
		return False


def buildWordleAnalyzerLink(words: list[str]) -> str:
	# Always use hard mode (hm=1)
	plaintext = "".join(w.lower() for w in words)
	seed = random.randint(0, 99)
	encoded = _encode(seed, plaintext)
	params = {"guesses": encoded, "seed": str(seed), "hm": "1"}  # Always hard mode
	base = ANALYZER_BASE_URL.strip()
	if "?" in base:
		sep = "" if base.endswith("?") else "&"
		return base + sep + urlencode(params)
	return base.rstrip("/") + "/?" + urlencode(params)


def captionHtml(
		authorName: str | None,
		authorUsername: str | None,
		link: str | None,
		customText: str | None = None,
		timeRome: str | None = None
) -> tuple[str, ParseMode]:
	name = (authorName or "").strip()
	handle = ("@" + authorUsername.strip()) if authorUsername else ""
	first_line = " ".join(part for part in [name, handle] if part).strip() or "someone"

	if timeRome:
		first_line = f"[{timeRome}] {first_line}"

	lines = [html.escape(first_line)]

	if link:
		safe = html.escape(link, quote=True)
		label = html.escape(ANALYZER_LINK_LABEL)
		lines.append(f'<a href="{safe}">{label}</a>')

	if customText:
		lines.append(html.escape(customText))

	return "\n".join(lines), ParseMode.HTML


def formatUserLabel(fallbackDisplay: str, username: str | None, fullName: str | None) -> str:
	u = username.strip() if username else ""
	n = fullName.strip() if fullName else ""
	if u and n:
		return f"@{u} – {n}"
	if u:
		return f"@{u}"
	if n:
		return n
	return fallbackDisplay


def _encode(seed: int, word: str) -> str:
	LETTERS = list("abcdefghijklmnopqrstuvwxyz")
	LETTERS_MAP = {ch: i for i, ch in enumerate(LETTERS)}

	def mulberry32(seed: int):
		seed &= 0xFFFFFFFF

		def rand() -> float:
			nonlocal seed
			seed = (seed + 0x6D2B79F5) & 0xFFFFFFFF
			t = ((seed ^ (seed >> 15)) * (1 | seed)) & 0xFFFFFFFF
			t = (t + (((t ^ (t >> 7)) * (61 | t)) & 0xFFFFFFFF)) ^ t
			t &= 0xFFFFFFFF
			return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0

		return rand

	def _shuffle_with(rand: callable, array: list[str]) -> list[str]:
		arr = list(array)
		current_index = len(arr)
		while current_index:
			random_index = int(rand() * current_index)
			current_index -= 1
			arr[current_index], arr[random_index] = arr[random_index], arr[current_index]
		return arr

	shuffled = _shuffle_with(mulberry32(seed), LETTERS)
	out = []
	for i, ch in enumerate(word):
		idx = LETTERS_MAP[ch]
		out.append(shuffled[(idx + i) % len(shuffled)])
	return "".join(out)


async def startCmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
	lang = userLang(update)
	await update.message.reply_text(tr(lang, "welcome"), parse_mode=ParseMode.MARKDOWN)


async def helpCmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
	lang = userLang(update)
	user = update.effective_user
	if user and isAdmin(user.id):
		await update.message.reply_text(tr(lang, "help_admin"))
	else:
		await update.message.reply_text(tr(lang, "help_user"))


async def idCmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
	lang = userLang(update)
	user = update.effective_user
	if not user:
		return
	await update.message.reply_text(tr(lang, "your_user_id", uid=user.id))


async def authorCmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
	lang = userLang(update)
	anchor = '<a href="https://github.com/aleSuglia">Smiley</a>'
	await update.message.reply_text(tr(lang, "created_by", author=anchor), parse_mode=ParseMode.HTML)


async def resetdbCmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
	lang = userLang(update)
	user = update.effective_user
	if not user or not isAdmin(user.id):
		logger.warning(f"Unauthorized user {user.id} attempted to reset database")
		await update.message.reply_text(tr(lang, "not_authorized", uid=user.id if user else "?"))
		return
	logger.info(f"Admin {user.id} initiated database reset")
	await db.resetDb()
	await update.message.reply_text(tr(lang, "reset_done"))


async def resetTodayCmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
	lang = userLang(update)
	user = update.effective_user

	if not user or not isAdmin(user.id):
		logger.warning(f"Unauthorized user {user.id} attempted to reset today's images")
		await update.message.reply_text(tr(lang, "not_authorized", uid=user.id if user else "?"))
		return

	if not context.args:
		await update.message.reply_text(tr(lang, "reset_today_usage"))
		return

	arg = context.args[0]
	logger.info(f"Admin {user.id} attempting to reset today's images for: {arg}")

	# Get today's date range
	startUtc, endUtc = romeDayBoundsUtc()
	startIso = iso(startUtc)
	endIso = iso(endUtc)

	if arg.upper() == "ALL":
		# Delete all images from today
		deleted_count = await db.deleteImagesByDateRange(startIso, endIso)
		logger.info(f"Admin {user.id} deleted {deleted_count} images from today")
		await update.message.reply_text(tr(lang, "reset_today_all_done", count=deleted_count))
	elif arg.isdigit():
		# Delete images for specific user
		target_user_id = int(arg)
		deleted_count = await db.deleteImagesByUserAndDate(target_user_id, startIso, endIso)
		logger.info(f"Admin {user.id} deleted {deleted_count} images for user {target_user_id} from today")
		await update.message.reply_text(tr(lang, "reset_today_user_done", uid=target_user_id, count=deleted_count))
	else:
		await update.message.reply_text(tr(lang, "reset_today_bad_args"))


async def allowedCmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
	lang = userLang(update)
	user = update.effective_user
	if not user or not isAdmin(user.id):
		logger.warning(f"Unauthorized user {user.id} attempted to list allowed users")
		await update.message.reply_text(tr(lang, "not_authorized", uid=user.id if user else "?"))
		return
	rows = await db.listAllowedDetailed()
	if not rows:
		await update.message.reply_text(tr(lang, "allowed_list_empty"))
		return
	header = tr(lang, "allowed_list_header", count=len(rows))
	lines = []
	for uid, uname, fullname in rows:
		label = formatUserLabel(str(uid), uname, fullname)
		lines.append(f"{uid} – {label}")
	await update.message.reply_text(header + "\n" + "\n".join(lines))


async def allowCmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
	lang = userLang(update)
	user = update.effective_user
	if not user or not isAdmin(user.id):
		logger.warning(f"Unauthorized user {user.id} attempted to allow user")
		await update.message.reply_text(tr(lang, "not_authorized", uid=user.id if user else "?"))
		return
	if not context.args or not context.args[0].isdigit():
		await update.message.reply_text(tr(lang, "bad_args"))
		return
	uid = int(context.args[0])
	logger.info(f"Admin {user.id} attempting to allow user {uid}")
	added = await db.allowUser(uid)
	if added:
		logger.info(f"Successfully allowed user {uid}")
		await update.message.reply_text(tr(lang, "allow_ok", uid=uid))
	else:
		logger.info(f"User {uid} was already allowed")
		await update.message.reply_text(tr(lang, "allow_exists", uid=uid))


async def denyCmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
	lang = userLang(update)
	user = update.effective_user
	if not user or not isAdmin(user.id):
		logger.warning(f"Unauthorized user {user.id} attempted to deny user")
		await update.message.reply_text(tr(lang, "not_authorized", uid=user.id if user else "?"))
		return
	if not context.args or not context.args[0].isdigit():
		await update.message.reply_text(tr(lang, "bad_args"))
		return
	uid = int(context.args[0])
	logger.info(f"Admin {user.id} attempting to deny user {uid}")
	removed = await db.denyUser(uid)
	if removed:
		logger.info(f"Successfully denied user {uid}")
		await update.message.reply_text(tr(lang, "deny_ok", uid=uid))
	else:
		logger.info(f"User {uid} was not in allowed list")
		await update.message.reply_text(tr(lang, "deny_missing", uid=uid))


async def broadcastCmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
	lang = userLang(update)
	user = update.effective_user

	if not user or not isAdmin(user.id):
		logger.warning(f"Unauthorized user {user.id} attempted to broadcast")
		await update.message.reply_text(tr(lang, "not_authorized", uid=user.id if user else "?"))
		return

	msg = update.message
	if not msg or not msg.text:
		await update.message.reply_text(tr(lang, "broadcast_no_message"))
		return

	fullText = msg.text
	command = fullText.split(maxsplit=1)

	if len(command) < 2:
		await update.message.reply_text(tr(lang, "broadcast_no_message"))
		return

	message = command[1]

	# Get all allowed users
	allowedUsers = await db.listAllowed()

	if not allowedUsers:
		logger.info("No allowed users found for broadcast")
		await update.message.reply_text(tr(lang, "broadcast_no_users"))
		return

	logger.info(f"Broadcasting message to {len(allowedUsers)} users")
	successCount = 0
	failCount = 0

	# Send to all allowed users
	for userId in allowedUsers:
		try:
			await context.bot.send_message(
				chat_id=userId,
				text=message,
				parse_mode=ParseMode.HTML,
				disable_notification=True
			)
			successCount += 1
			await asyncio.sleep(0.05)
		except (Forbidden, BadRequest, TimedOut, NetworkError) as e:
			logger.warning(f"Failed to broadcast to user {userId}: {e}")
			failCount += 1

	logger.info(f"Broadcast completed: {successCount} successful, {failCount} failed")
	await update.message.reply_text(
		tr(lang, "broadcast_done", success=successCount, failed=failCount)
	)


async def receivePhoto(update: Update, context: ContextTypes.DEFAULT_TYPE):
	lang = userLang(update)
	msg = update.message
	user = update.effective_user
	chat = update.effective_chat

	if not user or not chat or not msg:
		logger.warning("Received photo update without user/chat/message")
		return

	logger.info(f"Processing photo from user {user.id}")

	if not await db.isAllowed(user.id):
		logger.info(f"Unauthorized user {user.id} attempted to send photo")
		await msg.reply_text(tr(lang, "not_authorized", uid=user.id if user else "?"))
		return

	startUtc, endUtc = romeDayBoundsUtc()
	startIso = iso(startUtc)
	endIso = iso(endUtc)
	dayKey = romeDayKey()

	if not msg.photo:
		logger.warning(f"User {user.id} sent message without photo")
		await msg.reply_text(tr(lang, "no_photo_found"))
		return

	best = chooseConstrainedPhoto(msg.photo)
	fileId = best.file_id

	u = update.effective_user
	userUsername = (u.username or "").strip() if u else ""
	userFullName = " ".join(filter(None, [u.first_name, u.last_name])).strip() if u else ""
	dname = displayName(update)

	# Get the photo file
	logger.info(f"Downloading photo file_id: {fileId} from user {user.id}")
	photo_file = await context.bot.get_file(fileId)

	# Download the photo
	photo_bytes = await photo_file.download_as_bytearray()
	photo_stream = io.BytesIO(bytes(photo_bytes))

	# Process image with OCR
	linkForThis = None
	try:
		logger.info(f"Running OCR on photo from user {user.id}")
		original_img = Image.open(photo_stream)
		processed_img = preprocess_image(original_img)
		img_b64 = encode_image_b64(processed_img)
		words = run_ocr(img_b64)
		logger.info(f"OCR extracted words for user {user.id}: {words}")

		# Get today's NYT solution
		from datetime import datetime
		today_date = datetime.now().strftime("%Y-%m-%d")
		solution = get_nyt_solution(today_date)
		logger.info(f"NYT solution for {today_date}: {solution}")

		# Add solution to words if it's not already there
		if solution and solution.upper() not in words:
			words.append(solution.upper())
			logger.info(f"Added solution {solution} to word list for user {user.id}")

		# Generate analyzer link if we have words
		linkForThis = buildWordleAnalyzerLink(words) if words else None
		if linkForThis:
			logger.info(f"Generated analyzer link for user {user.id}")
	except Exception as e:
		logger.warning(f"OCR processing failed for user {user.id}: {e}")
		linkForThis = None
		words = []

	# Custom text is now everything in the caption
	customText = (msg.caption or "").strip() if msg.caption else None

	try:
		logger.info(f"Saving image data for user {user.id}")
		await db.saveImage(
			user.id,
			chat.id,
			dname,
			fileId,
			dayKey,
			linkForThis,
			userUsername or None,
			userFullName or None,
			customText
		)
	except IntegrityError:
		logger.info(f"User {user.id} already uploaded today")
		await msg.reply_text(tr(lang, "already_uploaded"))
		return

	if linkForThis:
		try:
			safe = html.escape(linkForThis, quote=True)
			label = html.escape(ANALYZER_LINK_LABEL)
			await msg.reply_text(f'<a href="{safe}">{label}</a>', parse_mode=ParseMode.HTML)
			logger.info(f"Sent analyzer link to user {user.id}")
		except Exception as e:
			logger.warning(f"Failed to send analyzer link to user {user.id}: {e}")

	others = await db.getOtherImagesToday(user.id, startIso, endIso, limit=10)

	if others:
		logger.info(f"Sending {len(others)} previous images to user {user.id}")
		from datetime import datetime, timezone
		from zoneinfo import ZoneInfo
		ROME = ZoneInfo("Europe/Rome")

		for fid, authorDisplay, otherLink, otherUname, otherFull, otherCustom, createdAtIso in others:
			try:
				dt = datetime.fromisoformat(createdAtIso.replace("Z", "+00:00")).astimezone(ROME)
				hhmm = dt.strftime("%H:%M")
				authorName = (otherFull or authorDisplay or "").strip()

				capHtml, pMode = captionHtml(authorName, otherUname, otherLink, otherCustom, timeRome=hhmm)
				await msg.reply_photo(fid, caption=capHtml, parse_mode=pMode)
			except (Forbidden, BadRequest, TimedOut, NetworkError) as e:
				logger.warning(f"Failed to send previous image to user {user.id}: {e}")
	else:
		await msg.reply_text(tr(lang, "saved_no_others"))
		logger.info(f"No previous images to send to user {user.id}")

	recipientChatIds = await db.getRecipientChatsToday(user.id, startIso, endIso)
	uniqueChats: Set[int] = set(recipientChatIds)

	authorNameForUploader = (userFullName or dname or "").strip()

	from datetime import datetime, timezone
	from zoneinfo import ZoneInfo
	ROME = ZoneInfo("Europe/Rome")
	nowRome = datetime.now(timezone.utc).astimezone(ROME)
	now_hhmm = nowRome.strftime("%H:%M")

	logger.info(f"Distributing new image from user {user.id} to {len(uniqueChats)} recipients")
	for rcid in uniqueChats:
		try:
			capHtml, pMode = captionHtml(authorNameForUploader, userUsername, linkForThis, customText,
										 timeRome=now_hhmm)
			await context.bot.send_photo(chat_id=rcid, photo=fileId, caption=capHtml, parse_mode=pMode)
			await asyncio.sleep(0.05)
		except (Forbidden, BadRequest, TimedOut, NetworkError) as e:
			logger.warning(f"Failed to distribute image to chat {rcid}: {e}")


def chooseConstrainedPhoto(photos):
	def area(p):
		return (p.width or 0) * (p.height or 0)

	candidates = []
	for p in photos:
		widthOk = (IMAGE_MAX_WIDTH <= 0) or (p.width <= IMAGE_MAX_WIDTH)
		sizeOk = True
		if getattr(p, "file_size", None) is not None and IMAGE_MAX_BYTES > 0:
			sizeOk = p.file_size <= IMAGE_MAX_BYTES
		if widthOk and sizeOk:
			candidates.append(p)
	return max(candidates, key=area) if candidates else min(photos, key=area)


def registerHandlers(app: Application, adminUserId: int | None):
	global ADMIN_USER_ID
	ADMIN_USER_ID = adminUserId
	app.add_handler(CommandHandler("start", startCmd))
	app.add_handler(CommandHandler("help", helpCmd))
	app.add_handler(CommandHandler("id", idCmd))
	app.add_handler(CommandHandler("author", authorCmd))
	app.add_handler(CommandHandler("resetdb", resetdbCmd))
	app.add_handler(CommandHandler("resetToday", resetTodayCmd))
	app.add_handler(CommandHandler("allowed", allowedCmd))
	app.add_handler(CommandHandler("allow", allowCmd))
	app.add_handler(CommandHandler("deny", denyCmd))
	app.add_handler(CommandHandler("broadcast", broadcastCmd))
	app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, receivePhoto))
	app.add_handler(MessageHandler(filters.COMMAND, helpCmd))

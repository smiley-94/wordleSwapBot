import asyncio
import os
import re
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

logger = logging.getLogger(__name__)

maxPhotoBytes = int(os.environ["botMaxPhotoBytes"])
maxPhotoWidth = int(os.environ["botMaxPhotoWidth"])
analyzerBase = os.environ["botAnalyzerBase"]
analyzerLinkName = os.environ["botAnalyzerLinkName"]

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


def chooseConstrainedPhoto(photos):
    def area(p):
        return (p.width or 0) * (p.height or 0)

    candidates = []
    for p in photos:
        widthOk = (maxPhotoWidth <= 0) or (p.width <= maxPhotoWidth)
        sizeOk = True
        if getattr(p, "file_size", None) is not None and maxPhotoBytes > 0:
            sizeOk = p.file_size <= maxPhotoBytes
        if widthOk and sizeOk:
            candidates.append(p)
    return max(candidates, key=area) if candidates else min(photos, key=area)


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


def _encode(seed: int, word: str) -> str:
    shuffled = _shuffle_with(mulberry32(seed), LETTERS)
    out = []
    for i, ch in enumerate(word):
        idx = LETTERS_MAP[ch]
        out.append(shuffled[(idx + i) % len(shuffled)])
    return "".join(out)


def buildWordleAnalyzerLink(words: list[str], hm: int) -> str:
    plaintext = "".join(w.lower() for w in words)
    seed = random.randint(0, 99)
    encoded = _encode(seed, plaintext)
    params = {"guesses": encoded, "seed": str(seed), "hm": str(int(hm))}
    base = analyzerBase.strip()
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
        label = html.escape(analyzerLinkName)
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
        await update.message.reply_text(tr(lang, "not_authorized", uid=user.id if user else "?"))
        return
    await db.resetDb()
    await update.message.reply_text(tr(lang, "reset_done"))


async def allowedCmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = userLang(update)
    user = update.effective_user
    if not user or not isAdmin(user.id):
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
        await update.message.reply_text(tr(lang, "not_authorized", uid=user.id if user else "?"))
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(tr(lang, "bad_args"))
        return
    uid = int(context.args[0])
    added = await db.allowUser(uid)
    if added:
        await update.message.reply_text(tr(lang, "allow_ok", uid=uid))
    else:
        await update.message.reply_text(tr(lang, "allow_exists", uid=uid))


async def denyCmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = userLang(update)
    user = update.effective_user
    if not user or not isAdmin(user.id):
        await update.message.reply_text(tr(lang, "not_authorized", uid=user.id if user else "?"))
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(tr(lang, "bad_args"))
        return
    uid = int(context.args[0])
    removed = await db.denyUser(uid)
    if removed:
        await update.message.reply_text(tr(lang, "deny_ok", uid=uid))
    else:
        await update.message.reply_text(tr(lang, "deny_missing", uid=uid))


async def broadcastCmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = userLang(update)
    user = update.effective_user

    if not user or not isAdmin(user.id):
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

    chatIds = await db.getAllUserChatIds()

    if not chatIds:
        await update.message.reply_text(tr(lang, "broadcast_no_users"))
        return

    successCount = 0
    failCount = 0

    for chatId in chatIds:
        try:
            await context.bot.send_message(
                chat_id=chatId,
                text=message,
                parse_mode=ParseMode.HTML,
                disable_notification=True
            )
            successCount += 1
            await asyncio.sleep(0.05)
        except (Forbidden, BadRequest, TimedOut, NetworkError):
            failCount += 1

    await update.message.reply_text(
        tr(lang, "broadcast_done", success=successCount, failed=failCount)
    )


def determine_hm(caption: str) -> int:
    letters = [c for c in caption if c.isalpha()]
    if not letters:
        return 1
    return 0 if all(c.islower() for c in letters) else 1


async def receivePhoto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = userLang(update)
    msg = update.message
    user = update.effective_user
    chat = update.effective_chat

    if not user or not chat or not msg:
        return

    if not await db.isAllowed(user.id):
        await msg.reply_text(tr(lang, "not_authorized", uid=user.id if user else "?"))
        return

    startUtc, endUtc = romeDayBoundsUtc()
    startIso = iso(startUtc)
    endIso = iso(endUtc)
    dayKey = romeDayKey()

    if not msg.photo:
        await msg.reply_text(tr(lang, "no_photo_found"))
        return

    best = chooseConstrainedPhoto(msg.photo)
    fileId = best.file_id

    u = update.effective_user
    userUsername = (u.username or "").strip() if u else ""
    userFullName = " ".join(filter(None, [u.first_name, u.last_name])).strip() if u else ""
    dname = displayName(update)

    linkForThis = None
    customText = None
    cap = (msg.caption or "")

    if cap:
        parts = cap.split('@', 1)
        wordsPart = parts[0].strip()

        if len(parts) > 1:
            customText = parts[1].strip()

        if wordsPart and re.fullmatch(r"[A-Za-z\s]+", wordsPart):
            raw_tokens = wordsPart.split()
            valid_tokens = [t for t in raw_tokens if len(t) == 5 and t.isalpha()]

            if 1 <= len(valid_tokens) <= 7 and len(valid_tokens) == len(raw_tokens):
                hm = determine_hm(wordsPart)
                words = [tok.lower() for tok in valid_tokens]
                linkForThis = buildWordleAnalyzerLink(words, hm)

    try:
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


    if linkForThis:
        try:
            safe = html.escape(linkForThis, quote=True)
            label = html.escape(analyzerLinkName)
            await msg.reply_text(f'<a href="{safe}">{label}</a>', parse_mode=ParseMode.HTML)
        except Exception:
            pass

    others = await db.getOtherImagesToday(user.id, startIso, endIso, limit=10)

    if others:
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
            except (Forbidden, BadRequest, TimedOut, NetworkError):
                pass
    else:
        await msg.reply_text(tr(lang, "saved_no_others"))

    recipientChatIds = await db.getRecipientChatsToday(user.id, startIso, endIso)
    uniqueChats: Set[int] = set(recipientChatIds)

    authorNameForUploader = (userFullName or dname or "").strip()

    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    ROME = ZoneInfo("Europe/Rome")
    nowRome = datetime.now(timezone.utc).astimezone(ROME)
    now_hhmm = nowRome.strftime("%H:%M")

    for rcid in uniqueChats:
        try:
            capHtml, pMode = captionHtml(authorNameForUploader, userUsername, linkForThis, customText,
                                         timeRome=now_hhmm)
            await context.bot.send_photo(chat_id=rcid, photo=fileId, caption=capHtml, parse_mode=pMode)
            await asyncio.sleep(0.05)
        except (Forbidden, BadRequest, TimedOut, NetworkError):
            pass


def registerHandlers(app: Application, adminUserId: int | None):
    global ADMIN_USER_ID
    ADMIN_USER_ID = adminUserId
    app.add_handler(CommandHandler("start", startCmd))
    app.add_handler(CommandHandler("help", helpCmd))
    app.add_handler(CommandHandler("id", idCmd))
    app.add_handler(CommandHandler("author", authorCmd))
    app.add_handler(CommandHandler("resetdb", resetdbCmd))
    app.add_handler(CommandHandler("allowed", allowedCmd))
    app.add_handler(CommandHandler("allow", allowCmd))
    app.add_handler(CommandHandler("deny", denyCmd))
    app.add_handler(CommandHandler("broadcast", broadcastCmd))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, receivePhoto))
    app.add_handler(MessageHandler(filters.COMMAND, helpCmd))

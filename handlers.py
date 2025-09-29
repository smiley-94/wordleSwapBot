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
        return int(ADMIN_USER_ID) == int(userId)
    except Exception:
        return False

def chooseConstrainedPhoto(photos):
    def area(p): return (p.width or 0) * (p.height or 0)
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
    """
    Mulberry32 PRNG, ported from wordle-analyzer's TS.
    Returns a function producing floats in [0,1).
    """
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
    """
    Fisher–Yates using the provided RNG (signature: () -> float in [0,1)).
    """
    arr = list(array)
    current_index = len(arr)
    while current_index:
        random_index = int(rand() * current_index)
        current_index -= 1
        arr[current_index], arr[random_index] = arr[random_index], arr[current_index]
    return arr

def _encode(seed: int, word: str) -> str:
    """
    Mirrors encode(seed, word) from wordle-analyzer:
      - Shuffle alphabet with seeded PRNG
      - For each letter at index i: shuffled[(lettersMap[letter] + i) % 26]
    Precondition: 'word' must be lowercase a-z only.
    """
    shuffled = _shuffle_with(mulberry32(seed), LETTERS)
    out = []
    for i, ch in enumerate(word):
        idx = LETTERS_MAP[ch]  # KeyError if outside a-z, by design
        out.append(shuffled[(idx + i) % len(shuffled)])
    return "".join(out)

def buildWordleAnalyzerLink(words: list[str], hm: int) -> str:
    """
    Builds: https://wordle-analyzer.com/?guesses=<encoded>&seed=<seed>&hm=<0|1>
    - 'words' are 5-letter tokens (guesses + solution), concatenated without separators.
    - Seed is chosen in [0, 99] to mirror the TS example.
    - 'hm' is 0 if caption is all lowercase letters, else 1.
    """
    plaintext = "".join(w.lower() for w in words)   # encode expects lowercase
    seed = random.randint(0, 99)
    encoded = _encode(seed, plaintext)

    params = {"guesses": encoded, "seed": str(seed), "hm": str(int(hm))}
    base = analyzerBase.strip()
    if "?" in base:
        sep = "" if base.endswith("?") else "&"
        return base + sep + urlencode(params)
    return base.rstrip("/") + "/?" + urlencode(params)


def captionHtml(authorName: str | None, authorUsername: str | None, link: str | None) -> tuple[str, ParseMode]:
    """
    Line 1: "Full Name @username" (only present parts; fallback 'someone')
    Line 2: clickable analyzer label (only if link is provided)
    """
    name = (authorName or "").strip()
    handle = ("@" + authorUsername.strip()) if authorUsername else ""
    first_line = " ".join(part for part in [name, handle] if part).strip() or "someone"

    if link:
        safe = html.escape(link, quote=True)
        label = html.escape(analyzerLinkName)  # e.g., "analizer"
        return f'{html.escape(first_line)}\n<a href="{safe}">{label}</a>', ParseMode.HTML

    return html.escape(first_line), ParseMode.HTML


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
    anchor = '<a href="https://github.com/smiley-94">Smiley</a>'
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

def determine_hm(caption: str) -> int:
    """
    hm = 0 if the caption consists only of lowercase letters (a-z) and whitespace.
    hm = 1 otherwise (any uppercase present).
    Non-letters are not allowed for analyzer (handled by validator); this function
    only checks case, not token validity.
    """
    letters = [c for c in caption if c.isalpha()]
    if not letters:
        return 1  # no letters -> treat as 1 (won't be used if string is invalid anyway)
    return 0 if all(c.islower() for c in letters) else 1


async def receivePhoto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = userLang(update)
    msg = update.message
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat or not msg:
        return

    # Authorization
    if not await db.isAllowed(user.id):
        await msg.reply_text(tr(lang, "not_authorized", uid=user.id if user else "?"))
        return

    # Day bounds (Europe/Rome)
    startUtc, endUtc = romeDayBoundsUtc()
    startIso = iso(startUtc)
    endIso = iso(endUtc)
    dayKey = romeDayKey()

    # Validate presence of photo
    if not msg.photo:
        await msg.reply_text(tr(lang, "no_photo_found"))
        return

    # Pick the best-sized photo under constraints
    best = chooseConstrainedPhoto(msg.photo)
    fileId = best.file_id

    # Author fields
    u = update.effective_user
    userUsername = (u.username or "").strip() if u else ""
    userFullName = " ".join(filter(None, [u.first_name, u.last_name])).strip() if u else ""
    dname = displayName(update)

    linkForThis = None
    cap = (msg.caption or "")
    if cap and re.fullmatch(r"[A-Za-z\s]+", cap):
        raw_tokens = cap.split()
        valid_tokens = [t for t in raw_tokens if len(t) == 5 and t.isalpha()]
        if 1 <= len(valid_tokens) <= 7 and len(valid_tokens) == len(raw_tokens):
            hm = determine_hm(cap) 
            words = [tok.lower() for tok in valid_tokens]
            linkForThis = buildWordleAnalyzerLink(words, hm)


    # Persist (unique per user/day)
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
        )
    except IntegrityError:
        await msg.reply_text(tr(lang, "already_uploaded"))
        return

    # 1) Send the analyzer to the uploader FIRST (if we have a link)
    if linkForThis:
        try:
            safe = html.escape(linkForThis, quote=True)
            label = html.escape(analyzerLinkName)
            await msg.reply_text(f'<a href="{safe}">{label}</a>', parse_mode=ParseMode.HTML)
        except Exception:
            # Non-fatal: carry on to the rest of the flow
            pass

    # 2) Then send earlier photos (today) back to the uploader
    others = await db.getOtherImagesToday(user.id, startIso, endIso, limit=10)
    if others:
        for fid, authorDisplay, otherLink, otherUname, otherFull in others:
            try:
                authorName = (otherFull or authorDisplay or "").strip()
                capHtml, pMode = captionHtml(authorName, otherUname, otherLink)
                await msg.reply_photo(fid, caption=capHtml, parse_mode=pMode)
            except (Forbidden, BadRequest, TimedOut, NetworkError):
                # Ignore delivery errors to individual messages
                pass
    else:
        await msg.reply_text(tr(lang, "saved_no_others"))

    # 3) Finally, broadcast the uploader's photo to other chats that already uploaded today
    recipientChatIds = await db.getRecipientChatsToday(user.id, startIso, endIso)
    uniqueChats: Set[int] = set(recipientChatIds)
    authorNameForUploader = (userFullName or dname or "").strip()
    for rcid in uniqueChats:
        try:
            capHtml, pMode = captionHtml(authorNameForUploader, userUsername, linkForThis)
            await context.bot.send_photo(chat_id=rcid, photo=fileId, caption=capHtml, parse_mode=pMode)
            await asyncio.sleep(0.05)  # gentle pacing
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
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, receivePhoto))
    app.add_handler(MessageHandler(filters.COMMAND, helpCmd))

import os
import sqlite3
import asyncio
from datetime import datetime, timezone
from config import APP_DB_PATH
import logging

logger = logging.getLogger(__name__)


def openConn() -> sqlite3.Connection:
	# Ensure the directory exists
	db_dir = os.path.dirname(APP_DB_PATH) or "."
	os.makedirs(db_dir, exist_ok=True)

	# Check if we have write permissions to the directory
	if not os.access(db_dir, os.W_OK):
		raise PermissionError(f"No write permission to database directory: {db_dir}")

	conn = sqlite3.connect(APP_DB_PATH, timeout=30, isolation_level=None)
	conn.execute("PRAGMA journal_mode=WAL;")
	conn.execute("PRAGMA synchronous=NORMAL;")
	conn.execute("PRAGMA foreign_keys=ON;")
	return conn


def tableExists(conn: sqlite3.Connection, name: str) -> bool:
	cur = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1;", (name,))
	return cur.fetchone() is not None


CREATE_TABLE_FULL_SQL = """
CREATE TABLE images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    username TEXT,
    file_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    day_key TEXT,
    link TEXT,
    user_username TEXT,
    user_full_name TEXT,
    custom_text TEXT
);
"""

CREATE_INDEX_USER = "CREATE INDEX IF NOT EXISTS idx_images_user ON images(user_id);"
CREATE_INDEX_CHAT = "CREATE INDEX IF NOT EXISTS idx_images_chat ON images(chat_id);"
CREATE_INDEX_CREATED = "CREATE INDEX IF NOT EXISTS idx_images_created ON images(created_at);"

ALTER_ADD_USERNAME_SQL = "ALTER TABLE images ADD COLUMN username TEXT;"
ALTER_ADD_CHAT_SQL = "ALTER TABLE images ADD COLUMN chat_id INTEGER;"
ALTER_ADD_DAYKEY_SQL = "ALTER TABLE images ADD COLUMN day_key TEXT;"
ALTER_ADD_LINK_SQL = "ALTER TABLE images ADD COLUMN link TEXT;"
ALTER_ADD_USERUSERNAME_SQL = "ALTER TABLE images ADD COLUMN user_username TEXT;"
ALTER_ADD_USERFULLNAME_SQL = "ALTER TABLE images ADD COLUMN user_full_name TEXT;"
ALTER_ADD_CUSTOMTEXT_SQL = "ALTER TABLE images ADD COLUMN custom_text TEXT;"

CREATE_UNIQUE_DAY_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_images_user_day
ON images(user_id, day_key)
WHERE day_key IS NOT NULL;
"""

CREATE_ALLOWED_SQL = """
CREATE TABLE IF NOT EXISTS allowed_users (
    user_id INTEGER PRIMARY KEY,
    added_at TEXT NOT NULL
);
"""

INSERT_IMAGE_SQL = """
INSERT INTO images (user_id, chat_id, username, file_id, created_at, day_key, link, user_username, user_full_name, custom_text)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""

SELECT_OTHERS_TODAY_SQL = """
SELECT file_id,
       COALESCE(NULLIF(username, ''), 'someone') AS author_display,
       link,
       user_username,
       user_full_name,
       custom_text,
       created_at
FROM images
WHERE user_id <> ?
  AND created_at >= ?
  AND created_at < ?
ORDER BY created_at ASC;
"""

SELECT_TODAY_RECIPIENTS_SQL = """
SELECT DISTINCT chat_id
FROM images
WHERE user_id <> ?
  AND created_at >= ?
  AND created_at < ?;
"""

SELECT_ALLOWED_DETAILED_SQL = """
WITH latest AS (
    SELECT i.user_id,
           MAX(i.created_at) AS max_created
    FROM images i
    GROUP BY i.user_id
)
SELECT au.user_id,
       COALESCE(i.user_username, '') AS user_username,
       COALESCE(i.user_full_name, '') AS user_full_name
FROM allowed_users au
LEFT JOIN latest l ON l.user_id = au.user_id
LEFT JOIN images i
  ON i.user_id = l.user_id AND i.created_at = l.max_created
ORDER BY au.user_id;
"""

SELECT_ALL_USER_CHATS_SQL = """
WITH latest_chat AS (
    SELECT user_id, chat_id, MAX(created_at) AS max_created
    FROM images
    GROUP BY user_id
)
SELECT DISTINCT lc.chat_id
FROM latest_chat lc
INNER JOIN allowed_users au ON au.user_id = lc.user_id;
"""

DELETE_IMAGES_SQL = "DELETE FROM images;"
DELETE_IMAGES_BY_DATE_RANGE_SQL = "DELETE FROM images WHERE created_at >= ? AND created_at < ?;"
DELETE_IMAGES_BY_USER_AND_DATE_SQL = "DELETE FROM images WHERE user_id = ? AND created_at >= ? AND created_at < ?;"


def ensureSchemaSync():
	try:
		conn = openConn()
	except PermissionError as e:
		raise PermissionError(f"Cannot access database file: {e}")
	except Exception as e:
		raise Exception(f"Failed to open database connection: {e}")

	try:
		if not tableExists(conn, "images"):
			conn.executescript(CREATE_TABLE_FULL_SQL)
		else:
			cur = conn.execute("PRAGMA table_info(images);")
			cols = {row[1] for row in cur.fetchall()}
			if "username" not in cols:
				conn.execute(ALTER_ADD_USERNAME_SQL)
			if "chat_id" not in cols:
				conn.execute(ALTER_ADD_CHAT_SQL)
			if "day_key" not in cols:
				conn.execute(ALTER_ADD_DAYKEY_SQL)
			if "link" not in cols:
				conn.execute(ALTER_ADD_LINK_SQL)
			if "user_username" not in cols:
				conn.execute(ALTER_ADD_USERUSERNAME_SQL)
			if "user_full_name" not in cols:
				conn.execute(ALTER_ADD_USERFULLNAME_SQL)
			if "custom_text" not in cols:
				conn.execute(ALTER_ADD_CUSTOMTEXT_SQL)

		conn.execute(CREATE_INDEX_USER)
		try:
			conn.execute(CREATE_INDEX_CHAT)
		except sqlite3.OperationalError:
			pass
		conn.execute(CREATE_INDEX_CREATED)
		conn.execute(CREATE_UNIQUE_DAY_SQL)
		conn.executescript(CREATE_ALLOWED_SQL)
		conn.commit()
	finally:
		conn.close()


def saveImageSync(
		userId: int,
		chatId: int,
		displayName: str,
		fileId: str,
		dayKey: str,
		link: str | None,
		userUsername: str | None,
		userFullName: str | None,
		customText: str | None
):
	logger.debug(f"Saving image for user {userId}, day {dayKey}")
	ts = datetime.now(timezone.utc).isoformat()
	conn = openConn()
	try:
		conn.execute("BEGIN IMMEDIATE;")
		conn.execute(INSERT_IMAGE_SQL,
					 (userId, chatId, displayName, fileId, ts, dayKey, link, userUsername, userFullName, customText))
		conn.commit()
		logger.info(f"Successfully saved image for user {userId}")
	except sqlite3.IntegrityError:
		logger.warning(f"User {userId} already has image for day {dayKey}")
		conn.rollback()
		raise
	finally:
		conn.close()


def deleteImagesByDateRangeSync(startIso: str, endIso: str) -> int:
	conn = openConn()
	try:
		cur = conn.execute(DELETE_IMAGES_BY_DATE_RANGE_SQL, (startIso, endIso))
		conn.commit()
		count = cur.rowcount
		logger.info(f"Deleted {count} images from date range {startIso} to {endIso}")
		return count
	finally:
		conn.close()


def deleteImagesByUserAndDateSync(userId: int, startIso: str, endIso: str) -> int:
	conn = openConn()
	try:
		cur = conn.execute(DELETE_IMAGES_BY_USER_AND_DATE_SQL, (userId, startIso, endIso))
		conn.commit()
		count = cur.rowcount
		logger.info(f"Deleted {count} images for user {userId} from date range {startIso} to {endIso}")
		return count
	finally:
		conn.close()


def getOtherImagesTodaySync(
		excludeUserId: int,
		startIso: str,
		endIso: str,
		limit: int = 10
) -> list[tuple[str, str, str | None, str | None, str | None, str | None, str]]:
	conn = openConn()
	try:
		cur = conn.execute(SELECT_OTHERS_TODAY_SQL, (excludeUserId, startIso, endIso))
		rows = cur.fetchall()
		out = []
		for r in rows[:limit]:
			file_id, author_display, link, uusername, ufullname, custom_text, created_at = r
			out.append((file_id, author_display, link, uusername, ufullname, custom_text, created_at))
		return out
	finally:
		conn.close()


def getRecipientChatsTodaySync(excludeUserId: int, startIso: str, endIso: str) -> list[int]:
	conn = openConn()
	try:
		cur = conn.execute(SELECT_TODAY_RECIPIENTS_SQL, (excludeUserId, startIso, endIso))
		return [r[0] for r in cur.fetchall() if r[0] is not None]
	finally:
		conn.close()


def getAllUserChatIdsSync() -> list[int]:
	conn = openConn()
	try:
		cur = conn.execute(SELECT_ALL_USER_CHATS_SQL)
		return [r[0] for r in cur.fetchall() if r[0] is not None]
	finally:
		conn.close()


def resetDbSync():
	conn = openConn()
	try:
		conn.execute(DELETE_IMAGES_SQL)
		conn.execute("VACUUM")
		conn.commit()
		logger.info("Database images cleared successfully")
	finally:
		conn.close()


def allowUserSync(userId: int) -> bool:
	ts = datetime.now(timezone.utc).isoformat()
	conn = openConn()
	try:
		cur = conn.execute("INSERT OR IGNORE INTO allowed_users (user_id, added_at) VALUES (?, ?);", (userId, ts))
		conn.commit()
		inserted = cur.rowcount > 0
		if inserted:
			logger.info(f"User {userId} added to allowed list")
		else:
			logger.info(f"User {userId} was already in allowed list")
		return inserted
	finally:
		conn.close()


def denyUserSync(userId: int) -> bool:
	conn = openConn()
	try:
		cur = conn.execute("DELETE FROM allowed_users WHERE user_id = ?;", (userId,))
		conn.commit()
		deleted = cur.rowcount > 0
		if deleted:
			logger.info(f"User {userId} removed from allowed list")
		else:
			logger.info(f"User {userId} was not in allowed list")
		return deleted
	finally:
		conn.close()


def isAllowedSync(userId: int) -> bool:
	conn = openConn()
	try:
		cur = conn.execute("SELECT 1 FROM allowed_users WHERE user_id = ? LIMIT 1;", (userId,))
		result = cur.fetchone() is not None
		logger.debug(f"User {userId} allowed check: {result}")
		return result
	finally:
		conn.close()


def listAllowedSync() -> list[int]:
	conn = openConn()
	try:
		cur = conn.execute("SELECT user_id FROM allowed_users ORDER BY user_id;")
		out = []
		for r in cur.fetchall():
			v = r[0]
			if v is None:
				continue
			try:
				out.append(int(v))
			except Exception:
				continue
		logger.debug(f"Retrieved {len(out)} allowed users")
		return out
	finally:
		conn.close()


def listAllowedDetailedSync() -> list[tuple[int, str | None, str | None]]:
	conn = openConn()
	try:
		cur = conn.execute(SELECT_ALLOWED_DETAILED_SQL)
		rows = cur.fetchall()
		out = []
		for uid, uusername, ufullname in rows:
			out.append((int(uid), uusername or None, ufullname or None))
		logger.debug(f"Retrieved {len(out)} detailed allowed users")
		return out
	finally:
		conn.close()


async def ensureSchema():
	await asyncio.to_thread(ensureSchemaSync)


async def saveImage(
		userId: int,
		chatId: int,
		displayName: str,
		fileId: str,
		dayKey: str,
		link: str | None,
		userUsername: str | None,
		userFullName: str | None,
		customText: str | None
):
	await asyncio.to_thread(saveImageSync, userId, chatId, displayName, fileId, dayKey, link, userUsername,
							userFullName, customText)


async def deleteImagesByDateRange(startIso: str, endIso: str) -> int:
	return await asyncio.to_thread(deleteImagesByDateRangeSync, startIso, endIso)


async def deleteImagesByUserAndDate(userId: int, startIso: str, endIso: str) -> int:
	return await asyncio.to_thread(deleteImagesByUserAndDateSync, userId, startIso, endIso)


async def getOtherImagesToday(excludeUserId: int, startIso: str, endIso: str, limit: int = 10):
	return await asyncio.to_thread(getOtherImagesTodaySync, excludeUserId, startIso, endIso, limit)


async def getRecipientChatsToday(excludeUserId: int, startIso: str, endIso: str):
	return await asyncio.to_thread(getRecipientChatsTodaySync, excludeUserId, startIso, endIso)


async def getAllUserChatIds() -> list[int]:
	return await asyncio.to_thread(getAllUserChatIdsSync)


async def resetDb():
	await asyncio.to_thread(resetDbSync)


async def allowUser(userId: int) -> bool:
	return await asyncio.to_thread(allowUserSync, userId)


async def denyUser(userId: int) -> bool:
	return await asyncio.to_thread(denyUserSync, userId)


async def isAllowed(userId: int) -> bool:
	return await asyncio.to_thread(isAllowedSync, userId)


async def listAllowed() -> list[int]:
	return await asyncio.to_thread(listAllowedSync)


async def listAllowedDetailed() -> list[tuple[int, str | None, str | None]]:
	return await asyncio.to_thread(listAllowedDetailedSync)

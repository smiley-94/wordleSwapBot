from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

ROME_TZ = ZoneInfo("Europe/Rome")

def romeDayBoundsUtc(nowUtc: datetime | None = None) -> tuple[datetime, datetime]:
    if nowUtc is None:
        nowUtc = datetime.now(timezone.utc)
    nowRome = nowUtc.astimezone(ROME_TZ)
    startRome = datetime.combine(nowRome.date(), time.min, tzinfo=ROME_TZ)
    endRome = startRome + timedelta(days=1)
    return startRome.astimezone(timezone.utc), endRome.astimezone(timezone.utc)

def romeDayKey(nowUtc: datetime | None = None) -> str:
    if nowUtc is None:
        nowUtc = datetime.now(timezone.utc)
    return nowUtc.astimezone(ROME_TZ).date().isoformat()

def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")

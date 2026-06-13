"""Date normalization with a per-matter default timezone.

Dates that carry an explicit timezone (e.g. RFC 5322 "+0800") are converted to UTC
unchanged. Dates with no timezone (common in quoted "On ... wrote:" headers and some
Outlook fields) are interpreted in the matter's default timezone before conversion,
so the chronology orders and displays them correctly.
"""

import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Optional, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TZ_ABBREVIATIONS = {
    "SGT": timezone(timedelta(hours=8)),
}

CHINESE_MONTHS = {
    "\u4e00\u6708": 1,
    "\u4e8c\u6708": 2,
    "\u4e09\u6708": 3,
    "\u56db\u6708": 4,
    "\u4e94\u6708": 5,
    "\u516d\u6708": 6,
    "\u4e03\u6708": 7,
    "\u516b\u6708": 8,
    "\u4e5d\u6708": 9,
    "\u5341\u6708": 10,
    "\u5341\u4e00\u6708": 11,
    "\u5341\u4e8c\u6708": 12,
}

# Informal date formats seen in quoted "On ... wrote:" headers (Gmail and similar),
# which are not valid RFC 5322 and so are rejected by parsedate_to_datetime.
INFORMAL_DATE_FORMATS = (
    "%a, %b %d, %Y, %I:%M %p",
    "%a, %b %d, %Y at %I:%M %p",
    "%a, %b %d, %Y %I:%M %p",
    "%A, %B %d, %Y, %I:%M %p",
    "%A, %B %d, %Y at %I:%M %p",
    "%A, %B %d, %Y %I:%M:%S %p",
    "%A, %B %d, %Y %I:%M %p",
    "%A, %d %B %Y at %I:%M %p",
    "%A, %d %B %Y %I:%M %p",
    "%A, %d %B %Y at %H:%M",
    "%A, %d %B %Y %H:%M",
    "%b %d, %Y, %I:%M %p",
    "%b %d, %Y at %I:%M %p",
    "%b %d, %Y %I:%M %p",
    "%B %d, %Y, %I:%M %p",
    "%B %d, %Y at %I:%M %p",
    "%B %d, %Y %I:%M:%S %p",
    "%B %d, %Y %I:%M %p",
    "%d %B %Y at %I:%M:%S %p",
    "%d %B %Y at %I:%M %p",
    "%d %B %Y %I:%M:%S %p",
    "%d %B %Y %I:%M %p",
    "%m/%d/%Y %I:%M %p",
    "%d/%m/%Y %H:%M",
    "%d/%m/%y %H:%M",
    "%m/%d/%Y %H:%M",
    "%m/%d/%y %H:%M",
    "%d/%m/%y %I:%M %p",
    "%m/%d/%y %I:%M %p",
    "%a %d %b %Y %H:%M",
    "%A %d %B %Y %H:%M",
    "%d %b %Y %H:%M",
    "%d %B %Y %H:%M",
)


def resolve_zone(default_tz: Optional[str]) -> ZoneInfo:
    if not default_tz:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(default_tz)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def is_valid_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def coerce_datetime(value: Union[str, datetime, None]) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    localized = parse_localized_datetime(text)
    if localized:
        return localized
    tzinfo = trailing_timezone(text)
    if tzinfo:
        without_tz = re.sub(r"\s+[A-Z]{2,5}$", "", text).strip()
        parsed_without_tz = coerce_datetime(without_tz)
        if parsed_without_tz:
            return parsed_without_tz.replace(tzinfo=tzinfo) if parsed_without_tz.tzinfo is None else parsed_without_tz
    try:
        return parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError, OverflowError):
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    cleaned = " ".join(text.split())
    for fmt in INFORMAL_DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def trailing_timezone(text: str) -> Optional[timezone]:
    match = re.search(r"\s+([A-Z]{2,5})$", text.strip())
    if not match:
        return None
    return TZ_ABBREVIATIONS.get(match.group(1))


def parse_localized_datetime(text: str) -> Optional[datetime]:
    cleaned = normalize_localized_text(text)
    parsed = parse_chinese_numeric_datetime(cleaned)
    if parsed:
        return parsed
    return parse_chinese_month_name_datetime(cleaned)


def normalize_localized_text(text: str) -> str:
    return " ".join(text.replace("\u3000", " ").replace("\u202f", " ").split())


def parse_chinese_numeric_datetime(text: str) -> Optional[datetime]:
    match = re.search(
        r"(?P<year>\d{4})\s*\u5e74\s*(?P<month>\d{1,2})\s*\u6708\s*(?P<day>\d{1,2})\s*\u65e5"
        r"(?:\s*\([^)]*\)|\s*\u5468.)?\s*"
        r"(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?\s*(?P<ampm>\u4e0a\u5348|\u4e0b\u5348)?",
        text,
    )
    if not match:
        return None
    return build_datetime_from_match(match, int(match.group("month")))


def parse_chinese_month_name_datetime(text: str) -> Optional[datetime]:
    month_names = "|".join(sorted(map(re.escape, CHINESE_MONTHS), key=len, reverse=True))
    match = re.search(
        rf"(?:\u661f\u671f.|\u5468.)?,?\s*(?P<month_name>{month_names})\s+"
        r"(?P<day>\d{1,2}),\s*(?P<year>\d{4})\s+"
        r"(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?\s*(?P<ampm>\u4e0a\u5348|\u4e0b\u5348)?",
        text,
    )
    if not match:
        return None
    return build_datetime_from_match(match, CHINESE_MONTHS[match.group("month_name")])


def build_datetime_from_match(match: re.Match, month: int) -> datetime:
    hour = int(match.group("hour"))
    ampm = match.group("ampm")
    if ampm == "\u4e0b\u5348" and hour < 12:
        hour += 12
    elif ampm == "\u4e0a\u5348" and hour == 12:
        hour = 0
    return datetime(
        int(match.group("year")),
        month,
        int(match.group("day")),
        hour,
        int(match.group("minute")),
        int(match.group("second") or 0),
    )


def to_utc(value: Union[str, datetime, None], default_tz: str = "UTC") -> Optional[str]:
    """Return an ISO-8601 UTC string, or None if the value can't be parsed.

    Naive datetimes are interpreted in ``default_tz``; tz-aware ones keep their offset.
    """
    parsed = coerce_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=resolve_zone(default_tz))
    return parsed.astimezone(timezone.utc).isoformat()

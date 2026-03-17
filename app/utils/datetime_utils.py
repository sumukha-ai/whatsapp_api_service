"""Datetime helpers for consistent IST timestamps across the application."""
from datetime import datetime, timedelta, timezone


IST_TIMEZONE = timezone(timedelta(hours=5, minutes=30))


def ist_now():
    """Return current IST time as a naive datetime for DB compatibility."""
    return datetime.now(IST_TIMEZONE).replace(tzinfo=None)


def ist_from_unix(timestamp_value):
    """Convert a Unix timestamp (UTC epoch seconds) to naive IST datetime."""
    return datetime.fromtimestamp(int(timestamp_value), tz=timezone.utc).astimezone(IST_TIMEZONE).replace(tzinfo=None)

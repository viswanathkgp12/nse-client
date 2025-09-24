from datetime import date
import time


def to_epoch(dt: date) -> int:
    """Convert a datetime object to epoch timestamp in seconds."""
    return int(time.mktime(dt.timetuple()))

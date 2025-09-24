from datetime import date, datetime
import time


def to_epoch(dt: date) -> int:
    return int(time.mktime(dt.timetuple()))


def from_business_dt(dt_str):
    return datetime.strptime(dt_str, "%B %d, %Y")

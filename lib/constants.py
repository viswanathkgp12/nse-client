from enum import StrEnum


class ChartInterval(StrEnum):
    FIFTEEN_MINUTES = "15m"
    ONE_HOUR = "1h"
    FOUR_HOURS = "4h"
    ONE_DAY = "1d"
    ONE_WEEK = "1w"


# Constants
FIVE_AND_HALF_HOURS_IN_SECS = 19800

BASE_URL = "https://charting.nseindia.com"
CHART_DATA_URL = f"{BASE_URL}/Charts/symbolhistoricaldata/"

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/118.0",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
}

CHART_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Content-Type": "application/json; charset=utf-8",
    "Origin": BASE_URL,
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Connection": "keep-alive",
    "DNT": "1",
    "Sec-GPC": "1",
    "TE": "trailers",
}

INDEX_CSV_URLS = {
    "small_cap_250": "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",
    "mid_cap_150": "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
    "mid_small_cap_400": "https://nsearchives.nseindia.com/content/indices/ind_niftymidsmallcap400list.csv",
}

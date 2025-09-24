import asyncio
import json
import logging
import os
from datetime import date
from typing import Optional
from urllib.parse import quote_plus

from tenacity import (
    AsyncRetrying,
    stop_after_attempt,
    wait_fixed,
)
from nse_client.gateways.types import CandleData, CandleDataList, EarningResult

from nse_client.constants import (
    CHART_DATA_URL,
    CHART_HEADERS,
    FIVE_AND_HALF_HOURS_IN_SECS,
    ChartInterval,
    NSE_HEADERS,
)
from nse_client.gateways.angel import AngelBrokingGateway
from nse_client.gateways.moneycontrol import MoneyControlGateway
from nse_client.http_client import HttpClient
from nse_client.util import to_epoch

logger = logging.getLogger(__name__)


class NseClient(HttpClient):
    async def initialize_session(self):
        await self.get("https://www.nseindia.com/option-chain", mode="str")


class NseGateway:
    def __init__(self):
        self.angel = AngelBrokingGateway()
        self.moneycontrol = MoneyControlGateway()
        self.client = NseClient(headers=NSE_HEADERS)
        self.nse_scrip_codes = {}

        self.nse_indices = set()
        self.nse_fno_stocks = set()

    async def __aenter__(self):
        await self.fetch_scrips()
        await self.client.initialize_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.moneycontrol.client.close()
        await self.client.close()

    async def fetch_scrips(self, force=False):
        angel_data_path = os.path.join(os.path.dirname(__file__), "angel-data.json")
        if not os.path.exists(angel_data_path) or force:
            data = await self.angel.list_instruments()
            with open(angel_data_path, "w") as f:
                f.write(json.dumps(data))
        else:
            with open(angel_data_path, "r") as f:
                data = json.loads(f.read().encode())

        for each in data:
            exchange = each["exch_seg"]
            name = each["name"]
            token = each["token"]
            instrument_type = each["instrumenttype"]

            if exchange == "NFO" and instrument_type == "OPTSTK":
                self.nse_fno_stocks.add(name)
            elif exchange == "NSE":
                self.nse_scrip_codes[name] = token
                if instrument_type == "AMXIDX":
                    self.nse_indices.add(name)
            continue

    def fno_stocks(self):
        return list(self.nse_fno_stocks)

    def indices(self):
        return list(self.nse_indices)

    async def symbols_by_index(self, symbol: str):
        if symbol not in self.nse_indices:
            raise ValueError(f"{symbol} not an index!!!")

        orig = symbol
        symbol = quote_plus(symbol)
        data = await self.client.get(
            f"https://www.nseindia.com/api/equity-stockIndices?index={symbol}"
        )
        symbols = [s["symbol"] for s in data["data"]]
        filtered_symbols = [s for s in symbols if s != orig]
        return filtered_symbols

    async def price_band(self, symbol: str) -> str:
        """Get the price band for a given symbol."""
        symbol = quote_plus(symbol)
        data = await self.client.get(
            f"https://www.nseindia.com/api/quote-equity?symbol={symbol}"
        )
        return data["priceInfo"]["pPriceBand"]

    async def recent_earnings(self) -> list[EarningResult]:
        return await self.moneycontrol.earnings()

    async def insider_trades(self, symbol: str) -> list[dict]:
        """Get insider trading data for a given symbol."""
        symbol = quote_plus(symbol)
        data = await self.client.get(
            f"https://www.nseindia.com/api/corp-info?symbol={symbol}&corpType=insidertrading"
        )
        return [
            {
                "type": record.get("tdpTransactionType", ""),
                "quantity": record.get("secAcq", 0),
                "date": record.get("date", ""),
            }
            for record in data
        ]

    async def industry(self, symbol: str) -> Optional[str]:
        symbol = quote_plus(symbol)
        data = await self.client.get(
            f"https://www.nseindia.com/api/equity-meta-info?symbol={symbol}"
        )
        if data.get("isETFSec", False):
            logger.warning(f"ETF {symbol} does not have an industry")
            return None
        return data["industry"]

    async def candle(
        self,
        symbol: str,
        interval: ChartInterval,
        from_dt: date,
        to_dt: date,
    ) -> CandleData:
        nse_interval, chart_period = self._get_interval(interval)
        scrip_code = self.nse_scrip_codes.get(symbol)
        if not scrip_code:
            raise ValueError(f"{symbol} invalid")

        payload = {
            "exch": "N",
            "fromDate": to_epoch(from_dt) + FIVE_AND_HALF_HOURS_IN_SECS,
            "toDate": to_epoch(to_dt) + FIVE_AND_HALF_HOURS_IN_SECS,
            "timeInterval": nse_interval,
            "chartPeriod": chart_period,
            "chartStart": 0,
            "instrType": "C",
            "scripCode": scrip_code,
            "ulToken": scrip_code,
        }

        success, data = await self._scrape_chart_interval_data(
            symbol,
            payload,
            CHART_DATA_URL,
            interval,
        )
        if not success:
            raise Exception(f"Failed to fetch candle data for {symbol}")
        return data

    @staticmethod
    def _get_interval(interval: ChartInterval) -> tuple[int, str]:
        """Map ChartInterval to NSE-specific interval and chart period."""
        interval_map = {
            ChartInterval.FIFTEEN_MINUTES: (15, "I"),
            ChartInterval.ONE_HOUR: (60, "I"),
            ChartInterval.FOUR_HOURS: (240, "I"),
            ChartInterval.ONE_DAY: (1, "D"),
            ChartInterval.ONE_WEEK: (1, "W"),
        }
        if interval not in interval_map:
            raise ValueError(
                f"Invalid interval {interval}. Allowed values: {list(interval_map.keys())}"
            )
        return interval_map[interval]

    async def _scrape_chart_interval_data(
        self,
        symbol: str,
        payload: dict,
        url: str,
        interval: ChartInterval,
    ) -> tuple[bool, Optional[dict]]:
        data = await self.client.post(url, payload, headers=CHART_HEADERS)
        if isinstance(data, str):
            logger.debug(f"[{interval}] Failed data fetch for {symbol} with {data}")
            return False, None

        if data.get("s") == "Ok":
            return True, data
        logger.debug(f"[{interval}] Failed data fetch for {symbol} with {data}")
        return False, None

    async def candles(
        self,
        symbols: list[str],
        interval: ChartInterval,
        from_dt: date,
        to_dt: date,
        max_concurrent_requests: int = 25,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> CandleDataList:
        semaphore = asyncio.Semaphore(max_concurrent_requests)

        async def _fetch(symbol: str):
            try:
                async for attempt in AsyncRetrying(
                    stop=stop_after_attempt(max_retries),
                    wait=wait_fixed(retry_delay),
                    reraise=True,
                ):
                    with attempt:
                        async with semaphore:
                            data: CandleData = await self.candle(
                                symbol, interval, from_dt, to_dt
                            )
                            if data is None:
                                raise ConnectionError(f"No data received for {symbol}")
                            return symbol, data
            except Exception as e:
                logger.warning(
                    f"[{interval}] Failed to get data for {symbol} after {max_retries} retries: {e}"
                )
                return symbol, None

        tasks = [_fetch(symbol) for symbol in symbols]
        fetched_results = await asyncio.gather(*tasks)

        responses = []
        failed_names = []
        for symbol, data in fetched_results:
            if data is None:
                failed_names.append(symbol)
                continue
            responses.append({"symbol": symbol, "data": data})

        return {
            "failed": failed_names,
            "results": responses,
        }

import asyncio
import logging
import pandas as pd
import io
from typing import Dict, Set
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
    CHARTING_BASE_URL,
    CHART_DATA_URL,
    CHART_HEADERS,
    FIVE_AND_HALF_HOURS_IN_SECS,
    ChartInterval,
    NSE_HEADERS,
    NSE_BASE_URL,
)
from nse_client.gateways.angel import AngelBrokingGateway
from nse_client.gateways.moneycontrol import MoneyControlGateway
from nse_client.http_client import HttpClient
from nse_client.scrip_fetcher import ScripFetcher
from nse_client.util import to_epoch

logger = logging.getLogger(__name__)


class NseClient(HttpClient):
    async def initialize_session(self):
        await self.get("/option-chain", mode="str")


class NseGateway:
    def __init__(self):
        self._angel = AngelBrokingGateway()
        self._moneycontrol = MoneyControlGateway()
        self._scrip_fetcher = ScripFetcher(angel=self._angel)
        self._client = NseClient(base_url=NSE_BASE_URL, headers=NSE_HEADERS)

        self.nse_scrip_codes: Dict[str, str] = {}
        self._nse_indices: Set[str] = set()

    async def __aenter__(self):
        await self._scrip_fetcher.fetch()
        await self._client.initialize_session()
        await self.scrip_codes()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._moneycontrol.client.close()
        await self._client.close()

    async def fno_stocks(self):
        return self._scrip_fetcher.nse_fno_stocks

    async def scrip_codes(self):
        fno_data = await self._client.get(
            f"{CHARTING_BASE_URL}/Charts/GetFOMasters", mode="str"
        )
        eq_data = await self._client.get(
            f"{CHARTING_BASE_URL}/Charts/GetEQMasters", mode="str"
        )

        self._process_scrips(self._to_dict(fno_data))
        self._process_scrips(self._to_dict(eq_data))

    def _process_scrips(self, data: dict) -> None:
        for name, data in data.items():
            scrip = data.get("scrip_code")
            desc = data.get("desc")
            if 26_000 <= int(scrip) <= 26_500:
                desc = desc.upper()
                self.nse_scrip_codes[desc] = scrip
                self._nse_indices.add(desc)
                continue

            name = name.upper()
            if "-EQ" in name:
                name = name.replace("-EQ", "")
                self.nse_scrip_codes[name] = scrip

    @staticmethod
    def _to_dict(data):
        df = pd.read_csv(io.StringIO(data), sep="|")
        df_result = df[["TradingSymbol", "ScripCode", "Description"]]
        return (
            df_result.set_index("TradingSymbol")
            .apply(
                lambda row: {
                    "scrip_code": row["ScripCode"],
                    "desc": row["Description"],
                },
                axis=1,
            )
            .to_dict()
        )

    async def etf(self):
        data = await self._client.get("/api/etf")
        return [s["symbol"] for s in data["data"]]

    async def indices(self):
        return list(self._nse_indices)

    async def intraday_stocks(self):
        return self._scrip_fetcher.nse_intraday_stocks

    async def symbols_by_index(self, symbol: str):
        if symbol not in self._nse_indices:
            raise ValueError(f"{symbol} not an index!!!")

        orig = symbol.upper()
        symbol = quote_plus(symbol)
        data = await self._client.get(f"/api/equity-stockIndices?index={symbol}")
        symbols = [s["symbol"] for s in data["data"]]
        filtered_symbols = [s for s in symbols if s != orig]
        return filtered_symbols

    async def price_band(self, symbol: str) -> str:
        """Get the price band for a given symbol."""
        symbol = quote_plus(symbol)
        data = await self._client.get(f"/api/quote-equity?symbol={symbol}")
        return data["priceInfo"]["pPriceBand"]

    async def recent_earnings(self) -> list[EarningResult]:
        return await self._moneycontrol.earnings()

    async def insider_trades(self, symbol: str) -> list[dict]:
        """Get insider trading data for a given symbol."""
        symbol = quote_plus(symbol)
        data = await self._client.get(
            f"/api/corp-info?symbol={symbol}&corpType=insidertrading"
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
        data = await self._client.get(f"/api/equity-meta-info?symbol={symbol}")
        if data.get("isETFSec", False):
            logger.warning(f"ETF {symbol} does not have an industry")
            return None
        if "industry" not in data:
            logger.warning(f"{symbol} does not have an industry")
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
        data = await self._client.post(url, payload, headers=CHART_HEADERS)
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
        batch_size: int = 25,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        sleep_delay: float = 0.25,
    ) -> CandleDataList:
        all_results = []
        failed_names = []

        # Process symbols in batches
        for i in range(0, len(symbols), batch_size):
            batch_symbols = symbols[i : i + batch_size]
            logger.info(f"Processing symbols from {i} to {i + batch_size}...")

            async def _fetch(symbol: str):
                try:
                    async for attempt in AsyncRetrying(
                        stop=stop_after_attempt(max_retries),
                        wait=wait_fixed(retry_delay),
                        reraise=True,
                    ):
                        with attempt:
                            data: CandleData = await self.candle(
                                symbol, interval, from_dt, to_dt
                            )
                            if data is None:
                                raise ConnectionError(f"No data received for {symbol}")
                            return symbol, data
                except Exception as e:
                    logging.warning(
                        f"[{interval}] Failed to get data for {symbol} after {max_retries} retries: {e}"
                    )
                    return symbol, None

            tasks = [_fetch(symbol) for symbol in batch_symbols]
            fetched_results = await asyncio.gather(*tasks)

            for symbol, data in fetched_results:
                if data is None:
                    failed_names.append(symbol)
                    continue
                all_results.append({"symbol": symbol, "data": data})

            if i + batch_size < len(symbols):
                await asyncio.sleep(sleep_delay)

        return {
            "failed": failed_names,
            "results": all_results,
        }

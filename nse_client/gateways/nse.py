import asyncio
import json
import logging
import pandas as pd
import io
from typing import Dict, Set
from datetime import date, datetime, timedelta
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
        self._client = NseClient(
            base_url=NSE_BASE_URL,
            headers=NSE_HEADERS,
            timeout=30,
        )

        self.nse_scrip_codes: Dict[str, str] = {}
        self._nse_indices: Set[str] = set()
        self.nse_scrip_exchange: Dict[str, str] = {}

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
        all_data = await self._client.post(
            f"{CHARTING_BASE_URL}/v1/exchanges/allSymbols",
            {},
            mode="str",
        )
        json_data = json.loads(all_data)
        self._process_scrips(json_data["data"])

    def _process_scrips(self, res: list[dict]) -> None:
        for data in res:
            scrip = data.get("scripcode")
            symbol = data.get("symbol")
            if 26_000 <= int(scrip) <= 26_500:
                symbol = symbol.upper()
                self.nse_scrip_codes[symbol] = scrip
                self._nse_indices.add(symbol)
                continue

            name = data.get("symbol")
            name = name.upper()
            if "-EQ" in name:
                name = name.replace("-EQ", "")
                self.nse_scrip_codes[name] = scrip
                self.nse_scrip_exchange[name] = "EQ"
            if "-BE" in name:
                name = name.replace("-BE", "")
                self.nse_scrip_exchange[name] = "BE"

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
        data = await self._client.get(
            f"/api/NextApi/apiClient/indexTrackerApi?functionName=getAllIndicesSymbols&index={symbol}"
        )
        symbols = data["data"]
        filtered_symbols = [s for s in symbols if s != orig]
        return filtered_symbols

    async def price_band(self, symbol: str) -> Optional[int]:
        """Get the price band for a given symbol."""
        equity_response = await self._equity_response(symbol)
        price_info = (
            equity_response[0].get("priceInfo")
            if isinstance(equity_response[0], dict)
            else None
        )
        if not price_info:
            return None
        band = price_info["ppriceBand"]
        if band and band != "No Band":
            return int(band)
        return 20

    async def _equity_response(self, symbol: str):
        symbol = quote_plus(symbol)
        exchange = self.nse_scrip_exchange.get(symbol, "EQ")
        data = await self._client.get(
            f"/api/NextApi/apiClient/GetQuoteApi?functionName=getSymbolData&marketType=N&series={exchange}&symbol={symbol}"
        )
        if "equityResponse" not in data:
            logger.warning(f"{symbol} does not have equity info")
            return None
        equity_response = data["equityResponse"]
        if not equity_response:
            logger.warning(f"{symbol} does not have equity info")
            return None
        return equity_response

    async def ipo(self, days_to_lookback=270) -> list[EarningResult]:
        current_ipo = await self._client.get(f"/api/ipo-current-issue")
        symbols = [c["symbol"] for c in current_ipo if c["series"] == "EQ"]

        to_date = datetime.now()
        from_date = to_date - timedelta(days_to_lookback)
        past_ipo = await self._client.get(
            f"/api/public-past-issues",
            params={
                "from_date": from_date.strftime("%d-%m-%Y"),
                "to_date": to_date.strftime("%d-%m-%Y"),
            },
        )
        symbols.extend([c["symbol"] for c in past_ipo if c["securityType"] == "EQ"])
        return symbols

    async def recent_earnings(self) -> list[str]:
        return await self._moneycontrol.earnings()

    async def price_band_changes(self, days_to_lookback=30) -> list[dict]:
        today = datetime.now()
        end_dt = today.strftime("%d-%m-%Y")
        start_dt = (today - timedelta(days=days_to_lookback)).strftime("%d-%m-%Y")
        data = await self._client.get(
            f"api/eqsurvactions?from_date={start_dt}&to_date={end_dt}"
        )
        changes = []
        for item in data:
            from_price_band = item["fromPriceBand"]
            to_price_band = item["toPriceBand"]
            if from_price_band is None or from_price_band == "No Band":
                from_price_band = 0
            if to_price_band is None or to_price_band == "No Band":
                to_price_band = 0

            change = {
                "symbol": item["symbol"],
                "effectiveDate": item["effectiveDate"],
                "fromPriceBand": int(from_price_band),
                "toPriceBand": int(to_price_band),
                "change": int(to_price_band) - int(from_price_band),
            }
            changes.append(change)
        return changes

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

    async def industry(self, symbol: str) -> Optional[dict]:
        equity_response = await self._equity_response(symbol)
        sec_info = (
            equity_response[0].get("secInfo")
            if isinstance(equity_response[0], dict)
            else None
        )
        if (
            not sec_info
            or "basicIndustry" not in sec_info
            or "industryInfo" not in sec_info
            or "sector" not in sec_info
        ):
            logger.warning(f"{symbol} does not have an industry")
            return None
        return {
            "subIndustry": sec_info["basicIndustry"],
            "industry": sec_info["industryInfo"],
            "sector": sec_info["sector"],
        }

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

        exchange = self.nse_scrip_exchange.get(symbol, "EQ")
        payload = {
            "chartType": chart_period,
            "fromDate": to_epoch(from_dt) + FIVE_AND_HALF_HOURS_IN_SECS,
            "symbol": symbol + f"-{exchange}",
            "symbolType": "Equity",
            "toDate": to_epoch(to_dt) + FIVE_AND_HALF_HOURS_IN_SECS,
            "token": str(scrip_code),
            "timeInterval": nse_interval,
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
            ChartInterval.FIVE_MINUTES: (5, "I"),
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
        data = await self._client.get(url, payload, headers=CHART_HEADERS)
        if isinstance(data, str):
            logger.debug(f"[{interval}] Failed data fetch for {symbol} with {data}")
            return False, None

        if data.get("status"):
            return True, self._transform_dict(data.get("data", {}))
        logger.debug(f"[{interval}] Failed data fetch for {symbol} with {data}")
        return False, None

    def _transform_dict(self, data_list):
        """
        Renames dictionary keys to o, h, l, c, v, t.
        """
        return [
            {
                "o": d["open"],
                "h": d["high"],
                "l": d["low"],
                "c": d["close"],
                "v": d["volume"],
                "t": d["time"],
            }
            for d in data_list
        ]

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
            logger.info(
                f"[{interval}] Processing symbols from {i} to {i + batch_size}..."
            )

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

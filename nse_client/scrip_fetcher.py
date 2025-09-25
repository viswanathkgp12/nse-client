import os
import json
from datetime import datetime
from typing import Dict, List, Set

from nse_client.gateways.angel import AngelBrokingGateway


class ScripFetcher:
    """
    This uses Angel Broking Gateway to get all stocks with tokens in one-go
    Angel broking data has NSE/BSE/MCX etc.

    Filter out only for NSE intraday/fno/indices

    NOTE: Data is cached in JSON file.
          Force-fetched every 1 day to accommodate for price band changes/newly listed stocks
    """

    def __init__(self, angel: AngelBrokingGateway):
        self._angel = angel

        self.nse_scrip_codes: Dict[str, str] = {}
        self._nse_fno_stocks: Set[str] = set()
        self._nse_indices: Set[str] = set()
        self._nse_intraday_stocks: Set[str] = set()

        self._base_path = os.path.dirname(__file__)
        self._angel_data_path = os.path.join(self._base_path, "angel-data.json")
        self._last_refresh_path = os.path.join(
            self._base_path, "angel-data-refresh-dt.json"
        )

    async def fetch(self) -> None:
        if self._should_refresh_data():
            data = await self._fetch_and_cache_data()
        else:
            data = await self._load_cached_data()
        self._process_scrips(data)

    def _should_refresh_data(self) -> bool:
        if not os.path.exists(self._last_refresh_path) or not os.path.exists(
            self._angel_data_path
        ):
            return True

        try:
            with open(self._last_refresh_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                last_refresh = datetime.fromisoformat(data["last_refresh_at"])
                return (datetime.now() - last_refresh).days > 1
        except (json.JSONDecodeError, KeyError, ValueError):
            return True

    async def _fetch_and_cache_data(self):
        """Fetch data from Angel Broking and cache it."""
        try:
            data = await self._angel.list_instruments()
            self._save_json(self._angel_data_path, data)
            self._save_json(
                self._last_refresh_path,
                {"last_refresh_at": datetime.now().isoformat()},
            )
            return data
        except Exception as e:
            raise RuntimeError(f"Failed to fetch or cache data: {e}") from e

    async def _load_cached_data(self) -> List[Dict]:
        try:
            with open(self._angel_data_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            raise RuntimeError(f"Failed to load cached data: {e}") from e

    def _save_json(self, path: str, data: Dict) -> None:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except IOError as e:
            raise RuntimeError(f"Failed to save JSON to {path}: {e}") from e

    def _process_scrips(self, data: List[Dict]) -> None:
        for scrip in data:
            exchange = scrip.get("exch_seg")
            name = scrip.get("name")
            token = scrip.get("token")
            symbol = scrip.get("symbol", "")
            instrument_type = scrip.get("instrumenttype")

            if not all([exchange, name, token]):
                continue

            if exchange == "NFO" and instrument_type == "OPTSTK":
                self._nse_fno_stocks.add(name)
            elif exchange == "NSE":
                self.nse_scrip_codes[name] = token
                if instrument_type == "AMXIDX":
                    self._nse_indices.add(name)
                if "-EQ" in symbol:
                    self._nse_intraday_stocks.add(name)

    @property
    def nse_fno_stocks(self):
        return list(self._nse_fno_stocks)

    @property
    def nse_indices(self):
        return list(self._nse_indices)

    @property
    def nse_intraday_stocks(self):
        return list(self._nse_intraday_stocks)

from nse_client.util import from_business_dt

from nse_client.http_client import HttpClient
import asyncio


class MoneyControlGateway:
    default_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"
    }

    def __init__(self):
        self.client = HttpClient(headers=self.default_headers)

    async def earnings(self):
        url = "https://api.moneycontrol.com/mcapi/v1/earnings/rapid-results?limit=100&page=1&type=LR&subType=yoy&category=all&sortBy=latest&indexId=N&sector=&search=&seq=desc"
        data = await self.client.get(url=url)
        earnings_data = await self._decode_earnings_results(data)
        return earnings_data

    async def _nse_symbol(self, symbol):
        url = "https://priceapi.moneycontrol.com/pricefeed/nse/equitycash/" + symbol
        data = await self.client.get(url)
        return symbol, data.get("data", {}).get("NSEID")

    async def _decode_earnings_results(self, data, max_concurrent_requests=10):
        results = []
        symbols_to_fetch = []
        company_data_map = {}

        data = data.get("data", {})
        data = data.get("list", [])

        for company in data:
            name = company[1]
            release_dt = company[0]
            profit_arzg = company[5][2][3]
            symbol = company[6]

            if not profit_arzg:
                continue

            symbols_to_fetch.append(symbol)
            company_data_map[symbol] = {
                "name": name,
                "profit_pct": profit_arzg,
                "results_dt": from_business_dt(release_dt).date(),
                "original_symbol": symbol,
            }

        semaphore = asyncio.Semaphore(max_concurrent_requests)

        async def _fetch(symbol):
            async with semaphore:
                return await self._nse_symbol(symbol)

        nse_symbol_results = await asyncio.gather(
            *[_fetch(symbol) for symbol in symbols_to_fetch],
            return_exceptions=True,
        )

        nse_symbols_map = {
            symbol: nse_id for symbol, nse_id in nse_symbol_results if nse_id
        }

        for symbol, company_info in company_data_map.items():
            nse_symbol = nse_symbols_map.get(symbol)
            if nse_symbol:
                results.append(
                    {
                        "name": company_info["name"],
                        "profit_pct": company_info["profit_pct"],
                        "results_dt": company_info["results_dt"],
                        "symbol": nse_symbol,
                    }
                )

        return results

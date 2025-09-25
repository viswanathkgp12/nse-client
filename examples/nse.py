import asyncio
import json

from nse_client import NseGateway, ChartInterval
from datetime import date


async def main():
    async with NseGateway() as gateway:
        earnings = await gateway.recent_earnings()
        print(f"Earnings: {earnings}")

        indices = await gateway.indices()
        print(f"Indices: {indices}")

        intraday_stocks = await gateway.intraday_stocks()
        print(f"Intraday stocks: {intraday_stocks}")

        symbols = await gateway.symbols_by_index("NIFTY IT")
        print(f"Symbols: {symbols}")

        symbol = symbols[0]
        price_band = await gateway.price_band(symbol)
        print(f"Price band for {symbol} is {price_band}")

        industry = await gateway.industry(symbol)
        print(f"Basic Industry for {symbol} is {industry}")

        insider_trades = await gateway.insider_trades(symbol)
        print(f"Insider trades for {symbol} - {json.dumps(insider_trades)}")

        from_dt = date(2025, 1, 1)
        to_dt = date(2025, 9, 24)
        candles = await gateway.candles(
            symbols=symbols,
            interval=ChartInterval.ONE_DAY,
            from_dt=from_dt,
            to_dt=to_dt,
        )
        candle = await gateway.candle(
            symbol=symbol,
            interval=ChartInterval.ONE_DAY,
            from_dt=from_dt,
            to_dt=to_dt,
        )


if __name__ == "__main__":
    asyncio.run(main())

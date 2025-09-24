# NSE-Gateway

A Python library for interacting with the National Stock Exchange (NSE) of India APIs to fetch stock symbols, candle data, price bands, insider trading, and industry information.

## Installation

Download the latest `.whl` file from releases. Next install using:

```bash
pip install nse_client-0.3.0-py3-none-any.whl
```

## Features

- Get price band for a symbol(`2%`/`5%`/`10%`/`20%`/`No Band`). Stocks with derivatives have `No Band`.
- Get basic industry for a symbol
- Get historical candle data(`15m`/`1h`/`4h`/`1d`/`1w`). **NOTE:** NSE doesn't adjust historical data for stock splits/dividends etc.
- Get insider trades for symbol
- List indices and index constituent symbols
- List fno stocks
- List recent earnings(from MoneyControl)

## Usage

- Check `examples` folder

## Note

- `NseGateway` uses scrip codes to fetch candle data for stocks/indices. `NseGateway` class fetch and cache scrip codes in a JSON file during initialization. To ensure newly listed stocks are included, it’s recommended to periodically update the scrip codes. To do so:

```
async with NseGateway() as gateway:
    await gateway.fetch_scrips(force=True)
```

## License

MIT License

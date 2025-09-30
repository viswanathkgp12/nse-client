from nse_client.http_client import HttpClient


class AngelBrokingGateway:
    @staticmethod
    async def list_instruments():
        url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"

        cli = HttpClient(timeout=10)
        try:
            return await cli.get(url)
        finally:
            await cli.close()

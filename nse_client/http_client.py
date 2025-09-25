import asyncio
from typing import Literal

import aiohttp
import json
import logging

from aiohttp import ClientTimeout

logger = logging.getLogger(__name__)


class HttpClient:
    def __init__(self, base_url=None, headers=None, timeout=5):
        self.session = aiohttp.ClientSession(
            base_url=base_url,
            headers=headers,
            timeout=ClientTimeout(total=timeout),
        )

    async def get(
        self,
        url: str,
        params: dict = None,
        mode: Literal["json", "str"] = "json",
    ):
        return await self._request(
            url,
            method="GET",
            params=params,
            mode=mode,
        )

    async def post(
        self,
        url: str,
        body: dict,
        headers=None,
        mode: Literal["json", "str"] = "json",
    ):
        return await self._request(
            url,
            method="POST",
            body=body,
            headers=headers,
            mode=mode,
        )

    async def _request(
        self,
        url,
        method,
        params=None,
        body=None,
        headers=None,
        mode: Literal["json", "str"] = "json",
    ):
        try:
            async with self.session.request(
                url=url,
                method=method,
                params=params,
                data=json.dumps(body),
                headers=headers,
            ) as response:
                if not response.ok:
                    raise ConnectionError(f"{url} {response.status}: {response.reason}")

                if mode == "json":
                    return await response.json()
                return await response.text()
        except aiohttp.ClientError as e:
            logger.warning(f"{method} request failed for {url}: {str(e)}")
            raise (
                TimeoutError(str(e))
                if isinstance(e, aiohttp.ClientTimeout)
                else ConnectionError(str(e))
            )
        except asyncio.TimeoutError as e:
            logger.warning(f"{method} request timed-out for {url}: {str(e)}")
            raise TimeoutError(str(e))

    async def close(self):
        return await self.session.close()

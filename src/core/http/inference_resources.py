"""Own bounded upstream clients for every configured platform origin.

A single loop-bound client used to be locked to the one Loomy origin; with
千问办公 merged behind the same gateway the client table is keyed by origin
so both platforms share one event loop without leaking pools.  Cookies stay
globally rejected.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from http.cookiejar import CookieJar, DefaultCookiePolicy

import httpx

from . import runtime


class _RejectCookies(DefaultCookiePolicy):
    def set_ok(self, cookie, request):
        return False

    def return_ok(self, cookie, request):
        return False


class UpstreamClient:
    """Cookie-free HTTP clients bound to the running loop, one per upstream origin."""

    def __init__(self, config):
        self.config = config
        self._clients = {}
        self._loop = asyncio.get_running_loop()
        self._closed = False

    @staticmethod
    def _origin_of(url):
        value = httpx.URL(url)
        return value.scheme, value.host, value.port

    def get(self, url):
        origin = self._origin_of(url)
        if self._closed or asyncio.get_running_loop() is not self._loop:
            return None
        client = self._clients.get(origin)
        if client is None:
            client = httpx.AsyncClient(
                cookies=CookieJar(policy=_RejectCookies()), http2=False, follow_redirects=False,
                limits=httpx.Limits(max_connections=64, max_keepalive_connections=16, keepalive_expiry=30))
            self._clients[origin] = client
        return client

    async def aclose(self):
        self._closed = True
        clients, self._clients = list(self._clients.values()), {}
        for client in clients:
            await client.aclose()


@asynccontextmanager
async def inference_lifespan(app):
    client = UpstreamClient(app.state.config)
    runtime.bind_upstream(client, asyncio.get_running_loop())
    app.state.upstream = client
    try:
        yield
    finally:
        await client.aclose()
        runtime.bind_upstream(None, None)

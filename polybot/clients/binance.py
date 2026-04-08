from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable

import websockets

from polybot.models import FeedTick
from polybot.utils import now_ms

LOGGER = logging.getLogger(__name__)


class BinanceTradeStream:
    def __init__(
        self,
        base_url: str,
        symbol_to_asset: dict[str, str],
        on_tick: Callable[[str, FeedTick], None],
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.symbol_to_asset = {key.lower(): value for key, value in symbol_to_asset.items()}
        self.on_tick = on_tick

    async def run(self) -> None:
        streams = "/".join(f"{symbol}@trade" for symbol in sorted(self.symbol_to_asset))
        url = f"{self.base_url}/stream?streams={streams}"
        backoff = 1.0

        while True:
            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=2_000_000,
                ) as websocket:
                    LOGGER.info("Connected to Binance trade stream: %s", url)
                    backoff = 1.0
                    async for raw_message in websocket:
                        self._handle_message(raw_message)
            except Exception as exc:  # pragma: no cover - network branch
                LOGGER.warning("Binance stream disconnected: %s", exc)
                await asyncio.sleep(backoff)
                backoff = min(15.0, backoff * 1.5)

    def _handle_message(self, raw_message: str) -> None:
        try:
            message = json.loads(raw_message)
        except json.JSONDecodeError:
            return

        payload = message.get("data", message)
        symbol = str(payload.get("s", "")).lower()
        asset = self.symbol_to_asset.get(symbol)
        if not asset:
            return

        price_raw = payload.get("p")
        event_time_ms = payload.get("T") or payload.get("E")
        try:
            price = float(price_raw)
        except (TypeError, ValueError):
            return

        tick = FeedTick(
            source="binance_native",
            symbol=symbol,
            price=price,
            event_time_ms=int(event_time_ms) if event_time_ms is not None else None,
            observed_at_ms=now_ms(),
        )
        self.on_tick(asset, tick)

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx
import websockets

from polybot.config import MarketSeriesConfig
from polybot.models import FeedTick, MarketRuntime
from polybot.utils import now_ms, parse_jsonish_list, safe_float

LOGGER = logging.getLogger(__name__)

DEFAULT_ASSET_MAP: dict[str, dict[str, object]] = {
    "BTC": {
        "aliases": ("btc", "bitcoin"),
        "binance_symbol": "btcusdt",
        "chainlink_symbol": "btc/usd",
    },
    "ETH": {
        "aliases": ("eth", "ethereum"),
        "binance_symbol": "ethusdt",
        "chainlink_symbol": "eth/usd",
    },
    "SOL": {
        "aliases": ("sol", "solana"),
        "binance_symbol": "solusdt",
        "chainlink_symbol": "sol/usd",
    },
    "XRP": {
        "aliases": ("xrp",),
        "binance_symbol": "xrpusdt",
        "chainlink_symbol": "xrp/usd",
    },
}


def parse_timestamp_ms(value: object) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def recurrence_to_minutes(recurrence: str) -> int | None:
    raw = (recurrence or "").strip().lower()
    if raw.endswith("m") and raw[:-1].isdigit():
        return int(raw[:-1])
    if raw == "hourly":
        return 60
    if raw.endswith("h") and raw[:-1].isdigit():
        return int(raw[:-1]) * 60
    return None


def series_key(asset: str, recurrence: str) -> str:
    return f"{asset.lower()}_{recurrence.lower().replace(' ', '_')}"


class GammaClient:
    def __init__(self, gamma_base_url: str, clob_base_url: str) -> None:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        }
        self._gamma = httpx.AsyncClient(base_url=gamma_base_url.rstrip("/"), headers=headers, timeout=20.0)
        self._clob = httpx.AsyncClient(base_url=clob_base_url.rstrip("/"), headers=headers, timeout=20.0)

    async def close(self) -> None:
        await self._gamma.aclose()
        await self._clob.aclose()

    async def fetch_series(self, limit: int = 1000) -> list[dict[str, Any]]:
        response = await self._gamma.get("/series", params={"limit": limit})
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else []

    async def discover_series(
        self,
        asset_universe: tuple[str, ...],
        minute_only: bool,
    ) -> tuple[MarketSeriesConfig, ...]:
        records = await self.fetch_series()
        configs: list[MarketSeriesConfig] = []
        wanted_assets = {asset.upper() for asset in asset_universe}

        for record in records:
            if not record.get("active") or record.get("archived"):
                continue

            slug = str(record.get("slug") or "")
            title = str(record.get("title") or "")
            recurrence = str(record.get("recurrence") or "")
            recurrence_minutes = recurrence_to_minutes(recurrence)
            if recurrence_minutes is None:
                continue
            if minute_only and not recurrence.endswith("m"):
                continue
            if "up-or-down" not in slug.lower():
                continue

            asset = self._match_asset(title, slug)
            if asset is None or asset not in wanted_assets:
                continue

            source_meta = DEFAULT_ASSET_MAP[asset]
            max_entry_seconds = max(30, min(int(recurrence_minutes * 60 * 0.25), 240))
            min_gap_bps = 8.0 if recurrence_minutes >= 15 else 10.0
            min_edge_cents = 3.0 if recurrence_minutes >= 15 else 4.0
            configs.append(
                MarketSeriesConfig(
                    key=series_key(asset, recurrence),
                    label=title,
                    asset=asset,
                    binance_symbol=str(source_meta["binance_symbol"]),
                    chainlink_symbol=str(source_meta["chainlink_symbol"]),
                    series_id=str(record.get("id")),
                    window_minutes=recurrence_minutes,
                    max_entry_seconds=max_entry_seconds,
                    min_gap_bps=min_gap_bps,
                    min_edge_cents=min_edge_cents,
                    trade_enabled=True,
                )
            )

        configs.sort(key=lambda item: (item.window_minutes, item.asset, item.label))
        return tuple(configs)

    async def fetch_live_events_by_series_id(self, series_id: str, limit: int = 25) -> list[dict[str, Any]]:
        response = await self._gamma.get(
            "/events",
            params={
                "series_id": series_id,
                "active": "true",
                "closed": "false",
                "limit": limit,
            },
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else []

    async def fetch_clob_price(self, token_id: str, side: str = "buy") -> float | None:
        response = await self._clob.get("/price", params={"token_id": token_id, "side": side})
        response.raise_for_status()
        payload = response.json()
        return safe_float(payload.get("price"))

    async def fetch_market_runtime(
        self,
        series_config: MarketSeriesConfig,
        previous: MarketRuntime | None = None,
    ) -> MarketRuntime:
        runtime = MarketRuntime(
            key=series_config.key,
            label=series_config.label,
            asset=series_config.asset,
            series_id=series_config.series_id,
            window_minutes=series_config.window_minutes,
        )
        if previous is not None:
            runtime.price_to_beat = previous.price_to_beat
            runtime.price_to_beat_set_ms = previous.price_to_beat_set_ms

        if not series_config.series_id:
            runtime.status = "monitor-only"
            runtime.last_refresh_ms = now_ms()
            return runtime

        events = await self.fetch_live_events_by_series_id(series_config.series_id, limit=25)
        markets = self._flatten_event_markets(events)
        current_market = self._pick_current_market(markets)
        if current_market is None:
            runtime.status = "market-not-found"
            runtime.last_refresh_ms = now_ms()
            return runtime

        runtime.market_slug = str(current_market.get("slug") or "")
        runtime.market_question = str(current_market.get("question") or current_market.get("title") or "")
        runtime.event_start_ms = parse_timestamp_ms(current_market.get("eventStartTime"))
        runtime.end_ms = parse_timestamp_ms(current_market.get("endDate"))
        runtime.liquidity = safe_float(current_market.get("liquidityNum") or current_market.get("liquidity"))
        runtime.fees_enabled = bool(current_market.get("feesEnabled"))
        runtime.last_refresh_ms = now_ms()
        runtime.metadata = {
            "resolutionSource": current_market.get("resolutionSource"),
            "description": current_market.get("description"),
            "recurrence": series_config.window_minutes,
        }

        fee_schedule = current_market.get("feeSchedule") or {}
        runtime.maker_rebate_rate = safe_float(fee_schedule.get("rebateRate"))

        outcomes = [str(item) for item in parse_jsonish_list(current_market.get("outcomes"))]
        token_ids = [str(item) for item in parse_jsonish_list(current_market.get("clobTokenIds"))]
        price_map = self._extract_token_ids(outcomes, token_ids)
        runtime.up_token_id = price_map.get("UP")
        runtime.down_token_id = price_map.get("DOWN")

        if runtime.up_token_id and runtime.down_token_id:
            up_buy, down_buy = await asyncio.gather(
                self.fetch_clob_price(runtime.up_token_id, "buy"),
                self.fetch_clob_price(runtime.down_token_id, "buy"),
            )
            runtime.up_buy_price = up_buy
            runtime.down_buy_price = down_buy

        runtime.status = "ready"
        return runtime

    @staticmethod
    def _match_asset(title: str, slug: str) -> str | None:
        haystack = f"{title} {slug}".lower()
        for asset, meta in DEFAULT_ASSET_MAP.items():
            aliases = meta["aliases"]
            if any(alias in haystack for alias in aliases):
                return asset
        return None

    @staticmethod
    def _flatten_event_markets(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        markets: list[dict[str, Any]] = []
        for event in events:
            event_markets = event.get("markets") or []
            if isinstance(event_markets, list):
                for market in event_markets:
                    if isinstance(market, dict):
                        markets.append(market)
        return markets

    @staticmethod
    def _pick_current_market(markets: list[dict[str, Any]]) -> dict[str, Any] | None:
        now_value = now_ms()
        candidates: list[tuple[int, dict[str, Any]]] = []

        for market in markets:
            end_ms = parse_timestamp_ms(market.get("endDate"))
            start_ms = parse_timestamp_ms(market.get("eventStartTime") or market.get("startTime") or market.get("startDate"))
            if end_ms is None:
                continue
            if start_ms is None or start_ms <= now_value < end_ms:
                candidates.append((end_ms, market))

        if candidates:
            return sorted(candidates, key=lambda item: item[0])[0][1]

        upcoming: list[tuple[int, dict[str, Any]]] = []
        for market in markets:
            end_ms = parse_timestamp_ms(market.get("endDate"))
            if end_ms is not None and now_value < end_ms:
                upcoming.append((end_ms, market))

        return sorted(upcoming, key=lambda item: item[0])[0][1] if upcoming else None

    @staticmethod
    def _extract_token_ids(outcomes: list[str], token_ids: list[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for index, outcome in enumerate(outcomes):
            if index >= len(token_ids):
                continue
            label = outcome.strip().lower()
            token_id = token_ids[index]
            if label == "up":
                result["UP"] = token_id
            elif label == "down":
                result["DOWN"] = token_id
        return result


class PolymarketRTDSClient:
    def __init__(
        self,
        rtds_url: str,
        symbol_map: dict[str, str],
        on_tick: Callable[[str, FeedTick], None],
    ) -> None:
        self.rtds_url = rtds_url
        self.symbol_map = symbol_map
        self.on_tick = on_tick

    async def run(self) -> None:
        backoff = 1.0

        while True:
            try:
                async with websockets.connect(
                    self.rtds_url,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=2_000_000,
                ) as websocket:
                    await websocket.send(json.dumps(self._build_subscribe_message()))
                    keepalive = asyncio.create_task(self._keepalive(websocket))
                    LOGGER.info("Connected to Polymarket RTDS: %s", self.rtds_url)
                    backoff = 1.0

                    try:
                        async for raw_message in websocket:
                            self._handle_message(raw_message)
                    finally:
                        keepalive.cancel()
            except Exception as exc:  # pragma: no cover - network branch
                LOGGER.warning("RTDS stream disconnected: %s", exc)
                await asyncio.sleep(backoff)
                backoff = min(15.0, backoff * 1.5)

    async def _keepalive(self, websocket: websockets.WebSocketClientProtocol) -> None:
        while True:
            await asyncio.sleep(5)
            await websocket.send("PING")

    def _build_subscribe_message(self) -> dict[str, object]:
        binance_filters = ",".join(
            sorted(
                {
                    str(meta["binance_symbol"])
                    for meta in DEFAULT_ASSET_MAP.values()
                    if str(meta["binance_symbol"]).lower() in self.symbol_map
                }
            )
        )
        subscriptions: list[dict[str, str]] = []
        if binance_filters:
            subscriptions.append(
                {
                    "topic": "crypto_prices",
                    "type": "update",
                    "filters": binance_filters,
                }
            )

        for meta in DEFAULT_ASSET_MAP.values():
            chainlink_symbol = str(meta["chainlink_symbol"])
            subscriptions.append(
                {
                    "topic": "crypto_prices_chainlink",
                    "type": "*",
                    "filters": json.dumps({"symbol": chainlink_symbol}),
                }
            )

        return {
            "action": "subscribe",
            "subscriptions": subscriptions,
        }

    def _handle_message(self, raw_message: str) -> None:
        if raw_message == "PONG":
            return

        try:
            message = json.loads(raw_message)
        except json.JSONDecodeError:
            return

        topic = str(message.get("topic") or "")
        payload = message.get("payload") or {}
        if not isinstance(payload, dict):
            return

        symbol = str(payload.get("symbol") or "").lower()
        asset = self.symbol_map.get(symbol)
        if not asset:
            return

        price = safe_float(payload.get("value"))
        if price is None:
            return

        source = "polymarket_chainlink" if topic == "crypto_prices_chainlink" else "polymarket_binance"
        tick = FeedTick(
            source=source,
            symbol=symbol,
            price=price,
            event_time_ms=int(payload.get("timestamp")) if payload.get("timestamp") is not None else None,
            observed_at_ms=now_ms(),
        )
        self.on_tick(asset, tick)

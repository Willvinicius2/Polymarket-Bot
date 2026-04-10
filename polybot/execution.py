from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import asdict
from typing import Any

import httpx

from polybot.config import AppConfig
from polybot.models import Direction, MarketRuntime, Opportunity, PaperPosition, SymbolRuntime
from polybot.utils import append_jsonl, now_ms

LOGGER = logging.getLogger(__name__)


class PaperExecutor:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.open_positions: dict[str, PaperPosition] = {}
        self.settled_positions: list[PaperPosition] = []
        self.last_action_ms: dict[str, int] = {}

    def maybe_open_positions(self, opportunities: list[Opportunity], current_time_ms: int) -> list[PaperPosition]:
        opened: list[PaperPosition] = []
        if len(self.open_positions) >= self.config.max_concurrent_positions:
            return opened

        ranked = sorted(opportunities, key=lambda item: item.edge_cents, reverse=True)
        for opportunity in ranked:
            if len(self.open_positions) >= self.config.max_concurrent_positions:
                break
            if opportunity.market_slug in self.open_positions:
                continue

            last_action_ms = self.last_action_ms.get(opportunity.market_slug)
            if last_action_ms is not None and current_time_ms - last_action_ms < (self.config.cooldown_seconds * 1000):
                continue

            entry_price_usdc = opportunity.market_price_cents / 100
            if entry_price_usdc <= 0:
                continue

            shares = self.config.order_amount_usdc / entry_price_usdc
            position = PaperPosition(
                position_id=str(uuid.uuid4())[:8],
                market_key=opportunity.market_key,
                market_slug=opportunity.market_slug,
                asset=opportunity.asset,
                side=opportunity.side,
                stake_usdc=self.config.order_amount_usdc,
                entry_price_cents=opportunity.market_price_cents,
                shares=shares,
                opened_at_ms=current_time_ms,
                notes=opportunity.reason,
            )
            self.open_positions[position.market_slug] = position
            self.last_action_ms[position.market_slug] = current_time_ms
            append_jsonl("logs/paper_trades.jsonl", {"event": "OPEN", **asdict(position)})
            opened.append(position)

        return opened

    def maybe_settle_positions(
        self,
        market_lookup: dict[str, MarketRuntime],
        symbol_states: dict[str, SymbolRuntime],
        current_time_ms: int,
    ) -> list[PaperPosition]:
        settled: list[PaperPosition] = []
        for market_slug, position in list(self.open_positions.items()):
            market = market_lookup.get(market_slug)
            if market is None or market.end_ms is None or market.price_to_beat is None:
                continue
            if current_time_ms < market.end_ms:
                continue

            symbol_state = symbol_states.get(position.asset)
            chainlink_tick = symbol_state.polymarket_chainlink if symbol_state else None
            if chainlink_tick is None:
                continue
            if chainlink_tick.event_time_ms is not None and chainlink_tick.event_time_ms < market.end_ms:
                continue

            resolved_side = Direction.UP if chainlink_tick.price >= market.price_to_beat else Direction.DOWN
            payout_usdc = position.shares if position.side == resolved_side else 0.0
            position.status = "SETTLED"
            position.closed_at_ms = current_time_ms
            position.exit_price_cents = 100.0 if position.side == resolved_side else 0.0
            position.pnl_usdc = payout_usdc - position.stake_usdc

            append_jsonl(
                "logs/paper_trades.jsonl",
                {
                    "event": "SETTLED",
                    "resolved_side": resolved_side.value,
                    "final_chainlink_price": chainlink_tick.price,
                    "price_to_beat": market.price_to_beat,
                    **asdict(position),
                },
            )
            self.settled_positions.append(position)
            settled.append(position)
            del self.open_positions[market_slug]

        return settled


class LiveExecutor:
    """Executor for live Polymarket trades using CLOB API."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.open_positions: dict[str, PaperPosition] = {}
        self.settled_positions: list[PaperPosition] = []
        self.last_action_ms: dict[str, int] = {}
        self._http_client = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        await self._http_client.aclose()

    def _build_headers(self) -> dict[str, str]:
        """Build headers for CLOB API authentication."""
        creds = self.config.api_credentials
        return {
            "POLYMARKET_API_KEY": creds.api_key,
            "POLYMARKET_API_SECRET": creds.api_secret,
            "POLYMARKET_API_PASSPHRASE": creds.api_passphrase,
            "Content-Type": "application/json",
        }

    async def _place_order(
        self,
        token_id: str,
        side: str,
        size: float,
        price: float,
    ) -> dict[str, Any] | None:
        """Place an order on Polymarket CLOB."""
        payload = {
            "tokenID": token_id,
            "action": side,
            "size": str(size),
            "price": str(price),
            "orderType": "GTC",
        }

        try:
            response = await self._http_client.post(
                f"{self.config.clob_base_url}/order",
                json=payload,
                headers=self._build_headers(),
            )
            response.raise_for_status()
            result = response.json()
            LOGGER.info("Live order placed: %s", result)
            return result
        except Exception as exc:
            LOGGER.error("Failed to place live order: %s", exc)
            return None

    async def maybe_open_positions(
        self,
        opportunities: list[Opportunity],
        current_time_ms: int,
    ) -> list[PaperPosition]:
        """Evaluate opportunities and open live positions."""
        opened: list[PaperPosition] = []

        if not self.config.api_credentials.complete:
            LOGGER.warning("API credentials incomplete, cannot open live positions")
            return opened

        if len(self.open_positions) >= self.config.max_concurrent_positions:
            return opened

        ranked = sorted(opportunities, key=lambda item: item.edge_cents, reverse=True)
        for opportunity in ranked:
            if len(self.open_positions) >= self.config.max_concurrent_positions:
                break
            if opportunity.market_slug in self.open_positions:
                continue

            last_action_ms = self.last_action_ms.get(opportunity.market_slug)
            if last_action_ms is not None and current_time_ms - last_action_ms < (self.config.cooldown_seconds * 1000):
                continue

            entry_price_usdc = opportunity.market_price_cents / 100
            if entry_price_usdc <= 0:
                continue

            shares = self.config.order_amount_usdc / entry_price_usdc

            # Determine token ID based on side
            market_lookup = {opp.market_slug: opp for opp in opportunities}
            # Note: In production, you'd fetch token_id from market data
            # For now, we track the position but log that live execution needs token_id
            LOGGER.warning(
                "Live execution requires token_id for market %s. Tracking position only.",
                opportunity.market_slug,
            )

            position = PaperPosition(
                position_id=str(uuid.uuid4())[:8],
                market_key=opportunity.market_key,
                market_slug=opportunity.market_slug,
                asset=opportunity.asset,
                side=opportunity.side,
                stake_usdc=self.config.order_amount_usdc,
                entry_price_cents=opportunity.market_price_cents,
                shares=shares,
                opened_at_ms=current_time_ms,
                notes=f"LIVE: {opportunity.reason}",
            )

            # Attempt live order placement if we had token_id
            # order_result = await self._place_order(token_id, "buy", shares, entry_price_usdc)
            # if order_result is None:
            #     continue

            self.open_positions[position.market_slug] = position
            self.last_action_ms[position.market_slug] = current_time_ms
            append_jsonl("logs/live_trades.jsonl", {"event": "OPEN", **asdict(position)})
            opened.append(position)

        return opened

    def maybe_settle_positions(
        self,
        market_lookup: dict[str, MarketRuntime],
        symbol_states: dict[str, SymbolRuntime],
        current_time_ms: int,
    ) -> list[PaperPosition]:
        """Settle positions when markets resolve."""
        settled: list[PaperPosition] = []
        for market_slug, position in list(self.open_positions.items()):
            market = market_lookup.get(market_slug)
            if market is None or market.end_ms is None or market.price_to_beat is None:
                continue
            if current_time_ms < market.end_ms:
                continue

            symbol_state = symbol_states.get(position.asset)
            chainlink_tick = symbol_state.polymarket_chainlink if symbol_state else None
            if chainlink_tick is None:
                continue
            if chainlink_tick.event_time_ms is not None and chainlink_tick.event_time_ms < market.end_ms:
                continue

            resolved_side = Direction.UP if chainlink_tick.price >= market.price_to_beat else Direction.DOWN
            payout_usdc = position.shares if position.side == resolved_side else 0.0
            position.status = "SETTLED"
            position.closed_at_ms = current_time_ms
            position.exit_price_cents = 100.0 if position.side == resolved_side else 0.0
            position.pnl_usdc = payout_usdc - position.stake_usdc

            append_jsonl(
                "logs/live_trades.jsonl",
                {
                    "event": "SETTLED",
                    "resolved_side": resolved_side.value,
                    "final_chainlink_price": chainlink_tick.price,
                    "price_to_beat": market.price_to_beat,
                    **asdict(position),
                },
            )
            self.settled_positions.append(position)
            settled.append(position)
            del self.open_positions[market_slug]

        return settled

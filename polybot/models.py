from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ExecutionMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"


class Direction(StrEnum):
    UP = "UP"
    DOWN = "DOWN"
    FLAT = "FLAT"


@dataclass(slots=True)
class FeedTick:
    source: str
    symbol: str
    price: float
    observed_at_ms: int
    event_time_ms: int | None = None

    @property
    def age_ms(self) -> int:
        return max(0, self.observed_at_ms - (self.event_time_ms or self.observed_at_ms))


@dataclass(slots=True)
class SymbolRuntime:
    asset: str
    native_binance: FeedTick | None = None
    polymarket_binance: FeedTick | None = None
    polymarket_chainlink: FeedTick | None = None


@dataclass(slots=True)
class MarketRuntime:
    key: str
    label: str
    asset: str
    series_id: str | None
    window_minutes: int
    market_slug: str | None = None
    market_question: str | None = None
    event_start_ms: int | None = None
    end_ms: int | None = None
    up_token_id: str | None = None
    down_token_id: str | None = None
    up_buy_price: float | None = None
    down_buy_price: float | None = None
    liquidity: float | None = None
    spread_up: float | None = None
    spread_down: float | None = None
    price_to_beat: float | None = None
    price_to_beat_set_ms: int | None = None
    fees_enabled: bool = False
    maker_rebate_rate: float | None = None
    status: str = "loading"
    last_refresh_ms: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def time_left_ms(self, now_ms: int) -> int | None:
        if self.end_ms is None:
            return None
        return self.end_ms - now_ms


@dataclass(slots=True)
class Opportunity:
    market_key: str
    market_slug: str
    label: str
    asset: str
    side: Direction
    confidence: float
    model_up: float
    model_down: float
    edge_cents: float
    lead_gap_bps: float
    lead_gap_usd: float
    native_vs_price_to_beat_bps: float
    chainlink_vs_price_to_beat_bps: float
    time_left_ms: int
    market_price_cents: float
    reason: str


@dataclass(slots=True)
class PaperPosition:
    position_id: str
    market_key: str
    market_slug: str
    asset: str
    side: Direction
    stake_usdc: float
    entry_price_cents: float
    shares: float
    opened_at_ms: int
    status: str = "OPEN"
    closed_at_ms: int | None = None
    exit_price_cents: float | None = None
    pnl_usdc: float | None = None
    notes: str = ""

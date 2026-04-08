from __future__ import annotations

from polybot.config import AppConfig, MarketSeriesConfig
from polybot.models import Direction, MarketRuntime, Opportunity, SymbolRuntime
from polybot.utils import clamp, signed_bps


def _direction_from_price(price: float | None, threshold: float | None) -> Direction:
    if price is None or threshold is None:
        return Direction.FLAT
    if price > threshold:
        return Direction.UP
    if price < threshold:
        return Direction.DOWN
    return Direction.FLAT


def build_opportunity(
    config: AppConfig,
    series: MarketSeriesConfig,
    market: MarketRuntime,
    symbol_state: SymbolRuntime,
    current_time_ms: int,
) -> Opportunity | None:
    if not series.trade_enabled or market.price_to_beat is None or market.end_ms is None:
        return None

    time_left_ms = market.end_ms - current_time_ms
    if time_left_ms <= 0 or time_left_ms > series.max_entry_seconds * 1000:
        return None

    native_tick = symbol_state.native_binance
    chainlink_tick = symbol_state.polymarket_chainlink
    if native_tick is None or chainlink_tick is None:
        return None

    native_price = native_tick.price
    chainlink_price = chainlink_tick.price
    price_to_beat = market.price_to_beat

    lead_gap_bps = signed_bps(native_price, chainlink_price)
    native_vs_threshold_bps = signed_bps(native_price, price_to_beat)
    chainlink_vs_threshold_bps = signed_bps(chainlink_price, price_to_beat)
    if lead_gap_bps is None or native_vs_threshold_bps is None or chainlink_vs_threshold_bps is None:
        return None

    lead_gap_usd = native_price - chainlink_price
    abs_lead_gap_bps = abs(lead_gap_bps)
    effective_min_gap = max(config.min_lead_gap_bps, series.min_gap_bps)
    if abs_lead_gap_bps < effective_min_gap:
        return None

    expected_side = _direction_from_price(native_price, price_to_beat)
    if expected_side == Direction.FLAT:
        return None

    chainlink_side = _direction_from_price(chainlink_price, price_to_beat)
    side_disagreement = chainlink_side not in (Direction.FLAT, expected_side)

    gap_score = clamp(abs_lead_gap_bps / effective_min_gap, 0.0, 3.0)
    threshold_score = clamp(abs(native_vs_threshold_bps) / max(4.0, effective_min_gap * 0.75), 0.0, 3.0)
    time_pressure = clamp(1.0 - (time_left_ms / (series.max_entry_seconds * 1000)), 0.0, 1.0)
    stale_penalty = 0.0

    if native_tick.age_ms > 2_000 or chainlink_tick.age_ms > 2_000:
        stale_penalty += 0.15
    if native_tick.observed_at_ms - chainlink_tick.observed_at_ms > 3_000:
        stale_penalty += 0.10

    confidence = 0.50 + (gap_score * 0.08) + (threshold_score * 0.07) + (time_pressure * 0.10)
    if side_disagreement:
        confidence += 0.15
    confidence = clamp(confidence - stale_penalty, 0.01, 0.98)

    model_up = confidence if expected_side == Direction.UP else 1.0 - confidence
    model_down = 1.0 - model_up

    market_price_cents = (market.up_buy_price or 0.0) * 100 if expected_side == Direction.UP else (market.down_buy_price or 0.0) * 100
    if market_price_cents <= 0:
        return None

    model_price_cents = model_up * 100 if expected_side == Direction.UP else model_down * 100
    edge_cents = model_price_cents - market_price_cents
    if edge_cents < max(config.min_edge_cents, series.min_edge_cents):
        return None

    reason_parts = [
        f"lead={lead_gap_usd:+.2f} USD",
        f"gap={lead_gap_bps:+.1f} bps",
        f"threshold={native_vs_threshold_bps:+.1f} bps",
        f"time_left={max(0, int(time_left_ms / 1000))}s",
    ]
    if side_disagreement:
        reason_parts.append("chainlink_lagging_threshold")

    return Opportunity(
        market_key=series.key,
        market_slug=market.market_slug or "-",
        label=series.label,
        asset=series.asset,
        side=expected_side,
        confidence=confidence,
        model_up=model_up,
        model_down=model_down,
        edge_cents=edge_cents,
        lead_gap_bps=lead_gap_bps,
        lead_gap_usd=lead_gap_usd,
        native_vs_price_to_beat_bps=native_vs_threshold_bps,
        chainlink_vs_price_to_beat_bps=chainlink_vs_threshold_bps,
        time_left_ms=time_left_ms,
        market_price_cents=market_price_cents,
        reason=", ".join(reason_parts),
    )

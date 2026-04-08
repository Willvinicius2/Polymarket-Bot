from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from polybot.models import ExecutionMode


@dataclass(frozen=True, slots=True)
class MarketSeriesConfig:
    key: str
    label: str
    asset: str
    binance_symbol: str
    chainlink_symbol: str
    series_id: str | None
    window_minutes: int
    max_entry_seconds: int
    min_gap_bps: float
    min_edge_cents: float
    trade_enabled: bool = True


@dataclass(frozen=True, slots=True)
class ApiCredentials:
    private_key: str
    api_key: str
    api_secret: str
    api_passphrase: str
    funder_address: str

    @property
    def complete(self) -> bool:
        return all(
            [
                self.private_key,
                self.api_key,
                self.api_secret,
                self.api_passphrase,
                self.funder_address,
            ]
        )


@dataclass(frozen=True, slots=True)
class AppConfig:
    mode: ExecutionMode
    gamma_base_url: str
    clob_base_url: str
    polymarket_rtds_url: str
    binance_ws_base_url: str
    order_amount_usdc: float
    min_edge_cents: float
    min_lead_gap_bps: float
    market_refresh_seconds: float
    signal_refresh_seconds: float
    ui_refresh_seconds: float
    cooldown_seconds: int
    max_concurrent_positions: int
    state_path: str
    api_credentials: ApiCredentials
    markets: tuple[MarketSeriesConfig, ...]
    asset_universe: tuple[str, ...]
    monitor_only_assets: tuple[str, ...]
    minute_only_discovery: bool


DEFAULT_MARKETS = (
    MarketSeriesConfig(
        key="btc_15m",
        label="BTC 15m",
        asset="BTC",
        binance_symbol="btcusdt",
        chainlink_symbol="btc/usd",
        series_id="10192",
        window_minutes=15,
        max_entry_seconds=120,
        min_gap_bps=8.0,
        min_edge_cents=3.0,
    ),
    MarketSeriesConfig(
        key="eth_5m",
        label="ETH 5m",
        asset="ETH",
        binance_symbol="ethusdt",
        chainlink_symbol="eth/usd",
        series_id="10683",
        window_minutes=5,
        max_entry_seconds=45,
        min_gap_bps=10.0,
        min_edge_cents=4.0,
    ),
    MarketSeriesConfig(
        key="xrp_monitor",
        label="XRP monitor",
        asset="XRP",
        binance_symbol="xrpusdt",
        chainlink_symbol="xrp/usd",
        series_id=None,
        window_minutes=15,
        max_entry_seconds=0,
        min_gap_bps=12.0,
        min_edge_cents=0.0,
        trade_enabled=False,
    ),
)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else default


def load_config() -> AppConfig:
    load_dotenv()

    mode_raw = (os.getenv("POLYBOT_MODE") or "paper").strip().lower()
    mode = ExecutionMode.LIVE if mode_raw == "live" else ExecutionMode.PAPER

    creds = ApiCredentials(
        private_key=(os.getenv("POLYMARKET_PRIVATE_KEY") or "").strip(),
        api_key=(os.getenv("POLYMARKET_API_KEY") or "").strip(),
        api_secret=(os.getenv("POLYMARKET_API_SECRET") or "").strip(),
        api_passphrase=(os.getenv("POLYMARKET_API_PASSPHRASE") or "").strip(),
        funder_address=(os.getenv("POLYMARKET_FUNDER_ADDRESS") or "").strip(),
    )

    return AppConfig(
        mode=mode,
        gamma_base_url=(os.getenv("POLYBOT_GAMMA_BASE_URL") or "https://gamma-api.polymarket.com").strip(),
        clob_base_url=(os.getenv("POLYBOT_CLOB_BASE_URL") or "https://clob.polymarket.com").strip(),
        polymarket_rtds_url=(os.getenv("POLYBOT_RTDS_URL") or "wss://ws-live-data.polymarket.com").strip(),
        binance_ws_base_url=(os.getenv("POLYBOT_BINANCE_WS_URL") or "wss://stream.binance.com:9443").strip(),
        order_amount_usdc=_env_float("POLYBOT_ORDER_AMOUNT_USDC", 25.0),
        min_edge_cents=_env_float("POLYBOT_MIN_EDGE_CENTS", 3.0),
        min_lead_gap_bps=_env_float("POLYBOT_MIN_LEAD_GAP_BPS", 8.0),
        market_refresh_seconds=_env_float("POLYBOT_MARKET_REFRESH_SECONDS", 10.0),
        signal_refresh_seconds=_env_float("POLYBOT_SIGNAL_REFRESH_SECONDS", 1.0),
        ui_refresh_seconds=_env_float("POLYBOT_UI_REFRESH_SECONDS", 0.5),
        cooldown_seconds=_env_int("POLYBOT_COOLDOWN_SECONDS", 30),
        max_concurrent_positions=_env_int("POLYBOT_MAX_CONCURRENT_POSITIONS", 3),
        state_path=(os.getenv("POLYBOT_STATE_PATH") or "state/latest_snapshot.json").strip(),
        api_credentials=creds,
        markets=DEFAULT_MARKETS,
        asset_universe=("BTC", "ETH", "SOL", "XRP"),
        monitor_only_assets=("XRP",),
        minute_only_discovery=(os.getenv("POLYBOT_MINUTE_ONLY_DISCOVERY") or "true").strip().lower() != "false",
    )

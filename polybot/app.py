from __future__ import annotations

import argparse
import asyncio
import copy
import logging
from dataclasses import asdict, dataclass, field

from rich.console import Console
from rich.live import Live

from polybot.clients.binance import BinanceTradeStream
from polybot.clients.polymarket import DEFAULT_ASSET_MAP, GammaClient, PolymarketRTDSClient
from polybot.config import AppConfig, MarketSeriesConfig, load_config
from polybot.execution import LiveExecutor, PaperExecutor
from polybot.models import ExecutionMode, FeedTick, MarketRuntime, Opportunity, SymbolRuntime
from polybot.strategies.latency_gap import build_opportunity
from polybot.ui import build_dashboard
from polybot.utils import now_ms, write_json

LOGGER = logging.getLogger(__name__)
CONSOLE = Console()


@dataclass(slots=True)
class RuntimeState:
    series_configs: dict[str, MarketSeriesConfig] = field(default_factory=dict)
    symbol_states: dict[str, SymbolRuntime] = field(default_factory=dict)
    active_markets: dict[str, MarketRuntime] = field(default_factory=dict)
    market_cache_by_slug: dict[str, MarketRuntime] = field(default_factory=dict)
    opportunities: dict[str, Opportunity] = field(default_factory=dict)


class TradingBot:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.state = RuntimeState(
            series_configs={cfg.key: cfg for cfg in config.markets},
            symbol_states={asset: SymbolRuntime(asset=asset) for asset in config.asset_universe},
        )
        self.paper_executor = PaperExecutor(config)
        self.live_executor = LiveExecutor(config) if config.mode == ExecutionMode.LIVE else None
        self.gamma = GammaClient(config.gamma_base_url, config.clob_base_url)
        self._running = True

        self._binance_symbol_map = {
            str(meta["binance_symbol"]).lower(): asset
            for asset, meta in DEFAULT_ASSET_MAP.items()
            if asset in config.asset_universe
        }
        self._rtds_symbol_map = dict(self._binance_symbol_map)
        self._rtds_symbol_map.update(
            {
                str(meta["chainlink_symbol"]).lower(): asset
                for asset, meta in DEFAULT_ASSET_MAP.items()
                if asset in config.asset_universe
            }
        )

    @property
    def executor(self) -> PaperExecutor | LiveExecutor:
        """Return the active executor based on mode."""
        if self.config.mode == ExecutionMode.LIVE and self.live_executor is not None:
            return self.live_executor
        return self.paper_executor

    async def close(self) -> None:
        await self.gamma.close()
        if self.live_executor is not None:
            await self.live_executor.close()

    def on_tick(self, asset: str, tick: FeedTick) -> None:
        symbol_state = self.state.symbol_states.setdefault(asset, SymbolRuntime(asset=asset))
        if tick.source == "binance_native":
            symbol_state.native_binance = tick
        elif tick.source == "polymarket_binance":
            symbol_state.polymarket_binance = tick
        elif tick.source == "polymarket_chainlink":
            symbol_state.polymarket_chainlink = tick

    async def refresh_series_configs(self) -> None:
        discovered = await self.gamma.discover_series(
            asset_universe=self.config.asset_universe,
            minute_only=self.config.minute_only_discovery,
        )
        merged = {cfg.key: cfg for cfg in self.config.markets}
        for cfg in discovered:
            merged[cfg.key] = cfg
        self.state.series_configs = merged

    async def refresh_markets(self) -> None:
        refreshed: dict[str, MarketRuntime] = {}
        for key, series_cfg in sorted(self.state.series_configs.items()):
            previous = self.state.active_markets.get(key)
            try:
                runtime = await self.gamma.fetch_market_runtime(series_cfg, previous=previous)
            except Exception as exc:  # pragma: no cover - network branch
                runtime = copy.deepcopy(previous) if previous is not None else MarketRuntime(
                    key=series_cfg.key,
                    label=series_cfg.label,
                    asset=series_cfg.asset,
                    series_id=series_cfg.series_id,
                    window_minutes=series_cfg.window_minutes,
                )
                runtime.status = f"refresh-error: {exc}"
                runtime.last_refresh_ms = now_ms()

            refreshed[key] = runtime
            if runtime.market_slug:
                self.state.market_cache_by_slug[runtime.market_slug] = copy.deepcopy(runtime)

        self.state.active_markets = refreshed

    def _latch_price_to_beat(self) -> None:
        current_time = now_ms()
        for market in self.state.active_markets.values():
            if market.price_to_beat is not None or market.event_start_ms is None:
                continue
            if current_time < market.event_start_ms:
                continue

            symbol_state = self.state.symbol_states.get(market.asset)
            chainlink_tick = symbol_state.polymarket_chainlink if symbol_state else None
            if chainlink_tick is None:
                continue

            tick_time = chainlink_tick.event_time_ms or chainlink_tick.observed_at_ms
            if tick_time < market.event_start_ms:
                continue

            market.price_to_beat = chainlink_tick.price
            market.price_to_beat_set_ms = chainlink_tick.observed_at_ms
            if market.market_slug:
                self.state.market_cache_by_slug[market.market_slug] = copy.deepcopy(market)

    def build_opportunities(self) -> list[Opportunity]:
        current_time = now_ms()
        opportunities: dict[str, Opportunity] = {}
        self._latch_price_to_beat()

        for key, market in self.state.active_markets.items():
            series_cfg = self.state.series_configs.get(key)
            symbol_state = self.state.symbol_states.get(market.asset)
            if series_cfg is None or symbol_state is None:
                continue

            opportunity = build_opportunity(
                config=self.config,
                series=series_cfg,
                market=market,
                symbol_state=symbol_state,
                current_time_ms=current_time,
            )
            if opportunity is not None:
                opportunities[key] = opportunity

        self.state.opportunities = opportunities
        return list(opportunities.values())

    def snapshot(self) -> dict[str, object]:
        return {
            "mode": self.config.mode.value,
            "symbols": {
                asset: {
                    "native_binance": asdict(runtime.native_binance) if runtime.native_binance else None,
                    "polymarket_binance": asdict(runtime.polymarket_binance) if runtime.polymarket_binance else None,
                    "polymarket_chainlink": asdict(runtime.polymarket_chainlink) if runtime.polymarket_chainlink else None,
                }
                for asset, runtime in self.state.symbol_states.items()
            },
            "markets": {key: asdict(value) for key, value in self.state.active_markets.items()},
            "opportunities": {key: asdict(value) for key, value in self.state.opportunities.items()},
            "open_positions": [asdict(item) for item in self.executor.open_positions.values()],
            "settled_positions": [asdict(item) for item in self.executor.settled_positions[-20:]],
        }

    async def persist_snapshot(self) -> None:
        write_json(self.config.state_path, self.snapshot())

    async def discovery_loop(self) -> None:
        while self._running:
            await self.refresh_series_configs()
            await asyncio.sleep(300)

    async def market_loop(self) -> None:
        while self._running:
            await self.refresh_markets()
            await asyncio.sleep(self.config.market_refresh_seconds)

    async def signal_loop(self) -> None:
        while self._running:
            opportunities = self.build_opportunities()
            current_time = now_ms()
            if isinstance(self.executor, LiveExecutor):
                await self.executor.maybe_open_positions(opportunities, current_time)
            else:
                self.executor.maybe_open_positions(opportunities, current_time)
            market_lookup = dict(self.state.market_cache_by_slug)
            for market in self.state.active_markets.values():
                if market.market_slug:
                    market_lookup[market.market_slug] = market
            self.executor.maybe_settle_positions(market_lookup, self.state.symbol_states, current_time)
            await self.persist_snapshot()
            await asyncio.sleep(self.config.signal_refresh_seconds)

    async def ui_loop(self) -> None:
        with Live(screen=True, auto_refresh=False, console=CONSOLE) as live:
            while self._running:
                live.update(
                    build_dashboard(
                        mode_label=self.config.mode.value,
                        markets=self.state.active_markets,
                        symbol_states=self.state.symbol_states,
                        opportunities=list(self.state.opportunities.values()),
                        open_positions=list(self.executor.open_positions.values()),
                        settled_positions=self.executor.settled_positions,
                    ),
                    refresh=True,
                )
                await asyncio.sleep(self.config.ui_refresh_seconds)

    async def run(self, with_ui: bool) -> None:
        await self.refresh_series_configs()
        await self.refresh_markets()

        binance_stream = BinanceTradeStream(
            base_url=self.config.binance_ws_base_url,
            symbol_to_asset=self._binance_symbol_map,
            on_tick=self.on_tick,
        )
        polymarket_stream = PolymarketRTDSClient(
            rtds_url=self.config.polymarket_rtds_url,
            symbol_map=self._rtds_symbol_map,
            on_tick=self.on_tick,
        )

        tasks = [
            asyncio.create_task(binance_stream.run(), name="binance-stream"),
            asyncio.create_task(polymarket_stream.run(), name="polymarket-rtds"),
            asyncio.create_task(self.discovery_loop(), name="series-discovery"),
            asyncio.create_task(self.market_loop(), name="market-refresh"),
            asyncio.create_task(self.signal_loop(), name="signal-loop"),
        ]
        if with_ui:
            tasks.append(asyncio.create_task(self.ui_loop(), name="ui-loop"))

        try:
            await asyncio.gather(*tasks)
        finally:
            self._running = False
            for task in tasks:
                task.cancel()
            await self.close()

    async def run_once(self) -> None:
        await self.refresh_series_configs()
        await self.refresh_markets()
        self.build_opportunities()
        await self.persist_snapshot()
        await self.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Polymarket latency bot")
    parser.add_argument("--no-ui", action="store_true", help="disable the rich live dashboard")
    parser.add_argument("--once", action="store_true", help="run one discovery/refresh cycle and exit")
    return parser.parse_args()


async def _async_main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    args = parse_args()
    config = load_config()
    bot = TradingBot(config)

    if args.once:
        await bot.run_once()
        CONSOLE.print(f"Snapshot written to [bold]{config.state_path}[/bold]")
        return

    await bot.run(with_ui=not args.no_ui)


def main() -> None:
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

from __future__ import annotations

from rich.columns import Columns
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from polybot.models import MarketRuntime, Opportunity, PaperPosition, SymbolRuntime
from polybot.utils import short_slug


def _fmt_price(value: float | None, digits: int = 2) -> str:
    return "-" if value is None else f"{value:,.{digits}f}"


def _fmt_cents(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}c"


def _fmt_seconds(value_ms: int | None) -> str:
    if value_ms is None:
        return "-"
    total = max(0, int(value_ms / 1000))
    minutes, seconds = divmod(total, 60)
    return f"{minutes:02d}:{seconds:02d}"


def build_dashboard(
    mode_label: str,
    markets: dict[str, MarketRuntime],
    symbol_states: dict[str, SymbolRuntime],
    opportunities: list[Opportunity],
    open_positions: list[PaperPosition],
    settled_positions: list[PaperPosition],
) -> Panel:
    header = Text()
    header.append("Polymarket Bot ", style="bold cyan")
    header.append(f"[mode={mode_label}]", style="bold yellow")
    header.append("  Native Binance x RTDS Binance x RTDS Chainlink", style="white")

    feeds_table = Table(expand=True)
    feeds_table.add_column("Asset", style="bold")
    feeds_table.add_column("Native Binance")
    feeds_table.add_column("PM Binance")
    feeds_table.add_column("PM Chainlink")
    feeds_table.add_column("Lead USD")
    feeds_table.add_column("Lead bps")

    for asset in sorted(symbol_states):
        runtime = symbol_states[asset]
        native = runtime.native_binance.price if runtime.native_binance else None
        pm_binance = runtime.polymarket_binance.price if runtime.polymarket_binance else None
        pm_chainlink = runtime.polymarket_chainlink.price if runtime.polymarket_chainlink else None
        lead_usd = native - pm_chainlink if native is not None and pm_chainlink is not None else None
        lead_bps = ((native - pm_chainlink) / pm_chainlink) * 10_000 if native is not None and pm_chainlink not in (None, 0) else None
        feeds_table.add_row(
            asset,
            _fmt_price(native),
            _fmt_price(pm_binance),
            _fmt_price(pm_chainlink),
            "-" if lead_usd is None else f"{lead_usd:+.2f}",
            "-" if lead_bps is None else f"{lead_bps:+.1f}",
        )

    markets_table = Table(expand=True)
    markets_table.add_column("Market", style="bold")
    markets_table.add_column("Slug")
    markets_table.add_column("Time Left")
    markets_table.add_column("PTB")
    markets_table.add_column("Up")
    markets_table.add_column("Down")
    markets_table.add_column("Status")

    market_keys = sorted(markets, key=lambda key: (markets[key].window_minutes, markets[key].asset))
    for key in market_keys:
        market = markets[key]
        time_left = market.time_left_ms(market.last_refresh_ms or 0)
        markets_table.add_row(
            market.label,
            short_slug(market.market_slug),
            _fmt_seconds(time_left),
            _fmt_price(market.price_to_beat),
            _fmt_cents(market.up_buy_price * 100 if market.up_buy_price is not None else None),
            _fmt_cents(market.down_buy_price * 100 if market.down_buy_price is not None else None),
            market.status,
        )

    opportunities_table = Table(expand=True)
    opportunities_table.add_column("Signal", style="bold")
    opportunities_table.add_column("Side")
    opportunities_table.add_column("Confidence")
    opportunities_table.add_column("Mkt Price")
    opportunities_table.add_column("Edge")
    opportunities_table.add_column("Gap")
    opportunities_table.add_column("Reason")

    for opportunity in sorted(opportunities, key=lambda item: item.edge_cents, reverse=True)[:8]:
        opportunities_table.add_row(
            opportunity.label,
            opportunity.side.value,
            f"{opportunity.confidence * 100:.1f}%",
            _fmt_cents(opportunity.market_price_cents),
            f"{opportunity.edge_cents:+.1f}c",
            f"{opportunity.lead_gap_bps:+.1f} bps",
            opportunity.reason,
        )

    positions_table = Table(expand=True)
    positions_table.add_column("Position", style="bold")
    positions_table.add_column("Side")
    positions_table.add_column("Stake")
    positions_table.add_column("Entry")
    positions_table.add_column("Status")
    positions_table.add_column("PnL")

    display_positions = list(open_positions) + list(settled_positions[-5:])
    if not display_positions:
        positions_table.add_row("-", "-", "-", "-", "No positions yet", "-")
    else:
        for position in display_positions:
            pnl_text = "-" if position.pnl_usdc is None else f"{position.pnl_usdc:+.2f}"
            positions_table.add_row(
                short_slug(position.market_slug, 28),
                position.side.value,
                f"{position.stake_usdc:.2f}",
                _fmt_cents(position.entry_price_cents),
                position.status,
                pnl_text,
            )

    content = Group(
        header,
        "",
        Panel(feeds_table, title="Feed Health", border_style="cyan"),
        "",
        Columns(
            [
                Panel(markets_table, title="Active Markets", border_style="green"),
                Panel(opportunities_table, title="Top Signals", border_style="magenta"),
            ],
            expand=True,
        ),
        "",
        Panel(positions_table, title="Paper Execution", border_style="yellow"),
    )
    return Panel(content, border_style="bright_blue")

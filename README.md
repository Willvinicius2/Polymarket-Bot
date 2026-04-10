# Polymarket Bot

Python-first trading bot for Polymarket crypto markets.

This repository now focuses on:

- native Binance trade stream monitoring
- Polymarket RTDS Binance feed monitoring
- Polymarket RTDS Chainlink feed monitoring
- automatic discovery of active crypto `Up or Down` series in minute-based windows
- autonomous paper execution driven by lead/lag signals
- a rich live dashboard that is easy to read while the bot is running

The old JavaScript implementation is still in [`src/`](./src) as a reference, but the new primary runtime lives in `polybot/`.

## Current strategy focus

The first version is built around a specific hypothesis:

- native Binance can lead Polymarket's mirrored Chainlink stream in the final part of short recurring markets
- when that lead is large enough, and the market is still priced off a lagging state, `Up` or `Down` shares can become mispriced

So the bot measures:

- native Binance vs Polymarket RTDS Binance
- native Binance vs Polymarket RTDS Chainlink
- current market buy price vs our modeled directional confidence

It also keeps a paper-trading loop running so we can validate the strategy before enabling live trading.

## Asset coverage

The bot is designed to scan any supported crypto series that Polymarket currently exposes in recurring minute windows.

Right now the official RTDS crypto symbols documented by Polymarket are:

- BTC
- ETH
- SOL
- XRP

Series discovery is automatic for minute-based `Up or Down` series. If Polymarket adds a new supported minute series, the bot should pick it up on the next discovery cycle.

## Interface

The default interface is a full-screen rich dashboard with:

- feed health per asset
- active markets
- top signals
- autonomous paper positions and PnL

The bot also writes a machine-readable snapshot to `state/latest_snapshot.json`, so we can add a web UI later without changing the core engine.

## Requirements

- Python 3.12+
- Node.js (for the JavaScript version in `src/`)

## Install

### Python version (recommended)

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

### JavaScript version (legacy)

```bash
npm install
```

## Run

### Python version

Live dashboard:

```bash
python -m polybot.app
```

Headless mode:

```bash
python -m polybot.app --no-ui
```

One refresh cycle only:

```bash
python -m polybot.app --once --no-ui
```

### JavaScript version

```bash
node src/index.js
```

**Interactive controls:**
- Press `1` to switch to **SIMULACAO** mode (paper trading)
- Press `2` to switch to **REAL** mode (live trading - use with caution!)
- Press `Ctrl+C` to exit

## Environment

Copy `.env.example` to `.env` and adjust values if needed.

### Python version

Main knobs:

- `POLYBOT_MODE=paper` (use `live` for real trading)
- `POLYBOT_ORDER_AMOUNT_USDC`
- `POLYBOT_MIN_EDGE_CENTS`
- `POLYBOT_MIN_LEAD_GAP_BPS`
- `POLYBOT_MARKET_REFRESH_SECONDS`

### JavaScript version

Main knobs:

- `EXECUTION_MODE=simulacao` (use `real` for real trading)
- `POLYMARKET_SERIES_ID`
- `POLYMARKET_AUTO_SELECT_LATEST`

## Live trading credentials

Paper/simulation mode works without private credentials.

For live Polymarket execution, configure these in your `.env` file:

- `POLYMARKET_PRIVATE_KEY`
- `POLYMARKET_API_KEY`
- `POLYMARKET_API_SECRET`
- `POLYMARKET_API_PASSPHRASE`
- `POLYMARKET_FUNDER_ADDRESS`

Optional but useful later:

- a dedicated Chainlink / sponsored crypto price access path if we expand beyond the public RTDS-supported symbols

## Notes

- This is a high-risk trading system, not a guaranteed-profit system.
- The current default is aggressive paper execution, not live execution.
- The research notes that shaped this version are in [`docs/research-notes.md`](./docs/research-notes.md).

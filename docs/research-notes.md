# Research Notes

## What the official docs confirm

- Polymarket RTDS officially streams crypto prices from two sources: `crypto_prices` (Binance) and `crypto_prices_chainlink` (Chainlink).
- The current RTDS endpoint is `wss://ws-live-data.polymarket.com`.
- Supported RTDS crypto symbols are currently:
  - Binance source: `btcusdt`, `ethusdt`, `solusdt`, `xrpusdt`
  - Chainlink source: `btc/usd`, `eth/usd`, `sol/usd`, `xrp/usd`
- Polymarket says the display price is normally the midpoint of the bid/ask spread. If the spread is wider than 10 cents, Polymarket falls back to the last traded price.
- Polymarket L2 trading requires API credentials plus a private key / funder address.
- Polymarket maker rebates are active in crypto markets, with a rebate pool funded by taker fees. Crypto rebate distribution is currently documented as 20 percent of the eligible taker fee pool, weighted by executed maker liquidity.

## Why this matters for our bot

- We can measure three feeds at the same time:
  - native Binance stream
  - Polymarket mirrored Binance stream
  - Polymarket mirrored Chainlink stream
- That lets us separate:
  - native exchange move
  - RTDS relay lag
  - Chainlink lag against exchange price
- The first strategy pass should focus on markets whose resolution is explicitly tied to Chainlink price streams, because that is where a lead/lag edge is most testable.

## First market basket

- `BTC Up or Down 15m` (`series_id=10192`)
- `ETH Up or Down 5m` (`series_id=10683`)
- `Solana Up or Down Hourly` (`series_id=10122`)
- `XRP` is kept in monitoring mode for feed analytics even when we do not yet have a default directional market series configured.

## Strategy directions

- Latency lead:
  - compare native Binance against RTDS Chainlink near settlement windows
  - look for cases where Binance has already crossed the effective threshold and Chainlink has not caught up
- RTDS relay quality:
  - compare native Binance against RTDS Binance to estimate how much delay comes from Polymarket relay versus Chainlink itself
- Market mispricing:
  - compare our directional confidence against current `Up` / `Down` buy prices from the CLOB
- Maker rebate mode:
  - useful later for quieter markets with wider spreads, but not the first edge we should automate

## Social/X takeaway

- I attempted to use current X search as requested, but the accessible public results were low-signal and not reliable enough to treat as a primary base for the trading logic.
- Because of that, the implementation is anchored mainly in official Polymarket docs plus live market structure, and social signals should only be used as hypotheses to test in logs.

## Source links

- Polymarket RTDS: https://docs.polymarket.com/market-data/websocket/rtds
- Polymarket changelog: https://docs.polymarket.com/changelog
- Polymarket price calculation help: https://help.polymarket.com/en/articles/13364488-how-are-prices-calculated
- Polymarket L2 client docs: https://docs.polymarket.com/trading/clients/l2
- Polymarket maker rebates: https://docs.polymarket.com/market-makers/maker-rebates
- py-clob-client on PyPI: https://pypi.org/project/py-clob-client/
- Binance WebSocket streams: https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams

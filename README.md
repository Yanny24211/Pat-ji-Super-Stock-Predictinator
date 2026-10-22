# Investopedia AI Trader (paper trading)

Core + satellite strategy from `profile.yaml`: a scheduled buy of one global equity ETF, plus a small AI-driven
satellite. Claude researches a watchlist (fundamentals, headlines, market context) and proposes buys; a
deterministic risk gate enforces position, count and budget limits; you approve each order.

## Setup
1. `pip install -r requirements.txt` and `export ANTHROPIC_API_KEY=...`
2. Try it with no Investopedia account: `python main.py` (uses a local paper ledger).
3. For Investopedia: create a game with $6,000 starting cash, install Node.js, then
   `git clone https://github.com/dchrostowski/investopedia_simulator_api`, copy `credentials_example.json` to
   `credentials.json` there and fill it in, `pip install -r` its requirements.txt, then
   `INVESTOPEDIA_LIB=/path/to/investopedia_simulator_api python main.py --broker investopedia`
4. Optional phone alerts: `export NTFY_TOPIC=your-private-topic` (ntfy.sh).

## Exits (satellite only; the core ETF is never sold)
1. Stop-loss: sells the whole position if it is down `stop_loss_pct` vs cost. Always allowed.
2. Trim: sells down toward `max_position_pct` if a position grows past `trim_above_pct` of equity.
3. AI review: Claude defaults to "hold" and may recommend a sell only if the thesis looks broken. It must cite
   evidence, meet `min_confidence`, respect `min_hold_days` and the monthly trade cap.
Rule-based exits are exempt from the monthly cap. Symbols with a pending order are skipped, and a symbol sold
in a run is not re-bought in the same run.

## Caveats
- Investopedia has no official API. This relies on an unofficial community library that may break at any time,
  and I could not verify that Investopedia's terms allow automated access. Check them first.
- Market orders may not fill until the next open, so cash can look unchanged right after an order. Watchlist
  symbols must be US-listed. Every decision is logged in `logs/decisions.jsonl`; hold periods are measured from
  your last logged buy, so positions opened outside this app count as old enough to sell.
- Simulated results prove little. Treat this as a test of the pipeline, not of the strategy.

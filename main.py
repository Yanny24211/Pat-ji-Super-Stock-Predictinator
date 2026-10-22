"""Usage: python main.py [--broker paper|investopedia] [--yes]
Run monthly (cron / Task Scheduler). Every order is shown with its rationale and needs your approval.
Order of work: rule-based exits -> AI sell review -> core buy -> AI satellite buys."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import yaml
import agent
import risk
from brokers import make_broker

ROOT = Path(__file__).parent
LOG = ROOT / "logs" / "decisions.jsonl"


def log(kind, **kw):
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "kind": kind, **kw}, default=str) + "\n")


def read_log():
    return [json.loads(x) for x in LOG.read_text().splitlines() if x.strip()] if LOG.exists() else []


def trades_this_month():
    """AI-driven satellite trades (buys and sells). Rule-based exits are exempt from the cap."""
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return sum(1 for r in read_log() if r["kind"] == "trade" and r.get("role") == "satellite" and r["ts"].startswith(month))


def days_since_buy(sym):
    buys = [r["ts"] for r in read_log() if r["kind"] == "trade" and r.get("side") == "buy" and r["symbol"] == sym]
    return (datetime.now(timezone.utc) - datetime.fromisoformat(max(buys))).days if buys else None


def notify(text):
    print("\n" + text)
    topic = os.getenv("NTFY_TOPIC")  # optional phone push via ntfy.sh
    if topic:
        import requests
        requests.post(f"https://ntfy.sh/{topic}", data=text.encode(), timeout=10)


def place(broker, side, role, sym, qty, price, why, auto):
    if qty < 1:
        return False
    notify(f"[{role.upper()}] {side.upper()} {qty} {sym} @ ~${price:,.2f} (~${qty * price:,.0f})\n{why}")
    if auto or input("Approve this order? [y/N] ").strip().lower() == "y":
        getattr(broker, side)(sym, qty)
        log("trade", side=side, role=role, symbol=sym, qty=qty, price=price)
        print("Order submitted.")
        return True
    log("rejected", side=side, role=role, symbol=sym)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", default="paper", choices=["paper", "investopedia"])
    ap.add_argument("--yes", action="store_true", help="skip approval prompts (simulator only)")
    args = ap.parse_args()
    prof = yaml.safe_load((ROOT / "profile.yaml").read_text())
    auto = args.yes or prof.get("auto_approve", False)
    broker = make_broker(args.broker, prof)
    core = prof["core"]["symbol"]
    market = agent.market_context()
    s, pending, acted = broker.snapshot(), broker.open_symbols(), set()

    # 1) Rule-based exits: stop-loss and trim (satellite only)
    for sym, qty, why in risk.forced_exits(s, prof):
        if sym not in pending:
            acted.add(sym)
            place(broker, "sell", "risk", sym, qty, s["positions"][sym]["price"], why, auto)
    s = broker.snapshot()

    # 2) AI sell review of remaining satellite holdings
    held = {k: v for k, v in s["positions"].items() if k != core and k not in pending and k not in acted}
    if held:
        data = agent.gather(list(held))
        for k, v in held.items():
            if k in data:
                data[k]["position"] = {"gain_pct": round((v["price"] / (v.get("cost") or v["price"]) - 1) * 100, 1),
                                       "days_held": days_since_buy(k)}
        for p in agent.review(prof, data, market, s):
            sym = p.get("symbol")
            if sym not in held:
                continue
            ok, reason, qty = risk.check_sell(p, held[sym], prof, trades_this_month(), days_since_buy(sym))
            log("review", accepted=ok, reason=reason, **p)
            print(f"{sym}: {p.get('action')} (conf {p.get('confidence')}) -> {reason}")
            if ok:
                acted.add(sym)
                why = f"Reason: {p['rationale']}\nCase for holding: {p['case_for_holding']}\nEvidence: {p['evidence']}"
                place(broker, "sell", "satellite", sym, qty, held[sym]["price"], why, auto)
        s = broker.snapshot()

    # 3) Core: deterministic scheduled buy toward target weight (never sold)
    cfg = prof["core"]
    px = agent.get_price(core)
    gap = s["equity"] * cfg["target_pct"] / 100 - s["positions"].get(core, {"qty": 0})["qty"] * px
    amt = min(gap, s["cash"], prof["monthly_core_buy_usd"])
    if core not in pending:
        place(broker, "buy", "core", core, int(amt // px), px, "Scheduled core buy toward target weight.", auto)

    # 4) AI satellite buys
    s = broker.snapshot()
    cands = [x for x in prof["watchlist"] if x not in s["positions"] and x not in pending and x not in acted]
    data = agent.gather(cands)
    for p in agent.propose(prof, data, market, s):
        ok, reason, qty = risk.check(p, data, s, prof, trades_this_month())
        log("proposal", accepted=ok, reason=reason, **p)
        print(f"{p.get('symbol')}: {p.get('action')} (conf {p.get('confidence')}) -> {reason}")
        if ok:
            why = f"Thesis: {p['thesis']}\nRisks: {p['risks']}\nBear case: {p['bear_case']}\nEvidence: {p['evidence']}"
            if place(broker, "buy", "satellite", p["symbol"], qty, data[p["symbol"]]["price"], why, auto):
                s = broker.snapshot()


if __name__ == "__main__":
    main()

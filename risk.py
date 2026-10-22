"""Deterministic gate. Every AI proposal must pass these rules before it can become an order."""
import math


def check(p, data, s, prof, trades_this_month):
    sat, core = prof["satellite"], prof["core"]["symbol"]
    sym = p.get("symbol")
    if p.get("action") != "buy":
        return False, "not a buy", 0
    if sym not in data or not data[sym].get("price"):
        return False, "unknown symbol or no price data", 0
    if not p.get("evidence"):
        return False, "no cited evidence", 0
    if p.get("confidence", 0) < sat["min_confidence"]:
        return False, "confidence below minimum", 0
    if trades_this_month >= sat["max_trades_per_month"]:
        return False, "monthly trade cap reached", 0
    held = {k: v for k, v in s["positions"].items() if k != core}
    if len(held) >= sat["max_positions"]:
        return False, "max satellite positions reached", 0
    sat_budget = s["equity"] * sat["target_pct"] / 100 - sum(v["qty"] * v["price"] for v in held.values())
    cap = min(sat_budget, s["equity"] * sat["max_position_pct"] / 100, s["cash"])
    qty = math.floor(cap / data[sym]["price"])
    return (qty >= 1), ("ok" if qty >= 1 else "insufficient satellite budget"), max(qty, 0)


def forced_exits(s, prof):
    """Rule-based satellite exits (stop-loss, trim). The core ETF is never sold."""
    sat, core = prof["satellite"], prof["core"]["symbol"]
    out = []
    for sym, v in s["positions"].items():
        if sym == core:
            continue
        chg = (v["price"] / (v.get("cost") or v["price"]) - 1) * 100
        w = v["qty"] * v["price"] / s["equity"] * 100
        if chg <= -sat["stop_loss_pct"]:
            out.append((sym, v["qty"], f"Stop-loss: down {chg:.1f}% vs cost (limit -{sat['stop_loss_pct']}%)."))
        elif w > sat["trim_above_pct"]:
            excess = v["qty"] * v["price"] - s["equity"] * sat["max_position_pct"] / 100
            qty = int(excess // v["price"])
            if qty >= 1:
                out.append((sym, qty, f"Trim: {w:.1f}% of equity (limit {sat['trim_above_pct']}%); "
                                      f"selling back toward {sat['max_position_pct']}%."))
    return out


def check_sell(p, pos, prof, trades_this_month, days_held):
    sat = prof["satellite"]
    if p.get("action") != "sell":
        return False, "hold", 0
    if not p.get("evidence"):
        return False, "no cited evidence", 0
    if p.get("confidence", 0) < sat["min_confidence"]:
        return False, "confidence below minimum", 0
    if days_held is not None and days_held < sat["min_hold_days"]:
        return False, f"held {days_held}d, minimum is {sat['min_hold_days']}d", 0
    if trades_this_month >= sat["max_trades_per_month"]:
        return False, "monthly trade cap reached", 0
    return True, "ok", pos["qty"]

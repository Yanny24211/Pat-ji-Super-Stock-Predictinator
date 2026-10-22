"""Broker adapters. Both expose snapshot(), buy(), sell(), open_symbols().
Positions: {symbol: {qty, price, cost}} where cost is the average purchase price."""
import json
import os
import sys
from pathlib import Path
from agent import get_price

ROOT = Path(__file__).parent


def num(x):
    return float(str(x).replace("$", "").replace(",", "").strip())


class PaperBroker:
    """Local ledger; works with no Investopedia account."""
    def __init__(self, prof):
        self.f = ROOT / "paper_state.json"
        self.st = json.loads(self.f.read_text()) if self.f.exists() else {"cash": prof["starting_cash"], "positions": {}}
        for k, v in list(self.st["positions"].items()):  # migrate older qty-only format
            if not isinstance(v, dict):
                self.st["positions"][k] = {"qty": v, "cost": get_price(k)}

    def _save(self):
        self.f.write_text(json.dumps(self.st))

    def snapshot(self):
        pos = {k: {"qty": v["qty"], "price": get_price(k), "cost": v["cost"]} for k, v in self.st["positions"].items()}
        eq = self.st["cash"] + sum(v["qty"] * v["price"] for v in pos.values())
        return {"cash": self.st["cash"], "positions": pos, "equity": eq}

    def open_symbols(self):
        return set()

    def buy(self, sym, qty):
        px = get_price(sym)
        cur = self.st["positions"].get(sym, {"qty": 0, "cost": 0})
        tot = cur["qty"] + qty
        self.st["positions"][sym] = {"qty": tot, "cost": (cur["qty"] * cur["cost"] + qty * px) / tot}
        self.st["cash"] -= qty * px
        self._save()

    def sell(self, sym, qty):
        cur = self.st["positions"][sym]
        qty = min(qty, cur["qty"])
        self.st["cash"] += qty * get_price(sym)
        cur["qty"] -= qty
        if cur["qty"] == 0:
            del self.st["positions"][sym]
        self._save()


class InvestopediaBroker:
    """Wraps github.com/dchrostowski/investopedia_simulator_api (unofficial; needs Node.js).
    Set INVESTOPEDIA_LIB to the cloned folder; put credentials.json inside it."""
    def __init__(self, prof):
        lib = os.environ["INVESTOPEDIA_LIB"]
        sys.path.insert(0, lib)
        os.chdir(lib)  # the library loads files relative to its own folder
        from investopedia_api import InvestopediaApi
        self.client = InvestopediaApi(json.load(open("credentials.json")))
        self.p = self.client.portfolio

    def snapshot(self):
        self.p.refresh()
        pos = {x.symbol: {"qty": int(num(x.quantity)), "price": num(x.current_price), "cost": num(x.purchase_price)}
               for x in self.p.stock_portfolio}
        return {"cash": num(self.p.cash), "positions": pos, "equity": num(self.p.account_value)}

    def open_symbols(self):
        self.p.refresh()
        return {o.symbol for o in self.p.open_orders}

    def _trade(self, sym, qty, kind):
        from investopedia_api import StockTrade, TransactionType
        t = StockTrade(portfolio_id=self.p.portfolio_id, symbol=sym, quantity=qty,
                       transaction_type=getattr(TransactionType, kind))  # market order, end of day
        t.validate()
        t.execute()

    def buy(self, sym, qty):
        self._trade(sym, qty, "BUY")

    def sell(self, sym, qty):
        self._trade(sym, qty, "SELL")


def make_broker(name, prof):
    return PaperBroker(prof) if name == "paper" else InvestopediaBroker(prof)

"""Data gathering + LLM research. The LLM only proposes; risk.py decides."""
import json
import anthropic
import yfinance as yf

SYSTEM = """You are a cautious equity research analyst for a paper-trading account.
Investor profile: {profile}
Use ONLY the data provided; never invent figures. For EACH candidate return an object with:
symbol, action ("buy" or "pass"), confidence (0-1), thesis, risks, bear_case,
evidence (list of the specific data fields or headlines you relied on).
Recommend "buy" for at most 2 candidates, and only if it clearly fits a long-horizon growth profile.
Respond with a JSON array only."""


def get_price(sym):
    return float(yf.Ticker(sym).fast_info["last_price"])


def market_context():
    out = {}
    for name, sym in {"vix": "^VIX", "sp500": "^GSPC"}.items():
        h = yf.Ticker(sym).history(period="1mo")["Close"]
        out[name] = {"last": round(float(h.iloc[-1]), 2),
                     "1m_change_pct": round((float(h.iloc[-1]) / float(h.iloc[0]) - 1) * 100, 2)}
    return out


def gather(symbols):
    data = {}
    for s in symbols:
        try:
            t = yf.Ticker(s)
            i = t.info or {}
            news = []
            for n in (t.news or [])[:5]:
                title = (n.get("content") or {}).get("title") or n.get("title")
                if title:
                    news.append(title)
            data[s] = {
                "price": i.get("currentPrice") or i.get("regularMarketPrice"),
                "trailing_pe": i.get("trailingPE"), "forward_pe": i.get("forwardPE"),
                "revenue_growth": i.get("revenueGrowth"), "profit_margin": i.get("profitMargins"),
                "debt_to_equity": i.get("debtToEquity"), "beta": i.get("beta"),
                "52w_low": i.get("fiftyTwoWeekLow"), "52w_high": i.get("fiftyTwoWeekHigh"),
                "sector": i.get("sector"), "headlines": news,
            }
        except Exception as e:
            print(f"skip {s}: {e}")
    return data


def propose(prof, data, market, state):
    style = dict(prof["satellite"], horizon="30+ years", style="long-horizon growth")
    r = anthropic.Anthropic().messages.create(
        model=prof.get("model", "claude-sonnet-5-5"), max_tokens=3000,
        system=SYSTEM.format(profile=json.dumps(style)),
        messages=[{"role": "user", "content": json.dumps(
            {"market": market, "candidates": data, "already_held": list(state["positions"])}, default=str)}],
    )
    txt = r.content[0].text
    return json.loads(txt[txt.index("["): txt.rindex("]") + 1])


REVIEW_SYSTEM = """You are a cautious portfolio reviewer for a long-horizon paper-trading account.
Profile: {profile}
For EACH holding decide "hold" or "sell". Default to hold. Sell only if the growth thesis appears broken or
valuation/risk has clearly deteriorated, using ONLY the data provided; never invent figures. Do not sell
because of short-term price moves. Return a JSON array of objects: symbol, action ("hold" or "sell"),
confidence (0-1), rationale, case_for_holding, evidence (specific data fields or headlines relied on). JSON only."""


def review(prof, data, market, state):
    style = dict(prof["satellite"], horizon="30+ years", style="long-horizon growth")
    r = anthropic.Anthropic().messages.create(
        model=prof.get("model", "claude-sonnet-5-5"), max_tokens=3000,
        system=REVIEW_SYSTEM.format(profile=json.dumps(style)),
        messages=[{"role": "user", "content": json.dumps({"market": market, "holdings": data}, default=str)}],
    )
    txt = r.content[0].text
    return json.loads(txt[txt.index("["): txt.rindex("]") + 1])

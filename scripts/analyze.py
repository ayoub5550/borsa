#!/usr/bin/env python3
"""Statistics and charts from data/prices.csv and data/sessions.csv.

Outputs:
  data/yearly.csv          yearly market activity
  data/tickers.csv         per-ticker summary (first/last price, high/low, liquidity)
  charts/*.png             charts used in docs/05-statistics-performance.md
  stdout                   summary tables
Requires: pandas, matplotlib
"""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA, CHARTS = f"{ROOT}/data", f"{ROOT}/charts"
NAMES = {"ALL": "Alliance", "AUR": "El Aurassi", "SAI": "Saidal", "BIO": "Biopharm", "CPA": "CPA",
         "BDL": "BDL", "AYRD": "Ayrade", "AOM": "AOM Invest", "MST": "Moustachir", "CREX": "CRAPC Exp.",
         "ERD": "Eriad Setif", "ROUI": "NCA Rouiba"}


def load():
    p = pd.read_csv(f"{DATA}/prices.csv", parse_dates=["date"])
    s = pd.read_csv(f"{DATA}/sessions.csv", parse_dates=["date"])
    return p, s


def yearly(p, s):
    s["year"] = s.date.dt.year
    y = s.groupby("year").agg(sessions=("session", "count"), value_DA=("value", "sum"),
                              volume=("volume", "sum"), trades=("trades", "sum"),
                              zero_trade_sessions=("trades", lambda x: int((x == 0).sum())))
    y["zero_trade_pct"] = (100 * y.zero_trade_sessions / y.sessions).round(1)
    y["avg_value_per_session_DA"] = (y.value_DA / y.sessions).round(0)
    tick = p[p.market == "main"].groupby(p.date.dt.year).ticker.nunique()
    y["listed_main"] = tick
    y.to_csv(f"{DATA}/yearly.csv")
    return y


def tickers(p):
    rows = []
    for (mkt, tk), g in p.sort_values("date").groupby(["market", "ticker"]):
        traded = g[g.volume > 0]
        last = g.iloc[-1]
        yr = g[g.date >= last.date - pd.Timedelta(days=365)]
        rows.append(dict(
            ticker=tk, name=NAMES.get(tk, ""), market=mkt,
            first_date=g.date.iloc[0].date(), first_close=g.close.iloc[0],
            last_date=last.date.date(), last_close=last.close,
            change_since_first_pct=round(100 * (last.close / g.close.iloc[0] - 1), 1),
            change_1y_pct=round(100 * (last.close / yr.close.iloc[0] - 1), 1) if len(yr) else None,
            high=g.close.max(), high_date=g.loc[g.close.idxmax(), "date"].date(),
            low=g.close.min(), low_date=g.loc[g.close.idxmin(), "date"].date(),
            sessions_listed=len(g), sessions_traded=len(traded),
            traded_pct=round(100 * len(traded) / len(g), 1),
            total_value_DA=round(g.value.sum()),
        ))
    t = pd.DataFrame(rows).sort_values(["market", "first_date"])
    t.to_csv(f"{DATA}/tickers.csv", index=False)
    return t


def charts(p, s, y):
    os.makedirs(CHARTS, exist_ok=True)
    # 1. yearly traded value
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.bar(y.index, y.value_DA / 1e6, color="#1f6f5c")
    ax.set_yscale("log")
    ax.set_title("Bourse d'Alger - equity value traded per year (million DA, log scale)")
    ax.set_ylabel("million DA")
    ax.grid(axis="y", alpha=.3)
    fig.tight_layout()
    fig.savefig(f"{CHARTS}/yearly_value.png", dpi=130)
    plt.close(fig)
    # 2. share of sessions with zero trades
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.bar(y.index, y.zero_trade_pct, color="#b5543c")
    ax.set_title("Share of sessions with ZERO trades (%)")
    ax.grid(axis="y", alpha=.3)
    fig.tight_layout()
    fig.savefig(f"{CHARTS}/zero_trade_sessions.png", dpi=130)
    plt.close(fig)
    # 3. price history of each current main-market stock
    cur = p[p.date >= p.date.max() - pd.Timedelta(days=10)].ticker.unique()
    fig, axes = plt.subplots(4, 3, figsize=(14, 12))
    for ax, tk in zip(axes.flat, sorted(cur)):
        g = p[p.ticker == tk].sort_values("date")
        ax.plot(g.date, g.close, lw=1.2, color="#1f4e79")
        ax.set_title(f"{tk} - {NAMES.get(tk, '')}", fontsize=10)
        ax.grid(alpha=.3)
        ax.tick_params(labelsize=7)
    for ax in list(axes.flat)[len(cur):]:
        ax.axis("off")
    fig.suptitle("Closing price history (DA) - SGBV sessions", fontsize=13)
    fig.tight_layout()
    fig.savefig(f"{CHARTS}/price_history.png", dpi=120)
    plt.close(fig)
    # 4. recent 2 years: CPA & BDL vs IPO price
    fig, ax = plt.subplots(figsize=(11, 5))
    for tk, ipo, c in (("CPA", 2300, "#1f4e79"), ("BDL", 1400, "#1f6f5c")):
        g = p[(p.ticker == tk) & (p.date >= "2024-01-01")].sort_values("date")
        ax.plot(g.date, g.close, label=f"{tk} close", color=c)
        ax.axhline(ipo, ls="--", color=c, alpha=.6, label=f"{tk} IPO price {ipo}")
    ax.legend()
    ax.grid(alpha=.3)
    ax.set_title("CPA and BDL vs IPO price (DA)")
    fig.tight_layout()
    fig.savefig(f"{CHARTS}/cpa_bdl_vs_ipo.png", dpi=130)
    plt.close(fig)


def main():
    p, s = load()
    y = yearly(p, s)
    t = tickers(p)
    charts(p, s, y)
    pd.set_option("display.width", 250)
    print(y.to_string())
    print()
    print(t.to_string(index=False))


if __name__ == "__main__":
    main()

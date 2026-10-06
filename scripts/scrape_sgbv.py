#!/usr/bin/env python3
"""Scrape the full trading history of the Algiers Stock Exchange (SGBV).

Steps (each step is cached on disk, so the script can be re-run safely):
  1. sessions  : list of all sessions per year (id, date, volume, value, trades)
  2. main      : per-session detail page of the main market (close per ticker)
  3. pme       : per-session detail page of the growth/PME market
  4. parse     : build data/sessions.csv and data/prices.csv

Usage:
  python scripts/scrape_sgbv.py all            # everything
  python scripts/scrape_sgbv.py update         # only sessions newer than data/prices.csv
  python scripts/scrape_sgbv.py parse          # rebuild CSVs from the cache

Be polite: max 4 threads, retries with backoff. Standard library only.
"""
import concurrent.futures as cf
import csv
import datetime as dt
import html
import os
import re
import sys
import time
import urllib.parse
import urllib.request

BASE = "https://www.sgbv.dz"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache")
DATA = os.path.join(ROOT, "data")
THREADS = 4
FIRST_PME_ID = 1766  # first session id where the PME page exists (2016)


def http(url, data=None, tries=4):
    body = urllib.parse.urlencode(data).encode() if data else None
    for a in range(tries):
        try:
            req = urllib.request.Request(url, data=body, headers=UA)
            return urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "ignore")
        except Exception:
            time.sleep(2 + 3 * a)
    raise RuntimeError(f"failed: {url}")


def clean(t):
    t = re.sub(r"<script.*?</script>", "", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t))


def num(s):
    return float(s.replace(" ", "").replace(".", "").replace(",", ".")) if s else None


# ---------- 1. sessions ----------
def fetch_sessions(years):
    os.makedirs(f"{CACHE}/years", exist_ok=True)
    sessions = {}
    for y in years:
        p = f"{CACHE}/years/{y}.html"
        if y >= dt.date.today().year or not os.path.exists(p):
            open(p, "w").write(http(f"{BASE}/fr/histo_boc_ajax.php", {"date": str(y), "lang": "fr", "type": "1"}))
        t = open(p).read()
        for m in re.finditer(r"<td>(\d+)</td>\s*<td>(\d\d/\d\d/\d{4})</td>\s*<td>([\d ]*)</td>\s*<td>([\d ,]*)</td>\s*<td>(\d*)</td>", t):
            sid, d, vol, val, n = m.groups()
            sessions[int(sid)] = dict(session=int(sid), date=f"{d[6:]}-{d[3:5]}-{d[:2]}",
                                      volume=int(vol.replace(" ", "") or 0), value=num(val) or 0.0, trades=int(n or 0))
    return sessions


# ---------- 2/3. detail pages ----------
def fetch_detail(kind, sid):
    page = "details_boc" if kind == "main" else "details_boc_pme"
    p = f"{CACHE}/{kind}/{sid}.html"
    if os.path.exists(p) and os.path.getsize(p) > 2000:
        return sid, "cached"
    try:
        open(p, "w").write(http(f"{BASE}/?page={page}&id_sea={sid}&lang=fr"))
        return sid, "ok"
    except RuntimeError:
        return sid, "fail"


def fetch_details(kind, ids):
    os.makedirs(f"{CACHE}/{kind}", exist_ok=True)
    with cf.ThreadPoolExecutor(THREADS) as ex:
        res = list(ex.map(lambda i: fetch_detail(kind, i), ids))
    fails = [i for i, s in res if s == "fail"]
    print(f"{kind}: {len(ids) - len(fails)} ok, {len(fails)} failed {fails[:20]}")


# ---------- 4. parse ----------
MAIN_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,5})\s+((?:\d{1,3}(?: \d{3})*|\d+),\d\d)\s+(\d+)\s+((?:\d{1,3}(?: \d{3})*|\d+),\d\d)\s+(\d+)\b")
PME_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,5})\s+([\d .,]+?)\s+([\d .,]+?)\s+(\d+)\s+([\d ]+,\d\d)\s+(\d+)\b")


def parse_detail(path, pme=False):
    t = clean(open(path, encoding="utf-8", errors="ignore").read())
    j = t.find("Nombre de transactions")
    if j < 0:
        return []
    s = t[j + len("Nombre de transactions"):].split("Evenements")[0]
    out = []
    if pme:
        for tk, c, o, v, val, n in PME_RE.findall(s):
            out.append(dict(ticker=tk, close=num(c), open=num(o), volume=int(v), value=num(val), trades=int(n)))
    else:
        for tk, c, v, val, n in MAIN_RE.findall(s):
            out.append(dict(ticker=tk, close=num(c), open="", volume=int(v), value=num(val), trades=int(n)))
    return out


def build_csv(sessions):
    os.makedirs(DATA, exist_ok=True)
    with open(f"{DATA}/sessions.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, ["session", "date", "volume", "value", "trades"])
        w.writeheader()
        for sid in sorted(sessions):
            w.writerow(sessions[sid])
    rows = []
    for kind in ("main", "pme"):
        d = f"{CACHE}/{kind}"
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            sid = int(f[:-5])
            if sid not in sessions:
                continue
            for r in parse_detail(f"{d}/{f}", kind == "pme"):
                rows.append(dict(date=sessions[sid]["date"], session=sid, market=kind, **r))
    # the PME page sometimes repeats main-market lines (e.g. DAL2): keep the main-market copy
    main_keys = {(r["session"], r["ticker"]) for r in rows if r["market"] == "main"}
    rows = [r for r in rows if r["market"] == "main" or (r["session"], r["ticker"]) not in main_keys]
    rows.sort(key=lambda r: (r["date"], r["market"], r["ticker"]))
    keys = ["date", "session", "market", "ticker", "close", "open", "volume", "value", "trades"]
    with open(f"{DATA}/prices.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, keys)
        w.writeheader()
        w.writerows(rows)
    print(f"prices.csv: {len(rows)} rows, sessions.csv: {len(sessions)} sessions")


def last_session_in_csv():
    p = f"{DATA}/prices.csv"
    if not os.path.exists(p):
        return 0
    with open(p) as fh:
        return max((int(r["session"]) for r in csv.DictReader(fh)), default=0)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    this_year = dt.date.today().year
    # past years are cached after the first run; the current year is always refreshed
    sessions = fetch_sessions(range(1999, this_year + 1))
    if mode == "parse":
        build_csv(sessions)
        return
    start = 1 if mode == "all" else last_session_in_csv() + 1
    ids = [i for i in sorted(sessions) if i >= start]
    fetch_details("main", ids)
    fetch_details("pme", [i for i in ids if i >= FIRST_PME_ID])
    build_csv(sessions)


if __name__ == "__main__":
    main()

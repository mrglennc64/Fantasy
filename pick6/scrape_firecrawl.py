"""Scrape a pick'em board via Firecrawl -> data/boards/<date>.csv. No proxy setup.

Firecrawl renders the page (JS + anti-bot + US proxy, so it reaches geo-blocked
DK Pick6 and bot-walled PrizePicks) and EXTRACTS structured JSON against a schema.
We ask it for every player prop on the board, map stat types to our markets, and
write the board CSV the picker/cron read.

*** YOU supply the key (free tier at firecrawl.dev). I can't hold it. Set: ***
    FIRECRAWL_API_KEY=fc-...

    FIRECRAWL_API_KEY=fc-... python scrape_firecrawl.py 2026-07-06 prizepicks \
        https://app.prizepicks.com/
    # DK Pick6 (Firecrawl uses a US IP so geo-block doesn't matter):
    FIRECRAWL_API_KEY=fc-... python scrape_firecrawl.py 2026-07-06 dk_pick6 \
        https://pick6.draftkings.com/?sport=MLB
"""
from __future__ import annotations

import csv
import json
import os
import sys
import urllib.request

from capture import BOARDS, resolve, slate_rows  # reuse name/game resolution
from feed import norm

STAT_MAP = {
    "strikeouts": "strikeouts", "pitcher strikeouts": "strikeouts",
    "strikeouts thrown": "strikeouts", "hits": "hits", "total bases": "total_bases",
    "home runs": "home_runs", "hits+runs+rbis": "hits_runs_rbis",
    "runs": "runs", "rbis": "rbi", "rbi": "rbi",
}
BATTER = {"hits", "total_bases", "home_runs", "rbi", "runs", "hits_runs_rbis"}
SCHEMA = {
    "type": "object",
    "properties": {"props": {"type": "array", "items": {"type": "object",
        "properties": {"player": {"type": "string"}, "stat": {"type": "string"},
                       "line": {"type": "number"}},
        "required": ["player", "stat", "line"]}}},
    "required": ["props"],
}


def firecrawl(url: str, key: str) -> dict:
    body = json.dumps({
        "url": url, "formats": ["json"], "onlyMainContent": False,
        "waitFor": 4000,
        "jsonOptions": {"schema": SCHEMA,
                        "prompt": "Extract every MLB player prop shown: player "
                                  "name, the stat type, and the line/projection number."},
    }).encode()
    req = urllib.request.Request(
        "https://api.firecrawl.dev/v1/scrape", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def main():
    if len(sys.argv) < 4:
        print(__doc__); return
    date, platform, url = sys.argv[1], sys.argv[2], sys.argv[3]
    key = os.environ.get("FIRECRAWL_API_KEY")
    if not key:
        print("set FIRECRAWL_API_KEY (free tier at firecrawl.dev)"); return

    print(f"scraping {url} via Firecrawl ...")
    try:
        res = firecrawl(url, key)
    except Exception as e:
        print(f"FAILED: {type(e).__name__} {getattr(e,'code','')}"); return
    props = ((res.get("data") or {}).get("json") or {}).get("props") or []
    rows = []
    for p in props:
        market = STAT_MAP.get(str(p.get("stat", "")).strip().lower())
        if market is None or p.get("line") is None or not p.get("player"):
            continue
        rows.append({"player": p["player"], "market": market, "line": float(p["line"])})
    if not rows:
        print(f"no props extracted (got {len(props)} raw items). Check the URL / board is live.")
        return

    by_market = {}
    for r in rows:
        by_market.setdefault(r["market"], []).append(r)
    print(f"extracted {len(rows)} props across {len(by_market)} markets")

    hdr = ["date", "player", "team", "game", "market", "platform", "line", "slot",
           "more_boost", "more_available", "less_available", "notes"]
    os.makedirs(BOARDS, exist_ok=True)
    for market, group in by_market.items():
        is_batter = market in BATTER
        slate = [] if is_batter else slate_rows(date)
        path = os.path.join(BOARDS, f"{date}{'_batters' if is_batter else ''}.csv")
        exists = os.path.exists(path)
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=hdr)
            if not exists:
                w.writeheader()
            for r in group:
                full, game = resolve(r["player"], slate) if slate else (r["player"], "")
                w.writerow({"date": date, "player": full, "team": "", "game": game,
                            "market": market, "platform": platform, "line": r["line"],
                            "slot": "", "more_boost": 1.0, "more_available": "True",
                            "less_available": "True", "notes": "firecrawl"})
        print(f"  {market:14} {len(group):>3} -> {path}")


if __name__ == "__main__":
    main()

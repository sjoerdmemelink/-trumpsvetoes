#!/usr/bin/env python3
"""
Daily updater for trumpsvetoes.com.

Reads three kinds of sources and writes docs/data.json:

  1. Formal vetoes    -> U.S. Senate's official list (counted)
  2. Veto threats     -> Trump's own posts via the Trump's Truth archive (counted)
  3. News headlines   -> Google News RSS, strict filter + outlet allowlist (shown, NOT counted)

Run locally:   python scripts/update_data.py --dry-run
Run for real:  python scripts/update_data.py
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, NavigableString

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "docs" / "data.json"
MANUAL_PATH = ROOT / "scripts" / "manual.json"

START_DATE = date(2026, 11, 4)          # counter starts the day after the midterms
ET_ZONE = ZoneInfo("America/New_York")

SENATE_URL = "https://www.senate.gov/legislative/vetoes/TrumpDJ2.htm"
TRUTH_URLS = [
    "https://www.trumpstruth.org/search?q=veto&sort=desc&per_page=100",
    "https://www.trumpstruth.org/?sort=desc&per_page=100",
]
NEWS_URL = (
    "https://news.google.com/rss/search?"
    "q=Trump+veto+threat+when:14d&hl=en-US&gl=US&ceid=US:en"
)
USER_AGENT = "trumpsvetoes.com daily updater (contact: see site footer)"
# senate.gov rejects bare bot user agents (HTTP 403), so identify as a normal, honest HTTP client:
SENATE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; trumpsvetoes-bot/1.0; +https://trumpsvetoes.com)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}
BALLOTPEDIA_URLS = [
    "https://ballotpedia.org/Donald_Trump:_Vetoed_legislation,_2025-2026",
    "https://ballotpedia.org/Donald_Trump:_Vetoed_legislation,_2025-2027",
    "https://ballotpedia.org/Donald_Trump:_Vetoed_legislation",
]
TIMEOUT = 30

MAX_THREATS = 100
MAX_NEWS = 30
MAX_QUOTE_CHARS = 280

NEWS_ALLOWLIST = {
    "reuters", "associated press", "ap news", "the new york times", "the wall street journal",
    "the washington post", "cnn", "nbc news", "cbs news", "abc news", "politico", "axios",
    "the hill", "bloomberg", "bbc", "bbc news", "npr", "pbs", "pbs newshour", "fox news",
    "usa today", "the guardian", "newsweek",
}

# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------

def log(msg: str) -> None:
    print(msg, flush=True)


def http_get(url: str, headers: dict | None = None) -> str:
    r = requests.get(url, headers=headers or {"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def https(url: str) -> str:
    return re.sub(r"^http://", "https://", url or "")


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


# --------------------------------------------------------------------------------------
# 1. Senate vetoes
# --------------------------------------------------------------------------------------

SESSION_RE = re.compile(r"Congress,\s*\d+(?:st|nd|rd|th)\s*Session\s*\((\d{4})\)", re.I)
BILL_RE = re.compile(r"^(?:H\.R\.|S\.|H\.J\.Res\.|S\.J\.Res\.|H\.Con\.Res\.|S\.Con\.Res\.|H\.Res\.|S\.Res\.)\s*\d+", re.I)


def parse_veto_date(raw: str, year: int) -> date | None:
    raw = clean(raw).replace("Sept", "Sep").replace(".", "")
    for fmt in ("%b %d %Y", "%B %d %Y"):
        try:
            return datetime.strptime(f"{raw} {year}", fmt).date()
        except ValueError:
            continue
    return None


def parse_senate(html: str) -> list[dict]:
    """Return every veto on the Senate page dated on/after START_DATE."""
    soup = BeautifulSoup(html, "html.parser")
    if "Vetoes by President" not in soup.get_text():
        raise ValueError("Senate page layout changed: heading not found")

    year = None
    found_any_row = False
    out: list[dict] = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        row_text = clean(tr.get_text(" "))
        m = SESSION_RE.search(row_text)
        if m:
            year = int(m.group(1))
            continue
        texts = [clean(c.get_text(" ")) for c in cells]
        nonempty = [(c, t) for c, t in zip(cells, texts) if t]
        if len(nonempty) < 4 or not BILL_RE.match(nonempty[0][1]):
            continue
        found_any_row = True
        if year is None:
            raise ValueError("Senate page layout changed: no session year before first bill row")

        bill_cell, bill = nonempty[0]
        subject = nonempty[1][1]
        vdate = parse_veto_date(nonempty[2][1], year)
        status = nonempty[-1][1]
        if vdate is None or vdate < START_DATE:
            continue
        a = bill_cell.find("a", href=True)
        item = {
            "date": vdate.isoformat(),
            "bill": bill,
            "subject": subject,
            "status": status,
            "url": https(a["href"]) if a else SENATE_URL,
        }
        if "pocket" in row_text.lower():
            item["status"] = ("Pocket veto. " + status).strip()
        out.append(item)

    # Sanity check: the page lists the two 2025 vetoes, so we must have seen bill rows.
    if not found_any_row:
        raise ValueError("Senate page layout changed: no bill rows found")
    out.sort(key=lambda v: (v["date"], v["bill"]))
    return out


# --------------------------------------------------------------------------------------
# 1b. Backup source for vetoes: Ballotpedia (cites the Senate record)
# --------------------------------------------------------------------------------------

BP_DATE_RE = re.compile(r"[A-Z][a-z]+ \d{1,2}, \d{4}")
BP_BILL_RE = re.compile(r"^((?:H|S)\.[A-Za-z. ]*\d+)\s*[-\u2013\u2014]\s*(.+)$")


def describe_page(soup: BeautifulSoup, html: str) -> str:
    title = clean(soup.title.get_text()) if soup.title else "no title"
    return f"(got '{title[:80]}', {len(html)} bytes)"


def parse_ballotpedia(html: str) -> list[dict]:
    """Return vetoes dated on/after START_DATE from Ballotpedia.

    Looks for list items shaped like:  <li><b>December 29, 2025</b>: <ul><li><a>H.R.131 - Title</a></li></ul></li>
    anywhere on the page, so it doesn't depend on the exact heading text.
    """
    soup = BeautifulSoup(html, "html.parser")
    seen_any = False
    out: list[dict] = []
    for li in soup.find_all("li"):
        strong = li.find(["b", "strong"], recursive=False)
        m = BP_DATE_RE.search(strong.get_text() if strong else "")
        if not m:
            continue
        subs = []
        for sub in li.find_all("li"):
            a = sub.find("a", href=True)
            bm = BP_BILL_RE.match(clean(a.get_text())) if a else None
            if bm:
                subs.append((a, bm))
        if not subs:
            continue
        try:
            vdate = datetime.strptime(m.group(0), "%B %d, %Y").date()
        except ValueError:
            continue
        seen_any = True
        if vdate < START_DATE:
            continue
        for a, bm in subs:
            out.append({
                "date": vdate.isoformat(),
                "bill": clean(bm.group(1)),
                "subject": clean(bm.group(2)),
                "status": "",
                "url": https(a["href"]),
            })
    if not seen_any:
        raise ValueError("Ballotpedia layout changed: no dated veto entries found " + describe_page(soup, html))
    out.sort(key=lambda v: (v["date"], v["bill"]))
    return out


# --------------------------------------------------------------------------------------
# 1c. Second backup: White House announcements "Congressional Bill H.R. 504 Vetoed"
# --------------------------------------------------------------------------------------

WH_FEEDS = [
    "https://www.whitehouse.gov/briefings-statements/feed/",
    "https://www.whitehouse.gov/feed/",
]
WH_TITLE_RE = re.compile(r"Congressional Bill\s+(.+?)\s+Vetoed", re.I)


def parse_whitehouse_feed(xml_text: str) -> list[dict]:
    from email.utils import parsedate_to_datetime

    root = ET.fromstring(xml_text)
    items = list(root.iter("item"))
    if not items:
        raise ValueError("White House feed has no items")
    out: list[dict] = []
    for item in items:
        title = clean(item.findtext("title") or "")
        m = WH_TITLE_RE.search(title)
        if not m:
            continue
        try:
            d = parsedate_to_datetime(item.findtext("pubDate") or "").astimezone(ET_ZONE).date()
        except (TypeError, ValueError):
            continue
        if d < START_DATE:
            continue
        out.append({
            "date": d.isoformat(),
            "bill": clean(m.group(1)),
            "subject": "Veto announced by the White House",
            "status": "",
            "url": clean(item.findtext("link") or ""),
        })
    out.sort(key=lambda v: (v["date"], v["bill"]))
    return out


# --------------------------------------------------------------------------------------
# 2. Trump's own posts (Trump's Truth archive)
# --------------------------------------------------------------------------------------

POST_DATE_RE = re.compile(r"[A-Z][a-z]+ \d{1,2}, \d{4}, \d{1,2}:\d{2} [AP]M")
MARK_RE = re.compile(r"§§POST\|(.*?)\|(.*?)§§")
NOISE_LINES = re.compile(
    r"^(Original Post|Results per page.*|Prev\. Page|Next Page|\*?\s*\d+|10|25|50|100|"
    r"Video previously posted.*|Image previously posted.*|View \d+ matching posts?.*|"
    r"Identical file|Visual match|Donald J\. Trump|@realDonaldTrump|·)$",
    re.I,
)

THREAT_PATTERNS = [
    re.compile(r"(?:\bwill|\bwould|going to|gonna|\bshall|\bmust|'ll|’ll)\s[^.!?\n]{0,60}\bveto", re.I),
    re.compile(r"\bveto\b[^.!?\n]{0,30}\b(?:it|them|everything|anything)\b", re.I),
    re.compile(r"\bmr\.?\s+veto\b", re.I),
    re.compile(r"\bi\s+veto\b", re.I),
]


def is_threat_text(text: str) -> bool:
    return any(p.search(text) for p in THREAT_PATTERNS)


def parse_truth(html: str) -> list[dict]:
    """Return posts dated on/after START_DATE whose text contains explicit veto-threat language."""
    soup = BeautifulSoup(html, "html.parser")
    n_markers = 0
    for a in soup.find_all("a", href=re.compile(r"/statuses/\d+")):
        label = clean(a.get_text())
        parent_text = a.parent.get_text(" ") if a.parent else ""
        if POST_DATE_RE.fullmatch(label) and "realDonaldTrump" in parent_text:
            href = a["href"]
            if href.startswith("/"):
                href = "https://www.trumpstruth.org" + href
            a.replace_with(NavigableString(f"\n§§POST|{href}|{label}§§\n"))
            n_markers += 1
    if n_markers == 0:
        raise ValueError("Truth archive layout changed: no posts found")

    text = soup.get_text("\n")
    parts = MARK_RE.split(text)  # [pre, href, date, body, href, date, body, ...]
    out: list[dict] = []
    for i in range(1, len(parts), 3):
        href, label, body = parts[i], parts[i + 1], parts[i + 2]
        try:
            dt = datetime.strptime(label, "%B %d, %Y, %I:%M %p").replace(tzinfo=ET_ZONE)
        except ValueError:
            continue
        if dt.date() < START_DATE:
            continue
        lines = [clean(l) for l in body.split("\n")]
        lines = [l for l in lines if l and not NOISE_LINES.match(l)]
        post = clean(" ".join(lines))
        if not post or not is_threat_text(post):
            continue
        if len(post) > MAX_QUOTE_CHARS:
            post = post[: MAX_QUOTE_CHARS - 1].rstrip() + "…"
        out.append({"date": dt.date().isoformat(), "source": "truth", "text": post, "url": href})
    return out


# --------------------------------------------------------------------------------------
# 3. News headlines (not counted)
# --------------------------------------------------------------------------------------

NEWS_PATTERNS = [
    re.compile(r"\b(?:threaten\w*|vow\w*|warn\w*|pledg\w*|promis\w*)\b[^.]{0,50}\bveto", re.I),
    re.compile(r"\bveto threat", re.I),
    re.compile(r"\b(?:will|would|to) veto\b", re.I),
    re.compile(r"\bmr\.?\s+veto\b", re.I),
]


def norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def parse_news(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    out: list[dict] = []
    seen: set[str] = set()
    for item in root.iter("item"):
        title = clean(item.findtext("title") or "")
        link = clean(item.findtext("link") or "")
        src_el = item.find("source")
        outlet = clean(src_el.text if src_el is not None and src_el.text else "")
        pub = item.findtext("pubDate") or ""
        if outlet and title.endswith(" - " + outlet):
            title = title[: -len(outlet) - 3].strip()
        if not title or not link or outlet.lower() not in NEWS_ALLOWLIST:
            continue
        if not any(p.search(title) for p in NEWS_PATTERNS):
            continue
        try:
            d = datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %Z").date()
        except ValueError:
            continue
        if d < START_DATE:
            continue
        key = norm_title(title)
        if key in seen:
            continue
        seen.add(key)
        out.append({"date": d.isoformat(), "title": title, "outlet": outlet, "url": link})
    return out


# --------------------------------------------------------------------------------------
# Merge + write
# --------------------------------------------------------------------------------------

def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def merge_by_url(old: list[dict], new: list[dict], limit: int, hidden: set[str]) -> list[dict]:
    merged: dict[str, dict] = {}
    for it in old + new:
        if it.get("url") and it["url"] not in hidden and it.get("date", "") >= START_DATE.isoformat():
            merged[it["url"]] = it
    return sorted(merged.values(), key=lambda x: (x["date"], x["url"]), reverse=True)[:limit]


def combine_vetoes(old: list[dict], new: list[dict], complete: bool, extra: list[dict], hidden: set[str]) -> list[dict]:
    """A complete source (Senate list, Ballotpedia) replaces what we had.
    A partial source (a recent-items feed) only adds, so a veto never drops off the site
    just because it scrolled out of the feed."""
    base = [] if complete else old
    out = merge_by_url(base, new + extra, 500, hidden)
    out.sort(key=lambda v: (v["date"], v["bill"]))
    return out


def run(dry_run: bool) -> int:
    old = load_json(DATA_PATH, {"vetoes": [], "threats": [], "news": []})
    manual = load_json(MANUAL_PATH, {})
    hidden = set(manual.get("hide_urls", []))
    checks: dict[str, str] = {}

    vetoes = old.get("vetoes", [])
    try:
        vetoes = parse_senate(http_get(SENATE_URL, SENATE_HEADERS))
        checks["senate"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["senate"] = f"failed: {e}"
        log(f"WARNING senate: {e}")
        for url in BALLOTPEDIA_URLS:
            try:
                vetoes = parse_ballotpedia(http_get(url))
                checks["ballotpedia (backup)"] = "ok"
                break
            except Exception as e2:  # noqa: BLE001
                checks["ballotpedia (backup)"] = f"failed: {e2}"
                log(f"WARNING ballotpedia ({url}): {e2}")
        if checks.get("ballotpedia (backup)") != "ok":
            for url in WH_FEEDS:
                try:
                    vetoes = parse_whitehouse_feed(http_get(url))
                    checks["whitehouse feed (backup)"] = "ok"
                    break
                except Exception as e3:  # noqa: BLE001
                    checks["whitehouse feed (backup)"] = f"failed: {e3}"
                    log(f"WARNING whitehouse ({url}): {e3}")

    new_threats: list[dict] = []
    for url in TRUTH_URLS:
        try:
            new_threats = parse_truth(http_get(url))
            checks["truth"] = "ok"
            break
        except Exception as e:  # noqa: BLE001
            checks["truth"] = f"failed: {e}"
            log(f"WARNING truth ({url}): {e}")

    news = old.get("news", [])
    try:
        news = merge_by_url(news, parse_news(http_get(NEWS_URL)), MAX_NEWS, hidden)
        checks["news"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["news"] = f"failed: {e}"
        log(f"WARNING news: {e}")

    if not any(v == "ok" for v in checks.values()):
        log("ERROR: every source failed; leaving data.json untouched.")
        return 1

    complete = checks.get("senate") == "ok" or checks.get("ballotpedia (backup)") == "ok"
    vetoes = combine_vetoes(old.get("vetoes", []), vetoes, complete, manual.get("add_vetoes", []), hidden)
    threats = merge_by_url(old.get("threats", []), new_threats + manual.get("add_threats", []), MAX_THREATS, hidden)

    data = {
        "start_date": START_DATE.isoformat(),
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "vetoes": vetoes,
        "threats": threats,
        "news": [n for n in news if n["url"] not in hidden],
        "checks": checks,
    }

    added_threats = [t for t in threats if t not in old.get("threats", [])]
    log(f"checks: {checks}")
    log(f"vetoes: {len(vetoes)}  threats: {len(threats)} (+{len(added_threats)} new)  news: {len(data['news'])}")
    for t in added_threats:
        log(f"  NEW THREAT {t['date']}: {t['text'][:100]}  <{t['url']}>")

    if dry_run:
        log("dry run: nothing written.")
        return 0
    DATA_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"wrote {DATA_PATH}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="fetch and report, but don't write data.json")
    sys.exit(run(ap.parse_args().dry_run))

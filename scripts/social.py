#!/usr/bin/env python3
"""
Posts new vetoes and veto threats from docs/data.json to X and Bluesky.

- Runs after update_data.py in the daily workflow.
- Remembers what it already posted in scripts/posted.json, so nothing is posted twice.
- First run (no posted.json yet): marks everything that exists as "already posted"
  and posts nothing, so you never get a flood of old items.
- A platform without credentials is skipped. A failure on one platform never blocks the other.
- News headlines are never posted (they are not counted on the site either).

Secrets (GitHub > Settings > Secrets and variables > Actions):
  X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET
  BSKY_HANDLE, BSKY_APP_PASSWORD

Local test without posting:  DRY_RUN=1 python scripts/social.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "docs" / "data.json"
STATE_PATH = ROOT / "scripts" / "posted.json"

SITE_TEXT = "TrumpsVetoes.com"
SITE_URL = "https://trumpsvetoes.com"
MAX_POSTS_PER_RUN = 5          # safety valve: never flood the timeline
X_LIMIT = 280
BSKY_LIMIT = 300
TIMEOUT = 30
PLATFORMS = ("x", "bluesky")
INTRO_TEXT = ("This account posts automatically whenever President Trump issues a formal veto, "
              "or a veto threat goes on the record, from November 4, 2026 onward. "
              f"Sources and the running count: {SITE_TEXT}")


def log(msg: str) -> None:
    print(msg, flush=True)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def fmt_date(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def shorten(text: str, max_len: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


# --------------------------------------------------------------------------------------
# What to post
# --------------------------------------------------------------------------------------

def item_id(kind: str, item: dict) -> str:
    return f"{kind}:{item.get('url') or item.get('bill') or item.get('date')}"


def build_items(data: dict) -> list[dict]:
    """Every postable item, oldest first, with its message text."""
    out = []
    vetoes = sorted(data.get("vetoes", []), key=lambda v: (v.get("date", ""), v.get("bill", "")))
    for n, v in enumerate(vetoes, start=1):
        subject = shorten(v.get("subject", ""), 140)
        what = f"{v.get('bill', 'A bill')}, {subject}" if subject else v.get("bill", "A bill")
        text = (f"Veto #{n} since Nov 4, 2026: {what}. "
                f"Vetoed {fmt_date(v['date'])}. Running count at {SITE_TEXT}")
        out.append({"id": item_id("veto", v), "date": v["date"], "text": text, "links": []})

    threats = sorted(data.get("threats", []), key=lambda t: (t.get("date", ""), t.get("url", "")))
    for k, t in enumerate(threats, start=1):
        src = t.get("url", "")
        text = (f"Veto threat on the record ({fmt_date(t['date'])}). "
                f"Threats logged since Nov 4, 2026: {k}. Source: {src} · {SITE_TEXT}")
        out.append({"id": item_id("threat", t), "date": t["date"], "text": text, "links": [src] if src else []})

    out.sort(key=lambda i: i["date"])
    return out


def fit(text: str, limit: int) -> str:
    """Trim the message to the platform limit while keeping the site name at the end."""
    if len(text) <= limit:
        return text
    tail = f" {SITE_TEXT}"
    return text[: limit - len(tail) - 1].rstrip() + "…" + tail


# --------------------------------------------------------------------------------------
# X (official API v2, OAuth 1.0a user context)
# --------------------------------------------------------------------------------------

def env(name: str) -> str:
    """Secret value without stray spaces or line breaks that sneak in when pasting."""
    return os.environ.get(name, "").strip()


def post_x(text: str) -> str:
    from requests_oauthlib import OAuth1

    auth = OAuth1(env("X_API_KEY"), env("X_API_SECRET"), env("X_ACCESS_TOKEN"), env("X_ACCESS_SECRET"))
    r = requests.post("https://api.x.com/2/tweets", json={"text": fit(text, X_LIMIT)}, auth=auth, timeout=TIMEOUT)
    if r.status_code >= 300:
        raise RuntimeError(f"X answered {r.status_code}: {r.text[:300]}")
    return r.json().get("data", {}).get("id", "?")


# --------------------------------------------------------------------------------------
# Bluesky (AT Protocol)
# --------------------------------------------------------------------------------------

def bsky_facets(text: str, links: list[str]) -> list[dict]:
    """Make the site name and source URLs clickable. Offsets are in UTF-8 bytes."""
    targets = [(SITE_TEXT, SITE_URL)] + [(u, u) for u in links if u]
    facets = []
    raw = text.encode("utf-8")
    for needle, uri in targets:
        b = needle.encode("utf-8")
        start = raw.find(b)
        if start == -1:
            continue
        facets.append({
            "index": {"byteStart": start, "byteEnd": start + len(b)},
            "features": [{"$type": "app.bsky.richtext.facet#link", "uri": uri}],
        })
    return facets


def post_bluesky(text: str, links: list[str], session: dict) -> str:
    text = fit(text, BSKY_LIMIT)
    record = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "langs": ["en"],
        "facets": bsky_facets(text, links),
    }
    r = requests.post("https://bsky.social/xrpc/com.atproto.repo.createRecord",
                      headers={"Authorization": f"Bearer {session['accessJwt']}"},
                      json={"repo": session["did"], "collection": "app.bsky.feed.post", "record": record},
                      timeout=TIMEOUT)
    if r.status_code >= 300:
        raise RuntimeError(f"Bluesky answered {r.status_code}: {r.text[:300]}")
    return r.json().get("uri", "?")


def bsky_identifier() -> str:
    """Accepts 'name.bsky.social', '@name.bsky.social' or a did:plc: id."""
    ident = env("BSKY_HANDLE").lstrip("@").strip()
    return ident.lower() if not ident.startswith("did:") else ident


def bsky_login() -> dict:
    r = requests.post("https://bsky.social/xrpc/com.atproto.server.createSession",
                      json={"identifier": bsky_identifier(), "password": env("BSKY_APP_PASSWORD")},
                      timeout=TIMEOUT)
    if r.status_code >= 300:
        try:
            detail = r.json()
            detail = f"{detail.get('error', '')}: {detail.get('message', '')}"
        except ValueError:
            detail = r.text[:200]
        raise RuntimeError(f"Bluesky login failed ({r.status_code}) {detail} "
                           f"[identifier used: {bsky_identifier()}, password length: {len(env('BSKY_APP_PASSWORD'))}]")
    return r.json()


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------

def configured(platform: str) -> bool:
    keys = {"x": ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"],
            "bluesky": ["BSKY_HANDLE", "BSKY_APP_PASSWORD"]}[platform]
    return all(os.environ.get(k, "").strip() for k in keys)


def post_intro(state: dict, dry_run: bool) -> bool:
    """One-time introduction post per platform; also a quick test that the credentials work."""
    changed = False
    done = set(state.get("intro", []))
    for platform in PLATFORMS:
        if platform in done:
            log(f"{platform}: intro already posted earlier, skipped.")
            continue
        if not configured(platform):
            log(f"{platform}: no credentials set, intro skipped.")
            continue
        if dry_run:
            log(f"{platform} DRY RUN would post intro: {INTRO_TEXT}")
            continue
        try:
            ref = post_x(INTRO_TEXT) if platform == "x" else post_bluesky(INTRO_TEXT, [], bsky_login())
            state.setdefault("intro", []).append(platform)
            changed = True
            log(f"{platform}: intro posted -> {ref}")
        except Exception as e:  # noqa: BLE001
            log(f"WARNING {platform}: intro failed: {e}")
    return changed


def run(dry_run: bool = False, intro: bool = False) -> int:
    data = load_json(DATA_PATH, {})
    items = build_items(data)
    state = load_json(STATE_PATH, None)

    if state is None:
        state = {p: [i["id"] for i in items] for p in PLATFORMS}
        log(f"First run: marked {len(items)} existing item(s) as already posted. Nothing posted.")
        if intro:
            post_intro(state, dry_run)
        if not dry_run:
            STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        return 0

    changed = post_intro(state, dry_run) if intro else False
    for platform in PLATFORMS:
        done = set(state.get(platform, []))
        todo = [i for i in items if i["id"] not in done]
        if not todo:
            log(f"{platform}: nothing new.")
            continue
        if not configured(platform):
            log(f"{platform}: {len(todo)} new item(s), but no credentials set. Skipped (will retry next run).")
            continue
        if len(todo) > MAX_POSTS_PER_RUN:
            log(f"{platform}: {len(todo)} new items; posting the oldest {MAX_POSTS_PER_RUN} now, the rest next run.")
            todo = todo[:MAX_POSTS_PER_RUN]

        session = None
        for item in todo:
            if dry_run:
                log(f"{platform} DRY RUN would post: {item['text']}")
                continue
            try:
                if platform == "x":
                    ref = post_x(item["text"])
                else:
                    session = session or bsky_login()
                    ref = post_bluesky(item["text"], item["links"], session)
                state.setdefault(platform, []).append(item["id"])
                changed = True
                log(f"{platform}: posted {item['id']} -> {ref}")
            except Exception as e:  # noqa: BLE001
                log(f"WARNING {platform}: could not post {item['id']}: {e}")
                break  # keep order; try again next run

    if changed and not dry_run:
        STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(run(dry_run=os.environ.get("DRY_RUN") == "1", intro=os.environ.get("SOCIAL_INTRO") == "1"))

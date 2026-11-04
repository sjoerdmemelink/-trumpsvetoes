import json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import social as s

DATA = {
  "vetoes": [
    {"date": "2026-12-02", "bill": "H.R. 77", "subject": "Another Test Act", "url": "https://www.congress.gov/b"},
    {"date": "2026-11-20", "bill": "S.5", "subject": "Test Spending Act", "url": "https://www.congress.gov/a"},
  ],
  "threats": [{"date": "2026-11-21", "source": "truth", "text": "I will veto it", "url": "https://www.trumpstruth.org/statuses/50001"}],
  "news": [{"date": "2026-11-21", "title": "x", "url": "https://n/1"}],
}

def setup(tmp, data, state=None):
    s.DATA_PATH = tmp / "data.json"; s.STATE_PATH = tmp / "posted.json"
    s.DATA_PATH.write_text(json.dumps(data))
    if state is not None: s.STATE_PATH.write_text(json.dumps(state))
    elif s.STATE_PATH.exists(): s.STATE_PATH.unlink()

def test_messages():
    items = s.build_items(DATA)
    assert [i["id"].split(":")[0] for i in items] == ["veto", "threat", "veto"], items   # oldest first, news excluded
    assert items[0]["text"].startswith("Veto #1 since Nov 4, 2026: S.5, Test Spending Act. Vetoed Nov 20, 2026."), items[0]
    assert items[2]["text"].startswith("Veto #2"), items[2]
    assert "Threats logged since Nov 4, 2026: 1." in items[1]["text"] and items[1]["links"] == ["https://www.trumpstruth.org/statuses/50001"]
    for i in items:
        assert len(s.fit(i["text"], 280)) <= 280 and s.fit(i["text"], 280).endswith("TrumpsVetoes.com")
    long = s.fit("x" * 400 + " TrumpsVetoes.com", 280)
    assert len(long) <= 280 and long.endswith("TrumpsVetoes.com")
    print("messages ok")

def test_facets_bytes():
    text = "Veto threat… Source: https://a.b/c · TrumpsVetoes.com"
    f = s.bsky_facets(text, ["https://a.b/c"])
    raw = text.encode()
    got = sorted(raw[x["index"]["byteStart"]:x["index"]["byteEnd"]].decode() for x in f)
    assert got == ["TrumpsVetoes.com", "https://a.b/c"], got
    print("facets ok (utf-8 offsets)")

def test_first_run_posts_nothing():
    tmp = Path(tempfile.mkdtemp()); setup(tmp, DATA)
    calls = []
    s.post_x = lambda text: calls.append(text)
    os.environ.update({"X_API_KEY": "a", "X_API_SECRET": "b", "X_ACCESS_TOKEN": "c", "X_ACCESS_SECRET": "d"})
    s.run()
    state = json.loads(s.STATE_PATH.read_text())
    assert calls == [] and len(state["x"]) == 3 and len(state["bluesky"]) == 3, (calls, state)
    print("first run ok (nothing posted, all marked)")

def test_new_item_posted_once_and_retry_on_failure():
    tmp = Path(tempfile.mkdtemp())
    old = {"x": [], "bluesky": []}
    for i in s.build_items(DATA): old["x"].append(i["id"]); old["bluesky"].append(i["id"])
    data2 = json.loads(json.dumps(DATA)); data2["vetoes"].append({"date": "2026-12-10", "bill": "S.9", "subject": "New Act", "url": "https://www.congress.gov/c"})
    setup(tmp, data2, old)
    x_calls, b_calls = [], []
    s.post_x = lambda text: (x_calls.append(text), "1")[1]
    def fail_bsky(text, links, session): raise RuntimeError("down")
    s.post_bluesky = fail_bsky
    s.bsky_login = lambda: {"accessJwt": "t", "did": "d"}
    os.environ.update({"BSKY_HANDLE": "h", "BSKY_APP_PASSWORD": "p"})
    s.run()
    state = json.loads(s.STATE_PATH.read_text())
    assert len(x_calls) == 1 and x_calls[0].startswith("Veto #3 since Nov 4, 2026: S.9, New Act."), x_calls
    assert "veto:https://www.congress.gov/c" in state["x"] and "veto:https://www.congress.gov/c" not in state["bluesky"], state
    s.run()   # second run: X must not post again, Bluesky retries
    assert len(x_calls) == 1, x_calls
    print("posted once on X, Bluesky failure retried next run ok")

def test_skip_without_credentials():
    tmp = Path(tempfile.mkdtemp()); setup(tmp, DATA, {"x": [], "bluesky": []})
    for k in ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET", "BSKY_HANDLE", "BSKY_APP_PASSWORD"]: os.environ.pop(k, None)
    s.run()
    assert json.loads(s.STATE_PATH.read_text()) == {"x": [], "bluesky": []}
    print("skip without credentials ok (nothing marked, retried later)")

def test_max_per_run():
    tmp = Path(tempfile.mkdtemp())
    many = {"vetoes": [{"date": f"2026-12-{d:02d}", "bill": f"S.{d}", "subject": "x", "url": f"https://c/{d}"} for d in range(1, 9)], "threats": []}
    setup(tmp, many, {"x": [], "bluesky": []})
    calls = []
    s.post_x = lambda text: (calls.append(text), "1")[1]
    os.environ.update({"X_API_KEY": "a", "X_API_SECRET": "b", "X_ACCESS_TOKEN": "c", "X_ACCESS_SECRET": "d"})
    s.run()
    assert len(calls) == s.MAX_POSTS_PER_RUN, len(calls)
    print("max posts per run ok")


def test_intro_once():
    tmp = Path(tempfile.mkdtemp()); setup(tmp, {"vetoes": [], "threats": []}, {"x": [], "bluesky": []})
    calls = []
    s.post_x = lambda text: (calls.append(("x", text)), "1")[1]
    s.post_bluesky = lambda text, links, session: (calls.append(("b", text)), "u")[1]
    s.bsky_login = lambda: {"accessJwt": "t", "did": "d"}
    os.environ.update({"X_API_KEY": "a", "X_API_SECRET": "b", "X_ACCESS_TOKEN": "c", "X_ACCESS_SECRET": "d", "BSKY_HANDLE": "h", "BSKY_APP_PASSWORD": "p"})
    s.run(intro=True); s.run(intro=True)
    assert [c[0] for c in calls] == ["x", "b"], calls
    assert len(s.fit(s.INTRO_TEXT, 280)) == len(s.INTRO_TEXT) <= 280, len(s.INTRO_TEXT)
    print("intro posted once per platform ok")

if __name__ == "__main__":
    test_messages(); test_facets_bytes(); test_first_run_posts_nothing(); test_new_item_posted_once_and_retry_on_failure(); test_skip_without_credentials(); test_max_per_run(); test_intro_once()
    print("ALL SOCIAL OK")

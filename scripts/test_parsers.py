import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import update_data as u

SENATE = """
<html><body><h1>Vetoes by President Donald J. Trump</h1>
<table>
<tr><td colspan=9>119th Congress, 1st Session (2025)</td></tr>
<tr><td>Bill No.</td><td></td><td>Subject</td><td></td><td>Veto Date</td><td></td><td>Presidential Message</td><td></td><td>Status</td></tr>
<tr><td><a href="http://www.congress.gov/bill/119th-congress/house-bill/131">H.R.131</a></td><td></td><td>Finish the Arkansas Valley Conduit Act</td><td></td><td>Dec 29</td><td></td><td>H.Doc. 119-119</td><td></td><td>The House sustained the veto on Jan 8, 2026 by vote No. 9 (248-177).</td></tr>
<tr><td colspan=9>119th Congress, 2nd Session (2026)</td></tr>
<tr><td><a href="http://www.congress.gov/bill/119th-congress/house-bill/9999">H.R.9999</a></td><td></td><td>Test Bill Before Start</td><td></td><td>Oct 30</td><td></td><td>H.Doc. 1</td><td></td><td>Pending.</td></tr>
<tr><td><a href="http://www.congress.gov/bill/119th-congress/senate-bill/123">S.123</a></td><td></td><td>Test Bill After Start</td><td></td><td>Nov 20</td><td></td><td>S.Doc. 2</td><td></td><td>The Senate sustained the veto.</td></tr>
<tr><td><a href="http://www.congress.gov/bill/119th-congress/senate-bill/124">S.124</a></td><td></td><td>Pocket Test</td><td></td><td>Dec 28</td><td></td><td>Pocket veto</td><td></td><td>Not subject to override.</td></tr>
</table></body></html>
"""

TRUTH = """
<html><body>
<div class="post"><div class="hdr"><a href="#">@realDonaldTrump</a> · <a href="/statuses/50001">November 20, 2026, 9:15 AM</a></div>
<p>If the Dumocrats send me that spending bill, I will veto it immediately. President DONALD J. TRUMP</p><a href="x">Original Post</a></div>
<div class="post"><div class="hdr"><a href="#">@realDonaldTrump</a> · <a href="/statuses/43483">November 3, 2026, 11:40 PM</a></div>
<a href="x">Original Post</a></div>
<div class="post"><div class="hdr"><a href="#">@realDonaldTrump</a> · <a href="/statuses/50002">November 21, 2026, 7:00 PM</a></div>
<p>The veto process is a long tradition in America. Nice weather today!</p>
<ul><li><a href="/statuses/41266">August 26, 2026, 10:09 PM</a> — Identical file</li></ul></div>
<div class="post"><div class="hdr"><a href="#">@realDonaldTrump</a> · <a href="/statuses/50003">November 22, 2026, 8:00 PM</a></div>
<p>I guess I'll become Mr. Veto.</p></div><div>Results per page</div>
</body></html>
"""

NEWS = """<?xml version="1.0"?><rss><channel>
<item><title>Trump threatens to veto Democratic spending bill - Reuters</title><link>https://news.google.com/a1</link><pubDate>Fri, 20 Nov 2026 14:00:00 GMT</pubDate><source url="https://reuters.com">Reuters</source></item>
<item><title>Trump threatens to veto Democratic spending bill - Politico</title><link>https://news.google.com/a2</link><pubDate>Fri, 20 Nov 2026 15:00:00 GMT</pubDate><source url="https://politico.com">Politico</source></item>
<item><title>Trump threatens to veto Democratic spending bill - Random Blog</title><link>https://news.google.com/a3</link><pubDate>Fri, 20 Nov 2026 15:00:00 GMT</pubDate><source url="https://x.com">Random Blog</source></item>
<item><title>Veto threat issued - Axios</title><link>https://news.google.com/a4</link><pubDate>Mon, 02 Nov 2026 15:00:00 GMT</pubDate><source url="https://axios.com">Axios</source></item>
<item><title>Weather report - CNN</title><link>https://news.google.com/a5</link><pubDate>Fri, 20 Nov 2026 15:00:00 GMT</pubDate><source url="https://cnn.com">CNN</source></item>
</channel></rss>"""

def test_senate():
    v = u.parse_senate(SENATE)
    assert [x["bill"] for x in v] == ["S.123", "S.124"], v
    assert v[0]["url"].startswith("https://www.congress.gov"), v[0]
    assert v[1]["status"].startswith("Pocket veto"), v[1]
    print("senate ok:", [x["bill"] for x in v])

def test_truth():
    t = u.parse_truth(TRUTH)
    ids = [x["url"].rsplit("/", 1)[1] for x in t]
    assert ids == ["50001", "50003"], ids
    assert "Results per page" not in t[1]["text"], t[1]
    print("truth ok:", ids, "|", t[0]["text"][:60])

def test_news():
    n = u.parse_news(NEWS)
    assert len(n) == 1 and n[0]["outlet"] == "Reuters", n
    print("news ok:", n[0]["title"])

def test_threat_regex():
    yes = ["I will veto it", "They send it, I'll veto it.", "Mr. Veto is here", "I veto", "we would surely veto this garbage", "veto everything"]
    no = ["The veto hat is cool", "A veto is a power of the presidency", "Nice day"]
    assert all(u.is_threat_text(s) for s in yes), [s for s in yes if not u.is_threat_text(s)]
    assert not any(u.is_threat_text(s) for s in no), [s for s in no if u.is_threat_text(s)]
    print("regex ok")

def test_layout_change_detected():
    for bad in ["<html><body>nothing</body></html>", "<h1>Vetoes by President</h1><table></table>"]:
        try:
            u.parse_senate(bad); raise SystemExit("should have raised")
        except ValueError: pass
    try:
        u.parse_truth("<html></html>"); raise SystemExit("should have raised")
    except ValueError: pass
    print("layout-change detection ok")


BALLOTPEDIA = """<html><body><h2><span>Trump's vetoes</span></h2>
<p>intro</p><ul>
<li><b>November 20, 2026</b>:<ul>
<li><a href="https://www.congress.gov/bill/119th-congress/senate-bill/5">S.5 - Test Spending Act</a>.<sup>[2]</sup></li>
<li><a href="https://www.congress.gov/bill/119th-congress/house-bill/77">H.R. 77 \u2013 Another Test Act</a></li></ul></li>
<li><b>December 29, 2025</b>:<ul><li><a href="https://www.congress.gov/bill/119th-congress/house-bill/131">H.R.131 - Finish the Arkansas Valley Conduit Act</a></li></ul></li>
</ul><h2>Summary of Trump's vetoes</h2></body></html>"""

def test_ballotpedia():
    v = u.parse_ballotpedia(BALLOTPEDIA)
    assert [x["bill"] for x in v] == ["H.R. 77", "S.5"], v
    assert v[1]["subject"] == "Test Spending Act", v[1]
    for bad in ["<html><body>nothing</body></html>", "<h2>Trump's vetoes</h2>"]:
        try:
            u.parse_ballotpedia(bad); raise SystemExit("should have raised")
        except ValueError: pass
    print("ballotpedia ok:", [x["bill"] for x in v])


BP_WITH_EDIT = """<html><head><title>Donald Trump: Vetoed legislation</title></head><body>
<h2><span class="mw-headline">Trump's vetoes</span><span class="mw-editsection">[edit]</span></h2>
<ul><li><b>November 25, 2026</b>:<ul><li><a href="http://www.congress.gov/bill/119th-congress/senate-bill/9">S.9 - Edit Marker Act</a></li></ul></li></ul></body></html>"""

WH_FEED = """<?xml version="1.0"?><rss><channel>
<item><title>Congressional Bill H.R. 504 Vetoed</title><link>https://www.whitehouse.gov/briefings-statements/2025/12/congressional-bill-h-r-504-vetoed/</link><pubDate>Tue, 30 Dec 2025 01:00:00 +0000</pubDate></item>
<item><title>Congressional Bill S. 5 Vetoed</title><link>https://www.whitehouse.gov/briefings-statements/2026/11/congressional-bill-s-5-vetoed/</link><pubDate>Fri, 20 Nov 2026 20:00:00 +0000</pubDate></item>
<item><title>Something else entirely</title><link>https://www.whitehouse.gov/x/</link><pubDate>Fri, 20 Nov 2026 20:00:00 +0000</pubDate></item>
</channel></rss>"""

def test_ballotpedia_tolerant():
    v = u.parse_ballotpedia(BP_WITH_EDIT)
    assert [x["bill"] for x in v] == ["S.9"], v
    try:
        u.parse_ballotpedia("<html><head><title>Just a moment...</title></head><body>challenge</body></html>")
        raise SystemExit("should have raised")
    except ValueError as e:
        assert "Just a moment" in str(e), e
    print("ballotpedia tolerant + diagnostics ok")

def test_whitehouse():
    v = u.parse_whitehouse_feed(WH_FEED)
    assert [x["bill"] for x in v] == ["S. 5"], v
    print("whitehouse feed ok:", v[0]["bill"], v[0]["date"])

if __name__ == "__main__":
    test_senate(); test_ballotpedia(); test_ballotpedia_tolerant(); test_whitehouse(); test_truth(); test_news(); test_threat_regex(); test_layout_change_detected()
    print("ALL OK")

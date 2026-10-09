import copy
import os
import tempfile
import time
import unittest
import zipfile

from redditalerts import config as config_mod
from redditalerts.engine import run_cycle
from redditalerts.filters import check_post, uniqueness_problem
from redditalerts.store import Store

NOW = time.time()


def post(pid, title, comments=500, **kw):
    p = {
        "id": pid, "name": "t3_" + pid, "title": title, "subreddit": kw.pop("subreddit", "india"),
        "permalink": f"/r/india/comments/{pid}/x/", "num_comments": comments, "score": 900,
        "upvote_ratio": 0.9, "created_utc": NOW - 3 * 3600, "is_self": True, "domain": "self.india",
        "url": f"https://www.reddit.com/r/india/comments/{pid}/x/", "selftext": "", "over_18": False,
        "stickied": False,
    }
    p.update(kw)
    return p


class FakeClient:
    def __init__(self, posts):
        self.posts = posts

    def subreddit(self, name, sort="hot", t=None, limit=100):
        return copy.deepcopy(self.posts)

    search_results = []

    def search(self, *a, **k):
        return copy.deepcopy(self.search_results)

    def top_comments(self, pid, limit=8, subreddit=None):
        return [{"author": "u1", "score": 120, "body": "This is a <test> comment & more"}]


def make_cfg(tmp):
    cfg = config_mod._merge(config_mod.DEFAULTS, {})
    cfg.update(subreddits=["india"], data_dir=os.path.join(tmp, "data"),
               reports_dir=os.path.join(tmp, "reports"))
    cfg["report"]["use_ai"] = False
    return cfg


class FilterTests(unittest.TestCase):
    def setUp(self):
        self.cfg = make_cfg(tempfile.mkdtemp())

    def test_comment_threshold(self):
        self.assertIsNone(check_post(post("a", "Big thread", 300), self.cfg))
        self.assertIn("comments", check_post(post("a", "Small thread", 299), self.cfg))

    def test_blocks_social_links(self):
        p = post("a", "Look at this", is_self=False, domain="x.com",
                 url="https://x.com/someone/status/1")
        self.assertIn("x.com", uniqueness_problem(p, self.cfg))
        p = post("b", "Look", is_self=False, domain="youtu.be", url="https://youtu.be/abc")
        self.assertIsNotNone(uniqueness_problem(p, self.cfg))

    def test_blocks_links_in_text_and_phrases(self):
        p = post("a", "Discussion", selftext="source: https://www.instagram.com/p/xyz/")
        self.assertIn("instagram.com", uniqueness_problem(p, self.cfg))
        p = post("b", "Minister's tweet on the protest goes viral")
        self.assertIn("tweet", uniqueness_problem(p, self.cfg))

    def test_phrase_needs_word_boundary(self):
        # "next post" must not match "x post"
        self.assertIsNone(uniqueness_problem(post("a", "Read the next post about Delhi"), self.cfg))

    def test_reddit_native_media_allowed(self):
        for url, dom in (("https://i.redd.it/abc.jpg", "i.redd.it"),
                         ("https://v.redd.it/abc", "v.redd.it"),
                         ("https://www.reddit.com/gallery/abc", "reddit.com")):
            p = post("a", "Photo from the protest", is_self=False, domain=dom, url=url)
            self.assertIsNone(uniqueness_problem(p, self.cfg), url)

    def test_strict_vs_relaxed_news(self):
        p = post("a", "Court ruling", is_self=False, domain="thehindu.com",
                 url="https://www.thehindu.com/news/x")
        self.assertIsNotNone(uniqueness_problem(p, self.cfg))
        self.cfg["uniqueness_mode"] = "relaxed"
        self.assertIsNone(uniqueness_problem(p, self.cfg))

    def test_crosspost_of_tweet_blocked(self):
        parent = post("orig", "Original", is_self=False, domain="twitter.com",
                      url="https://twitter.com/a/status/1")
        p = post("xp", "Crossposted", crosspost_parent_list=[parent])
        self.assertIsNotNone(uniqueness_problem(p, self.cfg))

    def test_age_nsfw_removed(self):
        self.assertIn("old", check_post(post("a", "x", created_utc=NOW - 100 * 3600), self.cfg))
        self.assertEqual("NSFW", check_post(post("a", "x", over_18=True), self.cfg))
        self.assertEqual("removed", check_post(post("a", "x", selftext="[removed]"), self.cfg))


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = make_cfg(self.tmp)
        self.store = Store(config_mod.resolve_dir(self.cfg, "data_dir"))
        self.posts = [
            post("p1", "Delhi protest: metro stations closed", 900),
            post("p2", "Farmers union joins protest at Jantar Mantar", 700),
            post("p3", "Why is the city on lockdown today", 650, subreddit="delhi"),
            post("p4", "Students detained on the way to Delhi", 400),
            post("p5", "Screenshot of tweet by minister", 2000),
            post("p6", "Small thread", 40),
            post("p7", "Delhi protest: metro stations closed!!", 800),  # same story as p1
        ]

    def test_hourly_limit_and_no_repeats(self):
        client = FakeClient(self.posts)
        r1 = run_cycle(self.cfg, self.store, client)
        self.assertEqual(["p1"], [a["id"] for a in r1["new_alerts"]])  # 3/hour every 20 min -> 1
        ids = []
        for _ in range(4):
            ids += [a["id"] for a in run_cycle(self.cfg, self.store, client)["new_alerts"]]
        self.assertEqual(["p2", "p3"], ids)  # hourly cap of 3 reached, no repeats
        self.assertEqual(3, self.store.sent_in_last_hour())
        # p5 (tweet), p6 (few comments), p7 (duplicate story) are never picked
        self.assertNotIn("p5", self.store.state["sent"])
        self.assertNotIn("p7", self.store.state["sent"])

    def test_state_persists(self):
        run_cycle(self.cfg, self.store, FakeClient(self.posts))
        again = Store(config_mod.resolve_dir(self.cfg, "data_dir"))
        self.assertIn("p1", again.state["sent"])

    def test_report_searches_do_not_become_alerts(self):
        client = FakeClient([])
        client.search_results = [post("g1", "Controller giveaway", 2100, subreddit="Gamesir")]
        res = run_cycle(self.cfg, self.store, client, make_report=True, report_keywords=["SIR"])
        self.assertEqual([], res["new_alerts"])

    def test_report_docx(self):
        self.cfg["report"]["min_comments"] = 50
        res = run_cycle(self.cfg, self.store, FakeClient(self.posts), send=False, make_report=True,
                        report_topic="Delhi Protest")
        self.assertIsNotNone(res["report"], res["errors"])
        path = os.path.join(self.cfg["reports_dir"], res["report"]["file"])
        self.assertTrue(res["report"]["title"].startswith("Reddit Report — Delhi Protest | "))
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode()
            rels = z.read("word/_rels/document.xml.rels").decode()
        self.assertIn("Comprehensive Report", xml)
        self.assertIn("Delhi protest: metro stations closed", xml)
        self.assertIn("https://www.reddit.com/r/india/comments/p1/x/", rels)
        self.assertNotIn("p7/x", rels)  # duplicate story merged
        self.assertIn("&lt;test&gt;", xml)  # text is escaped


if __name__ == "__main__":
    unittest.main()

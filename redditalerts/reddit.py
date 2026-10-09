"""Minimal Reddit client (standard library only).

Order of preference: Reddit API (if app credentials are configured), then Reddit's
public JSON feed, then Reddit's web pages (used automatically when Reddit blocks the
JSON feed on this network)."""

import base64
import json
import logging
import shutil
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

from . import webparse

log = logging.getLogger(__name__)

PUBLIC_BASE = "https://www.reddit.com"
OAUTH_BASE = "https://oauth.reddit.com"


class RedditError(Exception):
    pass


class Blocked(RedditError):
    """Reddit refused its JSON feed for this network (web pages may still work)."""


def _ssl_context():
    try:
        import certifi  # optional; helps on some macOS Python installs
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def http_request(url, headers=None, data=None, method=None, timeout=30):
    """Return (status, body_text). Falls back to the system curl on SSL errors
    (common on fresh macOS Python installs that lack certificates)."""
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        if isinstance(e.reason, ssl.SSLError) and shutil.which("curl"):
            return _curl(url, headers, data, method, timeout)
        raise


def _curl(url, headers, data, method, timeout):
    cmd = ["curl", "-sS", "-m", str(timeout), "-w", "\n%{http_code}"]
    for k, v in (headers or {}).items():
        cmd += ["-H", f"{k}: {v}"]
    if method:
        cmd += ["-X", method]
    if data is not None:
        cmd += ["--data-binary", "@-"]
    out = subprocess.run(cmd + [url], input=data, capture_output=True, check=True).stdout
    body, _, code = out.decode("utf-8", "replace").rpartition("\n")
    return int(code), body


class RedditClient:
    def __init__(self, cfg):
        self.user_agent = cfg["user_agent"]
        self.delay = float(cfg.get("request_delay_seconds", 2.0))
        self.client_id = cfg.get("reddit_client_id") or ""
        self.client_secret = cfg.get("reddit_client_secret") or ""
        self._token = None
        self._token_expiry = 0
        self._last_call = 0.0
        self.mode = "json"

    @property
    def using_oauth(self):
        return bool(self.client_id and self.client_secret)

    def _auth_header(self):
        if not self.using_oauth:
            return {}
        if not self._token or time.time() > self._token_expiry - 60:
            basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
            status, body = http_request(
                PUBLIC_BASE + "/api/v1/access_token",
                headers={"Authorization": "Basic " + basic, "User-Agent": self.user_agent,
                         "Content-Type": "application/x-www-form-urlencoded"},
                data=b"grant_type=client_credentials", method="POST")
            if status != 200:
                raise RedditError(f"Reddit login failed (HTTP {status}). Check the client id/secret.")
            payload = json.loads(body)
            self._token = payload["access_token"]
            self._token_expiry = time.time() + int(payload.get("expires_in", 3600))
        return {"Authorization": "Bearer " + self._token}

    def _fetch(self, url, accept, what):
        """GET with pacing and retries. Returns the body of a 200 response."""
        for attempt in range(4):
            wait = self.delay - (time.time() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.time()
            headers = {"User-Agent": self.user_agent, "Accept": accept}
            if url.startswith(OAUTH_BASE):
                headers.update(self._auth_header())
            try:
                status, body = http_request(url, headers=headers)
            except (urllib.error.URLError, OSError, subprocess.CalledProcessError) as e:
                if attempt == 3:
                    raise RedditError(f"Network error reaching Reddit: {e}")
                time.sleep(5 * (attempt + 1))
                continue
            if status == 200:
                if accept == "text/html" and "reputation-recaptcha" in body and not any(
                        m in body for m in ("<shreddit-post ", "<shreddit-comment ",
                                            "search-telemetry-tracker")):
                    raise RedditError(f"Reddit asked for a captcha on {what}; try again later.")
                return body
            if status == 429 or status >= 500:
                time.sleep(15 * (attempt + 1))
                continue
            if status == 403 and "blocked by network security" in body:
                raise Blocked(f"Reddit blocked this network for {what}")
            if status in (401, 403):
                raise RedditError(f"Reddit refused {what} (HTTP {status}); it may be private or banned.")
            if status == 404:
                raise RedditError(f"Not found: {what}")
            raise RedditError(f"Reddit HTTP {status} for {what}")
        raise RedditError(f"Reddit kept rate-limiting {what}; try again later.")

    def get(self, path, params=None):
        """GET a Reddit JSON path like '/r/india/hot'. Returns parsed JSON."""
        params = dict(params or {})
        params["raw_json"] = 1
        base = OAUTH_BASE + path if self.using_oauth else PUBLIC_BASE + path + ".json"
        body = self._fetch(base + "?" + urllib.parse.urlencode(params), "application/json", path)
        try:
            return json.loads(body)
        except ValueError:
            raise Blocked("Reddit returned a web page instead of data")

    def _web(self, path, params, what):
        return self._fetch(PUBLIC_BASE + path + "?" + urllib.parse.urlencode(params),
                           "text/html", what)

    def _use(self, json_call, web_call):
        """Try Reddit's JSON feed; if Reddit blocks this network, switch to web pages
        for the rest of this run."""
        if self.mode == "json":
            try:
                return json_call()
            except Blocked:
                if self.using_oauth:
                    raise
                log.info("Reddit blocked its data feed on this network; reading web pages instead.")
                self.mode = "web"
        return web_call()

    @staticmethod
    def _posts(listing):
        return [c["data"] for c in listing.get("data", {}).get("children", []) if c.get("kind") == "t3"]

    def subreddit(self, name, sort="hot", t=None, limit=100):
        params = {"limit": limit}
        if t:
            params["t"] = t

        def web():
            wp = {"name": name}
            if t:
                wp["t"] = t
            return webparse.parse_listing(self._web(
                f"/svc/shreddit/community-more-posts/{sort}/", wp, f"r/{name}"))
        return self._use(lambda: self._posts(self.get(f"/r/{name}/{sort}", params)), web)

    def search(self, query, sort="comments", t="day", limit=100):
        def web():
            posts = webparse.parse_search(self._web(
                "/svc/shreddit/search/", {"q": query, "sort": sort, "t": t, "type": "link"},
                f"search '{query}'"))
            self.fill_links(posts)
            return posts
        return self._use(lambda: self._posts(self.get("/search", {
            "q": query, "sort": sort, "t": t, "limit": limit, "type": "link"})), web)

    def fill_links(self, posts):
        """Search pages don't show where a post links to; look that up in one batch.
        Posts whose link stays unknown are kept out of alerts (uniqueness can't be checked)."""
        need = [p for p in posts if p.get("_needs_link")]
        for i in range(0, len(need), 25):
            chunk = need[i:i + 25]
            ids = ",".join("t3_" + p["id"] for p in chunk)
            try:
                feed = self._fetch(f"{PUBLIC_BASE}/by_id/{ids}/.rss", "application/atom+xml",
                                   "post details")
            except RedditError as e:
                log.warning("Could not look up search result links: %s", e)
                continue
            info = webparse.parse_by_id_rss(feed)
            for p in chunk:
                if p["id"] in info:
                    url = info[p["id"]]["url"]
                    p.update(url=url, selftext=info[p["id"]]["selftext"], _needs_link=False)
                    host = (urllib.parse.urlparse(url).hostname or "").lower()
                    p["domain"] = host[4:] if host.startswith("www.") else host
                    p["is_self"] = f"/comments/{p['id']}" in url

    def top_comments(self, post_id, limit=8, subreddit=None):
        """Return the top-level comments (highest scored first) as dicts."""
        def web():
            if not subreddit:
                return []
            return webparse.parse_comments(self._web(
                f"/svc/shreddit/comments/r/{subreddit}/t3_{post_id}", {"sort": "top"},
                "comments"), limit)
        return self._use(lambda: self._json_comments(post_id, limit), web)

    def _json_comments(self, post_id, limit):
        data = self.get(f"/comments/{post_id}", {"sort": "top", "limit": limit * 3, "depth": 1})
        if not isinstance(data, list) or len(data) < 2:
            return []
        comments = []
        for child in data[1].get("data", {}).get("children", []):
            if child.get("kind") != "t1":
                continue
            c = child["data"]
            body = (c.get("body") or "").strip()
            if not body or body in ("[deleted]", "[removed]") or c.get("stickied"):
                continue
            if (c.get("author") or "").lower() == "automoderator":
                continue
            comments.append({"author": c.get("author"), "score": c.get("score", 0), "body": body})
        comments.sort(key=lambda c: c["score"], reverse=True)
        return comments[:limit]

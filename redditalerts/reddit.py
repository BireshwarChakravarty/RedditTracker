"""Minimal Reddit client (standard library only).

Uses Reddit's public JSON pages by default. If Reddit API app credentials are
configured, uses OAuth instead (more reliable from cloud servers).
"""

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

log = logging.getLogger(__name__)

PUBLIC_BASE = "https://www.reddit.com"
OAUTH_BASE = "https://oauth.reddit.com"


class RedditError(Exception):
    pass


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

    def get(self, path, params=None):
        """GET a Reddit path like '/r/india/hot'. Returns parsed JSON."""
        params = dict(params or {})
        params["raw_json"] = 1
        if self.using_oauth:
            url = OAUTH_BASE + path
        else:
            url = PUBLIC_BASE + path + ".json"
        url += "?" + urllib.parse.urlencode(params)
        for attempt in range(4):
            wait = self.delay - (time.time() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.time()
            headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
            headers.update(self._auth_header())
            try:
                status, body = http_request(url, headers=headers)
            except (urllib.error.URLError, OSError, subprocess.CalledProcessError) as e:
                if attempt == 3:
                    raise RedditError(f"Network error reaching Reddit: {e}")
                time.sleep(5 * (attempt + 1))
                continue
            if status == 200:
                try:
                    return json.loads(body)
                except ValueError:
                    raise RedditError("Reddit returned a non-JSON page (possibly a block or captcha).")
            if status == 429 or status >= 500:
                time.sleep(15 * (attempt + 1))
                continue
            if status in (401, 403):
                raise RedditError(
                    f"Reddit refused the request (HTTP {status}) for {path}. The subreddit may be "
                    "private/banned, or Reddit is blocking this network; adding Reddit API "
                    "credentials usually fixes the latter.")
            if status == 404:
                raise RedditError(f"Not found: {path}")
            raise RedditError(f"Reddit HTTP {status} for {path}")
        raise RedditError(f"Reddit kept rate-limiting {path}; try again later.")

    @staticmethod
    def _posts(listing):
        return [c["data"] for c in listing.get("data", {}).get("children", []) if c.get("kind") == "t3"]

    def subreddit(self, name, sort="hot", t=None, limit=100):
        params = {"limit": limit}
        if t:
            params["t"] = t
        return self._posts(self.get(f"/r/{name}/{sort}", params))

    def search(self, query, sort="comments", t="day", limit=100):
        return self._posts(self.get("/search", {"q": query, "sort": sort, "t": t,
                                                "limit": limit, "type": "link"}))

    def top_comments(self, post_id, limit=8):
        """Return the top-level comments (highest scored first) as dicts."""
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

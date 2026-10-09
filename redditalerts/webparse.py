"""Read posts and comments from Reddit's web pages.

Used automatically when Reddit refuses its JSON feed (it blocks many cloud and office
networks). The web pages carry the same facts the alerts need: title, subreddit,
comment count, score, link, post type and age."""

import html
import json
import re
from datetime import datetime

POST_TAG = re.compile(r"<shreddit-post\s[^>]*>", re.S)
COMMENT_TAG = re.compile(r"<shreddit-comment\s[^>]*>", re.S)
TAGS = re.compile(r"<[^>]+>")


def _attr(tag, name):
    m = re.search(r'\s' + re.escape(name) + r'="([^"]*)"', tag)
    return html.unescape(m.group(1)) if m else None


def _flag(tag, name):
    return re.search(r"\s" + re.escape(name) + r'(?:\s|=|>|/)', tag) is not None


def _num(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _ts(value):
    if not value:
        return 0.0
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z").timestamp()
    except ValueError:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0


def _text(fragment):
    text = html.unescape(TAGS.sub(" ", fragment))
    return " ".join(text.split())


def parse_listing(page):
    """Posts from a /svc/shreddit/community-more-posts/... page, as Reddit-JSON-like dicts."""
    posts, seen = [], set()
    for m in POST_TAG.finditer(page):
        tag = m.group(0)
        pid = (_attr(tag, "id") or "").removeprefix("t3_")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        end = page.find("</shreddit-post>", m.end())
        inner = page[m.end(): end if end > 0 else m.end()]
        body = ""
        tb = re.search(r'<shreddit-post-text-body\b.*?</shreddit-post-text-body>', inner, re.S)
        if tb:
            body = _text(tb.group(0))
        flair = re.search(r"<shreddit-post-flair\b.*?</shreddit-post-flair>", inner, re.S)
        domain = _attr(tag, "domain") or ""
        post_type = _attr(tag, "post-type") or ""
        url = _attr(tag, "content-href") or ""
        posts.append({
            "id": pid,
            "title": _attr(tag, "post-title") or "",
            "subreddit": (_attr(tag, "subreddit-name")
                          or (_attr(tag, "subreddit-prefixed-name") or "").removeprefix("r/")),
            "permalink": _attr(tag, "permalink") or "",
            "url": url,
            "domain": domain,
            "num_comments": _num(_attr(tag, "comment-count")),
            "score": _num(_attr(tag, "score")),
            "upvote_ratio": float(_attr(tag, "upvote-ratio") or 0) or None,
            "created_utc": _ts(_attr(tag, "created-timestamp")),
            "is_self": post_type == "text" or domain.startswith("self."),
            "is_gallery": post_type in ("gallery", "multi_media"),
            "post_hint": post_type,
            "over_18": _flag(tag, "nsfw"),
            "stickied": _flag(tag, "stickied") or _flag(tag, "is-post-stickied"),
            "selftext": body,
            "link_flair_text": _text(flair.group(0)) if flair else "",
            "author": _attr(tag, "author"),
        })
    return posts


def parse_search(page):
    """Posts from a /svc/shreddit/search/ page. Links/post types are not on this page,
    so 'url' is left empty (fill it with parse_by_id_rss)."""
    posts, seen = [], set()
    for m in re.finditer(r'data-faceplate-tracking-context="([^"]+)"', page):
        try:
            ctx = json.loads(html.unescape(m.group(1)))
        except ValueError:
            continue
        post = ctx.get("post") or {}
        pid = (post.get("id") or "").removeprefix("t3_")
        if not pid or pid in seen or (ctx.get("action_info") or {}).get("type") not in (None, "post"):
            continue
        anchor = page.find(f'id="search-post-title-t3_{pid}"', m.end())
        if anchor < 0:
            continue
        seen.add(pid)
        block = page[m.start(): page.find("</div>", page.find('data-testid="search-counter-row"', anchor)) + 6]
        link = re.search(r'href="(/r/[^"]+/comments/' + pid + r'/[^"]*)"', block)
        nums = re.findall(r'<faceplate-number[^>]*number="(\d+)"[^>]*>\s*</faceplate-number>\s*(votes?|comments?)', block)
        counts = {kind.rstrip("s"): int(n) for n, kind in nums}
        ts = re.search(r'<faceplate-timeago[^>]*ts="([^"]+)"', block)
        sub = (ctx.get("subreddit") or {}).get("name") or ""
        posts.append({
            "id": pid, "title": post.get("title") or "", "subreddit": sub,
            "permalink": link.group(1) if link else f"/r/{sub}/comments/{pid}/",
            "url": "", "domain": "", "num_comments": counts.get("comment", 0),
            "score": counts.get("vote", 0), "upvote_ratio": None,
            "created_utc": _ts(ts.group(1)) if ts else 0.0, "is_self": False,
            "over_18": bool(post.get("nsfw")), "stickied": False, "selftext": "",
            "link_flair_text": "", "_needs_link": True,
        })
    return posts


def parse_by_id_rss(feed):
    """{post_id: {"url": ..., "selftext": ...}} from a /by_id/t3_a,t3_b/.rss feed."""
    out = {}
    for entry in re.findall(r"<entry>(.*?)</entry>", feed, re.S):
        pid = re.search(r"<id>t3_(\w+)</id>", entry)
        content = re.search(r'<content type="html">(.*?)</content>', entry, re.S)
        if not pid or not content:
            continue
        body = html.unescape(content.group(1))
        link = re.search(r'<a href="([^"]+)">\[link\]</a>', body)
        md = re.search(r'<div class="md">(.*?)</div>', body, re.S)
        out[pid.group(1)] = {"url": html.unescape(link.group(1)) if link else "",
                             "selftext": _text(md.group(1)) if md else ""}
    return out


def parse_comments(page, limit=8):
    """Top-level comments from a /svc/shreddit/comments/... page, best first."""
    comments = []
    for m in COMMENT_TAG.finditer(page):
        tag = m.group(0)
        if _attr(tag, "depth") not in (None, "0"):
            continue
        author = _attr(tag, "author") or ""
        if author.lower() == "automoderator" or _flag(tag, "stickied"):
            continue
        thing = _attr(tag, "thingId") or ""
        body_m = re.search(r'id="' + re.escape(thing) + r'-comment-rtjson-content"[^>]*>(.*?)</div>\s*</div>',
                           page[m.end():m.end() + 20000], re.S) if thing else None
        body = _text(body_m.group(1)) if body_m else ""
        if not body or body in ("[deleted]", "[removed]"):
            continue
        comments.append({"author": author, "score": _num(_attr(tag, "score")), "body": body})
    comments.sort(key=lambda c: c["score"], reverse=True)
    return comments[:limit]

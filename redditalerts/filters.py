"""Rules that decide whether a Reddit post is a unique, high-engagement alert."""

import re
import time
from urllib.parse import urlparse

REDDIT_NATIVE_DOMAINS = ("reddit.com", "redd.it")
URL_RE = re.compile(r"https?://[^\s)\]>\"']+", re.I)


def domain_of(url):
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _matches_domain(host, domains):
    return any(host == d or host.endswith("." + d) for d in domains)


def is_reddit_native(post):
    """Text posts, Reddit-hosted images/videos/galleries, and links to other Reddit posts."""
    if post.get("is_self") or (post.get("domain") or "").startswith("self."):
        return True
    if post.get("is_gallery"):
        return True
    return _matches_domain(domain_of(post.get("url") or ""), REDDIT_NATIVE_DOMAINS)


def _phrase_regex(phrases):
    parts = [re.escape(p.lower()).replace(r"\ ", r"\s+") for p in phrases if p.strip()]
    if not parts:
        return None
    return re.compile(r"(?<![a-z0-9])(" + "|".join(parts) + r")(?![a-z0-9])", re.I)


def normalize_title(title):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).split())


def similar_titles(a, b, threshold=0.8):
    wa, wb = set(normalize_title(a).split()), set(normalize_title(b).split())
    if not wa or not wb:
        return False
    if wa == wb:
        return True
    return len(wa & wb) / len(wa | wb) >= threshold


def source_post(post):
    """For crossposts, the original post (that is where the content really lives)."""
    parents = post.get("crosspost_parent_list") or []
    return parents[0] if parents else post


def uniqueness_problem(post, cfg):
    """Return a reason string if the post's content came from / was shared on another
    platform, else None."""
    if post.get("_needs_link"):
        return "couldn't confirm where it links"
    blocked = [d.lower() for d in cfg["blocked_domains"]]
    for p in (post, source_post(post)):
        link_host = domain_of(p.get("url") or "")
        if link_host and _matches_domain(link_host, blocked):
            return f"links to {link_host}"
        if cfg["uniqueness_mode"] == "strict" and not is_reddit_native(p):
            return f"links to an outside site ({link_host or p.get('domain')})"
        for url in URL_RE.findall(p.get("selftext") or ""):
            host = domain_of(url)
            if _matches_domain(host, blocked):
                return f"text contains a {host} link"
        media = p.get("secure_media") or p.get("media") or {}
        if isinstance(media, dict) and media.get("type") and \
                _matches_domain(str(media.get("type")).lower(), blocked):
            return f"embeds {media.get('type')}"
    rx = _phrase_regex(cfg["blocked_phrases"])
    if rx:
        text = (post.get("title") or "") + "\n" + (post.get("selftext") or "")[:3000]
        m = rx.search(text)
        if m:
            return f"mentions '{m.group(0)}' (likely shared from another platform)"
    return None


def check_post(post, cfg, min_comments=None, now=None, require_unique=True):
    """Return None if the post qualifies, otherwise a short reason for skipping it."""
    now = now or time.time()
    min_comments = cfg["min_comments"] if min_comments is None else min_comments
    if post.get("num_comments", 0) < min_comments:
        return f"only {post.get('num_comments', 0)} comments"
    age_h = (now - float(post.get("created_utc", now))) / 3600
    if age_h > cfg["max_post_age_hours"]:
        return f"too old ({age_h:.0f}h)"
    if post.get("removed_by_category") or post.get("selftext") in ("[removed]", "[deleted]"):
        return "removed"
    if cfg["skip_nsfw"] and post.get("over_18"):
        return "NSFW"
    if cfg["skip_pinned_posts"] and post.get("stickied"):
        return "pinned"
    text = (post.get("title") or "") + "\n" + (post.get("selftext") or "")
    block_rx = _phrase_regex(cfg.get("keywords_block") or [])
    if block_rx and block_rx.search(text):
        return "blocked keyword"
    any_rx = _phrase_regex(cfg.get("keywords_any") or [])
    if any_rx and not any_rx.search(text):
        return "no matching keyword"
    if require_unique:
        return uniqueness_problem(post, cfg)
    return None


def dedupe_key(post):
    return source_post(post).get("id") or post.get("id")

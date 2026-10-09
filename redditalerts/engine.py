"""One check cycle: fetch Reddit, pick new alerts, optionally write a report."""

import logging
import math
import time

from . import messages
from .filters import check_post, dedupe_key, similar_titles
from .reddit import RedditError
from .report import build_report

log = logging.getLogger(__name__)


def search_posts(client, queries, errors):
    found = {}
    for q in queries:
        if not q.strip():
            continue
        try:
            for p in client.search(q.strip(), sort="comments", t="day"):
                found[p["id"]] = p
        except RedditError as e:
            errors.append(f"search '{q}': {e}")
    return found


def fetch_pool(cfg, client):
    """All candidate posts from the watched subreddits and searches, keyed by id."""
    pool, errors = {}, []
    for sub in cfg["subreddits"]:
        sub = sub.strip().removeprefix("r/").strip("/")
        if not sub:
            continue
        for sort, t in (("hot", None), ("top", "day")):
            try:
                for p in client.subreddit(sub, sort=sort, t=t):
                    pool[p["id"]] = p
            except RedditError as e:
                errors.append(f"r/{sub}: {e}")
                break
    pool.update(search_posts(client, cfg.get("search_queries") or [], errors))
    return list(pool.values()), errors


def qualifying(cfg, store, posts):
    """Posts that pass every alert rule and were never sent/rejected, best first."""
    out, skipped = [], {}
    recent_titles = store.sent_titles()
    for p in sorted(posts, key=lambda p: p.get("num_comments", 0), reverse=True):
        reason = check_post(p, cfg)
        key = dedupe_key(p)
        if not reason and store.seen(key):
            reason = "already sent or rejected"
        if not reason and any(similar_titles(p.get("title"), t) for t in recent_titles):
            reason = "same story already sent"
        if not reason and any(dedupe_key(q) == key or similar_titles(p.get("title"), q.get("title"))
                              for q in out):
            reason = "duplicate in this batch"
        if reason:
            skipped[p["id"]] = reason
        else:
            out.append(p)
    return out, skipped


def alerts_allowed_now(cfg, store):
    per_hour = int(cfg["posts_per_hour"])
    per_check = max(1, math.ceil(per_hour * int(cfg["check_every_minutes"]) / 60))
    return max(0, min(per_check, per_hour - store.sent_in_last_hour()))


def run_cycle(cfg, store, client, send=True, make_report=False, report_topic=None,
              report_keywords=None):
    started = time.time()
    posts, errors = fetch_pool(cfg, client)
    if not posts and errors:
        errors.insert(0, "Could not load anything from Reddit.")
    good, skipped = qualifying(cfg, store, posts)
    n = alerts_allowed_now(cfg, store) if send else len(good)
    picks = [messages.alert_item(p) for p in good[:n]]
    backups = [dict(messages.alert_item(p), key=dedupe_key(p)) for p in good[n:n + 10]]

    result = {"at": started, "checked": len(posts), "qualified": len(good),
              "new_alerts": picks, "errors": errors, "report": None}
    if send:
        for p, item in zip(good, picks):
            store.mark_sent(dedupe_key(p), item)
        with store.lock:
            store.state["backups"] = backups

    if make_report and posts:
        # Report keywords are also searched Reddit-wide, but those results feed only the
        # report, never the alerts.
        keywords = report_keywords if report_keywords is not None else cfg["report"].get("keywords") or []
        report_pool = {p["id"]: p for p in posts}
        report_pool.update(search_posts(client, keywords, result["errors"]))
        try:
            path, info = build_report(cfg, client, list(report_pool.values()), topic=report_topic,
                                      keywords=report_keywords)
            if path:
                result["report"] = info
                with store.lock:
                    store.state["reports"].append(info)
            else:
                result["errors"].append("Report: " + info)
        except Exception as e:
            log.exception("Report failed")
            result["errors"].append(f"Report failed: {e}")

    if send:
        with store.lock:
            store.state["runs"].append({k: v for k, v in result.items() if k != "new_alerts"}
                                       | {"sent": len(picks)})
        store.save()
    log.info("Checked %d posts, %d qualified, %d new alerts%s", len(posts), len(good), len(picks),
             f", {len(errors)} problems" if errors else "")
    result["skipped"] = skipped
    result["candidates"] = good
    return result

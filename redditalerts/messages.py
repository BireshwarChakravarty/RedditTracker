"""Alert text for WhatsApp/Telegram/Slack/Discord, plus delivery to webhooks."""

import html
import json
import logging
import time

from .reddit import http_request

log = logging.getLogger(__name__)


def permalink(post):
    return "https://www.reddit.com" + post["permalink"]


def _k(n):
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def _age(post):
    hours = (time.time() - float(post.get("created_utc", time.time()))) / 3600
    return f"{hours * 60:.0f}m ago" if hours < 1 else f"{hours:.0f}h ago"


def alert_item(post):
    """Compact record of a post used by the dashboard, history and messages."""
    return {
        "id": post["id"],
        "title": post.get("title", "").strip(),
        "subreddit": post.get("subreddit", ""),
        "url": permalink(post),
        "num_comments": int(post.get("num_comments", 0)),
        "score": int(post.get("score", 0)),
        "upvote_ratio": post.get("upvote_ratio"),
        "created_utc": float(post.get("created_utc", 0)),
        "age": _age(post),
        "flair": post.get("link_flair_text") or "",
    }


def whatsapp_text(item):
    return (f"*{item['title']}*\n"
            f"r/{item['subreddit']} · {_k(item['num_comments'])} comments · "
            f"{_k(item['score'])} upvotes · {item['age']}\n"
            f"{item['url']}")


def whatsapp_batch(items):
    return "\n\n".join(whatsapp_text(i) for i in items)


def _post_json(url, payload):
    status, body = http_request(url, headers={"Content-Type": "application/json"},
                                data=json.dumps(payload).encode(), method="POST")
    if status >= 300:
        raise RuntimeError(f"HTTP {status}: {body[:200]}")


def deliver(cfg, items):
    """Send alerts to every configured channel. Returns a list of error strings."""
    errors = []
    if not items:
        return errors
    if cfg.get("telegram_bot_token") and cfg.get("telegram_chat_id"):
        url = f"https://api.telegram.org/bot{cfg['telegram_bot_token']}/sendMessage"
        for i in items:
            text = (f"<b>{html.escape(i['title'])}</b>\nr/{html.escape(i['subreddit'])} · "
                    f"{_k(i['num_comments'])} comments · {_k(i['score'])} upvotes · {i['age']}\n"
                    f"{i['url']}")
            try:
                _post_json(url, {"chat_id": cfg["telegram_chat_id"], "text": text,
                                 "parse_mode": "HTML"})
            except Exception as e:
                errors.append(f"Telegram: {e}")
    if cfg.get("slack_webhook_url"):
        try:
            _post_json(cfg["slack_webhook_url"], {"text": whatsapp_batch(items)})
        except Exception as e:
            errors.append(f"Slack: {e}")
    if cfg.get("discord_webhook_url"):
        for i in items:
            content = whatsapp_text(i).replace(f"*{i['title']}*", f"**{i['title']}**", 1)
            try:
                _post_json(cfg["discord_webhook_url"], {"content": content[:1900]})
            except Exception as e:
                errors.append(f"Discord: {e}")
    if cfg.get("generic_webhook_url"):
        try:
            _post_json(cfg["generic_webhook_url"],
                       {"text": whatsapp_batch(items), "alerts": items})
        except Exception as e:
            errors.append(f"Webhook: {e}")
    for e in errors:
        log.warning("Delivery failed: %s", e)
    return errors

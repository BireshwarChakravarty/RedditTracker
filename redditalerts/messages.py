"""WhatsApp-ready alert text."""

import time


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

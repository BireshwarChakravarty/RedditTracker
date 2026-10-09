"""Settings: defaults, loading/saving config.json, and environment overrides."""

import copy
import json
import os
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG_PATH = os.path.join(ROOT, "config.json")

DEFAULTS = {
    # --- What to watch -------------------------------------------------------
    "subreddits": [
        "india", "IndiaSpeaks", "indianews", "IndianFocus", "CriticalThinkingIndia",
        "unitedstatesofindia", "indiadiscussion", "IndianModerate", "delhi",
        "mumbai", "bangalore", "kolkata", "chennai", "hyderabad", "pune",
    ],
    # Extra Reddit-wide searches (e.g. "Delhi protest"). Leave empty to skip.
    "search_queries": [],
    # If not empty, a post must mention at least one of these words to qualify.
    "keywords_any": [],
    # Posts mentioning any of these words are always skipped.
    "keywords_block": [],

    # --- Alert rules ---------------------------------------------------------
    "min_comments": 300,
    "posts_per_hour": 3,
    "check_every_minutes": 20,
    "max_post_age_hours": 48,
    "skip_nsfw": True,
    "skip_pinned_posts": False,
    # "strict": only Reddit-native posts (text, Reddit images/videos/galleries).
    # "relaxed": news-article links are OK, but social-media links are still blocked.
    "uniqueness_mode": "strict",
    "blocked_domains": [
        "x.com", "twitter.com", "t.co", "mobile.twitter.com", "nitter.net", "xcancel.com",
        "fxtwitter.com", "vxtwitter.com", "fixupx.com", "fixvx.com",
        "instagram.com", "instagr.am", "ddinstagram.com",
        "facebook.com", "fb.com", "fb.watch", "m.facebook.com",
        "youtube.com", "youtu.be", "m.youtube.com",
        "threads.net", "threads.com", "linkedin.com", "lnkd.in",
        "tiktok.com", "t.me", "telegram.me", "whatsapp.com", "wa.me",
        "snapchat.com", "sharechat.com", "mojapp.in", "kooapp.com",
        "bsky.app", "truthsocial.com", "pinterest.com", "tumblr.com", "quora.com",
    ],
    # Title/body phrases that mean the content came from another platform.
    "blocked_phrases": [
        "tweet", "tweets", "tweeted", "retweet", "twitter", "x.com", "x post", "post on x",
        "posted on x", "instagram", "insta post", "insta reel", "ig post", "ig reel",
        "facebook post", "fb post", "youtube video", "yt video",
    ],

    # --- Report (.docx) ------------------------------------------------------
    "report": {
        "create_each_run": True,
        # When running continuously, create an automatic report at most this often.
        "every_minutes": 60,
        "topic": "Trending Discussions",
        "keywords": [],
        "min_comments": 50,
        "max_posts": 8,
        "top_comments_per_post": 8,
        # Write the narrative with Claude when ANTHROPIC_API_KEY is set.
        "use_ai": True,
        "ai_model": "claude-opus-5-5",
    },

    # --- Where alerts go (all optional) --------------------------------------
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "slack_webhook_url": "",
    "discord_webhook_url": "",
    "generic_webhook_url": "",

    # --- Reddit access -------------------------------------------------------
    # Optional Reddit API app credentials. Without them, public JSON is used.
    "reddit_client_id": "",
    "reddit_client_secret": "",
    "user_agent": "RedditAlertsTeamTool/1.0 (team alerts monitor)",
    "request_delay_seconds": 2.0,

    # --- App -----------------------------------------------------------------
    "timezone_name": "IST",
    "timezone_offset_minutes": 330,
    "dashboard_host": "127.0.0.1",
    "dashboard_port": 8765,
    "open_browser": True,
    "data_dir": "data",
    "reports_dir": "reports",
}

# Environment variables override config.json (handy for GitHub Actions secrets).
ENV_OVERRIDES = {
    "REDDIT_CLIENT_ID": "reddit_client_id",
    "REDDIT_CLIENT_SECRET": "reddit_client_secret",
    "TELEGRAM_BOT_TOKEN": "telegram_bot_token",
    "TELEGRAM_CHAT_ID": "telegram_chat_id",
    "SLACK_WEBHOOK_URL": "slack_webhook_url",
    "DISCORD_WEBHOOK_URL": "discord_webhook_url",
    "GENERIC_WEBHOOK_URL": "generic_webhook_url",
}


def _merge(base, override):
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load(path=DEFAULT_CONFIG_PATH):
    """Return the effective config. Creates config.json with defaults if missing."""
    user = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            user = json.load(fh)
    else:
        save(DEFAULTS, path)
    cfg = _merge(DEFAULTS, user)
    for env, key in ENV_OVERRIDES.items():
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    cfg["_path"] = path
    return cfg


def save(cfg, path=None):
    path = path or cfg.get("_path") or DEFAULT_CONFIG_PATH
    clean = {k: v for k, v in cfg.items() if not k.startswith("_")}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(clean, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def resolve_dir(cfg, key):
    path = cfg[key]
    if not os.path.isabs(path):
        path = os.path.join(ROOT, path)
    os.makedirs(path, exist_ok=True)
    return path


def tz(cfg):
    return timezone(timedelta(minutes=int(cfg["timezone_offset_minutes"])), cfg["timezone_name"])


def now_local(cfg):
    return datetime.now(tz(cfg))

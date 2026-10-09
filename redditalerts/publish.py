"""Builds the hosted (GitHub Pages) version of the dashboard: a static page plus data.json
and the Word reports. The page is read-only; GitHub Actions does the scanning."""

import json
import os
import shutil
import time

from . import config as config_mod
from .messages import whatsapp_text
from .report import ai_available
from .store import Store

PAGE = os.path.join(os.path.dirname(__file__), "dashboard.html")
KEEP_DAYS = 30
SHOW_REPORTS = 60


def prune_reports(reports_dir, store):
    """Delete Word reports older than KEEP_DAYS so the history branch stays small."""
    cutoff = time.time() - KEEP_DAYS * 86400
    for name in os.listdir(reports_dir):
        full = os.path.join(reports_dir, name)
        if name.endswith(".docx") and os.path.getmtime(full) < cutoff:
            os.remove(full)
    with store.lock:
        store.state["reports"] = [r for r in store.state.get("reports") or []
                                  if os.path.exists(os.path.join(reports_dir, r["file"]))]


def build_site(cfg, out_dir, repo=""):
    store = Store(config_mod.resolve_dir(cfg, "data_dir"))
    reports_dir = config_mod.resolve_dir(cfg, "reports_dir")
    prune_reports(reports_dir, store)
    store.save()

    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(os.path.join(out_dir, "reports"))

    week = time.time() - 7 * 86400
    sent = [s for s in store.recent_sent(500) if s["at"] >= week]
    backups = list(store.state.get("backups") or [])
    for item in sent + backups:
        item["whatsapp"] = whatsapp_text(item)
    reports = list(reversed(store.state.get("reports") or []))[:SHOW_REPORTS]
    for r in reports:
        shutil.copy2(os.path.join(reports_dir, r["file"]), os.path.join(out_dir, "reports", r["file"]))
    runs = store.state.get("runs") or []

    data = {
        "hosted": True,
        "repo": repo,
        "now": time.time(),
        "busy": None,
        "last_run": runs[-1] if runs else None,
        "next_run_at": (runs[-1]["at"] if runs else time.time()) + int(cfg["check_every_minutes"]) * 60,
        "errors": (runs[-1].get("errors") if runs else []) or [],
        "sent": sent,
        "backups": backups,
        "reports": reports,
        "ai": ai_available(cfg),
        "sent_last_hour": store.sent_in_last_hour(),
        "settings": {
            k: cfg[k] for k in ("min_comments", "posts_per_hour", "check_every_minutes",
                                "max_post_age_hours", "uniqueness_mode", "subreddits",
                                "search_queries")
        } | {"report": {k: cfg["report"].get(k) for k in ("create_each_run", "every_minutes", "topic")}},
    }
    with open(os.path.join(out_dir, "data.json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    shutil.copy2(PAGE, os.path.join(out_dir, "index.html"))
    with open(os.path.join(out_dir, ".nojekyll"), "w"):
        pass
    return data

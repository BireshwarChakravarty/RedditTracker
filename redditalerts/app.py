"""Local web dashboard + background scheduler."""

import json
import logging
import os
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from . import config as config_mod
from .engine import run_cycle
from .messages import whatsapp_batch, whatsapp_text
from .reddit import RedditClient
from .report import ai_available
from .store import Store

log = logging.getLogger(__name__)
PAGE = os.path.join(os.path.dirname(__file__), "dashboard.html")

EDITABLE = {
    "min_comments": int, "posts_per_hour": int, "check_every_minutes": int,
    "max_post_age_hours": int, "subreddits": list, "search_queries": list,
    "keywords_any": list, "keywords_block": list, "uniqueness_mode": str,
    "skip_nsfw": bool, "skip_pinned_posts": bool,
    "reddit_client_id": str, "reddit_client_secret": str,
}
REPORT_EDITABLE = {"create_each_run": bool, "every_minutes": int, "topic": str,
                   "keywords": list, "min_comments": int, "max_posts": int, "use_ai": bool}


def _coerce(kind, value):
    if kind is list:
        if isinstance(value, str):
            value = value.replace(",", "\n").splitlines()
        return [v.strip() for v in value if str(v).strip()]
    if kind is bool:
        return bool(value)
    if kind is int:
        return max(0, int(value))
    return str(value).strip()


class App:
    def __init__(self, cfg):
        self.cfg = cfg
        self.store = Store(config_mod.resolve_dir(cfg, "data_dir"))
        self.reports_dir = config_mod.resolve_dir(cfg, "reports_dir")
        self.busy = None
        self.wake = threading.Event()
        self.pending_report = None
        self.last_errors = []

    # --- work ----------------------------------------------------------------
    def _last_report_at(self):
        reports = self.store.state.get("reports") or []
        return reports[-1]["at"] if reports else 0

    def cycle(self, force_report=None):
        cfg = self.cfg
        rcfg = cfg["report"]
        auto_report = rcfg.get("create_each_run") and \
            time.time() - self._last_report_at() >= int(rcfg.get("every_minutes", 60)) * 60 - 30
        self.busy = "Checking Reddit…"
        try:
            client = RedditClient(cfg)
            if force_report is not None:
                self.busy = "Building report…"
                res = run_cycle(cfg, self.store, client, send=False, make_report=True,
                                report_topic=force_report.get("topic"),
                                report_keywords=force_report.get("keywords"))
                self.store.save()
            else:
                res = run_cycle(cfg, self.store, client, send=True, make_report=bool(auto_report))
            self.last_errors = res["errors"]
            return res
        except Exception as e:
            log.exception("Cycle failed")
            self.last_errors = [f"Unexpected error: {e}"]
            with self.store.lock:
                self.store.state["runs"].append({"at": time.time(), "errors": self.last_errors,
                                                 "sent": 0, "checked": 0, "qualified": 0})
            self.store.save()
        finally:
            self.busy = None

    def last_run_at(self):
        runs = self.store.state.get("runs") or []
        return runs[-1]["at"] if runs else 0

    def next_run_at(self):
        return self.last_run_at() + int(self.cfg["check_every_minutes"]) * 60

    def scheduler(self):
        while True:
            if self.pending_report is not None:
                req, self.pending_report = self.pending_report, None
                self.cycle(force_report=req)
            elif time.time() >= self.next_run_at() or self.wake.is_set():
                self.wake.clear()
                self.cycle()
            self.wake.wait(timeout=10)

    # --- API -----------------------------------------------------------------
    def snapshot(self):
        cfg = self.cfg
        sent = self.store.recent_sent(80)
        for s in sent:
            s["whatsapp"] = whatsapp_text(s)
        backups = list(self.store.state.get("backups") or [])
        for b in backups:
            b["whatsapp"] = whatsapp_text(b)
        runs = self.store.state.get("runs") or []
        reports = [r for r in reversed(self.store.state.get("reports") or [])
                   if os.path.exists(os.path.join(self.reports_dir, r["file"]))][:30]
        settings = {k: cfg[k] for k in EDITABLE}
        settings["report"] = {k: cfg["report"].get(k) for k in REPORT_EDITABLE}
        return {
            "busy": self.busy, "now": time.time(),
            "last_run": runs[-1] if runs else None,
            "next_run_at": self.next_run_at(), "errors": self.last_errors,
            "sent": sent, "backups": backups, "reports": reports,
            "oauth": bool(cfg["reddit_client_id"] and cfg["reddit_client_secret"]),
            "ai": ai_available(cfg), "settings": settings,
            "sent_last_hour": self.store.sent_in_last_hour(),
        }

    def update_settings(self, data):
        for key, kind in EDITABLE.items():
            if key in data:
                self.cfg[key] = _coerce(kind, data[key])
        for key, kind in REPORT_EDITABLE.items():
            if key in (data.get("report") or {}):
                self.cfg["report"][key] = _coerce(kind, data["report"][key])
        self.cfg["check_every_minutes"] = max(5, self.cfg["check_every_minutes"])
        if self.cfg["uniqueness_mode"] not in ("strict", "relaxed"):
            self.cfg["uniqueness_mode"] = "strict"
        config_mod.save(self.cfg)

    def promote(self, key):
        with self.store.lock:
            item = next((b for b in self.store.state["backups"] if b["key"] == key), None)
            if not item:
                return False
            self.store.state["backups"].remove(item)
            self.store.mark_sent(key, {k: v for k, v in item.items() if k not in ("key", "whatsapp")})
        self.store.save()
        return True


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body, ctype="application/json", extra=None):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False))

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                with open(PAGE, encoding="utf-8") as fh:
                    return self._send(200, fh.read(), "text/html; charset=utf-8")
            if path == "/api/state":
                return self._json(app.snapshot())
            if path == "/api/whatsapp-latest":
                cutoff = time.time() - 3600
                items = [s for s in app.store.recent_sent() if s["at"] >= cutoff]
                return self._send(200, whatsapp_batch(items), "text/plain; charset=utf-8")
            if path.startswith("/reports/"):
                name = os.path.basename(unquote(path[len("/reports/"):]))
                full = os.path.join(app.reports_dir, name)
                if name.endswith(".docx") and os.path.isfile(full):
                    with open(full, "rb") as fh:
                        return self._send(
                            200, fh.read(),
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            {"Content-Disposition": f'attachment; filename="{name}"'})
            self._send(404, "Not found", "text/plain")

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                length = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._json({"error": "bad request"}, 400)
            try:
                if path == "/api/run":
                    app.wake.set()
                elif path == "/api/report":
                    app.pending_report = {
                        "topic": data.get("topic") or app.cfg["report"]["topic"],
                        "keywords": _coerce(list, data.get("keywords") or [])}
                    app.wake.set()
                elif path == "/api/reject":
                    app.store.mark_rejected(data["key"], data.get("title", ""))
                    app.store.save()
                elif path == "/api/promote":
                    if not app.promote(data["key"]):
                        return self._json({"error": "not found"}, 404)
                elif path == "/api/settings":
                    app.update_settings(data)
                else:
                    return self._json({"error": "not found"}, 404)
            except Exception as e:
                traceback.print_exc()
                return self._json({"error": str(e)}, 400)
            self._json({"ok": True})

    return Handler


def serve(cfg):
    app = App(cfg)
    threading.Thread(target=app.scheduler, daemon=True).start()
    host, port = cfg["dashboard_host"], int(cfg["dashboard_port"])
    server = ThreadingHTTPServer((host, port), make_handler(app))
    url = f"http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}"
    print(f"\n  Reddit Alerts is running. Open {url} in your browser.")
    print("  Keep this window open. Press Ctrl+C to stop.\n")
    if cfg.get("open_browser"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")

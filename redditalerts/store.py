"""Persistent state: what was already sent, what the team rejected, last run info."""

import json
import os
import threading
import time

KEEP_DAYS = 30


class Store:
    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, "state.json")
        self.lock = threading.RLock()
        self.state = {"sent": {}, "rejected": {}, "backups": [], "runs": [], "reports": []}
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as fh:
                self.state.update(json.load(fh))

    def save(self):
        with self.lock:
            cutoff = time.time() - KEEP_DAYS * 86400
            for bucket in ("sent", "rejected"):
                self.state[bucket] = {k: v for k, v in self.state[bucket].items()
                                      if v.get("at", 0) >= cutoff}
            self.state["runs"] = self.state["runs"][-50:]
            self.state["reports"] = self.state["reports"][-100:]
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.state, fh, indent=1, ensure_ascii=False)
            os.replace(tmp, self.path)

    def seen(self, key):
        return key in self.state["sent"] or key in self.state["rejected"]

    def sent_titles(self, within_hours=72):
        cutoff = time.time() - within_hours * 3600
        return [v["title"] for v in self.state["sent"].values() if v.get("at", 0) >= cutoff]

    def sent_in_last_hour(self):
        cutoff = time.time() - 3600
        return sum(1 for v in self.state["sent"].values() if v.get("at", 0) >= cutoff)

    def mark_sent(self, key, item):
        with self.lock:
            self.state["sent"][key] = dict(item, at=time.time())

    def mark_rejected(self, key, title=""):
        with self.lock:
            self.state["rejected"][key] = {"title": title, "at": time.time()}
            self.state["sent"].pop(key, None)
            self.state["backups"] = [b for b in self.state["backups"] if b["key"] != key]

    def recent_sent(self, limit=60):
        items = [dict(v, key=k) for k, v in self.state["sent"].items()]
        items.sort(key=lambda v: v["at"], reverse=True)
        return items[:limit]

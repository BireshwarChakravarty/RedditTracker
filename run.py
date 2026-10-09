#!/usr/bin/env python3
"""Reddit Alerts — start here.

  python run.py                 Open the dashboard and keep checking Reddit (default)
  python run.py once            Run one check, send alerts, then exit (for schedulers)
  python run.py once --report   Same, and also create a Word report
  python run.py preview         Show what would qualify right now (sends nothing)
  python run.py report --topic "Delhi Protest" --keywords "Delhi protest, Jantar Mantar"
                                Create a Word report only
  python run.py publish --out site
                                Build the hosted web page (used by GitHub Actions)
"""

import argparse
import logging
import sys
import time

if sys.version_info < (3, 9):
    sys.exit("Reddit Alerts needs Python 3.9 or newer. Download it from https://www.python.org/downloads/")

from redditalerts import config as config_mod  # noqa: E402
from redditalerts.engine import run_cycle  # noqa: E402
from redditalerts.messages import whatsapp_text  # noqa: E402
from redditalerts.reddit import RedditClient  # noqa: E402
from redditalerts.store import Store  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Unique, high-engagement Reddit alerts.")
    ap.add_argument("command", nargs="?", default="dashboard",
                    choices=["dashboard", "once", "preview", "report", "publish"])
    ap.add_argument("--config", default=config_mod.DEFAULT_CONFIG_PATH)
    ap.add_argument("--report", action="store_true", help="also create a Word report")
    ap.add_argument("--topic", help="report topic, e.g. 'Delhi Protest'")
    ap.add_argument("--keywords", help="comma-separated report keywords")
    ap.add_argument("--auto-report", action="store_true",
                    help="also create a report if the last one is older than the report interval")
    ap.add_argument("--out", default="site", help="output folder for publish")
    ap.add_argument("--repo", default="", help="owner/repo, shown as links on the hosted page")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
    cfg = config_mod.load(args.config)
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()] if args.keywords else None

    if args.command == "dashboard":
        from redditalerts.app import serve
        if args.no_browser:
            cfg["open_browser"] = False
        serve(cfg)
        return

    if args.command == "publish":
        from redditalerts.publish import build_site
        data = build_site(cfg, args.out, repo=args.repo)
        print(f"Web page built in {args.out}/ ({len(data['sent'])} alerts, {len(data['reports'])} reports)")
        return

    store = Store(config_mod.resolve_dir(cfg, "data_dir"))
    client = RedditClient(cfg)
    if args.command == "preview":
        res = run_cycle(cfg, store, client, send=False)
        print(f"\nScanned {res['checked']} posts; {res['qualified']} qualify right now:\n")
        for item in res["new_alerts"][:20]:
            print(whatsapp_text(item) + "\n")
    else:
        make_report = args.command == "report" or args.report or bool(args.topic or args.keywords)
        if args.auto_report and not make_report and cfg["report"].get("create_each_run"):
            reports = store.state.get("reports") or []
            last = reports[-1]["at"] if reports else 0
            make_report = time.time() - last >= int(cfg["report"].get("every_minutes", 60)) * 60 - 120
        res = run_cycle(cfg, store, client, send=args.command == "once",
                        make_report=make_report, report_topic=args.topic, report_keywords=keywords)
        if args.command == "report":
            store.save()
        if args.command == "once":
            print(f"\n{len(res['new_alerts'])} new alert(s):\n")
            for item in res["new_alerts"]:
                print(whatsapp_text(item) + "\n")
        if res["report"]:
            print(f"Report created: {config_mod.resolve_dir(cfg, 'reports_dir')}/{res['report']['file']}")
    for e in res["errors"]:
        print("Problem:", e)
    if res["errors"] and not res["checked"]:
        sys.exit(1)


if __name__ == "__main__":
    main()

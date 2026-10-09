"""Builds the 'Reddit Report — <topic> | <date, time>' Word document."""

import json
import logging
import os
import re
import time

from . import config as config_mod
from .docx_writer import Document
from .filters import check_post, similar_titles
from .messages import alert_item

log = logging.getLogger(__name__)

AI_SYSTEM = """You are a social-media analyst writing a Reddit monitoring report for an \
Indian media-monitoring team. Write in clear, neutral, Indian/British English \
(e.g. "mobilisation", "criticising").

Style rules (follow the team's existing reports):
- Group the posts into themes/narratives. Each section is one paragraph of 2-4 sentences \
describing what users are saying, the split in opinion, and why it matters.
- Wrap key phrases in **double asterisks** for bold (subreddit names, people, organisations, \
core claims, main reactions). Bold generously but meaningfully, as in a briefing note.
- Attribute claims to users ("users claim", "a post purporting to show"). Never present \
unverified user claims as facts; say so when comments question a claim.
- Use only the posts and comments provided. Do not invent facts, numbers or events.
- Do not use markdown other than **bold**. No headings, bullet points or emojis."""

AI_INSTRUCTIONS = """Topic: {topic}
Report time: {when}

Below are the Reddit posts (JSON). Return ONLY a JSON object, no other text:
{{
  "summary": "one paragraph (4-7 sentences) giving the overall picture and main narratives",
  "sections": [
    {{"post_ids": ["<id>", "..."], "paragraph": "theme paragraph"}}
  ]
}}
Every post id must appear in exactly one section. Order sections from most to least significant.

Posts:
{posts}"""


def _k(n):
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def _clip(text, n):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


def select_posts(cfg, posts):
    rcfg = cfg["report"]
    rule_cfg = dict(cfg, keywords_any=rcfg.get("keywords") or cfg.get("keywords_any") or [])
    chosen = []
    for p in sorted(posts, key=lambda p: p.get("num_comments", 0), reverse=True):
        if check_post(p, rule_cfg, min_comments=rcfg["min_comments"], require_unique=False):
            continue
        if any(p["id"] == c["id"] or similar_titles(p.get("title"), c.get("title")) for c in chosen):
            continue
        chosen.append(p)
        if len(chosen) >= rcfg["max_posts"]:
            break
    return chosen


def _template_narrative(entries):
    subs = []
    for e in entries:
        if e["subreddit"] not in subs:
            subs.append(e["subreddit"])
    top = entries[0]
    total = sum(e["num_comments"] for e in entries)
    sub_list = ", ".join("r/" + s for s in subs[:5])
    summary = (f"Reddit discussion tracked in this report spans **{len(entries)} posts** across "
               f"**{sub_list}**, drawing **{_k(total)} comments** in total. The most-discussed "
               f"thread is **\"{top['title']}\"** on **r/{top['subreddit']}** with "
               f"**{_k(top['num_comments'])} comments**.")
    sections = []
    for e in entries:
        ratio = e.get("upvote_ratio")
        ratio_txt = f" ({ratio * 100:.0f}% upvoted)" if isinstance(ratio, (int, float)) else ""
        para = (f"A post on **r/{e['subreddit']}** titled **\"{e['title']}\"** has drawn "
                f"**{_k(e['num_comments'])} comments** and **{_k(e['score'])} upvotes**{ratio_txt} "
                f"since it was posted {e['age']}.")
        if e.get("selftext"):
            para += f" The post says: \"{_clip(e['selftext'], 280)}\""
        quotes = [f"\"{_clip(c['body'], 180)}\" ({_k(c['score'])} points)" for c in e["comments"][:3]]
        if quotes:
            para += " Top comments include: " + "; ".join(quotes) + "."
        sections.append({"post_ids": [e["id"]], "paragraph": para})
    return summary, sections


def _ai_narrative(cfg, entries, topic, when):
    import anthropic  # optional dependency

    payload = [{
        "id": e["id"], "subreddit": "r/" + e["subreddit"], "title": e["title"],
        "comments": e["num_comments"], "upvotes": e["score"], "posted": e["age"],
        "flair": e["flair"], "post_text": _clip(e.get("selftext"), 1500),
        "top_comments": [{"score": c["score"], "text": _clip(c["body"], 600)} for c in e["comments"]],
    } for e in entries]
    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=cfg["report"].get("ai_model") or "claude-opus-5-5",
        max_tokens=16000,
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=AI_SYSTEM,
        messages=[{"role": "user", "content": AI_INSTRUCTIONS.format(
            topic=topic, when=when, posts=json.dumps(payload, ensure_ascii=False, indent=1))}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined to write this report")
    text = "".join(b.text for b in response.content if b.type == "text")
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise RuntimeError("AI response was not JSON")
    data = json.loads(match.group(0))
    ids = {e["id"] for e in entries}
    sections, used = [], set()
    for s in data.get("sections", []):
        pids = [p for p in s.get("post_ids", []) if p in ids and p not in used]
        if pids and s.get("paragraph"):
            used.update(pids)
            sections.append({"post_ids": pids, "paragraph": s["paragraph"].strip()})
    leftover = [e for e in entries if e["id"] not in used]
    if leftover:
        sections += _template_narrative(leftover)[1]
    return data.get("summary", "").strip(), sections


def ai_available(cfg):
    if not cfg["report"].get("use_ai") or not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


def build_report(cfg, client, posts, topic=None, keywords=None):
    """Create the .docx report. Returns (path, info dict) or (None, reason)."""
    if keywords is not None:
        cfg = dict(cfg, report=dict(cfg["report"], keywords=keywords))
    topic = (topic or cfg["report"]["topic"]).strip() or "Trending Discussions"
    now = config_mod.now_local(cfg)
    chosen = select_posts(cfg, posts)
    if not chosen:
        return None, "No posts matched the report settings (try a lower report comment minimum or fewer keywords)."

    entries = []
    for p in chosen:
        e = alert_item(p)
        e["selftext"] = p.get("selftext") or ""
        try:
            e["comments"] = client.top_comments(p["id"], cfg["report"]["top_comments_per_post"])
        except Exception as ex:
            log.warning("Could not load comments for %s: %s", p["id"], ex)
            e["comments"] = []
        entries.append(e)

    when = (f"{now.day} {now:%b %Y}, {now.hour % 12 or 12}:{now:%M} "
            f"{'AM' if now.hour < 12 else 'PM'} {cfg['timezone_name']}")
    used_ai = False
    if ai_available(cfg):
        try:
            summary, sections = _ai_narrative(cfg, entries, topic, when)
            used_ai = True
        except Exception as ex:
            log.warning("AI write-up failed, using the standard write-up: %s", ex)
            summary, sections = _template_narrative(entries)
    else:
        summary, sections = _template_narrative(entries)

    by_id = {e["id"]: e for e in entries}
    title = f"Reddit Report — {topic} | {when}"
    doc = Document()
    doc.title(title)
    doc.paragraph(summary)
    doc.heading("Comprehensive Report")
    for s in sections:
        doc.paragraph(s["paragraph"])
        for pid in s["post_ids"]:
            e = by_id[pid]
            doc.link(e["title"], e["url"],
                     note=f"r/{e['subreddit']} · {_k(e['num_comments'])} comments · {e['age']}")
    doc.small(f"Generated automatically at {when} from {len(entries)} Reddit posts"
              f"{' (write-up drafted by AI — please review)' if used_ai else ''}.")

    safe_topic = re.sub(r"[^A-Za-z0-9]+", "_", topic).strip("_")[:40] or "Report"
    fname = f"Reddit_Report_{safe_topic}_{now.strftime('%Y-%m-%d_%H%M')}.docx"
    path = os.path.join(config_mod.resolve_dir(cfg, "reports_dir"), fname)
    n = 2
    while os.path.exists(path):
        path = os.path.join(os.path.dirname(path), fname.replace(".docx", f"_{n}.docx"))
        n += 1
    fname = os.path.basename(path)
    doc.save(path, title=title)
    log.info("Report written: %s", path)
    return path, {"file": fname, "title": title, "posts": len(entries), "ai": used_ai,
                  "at": time.time()}

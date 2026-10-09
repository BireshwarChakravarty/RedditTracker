# Reddit Alerts

Finds **unique, high-engagement Reddit posts** for the Alerts group and creates
**Word reports** in the team's "Reddit Report — Topic | Date, Time" format.

It scans live Reddit (the subreddits you choose plus optional Reddit-wide searches)
every 20 minutes and picks **up to 3 posts per hour** that:

- have **at least 300 comments** (you can change this),
- are **unique to Reddit**: no links to X/Twitter, Instagram, Facebook, YouTube, Threads,
  Telegram, WhatsApp and similar sites (in the link, the post text or the original of a
  crosspost), and no "tweet / Instagram reel / YouTube video" mentions that suggest the
  content was copied from elsewhere. In *strict* mode (default) it also skips news-article
  links, so only content posted on Reddit itself (text, Reddit images/videos/galleries) counts,
- were **never alerted before**: no repeats, and the same story posted in two subreddits counts once.

## Start it (no technical setup)

1. Install Python 3.9+ from https://www.python.org/downloads/ (on Windows tick **"Add Python to PATH"**).
2. Download this folder (GitHub → **Code → Download ZIP**) and unzip it.
3. Double-click:
   - **Windows:** `Start Reddit Alerts (Windows).bat`
   - **Mac:** `Start Reddit Alerts (Mac).command` (the first time: right-click → Open)
   - **Linux:** `./start_linux.sh`
4. A dashboard opens at http://localhost:8765. Keep the black window open while you work.

## Using the dashboard

- **Alerts to share**: click **Copy** and paste into the WhatsApp Alerts group. The
  message is already formatted (bold title, subreddit, comment count, link).
  **Copy last hour's alerts** copies all of them at once.
- **Not relevant** removes a post forever. **Backup picks** are other qualifying posts;
  click **Use this** to swap one in.
- **Reports (Word)**: type a topic (e.g. *Delhi Protest*) and optional keywords, then click
  **Create report now**. The `.docx` has the title with date and time, a summary, a
  "Comprehensive Report" section and linked post titles. It is saved in the `reports/`
  folder and can be downloaded from the dashboard. By default a report is also created
  automatically about once an hour while the tool runs (turn this off in Settings).
- **Settings**: comment minimum, alerts per hour, subreddits, keywords, strict/relaxed
  uniqueness, report options. Changes are saved to `config.json`.

### AI-written report narrative (optional)

Without setup, reports use a factual template (post stats, what the post says, top comments).
For an analyst-style narrative like the team's hand-written reports, set an Anthropic API key
before starting (`ANTHROPIC_API_KEY`). The `anthropic` package installs automatically when you
start with the launcher. Always review AI text before sharing.

### Sending alerts automatically (optional)

WhatsApp has no official way for bots to post into groups, so the default is copy and paste.
If the team also uses Telegram, Slack or Discord, paste a bot token or webhook URL in
**Settings → Send alerts automatically** and every alert is posted there too.

## Command line (optional)

```
python run.py                 # dashboard + checks every 20 minutes (default)
python run.py preview         # list posts that qualify right now, send nothing
python run.py once            # one check: pick, record and send alerts, then exit
python run.py once --report   # same, plus a Word report
python run.py report --topic "Delhi Protest" --keywords "Delhi protest, Jantar Mantar, SIR"
```

`once` is useful with Windows Task Scheduler or cron if you don't want the dashboard open.

## Good to know

- **One shared runner:** "already sent" history is stored in `data/` on the computer running
  the tool. Have one person (or one always-on machine) run it so everyone sees the same alerts.
  Others can open the dashboard on the office network if you set `"dashboard_host": "0.0.0.0"`
  in `config.json`. Note that anyone who can reach it can then change settings.
- **Reddit blocking:** Reddit's public pages work from normal office/home internet. If you see
  "Reddit refused the request" (common on cloud servers/VPNs), add Reddit API credentials in
  Settings (create a "script" app at https://www.reddit.com/prefs/apps).
- **Limits of the uniqueness check:** a post can still be a screenshot of a tweet without saying
  so. The tool catches links and wording, not image content, so take a quick look before sharing.
- Tests: `python -m unittest discover -s tests -t .`

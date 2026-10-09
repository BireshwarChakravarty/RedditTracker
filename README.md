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

## The team web page (hosted free on GitHub)

The team opens **https://bireshwarchakravarty.github.io/RedditTracker/**. There's nothing to
install, and it works on phones. GitHub checks Reddit every 20 minutes by itself, so no
computer needs to stay on. The page lets the team:

- **Copy for WhatsApp** on any alert, or **Copy this hour's alerts** at once
- **Export alerts (Excel / CSV)**: the last 7 days of alerts as a spreadsheet
- **Download** the Word reports (one is made automatically about every hour)
- **Hide** a post they don't want to see (on their own device only)

It costs nothing because the repository is public. The page is public too; it only shows
public Reddit posts and reports built from them.

### One-time setup (repository owner)

1. **Turn on the web page:** repository **Settings → Pages**, under *Build and deployment* set
   **Source** to **GitHub Actions**.
2. **Start the first check:** **Actions** tab → **Reddit Alerts** → **Run workflow** → **Run workflow**.
   After about 2 minutes the page is live at the link above, and it then updates every 20 minutes.

### Day to day

- **Check now / report on a topic:** Actions → Reddit Alerts → **Run workflow**. Leave the boxes
  empty to just check for alerts, or enter a topic (e.g. *Delhi Protest*) and keywords for a
  Word report. Only people with access to the repository can do this.
- **Change settings** (comment minimum, subreddits, searches, report topic): edit
  [`config.json`](config.json) on GitHub (pencil icon) and commit. The next check uses it.
- **History** (what was already sent) is kept on the `alerts-data` branch. Don't delete it,
  or old posts may be alerted again.
- **AI-written reports (optional):** add a repository secret named `ANTHROPIC_API_KEY`
  (Settings → Secrets and variables → Actions). Never put keys in `config.json`, because the
  repository is public.
- GitHub may run scheduled checks a few minutes late when it's busy. If nobody commits to
  the repository for 60 days, GitHub pauses the schedule and emails the owner; click
  **Enable workflow** on the Actions tab to resume.

## Run it on your own computer instead (optional)

1. Install Python 3.9+ from https://www.python.org/downloads/ (on Windows tick **"Add Python to PATH"**).
2. Download this folder (GitHub → **Code → Download ZIP**) and unzip it.
3. Double-click:
   - **Windows:** `Start Reddit Alerts (Windows).bat`
   - **Mac:** `Start Reddit Alerts (Mac).command` (the first time: right-click → Open)
   - **Linux:** `./start_linux.sh`
4. A dashboard opens at http://localhost:8765. Keep the black window open while you work.

## Using the dashboard

The dashboard looks and feels like Reddit, with light and dark mode (it follows your
computer's setting; the sun/moon button in the top right switches it).

- **Alerts**: click **Copy for WhatsApp** and paste into the WhatsApp Alerts group. The
  message is already formatted (bold title, subreddit, comment count, link).
  **Copy this hour's alerts** copies all of them at once.
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

## Command line (optional)

```
python run.py                 # dashboard + checks every 20 minutes (default)
python run.py preview         # list posts that qualify right now, send nothing
python run.py once            # one check: pick and record alerts, print them, then exit
python run.py once --report   # same, plus a Word report
python run.py report --topic "Delhi Protest" --keywords "Delhi protest, Jantar Mantar, SIR"
```

`once` is useful with Windows Task Scheduler or cron if you don't want the dashboard open.

## Good to know

- **One shared runner:** "already sent" history is stored in `data/` on the computer running
  the tool. Have one person (or one always-on machine) run it so everyone sees the same alerts.
  Others can open the dashboard on the office network if you set `"dashboard_host": "0.0.0.0"`
  in `config.json`. Note that anyone who can reach it can then change settings.
- **Reddit blocking:** Reddit blocks its data feed on many cloud and some office networks.
  When that happens the tool switches to reading Reddit's normal web pages automatically,
  with the same rules and results (tested live: 400+ posts scanned in about a minute). If
  Reddit ever blocks those too, the dashboard shows it under "Problems"; adding Reddit API
  credentials in Settings is the fallback.
- **Limits of the uniqueness check:** a post can still be a screenshot of a tweet without saying
  so. The tool catches links and wording, not image content, so take a quick look before sharing.
- Tests: `python -m unittest discover -s tests -t .`

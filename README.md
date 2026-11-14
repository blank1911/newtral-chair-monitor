# Newtral Standing-Mate Chair Price Monitor

Pushes an alert to your phone when the **Newtral Standing-Mate chair (Medium/Large)** drops
below its normal price of **$349.99** on newtralchair.com or Amazon.

It only alerts. It never buys, adds to cart, logs in, or tries to get past bot protection.
If a site blocks it, it logs that, warns you once after 3 blocked runs in a row, and skips that site.

## What it watches

| Target | How it reads the price |
|---|---|
| `newtral_site`: newtralchair.com | The store's public Shopify product JSON (`/products/standing-mate-ergonomic-chair.js`), Medium/Large variant `41672021115013`. Exact price and stock flag, no scraping. |
| `amazon`: amazon.com/dp/B0H3699JFY | The buy box price on the M/L listing (this listing includes an anti-fatigue mat). Amazon often refuses GitHub's servers with a robot check; that shows as `BLOCKED` and is skipped. Clip-on coupons are not counted. |

Small size: variant `41607819493509` on the site, ASIN `B0GVS6S9RB` on Amazon. Swap them in `config.yaml` if you change size.

## Alerts

| Alert | Priority |
|---|---|
| CHAIR AT $X: price at or below `target_price` ($300) | 5 urgent |
| Chair price drop: any drop of $1 or more below the last alerted price (starting from $349.99) | 4 high |
| Chair back in stock | 3 |
| Page layout changed, or a site failing 3 runs in a row (once per incident) | 3 |
| Chair price back up (sale ended) / out of stock | 2 |
| Chair monitor alive with both prices and the lowest seen (daily, first run after 9am Mountain Time) | 1 |

Each drop alerts once. A further drop alerts again. If the price goes back up and drops again, you get alerted again.

## Local setup (Windows PowerShell)

Needs Python 3.12 from python.org (tick "Add python.exe to PATH").

```powershell
cd path\to\newtral-chair-monitor
py -3.12 -m venv .venv
# If activation is blocked, run this once:
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest
```

Dry run against the live sites (prints what would alert, sends nothing, writes no state):

```powershell
python monitor.py --dry-run
```

Dry run against a fixture where the chair is on sale for $299.99 (should print a p5 "CHAIR AT $299.99"):

```powershell
python monitor.py --dry-run --newtral-json tests\fixtures\newtral_sale.json
```

Send one test notification at each priority (1 through 5):

```powershell
$env:NTFY_TOPIC = "your-long-random-topic"
python monitor.py --test-alert
```

## GitHub setup

1. Public repo (unlimited free Actions minutes). Nothing secret is in the code.
2. **Settings > Secrets and variables > Actions > New repository secret**: name `NTFY_TOPIC`, value a new long random topic.
3. **Settings > Actions > General > Workflow permissions**: "Read and write permissions" so the workflow can commit `state.json`.
4. **Actions > monitor > Run workflow** for a manual run. The run summary shows each target's status and price.
5. Tick "Only send one test notification at each priority" on that same button to test your phone.

### Schedule (cron-job.org)

GitHub's own cron is badly throttled, so the `monitor` workflow's hourly `schedule` is only a backup.
The real trigger is a cron-job.org job every **30 minutes**:

- URL: `https://api.github.com/repos/blank1911/newtral-chair-monitor/actions/workflows/monitor.yml/dispatches`
- Method: `POST`
- Headers: `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`
- Body: `{"ref":"main"}`
- Token: a fine-grained GitHub token with access to this repo only, permission **Actions: Read and write**.

A successful dispatch returns HTTP 204.

The `keepalive` workflow runs weekly and commits a date to `state.json` if nothing else has, because
GitHub turns off scheduled workflows in public repos after 60 days without activity.

## Phone (Pixel / Android)

In the ntfy app tap **+**, enter the topic exactly, server `ntfy.sh`, subscribe. Priority 5 alerts use
ntfy's Max priority channel; allow it to override Do Not Disturb if you want sale alerts loud.

## Refreshing test fixtures

**Actions > snapshot > Run workflow** fetches each target once and saves the raw JSON and HTML to the
`snapshots` branch.

## Configuration

Everything is in `config.yaml`: baseline and target price, minimum drop, product IDs, per-target
`enabled`, heartbeat hour and timezone. If Amazon is always `BLOCKED`, set `amazon.enabled: false`.

## State

`state.json` holds each target's last price and stock status, the price a drop is measured from,
the lowest price seen and when, failure counts, and the last heartbeat date. To start fresh, replace
its contents with `{}`.

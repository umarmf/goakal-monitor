# Akal Batch 1 seat monitor

Watches `9 kursi tersisa` for **Batch 1** on
<https://goakal.com/brobri/program-suami-qawwam> and pushes an **ntfy**
notification when it changes, plus a **daily digest** at 08:00 WIB comparing
today against yesterday.

Runs on a GitHub Actions cron every 15 minutes — no server, no laptop required.

## Files

| File | Purpose |
|---|---|
| `monitor.py` | Fetch page → parse Batch 1 quota → compare to `state.json` → notify |
| `state.json` | Last known seat count + digest bookkeeping (committed back by CI) |
| `.github/workflows/monitor.yml` | Cron `*/15 * * * *` + manual dispatch |

No dependencies outside the Python standard library.

## How it reads the number

The page is server-rendered, so no browser is needed. The embedded RSC payload
carries the real data:

```
"title":"Batch 1 (10 pertama)", ... "quotaMax":10, "quotaUsed":1
```

`kursi tersisa = quotaMax - quotaUsed`. If that payload ever disappears, the
script falls back to the badge text (`>9<!-- --> kursi tersisa`) and says so via
`source` in `state.json`.

## Setup (once)

1. Create a **public** GitHub repo, e.g. `akal-monitor`.
   - Public matters: each scheduled run is billed as at least 1 minute. 96 runs
     a day ≈ 2,900 min/month, which exceeds the 2,000 free private-repo minutes.
     A public repo has unlimited Actions minutes. Nothing secret lives in the
     code — the ntfy topic stays in repo secrets.
2. Push this folder as the repo root:

   ```powershell
   cd D:\Umar\akal-monitor
   git init -b main
   git add .
   git commit -m "Akal Batch 1 seat monitor"
   git remote add origin https://github.com/<you>/akal-monitor.git
   git push -u origin main
   ```

3. Generate a topic name (this string *is* the secret — keep it long and random):

   ```powershell
   python -c "import secrets;print('akal-'+secrets.token_urlsafe(18))"
   ```

4. Repo → **Settings → Secrets and variables → Actions → New repository secret**
   → name `NTFY_TOPIC`, value = the string from step 3.
5. Install the **ntfy** app (Android / iOS / F-Droid) and subscribe to that same
   topic. Or open `https://ntfy.sh/<topic>` in a browser to watch it live.
6. Repo → **Actions** → *Akal Batch 1 seat monitor* → **Run workflow**.
   You should get one `Monitor aktif: 9 kursi tersisa` push.
7. If the run fails at *Persist state* with a 403, go to **Settings → Actions →
   General → Workflow permissions** and choose **Read and write permissions**.

## What the alerts look like

- **Change** (priority high, tag `warning`)
  `Akal Batch 1: 9 -> 8` — old value, delta, quota used, timestamp.
- **Daily digest** (08:00 WIB, tag `calendar`; priority high only if it moved)
  `Akal harian: 8 kursi tersisa` — today vs yesterday, and the delta.
- **Error** (priority urgent, tag `rotating_light`) — page unreachable, layout
  changed, or invalid quota. At most one error alert every 6 hours.

## Tuning

Repo → Settings → Secrets and variables → Actions → **Variables**:

| Variable | Default | Meaning |
|---|---|---|
| `NTFY_SERVER` | `https://ntfy.sh` | point at a self-hosted ntfy |
| `DIGEST_HOUR` | `8` | hour of the daily digest, Asia/Jakarta |

Local run without sending anything:

```powershell
$env:PYTHONIOENCODING="utf-8"
python monitor.py --dry-run
```

Delete the `--dry-run` flag and set `NTFY_TOPIC` to push for real.

## Caveats

- GitHub cron is best-effort: a run can be delayed 5–30 minutes under load, and
  is occasionally dropped. Fine for seats; not a real-time guarantee.
- GitHub disables scheduled workflows after 60 days without repo activity. The
  script refreshes `lastHeartbeat` and CI commits it every 30 days, which keeps
  the workflow alive even if the seat count never moves.
- `state.json` is byte-identical when nothing changed, so quiet runs produce no
  commits.
- Only Batch 1 is tracked. Batch 2 opens when Batch 1 sells out; extend
  `parse_batch1` to return all four batches if you want them watched too.

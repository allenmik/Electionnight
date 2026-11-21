# The Rundown

A live NBA companion: a morning **Preview** (what and who to watch), a **Live** view with hot games, hot players and
a moment-by-moment feed (runs, crunch time, game-winners, season highs), and a nightly **Recap** that ranks the best
moments. One small Python server does all of it. **No AI model is involved at runtime, so it costs nothing but hosting.**

```
ESPN public endpoints  ->  server.py (polls + story engine)  ->  browsers (Server-Sent Events)
```

## Run it

```bash
cd rundown
python3 server.py          # needs Python 3.9+, no packages to install
# open http://localhost:8080
```

On Windows, double-click `Start-Rundown.bat` in this folder (or run `py server.py` in PowerShell).
Nothing needs installing besides Python itself.

The first start pulls the season from ESPN and builds the recap and preview (about a minute). After that:

| What | When |
|---|---|
| Live scores, alerts, hot players | every 20 s while games are on, every 2 min otherwise, pushed to every open browser |
| Recap | rebuilt automatically when the last game of a night ends |
| Preview | rebuilt once each morning after 7 am Eastern |

## What a fan sees

* **Watch now** bar on every tab: the hottest live game, why (crunch time, overtime, a run, a star line) and the channel.
* **Hot games** ranked by how worth-switching-to they are, each with a 5-bar heat meter; the hottest get chasing lights.
* **Where to watch**: national TV plus each team's local TV and streaming, from ESPN's broadcast listings.
* **Alerts**: one alert per player stat (a newer milestone replaces the older one), clips rated so only real action
  or hot players reach the main feed, scoreboard-style score rolls, blinking runs, fire stripes on hot players.
* **Jumbotron takeover** for the biggest moments (game-winners, buzzer-beaters, overtime, 50-point and 20-20 nights),
  with confetti. Add `?demo` to the address to play the effects on demand; demo alerts are labeled "Demo".
* Effects switch off for anyone with "reduce motion" turned on.

## Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `8080` | port to listen on |
| `RUNDOWN_DATA` | `./data` | where the season cache and generated files live (keep it on a persistent disk) |
| `POLL_SECONDS` | `20` | ESPN polling interval while a game is live |
| `IDLE_SECONDS` | `120` | polling interval when nothing is live |
| `SEASON_START` | `2026-10-20` | first day of the season to pull. **Change this each season.** |

## Deploy

Anything that runs a long-lived Python process works (a small VM, Fly.io, Railway, Render, a Raspberry Pi).

```bash
docker build -t rundown .
docker run -p 8080:8080 -v rundown-data:/data rundown
```

Two things matter on a host: the process must stay running (not scale to zero) because the polling loop lives in it,
and `RUNDOWN_DATA` should point at a persistent disk so a restart does not re-download the season.
If you put it behind a proxy, make sure it does not buffer `/events` (the server already sends `X-Accel-Buffering: no`).

## Endpoints

`/` the page · `/events` live stream · `/api/live` · `/api/digest` (recaps, form guide) · `/api/preview` · `/healthz`

## Tests

```bash
python3 tests/test_server.py          # recap rebuild after the last game, morning preview timing, polling speed
python3 tests/test_engine_replay.py   # replays a past night poll by poll (needs the data folder from one run)
REPLAY_FILE=data/live_replay_dev.json python3 server.py   # serve that replay as if it were live, for design work
```

## Layout

```
server.py            HTTP server, ESPN polling loop, push stream, nightly and morning jobs
static/index.html    the whole front end (one file, no build step)
engine/live_nba.py   live story engine (runs, crunch time, game-winners, records, hot players)
engine/analyze_nba.py, digest_nba.py   per-game analysis and the nightly "best moments" ranking
engine/preview_nba.py                  morning preview (matchups, injuries, who to watch)
engine/fetch_season.py, build_data.py  season download and standings
tests/                                 server job tests and a poll-by-poll engine replay
```

## Limits worth knowing

* The data comes from **ESPN's unofficial public endpoints**. They need no key and have worked well, but ESPN does not
  document or guarantee them and its terms do not cover a commercial product. Fine for a private page with friends;
  for anything public or paid, use a licensed feed and swap it into `engine/live_nba.py`.
* The feed runs roughly 20 to 60 seconds behind the live action (measured in `latency.csv` inside the data folder).
* Records are only what the data can prove (season highs, milestones, ESPN's own recap wording), not all-time records.
* NBA only. The structure is built so another sport is a new engine folder, not a rewrite.

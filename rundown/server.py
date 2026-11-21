#!/usr/bin/env python3
"""The Rundown: standalone NBA live-companion server. Python standard library only.

What it does (no AI model involved, so running it costs nothing but hosting):
  * polls ESPN's public endpoints every few seconds while games are on
  * runs the story engine (runs, crunch time, game-winners, hot players, records)
  * pushes every change to all open browsers over Server-Sent Events
  * rebuilds the nightly recap and the morning preview by itself

Run:   python3 server.py            (then open http://localhost:8080)
Env:   PORT (8080)  RUNDOWN_DATA (./data)  POLL_SECONDS (20)  IDLE_SECONDS (120)  SEASON_START (2026-10-20)
"""
import hashlib, json, os, queue, subprocess, sys, threading, time, traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(ROOT, 'engine')
STATIC = os.path.join(ROOT, 'static')
DATA = os.path.abspath(os.environ.get('RUNDOWN_DATA', os.path.join(ROOT, 'data')))
PORT = int(os.environ.get('PORT', '8080'))
POLL = int(os.environ.get('POLL_SECONDS', '20'))
IDLE = int(os.environ.get('IDLE_SECONDS', '120'))

os.makedirs(DATA, exist_ok=True)
os.chdir(DATA)                       # the engine reads and writes relative to the data folder
os.environ['RUNDOWN_DATA'] = DATA
sys.path.insert(0, ENGINE)
import live_nba                      # noqa: E402  (needs the path set above)
import analyze_nba                   # noqa: E402
from tzcompat import ET              # noqa: E402  US Eastern, works without a time-zone database

STATE = {'live': None, 'digest': None, 'preview': None, 'preview_for': None, 'maintained_for': None}
CLIENTS = set()
LOCK = threading.Lock()


def log(*a):
    print(datetime.now(timezone.utc).strftime('%H:%M:%S'), *a, flush=True)


def read_json(name):
    try:
        with open(os.path.join(DATA, name)) as f:
            return json.load(f)
    except Exception:
        return None


def run_engine(script, *args, timeout=900):
    """Run one of the batch scripts (season fetch, standings, digest, preview) inside the data folder."""
    try:
        r = subprocess.run([sys.executable, os.path.join(ENGINE, script), *args], cwd=DATA,
                           capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout,
                           env={**os.environ, 'PYTHONUTF8': '1'})   # Windows: player names with accents
        if r.returncode != 0:
            log('engine step failed:', script, (r.stderr or '')[-300:])
        return r.returncode == 0
    except Exception as e:
        log('engine step error:', script, e)
        return False


def broadcast(event, payload):
    msg = f'event: {event}\ndata: {json.dumps(payload, separators=(",", ":"))}\n\n'
    with LOCK:
        for q in list(CLIENTS):
            try:
                q.put_nowait(msg)
            except queue.Full:
                CLIENTS.discard(q)


def refresh_digest():
    ok = run_engine('fetch_season.py') and run_engine('build_data.py') and run_engine('digest_nba.py')
    d = read_json('nba_digest.json')
    if ok and d:
        STATE['digest'] = d
        broadcast('digest', d)
        log('recap rebuilt')
    return ok


def refresh_preview(today):
    run_engine('build_data.py')
    ok = run_engine('preview_nba.py', today.replace('-', ''))
    p = read_json('preview.json')
    if ok and p:
        STATE['preview'] = p
        STATE['preview_for'] = today
        broadcast('preview', p)
        log('preview rebuilt for', today)


def bootstrap():
    """First start: pull the season so recaps, form guide and the preview exist."""
    STATE['digest'] = read_json('nba_digest.json')
    STATE['preview'] = read_json('preview.json')
    STATE['live'] = read_json('live.json')
    if not STATE['digest']:
        log('first start: pulling the season from ESPN (about a minute)')
        refresh_digest()
    today = datetime.now(ET).date().isoformat()
    if not STATE['preview'] or (STATE['preview'] or {}).get('slate') != today:
        refresh_preview(today)
    else:
        STATE['preview_for'] = today


def signature(doc):
    d = {k: v for k, v in doc.items() if k not in ('updated', 'lag')}
    return hashlib.md5(json.dumps(d, sort_keys=True).encode()).hexdigest()


LOOP = {'sig': None, 'finals': 0}
REPLAY_FILE = os.environ.get('REPLAY_FILE')    # development only: serve a saved live document instead of polling ESPN


def step(doc, now=None):
    """Handle one poll result: push changes, rebuild the recap when a night ends, rebuild the preview each morning.
    Returns how long to wait before the next poll."""
    sig = signature(doc)
    STATE['live'] = doc
    if sig != LOOP['sig']:
        LOOP['sig'] = sig
        with open(os.path.join(DATA, 'live.json'), 'w') as f:
            json.dump(doc, f, separators=(',', ':'))
        broadcast('live', doc)
    else:
        broadcast('tick', {'updated': doc.get('updated'), 'lag': doc.get('lag')})
    # every game final on two polls in a row: rebuild the recap once for that slate
    LOOP['finals'] = LOOP['finals'] + 1 if doc.get('allfinal') else 0
    if LOOP['finals'] >= 2 and STATE['maintained_for'] != doc.get('slate'):
        STATE['maintained_for'] = doc.get('slate')
        threading.Thread(target=refresh_digest, daemon=True).start()
    # morning: build today's preview once, after 7am Eastern, when nothing is live
    now = now or datetime.now(ET)
    today = now.date().isoformat()
    if now.hour >= 7 and STATE['preview_for'] != today and not doc.get('live'):
        STATE['preview_for'] = today
        threading.Thread(target=refresh_preview, args=(today,), daemon=True).start()
    return POLL if doc.get('live') else IDLE


def live_loop():
    while True:
        wait = IDLE
        try:
            if REPLAY_FILE:
                with open(REPLAY_FILE) as f:
                    doc = json.load(f)
                doc['updated'] = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
            else:
                doc, _ = live_nba.poll()
            wait = step(doc)
        except Exception:
            log('poll failed (will retry):', traceback.format_exc().splitlines()[-1])
        time.sleep(wait)


# ---------------------------------------------------------------- one game: story first, full stats second
GAME_CACHE = {}
TEAM_STATS = [('fieldGoalPct', 'Field goal %'), ('threePointFieldGoalPct', '3-point %'), ('freeThrowPct', 'Free throw %'),
              ('totalRebounds', 'Rebounds'), ('offensiveRebounds', 'Offensive rebounds'), ('assists', 'Assists'),
              ('steals', 'Steals'), ('blocks', 'Blocks'), ('totalTurnovers', 'Turnovers'), ('turnoverPoints', 'Points off turnovers'),
              ('pointsInPaint', 'Points in the paint'), ('fastBreakPoints', 'Fast-break points'), ('largestLead', 'Largest lead'),
              ('fouls', 'Fouls')]
LOWER_IS_BETTER = {'totalTurnovers', 'fouls'}


def build_game(s, gid):
    hc = s['header']['competitions'][0]
    st = hc['status']['type']
    comps = sorted(hc['competitors'], key=lambda c: c['homeAway'] != 'away')          # away first
    teams = []
    for c in comps:
        t = c['team']
        teams.append({'abbr': t['abbreviation'], 'name': t.get('displayName'), 'short': t.get('shortDisplayName') or t.get('name'),
                      'color': '#' + (t.get('color') or '777777'), 'score': int(c.get('score') or 0), 'home': c['homeAway'] == 'home',
                      'line': [l.get('displayValue') for l in c.get('linescores') or []], 'winner': bool(c.get('winner')),
                      'record': next((r.get('summary') for r in c.get('record') or [] if r.get('type') == 'total'), None)})
    order = [t['abbr'] for t in teams]
    # team comparison
    tstats = {}
    for bt in s.get('boxscore', {}).get('teams', []):
        vals = {x.get('name'): x.get('displayValue') for x in bt.get('statistics', [])}
        tstats[bt['team']['abbreviation']] = vals
    compare = []
    for key, label in TEAM_STATS:
        if all(key in tstats.get(a, {}) for a in order):
            compare.append({'key': key, 'label': label, 'vals': [tstats[a][key] for a in order], 'low': key in LOWER_IS_BETTER})
    # full player lines
    players = {}
    for bp in s.get('boxscore', {}).get('players', []):
        grp = (bp.get('statistics') or [{}])[0]
        rows = []
        for a in grp.get('athletes', []):
            ath = a.get('athlete', {})
            rows.append({'id': ath.get('id'), 'name': ath.get('displayName'), 'pos': (ath.get('position') or {}).get('abbreviation', ''),
                         'num': ath.get('jersey', ''), 'starter': bool(a.get('starter')), 'dnp': bool(a.get('didNotPlay')) or not a.get('stats'),
                         'reason': (a.get('reason') or '').title() if a.get('didNotPlay') else '', 'stats': a.get('stats') or []})
        players[bp['team']['abbreviation']] = {'labels': grp.get('labels', []), 'rows': rows, 'totals': grp.get('totals', [])}
    # the story
    story = {}
    try:
        g = analyze_nba.analyze_game(s)
        story = {'lead_changes': g['lead_changes'], 'max_lead': {g['home']: g['max_lead_home'], g['away']: g['max_lead_away']},
                 'run': g.get('run'), 'comeback': g['comeback'], 'winshot': g.get('winshot'), 'tieshot': g.get('tieshot'),
                 'moments': g['moments'], 'headline': g.get('headline'), 'recap': g.get('recap'), 'videos': g['videos'][:8],
                 'flow': g.get('flow') or []}
    except Exception:
        story = {}
    plays = []
    for pl in reversed((s.get('plays') or [])[-15:]):
        plays.append({'text': pl.get('text'), 'clock': (pl.get('clock') or {}).get('displayValue'), 'per': (pl.get('period') or {}).get('number'),
                      'a': pl.get('awayScore'), 'h': pl.get('homeScore'), 'scoring': bool(pl.get('scoringPlay'))})
    gi = s.get('gameInfo') or {}
    venue = gi.get('venue') or {}
    live = STATE.get('live') or {}
    card = next((x for x in live.get('games', []) if x.get('gid') == gid), {})
    return {'gid': gid, 'state': st.get('state'), 'detail': st.get('shortDetail') or st.get('detail'), 'date': hc.get('date'),
            'teams': teams, 'compare': compare, 'players': players, 'story': story, 'plays': plays,
            'feed': [e for e in live.get('feed', []) if e.get('gid') == gid][::-1],
            'why': card.get('why', ''), 'tv': card.get('tv') or live_nba.networks(hc), 'cup': card.get('cup') or cup_for(gid),
            'info': {'venue': venue.get('fullName'), 'city': ', '.join(x for x in ((venue.get('address') or {}).get('city'), (venue.get('address') or {}).get('state')) if x),
                     'attendance': gi.get('attendance'), 'officials': [o.get('displayName') for o in gi.get('officials') or []]}}


def cup_for(gid):
    try:
        with open(os.path.join(DATA, 'cache', 'nba_events.json')) as f:
            ev = json.load(f).get(gid) or []
        return ev[2] if len(ev) > 2 else ''
    except Exception:
        return ''


def game_payload(gid):
    now = time.time()
    hit = GAME_CACHE.get(gid)
    if hit and (hit[1].get('state') == 'post' or now - hit[0] < 15):
        return hit[1]
    path = os.path.join(DATA, 'cache', 'nba', gid + '.json')
    if os.path.exists(path):
        with open(path) as f:
            s = json.load(f)
    else:
        s = live_nba.get(live_nba.B + 'summary?event=' + gid)
    payload = build_game(s, gid)
    if payload['state'] == 'post' and not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(s, f)
    GAME_CACHE[gid] = (now, payload)
    return payload


class Handler(BaseHTTPRequestHandler):
    server_version = 'Rundown/1.0'

    def log_message(self, *a):
        pass

    def send_body(self, code, ctype, body, extra=None):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split('?')[0]
        if path in ('/', '/index.html'):
            with open(os.path.join(STATIC, 'index.html'), 'rb') as f:
                return self.send_body(200, 'text/html; charset=utf-8', f.read())
        if path in ('/api/live', '/api/digest', '/api/preview'):
            data = STATE.get(path.split('/')[-1])
            body = json.dumps(data if data is not None else {}, separators=(',', ':')).encode()
            return self.send_body(200 if data is not None else 503, 'application/json', body)
        if path.startswith('/api/game/'):
            gid = path.rsplit('/', 1)[-1]
            if not gid.isdigit():
                return self.send_body(404, 'application/json', b'{}')
            try:
                body = json.dumps(game_payload(gid), separators=(',', ':')).encode()
                return self.send_body(200, 'application/json', body)
            except Exception as e:
                log('game page failed:', gid, e)
                return self.send_body(502, 'application/json', b'{}')
        if path == '/healthz':
            return self.send_body(200, 'text/plain', b'ok')
        if path == '/events':
            return self.stream()
        self.send_body(404, 'text/plain', b'not found')

    def stream(self):
        q = queue.Queue(maxsize=200)
        with LOCK:
            CLIENTS.add(q)
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.send_header('X-Accel-Buffering', 'no')
            self.end_headers()
            self.wfile.write(b'retry: 3000\n\n')
            self.wfile.flush()
            while True:
                try:
                    self.wfile.write(q.get(timeout=20).encode())
                except queue.Empty:
                    self.wfile.write(b': keep-alive\n\n')   # keeps proxies from closing the stream
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with LOCK:
                CLIENTS.discard(q)


if __name__ == '__main__':
    log('data folder:', DATA)
    threading.Thread(target=lambda: (bootstrap(), live_loop()), daemon=True).start()
    srv = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)
    srv.daemon_threads = True
    log(f'The Rundown is up on http://localhost:{PORT}')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass

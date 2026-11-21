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
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(ROOT, 'engine')
STATIC = os.path.join(ROOT, 'static')
DATA = os.path.abspath(os.environ.get('RUNDOWN_DATA', os.path.join(ROOT, 'data')))
PORT = int(os.environ.get('PORT', '8080'))
POLL = int(os.environ.get('POLL_SECONDS', '20'))
IDLE = int(os.environ.get('IDLE_SECONDS', '120'))
ET = ZoneInfo('America/New_York')

os.makedirs(DATA, exist_ok=True)
os.chdir(DATA)                       # the engine reads and writes relative to the data folder
os.environ['RUNDOWN_DATA'] = DATA
sys.path.insert(0, ENGINE)
import live_nba                      # noqa: E402  (needs the path set above)

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
                           capture_output=True, text=True, timeout=timeout)
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

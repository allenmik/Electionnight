"""Checks for the server's night-end and morning jobs. Run:  python3 tests/test_server.py  (no network needed)."""
import os, sys, tempfile, threading
from datetime import datetime

os.environ['RUNDOWN_DATA'] = tempfile.mkdtemp(prefix='rundown-test-')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import server  # noqa: E402

calls = {'digest': 0, 'preview': []}
server.refresh_digest = lambda: calls.__setitem__('digest', calls['digest'] + 1)
server.refresh_preview = lambda day: calls['preview'].append(day)
threading.Thread = lambda target, args=(), daemon=None: type('T', (), {'start': lambda self: target(*args)})()


def doc(slate, live=0, allfinal=False, n=0):
    return {'slate': slate, 'live': live, 'allfinal': allfinal, 'games': [{'gid': str(n)}], 'updated': str(n)}


evening = server.ET and datetime(2026, 11, 21, 22, 0, tzinfo=server.ET)
server.STATE['preview_for'] = '2026-11-21'

# live games: no recap yet
server.step(doc('2026-11-21', live=2, n=1), evening)
assert calls['digest'] == 0
# first all-final poll: wait one more poll in case a late game is just updating
server.step(doc('2026-11-21', allfinal=True, n=2), evening)
assert calls['digest'] == 0, 'rebuilt too early'
# second all-final poll: rebuild exactly once
server.step(doc('2026-11-21', allfinal=True, n=3), evening)
server.step(doc('2026-11-21', allfinal=True, n=4), evening)
server.step(doc('2026-11-21', allfinal=True, n=5), evening)
assert calls['digest'] == 1, f"expected one recap rebuild, got {calls['digest']}"
# next night: one more rebuild
server.step(doc('2026-11-22', allfinal=True, n=6), evening)
server.step(doc('2026-11-22', allfinal=True, n=7), evening)
assert calls['digest'] == 2

# morning preview: not before 7am Eastern, once after, never while games are live
server.step(doc('2026-11-22', n=8), datetime(2026, 11, 23, 6, 30, tzinfo=server.ET))
assert calls['preview'] == []
server.step(doc('2026-11-23', live=1, n=9), datetime(2026, 11, 23, 9, 0, tzinfo=server.ET))
assert calls['preview'] == [], 'should wait while a game is live'
server.step(doc('2026-11-23', n=10), datetime(2026, 11, 23, 9, 0, tzinfo=server.ET))
server.step(doc('2026-11-23', n=11), datetime(2026, 11, 23, 10, 0, tzinfo=server.ET))
assert calls['preview'] == ['2026-11-23'], calls['preview']

# polling speed follows the games
assert server.step(doc('2026-11-23', live=1, n=12)) == server.POLL
assert server.step(doc('2026-11-23', n=13)) == server.IDLE
print('server tests passed')

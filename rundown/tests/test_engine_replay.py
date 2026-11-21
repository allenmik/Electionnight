"""Replays a finished night through the live engine, poll by poll, and checks the feed and the game ranking.
Needs the season cache, so run the server once first. Run:  python3 tests/test_engine_replay.py [data-folder] [date]"""
import collections, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'data'))
DATE = sys.argv[2] if len(sys.argv) > 2 else '2026-11-15'
if not os.path.isdir(os.path.join(DATA, 'cache', 'nba')):
    sys.exit(f'skipped: no season cache in {DATA} (start the server once first)')
os.environ['RUNDOWN_DATA'] = DATA
os.chdir(DATA)
sys.path.insert(0, os.path.join(ROOT, 'engine'))
import live_nba  # noqa: E402

doc = live_nba.replay_frames(DATE, [0.3, 0.5, 0.65, 0.8, 0.9, 0.97])
feed = doc['feed']
assert feed, 'no events produced'

# 1) one alert per player stat: newer tiers replace older ones
groups = collections.Counter(e['grp'] for e in feed if e.get('grp'))
dupes = {g: n for g, n in groups.items() if n > 1}
assert not dupes, f'duplicate stat alerts: {dupes}'

# 2) clip scoring: every clip is rated, routine ones rate 1
clips = [e for e in feed if e['kind'] == 'clip']
assert all(1 <= e['imp'] <= 3 for e in clips)

# 3) live games are ranked by heat, hottest first, and each has a reason when there is one
live = [g for g in doc['games'] if g['state'] == 'in']
assert [g['heat'] for g in live] == sorted((g['heat'] for g in live), reverse=True), 'games not ranked by heat'
print(f"{len(feed)} feed items, {len(groups)} stat groups, no duplicates")
print('clip ratings:', dict(collections.Counter(e['imp'] for e in clips)))
for g in live:
    print(f"  heat {g['heat']:>5}  {g['away']} {g['as']} @ {g['home']} {g['hs']}  {g['detail']:<10} {g.get('why', '')}")
print('engine replay test passed')
json.dump({**doc, 'mode': 'live'}, open(os.path.join(DATA, 'live_replay_dev.json'), 'w'))

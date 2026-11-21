import json,urllib.request,os,sys,datetime,concurrent.futures as cf
from zoneinfo import ZoneInfo
B="https://site.api.espn.com/apis/site/v2/sports/basketball/nba/"
def get(u,tries=3):
    for i in range(tries):
        try: return json.load(urllib.request.urlopen(u,timeout=40))
        except Exception as e:
            if i==tries-1: raise
os.makedirs('cache/nba',exist_ok=True)
start=datetime.date.fromisoformat(os.environ.get('SEASON_START','2026-10-20')); end=datetime.datetime.now(ZoneInfo('America/New_York')).date()
events={}
d=start
while d<=end:
    sb=get(B+"scoreboard?dates="+d.strftime("%Y%m%d"))
    for e in sb['events']:
        events[e['id']]=(d.isoformat(),e['status']['type']['state'])
    d+=datetime.timedelta(days=1)
fin=[i for i,(dt,st) in events.items() if st=='post']
print('events',len(events),'final',len(fin))
def one(i):
    p=f'cache/nba/{i}.json'
    if os.path.exists(p): return 0
    s=get(B+"summary?event="+i)
    json.dump(s,open(p,'w'))
    return 1
with cf.ThreadPoolExecutor(8) as ex:
    n=sum(ex.map(one,fin))
json.dump({i:v for i,v in events.items()},open('cache/nba_events.json','w'))
print('fetched',n)

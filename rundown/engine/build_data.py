import json, urllib.request, datetime
from zoneinfo import ZoneInfo
B="https://site.api.espn.com/apis/"
def get(u):
    return json.load(urllib.request.urlopen(u, timeout=30))
teams={}
for t in get(B+"site/v2/sports/basketball/nba/teams")['sports'][0]['leagues'][0]['teams']:
    t=t['team']; teams[t['id']]={'abbr':t['abbreviation'],'name':t['displayName'],'short':t['shortDisplayName'],'color':'#'+t.get('color','777777'),'alt':'#'+t.get('alternateColor','ffffff')}
st=get(B+"v2/sports/basketball/nba/standings")
standings=[]
for ch in st['children']:
    conf='East' if ch['name'].startswith('East') else 'West'
    for e in ch['standings']['entries']:
        s={x['name']:x.get('displayValue') for x in e['stats']}
        tid=e['team']['id']
        standings.append({'id':tid,'conf':conf,**{k:teams[tid][k] for k in ('abbr','name','short','color')},
          'w':int(s['wins']),'l':int(s['losses']),'pf':float(s['avgPointsFor']),'pa':float(s['avgPointsAgainst']),
          'diff':float(s['differential']),'streak':s['streak'],'home':s['Home'],'road':s['Road'],'l10':s['Last Ten Games'],
          'seed':int(float(s['playoffSeed'])),'conf_rec':s.get('vs. Conf.')})
games=[]
today=datetime.datetime.now(ZoneInfo('America/New_York')).date()
for d in range(-3,2):
    day=today+datetime.timedelta(days=d)
    sb=get(B+"site/v2/sports/basketball/nba/scoreboard?dates="+day.strftime("%Y%m%d"))
    for e in sb['events']:
        c=e['competitions'][0]
        cs={x['homeAway']:x for x in c['competitors']}
        games.append({'date':day.isoformat(),'time':e['date'],'status':e['status']['type']['description'],'state':e['status']['type']['state'],
          'home':cs['home']['team']['abbreviation'],'away':cs['away']['team']['abbreviation'],
          'hs':int(cs['home'].get('score') or 0),'as':int(cs['away'].get('score') or 0)})
out={'updated':datetime.datetime.utcnow().isoformat()+'Z','season':'2026-27','source':'ESPN public API','standings':standings,'games':games}
json.dump(out,open('nba.json','w'),separators=(',',':'))
print(len(standings),len(games),len(json.dumps(out)))
for g in games[-8:]: print(g)
print(sorted(standings,key=lambda x:-x['w']/(x['w']+x['l']))[:3])

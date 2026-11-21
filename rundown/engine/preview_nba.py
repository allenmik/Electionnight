"""Morning preview: what to watch + who to watch for today's slate."""
import json,collections,urllib.request,sys
from datetime import datetime,timedelta,timezone
from analyze_nba import load_all,et_date
from live_nba import networks, cup_label
B="https://site.api.espn.com/apis/site/v2/sports/basketball/nba/"
get=lambda u:json.load(urllib.request.urlopen(u,timeout=30))
G=load_all()
snap=json.load(open('nba.json'));S={t['abbr']:t for t in snap['standings']}
tn=lambda a:S.get(a,{}).get('short',a)
logs=collections.defaultdict(list);teamdates=collections.defaultdict(set)
for g in G:
    teamdates[g['home']].add(g['date']);teamdates[g['away']].add(g['date'])
    for p in g['players']:
        if p['min']>=8: logs[p['id']].append({**p,'date':g['date'],'opp':g['away'] if p['team']==g['home'] else g['home']})
def pstats(pid):
    L=logs[pid]
    if len(L)<5: return None
    avg=lambda xs:sum(xs)/len(xs)
    l3=L[-3:];prev=L[:-3] or L
    return {'id':pid,'name':L[-1]['name'],'team':L[-1]['team'],'games':len(L),'ppg':round(avg([x['pts'] for x in L]),1),'rpg':round(avg([x['reb'] for x in L]),1),'apg':round(avg([x['ast'] for x in L]),1),
            'min':round(avg([x['min'] for x in L]),1),'spg':round(avg([x['stl'] for x in L]),1),'bpg':round(avg([x['blk'] for x in L]),1),'tpg':round(avg([x['tpm'] for x in L]),1),'l3reb':round(avg([x['reb'] for x in l3]),1),'l3ast':round(avg([x['ast'] for x in l3]),1),'l3ppg':round(avg([x['pts'] for x in l3]),1),'delta':round(avg([x['gs'] for x in l3])-avg([x['gs'] for x in prev]),1),
            'l3gs':round(avg([x['gs'] for x in l3]),1),'hi':max(x['pts'] for x in L),'last':[x['pts'] for x in l3],'lastdate':L[-1]['date']}
def streaks():
    res=collections.defaultdict(list)
    for g in G:
        res[g['home']].append((g['ts'],g['hs']>g['as']));res[g['away']].append((g['ts'],g['as']>g['hs']))
    out={}
    for t,L in res.items():
        L.sort();n=1
        while n<len(L) and L[-1-n][1]==L[-1][1]: n+=1
        out[t]={'t':'W' if L[-1][1] else 'L','n':n}
    return out
sk=streaks()
sb=get(B+"scoreboard?dates="+sys.argv[1]) if len(sys.argv)>1 else get(B+"scoreboard")
ev=sorted(sb['events'],key=lambda e:e['date'])
slate=et_date(ev[0]['date']) if ev else None
offr=sorted(S,key=lambda a:-S[a]['pf']);defr=sorted(S,key=lambda a:S[a]['pa']);by_pct=sorted(S,key=lambda a:-S[a]['w']/max(1,S[a]['w']+S[a]['l']))
games=[];allplayers={}
yday=(datetime.fromisoformat(slate)-timedelta(days=1)).date().isoformat() if slate else None
for e in ev:
    c=e['competitions'][0];cs={x['homeAway']:x for x in c['competitors']}
    A,H=cs['away']['team']['abbreviation'],cs['home']['team']['abbreviation']
    try: s=get(B+"summary?event="+e['id'])
    except Exception: s={}
    pc=(s.get('pickcenter') or [{}])[0] if s else {}
    sp=pc.get('spread');fav=None
    if sp is not None: fav=(H if sp<0 else A,abs(sp))
    inj=[]
    for t in s.get('injuries',[]) or []:
        ab=t['team']['abbreviation']
        for i in t.get('injuries',[]):
            a=i.get('athlete',{});st_=i.get('status') or i.get('type',{}).get('description','')
            nm=a.get('displayName');pid=a.get('id')
            ps=pstats(pid) if pid in logs else None
            if ps and ps['ppg']>=12 and st_ in('Out','Doubtful','Questionable','Day-To-Day'): inj.append({'name':nm,'team':ab,'status':st_,'ppg':ps['ppg']})
    inj.sort(key=lambda x:-x['ppg'])
    why=[];score=0
    for t in (A,H):
        k=sk.get(t)
        if k and k['t']=='W' and k['n']>=5: why.append(f"{tn(t)} have won {k['n']} straight");score+=k['n']*2
        if k and k['t']=='L' and k['n']>=5: why.append(f"{tn(t)} are trying to snap a {k['n']}-game skid");score+=k['n']
        if yday in teamdates[t] : why.append(f"{tn(t)} on the second night of a back-to-back");score+=0
    if by_pct.index(A)<6 and by_pct.index(H)<6: why.append("Two of the league’s top six records");score+=16
    for x,y in((A,H),(H,A)):
        if offr.index(x)<5 and defr.index(y)<5: why.append(f"{tn(x)}'s top-5 offense against {tn(y)}'s top-5 defense");score+=8
    if fav and fav[1]<=3: why.append(f"Tight line: {fav[0]} -{fav[1]:g}");score+=8
    if fav and fav[1]>=10: why.append(f"{fav[0]} heavy favorites (-{fav[1]:g})")
    # players
    kp=[]
    for t in (A,H):
        cand=[pstats(p) for p in logs if logs[p] and logs[p][-1]['team']==t]
        cand=[c_ for c_ in cand if c_ and c_['min']>=22 and (yday<=c_['lastdate'] or True)]
        outn={i['name'] for i in inj if i['status']=='Out'}
        cand=[c_ for c_ in cand if c_['name'] not in outn]
        cand.sort(key=lambda x:-(x['ppg']+max(0,x['delta'])*1.2))
        for c_ in cand[:2]:
            kp.append(c_);allplayers[c_['id']]={**c_,'game':f"{A} @ {H}",'gid':e['id']}
            if c_['delta']>=6 and c_['l3gs']>=17: score+=6;why.append(f"{c_['name']} is heating up ({c_['l3ppg']} ppg last 3)")
    games.append({'gid':e['id'],'away':A,'home':H,'time':e['date'],'arec':f"{S[A]['w']}-{S[A]['l']}",'hrec':f"{S[H]['w']}-{S[H]['l']}",
                  'tv':networks(c),'cup':cup_label(c),'fav':fav[0] if fav else None,'spread':fav[1] if fav else None,'ou':pc.get('overUnder'),'score':score,'why':why[:4],'key':kp,'inj':inj[:4],
                  'b2b':[t for t in (A,H) if yday in teamdates[t]]})
games.sort(key=lambda g:-g['score'])
def tags_for(p):
    t=[]
    if p['delta']>=6: t.append('Heating up')
    if p['ppg']>=27: t.append('Scoring star')
    if p['rpg']>=10: t.append(f"Glass cleaner ({p['rpg']} reb)")
    if p['apg']>=7: t.append(f"Playmaker ({p['apg']} ast)")
    if p['bpg']>=1.6: t.append(f"Rim protector ({p['bpg']} blk)")
    if p['spg']>=1.6: t.append(f"Thief ({p['spg']} stl)")
    if p['tpg']>=3: t.append(f"Sniper ({p['tpg']} threes)")
    return t
for p_ in allplayers.values(): p_['tags']=tags_for(p_)
watch=sorted([p_ for p_ in allplayers.values() if p_['tags'] or p_['ppg']>=18],key=lambda p:-(p['ppg']*0.6+p['rpg']*0.9+p['apg']*0.9+max(0,p['delta'])*1.5+(8 if p['delta']>=6 else 0)))[:16]
out={'slate':slate,'updated':datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z'),'games':games,'players':watch}
json.dump(out,open('preview.json','w'),separators=(',',':'))
print(slate,len(games),'games',len(json.dumps(out)),'bytes')
for g in games: print(g['away'],'@',g['home'],g['score'],g['why'],[ (p['name'],p['ppg'],p['l3ppg']) for p in g['key']][:4],g['inj'][:2])
print([ (p['name'],p['ppg'],p['l3ppg'],p['delta']) for p in watch])

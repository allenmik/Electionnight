import json,collections,statistics as st
from datetime import datetime,timedelta
from analyze_nba import load_all
G=load_all()
teams={t['abbr']:t for t in json.load(open('nba.json'))['standings']}
tname=lambda a:teams.get(a,{}).get('short',a)
def margin_str(g): return f"{max(g['hs'],g['as'])}-{min(g['hs'],g['as'])}"
def thrill(g):
    s=0
    s+=max(0,40-g['margin']*2.2)                    # closeness of final
    s+=min(g['lead_changes'],14)*1.6
    s+=g['ot']*14
    if g['clutch_margin'] is not None: s+= {True:12}.get(g['clutch_margin']<=3,0) or (6 if g['clutch_margin']<=6 else 0)
    if g['comeback']>=15: s+=min(g['comeback'],25)*0.6
    s+=min(g['excite'],12)*0.8
    return round(s,1)
# ---- per-player season logs (all games, chronological)
logs=collections.defaultdict(list)
for g in G:
    for p in g['players']:
        if p['min']>=8: logs[p['id']].append({**p,'date':g['date'],'gid':g['id'],'opp':g['away'] if p['team']==g['home'] else g['home'],'home':p['team']==g['home']})
def asof_trend(pid,date):
    L=[x for x in logs[pid] if x['date']<=date]
    if len(L)<9: return None
    last=L[-3:];prev=L[:-3]
    if not prev or L[-1]['date']!=date: return None
    lg=sum(x['gs'] for x in last)/3;pg=sum(x['gs'] for x in prev)/len(prev)
    lp=sum(x['pts'] for x in last)/3;pp=sum(x['pts'] for x in prev)/len(prev)
    avgmin=sum(x['min'] for x in L)/len(L)
    also=[]
    for k_,th,lab in (('reb',3,'reb'),('ast',3,'ast'),('stl',1,'stl'),('blk',1,'blk'),('tpm',1.5,'threes')):
        a3=sum(x[k_] for x in last)/3;ap=sum(x[k_] for x in prev)/len(prev)
        if a3-ap>=th and a3>=(1.5 if k_ in('stl','blk') else 3 if k_=='tpm' else 5): also.append(f"{a3:.1f} {lab} (was {ap:.1f})")
    return {'also':also,'id':pid,'name':L[-1]['name'],'team':L[-1]['team'],'last3_pts':round(lp,1),'season_pts':round(pp,1),'last3_gs':round(lg,1),'season_gs':round(pg,1),
            'delta':round(lg-pg,1),'min':round(avgmin,1),'games':len(L),'line':[{'p':x['pts'],'o':x['opp'],'d':x['date']} for x in last]}
def streaks(date):
    res=collections.defaultdict(list)
    for g in G:
        if g['date']<=date:
            res[g['home']].append((g['date'],g['hs']>g['as'])); res[g['away']].append((g['date'],g['as']>g['hs']))
    out={}
    for t,L in res.items():
        L.sort(); n=1
        while n<len(L) and L[-1-n][1]==L[-1][1]: n+=1
        out[t]={'type':'W' if L[-1][1] else 'L','n':n,'played':L[-1][0],'w':sum(1 for _,w in L if w),'l':sum(1 for _,w in L if not w),
                'l10':sum(1 for _,w in L[-10:] if w)}
    return out
import re
REC_RE=re.compile(r"[^.]*\b(record|franchise|history|career[- ]high|career night|first time since|since \d{4}|most [a-z0-9 ]{0,30} since)\b[^.]*\.",re.I)
INJ_RE=re.compile(r"[^.]*\b(left the game|did not return|exited|helped off|to the locker room|suffered|injured his)\b[^.]*\.",re.I)
SLAM_RE=re.compile(r"poster|slam|dunk|alley|jam|flush|windmill|monster|thunderous",re.I)
ABBR=re.compile(r"\b(Jr|Sr|St|Mr|Dr|Mrs)\.")
def prot(t): return ABBR.sub(lambda m:m.group(1)+'§',t or '')
def unprot(t): return t.replace('§','.')
poss=lambda n:n+("'" if n.endswith('s') else "'s")
def trunc(s,n=190):
    return s if len(s)<=n else s[:n].rsplit(' ',1)[0]+'…'
def shooter(t): return re.split(r' makes | hits ',t)[0]

def player_hot(p):
    comps={}
    gs=p['gs'];pts=p['pts'];reb=p['reb'];ast=p['ast'];stl=p['stl'];blk=p['blk'];tpm=p['tpm']
    if gs>=28: comps['pts']=55+(gs-28)*2.2
    if pts>=40: comps['pts']=max(comps.get('pts',0),65+(pts-40)*2)
    elif pts>=35: comps['pts']=max(comps.get('pts',0),45)
    elif pts>=30: comps['pts']=max(comps.get('pts',0),32)
    if reb>=13: comps['reb']=50+(reb-13)*4
    if ast>=11: comps['ast']=50+(ast-11)*4
    if stl>=4: comps['stl']=45+(stl-4)*9
    if blk>=4: comps['blk']=45+(blk-4)*9
    if tpm>=6: comps['tpm']=45+(tpm-6)*6
    cats=sorted([pts,reb,ast,stl,blk],reverse=True)
    if cats[0]>=10 and cats[1]>=10 and cats[2]>=10: comps['td']=62
    if pts>=20 and reb>=20: comps['tt']=72
    if p['fga']>=10 and p['fgm']/p['fga']>=.75 and pts>=20: comps['eff']=40
    badges=[]
    if pts>=25: badges.append(f"{pts} pts")
    if reb>=11: badges.append(f"{reb} reb")
    if ast>=9: badges.append(f"{ast} ast")
    if stl>=3: badges.append(f"{stl} stl")
    if blk>=3: badges.append(f"{blk} blk")
    if tpm>=5: badges.append(f"{tpm} threes")
    if 'td' in comps: badges.append('triple-double')
    elif cats[0]>=10 and cats[1]>=10: badges.append('double-double')
    if 'tt' in comps: badges.append('20-20')
    if 'eff' in comps: badges.append(f"{p['fgm']}-of-{p['fga']} shooting")
    if not comps: return {'score':0,'badges':badges,'label':'Big night'}
    top=max(comps,key=comps.get);sc=comps[top]+0.25*(sum(comps.values())-comps[top])
    label={'pts':'On fire' if (pts>=40 or gs>=32) else 'Big night','reb':'Glass cleaner','ast':'Dime machine','stl':'Defensive wall','blk':'Defensive wall','tpm':'Sharpshooter','td':'Triple-double','tt':'20-20 night','eff':'Perfect touch'}[top]
    return {'score':sc,'badges':badges,'label':label}

def story_player(date,g,p):
    bits=[f"{p['pts']} pts"]
    if p['reb']>=5:bits.append(f"{p['reb']} reb")
    if p['ast']>=5:bits.append(f"{p['ast']} ast")
    if p['stl']>=3:bits.append(f"{p['stl']} stl")
    if p['blk']>=3:bits.append(f"{p['blk']} blk")
    extra=[]
    if p['dd']>=3: extra.append('triple-double')
    elif p['dd']==2: extra.append('double-double')
    if p['tpm']>=6: extra.append(f"{p['tpm']} threes")
    return bits,extra
def build_night(date):
    gs=[g for g in G if g['date']==date]
    if not gs: return None
    stories=[];standouts=[];sk=streaks(date)
    for g in gs:
        h,a=g['home'],g['away'];w=g['winner'];l=a if w==h else h
        tag=f"{a} @ {h}"
        th=thrill(g);g['thrill']=th
        # thriller
        if th>=45:
            kick=[f"{g['lead_changes']} lead changes" if g['lead_changes']>=6 else None, f"decided by {g['margin']}" if g['margin']<=6 else None,
                  f"{g['ot']}OT" if g['ot'] else None, f"{tname(w)} trailed by {g['comeback']}" if g['comeback']>=12 else None]
            stories.append({'kind':'thriller','label':'Thriller','score':th,'gid':g['id'],'game':tag,'head':g['headline'] or f"{tname(w)} edge {tname(l)} {margin_str(g)}",
                            'facts':[k for k in kick if k]})
        if g['comeback']>=15:
            stories.append({'kind':'comeback','label':'Comeback','score':40+g['comeback']*2.2,'gid':g['id'],'game':tag,'head':g['headline'] or f"{tname(w)} rally from {g['comeback']} down",
                            'facts':[f"Trailed by {g['comeback']}",f"Won {margin_str(g)}"]})
        if g.get('upset') and g['fav_by']>=5:
            stories.append({'kind':'upset','label':'Upset','score':35+g['fav_by']*3.2,'gid':g['id'],'game':tag,'head':g['headline'] or f"{tname(w)} stun {tname(l)}",
                            'facts':[f"{l} were {g['fav_by']:g}-point favorites",f"Won {margin_str(g)}"]})
        if g['margin']>=22:
            ht=g.get('halftime'); 
            facts=[f"Final {margin_str(g)}"]
            if ht: 
                hm=abs(ht[0]-ht[1]); facts.append(f"{hm}-point lead at the half")
            if g.get('run') and g['run']['pts']>=14: facts.append(f"{g['run']['team']} ran off {g['run']['pts']} straight")
            stories.append({'kind':'blowout','label':'Blowout','score':28+g['margin']*1.6,'gid':g['id'],'game':tag,'head':g['headline'] or f"{tname(w)} rout {tname(l)}",'facts':facts})
        if g.get('run') and g['run']['pts']>=17 and g['margin']<22:
            stories.append({'kind':'run','label':'Big run','score':30+g['run']['pts']*1.8,'gid':g['id'],'game':tag,'head':f"{tname(g['run']['team'])} ripped off a {g['run']['pts']}-0 run",
                            'facts':[f"{g['run']['from']} to {g['run']['to']}",f"Final {margin_str(g)}"]})
        for p in g['players']:
            bits,extra=story_player(date,g,p)
            hv=player_hot(p)
            if hv['score']>0 or p['gs']>=20:
                opp=a if p['team']==h else h
                standouts.append({'pts':p['pts'],'reb':p['reb'],'ast':p['ast'],'stl':p['stl'],'blk':p['blk'],'tpm':p['tpm'],'name':p['name'],'team':p['team'],'gid':g['id'],'game':tag,'score':round(hv['score']+p['gs']*0.3,1),'badges':hv['badges'] or [f"{p['pts']} pts"],
                                  'line':f"{p['pts']} pts, {p['reb']} reb, {p['ast']} ast"+(f", {p['stl']} stl" if p['stl']>=2 else '')+(f", {p['blk']} blk" if p['blk']>=2 else ''),
                                  'shoot':f"{p['fg']} FG, {p['tp']} 3PT",'res':f"{'W' if p['team']==w else 'L'} {margin_str(g)} vs {opp}",'min':p['min'],'label':hv['label']})
            if hv['score']>=50:
                eff=f"{p['fg']} FG" + (f", {p['tpm']}-for-{p['tp'].split('-')[1]} from deep" if p['tpm']>=5 else '')
                stories.append({'kind':'player','label':hv['label'],'score':min(hv['score'],100)+(8 if p['team']==w else 0),
                                'gid':g['id'],'game':tag,'pid':p['id'],'name':p['name'],'team':p['team'],'head':f"{p['name']}: "+", ".join(bits),
                                'facts':extra+[eff,f"{'Win' if p['team']==w else 'Loss'} {margin_str(g)} vs {a if p['team']==h else h}"],'gs':p['gs']})
    # ---- headline-grabbing moments beyond individual stat lines
    pre_sk=streaks(str((datetime.fromisoformat(date)-timedelta(days=1)).date()))
    pct_end={t:(s['w']/max(1,s['w']+s['l'])) for t,s in sk.items()}
    for g in gs:
        h,a=g['home'],g['away'];w=g['winner'];l=a if w==h else h;tag=f"{a} @ {h}"
        ws=g.get('winshot')
        if ws:
            who=shooter(ws['text']);buzz=ws['sec']<=1.5
            stories.append({'kind':'winner','label':'Buzzer-beater' if buzz else 'Game-winner','score':100 if buzz else 94,'gid':g['id'],'game':tag,
                'head':f"{who} wins it for {tname(w)} {'at the buzzer' if buzz else 'with '+ws['clock']+' left'}",'facts':[f"{ws['text']}",f"Final {margin_str(g)}"+(' (OT)' if g['ot'] else '')]})
        ts=g.get('tieshot')
        if ts:
            stories.append({'kind':'winner','label':'Forces OT','score':86,'gid':g['id'],'game':tag,'head':f"{shooter(ts['text'])} ties it with {ts['clock']} left in regulation",'facts':[ts['text'],f"{tname(w)} won {margin_str(g)} in OT"]})
        txt=g.get('rtext') or ''
        m=REC_RE.search(prot(g.get('recap')))
        if m:
            sent=unprot(m.group(0)).strip().lstrip('—').strip()
            big=re.search(r'record|franchise|history',sent,re.I)
            stories.append({'kind':'record','label':'Record watch' if big else 'Career night','score':84 if big else 66,'gid':g['id'],'game':tag,'head':trunc(sent),'facts':['From the ESPN recap']})
        m=INJ_RE.search(prot(g.get('recap')))
        if m: stories.append({'kind':'injury','label':'Injury','score':82,'gid':g['id'],'game':tag,'head':trunc(unprot(m.group(0)).strip().lstrip('—').strip()),'facts':['From the ESPN recap']})
        # streak snapped / skid snapped
        ow=pre_sk.get(l);ol=pre_sk.get(w)
        if ow and ow['type']=='W' and ow['n']>=6: stories.append({'kind':'snapped','label':'Streak snapped','score':58+ow['n']*3,'gid':g['id'],'game':tag,'head':f"{tname(w)} end {poss(tname(l))} {ow['n']}-game winning streak",'facts':[f"Final {margin_str(g)}"]})
        if ol and ol['type']=='L' and ol['n']>=6: stories.append({'kind':'snapped','label':'Skid snapped','score':54+ol['n']*3,'gid':g['id'],'game':tag,'head':f"{tname(w)} finally win after {ol['n']} straight losses",'facts':[f"Final {margin_str(g)}"]})
        # statement win over a top team
        if pct_end.get(l,0)>=.72 and g['margin']>=10 and w==a: stories.append({'kind':'statement','label':'Statement win','score':52+g['margin'],'gid':g['id'],'game':tag,'head':f"{tname(w)} win big on the road against {tname(l)}",'facts':[f"{tname(l)} are {teams[l]['w']}-{teams[l]['l']}",f"Final {margin_str(g)}"]})
    # best slam / highlight clip of the night
    cl=[]
    for g in gs:
        for v in g['videos']:
            if re.search(r'game highlights',v['t'],re.I): continue
            sc=0
            if re.search(r'poster|posterize|windmill|thunderous|monster|between the legs|behind the back|half-court|logo|buzzer|game-winner',v['t'],re.I): sc+=3
            if SLAM_RE.search(v['t']): sc+=2
            if re.search(r'block',v['t'],re.I): sc+=1
            if sc>=2: cl.append((sc+g['thrill']/60,g,v))
    cl.sort(key=lambda x:-x[0])
    for sc,g,v in cl[:2]:
        stories.append({'kind':'highlight','label':'Highlight','score':50+sc*3,'gid':g['id'],'game':f"{g['away']} @ {g['home']}",'head':v['t'],'u':v['u'],'facts':[f"{g['away']} {g['as']}, {g['home']} {g['hs']}"]})
    # streak stories (teams that played that night)
    played={x for g in gs for x in (g['home'],g['away'])}
    for t in played:
        s=sk[t]
        if s['played']!=date: continue
        if s['type']=='W' and s['n']>=6:
            stories.append({'kind':'streak','label':'Win streak','score':36+s['n']*5,'team':t,'head':f"{tname(t)} have won {s['n']} straight",'facts':[f"{s['w']}-{s['l']} on the season",f"{s['l10']}-{10-s['l10']} last 10"]})
        if s['type']=='L' and s['n']>=6:
            stories.append({'kind':'slump','label':'Skid','score':30+s['n']*4,'team':t,'head':f"{tname(t)} have dropped {s['n']} in a row",'facts':[f"{s['w']}-{s['l']} on the season"]})
    # heating up (as-of that date, player played that night)
    for g in gs:
        for p in g['players']:
            tr=asof_trend(p['id'],date)
            if tr and tr['delta']>=6 and tr['last3_gs']>=17 and tr['min']>=20:
                stories.append({'kind':'heating','label':'Heating up','score':34+tr['delta']*3,'pid':p['id'],'name':p['name'],'team':p['team'],'gid':g['id'],
                                'head':f"{p['name']} is heating up: {tr['last3_pts']} ppg over his last 3",
                                'facts':[f"Season avg before that: {tr['season_pts']} ppg",' · '.join(f"{x['p']} vs {x['o']}" for x in tr['line'])],'game':f"{g['away']} @ {g['home']}"})
    # dedupe: one story per game for game-kinds is too strict; keep top per (kind,gid/pid)
    seen=set();uniq=[]
    for s in sorted(stories,key=lambda s:-s['score']):
        k=(s['kind'],s.get('pid') or s.get('gid') or s.get('team'))
        if k in seen: continue
        seen.add(k);uniq.append(s)
    recg={s['gid'] for s in uniq if s['kind'] in('record',) and s.get('gid')}
    uniq=[s for s in uniq if not(s['kind']=='blowout' and s.get('gid') in recg)]
    # diversity: max 3 per game, max 4 players
    out=[];cg=collections.Counter();ck=collections.Counter()
    for s in uniq:
        if cg[s.get('gid')]>=3 and s.get('gid'): continue
        if ck[s['kind']]>=(4 if s['kind'] in ('player',) else 3 if s['kind'] in ('heating',) else 2 if s['kind'] in ('slump','streak','highlight','blowout','run') else 4): continue
        cg[s.get('gid')]+=1;ck[s['kind']]+=1;out.append(s)
    top=out[:10]
    # game cards
    cards=[]
    for g in sorted(gs,key=lambda g:-g['thrill']):
        tags=[]
        if g['ot']:tags.append(f"{g['ot']}OT" if g['ot']>1 else 'OT')
        if g['margin']<=5:tags.append('Nail-biter')
        if g['comeback']>=15:tags.append(f"{g['comeback']}-pt comeback")
        if g.get('upset') and g['fav_by']>=5:tags.append('Upset')
        if g['margin']>=22:tags.append('Blowout')
        if g['lead_changes']>=10:tags.append(f"{g['lead_changes']} lead changes")
        pl=sorted(g['players'],key=lambda p:-p['gs'])[:2]
        # best moment: top scoring play by wp swing in Q4/OT, else top overall
        m=g['moments'][0] if g['moments'] else None
        cards.append({'gid':g['id'],'home':g['home'],'away':g['away'],'hs':g['hs'],'as':g['as'],'thrill':g['thrill'],'tags':tags,'flow':g.get('flow',[]),'headline':g['headline'],'recap':g['recap'],
                      'winner':g['winner'],'ot':g['ot'],'lc':g['lead_changes'],'comeback':g['comeback'],'maxh':g['max_lead_home'],'maxa':g['max_lead_away'],
                      'run':g.get('run'),'moment':m,'top':[{'name':p['name'],'team':p['team'],'pts':p['pts'],'reb':p['reb'],'ast':p['ast'],'fg':p['fg']} for p in pl],
                      'videos':g['videos'][:6]})
    standouts.sort(key=lambda x:-x['score'])
    try: evs=json.load(open('cache/nba_events.json'))
    except Exception: evs={}
    for c_ in cards: c_['cup']=(evs.get(c_['gid']) or ['','',''])[2] if len(evs.get(c_['gid']) or [])>2 else ''
    return {'date':date,'games':len(gs),'stories':top,'cards':cards,'standouts':standouts[:60],
            'pts':sum(g['hs']+g['as'] for g in gs)}
dates=sorted({g['date'] for g in G})[-4:]
nights=[n for n in (build_night(d) for d in dates) if n]
# global "right now"
last=dates[-1];sk=streaks(last)
hot=sorted([(t,s) for t,s in sk.items() if s['type']=='W' and s['n']>=4],key=lambda x:-x[1]['n'])
cold=sorted([(t,s) for t,s in sk.items() if s['type']=='L' and s['n']>=4],key=lambda x:-x[1]['n'])
heat=[]
for pid in [k for k in list(logs) if logs[k]]:
    dp=logs[pid][-1]['date']; tr=asof_trend(pid,dp) if dp>=dates[-3] else None
    if tr and tr['delta']>=4 and tr['last3_gs']>=15 and tr['min']>=18: heat.append(tr)
heat.sort(key=lambda x:-x['delta'])
for h_ in heat:
    pass
cool=[]
for pid in [k for k in list(logs) if logs[k]]:
    dp=logs[pid][-1]['date']; tr=asof_trend(pid,dp) if dp>=dates[-3] else None
    if tr and tr['delta']<=-6 and tr['season_gs']>=15 and tr['min']>=24: cool.append(tr)
cool.sort(key=lambda x:x['delta'])
out={'sport':'NBA','generated':datetime.utcnow().isoformat()+'Z','nights':nights,
     'hot':[{'team':t,'n':s['n'],'w':s['w'],'l':s['l']} for t,s in hot],'cold':[{'team':t,'n':s['n'],'w':s['w'],'l':s['l']} for t,s in cold],
     'heating':heat[:16],'cooling':cool[:5]}
json.dump(out,open('nba_digest.json','w'),separators=(',',':'))
print('size',len(json.dumps(out)))
for n in nights[-2:]:
    print('\n==',n['date'],n['games'],'games')
    for i,s in enumerate(n['stories'],1): print(i,f"[{s['label']}] {s['score']:.0f}",s['head'],'|',s['facts'])
print('\nHOT',[(h['team'],h['n']) for h in out['hot']],'COLD',[(h['team'],h['n']) for h in out['cold']])
print('HEATING',[(h['name'],h['delta'],h['last3_pts']) for h in out['heating']])
print('COOLING',[(h['name'],h['delta'],h['last3_pts'],h['season_pts']) for h in out['cooling']])

# ---- tonight's watchlist
snap=json.load(open('nba.json'))
tdate=(datetime.fromisoformat(last)+timedelta(days=1)).date().isoformat()
up=[g for g in snap['games'] if g['date']==tdate and g['state']=='pre']
S={t['abbr']:t for t in snap['standings']}
offr=sorted(S,key=lambda a:-S[a]['pf']);defr=sorted(S,key=lambda a:S[a]['pa'])
heatnames={h['team']:h for h in heat}
tonight=[]
for g in sorted(up,key=lambda g:g['time']):
    h,a=g['home'],g['away'];why=[];sc=0
    for t in (a,h):
        s_=sk.get(t)
        if s_ and s_['type']=='W' and s_['n']>=5: why.append(f"{tname(t)} have won {s_['n']} straight");sc+=s_['n']*2
        if s_ and s_['type']=='L' and s_['n']>=5: why.append(f"{tname(t)} are looking to end a {s_['n']}-game skid");sc+=s_['n']
        if t in heatnames: why.append(f"{heatnames[t]['name']} is heating up ({heatnames[t]['last3_pts']} ppg last 3)");sc+=6
    pa_,ph_=S[a]['w']/max(1,S[a]['w']+S[a]['l']),S[h]['w']/max(1,S[h]['w']+S[h]['l'])
    if pa_>=.65 and ph_>=.65: why.append("Two top teams");sc+=14
    for x,y in ((a,h),(h,a)):
        if offr.index(x)<5 and defr.index(y)<5: why.append(f"{tname(x)}'s offense meets {tname(y)}'s defense (both top 5)");sc+=8
    tonight.append({'away':a,'home':h,'time':g['time'],'why':why[:3],'score':sc,'arec':f"{S[a]['w']}-{S[a]['l']}",'hrec':f"{S[h]['w']}-{S[h]['l']}"})
out['tonight']={'date':tdate,'games':tonight}
out['teams']={a:{'name':t['name'],'short':t['short'],'color':t['color'],'w':t['w'],'l':t['l']} for a,t in S.items()}
out['updated']=datetime.utcnow().isoformat()+'Z'
json.dump(out,open('nba_digest.json','w'),separators=(',',':'))
print('tonight',tdate,[(g['away'],g['home'],g['score'],g['why']) for g in tonight][:5],'size',len(json.dumps(out)))

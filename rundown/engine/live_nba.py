"""Live NBA engine: poll ESPN, detect what matters, emit live.json.
Usage: python3 live_nba.py            -> one live poll, writes live.json, prints status line
       python3 live_nba.py replay DATE FRAC [FRAC...]   -> test against cached finished games
"""
import json,os,re,sys,time,urllib.request,glob,collections
from analyze_nba import shot_events
from datetime import datetime,timezone,timedelta
B="https://site.api.espn.com/apis/site/v2/sports/basketball/nba/"
HERE=os.environ.get('RUNDOWN_DATA') or os.getcwd()
def P(*a): return os.path.join(HERE,*a)
def get(u,tries=3):
    for i in range(tries):
        try: return json.load(urllib.request.urlopen(u,timeout=25))
        except Exception:
            if i==tries-1: raise
            time.sleep(1.5)
def clk(c):
    c=str(c).strip()
    if ':' in c:
        m,s=c.split(':'); return int(m)*60+float(s)
    try: return float(c)
    except: return 720.0
def ql(n): return {1:'Q1',2:'Q2',3:'Q3',4:'Q4'}.get(n,'OT' if n==5 else f'{n-4}OT')
def nowiso(): return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')

# ---- season context (highs) from cached box scores
def season_highs():
    f=P('season_highs.json')
    if os.path.exists(f) and time.time()-os.path.getmtime(f)<6*3600: return json.load(open(f))
    from analyze_nba import load_all
    hi={}
    for g in load_all():
        for p in g['players']:
            h=hi.setdefault(p['id'],{'pts':0,'tpm':0,'name':p['name']})
            h['pts']=max(h['pts'],p['pts']);h['tpm']=max(h['tpm'],p['tpm'])
    json.dump(hi,open(f,'w'));return hi

def load_state(name='state.json'):
    f=P(name)
    if os.path.exists(f):
        try: return json.load(open(f))
        except: pass
    return {'slate':None,'games':{},'feed':[]}

def analyze_live(s,status):
    """Derive live facts from a (possibly partial) summary."""
    hc=s['header']['competitions'][0];comp={c['homeAway']:c for c in hc['competitors']}
    H,A=comp['home']['team']['abbreviation'],comp['away']['team']['abbreviation']
    plays=s.get('plays') or []
    names={};teamof={};box={}
    for tm in s['boxscore'].get('players',[]):
        ab=tm['team']['abbreviation']
        for grp in tm['statistics']:
            lab=grp['labels']
            for a in grp['athletes']:
                pid=a['athlete']['id'];names[pid]=a['athlete']['displayName'];teamof[pid]=ab
                if a.get('stats') and status.get('boxscore_live',True):
                    d=dict(zip(lab,a['stats']));
                    def n(k):
                        v=d.get(k,'0');return int(v) if str(v).lstrip('-').isdigit() else 0
                    box[pid]={'reb':n('REB'),'ast':n('AST'),'stl':n('STL'),'blk':n('BLK')}
    tid={c['team']['id']:c['team']['abbreviation'] for c in hc['competitors']}
    if status.get('derive'):   # rehearsal only: rebuild partial rebounds/assists from the plays
        rb=collections.Counter();asv=collections.Counter()
        for p in plays:
            ps=p.get('participants') or []
            if 'Rebound' in p['type']['text'] and ps: rb[ps[0]['athlete']['id']]+=1
            if p.get('scoringPlay') and len(ps)>1: asv[ps[1]['athlete']['id']]+=1
        box={pid:{'reb':rb[pid],'ast':asv[pid],'stl':0,'blk':0} for pid in set(names)|set(rb)|set(asv)}
    pts=collections.Counter();tpm=collections.Counter();dunks=collections.Counter()
    scoring=[];prev=(0,0);lead_changes=0;last_sign=0;events=[];pp=[]
    def elapsed(per,c):
        base=720*min(per,4)+300*max(0,per-5) if per>4 else 720*(per-1)
        plen=720 if per<=4 else 300
        return (720*4+300*(per-5) if per>4 else base)+(plen-clk(c)) if per>4 else 720*(per-1)+(plen-clk(c))
    for p in plays:
        a,h=p.get('awayScore'),p.get('homeScore')
        if a is None or h is None: continue
        if p.get('scoringPlay') and p.get('participants'):
            pid=p['participants'][0]['athlete']['id'];v=p.get('scoreValue',0)
            pts[pid]+=v;pp.append((pid,v,elapsed(p['period']['number'],p['clock']['displayValue'])))
            if v==3: tpm[pid]+=1
            if 'Dunk' in p['type']['text']: dunks[pid]+=1
            if pid not in teamof and p.get('team',{}).get('id') in tid: teamof[pid]=tid[p['team']['id']]
        if (h,a)!=prev:
            dh,da=h-prev[0],a-prev[1]
            scoring.append({'seq':int(p['sequenceNumber']),'id':p['id'],'h':h,'a':a,'dh':dh,'da':da,'per':p['period']['number'],'clock':p['clock']['displayValue'],'text':p['text']})
            sign=(h>a)-(h<a)
            if sign!=0 and last_sign!=0 and sign!=last_sign: lead_changes+=1;scoring[-1]['lc']=True
            if sign!=0: last_sign=sign
            prev=(h,a)
    hs,as_=prev[0],prev[1]
    # current unanswered run
    run=None
    if scoring:
        tm=None;tot=0;start=None
        for sc in reversed(scoring):
            t='H' if sc['dh']>0 and sc['da']==0 else 'A' if sc['da']>0 and sc['dh']==0 else 'X'
            if tm is None: tm=t
            if t!=tm: break
            tot+=sc['dh'] or sc['da'];start=sc
        if tm in('H','A') and tot>=6: run={'team':H if tm=='H' else A,'pts':tot,'start_seq':start['seq'],'since':f"{ql(start['per'])} {start['clock']}"}
    per=status.get('period') or (plays[-1]['period']['number'] if plays else 1);cl=status.get('clock') or (plays[-1]['clock']['displayValue'] if plays else '12:00')
    wp=[w['homeWinPercentage'] for w in s.get('winprobability',[])]
    flow=None
    if wp:
        step=max(1,len(wp)//70);flow=[round(wp[i],3) for i in range(0,len(wp),step)]+[round(wp[-1],3)]
    vids=[]
    for v in s.get('videos') or []:
        href=(v.get('links') or {}).get('web',{}).get('href')
        if href and v.get('headline'): vids.append({'t':v['headline'],'u':href})
    players=[]
    for pid in set(pts)|set(box):
        players.append({'id':pid,'name':names.get(pid,'?'),'team':teamof.get(pid,'?'),'pts':pts[pid],'tpm':tpm[pid],'dunks':dunks[pid],**box.get(pid,{'reb':0,'ast':0,'stl':0,'blk':0})})
    players.sort(key=lambda x:-x['pts'])
    nowe=elapsed(per,cl) if plays else 0
    rec=collections.Counter()
    for pid,v,e_ in pp:
        if nowe-e_<=420: rec[pid]+=v
    recent=[{'name':names.get(pid,'?'),'team':teamof.get(pid,'?'),'recent':r,'pts':pts[pid],'mins':7} for pid,r in rec.most_common(3) if r>=9]
    inj=[]
    for t_ in s.get('injuries') or []:
        ab=t_['team']['abbreviation']
        for i_ in t_.get('injuries',[]):
            a_=i_.get('athlete',{});dt=i_.get('details') or {}
            inj.append({'id':a_.get('id'),'name':a_.get('displayName'),'team':ab,'status':i_.get('status'),'date':i_.get('date'),'detail':' '.join(x for x in (dt.get('type'),dt.get('detail')) if x)})
    ws,ts=(None,None)
    if status.get('state')=='post' and plays: ws,ts=shot_events(plays,hs>as_)
    lastwc=next((p.get('wallclock') for p in reversed(plays) if p.get('wallclock')),None)
    return {'lastwc':lastwc,'inj':inj,'winshot':ws,'tieshot':ts if (plays and max(p['period']['number'] for p in plays)>4) else None,'recent':recent,'home':H,'away':A,'hs':hs,'as':as_,'period':per,'clock':cl,'scoring':scoring,'lead_changes':lead_changes,'run':run,'flow':flow,
            'videos':vids,'players':players,'headline':(s.get('article') or {}).get('headline'),'box_live':bool(box)}


def networks(comp):
    """Where to watch, from an ESPN competition: [{'n': name, 'm': national|home|away, 't': TV|Streaming}]."""
    out=[]
    for b in comp.get('geoBroadcasts') or []:
        n=(b.get('media') or {}).get('shortName');m=((b.get('market') or {}).get('type') or '').lower();t=(b.get('type') or {}).get('shortName') or ''
        if n and not any(x['n']==n for x in out): out.append({'n':n,'m':m,'t':t})
    if not out:
        for b in comp.get('broadcasts') or []:
            for n in b.get('names') or []:
                if not any(x['n']==n for x in out): out.append({'n':n,'m':(b.get('market') or '').lower(),'t':''})
    order={'national':0,'home':1,'away':2}
    return sorted(out,key=lambda x:order.get(x['m'],3))

def hot_reasons(p,in_game=True):
    """Why a player is hot right now, across every stat. Returns (score, [badges], headline_stat) or None."""
    pts,reb,ast,stl,blk,tpm=p['pts'],p['reb'],p['ast'],p['stl'],p['blk'],p['tpm']
    r=[];sc=0;best=(0,None)
    def add(txt,s,key):
        nonlocal sc,best
        r.append(txt);sc+=s
        if s>best[0]: best=(s,key)
    if pts>=25: add(f"{pts} pts",40+(pts-25)*3,'pts')
    if reb>=12: add(f"{reb} reb",40+(reb-12)*4,'reb')
    if ast>=10: add(f"{ast} ast",40+(ast-10)*4,'ast')
    if stl>=4: add(f"{stl} stl",42+(stl-4)*9,'stl')
    if blk>=4: add(f"{blk} blk",42+(blk-4)*9,'blk')
    if tpm>=5: add(f"{tpm} threes",36+(tpm-5)*7,'tpm')
    cats=sorted([pts,reb,ast,stl,blk],reverse=True)
    if cats[0]>=10 and cats[1]>=10 and cats[2]>=10: add('triple-double',70,'td')
    elif cats[0]>=10 and cats[1]>=10 and cats[2]>=7: add('triple-double watch',44,'td')
    if pts>=20 and reb>=20: add('20-20',80,'tt')
    if not r: return None
    return {'score':round(sc,1),'badges':r,'key':best[1]}

def heat_score(g,state):
    """How much a fan should switch to this game right now."""
    if state=='pre': return 0
    m=abs(g['hs']-g['as']);per=g['period'];left=clk(g['clock'])
    if state=='post': return round(max(0,30-m*2)*0.2,1)          # finished games sink below live ones
    w={1:.3,2:.5,3:.8}.get(per,1.3)
    sc=max(0,30-m*2.2)*w                                            # closeness, weighted by how late it is
    if per>=5: sc+=55                                               # overtime
    elif per>=4 and m<=5 and left<=300: sc+=45                      # crunch time
    if g['run'] and g['run']['pts']>=10: sc+=g['run']['pts']*1.5    # a run in progress
    best=max([h['score'] for p in g['players'] for h in [hot_reasons(p)] if h] or [0])
    sc+=min(30,best/4)                                              # a star line
    sc+=min(g['lead_changes'],15)*0.6
    if m>=20 and per>=3: sc*=0.35                                   # blowouts drop
    return round(sc,1)

def why_watch(g,state):
    """The single best reason to switch to this game now."""
    if state!='in': return ''
    m=abs(g['hs']-g['as']);per=g['period'];left=clk(g['clock'])
    lead=g['home'] if g['hs']>g['as'] else g['away'] if g['as']>g['hs'] else None
    if per>=5: return 'Overtime'
    if per>=4 and m<=5 and left<=300: return 'Crunch time, '+('tied' if lead is None else f'{lead} up {m}')
    if g['run'] and g['run']['pts']>=10: return f"{g['run']['team']} on a {g['run']['pts']}-0 run"
    hots=[(h['score'],p,h) for p in g['players'] for h in [hot_reasons(p)] if h]
    if hots:
        _,p,h=max(hots,key=lambda x:x[0])
        if h['score']>=60: return f"{p['name']} has {', '.join(h['badges'][:2])}"
    if m<=4 and per>=3: return f'Tight in the {ql(per)}'
    if m>=20 and per>=3: return 'Blowout'
    return ''

def tags_for(g,state):
    t=[];m=abs(g['hs']-g['as']);per=g['period'];left=clk(g['clock'])
    if state=='in':
        if per>=5: t.append('Overtime')
        elif per>=4 and m<=5 and left<=300: t.append('Crunch time')
        elif m<=4 and per>=3: t.append('Tight')
        if m>=20 and per>=3: t.append('Blowout')
        if g['run'] and g['run']['pts']>=10: t.append(f"{g['run']['team']} on a {g['run']['pts']}-0 run")
        for p in g['players'][:1]:
            if p['pts']>=30: t.append(f"{p['name'].split()[-1]} has {p['pts']}")
        if g['lead_changes']>=10: t.append(f"{g['lead_changes']} lead changes")
    return t

def detect(gkey,g,state,st,meta,highs,now,mode):
    """Append feed events for this game; return list of new events."""
    fresh=gkey not in st['games'];gs=st['games'].setdefault(gkey,{'sent':[]});sent=set(gs['sent']);ev=[]
    quiet=fresh and not (state=='in' and g['period']==1 and clk(g['clock'])>=600)  # joining mid-game: don't replay history
    A,H=g['away'],g['home'];game=f"{A} @ {H}";per=g['period'];cl=g['clock'];left=clk(cl);m=abs(g['hs']-g['as'])
    lead=H if g['hs']>g['as'] else A if g['as']>g['hs'] else None
    score=f"{A} {g['as']}, {H} {g['hs']}"
    when=f"{ql(per)} {cl}" if state=='in' else 'Final'
    def add(key,kind,imp,text,url=None,grp=None):
        if key in sent: return
        sent.add(key);ev.append({'id':f"{gkey}:{key}",'ts':now,'gid':gkey,'game':game,'kind':kind,'imp':imp,'text':text,'when':when,'score':score,
                                 **({'u':url} if url else {}),**({'grp':f"{gkey}:{grp}"} if grp else {})})
    def tiered(prefix,val,thrs,imps,kind,text):
        crossed=[(t,i) for t,i in zip(thrs,imps) if val>=t]
        if not crossed: return
        for t,_ in crossed[:-1]: sent.add(f"{prefix}_{t}")
        t,i=crossed[-1];add(f"{prefix}_{t}",kind,i,text(t),grp=prefix)
    if state in('in','post'):
        # entering the fourth / OT
        if state=='in' and per==4 and left>=540:
            hot=[p for p in g['players'] if p['pts']>=30]
            tail=f" {hot[0]['name']} has {hot[0]['pts']}." if hot else ''
            if m<=5: add('q4','quarter',4,f"Into the fourth: {'tied' if lead is None else lead+' up '+str(m)} ({A} {g['as']}, {H} {g['hs']}).{tail}")
            else: add('q4','quarter',2,f"Into the fourth: {lead} up {m} ({A} {g['as']}, {H} {g['hs']}).{tail}")
        if state=='in' and per>=5 and left>=270: add(f'ot{per}','quarter',5,f"Overtime! {A} {g['as']}, {H} {g['hs']}.")
        # crunch time
        if state=='in' and per>=4 and m<=5 and left<=300: add(f'crunch{per}','crunch',4,f"Crunch time: {'tied' if lead is None else lead+' up '+str(m)} with {cl} left in {ql(per)}.")
        # lead changes in the clutch
        for sc in g['scoring']:
            if sc.get('lc') and sc['per']>=4 and clk(sc['clock'])<=300 and abs(sc['h']-sc['a'])<=6:
                newlead=H if sc['h']>sc['a'] else A
                add(f"lc{sc['seq']}",'clutch',4,f"{newlead} take the lead, {A} {sc['a']}, {H} {sc['h']}, with {sc['clock']} left in {ql(sc['per'])}.")
        # runs
        r=g['run']
        if r and state=='in':
            for thr,imp in ((10,2),(14,3),(18,4),(22,4)):
                if r['pts']>=thr: add(f"run{r['start_seq']}_{thr}",'run',imp,f"{r['team']} on a {r['pts']}-0 run since {r['since']}.")
        # blowout
        if state=='in' and per>=3 and m>=25: add('blow','blowout',2,f"Over early: {lead} up {m} in {ql(per)}.")
        # players
        for p in g['players']:
            nm=p['name']; hi=highs.get(p['id'],{'pts':0,'tpm':0})
            thr3=(', %d threes'%p['tpm']) if p['tpm']>=5 else ''
            tiered(f"p{p['id']}",p['pts'],(30,40,50,60),(3,4,5,5),'player',lambda t:f"{nm} ({p['team']}) {'has' if state=='in' else 'finished with'} {p['pts']} points{thr3}.")
            if p['pts']>=25 and p['pts']>hi['pts'] and hi['pts']>0:
                add(f"sh{p['id']}",'record',4,f"Season high for {nm} ({p['team']}): {p['pts']} points, past his {hi['pts']}.")
            if p['tpm']>=7 and p['tpm']>hi['tpm']: add(f"s3{p['id']}",'record',4,f"{nm} ({p['team']}) has {p['tpm']} threes, a new season high for him.")
            tiered(f"t{p['id']}",p['tpm'],(6,8,10),(3,3,5),'player',lambda t:f"{nm} ({p['team']}) is on fire from deep: {p['tpm']} threes.")
            if g['box_live'] and min(p['pts'],p['reb'],p['ast'])>=10: add(f"td{p['id']}",'player',4,f"Triple-double: {nm} ({p['team']}) has {p['pts']}/{p['reb']}/{p['ast']}.")
            if g['box_live']:
                tiered(f"rb{p['id']}",p['reb'],(12,15,20),(3,4,5),'player',lambda t:f"{nm} ({p['team']}) has {p['reb']} rebounds.")
                tiered(f"as{p['id']}",p['ast'],(10,12,15),(3,4,5),'player',lambda t:f"{nm} ({p['team']}) has {p['ast']} assists.")
                tiered(f"st{p['id']}",p['stl'],(4,5,6),(3,4,5),'player',lambda t:f"{nm} ({p['team']}) has {p['stl']} steals.")
                tiered(f"bk{p['id']}",p['blk'],(4,5,6),(3,4,5),'player',lambda t:f"{nm} ({p['team']}) has {p['blk']} blocks.")
            if g['box_live'] and p['pts']>=20 and p['reb']>=20: add(f"tt{p['id']}",'record',5,f"20-20 game: {nm} ({p['team']}) has {p['pts']} points and {p['reb']} rebounds.")
            if p['dunks']>=5: add(f"d{p['id']}",'player',2,f"{nm} has {p['dunks']} dunks.")
        # hot hand: points in the last ~7 minutes of game time
        if state=='in':
            for r in g['recent']:
                if r['recent']>=12: add(f"hh{r['name']}_{per}",'player',3,grp=f"hh{r['name']}",text=f"{r['name']} ({r['team']}) is heating up: {r['recent']} points in the last 7 minutes, {r['pts']} total.")
        # highlight clips
        hot_names={p['name'].split()[-1].lower() for p in g['players'] if p['pts']>=20 or hot_reasons(p)}
        for v in g['videos']:
            if re.search(r'game highlights',v['t'],re.I): continue
            t_=v['t'].lower()
            if re.search(r'buzzer|game-winner|go-ahead|poster|half-court|logo|clutch',t_): imp=3
            elif re.search(r'dunk|slam|jam|flush|alley|block|reject|swat|stuff|steal|and-1|and-one|hoop and the harm|elevates|skies|throws down|rocks the rim|takes flight',t_): imp=2
            else: imp=1                                              # routine "hits a shot" clips
            if any(n and n in t_ for n in hot_names): imp+=1         # it's the player everyone is watching
            if per>=4 and m<=5 and state=='in': imp+=1               # late in a close game
            add('v'+v['u'].split('/id/')[-1].split('/')[0],'clip',min(imp,3),v['t'],v['u'])
    # injuries reported after tip-off
    if state in('in','post') and meta.get('time'):
        for i_ in g['inj']:
            if i_['status'] in('Out','Doubtful') and i_['date'] and i_['date']>=meta['time'][:16] and highs.get(i_['id'],{}).get('pts',0)>=18:
                add(f"inj{i_['id']}",'injury',5,f"Injury update: {i_['name']} ({i_['team']}) is now listed {i_['status'].lower()}{' ('+i_['detail']+')' if i_['detail'] else ''}.")
    if state=='post':
        ws=g.get('winshot');ts=g.get('tieshot')
        if ws:
            buzz=ws['sec']<=1.5
            add('winshot','clutch',5,f"{'Buzzer-beater' if buzz else 'Game-winner'}: {ws['text'].split(' makes ')[0]} wins it for {H if g['hs']>g['as'] else A} with {ws['clock']} left. Final {A} {g['as']}, {H} {g['hs']}.")
        if ts: add('tieshot','clutch',4,f"{ts['text'].split(' makes ')[0]} ties it with {ts['clock']} left and sends it to overtime.")
        last=g['scoring'][-1] if g['scoring'] else None
        buzz=''
        for sc in reversed(g['scoring']):
            if sc.get('lc'):
                if sc['per']>=4 and clk(sc['clock'])<=10: buzz=f" Decided in the final {int(clk(sc['clock']))} seconds."
                break
        add('final','final',3 if m<=6 else 2,f"Final: {A} {g['as']}, {H} {g['hs']}. {g['headline'] or ''}{buzz}".strip())
    gs['sent']=sorted(sent)
    return [] if quiet else ev

def poll(replay=None):
    mode='replay' if replay else 'live'
    st=load_state('state_replay.json' if replay else 'state.json')
    highs=season_highs()
    games=[];newev=[];lags=[];now=replay['now'] if replay else nowiso()
    if replay:
        slate=replay['date'];srcs=replay['games']  # list of (gid, summary(trunc), status)
    else:
        sb=get(B+'scoreboard');from analyze_nba import et_date
        slate=et_date(min(e['date'] for e in sb['events'])) if sb['events'] else None
        srcs=[]
        for e in sb['events']:
            ty=e['status']['type'];stt=ty['state']
            srcs.append((e['id'],None,{'state':stt,'period':e['status'].get('period'),'clock':e['status'].get('displayClock'),'detail':ty.get('shortDetail'),'time':e['date'],
                         'teams':{c['homeAway']:c['team']['abbreviation'] for c in e['competitions'][0]['competitors']},
                         'scores':{c['homeAway']:int(c.get('score') or 0) for c in e['competitions'][0]['competitors']},
                         'tv':networks(e['competitions'][0])}))
    if st.get('slate')!=slate:
        st={'slate':slate,'games':{},'feed':[]}
    for gid,summ,status in srcs:
        state=status['state']
        if state=='pre':
            games.append({'gid':gid,'state':'pre','away':status['teams']['away'],'home':status['teams']['home'],'time':status.get('time'),'heat':0,'tags':[],'tv':status.get('tv') or []});continue
        if summ is None:
            gs=st['games'].get(gid,{})
            if state=='post' and gs.get('done'):
                games.append(gs['card']);continue
            try: summ=get(B+'summary?event='+gid)
            except Exception as ex:
                print('WARN summary fail',gid,ex,file=sys.stderr)
                if gs.get('card'): games.append(gs['card'])
                continue
        g=analyze_live(summ,status)
        if state=='post':
            g['period']=max(g['period'],4)
        ev=detect(gid,g,state,st,status,highs,now,mode);newev+=ev
        top=[{'name':p['name'],'team':p['team'],'pts':p['pts'],'reb':p['reb'],'ast':p['ast'],'tpm':p['tpm']} for p in g['players'][:3]]
        card={'gid':gid,'state':state,'away':g['away'],'home':g['home'],'as':g['as'],'hs':g['hs'],'period':g['period'],'clock':g['clock'],
              'detail':status.get('detail') or (f"{ql(g['period'])} {g['clock']}"),'margin':abs(g['hs']-g['as']),'heat':heat_score(g,state),'why':why_watch(g,state),'tv':status.get('tv') or [],
              'tags':tags_for(g,state),'flow':g['flow'],'lc':g['lead_changes'],'run':({'team':g['run']['team'],'pts':g['run']['pts']} if g['run'] and state=='in' else None),
              'top':top,'headline':g['headline'] if state=='post' else None,
              'hot':[{'name':p['name'],'team':p['team'],'pts':p['pts'],'reb':p['reb'],'ast':p['ast'],'stl':p['stl'],'blk':p['blk'],'tpm':p['tpm'],**h} for p in g['players'] for h in [hot_reasons(p)] if h]}
        if state=='in' and not replay and g.get('lastwc'):
            try:
                lag=(datetime.now(timezone.utc)-datetime.fromisoformat(g['lastwc'].replace('Z','+00:00'))).total_seconds()
                lags.append(lag)
                with open(P('latency.csv'),'a') as f_: f_.write(f"{now},{gid},{g['away']}@{g['home']},{lag:.0f}\n")
            except Exception: pass
        games.append(card)
        gst=st['games'].setdefault(gid,{'sent':[]});gst['card']=card
        st.setdefault('recent',{})[gid]=([{**r,'gid':gid,'game':f"{g['away']} @ {g['home']}"} for r in g['recent']] if state=='in' else [])
        if state=='post': gst['done']=True
    groups={e['grp'] for e in newev if e.get('grp')}
    st['feed']=(newev+[e for e in st['feed'] if e.get('grp') not in groups])[:150]
    json.dump(st,open(P('state_replay.json' if replay else 'state.json'),'w'))
    live=[g for g in games if g['state']=='in'];pre=[g for g in games if g['state']=='pre'];post=[g for g in games if g['state']=='post']
    allfinal=bool(games) and not live and not pre
    watch=[]
    for g in games:
        if g['state']!='pre':
            for p in g.get('hot',[]): watch.append({**p,'gid':g['gid'],'game':f"{g['away']} @ {g['home']}",'live':g['state']=='in'})
    watch.sort(key=lambda p:-p['score'])
    hotnow=[]
    for gid_,r_ in st.get('recent',{}).items():
        for x in r_: hotnow.append(x)
    hotnow.sort(key=lambda x:-x['recent'])
    doc={'mode':mode if (live or replay) else ('final' if allfinal else 'idle'),'updated':now,'slate':slate,'games':sorted(games,key=lambda g:(-(g['state']=='in'),-g['heat'],g.get('time') or '')),
         'feed':st['feed'][:80],'watch':watch[:40],'hotnow':hotnow[:6],'lag':(round(sorted(lags)[len(lags)//2]) if lags else None),'live':len(live),'pre':len(pre),'post':len(post),'allfinal':allfinal}
    return doc,newev

def replay_frames(date,fracs):
    cache={}
    for f in glob.glob(P('cache/nba/*.json')):
        s=json.load(open(f));
        from analyze_nba import et_date
        if et_date(s['header']['competitions'][0]['date'])==date: cache[s['header']['id']]=s
    t0=datetime(2026,11,17,0,0,tzinfo=timezone.utc)
    if os.path.exists(P('state_replay.json')): os.remove(P('state_replay.json'))
    out=None
    for i,fr in enumerate(fracs):
        srcs=[]
        for gid,s in cache.items():
            plays=s['plays'];k=max(1,int(len(plays)*fr)) if fr<1 else len(plays)
            t=json.loads(json.dumps(s));t['plays']=plays[:k];t['winprobability']=s['winprobability'][:k]
            if fr<1: t['videos']=[];t['article']=None
            last=plays[k-1];fin=(fr>=1)
            hc=s['header']['competitions'][0];comp={c['homeAway']:c for c in hc['competitors']}
            srcs.append((gid,t,{'state':'post' if fin else 'in','period':last['period']['number'],'clock':last['clock']['displayValue'],
                                'detail':'Final' if fin else f"{last['period']['displayValue']} {last['clock']['displayValue']}",'boxscore_live':fin,'derive':not fin,
                                'teams':{k_:v['team']['abbreviation'] for k_,v in comp.items()},'time':hc['date']}))
        doc,ev=poll({'now':(t0+timedelta(seconds=90*i)).isoformat().replace('+00:00','Z'),'date':date,'games':srcs})
        out=doc;print(f"frame {fr}: {len(ev)} new events, live={doc['live']} feed={len(doc['feed'])}")
    return out

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='replay':
        doc=replay_frames(sys.argv[2],[float(x) for x in sys.argv[3:]])
        json.dump(doc,open(P('live_replay.json'),'w'),separators=(',',':'))
        for e in doc['feed'][:25]: print(e['kind'],e['imp'],e['when'],'|',e['text'])
    else:
        doc,ev=poll()
        json.dump(doc,open(P('live.json'),'w'),separators=(',',':'))
        print(f"mode={doc['mode']} live={doc['live']} pre={doc['pre']} post={doc['post']} new={len(ev)} allfinal={doc['allfinal']}")

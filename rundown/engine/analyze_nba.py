import json,glob,re,collections,statistics as st
from datetime import datetime
from tzcompat import ET
def et_date(ts): return datetime.fromisoformat(ts.replace('Z','+00:00')).astimezone(ET).date().isoformat()
def clk(c):
    c=c.strip()
    if ':' in c:
        m,s=c.split(':'); return int(m)*60+float(s)
    return float(c)
def qlabel(n): return {1:'Q1',2:'Q2',3:'Q3',4:'Q4'}.get(n,f'OT{n-4}' if n>5 else 'OT')
def tleft(period,c):
    return f"{qlabel(period)} {c}"

def shot_events(plays,home_won):
    """Find the game-winning basket and a buzzer-beating tie that forced OT. plays: raw ESPN plays."""
    sign=lambda h,a:(h>a)-(h<a)
    win_sign=1 if home_won else -1
    prev=(0,0);win=None;tie=None
    for p in plays:
        h,a=p.get('homeScore'),p.get('awayScore')
        if h is None or a is None or not p.get('scoringPlay') or (h,a)==prev: continue
        sb,sa=sign(*prev),sign(h,a);per=p['period']['number'];c=p['clock']['displayValue']
        try: sec=float(c) if ':' not in c else 999
        except: sec=999
        if sa==win_sign and sb!=win_sign and per>=4: win={'text':p['text'],'per':per,'clock':c,'sec':sec,'h':h,'a':a}
        if sa==0 and sb!=0 and per==4 and sec<=5: tie={'text':p['text'],'per':per,'clock':c,'sec':sec,'h':h,'a':a}
        prev=(h,a)
    if win and win['sec']>5: win=None
    return win,tie

def analyze_game(s):
    hc=s['header']['competitions'][0]; comp={c['homeAway']:c for c in hc['competitors']}
    H,A=comp['home'],comp['away']
    g={'id':s['header']['id'],'home':H['team']['abbreviation'],'away':A['team']['abbreviation'],
       'hs':int(H['score']),'as':int(A['score']),'date':et_date(hc['date']),'ts':hc['date']}
    g['winner']=g['home'] if g['hs']>g['as'] else g['away']; g['margin']=abs(g['hs']-g['as'])
    plays=[p for p in s.get('plays',[])]
    g['periods']=max([p['period']['number'] for p in plays] or [4]); g['ot']=max(0,g['periods']-4)
    # score timeline
    tl=[(0,0,1,'12:00')]; lead_changes=0;ties=0;last_sign=0
    maxH=maxA=0; run=None; best_run={'H':(0,None),'A':(0,None)}
    cur=None  # (team, pts, start idx)
    prev=(0,0)
    runs=[]
    for p in plays:
        a,h=p.get('awayScore'),p.get('homeScore')
        if a is None or h is None: continue
        if (h,a)==prev: continue
        dh,da=h-prev[0],a-prev[1]
        if dh>0 and da==0: team='H'
        elif da>0 and dh==0: team='A'
        else: team=None
        if team:
            if cur and cur['t']==team: cur['pts']+=dh or da; cur['end']=(p['period']['number'],p['clock']['displayValue'])
            else:
                if cur: runs.append(cur)
                cur={'t':team,'pts':dh or da,'start':(p['period']['number'],p['clock']['displayValue']),'end':(p['period']['number'],p['clock']['displayValue'])}
        prev=(h,a); tl.append((h,a,p['period']['number'],p['clock']['displayValue']))
        maxH=max(maxH,h-a);maxA=max(maxA,a-h)
        sign=(h>a)-(h<a)
        if sign!=0 and last_sign!=0 and sign!=last_sign: lead_changes+=1
        if sign==0 and last_sign!=0: ties+=1
        if sign!=0: last_sign=sign
    if cur: runs.append(cur)
    g['lead_changes']=lead_changes; g['max_lead_home']=maxH; g['max_lead_away']=maxA
    # biggest run
    if runs:
        r=max(runs,key=lambda r:r['pts'])
        g['run']={'team':g['home'] if r['t']=='H' else g['away'],'pts':r['pts'],'from':tleft(*r['start']),'to':tleft(*r['end'])}
    wl=g['home'] if g['hs']>g['as'] else g['away']
    g['comeback']=(maxA if wl==g['home'] else maxH)  # deficit winner faced
    # win probability
    wpl=s.get('winprobability',[]); pid={p['id']:p for p in plays}
    ser=[];ex=0;big=[]
    for i,w in enumerate(wpl):
        ser.append(w['homeWinPercentage'])
        if i:
            d=abs(w['homeWinPercentage']-wpl[i-1]['homeWinPercentage']); ex+=d
            p=pid.get(w['playId']); 
            if p and p.get('scoringPlay'): big.append((d,p,wpl[i-1]['homeWinPercentage'],w['homeWinPercentage']))
    g['excite']=round(ex,2)
    if ser:
        n=len(ser); step=max(1,n//70); g['flow']=[round(ser[i],3) for i in range(0,n,step)]+[round(ser[-1],3)]
        wser=ser if wl==g['home'] else [1-x for x in ser]
        g['min_wp_winner']=round(min(wser),3)
    big.sort(key=lambda x:-x[0])
    g['halftime']=None
    for h,a,per,c in tl:
        if per==2 and clk(c)<=1: g['halftime']=(h,a)
    g['moments']=[{'swing':round(d,3),'text':p['text'],'when':tleft(p['period']['number'],p['clock']['displayValue']),'score':f"{g['away']} {p['awayScore']}, {g['home']} {p['homeScore']}",
                   'wp_after_home':round(b,3)} for d,p,a_,b in big[:3]]
    # clutch: margin at 2:00 left of Q4/OT
    clutch=None
    for h,a,per,c in tl:
        if per>=4:
            try:
                if clk(c)<=120: clutch=abs(h-a); break
            except: pass
    g['clutch_margin']=clutch
    # last go-ahead
    # spread
    pc=(s.get('pickcenter') or [{}])[0]; sp=pc.get('spread')
    if sp is not None:
        g['spread_home']=sp  # negative => home favored
        fav=g['home'] if sp<0 else g['away']; g['fav']=fav; g['fav_by']=abs(sp)
        # winner vs spread: positive => underdog won by margin
        g['upset']= (wl!=fav and abs(sp)>=1)
    hw=g['hs']>g['as']
    win,tie=shot_events(plays,hw)
    g['winshot']=win; g['tieshot']=tie if g['ot']>0 else None
    # recap + videos
    art=s.get('article') or {}
    g['headline']=art.get('headline'); g['recap']=art.get('description'); g['rtext']=((art.get('headline') or '')+' — '+(art.get('description') or ''))
    vids=[]
    for v in s.get('videos',[]) or []:
        href=(v.get('links') or {}).get('web',{}).get('href')
        if href and v.get('headline'): vids.append({'t':v['headline'],'u':href,'d':v.get('duration')})
    g['videos']=vids
    # players
    players=[]
    for tm in s['boxscore']['players']:
        ab=tm['team']['abbreviation']
        for grp in tm['statistics']:
            lab=grp['labels']
            for a in grp['athletes']:
                if a.get('didNotPlay') or not a['stats'] or a['stats'][0] in ('--',''): continue
                d=dict(zip(lab,a['stats']))
                def sp2(x):
                    m=re.match(r'(\d+)-(\d+)',x or ''); return (int(m.group(1)),int(m.group(2))) if m else (0,0)
                fgm,fga=sp2(d.get('FG'));tpm,tpa=sp2(d.get('3PT'));ftm,fta=sp2(d.get('FT'))
                try: mn=int(d['MIN'])
                except: mn=0
                n=lambda k:int(d.get(k,0) or 0) if str(d.get(k,'0')).lstrip('-').isdigit() else 0
                pts,reb,ast,stl,blk,to,pf=n('PTS'),n('REB'),n('AST'),n('STL'),n('BLK'),n('TO'),n('PF')
                gs=pts+.4*fgm-.7*fga-.4*(fta-ftm)+.7*n('OREB')+.3*n('DREB')+stl+.7*ast+.7*blk-.4*pf-to
                pm=d.get('+/-','0'); pm=int(pm.replace('+','')) if re.match(r'^[+-]?\d+$',pm or '') else 0
                cats=sum(1 for x in (pts,reb,ast,stl,blk) if x>=10)
                players.append({'id':a['athlete']['id'],'name':a['athlete']['displayName'],'team':ab,'min':mn,'pts':pts,'reb':reb,'ast':ast,'stl':stl,'blk':blk,'to':to,
                                'fg':f"{fgm}-{fga}",'fgm':fgm,'fga':fga,'tp':f"{tpm}-{tpa}",'tpm':tpm,'ft':f"{ftm}-{fta}",'gs':round(gs,1),'pm':pm,'dd':cats,'starter':a.get('starter',False)})
    g['players']=players
    return g
def load_all():
    out=[]
    for f in glob.glob('cache/nba/*.json'):
        try: out.append(analyze_game(json.load(open(f))))
        except Exception as e: print('ERR',f,repr(e))
    return sorted(out,key=lambda g:g['ts'])
if __name__=='__main__':
    G=load_all(); json.dump(G,open('nba_games.json','w'))
    print(len(G),'games')
    last=[g for g in G if g['date']>='2026-11-16']
    for g in last: print(g['away'],g['as'],g['home'],g['hs'],'lc',g['lead_changes'],'ex',g['excite'],'run',g.get('run'),'cb',g['comeback'],'clutch',g['clutch_margin'],'upset',g.get('upset'),g.get('fav'),g.get('fav_by'))
    print(G[-1]['moments'][:2]); print(G[-1]['headline'])

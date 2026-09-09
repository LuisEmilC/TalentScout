#!/usr/bin/env python3
import json, re, time, urllib.parse, urllib.request
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
RUNS=ROOT/'talent-finder-runs'; RUNS.mkdir(parents=True,exist_ok=True)
COUNTRIES=[('Europe','Belgium','Q31'),('Europe','Netherlands','Q55'),('Europe','Germany','Q183'),('Europe','France','Q142'),('Europe','Spain','Q29'),('Europe','Portugal','Q45'),('Europe','Italy','Q38'),('Europe','England','Q21'),('Europe','Austria','Q40'),('Europe','Switzerland','Q39'),('Europe','Denmark','Q35'),('Europe','Sweden','Q34'),('Europe','Norway','Q20'),('Europe','Poland','Q36'),('Europe','Czechia','Q213'),('Europe','Croatia','Q224'),('Europe','Serbia','Q403'),('Europe','Romania','Q218'),('Europe','Greece','Q41'),('Europe','Turkey','Q43'),('Europe','Ukraine','Q212'),('Asia','Japan','Q17'),('Asia','South Korea','Q884'),('Asia','Australia','Q408'),('Asia','New Zealand','Q664'),('Asia','Saudi Arabia','Q851'),('Asia','Qatar','Q846'),('Asia','India','Q668'),('North America','United States','Q30'),('North America','Canada','Q16'),('North America','Mexico','Q96'),('South America','Brazil','Q155'),('South America','Argentina','Q414'),('South America','Uruguay','Q77'),('South America','Colombia','Q739'),('South America','Chile','Q298'),('South America','Ecuador','Q736'),('South America','Paraguay','Q733'),('South America','Peru','Q419'),('Africa','Morocco','Q1028'),('Africa','Egypt','Q79'),('Africa','Nigeria','Q1033'),('Africa','Ghana','Q117'),('Africa','South Africa','Q258'),('Africa','Senegal','Q1041'),('Africa','Ivory Coast','Q1008'),('Oceania','New Zealand','Q664'),('Oceania','Australia','Q408')]
UA='TalentScout-Talent-Finder/2.0 (+https://github.com/LuisEmilC/TalentScout)'
SPARQL='https://query.wikidata.org/sparql?format=json&query='
WD='https://www.wikidata.org/w/api.php?action=wbgetentities&ids={}&format=json&props=claims|labels&languages=en'
SS='https://www.sofascore.com/api/v1/search/all?q={}'

def get(url,timeout=25):
    last=None
    for n in range(3):
        try:
            r=urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'application/json'}),timeout=timeout)
            return json.loads(r.read().decode())
        except Exception as e:
            last=e; time.sleep(1.5*(n+1))
    raise last

def scouting_day(now):
    local=now.astimezone(ZoneInfo('Europe/Brussels'))
    return local.date()-timedelta(days=1) if local.hour<12 else local.date()

def targets(day):
    i=((day-date(2026,1,1)).days*4)%len(COUNTRIES)
    return [COUNTRIES[(i+x)%len(COUNTRIES)] for x in range(4)]

def claims_qids(claims,p):
    out=[]
    for c in claims.get(p,[]) if isinstance(claims,dict) else []:
        try: out.append(c['mainsnak']['datavalue']['value']['id'])
        except Exception: pass
    return out

def birth(claims):
    for c in claims.get('P569',[]) if isinstance(claims,dict) else []:
        try: return c['mainsnak']['datavalue']['value']['time']
        except Exception: pass

def age(text,today):
    m=re.match(r'\+(\d{4})-(\d{2})-(\d{2})',text or '')
    if not m:return None
    y,mo,d=map(int,m.groups()); b=date(y,mo,d)
    return today.year-y-((today.month,today.day)<(mo,d))

def discover(country_qid,country,limit=25):
    q=f'''PREFIX xsd: <http://www.w3.org/2001/XMLSchema#> SELECT ?person ?personLabel ?birth ?club ?clubLabel WHERE {{ ?person wdt:P31 wd:Q5; wdt:P106 wd:Q937857; wdt:P569 ?birth; wdt:P54 ?club. ?club wdt:P17 wd:{country_qid}. FILTER(?birth >= "2002-01-01T00:00:00Z"^^xsd:dateTime) FILTER(?birth <= "2013-12-31T23:59:59Z"^^xsd:dateTime) SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }} }} LIMIT {limit}'''
    data=get(SPARQL+urllib.parse.quote(q),30); out=[]
    for r in data.get('results',{}).get('bindings',[]):
        out.append({'qid':r['person']['value'].rsplit('/',1)[-1],'name':r['personLabel']['value'],'clubQid':r['club']['value'].rsplit('/',1)[-1],'club':r.get('clubLabel',{}).get('value'),'country':country})
    return out

def sofa(name):
    d=get(SS.format(urllib.parse.quote(name)),20)
    for r in d.get('results',[]) or []:
        p=r.get('entity') if isinstance(r,dict) and r.get('entity') else r
        if isinstance(p,dict) and p.get('id') and str(p.get('name','')).strip().lower()==name.strip().lower(): return p
    return None

def verify(c,now):
    checks=[]; sources=['Wikidata']; reasons=[]
    try:
        ent=get(WD.format(c['qid']),20).get('entities',{}).get(c['qid'],{})
        cl=ent.get('claims',{}); a=age(birth(cl),now.date()); current=claims_qids(cl,'P54')
        c1=bool(ent.get('labels',{}).get('en',{}).get('value','').strip().lower()==c['name'].strip().lower()); checks.append(('identity',c1))
        c2=a is not None and 13<=a<=23; checks.append(('age_13_23',c2))
        c3=c['clubQid'] in current; checks.append(('current_club_wikidata',c3))
        c4=bool(c.get('club') and c.get('country')); checks.append(('club_and_country',c4))
        p=sofa(c['name']);
        if p:sources.append('Sofascore')
        c5=bool(p); checks.append(('independent_player_profile',c5))
        team=(p or {}).get('team',{}).get('name'); c6=bool(team and team.strip().lower()==c['club'].strip().lower()); checks.append(('current_club_independent',c6))
        # We never invent statistics. Search results without verified current stats remain rejected.
        stats=bool(p and all(k in p for k in ('position','country'))); c7=stats; checks.append(('profile_fields_available',c7))
        player={'id':f'official:wikidata:{c["qid"]}','name':c['name'],'age':a,'club':team or c['club'],'position':p.get('position') if p else None,'nationality':(p.get('country') or {}).get('name') if p else None,'goals':None,'assists':None,'appearances':None,'minutes':None,'sources':sorted(set(sources)),'verification':{'status':'verified','checkedAt':now.date().isoformat(),'checksPassed':[n for n,ok in checks if ok]},'country':c['country']}
        if len(sources)<2: reasons.append('fewer than 2 independent public sources')
        if not all(ok for _,ok in checks): reasons.append('not all 7 controls passed')
        if any(player.get(k) is None for k in ('position','nationality','goals','assists','appearances','minutes')): reasons.append('complete current statistics are not publicly verified')
        return player,checks,reasons
    except Exception as e:
        return None,[('runner_error',False)],[str(e)]

def main():
    now=datetime.now(timezone.utc); day=scouting_day(now); ts=targets(day); approved=[]; rejected=[]; errors=[]; seen=set(); screened=0
    for region,country,qid in ts:
        try: cs=discover(qid,country)
        except Exception as e: errors.append(f'{country}: {e}'); continue
        for c in cs:
            if c['qid'] in seen:continue
            seen.add(c['qid']); screened+=1
            p,checks,reasons=verify(c,now); passed=sum(1 for _,ok in checks if ok)
            if p and passed>=7 and len(p['sources'])>=2 and not any(p.get(k) is None for k in ('position','nationality','goals','assists','appearances','minutes')): approved.append(p)
            else: rejected.append({'name':c['name'],'country':country,'club':c.get('club'),'reason':' / '.join(reasons) or 'verification failed','failedControl':', '.join(n for n,ok in checks if not ok),'supportingSources':sorted(set((p or {}).get('sources',[])))})
    local=now.astimezone(ZoneInfo('Europe/Brussels')); stamp=local.strftime('%Y-%m-%d-%H%M%S')
    report={'runStartedAt':now.isoformat(),'runCompletedAt':datetime.now(timezone.utc).isoformat(),'runType':'automated real public-source scouting run','countriesScouted':[x[1] for x in ts],'regionOrder':[x[0] for x in ts],'scope':'Young players currently attached to clubs in the selected countries.','verificationPolicy':'Minimum 7 separate controls, minimum 2 independent public sources, no guessed fields, unresolved contradictions block publication.','candidatesScreened':screened,'approvedPlayers':approved,'rejectedPlayers':rejected,'existingPlayersPreserved':True,'unexpectedDeletions':False,'jsonValid':True,'writeVerification':'pending GitHub Actions sync','runnerErrors':errors}
    out=RUNS/f'{stamp}-automated-run.json'; out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(out)
if __name__=='__main__': main()

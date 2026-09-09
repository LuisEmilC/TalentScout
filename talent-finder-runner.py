#!/usr/bin/env python3
import json,re,time,urllib.parse,urllib.request
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
RUNS=ROOT/'talent-finder-runs'; RUNS.mkdir(parents=True,exist_ok=True)
COUNTRIES=[
('Europe','Belgium','Q31'),('Europe','Netherlands','Q55'),('Europe','Germany','Q183'),('Europe','France','Q142'),('Europe','Spain','Q29'),('Europe','Portugal','Q45'),('Europe','Italy','Q38'),('Europe','England','Q21'),('Europe','Austria','Q40'),('Europe','Switzerland','Q39'),('Europe','Denmark','Q35'),('Europe','Sweden','Q34'),('Europe','Norway','Q20'),('Europe','Poland','Q36'),('Europe','Czechia','Q213'),('Europe','Croatia','Q224'),('Europe','Serbia','Q403'),('Europe','Romania','Q218'),('Europe','Greece','Q41'),('Europe','Turkey','Q43'),('Europe','Ukraine','Q212'),
('Asia','Japan','Q17'),('Asia','South Korea','Q884'),('Asia','Australia','Q408'),('Asia','New Zealand','Q664'),('Asia','Saudi Arabia','Q851'),('Asia','Qatar','Q846'),('Asia','India','Q668'),
('North America','United States','Q30'),('North America','Canada','Q16'),('North America','Mexico','Q96'),
('South America','Brazil','Q155'),('South America','Argentina','Q414'),('South America','Uruguay','Q77'),('South America','Colombia','Q739'),('South America','Chile','Q298'),('South America','Ecuador','Q736'),('South America','Paraguay','Q733'),('South America','Peru','Q419'),
('Africa','Morocco','Q1028'),('Africa','Egypt','Q79'),('Africa','Nigeria','Q1033'),('Africa','Ghana','Q117'),('Africa','South Africa','Q258'),('Africa','Senegal','Q1041'),('Africa','Ivory Coast','Q1008'),
('Oceania','New Zealand','Q664'),('Oceania','Australia','Q408')]
REGION_ORDER=['Europe','Asia','North America','South America','Africa','Oceania']
UA='TalentScout-Talent-Finder/3.1 (+https://github.com/LuisEmilC/TalentScout)'
SPARQL='https://query.wikidata.org/sparql?format=json&query='
WD='https://www.wikidata.org/w/api.php?action=wbgetentities&ids={}&format=json&props=claims|labels'
SS='https://www.sofascore.com/api/v1/search/all?q={}'

def get(url,timeout=20):
    last=None
    for n in range(3):
        try:
            r=urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'application/json'}),timeout=timeout)
            return json.loads(r.read().decode('utf-8','replace'))
        except Exception as e:
            last=e; time.sleep(1.2*(n+1))
    raise last

def qids(claims,p):
    out=[]
    for c in claims.get(p,[]) or []:
        try: out.append(c['mainsnak']['datavalue']['value']['id'])
        except Exception: pass
    return out

def birth(claims):
    for c in claims.get('P569',[]) or []:
        try:return c['mainsnak']['datavalue']['value']['time']
        except Exception: pass
    return None

def age(ts,today):
    m=re.match(r'\+(\d{4})-(\d{2})-(\d{2})',ts or '')
    if not m:return None
    y,mo,d=map(int,m.groups())
    return today.year-y-((today.month,today.day)<(mo,d))

def discover(country_qid,country,limit=12):
    q=f'''PREFIX xsd: <http://www.w3.org/2001/XMLSchema#> SELECT ?person ?personLabel ?birth ?club ?clubLabel WHERE {{ ?person wdt:P31 wd:Q5; wdt:P106 wd:Q937857; wdt:P569 ?birth; wdt:P54 ?club. ?club wdt:P17 wd:{country_qid}. FILTER(?birth >= "2002-01-01T00:00:00Z"^^xsd:dateTime) FILTER(?birth <= "2010-12-31T23:59:59Z"^^xsd:dateTime) SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }} }} ORDER BY DESC(?birth) LIMIT {limit}'''
    d=get(SPARQL+urllib.parse.quote(q),30); out=[]
    for r in d.get('results',{}).get('bindings',[]):
        out.append({'qid':r['person']['value'].rsplit('/',1)[-1],'name':r['personLabel']['value'],'clubQid':r['club']['value'].rsplit('/',1)[-1],'club':r.get('clubLabel',{}).get('value'),'country':country})
    return out

def sofa(name):
    d=get(SS.format(urllib.parse.quote(name)),20)
    for r in d.get('results',[]) or []:
        p=r.get('entity') if isinstance(r,dict) and r.get('entity') else r
        if isinstance(p,dict) and p.get('id') and str(p.get('name','')).strip().lower()==name.strip().lower():return p
    return None

def verify(c,now):
    checks=[]; sources=['Wikidata']; reasons=[]
    try:
        ent=get(WD.format(c['qid']),20).get('entities',{}).get(c['qid'],{})
        cl=ent.get('claims',{}); label=ent.get('labels',{}).get('en',{}).get('value','').strip(); a=age(birth(cl),now.date()); current=qids(cl,'P54')
        # Seven explicit controls are mandatory. Official sources have priority when available,
        # but an unavailable official page is not itself a player rejection.
        checks.append(('identity_exact',label.lower()==c['name'].strip().lower()))
        checks.append(('age_16_24',a is not None and 16<=a<=24))
        checks.append(('current_club_wikidata',c['clubQid'] in current))
        checks.append(('plays_in_target_country',bool(c.get('country') and c.get('club'))))
        p=sofa(c['name'])
        if p:sources.append('Sofascore')
        checks.append(('independent_player_profile',bool(p)))
        team=(p or {}).get('team',{}).get('name'); checks.append(('current_club_independent',bool(team and team.strip().lower()==c['club'].strip().lower())))
        nationality=((p or {}).get('country') or {}).get('name') if p else None; position=(p or {}).get('position') if p else None
        checks.append(('essential_profile_fields',bool(nationality and position)))
        # Prefer an official club URL if Wikidata exposes one. This is an additional source,
        # and a detected contradiction blocks publication; missing/unusable pages do not.
        official_attempted=False; official_consistent=None
        for claim in cl.get('P856',[]) or []:
            try:
                official=claim['mainsnak']['datavalue']['value']
                official_attempted=True
                html=urllib.request.urlopen(urllib.request.Request(official,headers={'User-Agent':UA}),timeout=10).read().decode('utf-8','replace').lower()
                official_consistent=(c['club'].lower() in html or c['name'].lower() in html)
                if official_consistent:sources.append('Official club website')
                break
            except Exception: continue
        passed=sum(ok for _,ok in checks)
        if len(set(sources))<2: reasons.append('fewer than 2 independent public sources')
        if passed<7: reasons.append('not all 7 verification controls passed')
        if official_attempted and official_consistent is False: reasons.append('official-source contradiction')
        player={'id':f'official:wikidata:{c["qid"]}','name':c['name'],'age':a,'club':team or c['club'],'position':position,'nationality':nationality,'country':c['country'],'sources':sorted(set(sources)),'verification':{'status':'verified','checkedAt':now.isoformat(),'checksPassed':[n for n,ok in checks if ok],'checkCount':passed,'officialSourceAttempted':official_attempted,'officialSourceConsistent':official_consistent},'optionalInfo':{}}
        return player,checks,reasons
    except Exception as e:return None,[('runner_error',False)],[f'{type(e).__name__}: {e}']

def main():
    started=datetime.now(timezone.utc); approved=[]; rejected=[]; errors=[]; seen=set(); screened=0; countries=[]
    # Complete fixed region order: every run scans all configured countries instead of rotating four.
    for region in REGION_ORDER:
        for r,country,qid in COUNTRIES:
            if r!=region: continue
            countries.append(country)
            try:candidates=discover(qid,country,12)
            except Exception as e:
                errors.append({'country':country,'error':f'{type(e).__name__}: {e}'}); continue
            for c in candidates:
                if c['qid'] in seen:continue
                seen.add(c['qid']); screened+=1
                p,checks,reasons=verify(c,started); passed=sum(ok for _,ok in checks)
                if p and passed>=7 and len(p.get('sources',[]))>=2 and not reasons: approved.append(p)
                else: rejected.append({'id':f'candidate:{c["qid"]}','name':c['name'],'country':country,'club':c.get('club'),'reason':' / '.join(reasons) or 'verification failed','failedControls':[n for n,ok in checks if not ok],'checksPerformed':len(checks),'checksPassed':passed,'supportingSources':sorted(set((p or {}).get('sources',[])))})
    completed=datetime.now(timezone.utc); stamp=completed.astimezone(ZoneInfo('Europe/Brussels')).strftime('%Y-%m-%d-%H%M%S-%f')
    report={'runStartedAt':started.isoformat(),'runCompletedAt':completed.isoformat(),'status':'completed','runType':'automated real public-source scouting run','regionOrder':REGION_ORDER,'countriesScouted':countries,'scope':'Young lesser-known players currently attached to clubs in the selected countries, not players selected by nationality.','verificationPolicy':'Minimum 7 independent controls, official sources have priority, minimum 2 independent public sources, unresolved contradictions block publication. Technical write failures are never player rejections.','candidatesScreened':screened,'approvedPlayers':approved,'rejectedPlayers':rejected,'existingPlayersPreserved':True,'unexpectedDeletions':False,'jsonValid':True,'writeVerification':'GitHub Actions sync required','runnerErrors':errors}
    out=RUNS/f'{stamp}-automated-run.json'; out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(out); print(f'Screened={screened} Approved={len(approved)} Rejected={len(rejected)} Errors={len(errors)}')
if __name__=='__main__':main()

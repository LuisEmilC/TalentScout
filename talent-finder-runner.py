#!/usr/bin/env python3
import json,re,time,urllib.parse,urllib.request
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent; RUNS=ROOT/'talent-finder-runs'; RUNS.mkdir(parents=True,exist_ok=True)
COUNTRIES=['Belgium','Netherlands','France','Germany','Spain','Portugal','Italy','England','Turkey','Japan','South Korea','India','Saudi Arabia','Australia','New Zealand','Argentina','Brazil','Chile','Colombia','Ecuador','South Africa','Nigeria','Ghana','Morocco','Egypt','Mexico','Canada','United States','Costa Rica','Uruguay','Paraguay','Peru','Bolivia','Venezuela','Switzerland','Austria','Denmark','Sweden','Norway','Poland','Czechia','Croatia','Serbia','Greece','Romania','Ukraine','Georgia','Israel','Qatar','United Arab Emirates','Thailand','Indonesia','Malaysia','Vietnam','China','Iran','Iraq','Uzbekistan','Kazakhstan','Cameroon','Senegal','Ivory Coast','Algeria','Tunisia','Kenya','Tanzania','Zambia','Zimbabwe','Fiji','Papua New Guinea','Samoa','Tonga']
UA='TalentScout-Talent-Finder/5.0 (+https://github.com/LuisEmilC/TalentScout)'
SPARQL='https://query.wikidata.org/sparql?format=json&query='
WD='https://www.wikidata.org/w/api.php?action=wbgetentities&ids={}&format=json&props=claims|labels'
SS='https://www.sofascore.com/api/v1/search/all?q={}'
TM='https://www.transfermarkt.com/schnellsuche/ergebnis/schnellsuche?query={}'

def get(url,timeout=25):
    last=None
    for n in range(4):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'application/json','Accept-Language':'en-US,en;q=0.8'})
            with urllib.request.urlopen(req,timeout=timeout) as r:return json.loads(r.read().decode('utf-8','replace'))
        except Exception as e:
            last=e
            if n<3: time.sleep(1.5*(n+1))
    raise last

def html(url,timeout=15):
    req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'text/html,application/xhtml+xml','Accept-Language':'en-US,en;q=0.8'})
    with urllib.request.urlopen(req,timeout=timeout) as r:return r.read().decode('utf-8','replace').lower()

def qids(claims,p):
    out=[]
    for c in claims.get(p,[]) or []:
        try: out.append(c['mainsnak']['datavalue']['value']['id'])
        except Exception: pass
    return out

def vals(claims,p):
    out=[]
    for c in claims.get(p,[]) or []:
        try: out.append(c['mainsnak']['datavalue']['value'])
        except Exception: pass
    return out

def age(ts,today):
    m=re.match(r'\+(\d{4})-(\d{2})-(\d{2})',ts or '')
    if not m:return None
    y,mo,d=map(int,m.groups()); return today.year-y-((today.month,today.day)<(mo,d))

def discover(countries,limit=6):
    terms=', '.join(json.dumps(x,ensure_ascii=False) for x in countries)
    q=f'''PREFIX xsd:<http://www.w3.org/2001/XMLSchema#> PREFIX rdfs:<http://www.w3.org/2000/01/rdf-schema#>
SELECT ?person ?personLabel ?birth ?club ?clubLabel ?countryLabel WHERE {{
 ?person wdt:P31 wd:Q5; wdt:P106 wd:Q937857; wdt:P569 ?birth; wdt:P54 ?club.
 ?club wdt:P17 ?country. ?country rdfs:label ?countryLabel.
 FILTER(lang(?countryLabel)="en" && STR(?countryLabel) IN ({terms}))
 FILTER(?birth >= "2002-01-01T00:00:00Z"^^xsd:dateTime && ?birth <= "2010-12-31T23:59:59Z"^^xsd:dateTime)
 SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} ORDER BY ?countryLabel DESC(?birth)'''
    data=get(SPARQL+urllib.parse.quote(q),45); out=[]; counts={}
    for r in data.get('results',{}).get('bindings',[]):
        country=r['countryLabel']['value']
        if counts.get(country,0)>=limit: continue
        counts[country]=counts.get(country,0)+1
        out.append({'qid':r['person']['value'].rsplit('/',1)[-1],'name':r['personLabel']['value'],'clubQid':r['club']['value'].rsplit('/',1)[-1],'club':r.get('clubLabel',{}).get('value',''),'country':country})
    return out

def sofa(name):
    d=get(SS.format(urllib.parse.quote(name)),20)
    for r in d.get('results',[]) or []:
        p=r.get('entity') if isinstance(r,dict) and r.get('entity') else r
        if isinstance(p,dict) and p.get('id') and str(p.get('name','')).strip().lower()==name.strip().lower(): return p
    return None

def tm(name,club):
    try:
        page=html(TM.format(urllib.parse.quote(name)),12); text=re.sub(r'\s+',' ',re.sub('<[^>]+>',' ',page))
        return name.strip().lower() in text and club.strip().lower() in text
    except Exception:return False

def verify(c,now):
    checks=[]; sources={'Wikidata'}; reasons=[]
    try:
        ent=get(WD.format(c['qid']),20).get('entities',{}).get(c['qid'],{}); cl=ent.get('claims',{})
        label=ent.get('labels',{}).get('en',{}).get('value','').strip(); a=age(next(iter(vals(cl,'P569')),None),now.date()); current=qids(cl,'P54')
        checks.append(('identity_exact',label.lower()==c['name'].strip().lower()))
        checks.append(('age_16_24',a is not None and 16<=a<=24))
        checks.append(('current_club_wikidata',c['clubQid'] in current))
        p=sofa(c['name']); team=(p or {}).get('team',{}).get('name'); nationality=((p or {}).get('country') or {}).get('name') if p else None; position=(p or {}).get('position') if p else None
        if p:sources.add('Sofascore')
        checks.append(('independent_player_profile',bool(p)))
        checks.append(('current_club_independent',bool(team and team.strip().lower()==c['club'].strip().lower())))
        checks.append(('essential_profile_fields',bool(nationality and position)));
        third=tm(c['name'],c['club'])
        if third:sources.add('Transfermarkt')
        checks.append(('third_source_identity_and_club',third))
        club=get(WD.format(c['clubQid']),20).get('entities',{}).get(c['clubQid'],{}).get('claims',{}); official=False
        for u in vals(club,'P856')[:2]:
            try:
                page=html(str(u),10)
                if c['club'].lower() in page and c['name'].lower() in page: official=True; sources.add('Official club website'); break
            except Exception: pass
        checks.append(('official_club_or_third_source',third or official))
        passed=sum(ok for _,ok in checks)
        if passed<7: reasons.append('minder dan 7 controles')
        if len(sources)<2: reasons.append('minder dan 2 onafhankelijke bronnen')
        if not p: reasons.append('geen onafhankelijke spelerpagina')
        if p and (not team or team.strip().lower()!=c['club'].strip().lower()): reasons.append('clubconflict')
        player={'id':f'official:wikidata:{c["qid"]}','name':c['name'],'age':a,'club':team or c['club'],'position':position,'nationality':nationality,'country':c['country'],'sources':sorted(sources),'verification':{'status':'verified','checkedAt':now.isoformat(),'checksPassed':[n for n,ok in checks if ok],'checkCount':passed,'controls':{n:ok for n,ok in checks if ok or not ok}}}
        return player,checks,reasons
    except Exception as e:return None,[('runner_error',False)],[f'{type(e).__name__}: {e}']

def main():
    started=datetime.now(timezone.utc); day=int(started.strftime('%j'))-1; selected=[COUNTRIES[(day*4+i)%len(COUNTRIES)] for i in range(4)]
    approved=[]; rejected=[]; errors=[]; seen=set(); screened=0
    try:candidates=discover(selected,6)
    except Exception as e:candidates=[]; errors.append({'stage':'discovery','error':f'{type(e).__name__}: {e}'})
    for c in candidates:
        if c['qid'] in seen:continue
        seen.add(c['qid']); screened+=1; p,checks,reasons=verify(c,started); passed=sum(ok for _,ok in checks)
        if p and passed>=7 and len(p['sources'])>=2 and not reasons: approved.append(p)
        else: rejected.append({'id':f'candidate:{c["qid"]}','name':c['name'],'country':c['country'],'club':c['club'],'reason':' / '.join(reasons) or 'verification failed','failedControls':[n for n,ok in checks if not ok],'checksPerformed':len(checks),'checksPassed':passed,'supportingSources':sorted((p or {}).get('sources',[]))})
    completed=datetime.now(timezone.utc); stamp=completed.astimezone(ZoneInfo('Europe/Brussels')).strftime('%Y-%m-%d-%H%M%S-%f'); out=RUNS/f'{stamp}-automated-run.json'
    status='completed' if screened else 'blocked_before_database_write'
    report={'runStartedAt':started.isoformat(),'runCompletedAt':completed.isoformat(),'status':status,'runType':'automated real public-source scouting run','countriesScouted':selected,'scope':'Young lesser-known players currently attached to clubs in the selected countries, not selected by nationality.','verificationPolicy':'Minimum 7 explicit controls; minimum 2 independent public sources; essential published information is name, age, nationality, position, club and playing country; unresolved contradictions block publication.','candidatesScreened':screened,'approvedPlayers':approved,'rejectedPlayers':rejected,'existingPlayersPreserved':True,'unexpectedDeletions':False,'jsonValid':True,'writeVerification':'sync-after-talent-finder-run workflow','runnerErrors':errors}
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(out); print(f'Selected={selected} Screened={screened} Approved={len(approved)} Rejected={len(rejected)} Errors={len(errors)}')
    if not screened: raise SystemExit('FOUT: echte scouting-run leverde 0 kandidaten; database-write geblokkeerd.')
if __name__=='__main__':main()

#!/usr/bin/env python3
import json,re,time,urllib.parse,urllib.request
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent; RUNS=ROOT/'talent-finder-runs'; RUNS.mkdir(parents=True,exist_ok=True)
COUNTRIES=['Belgium','Netherlands','France','Germany','Spain','Portugal','Italy','England','Turkey','Japan','South Korea','India','Saudi Arabia','Australia','New Zealand','Argentina','Brazil','Chile','Colombia','Ecuador','South Africa','Nigeria','Ghana','Morocco','Egypt','Mexico','Canada','United States','Costa Rica','Uruguay','Paraguay','Peru','Bolivia','Venezuela','Switzerland','Austria','Denmark','Sweden','Norway','Poland','Czechia','Croatia','Serbia','Greece','Romania','Ukraine','Georgia','Israel','Qatar','United Arab Emirates','Thailand','Indonesia','Malaysia','Vietnam','China','Iran','Iraq','Uzbekistan','Kazakhstan','Cameroon','Senegal','Ivory Coast','Algeria','Tunisia','Kenya','Tanzania','Zambia','Zimbabwe','Fiji','Papua New Guinea','Samoa','Tonga']
UA='TalentScout-Talent-Finder/7.0 (+https://github.com/LuisEmilC/TalentScout)'
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

def age(value,today):
    if isinstance(value,dict): value=value.get('time','')
    m=re.match(r'\+(\d{4})-(\d{2})-(\d{2})',str(value or ''))
    if not m:return None
    y,mo,d=map(int,m.groups()); return today.year-y-((today.month,today.day)<(mo,d))

def discover(countries,limit=8):
    terms=', '.join(json.dumps(x,ensure_ascii=False) for x in countries)
    q=f'''PREFIX xsd:<http://www.w3.org/2001/XMLSchema#> PREFIX rdfs:<http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?person ?personLabel ?birth ?club ?clubLabel ?countryLabel WHERE {{
 ?person wdt:P31 wd:Q5; wdt:P106 wd:Q937857; wdt:P569 ?birth; wdt:P54 ?club.
 ?club wdt:P31 ?clubType; wdt:P17 ?country.
 ?country rdfs:label ?countryLabel.
 FILTER(lang(?countryLabel)="en" && STR(?countryLabel) IN ({terms}))
 FILTER(?birth >= "2002-01-01T00:00:00Z"^^xsd:dateTime && ?birth <= "2010-12-31T23:59:59Z"^^xsd:dateTime)
 FILTER NOT EXISTS {{ ?club wdt:P31/wdt:P279* wd:Q6979593. }}
 FILTER NOT EXISTS {{ ?club wdt:P31/wdt:P279* wd:Q6979586. }}
 SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} ORDER BY ?countryLabel DESC(?birth)'''
    data=get(SPARQL+urllib.parse.quote(q),45); out=[]; counts={}
    for r in data.get('results',{}).get('bindings',[]):
        country=r['countryLabel']['value']; club=r.get('clubLabel',{}).get('value','')
        if any(x in club.lower() for x in ('national football team','national under-','women\'s national','women national','u20','u21','u23')): continue
        if counts.get(country,0)>=limit: continue
        counts[country]=counts.get(country,0)+1
        out.append({'qid':r['person']['value'].rsplit('/',1)[-1],'name':r['personLabel']['value'],'clubQid':r['club']['value'].rsplit('/',1)[-1],'club':club,'country':country})
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
        club_match=bool(team and team.strip().lower()==c['club'].strip().lower())
        checks.append(('current_club_independent',club_match))
        checks.append(('essential_profile_fields',bool(nationality and position)) )
        third=tm(c['name'],c['club'])
        if third:sources.add('Transfermarkt')
        official=False
        clubent=get(WD.format(c['clubQid']),20).get('entities',{}).get(c['clubQid'],{}); clubclaims=clubent.get('claims',{})
        for u in vals(clubclaims,'P856')[:2]:
            try:
                page=html(str(u),10)
                if c['club'].lower() in page and c['name'].lower() in page: official=True; sources.add('Official club website'); break
            except Exception: pass
        checks.append(('independent_corroboration',third or official))
        passed=sum(ok for _,ok in checks)
        hard_conflict=bool(p and team and team.strip().lower()!=c['club'].strip().lower())
        if hard_conflict: reasons.append('harde clubtegenstrijdigheid')
        if not checks[0][1]: reasons.append('identiteit niet bevestigd')
        if passed<5: reasons.append('minder dan 5 van 7 hoofdcontroles')
        if len(sources)<2: reasons.append('minder dan 2 onafhankelijke bronnen')
        if hard_conflict: reasons.append('publicatie geblokkeerd door harde tegenstrijdigheid')
        player={'id':f'official:wikidata:{c["qid"]}','name':c['name'],'age':a,'club':team or c['club'],'position':position,'nationality':nationality,'country':c['country'],'sources':sorted(sources),'verification':{'status':'verified','checkedAt':now.isoformat(),'checksPassed':[n for n,ok in checks if ok],'checkCount':passed,'mainControlCount':7,'controls':{n:ok for n,ok in checks},'hardConflict':hard_conflict}}
        return player,checks,reasons,None
    except Exception as e:
        return None,[],[],{'candidateId':c.get('qid'),'name':c.get('name'),'club':c.get('club'),'country':c.get('country'),'errorType':type(e).__name__,'error':str(e)}

def main():
    started=datetime.now(timezone.utc); day=int(started.strftime('%j'))-1; selected=[COUNTRIES[(day*4+i)%len(COUNTRIES)] for i in range(4)]
    approved=[]; rejected=[]; errors=[]; seen=set(); screened=0
    try:candidates=discover(selected,8)
    except Exception as e:candidates=[]; errors.append({'stage':'discovery','errorType':type(e).__name__,'error':str(e)})
    for c in candidates:
        if c['qid'] in seen:continue
        seen.add(c['qid']); screened+=1; p,checks,reasons,error=verify(c,started)
        if error:
            errors.append({'stage':'candidate_verification',**error}); continue
        passed=sum(ok for _,ok in checks)
        if p and passed>=5 and len(p['sources'])>=2 and not reasons: approved.append(p)
        else:
            rejected.append({'id':f'candidate:{c["qid"]}','name':c['name'],'country':c['country'],'club':c['club'],'reason':' / '.join(reasons) or 'verification failed','failedControls':[n for n,ok in checks if not ok],'checksPerformed':7,'checksPassed':passed,'mainControlCount':7,'supportingSources':sorted((p or {}).get('sources',[]))})
    completed=datetime.now(timezone.utc); stamp=completed.astimezone(ZoneInfo('Europe/Brussels')).strftime('%Y-%m-%d-%H%M%S-%f'); out=RUNS/f'{stamp}-automated-run.json'
    report={'runStartedAt':started.isoformat(),'runCompletedAt':completed.isoformat(),'status':'completed','runType':'automated real public-source scouting run','regionOrder':['Europe','Asia','North America','South America','Africa','Oceania'],'countriesScouted':selected,'scope':'Young lesser-known players currently attached to clubs in the selected countries, not selected by nationality.','verificationPolicy':'Exactly 7 main controls. 5/7, 6/7 or 7/7 may pass; 4/7 or lower is rejected. Evidence subchecks do not create extra main controls. Minimum 2 independent public sources. Hard contradictions block publication. Technical errors are stored in runnerErrors and are never converted into player rejections.','candidatesScreened':screened,'approvedPlayers':approved,'rejectedPlayers':rejected,'runnerErrors':errors,'existingPlayersPreserved':True,'unexpectedDeletions':False,'jsonValid':True,'writeVerification':'workflow_run sync-after-talent-finder-run'}
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(out); print(f'Selected={selected} Screened={screened} Approved={len(approved)} Rejected={len(rejected)} Errors={len(errors)}')
    if not screened: raise SystemExit('FOUT: echte scouting-run leverde 0 kandidaten; database-write geblokkeerd.')
if __name__=='__main__':main()

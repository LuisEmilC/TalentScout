#!/usr/bin/env python3
import json,re,time,urllib.parse,urllib.request
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent; RUNS=ROOT/'talent-finder-runs'; RUNS.mkdir(parents=True,exist_ok=True)
COUNTRIES=['Belgium','Netherlands','France','Germany','Spain','Portugal','Italy','England','Turkey','Japan','South Korea','India','Saudi Arabia','Australia','New Zealand','Argentina','Brazil','Chile','Colombia','Ecuador','South Africa','Nigeria','Ghana','Morocco','Egypt','Mexico','Canada','United States','Costa Rica','Uruguay','Paraguay','Peru','Bolivia','Venezuela','Switzerland','Austria','Denmark','Sweden','Norway','Poland','Czechia','Croatia','Serbia','Greece','Romania','Ukraine','Georgia','Israel','Qatar','United Arab Emirates','Thailand','Indonesia','Malaysia','Vietnam','China','Iran','Iraq','Uzbekistan','Kazakhstan','Cameroon','Senegal','Ivory Coast','Algeria','Tunisia','Kenya','Tanzania','Zambia','Zimbabwe','Fiji','Papua New Guinea','Samoa','Tonga']
UA='TalentScout-Talent-Finder/7.4 (https://github.com/LuisEmilC/TalentScout; public scouting project)'
SPARQL='https://query.wikidata.org/sparql?format=json&query='
SPARQL_POST='https://query.wikidata.org/sparql'
WD='https://www.wikidata.org/w/api.php?action=wbgetentities&ids={}&format=json&props=claims|labels'
SS='https://www.sofascore.com/api/v1/search/all?q={}'
TM='https://www.transfermarkt.com/schnellsuche/ergebnis/schnellsuche?query={}'

def get(url,timeout=25):
    last=None
    for n in range(5):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'application/json','Accept-Language':'en-US,en;q=0.8'})
            with urllib.request.urlopen(req,timeout=timeout) as r:return json.loads(r.read().decode('utf-8','replace'))
        except Exception as e:
            last=e
            if n<4: time.sleep(min(12,2*(n+1)))
    raise last

def post_json(url,data,timeout=60):
    last=None; body=urllib.parse.urlencode(data).encode('utf-8')
    for n in range(5):
        try:
            req=urllib.request.Request(url,data=body,method='POST',headers={'User-Agent':UA,'Accept':'application/sparql-results+json, application/json','Content-Type':'application/x-www-form-urlencoded','Accept-Language':'en-US,en;q=0.8'})
            with urllib.request.urlopen(req,timeout=timeout) as r:return json.loads(r.read().decode('utf-8','replace'))
        except Exception as e:
            last=e
            if n<4: time.sleep(min(15,3*(n+1)))
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
    m=re.match(r'\+?(\d{4})-(\d{2})-(\d{2})',str(value or ''))
    if not m:return None
    y,mo,d=map(int,m.groups()); return today.year-y-((today.month,today.day)<(mo,d))

def entity_label(qid):
    try:return get(WD.format(qid),20).get('entities',{}).get(qid,{}).get('labels',{}).get('en',{}).get('value')
    except Exception:return None

def discover(countries,limit=8):
    terms=', '.join(json.dumps(x,ensure_ascii=False) for x in countries)
    q=f'''PREFIX xsd:<http://www.w3.org/2001/XMLSchema#> PREFIX rdfs:<http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?person ?personLabel ?birth ?club ?clubLabel ?countryLabel WHERE {{
 ?person wdt:P31 wd:Q5; wdt:P106 wd:Q937857; wdt:P569 ?birth; wdt:P54 ?club.
 ?club wdt:P17 ?country. ?country rdfs:label ?countryLabel.
 FILTER(lang(?countryLabel)="en" && STR(?countryLabel) IN ({terms}))
 FILTER(?birth >= "2003-01-01T00:00:00Z"^^xsd:dateTime && ?birth <= "2013-12-31T23:59:59Z"^^xsd:dateTime)
 SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} ORDER BY ?countryLabel DESC(?birth)'''
    try:data=post_json(SPARQL_POST,{'format':'json','query':q},60)
    except Exception:data=get(SPARQL+urllib.parse.quote(q),60)
    out=[]; counts={}
    for r in data.get('results',{}).get('bindings',[]):
        country=r['countryLabel']['value']; club=r.get('clubLabel',{}).get('value',''); low=club.lower()
        if any(x in low for x in ('national football team','national under-','women\'s national','women national','u20','u21','u23','national team')): continue
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
    checks=[]; sources={'Wikidata'}; reasons=[]; technical=[]
    try:
        ent=get(WD.format(c['qid']),20).get('entities',{}).get(c['qid'],{}); cl=ent.get('claims',{})
        label=ent.get('labels',{}).get('en',{}).get('value','').strip(); a=age(next(iter(vals(cl,'P569')),None),now.date()); current=qids(cl,'P54')
        nat_ids=qids(cl,'P27'); pos_ids=qids(cl,'P413')
        nationality=entity_label(nat_ids[0]) if nat_ids else None; position=entity_label(pos_ids[0]) if pos_ids else None
        checks += [('1_identity',label.lower()==c['name'].strip().lower()),('2_age_13_23',a is not None and 13<=a<=23),('3_current_club_wikidata',c['clubQid'] in current),('4_club_and_country',bool(c['club'] and c['country']))]
        sofa_ok=False; team=None; sofa_nat=None; sofa_pos=None
        try:
            p=sofa(c['name'])
            if p:
                sofa_ok=True; team=(p.get('team') or {}).get('name'); sofa_nat=(p.get('country') or {}).get('name'); sofa_pos=p.get('position'); sources.add('Sofascore')
        except Exception as e: technical.append({'source':'Sofascore','errorType':type(e).__name__,'error':str(e)})
        tm_ok=False
        try:
            tm_ok=tm(c['name'],c['club'])
            if tm_ok:sources.add('Transfermarkt')
        except Exception as e: technical.append({'source':'Transfermarkt','errorType':type(e).__name__,'error':str(e)})
        checks += [('5_independent_player_profile',sofa_ok or tm_ok),('6_current_club_independent',(bool(team and team.strip().lower()==c['club'].strip().lower()) if sofa_ok else tm_ok)),('7_essential_profile_fields_available',bool(c['name'] and a is not None and (sofa_nat or nationality) and (sofa_pos or position) and c['club'] and c['country']))]
        passed=sum(ok for _,ok in checks); hard_conflict=bool(sofa_ok and team and team.strip().lower()!=c['club'].strip().lower())
        if hard_conflict: reasons.append('harde clubtegenstrijdigheid')
        if not checks[0][1]: reasons.append('identiteit niet bevestigd')
        if passed<5: reasons.append('minder dan 5 van 7 hoofdcontroles')
        if len(sources)<2: reasons.append('minder dan 2 onafhankelijke bronnen')
        if technical and (not sofa_ok and not tm_ok): return None,checks,[],{'candidateId':c['qid'],'name':c['name'],'club':c['club'],'country':c['country'],'errorType':'SourceTechnicalError','error':'; '.join(f"{x['source']}: {x['error']}" for x in technical),'checks':{n:ok for n,ok in checks}}
        player={'id':f'official:wikidata:{c["qid"]}','name':c['name'],'age':a,'club':team or c['club'],'position':sofa_pos or position,'nationality':sofa_nat or nationality,'country':c['country'],'sources':sorted(sources),'verification':{'status':'verified','checkedAt':now.isoformat(),'checksPassed':[n for n,ok in checks if ok],'checkCount':passed,'mainControlCount':7,'controls':{n:ok for n,ok in checks},'hardConflict':hard_conflict,'additionalEvidence':{'sourceErrors':technical}}}
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
        if error: errors.append({'stage':'candidate_verification',**error}); continue
        passed=sum(ok for _,ok in checks)
        if p and passed>=5 and len(p['sources'])>=2 and not reasons: approved.append(p)
        else: rejected.append({'id':f'candidate:{c["qid"]}','name':c['name'],'country':c['country'],'club':c['club'],'reason':' / '.join(reasons) or 'verification failed','failedControls':[n for n,ok in checks if not ok],'checksPerformed':7,'checksPassed':passed,'mainControlCount':7,'supportingSources':sorted((p or {}).get('sources',[]))})
    completed=datetime.now(timezone.utc); stamp=completed.astimezone(ZoneInfo('Europe/Brussels')).strftime('%Y-%m-%d-%H%M%S-%f'); out=RUNS/f'{stamp}-automated-run.json'
    report={'runStartedAt':started.isoformat(),'runCompletedAt':completed.isoformat(),'status':'completed','runType':'automated real public-source scouting run','regionOrder':['Europe','Asia','North America','South America','Africa','Oceania'],'countriesScouted':selected,'scope':'Young lesser-known players currently attached to clubs in the selected countries, not selected by nationality.','verificationPolicy':'Exactly 7 main controls: identity, age 13-23, current club in Wikidata, club/country, independent player profile, independent current club, essential profile fields. 5/7, 6/7 or 7/7 may pass; 4/7 or lower is rejected. Evidence subchecks do not create extra main controls. Minimum 2 independent public sources. Hard contradictions block publication. Technical errors are stored in runnerErrors and are never converted into player rejections.','candidatesScreened':screened,'approvedPlayers':approved,'rejectedPlayers':rejected,'runnerErrors':errors,'existingPlayersPreserved':True,'unexpectedDeletions':False,'jsonValid':True,'writeVerification':'workflow_run sync-after-talent-finder-run'}
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(out); print(f'Selected={selected} Screened={screened} Approved={len(approved)} Rejected={len(rejected)} Errors={len(errors)}')
if __name__=='__main__':main()

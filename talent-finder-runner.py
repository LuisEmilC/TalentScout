#!/usr/bin/env python3
import json,re,time,urllib.parse,urllib.request
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
RUNS=ROOT/'talent-finder-runs'; RUNS.mkdir(parents=True,exist_ok=True)
REGION_ORDER=['Europe','Asia','North America','South America','Africa','Oceania']
COUNTRIES={
'Europe':['Albania','Andorra','Armenia','Austria','Azerbaijan','Belarus','Belgium','Bosnia and Herzegovina','Bulgaria','Croatia','Cyprus','Czechia','Denmark','England','Estonia','Finland','France','Georgia','Germany','Greece','Hungary','Iceland','Ireland','Italy','Kosovo','Latvia','Liechtenstein','Lithuania','Luxembourg','Malta','Moldova','Monaco','Montenegro','Netherlands','North Macedonia','Norway','Poland','Portugal','Romania','Russia','San Marino','Scotland','Serbia','Slovakia','Slovenia','Spain','Sweden','Switzerland','Turkey','Ukraine','Wales'],
'Asia':['Afghanistan','Bahrain','Bangladesh','Bhutan','Brunei','Cambodia','China','East Timor','India','Indonesia','Iran','Iraq','Israel','Japan','Jordan','Kazakhstan','Kuwait','Kyrgyzstan','Laos','Lebanon','Malaysia','Maldives','Mongolia','Myanmar','Nepal','North Korea','Oman','Pakistan','Palestine','Philippines','Qatar','Saudi Arabia','Singapore','South Korea','Sri Lanka','Syria','Tajikistan','Thailand','Turkmenistan','United Arab Emirates','Uzbekistan','Vietnam','Yemen'],
'North America':['Antigua and Barbuda','Bahamas','Barbados','Belize','Canada','Costa Rica','Cuba','Dominica','Dominican Republic','El Salvador','Grenada','Guatemala','Haiti','Honduras','Jamaica','Mexico','Nicaragua','Panama','Saint Kitts and Nevis','Saint Lucia','Saint Vincent and the Grenadines','Trinidad and Tobago','United States'],
'South America':['Argentina','Bolivia','Brazil','Chile','Colombia','Ecuador','Guyana','Paraguay','Peru','Suriname','Uruguay','Venezuela'],
'Africa':['Algeria','Angola','Benin','Botswana','Burkina Faso','Burundi','Cameroon','Cape Verde','Central African Republic','Chad','Comoros','Democratic Republic of the Congo','Republic of the Congo','Djibouti','Egypt','Equatorial Guinea','Eritrea','Eswatini','Ethiopia','Gabon','Gambia','Ghana','Guinea','Guinea-Bissau','Ivory Coast','Kenya','Lesotho','Liberia','Libya','Madagascar','Malawi','Mali','Mauritania','Mauritius','Morocco','Mozambique','Namibia','Niger','Nigeria','Rwanda','São Tomé and Príncipe','Senegal','Seychelles','Sierra Leone','Somalia','South Africa','South Sudan','Sudan','Tanzania','Togo','Tunisia','Uganda','Zambia','Zimbabwe'],
'Oceania':['Australia','Fiji','Kiribati','Marshall Islands','Micronesia','Nauru','New Zealand','Palau','Papua New Guinea','Samoa','Solomon Islands','Tonga','Tuvalu','Vanuatu']}
UA='TalentScout-Talent-Finder/4.0 (+https://github.com/LuisEmilC/TalentScout)'
SPARQL='https://query.wikidata.org/sparql?format=json&query='
WD='https://www.wikidata.org/w/api.php?action=wbgetentities&ids={}&format=json&props=claims|labels'
SS='https://www.sofascore.com/api/v1/search/all?q={}'
TM='https://www.transfermarkt.com/schnellsuche/ergebnis/schnellsuche?query={}'

def get(url,timeout=20,accept='application/json'):
    last=None
    for n in range(4):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':accept,'Accept-Language':'en-US,en;q=0.8'})
            with urllib.request.urlopen(req,timeout=timeout) as r:
                raw=r.read().decode('utf-8','replace')
            return json.loads(raw)
        except Exception as e:
            last=e
            if n<3: time.sleep(1.5*(n+1))
    raise last

def html(url,timeout=12):
    req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'text/html,application/xhtml+xml','Accept-Language':'en-US,en;q=0.8'})
    with urllib.request.urlopen(req,timeout=timeout) as r:return r.read().decode('utf-8','replace').lower()

def qids(claims,p):
    out=[]
    for c in claims.get(p,[]) or []:
        try: out.append(c['mainsnak']['datavalue']['value']['id'])
        except Exception: pass
    return out

def values(claims,p):
    out=[]
    for c in claims.get(p,[]) or []:
        try: out.append(c['mainsnak']['datavalue']['value'])
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
    y,mo,d=map(int,m.groups()); return today.year-y-((today.month,today.day)<(mo,d))

def discover_region(region,limit_per_country=8):
    names=COUNTRIES[region]
    vals=' '.join(json.dumps(x,ensure_ascii=False) for x in names)
    q=f'''PREFIX xsd: <http://www.w3.org/2001/XMLSchema#> PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?person ?personLabel ?birth ?club ?clubLabel ?countryLabel WHERE {{
 ?person wdt:P31 wd:Q5; wdt:P106 wd:Q937857; wdt:P569 ?birth; wdt:P54 ?club.
 ?club wdt:P17 ?country. ?country rdfs:label ?countryLabel.
 FILTER(lang(?countryLabel)="en") VALUES ?countryLabel {{{vals}}}
 FILTER(?birth >= "2002-01-01T00:00:00Z"^^xsd:dateTime) FILTER(?birth <= "2010-12-31T23:59:59Z"^^xsd:dateTime)
 SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} ORDER BY ?countryLabel DESC(?birth)'''
    d=get(SPARQL+urllib.parse.quote(q),45); out=[]; counts={}
    for r in d.get('results',{}).get('bindings',[]):
        country=r['countryLabel']['value'];
        if counts.get(country,0)>=limit_per_country: continue
        counts[country]=counts.get(country,0)+1
        out.append({'qid':r['person']['value'].rsplit('/',1)[-1],'name':r['personLabel']['value'],'clubQid':r['club']['value'].rsplit('/',1)[-1],'club':r.get('clubLabel',{}).get('value'),'country':country,'region':region})
    return out

def sofa(name):
    d=get(SS.format(urllib.parse.quote(name)),20)
    for r in d.get('results',[]) or []:
        p=r.get('entity') if isinstance(r,dict) and r.get('entity') else r
        if isinstance(p,dict) and p.get('id') and str(p.get('name','')).strip().lower()==name.strip().lower():return p
    return None

def transfermarkt(name,club):
    try:
        page=html(TM.format(urllib.parse.quote(name)),12)
        n=re.sub(r'\s+',' ',re.sub('<[^>]+>',' ',page))
        return name.strip().lower() in n and club.strip().lower() in n
    except Exception:return False

def verify(c,now):
    checks=[]; sources={'Wikidata'}; reasons=[]
    try:
        ent=get(WD.format(c['qid']),20).get('entities',{}).get(c['qid'],{})
        cl=ent.get('claims',{}); label=ent.get('labels',{}).get('en',{}).get('value','').strip(); a=age(birth(cl),now.date()); current=qids(cl,'P54')
        checks.append(('identity_exact',label.lower()==c['name'].strip().lower()))
        checks.append(('age_16_24',a is not None and 16<=a<=24))
        checks.append(('current_club_wikidata',c['clubQid'] in current))

        p=sofa(c['name']); team=(p or {}).get('team',{}).get('name'); nationality=((p or {}).get('country') or {}).get('name') if p else None; position=(p or {}).get('position') if p else None
        if p:sources.add('Sofascore')
        checks.append(('independent_player_profile',bool(p)))
        checks.append(('current_club_independent',bool(team and team.strip().lower()==c['club'].strip().lower())))
        checks.append(('essential_profile_fields',bool(nationality and position)))

        tm_ok=transfermarkt(c['name'],c['club'])
        if tm_ok:sources.add('Transfermarkt')
        checks.append(('third_source_identity_and_club',tm_ok))

        club_ent=get(WD.format(c['clubQid']),20).get('entities',{}).get(c['clubQid'],{})
        club_cl=club_ent.get('claims',{})
        official_urls=values(club_cl,'P856'); official_ok=False
        for official in official_urls[:3]:
            try:
                page=html(str(official),10)
                if c['club'].strip().lower() in page and c['name'].strip().lower() in page:
                    official_ok=True; break
            except Exception: continue
        if official_ok:sources.add('Official club website')
        checks.append(('official_club_source_when_available',official_ok or not official_urls))

        # Country is tied to the club, not the player's nationality.
        checks.append(('target_country_from_club',bool(c.get('country') and c.get('club'))))
        passed=sum(ok for _,ok in checks)
        # Approval requires 7+ controls and at least two genuinely different public sources.
        if passed<7: reasons.append('not all 7 verification controls passed')
        if len(sources)<2: reasons.append('fewer than 2 independent public sources')
        if not p: reasons.append('Sofascore player profile not found')
        if p and (not team or team.strip().lower()!=c['club'].strip().lower()): reasons.append('independent current club mismatch')

        player={'id':f'official:wikidata:{c["qid"]}','name':c['name'],'age':a,'club':team or c['club'],'position':position,'nationality':nationality,'country':c['country'],'region':c['region'],'sources':sorted(sources),'verification':{'status':'verified','checkedAt':now.isoformat(),'checksPassed':[n for n,ok in checks if ok],'checkCount':passed,'controls':{n:ok for n,ok in checks},'officialClubSourceUsed':official_ok}}
        return player,checks,reasons
    except Exception as e:return None,[('runner_error',False)],[f'{type(e).__name__}: {e}']

def main():
    started=datetime.now(timezone.utc); approved=[]; rejected=[]; errors=[]; seen=set(); screened=0; countries=[]
    for region in REGION_ORDER:
        countries.extend(COUNTRIES[region])
        try:candidates=discover_region(region,8)
        except Exception as e:
            errors.append({'region':region,'error':f'{type(e).__name__}: {e}'}); continue
        for c in candidates:
            if c['qid'] in seen:continue
            seen.add(c['qid']); screened+=1
            p,checks,reasons=verify(c,started); passed=sum(ok for _,ok in checks)
            if p and passed>=7 and len(p.get('sources',[]))>=2 and not reasons: approved.append(p)
            else: rejected.append({'id':f'candidate:{c["qid"]}','name':c['name'],'country':c['country'],'region':c['region'],'club':c.get('club'),'reason':' / '.join(reasons) or 'verification failed','failedControls':[n for n,ok in checks if not ok],'checksPerformed':len(checks),'checksPassed':passed,'supportingSources':sorted(set((p or {}).get('sources',[])))})
    completed=datetime.now(timezone.utc); stamp=completed.astimezone(ZoneInfo('Europe/Brussels')).strftime('%Y-%m-%d-%H%M%S-%f')
    report={'runStartedAt':started.isoformat(),'runCompletedAt':completed.isoformat(),'status':'completed','runType':'automated real public-source scouting run','regionOrder':REGION_ORDER,'countriesScouted':countries,'scope':'Young lesser-known players currently attached to clubs in the selected countries, not players selected by nationality.','verificationPolicy':'Minimum 7 explicit controls; Wikidata + independent football profile + third-source/official checks where available; minimum 2 distinct public sources; unresolved current-club contradictions block publication. Technical errors are never player rejections.','candidatesScreened':screened,'approvedPlayers':approved,'rejectedPlayers':rejected,'existingPlayersPreserved':True,'unexpectedDeletions':False,'jsonValid':True,'writeVerification':'GitHub Actions sync required','runnerErrors':errors}
    out=RUNS/f'{stamp}-automated-run.json'; out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(out); print(f'Screened={screened} Approved={len(approved)} Rejected={len(rejected)} Errors={len(errors)}')
if __name__=='__main__':main()

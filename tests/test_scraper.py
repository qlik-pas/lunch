"""Offline tests for scraper.py: week logic, parsers, translation cache/batching,
the Gemini retry/fallback chain and the extraction guard. No network, no API key.

    python tests/test_scraper.py
"""
import sys, os, json, copy, datetime, time, re
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import scraper as S
ok=0; bad=[]
def check(name, cond, extra=""):
    global ok
    if cond: ok+=1
    else: bad.append(f"{name} {extra}")

# week_info / claimed_week
w,dates,rng=S.week_info(datetime.date(2026,10,21)); check("week_info",(w,dates[0],dates[4],rng)==(43,"2026-10-19","2026-10-23","19–23 okt"),(w,dates,rng))
w,dates,_=S.week_info(datetime.date(2026,10,25)); check("sunday still wk43",w==43 and dates[0]=="2026-10-19")
for txt,exp in [("Vecka 43",43),("Meny V44",44),("Week 7",7),("Dagens v 43",43),("Måndag 19 okt",43),("Måndag, 17 Aug",None),("Vecka 99",None),("LUNCH WEEK 43-44, 2026",44),("Lunch week 43–44",44),("week 43-\n44, 2026",44),("Vecka 43 - 45",43),("Week 52-53",53),("hej",None)]:
    check(f"claimed_week {txt}",S.claimed_week(txt)==exp,S.claimed_week(txt))

# parsers on synthetic text
lin="Lunchbuffé\nMåndag 19 okt\nRätt A\nRätt B\nTisdag 20 okt\nRätt C\nLunchbuffén serveras mån-fre\nSkräp"
m=S.parse_linnea(lin); check("linnea",m["Måndag"]==["Rätt A","Rätt B"] and m["Tisdag"]==["Rätt C"] and not m["Onsdag"],m)
mh="Dagens rätt vecka 43\nMåndag\nA\nB\nC\nTisdag\nD\nVeckans pasta\nX"
m=S.parse_matochharmoni(mh); check("matochharmoni",m["Måndag"]==["A","B","C"] and m["Tisdag"]==["D"],m)

# Bryggan / Inspira, on the page text as captured in week 44
HERE=os.path.dirname(os.path.abspath(__file__))
t=open(os.path.join(HERE,"fixtures_bryggan.txt"),encoding="utf-8").read(); m=S.parse_bryggan(t)
check("bryggan week",S.claimed_week(t)==44)
check("bryggan 2 per day",all(len(m[d])==2 for d in S.DAYS),{d:len(m[d]) for d in S.DAYS})
check("bryggan dishes",m["Måndag"][0].startswith("Grönsaksfrittata") and m["Fredag"][1].startswith("Wallenbergare") and not any("reservation" in x for v in m.values() for x in v),m["Fredag"])
t=open(os.path.join(HERE,"fixtures_inspira.txt"),encoding="utf-8").read(); m=S.parse_inspira(t)
check("inspira week",S.claimed_week(t)==44)
check("inspira 4 per day",all(len(m[d])==4 for d in S.DAYS),{d:len(m[d]) for d in S.DAYS})
check("inspira green is veg, garnish joined",m["Måndag"][0]=="Vegetariskt: Pasta Mafaldine Puttanesca – parmesan & ruccola" and m["Tisdag"][1]=="Stekt sill & potatismos – brynt smör, rårörda lingon, rödlök & dill",m["Måndag"][:2])
check("inspira 'Asia|' without space",m["Tisdag"][2].startswith("Pho med kyckling"),m["Tisdag"][2])
check("parsers empty on junk",not any(S.parse_bryggan("hej").values()) and not any(S.parse_inspira("hej").values()))

# _entry / weekly
e=S._entry("Troppo","u",{"Måndag":["a"],"Tisdag":["a"],"Onsdag":["a"],"Torsdag":["a"],"Fredag":["a"]}); check("weekly flag",e.get("weekly") is True)
e=S._entry("Kantin","u",S._empty()); check("not weekly",not e.get("weekly"))

# closed weeks
for txt,exp in [("Vi håller stängt v. 44",True),("Restaurangen är stängd denna vecka",True),("Semesterstängt",True),("Stängt vecka 44",True),
                ("Vi har tyvärr stängt pga renovering",True),("Closed this week",True),
                ("Lör–sön stängt",False),("Köket stänger 14:00",False),("Mån-fre 11-14\nLör stängt",False),("helg stängt",False)]:
    check(f"says_closed {txt!r}",S.says_closed(txt)==exp)
check("week_key",S.week_key(datetime.date(2026,10,26))=="2026-W44" and S.week_key(datetime.date(2027,1,4))=="2027-W01")
check("closed flag",S._entry("X","u",S._empty(),closed=True).get("closed") is True and "closed" not in S._entry("X","u",S._empty()))
import tempfile
with tempfile.NamedTemporaryFile("w",suffix=".json",delete=False,encoding="utf-8") as f: f.write('{"2026-W44":["Smaka på Kina"],"junk":3}')
check("load_closed",S.load_closed(f.name)=={"2026-W44":{"Smaka på Kina"}},S.load_closed(f.name)); os.unlink(f.name)
check("load_closed missing",S.load_closed("/nonexistent.json")=={})

# _previous_menus
old={"week":43,"restaurants":[{"name":"A","menus":{"Måndag":["x"]}},{"name":"B","menus":{"Måndag":[]}}]}
check("prev same week",list(S._previous_menus(old,43))==["A"]); check("prev other week",S._previous_menus(old,44)=={})

# translations: cache, batch, failure keep, force
def mk(): return [{"name":"A","url":"u","menus":{"Måndag":["Köttbullar"],"Tisdag":[],"Onsdag":[],"Torsdag":[],"Fredag":[]}},
                  {"name":"W","url":"u","weekly":True,"menus":{d:["Soppa"] for d in S.DAYS}},
                  {"name":"E","url":"u","menus":S._empty()}]
calls=[]
def fake(sys_,payload): calls.append(payload); return {n:{d:[f"EN {x}" for x in v] for d,v in days.items()} for n,days in payload.items()}
r=mk(); S._with_translations(r,{},translate=fake)
check("one batched call",len(calls)==1 and set(calls[0])=={"A","W"},calls)
check("weekly asked once",list(calls[0]["W"])==["Måndag"])
check("weekly en all days",set(r[1]["en"])==set(S.DAYS) and r[1]["en"]["Fredag"]==["EN Soppa"])
check("empty place no en","en" not in r[2])
calls.clear(); r2=mk(); S._with_translations(r2,{"restaurants":r},translate=fake); check("cache hit no call",not calls and r2[0]["en"]==r[0]["en"])
r3=mk(); r3[0]["menus"]["Måndag"]=["Ny"]; S._with_translations(r3,{"restaurants":r},translate=fake); check("changed menu retranslated",calls and list(calls[0])==["A"])
def boom(*a): raise RuntimeError("x")
os.environ["FORCE_TRANSLATE"]="1"; r4=mk(); S._with_translations(r4,{"restaurants":r},translate=boom); check("force+fail keeps old en",r4[0].get("en")==r[0]["en"]); del os.environ["FORCE_TRANSLATE"]
bad_shape=lambda s,p: {"A":{"Måndag":["a","b"]}}  # wrong length
r5=mk(); S._with_translations(r5,{},translate=bad_shape); check("bad shape -> no en","en" not in r5[0])
check("never raises on garbage",True)
S._with_translations(mk(),{},translate=lambda s,p: "garbage")  # must not raise

# en_full: own field and prompt, own cache, independent of en
seen=[]
def fake_full(sys_,payload): seen.append(sys_); return {n:{d:[f"FULL {x}" for x in v] for d,v in days.items()} for n,days in payload.items()}
r=mk(); S._with_translations(r,{},translate=fake); S._with_translations(r,{},translate=fake_full,field="en_full")
check("en_full set, en untouched", r[0]["en_full"]["Måndag"]==["FULL Köttbullar"] and r[0]["en"]["Måndag"]==["EN Köttbullar"], r[0])
check("en_full uses the full prompt", seen and seen[0]==S.FULL_TRANSLATE_PROMPT and "faithfully" in seen[0])
seen.clear(); r6=mk(); S._with_translations(r6,{"restaurants":r},translate=fake_full,field="en_full"); check("en_full cache hit", not seen and r6[0]["en_full"]==r[0]["en_full"])
r7=mk(); S._with_translations(r7,{"restaurants":[{**x,"en_full":None} for x in r]},translate=boom,field="en_full"); check("en_full fail -> absent, no raise","en_full" not in r7[0])

# _llm_json: retries/fallback with mocked requests
import requests
os.environ["GEMINI_API_KEY"]="k"; slept=[]; time.sleep=lambda s: slept.append(s)
class R:
    def __init__(s,c,t=""): s.status_code=c; s.ok=c==200; s.text=t; s.headers={}
    def json(s): return {"candidates":[{"content":{"parts":[{"text":"noise {\"a\":1} noise"}]}}]}
def run(seq):
    it=iter(seq); urls=[]; slept.clear(); S._waited=0
    def post(u,**k):
        urls.append(u.split("models/")[1].split(":")[0]); x=next(it)
        if isinstance(x,Exception): raise x
        return x
    requests.post=post
    try: return S._llm_json("s",{}),urls
    except Exception as e: return "ERR "+str(e),urls
res,u=run([R(503),R(200)]); check("503 then ok",res=={"a":1} and len(slept)==1,(res,slept))
res,u=run([R(503)]*3+[R(200)]); check("falls to model 2",res=={"a":1} and u[-1]=="gemini-flash-lite-latest",u)
res,u=run([requests.exceptions.ReadTimeout("t"),R(200)]); check("timeout -> next model",res=={"a":1} and u==["gemini-flash-latest","gemini-flash-lite-latest"],u)
res,u=run([R(403,"nope")]); check("403 fails fast",str(res).startswith("ERR HTTP 403") and len(u)==1,res)
res,u=run([R(404),R(200)]); check("404 -> next",res=={"a":1})
res,u=run([R(503)]*3+[R(503)]*3+[R(503)]*3); check("all down error",str(res).startswith("ERR no model answered"),res)
del os.environ["GEMINI_API_KEY"]
try: S._llm_json("s",{}); check("no key raises",False)
except RuntimeError as e: check("no key raises","GEMINI_API_KEY" in str(e))

# extraction guard
page="Måndag\nKöttbullar med potatismos och lingon\nTisdag\nFisksoppa med bröd"
good=lambda s,p: {"Måndag":["Köttbullar med potatismos och lingon"],"Tisdag":["Fisksoppa med bröd"]}
check("extract ok",S._llm_extract_menus("X",page,call=good)["Tisdag"]==["Fisksoppa med bröd"])
for nm,fn in [("invented",lambda s,p:{"Måndag":["Hummer thermidor"]}),("non-dict",lambda s,p:"x"),("empty",lambda s,p:{d:[] for d in S.DAYS})]:
    try: S._llm_extract_menus("X",page,call=fn); check("extract "+nm,False)
    except ValueError: check("extract "+nm,True)
print(f"{ok} passed, {len(bad)} failed"); [print("FAIL",b) for b in bad]
sys.exit(1 if bad else 0)

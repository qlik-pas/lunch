"""Browser tests for index.html (headless Chromium via Playwright): boot, days, weekend,
fallbacks, classification, fixed list, roulette, the copy-to-clipboard button, layout,
themes, tap targets. Serves the repo itself; uses the committed lt.json.

    pip install playwright==1.63.0 && playwright install chromium
    python tests/test_ui.py
"""
import json, re, os, sys, datetime, http.server, threading, functools, unicodedata
from playwright.sync_api import sync_playwright
ROOT=os.path.join(os.path.dirname(os.path.abspath(__file__)),"..")
H=functools.partial(http.server.SimpleHTTPRequestHandler,directory=ROOT)
class Q(http.server.ThreadingHTTPServer): pass
H.log_message=lambda *a,**k: None
srv=Q(("127.0.0.1",0),H); threading.Thread(target=srv.serve_forever,daemon=True).start()
URL=f"http://127.0.0.1:{srv.server_address[1]}/"
LT=json.load(open(ROOT+"/lt.json"))
HTML=open(ROOT+"/index.html",encoding="utf-8").read()
FIXED=re.findall(r'\{ name: "([^"]+)",\s+blurb:',HTML)   # FIXED_PLACES in index.html
N=len(LT["restaurants"])
res=[]; 
def t(name,cond,extra=""):
    res.append((name,bool(cond),str(extra)[:160]))
WED=datetime.datetime(2026,10,21,12,0); SUN=datetime.datetime(2026,10,25,12,0); FRI=datetime.datetime(2026,10,23,12,0)

with sync_playwright() as p:
    b=p.chromium.launch()
    def page(when=WED,w=390,h=844,scheme="light",perms=True,reduced=False,route=None,init=None):
        c=b.new_context(viewport={"width":w,"height":h},color_scheme=scheme,reduced_motion="reduce" if reduced else "no-preference",
                        permissions=["clipboard-read","clipboard-write"] if perms else [])
        pg=c.new_page(); pg.errs=[]; pg.on("pageerror",lambda e:pg.errs.append(str(e)))
        pg.on("console",lambda m: pg.errs.append("console:"+m.text) if m.type=="error" and "Failed to load resource" not in m.text else None)
        pg.ext=[]; pg.on("request",lambda r: pg.ext.append(r.url) if not r.url.startswith(URL) and not r.url.startswith("data:") else None)
        if when: pg.clock.install(time=when)
        if init: pg.add_init_script(init)
        if route: pg.route("**/lt.json",route)
        pg.goto(URL); pg.wait_for_selector(".place",timeout=8000); pg.wait_for_timeout(500); return pg

    # ---- boot / today / status ------------------------------------------------
    pg=page()
    t("boot: no page errors", not pg.errs, pg.errs)
    t("boot: only Google Fonts external", all(("fonts.googleapis.com" in u or "fonts.gstatic.com" in u) for u in pg.ext), set(pg.ext))
    t("boot: status Live", "LIVE" in pg.inner_text("#status").upper(), pg.inner_text("#status"))
    t("boot: week label", f"Vecka {LT['week']}" in pg.inner_text("#weeklabel"), pg.inner_text("#weeklabel"))
    t("boot: Wednesday selected", pg.inner_text("#dayHeading").strip().lower()=="onsdag" and pg.get_attribute(".day:nth-child(3)","aria-selected")=="true")
    t("boot: IDAG tag", "idag" in pg.inner_text("#daySub").lower())
    t("boot: one card per scraped place", pg.locator(".place").count()==N, (pg.locator(".place").count(),N))
    t("boot: <html lang=sv>", pg.get_attribute("html","lang")=="sv")
    t("boot: theme-color metas", pg.locator('meta[name="theme-color"]').count()>=2)

    # ---- every day: heading + dish counts match data -----------------------------
    DAYS=["Måndag","Tisdag","Onsdag","Torsdag","Fredag"]
    for i,dn in enumerate(DAYS):
        pg.click(f".day:nth-child({i+1})"); pg.wait_for_timeout(150)
        ok_h = pg.inner_text("#dayHeading").strip().lower()==dn.lower()
        cards={pg.inner_text(f".place:nth-child({k+1}) h2").strip(): pg.locator(f".place:nth-child({k+1}) .dishes li").count() for k in range(pg.locator(".place").count())}
        exp={r["name"]:len([x for x in r["menus"][dn] if x.strip()]) for r in LT["restaurants"]}
        t(f"day {dn}: heading + dish counts", ok_h and all(cards.get(n)==c or (c==0 and n not in cards) for n,c in exp.items()), (ok_h,{n:(cards.get(n),c) for n,c in exp.items() if cards.get(n)!=c}))
        t(f"day {dn}: IDAG only on Wednesday", ("idag" in pg.inner_text("#daySub").lower())==(dn=="Onsdag"))
    # chips
    pg.click(".day:nth-child(3)")
    if any(x.lower().startswith("veg") for r in LT["restaurants"] for x in r["menus"]["Onsdag"]):
        t("chip: Grönt on Vegetariskt lines", pg.locator(".veg-chip").count()>=1, pg.locator(".veg-chip").count())
    bonus_days=[dn for dn in DAYS if any(any(x.lower().startswith("bonus") for x in r["menus"][dn]) for r in LT["restaurants"])]
    if bonus_days:
        pg.click(f".day:nth-child({DAYS.index(bonus_days[0])+1})"); pg.wait_for_timeout(100)
        t(f"chip: Bonus on {bonus_days[0]}", pg.locator(".treat-chip").count()>=1)
    # keyboard on rail
    pg.focus(".day:nth-child(1)"); pg.keyboard.press("Tab"); pg.keyboard.press("Enter"); pg.wait_for_timeout(100)
    t("keyboard: Tab+Enter switches day", pg.inner_text("#dayHeading").strip().lower()=="tisdag", pg.inner_text("#dayHeading"))
    pg.context.close()

    # ---- weekend -----------------------------------------------------------------
    pg=page(SUN)
    t("weekend: Monday + Helg note", pg.inner_text("#dayHeading").strip().lower()=="måndag" and "helg" in pg.inner_text("#daySub").lower(), pg.inner_text("#daySub"))
    pg.context.close()

    # ---- fallback paths -------------------------------------------------------------
    pg=page(route=lambda r: r.fulfill(status=404,body="no"))
    t("fallback 404: Sparad meny + snapshot renders", ("sparad" in pg.inner_text("#status").lower()) and pg.locator(".place").count()>=1, pg.inner_text("#status"))
    pg.context.close()
    pg=page(route=lambda r: r.fulfill(status=200,content_type="application/json",body='{"restaurants":[]}'))
    t("fallback empty json: snapshot kept", pg.locator(".place").count()>=1 and "sparad" in pg.inner_text("#status").lower(), pg.inner_text("#status"))
    pg.context.close()
    # classification with doctored data
    d=json.loads(json.dumps(LT))
    d["restaurants"][0]["menus"]={k:[] for k in DAYS}                                   # no menu -> demoted
    d["restaurants"][1]["menus"]={k:["Samma rätt"] for k in DAYS}                       # same every day, not weekly -> demoted
    d["restaurants"][1].pop("weekly",None)
    pg=page(route=lambda r: r.fulfill(status=200,content_type="application/json",body=json.dumps(d)))
    t("classify: 2 demoted, rest cards", pg.locator(".place").count()==N-2 and pg.locator("#others").is_visible(), pg.locator(".place").count())
    pg.click("#others summary"); pg.wait_for_timeout(150); txt=pg.inner_text("#others")
    t("classify: reasons shown", d["restaurants"][0]["name"] in txt and d["restaurants"][1]["name"] in txt and "Samma rätt" in txt, txt[:100])
    pg.context.close()

    # closed for the week -> own section, not "Meny inte uppdaterad"
    d=json.loads(json.dumps(LT))
    for r in d["restaurants"]: r.pop("closed",None)                                   # independent of today's lt.json
    d["restaurants"][0]["menus"]={k:[] for k in DAYS}; d["restaurants"][0]["closed"]=True
    pg=page(route=lambda r: r.fulfill(status=200,content_type="application/json",body=json.dumps(d)))
    t("closed: own section, no card", pg.locator(".place").count()<=N-1 and pg.locator("#closed").is_visible()
      and "stängt denna vecka (1)" in pg.inner_text("#closedLabel").lower(), pg.inner_text("#closedLabel"))
    pg.click("#closed summary"); pg.wait_for_timeout(150)
    t("closed: not in 'Meny inte uppdaterad'", d["restaurants"][0]["name"] in pg.inner_text("#closed")
      and (not pg.locator("#others").is_visible() or d["restaurants"][0]["name"] not in pg.inner_text("#others")))
    pg.context.close()

    # ---- language toggle --------------------------------------------------------------
    pg=page()
    t("lang: SV by default", pg.get_attribute("html","lang")=="sv" and pg.get_attribute('.lang [data-lang="sv"]',"aria-pressed")=="true")
    sv_first=pg.inner_text(".place .dishes li")
    pg.click('.lang [data-lang="en"]'); pg.wait_for_timeout(200)
    t("lang: EN switches page", pg.get_attribute("html","lang")=="en" and pg.inner_text("#dayHeading").strip()=="Wednesday"
      and pg.inner_text("#weeklabel").startswith(f"Week {LT['week']}") and "today" in pg.inner_text("#daySub").lower()
      and pg.inner_text(".day:nth-child(1) .dow").strip().lower()=="mon", (pg.inner_text("#dayHeading"),pg.inner_text("#weeklabel")))
    en_wed={x for r in LT["restaurants"] for x in r.get("en",{}).get("Onsdag",[])}
    shown=[re.sub(r"^(Veg|Bonus)\n","",x).strip() for x in pg.locator(".place .dishes li").all_inner_texts()]
    t("lang: EN dishes from lt.json en", not en_wed or any(x in en_wed or re.sub(r"^Vegetarian:\s*","",e)==x for x in shown for e in en_wed), shown[:3])
    t("lang: static labels translated", "can't decide" in pg.inner_text(".picker-intro").lower() and "standing menu" in pg.inner_text("#fixedLabel").lower()
      and "scraped every weekday" in pg.inner_text("footer").lower() and pg.get_attribute("#rail","aria-label")=="Pick a day")
    t("lang: no page errors", not pg.errs, pg.errs)
    pg.reload(); pg.wait_for_selector(".place"); pg.wait_for_timeout(400)
    t("lang: EN remembered after reload", pg.inner_text("#dayHeading").strip()=="Wednesday" and pg.get_attribute('.lang [data-lang="en"]',"aria-pressed")=="true")
    pg.click('.lang [data-lang="sv"]'); pg.wait_for_timeout(200)
    t("lang: back to SV restores Swedish", pg.inner_text("#dayHeading").strip()=="Onsdag" and pg.inner_text(".place .dishes li")==sv_first and "Live".upper() in pg.inner_text("#status").upper())
    pg.context.close()
    # missing translation -> Swedish line, no blank
    d=json.loads(json.dumps(LT)); d["restaurants"][0].pop("en",None)
    pg=page(route=lambda r: r.fulfill(status=200,content_type="application/json",body=json.dumps(d)),
            init="try{localStorage.setItem('lang','en')}catch(e){}")
    first=pg.locator(".place").first
    want=[x for x in d["restaurants"][0]["menus"]["Onsdag"] if x.strip()]
    t("lang: untranslated place falls back to Swedish", not want or " ".join(first.locator("li").first.inner_text().split()).removeprefix("Veg ").removeprefix("Grönt ") in [" ".join(re.sub(r"^(Vegetariskt|Bonus)\s*:\s*","",w).split()) for w in want], first.inner_text()[:80])
    pg.context.close()

    # ---- fixed list ------------------------------------------------------------------
    pg=page()
    t(f"fixed: label Fast meny ({len(FIXED)})", f"fast meny ({len(FIXED)})" in pg.inner_text("#fixedLabel").lower(), pg.inner_text("#fixedLabel"))
    pg.click("#fixedLabel"); pg.wait_for_timeout(150)
    links=pg.eval_on_selector_all("#fixedList a","els=>els.map(e=>[e.textContent,e.href,e.target,e.rel])")
    t("fixed: every place has a link, new tab, noopener", len(links)==len(FIXED) and all(l[2]=="_blank" and "noopener" in l[3] and l[1].startswith("http") for l in links), links)
    cards=pg.eval_on_selector_all(".place h2 a","els=>els.map(e=>[e.textContent,e.href])")
    t("cards: every title links to its url", [c[1].rstrip('/') for c in cards]==[r['url'].rstrip('/') for r in LT['restaurants']], cards[:2])

    # ---- roulette ----------------------------------------------------------------------
    valid_names={r["name"] for r in LT["restaurants"]}|set(FIXED)
    pg.click("#pickBtn"); pg.wait_for_timeout(4200)
    t("roulette: click spin lands", pg.locator("#pickResult").is_visible() and not pg.eval_on_selector("#pickBtn","e=>e.classList.contains('spinning')"))
    nm=pg.inner_text("#reel .pname").strip(); href=pg.get_attribute("#reel .pname a","href")
    t("roulette: result is a valid place with link", nm in valid_names and href and href.startswith("http"), (nm,href))
    t("roulette: result tinted (.landed)", pg.eval_on_selector("#pickResult","e=>e.classList.contains('landed')"))
    h1=pg.eval_on_selector("#reel","e=>e.getBoundingClientRect().height"); mk=pg.eval_on_selector("#reelMask","e=>e.getBoundingClientRect().height")
    t("roulette: one row visible (mask==row)", abs(mk-pg.eval_on_selector("#reel .reel-item","e=>e.getBoundingClientRect().height"))<1.5, (h1,mk))
    pg.click("#pickAgain"); pg.wait_for_timeout(4200); t("roulette: again works", pg.locator("#pickResult").is_visible() and pg.inner_text("#reel .pname").strip() in valid_names)
    # hold path
    bx=pg.eval_on_selector("#pickBtn","e=>{const r=e.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]}")
    pg.evaluate("document.getElementById('pickBtn').scrollIntoView({block:'center',behavior:'instant'})"); bx=pg.eval_on_selector("#pickBtn","e=>{const r=e.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]}")
    pg.mouse.move(*bx); pg.mouse.down(); pg.wait_for_timeout(900)
    t("roulette: hold keeps spinning", pg.eval_on_selector("#pickBtn","e=>e.classList.contains('spinning')"))
    pg.mouse.up(); pg.wait_for_timeout(4000)
    t("roulette: hold release lands", not pg.eval_on_selector("#pickBtn","e=>e.classList.contains('spinning')") and pg.inner_text("#reel .pname").strip() in valid_names)
    # rapid double click must end in a single settled row
    pg.click("#pickBtn"); pg.wait_for_timeout(120); pg.click("#pickBtn"); pg.wait_for_timeout(5500)
    tr1=pg.eval_on_selector("#reel","e=>getComputedStyle(e).transform"); pg.wait_for_timeout(600); tr2=pg.eval_on_selector("#reel","e=>getComputedStyle(e).transform")
    t("roulette: rapid double-click settles", tr1==tr2 and not pg.eval_on_selector("#pickBtn","e=>e.classList.contains('spinning')"), (tr1,tr2))
    pg.focus("#pickBtn"); pg.keyboard.press("Enter"); pg.wait_for_timeout(4200); t("roulette: keyboard Enter spins", pg.inner_text("#reel .pname").strip() in valid_names)
    pg.evaluate("scrollTo(0,0)"); pg.click(".day:nth-child(1)"); pg.wait_for_timeout(150)
    t("roulette: hidden on day switch", not pg.locator("#pickResult").is_visible())
    t("roulette: no page errors", not pg.errs, pg.errs)
    pg.context.close()
    pg=page(reduced=True); pg.click("#pickBtn"); pg.wait_for_timeout(3500)
    t("reduced motion: roulette still lands", pg.inner_text("#reel .pname").strip() in valid_names and not pg.errs, pg.errs)
    t("reduced motion: no entrance animation", pg.eval_on_selector(".place","e=>getComputedStyle(e).animationName")=="none", pg.eval_on_selector(".place","e=>getComputedStyle(e).animationName"))
    pg.context.close()

    # ---- share button --------------------------------------------------------------------
    READ="""async()=>{const it=(await navigator.clipboard.read())[0];const o={};for(const t of it.types)o[t]=await (await it.getType(t)).text();return o}"""
    pg=page(); pg.click("#shareBtn"); pg.wait_for_timeout(500)
    cb=pg.evaluate(READ); txt,html=cb["text/plain"],cb["text/html"]
    t("share: both clipboard types", set(cb)=={"text/plain","text/html"}, list(cb))
    t("share: label 'Copied ✓' then restores", "copied" in pg.inner_text("#shareBtn").lower())
    heads=[l for l in txt.split("\n") if l.endswith(":")]
    t("share: header + one line per place", heads[0].startswith("🎡") and len(heads)==1+N+len(FIXED), len(heads))
    t("share: no :shortcodes:", not re.search(r":[a-z_-]+:",txt))
    names=[h[2:].strip(" :") if not h.startswith("🍽") else h for h in heads[1:]]
    scraped=heads[1:1+N]; fixed=heads[1+N:]
    key=lambda s: re.sub(r"[̀-ͯ]","",__import__("unicodedata").normalize("NFD",re.sub(r"^\S+\s","",s))).lower()
    SL=pg.evaluate("()=>Object.fromEntries(Object.entries(SLACK).map(([k,v])=>[k,v[1]]))")
    page_order=[(SL.get(r["name"]) or r["name"]) for r in LT["restaurants"]]
    t("share: scraped in page order", [re.sub(r"^\S+\s","",x).rstrip(":") for x in scraped]==page_order, scraped)
    t("share: fixed after scraped, alphabetical", [key(x) for x in fixed]==sorted(key(x) for x in fixed) and any("Delphi" in x for x in fixed), fixed)
    t("share: html links every place + title", len(re.findall(r'<a href="https?://[^"]+">',html))==1+N+len(FIXED), len(re.findall(r'<a href',html)))
    t("share: title links to the lunch page", re.match(r'<div><a href="https://qlik-pas\.github\.io/lunch/">🎡',html) is not None, html[:120])
    en=[x for r in LT["restaurants"] for x in r.get("en",{}).get("Onsdag",[])]
    t("share: translated dishes are used", not en or any(x in txt for x in en[:5]))
    t("share: no Vegetariskt/Bonus lines", not re.search(r"^(Vegetariskt|Bonus)",txt,re.M))
    pg.wait_for_timeout(2500); t("share: label restores", "today's lunch" in pg.inner_text("#shareBtn").lower(), pg.inner_text("#shareBtn"))
    t("share: preview hidden on clean copy", not pg.locator("#shareResult").is_visible())
    # Laziza
    def laz(week,dayidx):
        return pg.evaluate("""([w,d])=>{WEEK.week=w; selected=d; const t=utbudText().text.split('\\n'); const i=t.findIndex(l=>l.includes('Laziza:')); return t[i+1]}""",[week,dayidx])
    t("laziza: even week Wednesday", laz(44,2)=="CRISPY CHICKEN!", laz(44,2))
    t("laziza: odd week Wednesday normal", laz(43,2)!="CRISPY CHICKEN!")
    t("laziza: even week Thursday normal", laz(44,3)!="CRISPY CHICKEN!")
    # no menu yet
    r=pg.evaluate("""()=>{WEEK.week=43; selected=2; WEEK.restaurants[0].menus['Onsdag']=[]; const t=utbudText().text.split('\\n'); const i=t.findIndex(l=>l.includes('Bricks:')); return t[i+1]}""")
    t("share: empty menu -> 'no menu yet'", r=="no menu yet", r)
    r=pg.evaluate("""()=>{selected=2; WEEK.restaurants[0].closed=true; const t=utbudText().text.split('\\n'); const i=t.findIndex(l=>l.includes('Bricks:')); delete WEEK.restaurants[0].closed; return t[i+1]}""")
    t("share: closed place -> 'closed this week'", r=="closed this week", r)
    # untranslated note
    pg.evaluate("""()=>{selected=2; delete WEEK.restaurants[1].en; }"""); pg.click("#shareBtn"); pg.wait_for_timeout(500)
    t("share: untranslated named in note", pg.locator("#shareResult").is_visible() and "Ej översatt" in pg.inner_text("#shareStatus"), pg.inner_text("#shareStatus") if pg.locator("#shareStatus").is_visible() else "hidden")
    pg.click(".day:nth-child(1)"); pg.wait_for_timeout(100)
    t("share: note hidden on day switch", not pg.locator("#shareResult").is_visible())
    pg.context.close()
    # failure: no clipboard API, execCommand refuses
    pg=page(perms=False, init="Object.defineProperty(navigator,'clipboard',{value:undefined});document.execCommand=()=>false")
    pg.click("#shareBtn"); pg.wait_for_timeout(400)
    t("share failure: text shown for manual copy", pg.locator("#shareOut").is_visible() and "Kunde inte kopiera" in pg.inner_text("#shareStatus") and "🎡" in pg.inner_text("#shareOut"))
    pg.context.close()
    # legacy path (no ClipboardItem) still carries both flavours
    pg=page(init="delete window.ClipboardItem"); pg.click("#shareBtn"); pg.wait_for_timeout(500)
    try:
        cb=pg.evaluate(READ); t("share legacy: both flavours via copy event", set(cb)>={"text/plain","text/html"} and "<a href" in cb["text/html"], list(cb))
    except Exception as e: t("share legacy: both flavours via copy event", False, e)
    pg.context.close()

    # ---- layout & themes -------------------------------------------------------------------
    for w in (320,375,768,1100):
        pg=page(w=w,h=800); hs=pg.evaluate("document.documentElement.scrollWidth>innerWidth")
        pg.click("#fixedLabel")
        sb=pg.eval_on_selector("#shareBtn","e=>{const r=e.getBoundingClientRect();return [r.right<=innerWidth, r.height]}")
        t(f"layout {w}px: no horizontal scroll, share btn inside", not hs and sb[0], (hs,sb))
        pg.context.close()
    pg=page(scheme="dark"); bg=pg.evaluate("getComputedStyle(document.body).backgroundColor"); t("dark: dark background", sum(map(int,re.findall(r"\d+",bg)[:3]))<200, bg)
    pg.context.close()
    pg=page(scheme="light"); bg=pg.evaluate("getComputedStyle(document.body).backgroundColor"); t("light: light background", sum(map(int,re.findall(r"\d+",bg)[:3]))>600, bg); pg.context.close()
    # tap targets
    pg=page(w=375); sizes=pg.evaluate("""()=>({pick:document.getElementById('pickBtn').offsetHeight, share:document.getElementById('shareBtn').offsetHeight, head:document.querySelector('.place-head').offsetHeight, sum:document.querySelector('#fixed summary, .fixed summary').offsetHeight})""")
    t("tap targets: pick/head/summary >=44, share >=40", sizes["pick"]>=44 and sizes["head"]>=44 and sizes["sum"]>=44 and sizes["share"]>=40, sizes); pg.context.close()
    b.close()

fails=[r for r in res if not r[1]]
for n,ok,e in res: print(("PASS " if ok else "FAIL ")+n+("" if ok else f"   -> {e}"))
print(f"\n{len(res)-len(fails)}/{len(res)} passed")
sys.exit(1 if fails else 0)

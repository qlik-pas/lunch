#!/usr/bin/env python3
"""
Scrapes the Lund lunch sources and writes lt.json in the shape index.html
expects: { week, range, dates[5], generated, restaurants:[{name,url,menus:{Day:[...]}}] }

Sources:
  Restaurang Edison  https://restaurangedison.se/lunch/   (Elementor HTML)
  Bricks Eatery      https://brickseatery.se/lunch         (Elementor HTML, same template)
  Smaka på Kina      https://www.smakapakina.se/meny       (Wix HTML)
  Kantin             https://www.kantinlund.se/            (WP HTML)
  Troppo             https://www.troppo.se/lunch           (Webflow; one weekly menu)
  Matstudio Kungsmarken https://www.matstudiokungsmarken.se/lunch/ (WP HTML)
  Mat och Harmoni    https://www.matochharmoni.se/#dagens  (WP HTML)
  Linnea Basilika    https://www.linneabasilika.se/lund-brunnshog/ (WP HTML)
  Bryggan            https://mersmak.me/vara-stallen/bryggan/ (WP HTML)
  Inspira            https://restauranginspira.se/#lunch   (WP HTML)
  Eatery             menu.pej.io TV/kiosk board — client-rendered, needs
                     headless Chromium (see fetch_rendered_text)

Network libs (requests, beautifulsoup4, playwright) are imported lazily inside
the fetchers so the parsers can be unit-tested with no dependencies installed.
"""
import os, re, json, time, datetime

DAYS = ["Måndag", "Tisdag", "Onsdag", "Torsdag", "Fredag"]
UPPER = {d.upper(): d for d in DAYS}
MONTHS_SV = ["jan","feb","mar","apr","maj","jun","jul","aug","sep","okt","nov","dec"]
UA = {"User-Agent": "Mozilla/5.0 (lunch-scraper; +https://github.com/qlik-pas)"}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _lines(text):
    """Split to clean, non-empty lines with markdown/list noise stripped."""
    out = []
    for raw in text.splitlines():
        s = raw.strip()
        s = re.sub(r"^#{1,6}\s*", "", s)          # markdown headings
        s = re.sub(r"^[-*]\s+", "", s)            # list bullets
        if not s or s == "---":
            continue
        out.append(s)
    return out


def _empty():
    return {d: [] for d in DAYS}


# Edison says "Vecka 35", Bricks "Lunchmeny V36", Eatery's board "VECKA 39",
# Troppo "Lunch Week 43, 2026", Matstudio Kungsmarken "Dagens v 43".
# Restaurants publish the coming week mid-week, so the label is the only way to
# tell "next week, live early" from "this week's menu".
WEEK_LABEL = re.compile(
    r"vecka\s*(\d{1,2})\b|meny\s*v\.?\s*(\d{1,2})\b|"
    r"\bweek\s*(\d{1,2})\b|dagens\s+v\.?\s*(\d{1,2})\b", re.I)

WEEK_RANGE_END = re.compile(r"\s*[-–—]\s*(\d{1,2})\b")

# No "Vecka N" label? A day header with a date ("Måndag 19 okt") says the same.
DATED_DAY = re.compile(r"\b(?:måndag|tisdag|onsdag|torsdag|fredag)\s+(\d{1,2})\s+(" + "|".join(MONTHS_SV) + r")\b", re.I)

def claimed_week(text):
    """ISO week the page/PDF claims to be for, or None if it carries no label."""
    m = WEEK_LABEL.search(text)
    if not m:
        d = DATED_DAY.search(text)
        if not d:
            return None
        try:
            return datetime.date(datetime.date.today().year, MONTHS_SV.index(d.group(2).lower()) + 1,
                                 int(d.group(1))).isocalendar()[1]
        except ValueError:
            return None
    n = int(next(g for g in m.groups() if g))
    # A range ("Lunch week 43-44" — Troppo's menu runs Saturday to Friday) is
    # for the later week: that's the one whose Monday–Friday it covers.
    r = WEEK_RANGE_END.match(text, m.end())
    if r and int(r.group(1)) == n + 1:
        n = int(r.group(1))
    return n if 1 <= n <= 53 else None


# --------------------------------------------------------------------------- #
# parsers (pure: take extracted text, return {Day: [dishes]})
# --------------------------------------------------------------------------- #
PRICE = re.compile(r"\d{2,3}\s*:-")

# "Bonus:" marks a free extra the restaurant throws in on a given weekday
# (Bricks' Thursday äppelpaj, Eatery's pancakes). It rides in the day's dish
# list like the "Vegetariskt:" line does; index.html gives it its own marker.
TREAT = re.compile(r"\bbjuder\b", re.I)
_EMOJI_TAIL = re.compile(r"[\U0001F300-\U0001FAFF☀-➿️]+\s*$")

def _treat_text(line):
    """Reduce a 'Vi bjuder …' sentence to just the thing being offered."""
    s = re.sub(r".*?\bbjuder\b\s*", "", line, flags=re.I)      # drop up to "bjuder"
    s = re.sub(r"^(våra\s+lunchgäster\s+)?på\s+", "", s, flags=re.I)
    s = _EMOJI_TAIL.sub("", s)                                  # Eatery's "…! 🍬"
    return s.strip(" .!–-").strip() or line.strip()

def parse_elementor(text):
    """Edison & Bricks: dish is the line after each 'NNN:-' price label.

    Lines that aren't priced are normally ignored, except a 'Vi bjuder …'
    sentence under a day — that's the free weekday extra, kept as 'Bonus: …'.
    """
    menus = _empty()
    day = None
    want_dish = False
    for line in _lines(text):
        if line in DAYS:
            day, want_dish = line, False
            continue
        if PRICE.search(line):
            want_dish = True
            continue
        if want_dish and day:
            menus[day].append(line)
            want_dish = False
            continue
        if day and TREAT.search(line):
            menus[day].append("Bonus: " + _treat_text(line))
    return menus


KINA_DAY = re.compile(r"^(Måndag|Tisdag|Onsdag|Torsdag|Fredag)\b")
KINA_NUM = re.compile(r"^\d+\.\s*")

def parse_kina(text):
    """Smaka på Kina: numbered dishes under 'Måndag, 17 Aug'; 'kr' closes a day."""
    menus = _empty()
    day = None
    for line in _lines(text):
        m = KINA_DAY.match(line)
        if m:
            day = m.group(1)
            continue
        if day is None:
            continue
        if re.search(r"\bkr\b", line, re.I):        # e.g. "110 kr" -> day done
            day = None
            continue
        if KINA_NUM.match(line):
            dish = KINA_NUM.sub("", line).strip()
            if dish:
                menus[day].append(dish)
    return menus


def _sentence_case(name):
    """ALL-CAPS dish name -> normal case. A word with no vowel (BBQ, DNA, …)
    is left as-is instead of being lowered into nonsense."""
    words = name.split()
    out = []
    for i, w in enumerate(words):
        if not re.search(r"[AEIOUYÅÄÖ]", w, re.I):
            out.append(w)
        elif i == 0:
            out.append(w.capitalize())
        else:
            out.append(w.lower())
    return " ".join(out)

def parse_eatery(text):
    """Eatery's menu board (menu.pej.io, client-rendered — see
    fetch_rendered_text). Each day is a header, then three dish blocks: an
    ALL-CAPS name line followed by a description line. Some days add a
    'SWEET TUESDAY' / 'PANCAKE THURSDAY' block — also ALL-CAPS name + a
    '… vi bjuder på …' line — kept as a 'Bonus:' entry instead of a dish."""
    menus = _empty()
    lines = _lines(text)
    day = None
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if line.upper() in UPPER:
            day = UPPER[line.upper()]
            i += 1
            continue
        if day is None:                                # banner text before Måndag
            i += 1
            continue
        if TREAT.search(line):
            menus[day].append("Bonus: " + _treat_text(line))
            i += 1
            continue
        if line.isupper() and len(line) > 2:
            nxt = lines[i + 1] if i + 1 < n else ""
            if TREAT.search(nxt):                       # this caps line was a promo title
                i += 1
                continue
            if nxt and not nxt.isupper():                # name + description pair
                if len(menus[day]) < 4:
                    menus[day].append(f"{_sentence_case(line)} {nxt.strip()}")
                i += 2
                continue
        i += 1                                          # stray line, ignore
    return menus


# A day line is just the day name now ("Måndag"), with the dish on the
# following line(s). Older markup put a date + the dish on the line itself
# ("Måndag 24/8 <dish>"); the optional group keeps that working.
KANTIN_DAY = re.compile(
    r"^(Måndag|Tisdag|Onsdag|Torsdag|Fredag)\b\s*(?:\d{1,2}[/.]\d{1,2}\.?)?\s*(.*)$")
KANTIN_STOP = re.compile(
    r"^(Veckans vegetariska|Månadens alternativ|Dagens|Hitta till|Öppettider|"
    r"Köket stänger|Vår syn|Kontakt|Boka)", re.I)

def _kantin_clean(dish):
    dish = dish.replace("\xa0", " ")
    dish = re.sub(r"\s*–\s*", " – ", dish)      # normalise spacing around en-dashes
    return re.sub(r"\s{2,}", " ", dish).strip(" –").strip()

def parse_kantin(text):
    """Kantin: a bare 'Måndag' line, then that day's dish on the next line(s),
    plus 'Veckans vegetariska:' (dish on its own next line) shown for every day.

    Everything between a day header and the next header / section label is
    joined, so a dish wrapped across lines still comes through. 'Månadens
    alternativ:' and the closing sections are skipped."""
    menus = _empty()
    lines = _lines(text)

    veg = None
    for i, line in enumerate(lines):
        m = re.match(r"Veckans vegetariska:?\s*(.*)$", line, re.I)
        if m:
            veg = m.group(1).strip()
            if not veg and i + 1 < len(lines):   # dish sits on the next line
                veg = _kantin_clean(lines[i + 1])
            break

    def entry(dish):
        e = [_kantin_clean(dish)]
        if veg:
            e.append("Vegetariskt: " + veg)
        return e

    day, buf = None, ""

    def flush():
        nonlocal day, buf
        if day and buf.strip() and not menus[day]:    # first fill wins
            menus[day] = entry(buf)
        day, buf = None, ""

    for line in lines:
        m = KANTIN_DAY.match(line)
        if m and not menus[m.group(1)]:               # a fresh day header
            flush()
            day, buf = m.group(1), m.group(2).strip()
            continue
        if day is None:
            continue
        if KANTIN_STOP.match(line):
            flush()
            continue
        buf = f"{buf} {line}".strip() if buf else line
    flush()
    return menus


# Troppo serves one weekly lunch menu (a new one every Saturday) — the same
# three dishes Mon–Fri — laid out as "Name -", a description, an origin tag
# like "(Thai)", and an "or" between dishes. The page is Webflow and sprinkles
# zero-width joiners between blocks, which would otherwise count as lines.
def parse_troppo(text):
    menus = _empty()
    lines = _lines(re.sub(r"[\u200b-\u200d\ufeff]", "", text))
    start = next((i for i, l in enumerate(lines) if re.search(r"lunch\s+menu", l, re.I)), None)
    if start is None:
        return menus
    dishes = []
    for l in lines[start + 1:]:
        if re.match(r"find us", l, re.I):
            break
        if l.lower() == "or" or re.fullmatch(r"\([^)]*\)", l) or l == ".":
            continue                                   # separator / "(Thai)" tag / stray dot
        m = re.match(r"^(.+?)\s+-\s*$", l)
        if m:
            dishes.append([m.group(1)])                # "Pad Thai Chicken -" opens a dish
        elif dishes:
            dishes[-1].append(l)
    entries = []
    for name, *desc in dishes:
        d = re.sub(r"\s+([.,])", r"\1", " ".join(desc)).strip()
        entries.append(f"{name} – {d}" if d else name)
    for day in DAYS:
        menus[day] = list(entries)
    return menus


# Bryggan (Mersmak): "LUNCHMENY v. 44", prices and what's included, then
# Måndag…Fredag each followed by its dishes (a vegetarian and a meat dish, but
# the page doesn't label which is which), ending at "Med reservation…".
BRYGGAN_STOP = re.compile(r"^(med reservation|för allergener|vi har smarriga)", re.I)

def parse_bryggan(text):
    menus = _empty()
    lines = _lines(text)
    start = next((i for i, l in enumerate(lines) if re.match(r"lunchmeny\b", l, re.I)), None)
    if start is None:
        return menus
    day = None
    for l in lines[start + 1:]:
        if BRYGGAN_STOP.match(l):
            break
        if l in DAYS:
            day = l
        elif day:
            menus[day].append(l)
    return menus


# Inspira (Medicon Village): "Lunch", "vecka 44", a row of day tabs, then each
# day with four lines "Green | Dish" / "Local | …" / "Asia | …" / "World | …",
# each followed by a garnish line "x | y & z". Green is the vegetarian line.
INSPIRA_DISH = re.compile(r"^(green|local|asia|world)\s*\|\s*(.+)$", re.I)

def parse_inspira(text):
    menus = _empty()
    day, last = None, None
    for l in _lines(text):
        if re.fullmatch(r"konferens", l, re.I) and day:
            break
        if l in DAYS:
            day, last = l, None
            continue
        m = INSPIRA_DISH.match(l)
        if day and m:
            dish = m.group(2).strip()
            menus[day].append(("Vegetariskt: " if m.group(1).lower() == "green" else "") + dish)
            last = len(menus[day]) - 1
        elif day and last is not None:
            garnish = re.sub(r"\s*\|\s*", ", ", l).strip()
            menus[day][last] += f" – {garnish}"
            last = None
    return menus


# Matstudio Kungsmarken: "Dagens v 43", then Måndag…Fredag each followed by
# that day's dish (sometimes wrapped over two lines), then "Veckans gröda" —
# the vegetarian dish, shown under every day like Kantin's. The à la carte
# list further down is permanent and ignored.
MATSTUDIO_STOP = re.compile(
    r"^(Veckans gröda|Alla rätter|Varmt välkomna|A LA CARTE|Kontakt)", re.I)

def parse_matstudio(text):
    menus = _empty()
    lines = _lines(text)
    veg = ""
    for i, line in enumerate(lines):
        if re.match(r"Veckans gröda", line, re.I):
            parts = []
            for nxt in lines[i + 1:]:
                if MATSTUDIO_STOP.match(nxt):
                    break
                parts.append(nxt)
            veg = _kantin_clean(" ".join(parts))
            break
    day, buf = None, []

    def flush():
        nonlocal day, buf
        if day and buf and not menus[day]:             # first fill wins
            menus[day] = [_kantin_clean(" ".join(buf))] + (["Vegetariskt: " + veg] if veg else [])
        day, buf = None, []

    for line in lines:
        if line in DAYS and not menus[line]:
            flush()
            day = line
        elif day is None:
            continue
        elif MATSTUDIO_STOP.match(line):
            flush()
        else:
            buf.append(line)
    flush()
    return menus



# Mat och Harmoni: "Dagens rätt vecka 43", then Måndag…Fredag each followed by
# that day's three dishes, one per line. "Veckans pasta/sallad" and the buffets
# further down are weekly/permanent extras and ignored.
MATHARMONI_STOP = re.compile(r"^(Veckans pasta|Veckans sallad|Buffé)", re.I)

def parse_matochharmoni(text):
    menus = _empty()
    lines = _lines(text)
    start = next((i for i, l in enumerate(lines) if re.match(r"Dagens rätt", l, re.I)), None)
    if start is None:
        return menus
    day = None
    for l in lines[start + 1:]:
        if MATHARMONI_STOP.match(l):
            break
        if l in DAYS and not menus[l]:
            day = l
        elif day:
            menus[day].append(l)
    return menus


# Linnea Basilika: a lunch buffet whose hot dishes rotate daily. "Måndag 19 okt"
# header, then one dish per line, until the "Lunchbuffén serveras …" blurb.
LINNEA_DAY = re.compile(r"^(Måndag|Tisdag|Onsdag|Torsdag|Fredag)\s+\d{1,2}\s+\w{3}\b", re.I)

def parse_linnea(text):
    menus = _empty()
    day = None
    for l in _lines(text):
        m = LINNEA_DAY.match(l)
        if m:
            day = m.group(1).capitalize()
        elif day and re.match(r"Lunchbuffén serveras", l, re.I):
            break
        elif day:
            menus[day].append(l)
    return menus


# --------------------------------------------------------------------------- #
# fetchers (network; deps imported here)
# --------------------------------------------------------------------------- #
def fetch_html_text(url):
    import requests
    from bs4 import BeautifulSoup
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text("\n")


# Eatery moved its menu off a weekly PDF onto a TV/kiosk display board built
# as a client-rendered app (menu.pej.io) — the data streams in over Firestore,
# so raw HTML never contains it. EATERY_MENU_URL overrides if the URL changes.
EATERY_MENU_URL = os.environ.get("EATERY_MENU_URL") or "https://menu.pej.io/ea/menus/lund"

def fetch_rendered_text(url, timeout=25):
    """Render a JS-only page in headless Chromium and return its visible text.
    Only Eatery needs this today; kept generic in case another source goes
    client-rendered too.

    The menu streams in over a live connection (Firestore), so "networkidle"
    never fires. Worse, the page renders in two steps: every day header shows
    up immediately with a "Saknar info" placeholder under it, then the real
    dishes replace those placeholders a moment later — so waiting for the day
    names alone (or a single fixed sleep) reliably grabs the placeholder page
    instead. Poll until the placeholder text is gone, or the timeout runs out
    and we return whatever's there — parse_eatery/build() already treat a bad
    scrape as a transient failure and fall back to the previous good menu."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(user_agent=UA["User-Agent"])
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            deadline = time.monotonic() + timeout
            text = ""
            while time.monotonic() < deadline:
                text = page.inner_text("body")
                ready = ("saknar info" not in text.lower()
                         and all(d.upper() in text.upper() for d in DAYS))
                if ready:
                    break
                page.wait_for_timeout(500)
            return text
        finally:
            browser.close()


# --------------------------------------------------------------------------- #
# assembly
# --------------------------------------------------------------------------- #
def week_info(today=None):
    today = today or datetime.date.today()
    week = today.isocalendar()[1]
    monday = today - datetime.timedelta(days=today.weekday())
    dates = [(monday + datetime.timedelta(days=i)).isoformat() for i in range(5)]
    friday = monday + datetime.timedelta(days=4)
    rng = f"{monday.day}–{friday.day} {MONTHS_SV[monday.month - 1]}"
    return week, dates, rng


SOURCES = [
    # name, public url, parser, fetch-kind   —   order here drives the page order
    ("Bricks Eatery",     "https://brickseatery.se/lunch",      parse_elementor, "html"),
    ("Eatery",            "https://www.eatery.se/lund/lunchmeny", parse_eatery,  "rendered"),
    ("Smaka på Kina",     "https://www.smakapakina.se/meny",    parse_kina,      "html"),
    ("Restaurang Edison", "https://restaurangedison.se/lunch/", parse_elementor, "html"),
    ("Kantin",            "https://www.kantinlund.se/",         parse_kantin,    "html"),
    ("Troppo",            "https://www.troppo.se/lunch",        parse_troppo,    "html"),
    ("Matstudio Kungsmarken", "https://www.matstudiokungsmarken.se/lunch/", parse_matstudio, "html"),
    ("Mat och Harmoni",   "https://www.matochharmoni.se/#dagens", parse_matochharmoni, "html"),
    ("Linnea Basilika",   "https://www.linneabasilika.se/lund-brunnshog/", parse_linnea, "html"),
    ("Bryggan",           "https://mersmak.me/vara-stallen/bryggan/", parse_bryggan, "html"),
    ("Inspira",           "https://restauranginspira.se/#lunch", parse_inspira,   "html"),
]

# One menu for the whole week, the same every day. lt.json marks these so the
# page shows them as full cards instead of demoting "same every day" to the
# collapsed "Meny inte uppdaterad" list (that rule is for places with no real daily menu).
WEEKLY = {"Troppo"}

def _entry(name, url, menus, closed=False):
    e = {"name": name, "url": url, "menus": menus}
    if name in WEEKLY:
        e["weekly"] = True
    if closed:
        e["closed"] = True
    return e


# --------------------------------------------------------------------------- #
# Closed weeks
# --------------------------------------------------------------------------- #
# A place that is shut for the week publishes no menu, which used to look like a
# broken parser (an `errors` line plus a pointless Gemini call). Two ways in:
#   1. closed.json — {"2026-W44": ["Smaka på Kina"]}, edited by hand. Wins always.
#   2. The page itself says so. Only consulted when the parser found 0 dishes,
#      and only on phrases about being shut for a period — a bare "stängt" is
#      too often "Lör–sön stängt" in the opening hours.
CLOSED_RE = re.compile(
    r"\b(?:håller|har|är)\s+(?:\w+\s+)?stäng(?:t|d|da)\b"
    r"|semesterstängt"
    r"|stängt\s+(?:denna|hela|i\s+dag|idag|under|vecka|v\.?\s*\d|för|pga|p\.\s?g\.\s?a|tills|t\.\s?o\.\s?m|fr\.?o\.?m)"
    r"|closed\s+(?:this|for|until|all)",
    re.I)


def week_key(today=None):
    y, w, _ = (today or datetime.date.today()).isocalendar()
    return f"{y}-W{w:02d}"


def load_closed(path="closed.json"):
    """{"2026-W44": ["Smaka på Kina"], ...}; a missing or broken file is just empty."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {k: set(v) for k, v in data.items() if isinstance(v, list)}
    except (OSError, ValueError, AttributeError):
        return {}


def says_closed(text):
    return bool(CLOSED_RE.search(text or ""))


# --------------------------------------------------------------------------- #
# English text for the page's "Kopiera dagens utbud" button
# --------------------------------------------------------------------------- #
# Each restaurant gets an `en` field in lt.json — the same shape as `menus`
# (day -> list, aligned 1:1 with the Swedish entries) but as short English dish
# names, ready to paste into Slack. It's produced here, at scrape time, so the
# button can copy synchronously (browsers only allow a clipboard write inside
# the click) and the page never calls a model itself.
#
# Translations are cached: a restaurant whose Swedish menus are unchanged keeps
# its `en`, so a model is only called when a menu actually changes (normally
# Monday). Provider: Google Gemini (free tier) with a GEMINI_API_KEY repo secret.
# (GitHub Models, used before, was retired 2026-07-30.)
# Any failure just leaves `en` off — the button falls back to the Swedish text.
TRANSLATE_PROMPT = """You turn restaurant lunch-menu lines (Swedish, sometimes English, sometimes with Chinese characters) into short English dish names for a Slack message listing today's lunch.

Rules:
- One output line per input line, same order. Never merge, drop, or add lines.
- Keep it short: the dish's essence in roughly 3-8 words, like "Slow-baked beef chuck with aioli & sage jus", "Fried herring & mash", "Oven pancake with smoked celeriac". Drop long garnish and sauce lists; keep what defines the dish.
- Use "&" instead of "and". Keep proper names and well-known foreign dish names (Mapo tofu, Tandoori chicken, raggmunk with a short gloss).
- Drop Chinese characters. Don't add words that aren't in the dish.
- A line starting "Vegetariskt:" becomes "Vegetarian: ..."; "Bonus:" stays "Bonus: ...".
- The input is JSON {"<restaurant>": {"<day>": ["line", ...], ...}, ...}. Reply with JSON only, the same structure: exactly the restaurant names, day keys and list lengths you were given."""


# The page's English view shows the whole dish, so it gets its own, faithful
# translation (`en_full`) next to the short Slack names (`en`). Same cache and
# batching; one more model call when a menu changes. If it fails, the page
# falls back to `en`, then to the Swedish line.
FULL_TRANSLATE_PROMPT = """You translate restaurant lunch-menu lines (Swedish, sometimes English, sometimes with Chinese characters) into English for the English version of a lunch web page.

Rules:
- One output line per input line, same order. Never merge, drop, or add lines.
- Translate the whole line faithfully: every component, side, sauce and garnish. Don't shorten or summarise, and don't add anything that isn't there.
- Keep the line's own punctuation and separators (commas, " – ", " / ", " | "). Keep "&" where the original has it; otherwise write "and".
- Keep proper names and well-known dish names (Mapo tofu, Pad Thai, Wallenbergare, raggmunk, kalops, Västerbotten); you may add a short gloss in parentheses for a Swedish classic, e.g. "Raggmunk (potato pancakes)".
- Drop Chinese characters. A line already in English stays as it is.
- A line starting "Vegetariskt:" becomes "Vegetarian: ..."; "Bonus:" stays "Bonus: ...".
- The input is JSON {"<restaurant>": {"<day>": ["line", ...], ...}, ...}. Reply with JSON only, the same structure: exactly the restaurant names, day keys and list lengths you were given."""


def _reply(r):
    """The response body as JSON, or an error that says what actually came back
    (an endpoint that answers 200 "OK" in text/plain would otherwise surface as
    a baffling JSONDecodeError)."""
    if not r.ok:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:150]!r}")
    try:
        return r.json()
    except ValueError:
        raise RuntimeError(f"non-JSON reply ({r.headers.get('content-type')}): {r.text[:150]!r}")


# The free tier is rate-limited and a model can be briefly overloaded (503), so a
# call retries with a pause and then falls through to the next model. One shared
# time budget keeps a bad day from stalling the whole scrape.
GEMINI_MODELS = ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-2.5-flash"]
TRANSLATE_BUDGET = 90           # seconds of waiting allowed per scraper run
_waited = 0.0


def _retry_delay(r, attempt):
    """Seconds to wait before retrying: Google's own hint ("retryDelay": "17s") if given."""
    m = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', r.text)
    return min(float(m.group(1)) + 1 if m else 5 * 2 ** attempt, 60)


def _llm_json(system, payload):
    """One JSON-in / JSON-out model call; returns the parsed reply."""
    import requests
    global _waited
    user = json.dumps(payload, ensure_ascii=False)
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("no GEMINI_API_KEY")
    models = [os.environ["TRANSLATE_MODEL"]] if os.environ.get("TRANSLATE_MODEL") else GEMINI_MODELS
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}}
    problems = []                       # one line per model that didn't deliver
    for model in models:
        for attempt in range(3):
            try:
                r = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    timeout=100, headers={"x-goog-api-key": key}, json=body)
            except requests.exceptions.Timeout:        # a slow model: the next one may be quicker
                problems.append(f"{model}: timed out")
                break
            if r.ok:
                text = _reply(r)["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(re.search(r"\{.*\}", text, re.S).group(0))
            if r.status_code == 404:                    # model id gone: try the next one
                problems.append(f"{model}: HTTP 404")
                break
            if r.status_code not in (429, 500, 503):    # bad key / bad request: no model will fix it
                _reply(r)
            problems.append(f"{model}: HTTP {r.status_code}")
            wait = _retry_delay(r, attempt)
            if attempt == 2 or _waited + wait > TRANSLATE_BUDGET:
                break                                   # out of retries or time: next model, no pointless sleep
            _waited += wait
            time.sleep(wait)
    raise RuntimeError("no model answered — " + "; ".join(problems[-4:]))


def _with_translations(restaurants, old, translate=_llm_json, field="en", prompt=None):
    """Attach `field` ("en": short Slack names, "en_full": the whole dish) to each
    restaurant — reused from `old` when its menus are unchanged, otherwise freshly
    translated. Never raises. Everything that needs translating goes in ONE model
    call (the free tier rate-limits per request)."""
    prompt = prompt or (FULL_TRANSLATE_PROMPT if field == "en_full" else TRANSLATE_PROMPT)
    prev = {r["name"]: r for r in old.get("restaurants", [])}
    force = bool(os.environ.get("FORCE_TRANSLATE"))
    cached, fresh, failed, todo = [], [], [], {}
    for r in restaurants:
        src = {d: v for d, v in r["menus"].items() if v}
        if not src:
            continue
        p = prev.get(r["name"])
        if p and p.get(field) and p.get("menus") == r["menus"] and not force:
            r[field] = p[field]
            cached.append(r["name"])
        else:
            # a weekly menu is the same list every day — translate it once
            todo[r["name"]] = (r, {"Måndag": src["Måndag"]} if r.get("weekly") else src)

    got_all, call_error = {}, None
    if todo:
        try:
            got_all = translate(prompt, {n: ask for n, (_, ask) in todo.items()})
        except Exception as e:
            call_error = f"{type(e).__name__}: {str(e)[:160]}"
    for name, (r, ask) in todo.items():
        try:
            if call_error:
                raise ValueError(call_error)
            got = got_all.get(name) or {}
            if r.get("weekly") and "Måndag" in got:
                got = {d: got["Måndag"] for d in r["menus"] if r["menus"][d]}
            en = {}
            for d, lines in {d: v for d, v in r["menus"].items() if v}.items():
                out = got.get(d)
                if (isinstance(out, list) and len(out) == len(lines)
                        and all(isinstance(x, str) and x.strip() for x in out)):
                    en[d] = [x.strip() for x in out]
            if not en:
                raise ValueError("reply didn't match the menu shape")
            r[field] = en
            fresh.append(name)
        except Exception as e:
            failed.append(name if call_error else f"{name} ({e})")
            p = prev.get(name)
            if p and p.get(field) and p.get("menus") == r["menus"]:
                r[field] = p[field]                  # a failed *re*translate mustn't wipe good text
    print(f"English ({field}): {len(cached)} cached, {len(fresh)} translated"
          + (f", {len(failed)} failed: {failed}" if failed else "")
          + (f" — {call_error}" if call_error else ""))
    return restaurants


# --------------------------------------------------------------------------- #
# Gemini as a fallback parser
# --------------------------------------------------------------------------- #
# When a restaurant redesigns its page the hand-written parser finds 0 dishes.
# Rather than showing last week's menu (or nothing) until someone fixes it, the
# page text is handed to Gemini to read the menu out. Nothing is trusted blindly:
# every dish must be made of words that actually appear on the page, so an
# invented menu is rejected and the old "kept previous" fallback takes over.
EXTRACT_PROMPT = """You read the text of a Swedish restaurant's lunch web page and extract this week's lunch menu.

- Input is JSON {"restaurant": ..., "page_text": ...}. Reply with JSON only: {"Måndag": [...], "Tisdag": [...], "Onsdag": [...], "Torsdag": [...], "Fredag": [...]}.
- One string per dish, copied from the page in its original language and wording. Join a dish that wraps over several lines; drop prices, allergen codes and opening hours. Never translate, invent or complete dishes.
- Only the lunch of the day / week. Ignore à la carte menus, standing buffets, drinks, catering and take-away lists.
- The page's weekly vegetarian option gets the prefix "Vegetariskt: ", a free extra (dessert, pancakes) the prefix "Bonus: ".
- If one menu applies to the whole week, repeat it under every day. A day without dishes gets [].
- If the page has no lunch menu at all, reply with all five days empty."""

PAGE_TEXT_LIMIT = 30000         # characters sent; the menu is always far smaller


def _words(s):
    return set(re.findall(r"[0-9a-zåäöéèü]+", s.lower()))


def _llm_extract_menus(name, text, call=None):
    """{Day: [dish]} read from the page text by Gemini, or ValueError if the
    answer is unusable. `call` defaults to `_llm_json` (injectable for tests)."""
    page = "\n".join(_lines(text))[:PAGE_TEXT_LIMIT]
    if not page:
        raise ValueError("empty page text")
    got = (call or _llm_json)(EXTRACT_PROMPT, {"restaurant": name, "page_text": page})
    page_words = _words(page)
    menus, kept, dropped = _empty(), 0, 0
    for day in DAYS:
        dishes = got.get(day) if isinstance(got, dict) else None
        for d in dishes if isinstance(dishes, list) else []:
            if not isinstance(d, str) or not d.strip():
                continue
            w = _words(re.sub(r"^(vegetariskt|bonus)\s*:\s*", "", d, flags=re.I))
            if w and len(w & page_words) / len(w) >= 0.85:
                menus[day].append(re.sub(r"\s+", " ", d).strip()); kept += 1
            else:
                dropped += 1
    if not kept:
        raise ValueError("Gemini found no menu on the page")
    if dropped > kept / 3:
        raise ValueError(f"Gemini's answer didn't match the page ({dropped} of {kept + dropped} dishes not found in it)")
    return menus


def _load_old():
    try:
        with open("lt.json", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _previous_menus(old, week):
    """Last run's menus keyed by name, so a flaky source keeps its data."""
    if old.get("week") != week:                      # stale week -> don't reuse
        return {}
    return {r["name"]: r["menus"] for r in old.get("restaurants", [])
            if any(r.get("menus", {}).values())}


def build():
    week, dates, rng = week_info()
    old = _load_old()
    prev = _previous_menus(old, week)
    restaurants, errors = [], []
    closed_now = load_closed().get(week_key(), set())
    for name, url, parser, kind in SOURCES:
        if name in closed_now:                       # closed.json: don't even fetch
            restaurants.append(_entry(name, url, _empty(), closed=True))
            continue
        try:
            if kind == "rendered":
                text = fetch_rendered_text(EATERY_MENU_URL)
            else:
                text = fetch_html_text(url)
            menus = parser(text)
            if not any(menus.values()) and says_closed(text):
                restaurants.append(_entry(name, url, _empty(), closed=True))
                continue
            if not any(menus.values()):
                try:
                    menus = _llm_extract_menus(name, text)
                except Exception as e:
                    raise ValueError(f"parsed 0 dishes (Gemini fallback: {str(e)[:120]})")
                errors.append(f"{name}: parser found 0 dishes — menu read by Gemini instead, fix the parser")
            cw = claimed_week(text)
            if cw is not None and cw != week:
                raise ValueError(f"sidan visar vecka {cw}, väntar på vecka {week}")
            restaurants.append(_entry(name, url, menus))
        except Exception as e:                       # one bad source ≠ empty file
            kept = prev.get(name)
            errors.append(f"{name}: {e}" + (" (kept previous)" if kept else ""))
            restaurants.append(_entry(name, url, kept or _empty()))

    _with_translations(restaurants, old)                     # short names, for the copy button
    _with_translations(restaurants, old, field="en_full")    # whole dishes, for the page's EN view

    out = {
        "week": week, "range": rng, "dates": dates,
        "generated": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "restaurants": restaurants,
    }
    if errors:
        out["errors"] = errors

    # Only rewrite when the menus themselves changed, so each commit in the
    # file's history marks a real menu update (not just a new timestamp).
    if old.get("restaurants") == restaurants and old.get("week") == week:
        print(f"lt.json oförändrad — vecka {week}, "
              f"{len(errors)} fel" + (f": {errors}" if errors else ""))
        return old

    with open("lt.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Wrote lt.json — vecka {week}, {len(restaurants)} ställen"
          + (f", {len(errors)} fel: {errors}" if errors else ""))
    return out


if __name__ == "__main__":
    build()

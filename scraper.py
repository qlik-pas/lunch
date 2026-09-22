#!/usr/bin/env python3
"""
Scrapes the five Lund lunch sources and writes lt.json in the shape index.html
expects: { week, range, dates[5], generated, restaurants:[{name,url,menus:{Day:[...]}}] }

Sources:
  Restaurang Edison  https://restaurangedison.se/lunch/   (Elementor HTML)
  Bricks Eatery      https://brickseatery.se/lunch         (Elementor HTML, same template)
  Smaka på Kina      https://www.smakapakina.se/meny       (Wix HTML)
  Kantin             https://www.kantinlund.se/            (WP HTML)
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


# Edison says "Vecka 35", Bricks "Lunchmeny V36", Eatery's PDF "MENY V35".
# Restaurants publish the coming week mid-week, so the label is the only way to
# tell "next week, live early" from "this week's menu".
WEEK_LABEL = re.compile(r"vecka\s*(\d{1,2})\b|meny\s*v\.?\s*(\d{1,2})\b", re.I)

def claimed_week(text):
    """ISO week the page/PDF claims to be for, or None if it carries no label."""
    m = WEEK_LABEL.search(text)
    if not m:
        return None
    n = int(m.group(1) or m.group(2))
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
]


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
    for name, url, parser, kind in SOURCES:
        try:
            if kind == "rendered":
                text = fetch_rendered_text(EATERY_MENU_URL)
            else:
                text = fetch_html_text(url)
            menus = parser(text)
            if not any(menus.values()):
                raise ValueError("parsed 0 dishes")
            cw = claimed_week(text)
            if cw is not None and cw != week:
                raise ValueError(f"sidan visar vecka {cw}, väntar på vecka {week}")
            restaurants.append({"name": name, "url": url, "menus": menus})
        except Exception as e:                       # one bad source ≠ empty file
            kept = prev.get(name)
            errors.append(f"{name}: {e}" + (" (kept previous)" if kept else ""))
            restaurants.append({"name": name, "url": url,
                                "menus": kept or _empty()})

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

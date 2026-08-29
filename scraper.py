#!/usr/bin/env python3
"""
Scrapes the five Lund lunch sources and writes lt.json in the shape index.html
expects: { week, range, dates[5], generated, restaurants:[{name,url,menus:{Day:[...]}}] }

Sources:
  Restaurang Edison  https://restaurangedison.se/lunch/   (Elementor HTML)
  Bricks Eatery      https://brickseatery.se/lunch         (Elementor HTML, same template)
  Smaka på Kina      https://www.smakapakina.se/meny       (Wix HTML)
  Eatery             weekly PDF linked from eatery.se/anlaggningar/lund

Network libs (requests, beautifulsoup4, pdfminer.six) are imported lazily inside
the fetchers so the parsers can be unit-tested with no dependencies installed.
"""
import os, io, re, json, datetime

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

def parse_elementor(text):
    """Edison & Bricks: dish is the line after each 'NNN:-' price label."""
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


def _is_eatery_footer(line):
    if line.isupper() and len(line) > 3:            # GENERÖS…, LUNCH, LUND, MENY V34
        return True
    return bool(re.match(r"(Med reservation|10\s*%)", line, re.I))

def _is_eatery_promo(line):
    return bool(re.match(r"(Sweet\s|Pancake\s)", line, re.I)) or "bjuder" in line.lower()

def parse_eatery(text):
    """Eatery PDF: 3 dishes under each UPPERCASE day; skip promo/footer lines."""
    menus = _empty()
    day = None
    for line in _lines(text):
        if line.upper() in UPPER:
            day = UPPER[line.upper()]
            continue
        if day is None:
            continue
        if _is_eatery_footer(line):
            day = None
            continue
        if _is_eatery_promo(line):
            continue
        if len(menus[day]) < 4:
            menus[day].append(line)
    return menus


KANTIN_DAY = re.compile(r"^(Måndag|Tisdag|Onsdag|Torsdag|Fredag)\b\s*\d{1,2}[/.]\d{1,2}\.?\s*(.*)$")
KANTIN_STOP = re.compile(r"^(Veckans vegetariska|Månadens alternativ|Dagens|Hitta till|Öppettider|Kontakt|Boka)", re.I)

def _kantin_clean(dish):
    dish = re.sub(r"\s*–\s*", " – ", dish)      # normalise spacing around en-dashes
    return re.sub(r"\s{2,}", " ", dish).strip(" –").strip()

def parse_kantin(text):
    """Kantin: 'Måndag 24/8 <dish>' per day, plus the weekly vegetarian shown daily.

    The live markup routinely breaks one day's dish across several lines — even
    mid-word — so everything after a day header is concatenated (no separator)
    until the next day header or a section label."""
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
        if day and buf.strip():
            menus[day] = entry(buf)
        day, buf = None, ""

    for line in lines:
        m = KANTIN_DAY.match(line)
        if m:
            flush()
            day, buf = m.group(1), m.group(2).strip()
            continue
        if day is None:
            continue
        if KANTIN_STOP.match(line):
            flush()
            continue
        buf += line.strip()
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


def fetch_pdf_text(url):
    import requests
    from pdfminer.high_level import extract_text
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    return extract_text(io.BytesIO(r.content))


EATERY_MENU_PAGE = "https://www.eatery.se/anlaggningar/lund"

def eatery_pdf_url(week):
    """Discover the current Swedish lunch PDF by scraping Eatery's Lund page.

    Both the directory and the weekly filename are unpredictable (the file for
    week 35 was 'Lund_sv_V35indd.pdf'), so the URL is never constructed. Set
    EATERY_PDF_URL to override when the scrape can't find it."""
    override = os.environ.get("EATERY_PDF_URL")
    if override:
        return override

    import requests
    r = requests.get(EATERY_MENU_PAGE, headers=UA, timeout=30)
    r.raise_for_status()
    urls = re.findall(r'https?://[^"\'\s]+?\.pdf', r.text, re.I)
    seen, cands = set(), []
    for u in urls:
        u = u.split("?")[0]
        if u not in seen:
            seen.add(u)
            cands.append(u)

    def score(u):
        low = u.lower()
        s = 0
        if "lund_sv" in low:
            s += 10
        if re.search(rf"v0*{week}(?!\d)", low):
            s += 5
        if "_eng" in low or "cafe" in low or "café" in low or "catering" in low:
            s -= 20
        return s

    best = max(cands, key=score, default=None)
    if best is None or score(best) < 10:
        raise ValueError(f"no Swedish lunch PDF link on {EATERY_MENU_PAGE}")
    return best


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
    # name, public url, parser, fetch-kind
    ("Restaurang Edison", "https://restaurangedison.se/lunch/", parse_elementor, "html"),
    ("Bricks Eatery",     "https://brickseatery.se/lunch",      parse_elementor, "html"),
    ("Smaka på Kina",     "https://www.smakapakina.se/meny",    parse_kina,      "html"),
    ("Kantin",            "https://www.kantinlund.se/",         parse_kantin,    "html"),
    ("Eatery",            "https://www.eatery.se/lund/lunchmeny", parse_eatery,  "pdf"),
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
            if kind == "pdf":
                text = fetch_pdf_text(eatery_pdf_url(week))
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

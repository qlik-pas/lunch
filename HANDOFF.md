# Handoff — lunch (2026-08-29)

Arbete gjort i en Prodia-session av misstag; flyttat hit. Repo: `qlik-pas/lunch`.

## Gjort (branch `fix-kantin-veg-line`)
- **scraper.py / Kantin veg-rad:** "Veckans vegetariska:" och rätten ligger på
  separata rader live — parsern faller nu tillbaka till nästa rad.
- **scraper.py / Kantin dagsrätter:** livemarkupen bryter en rätt över flera
  rader (mitt i ord), så rader efter en dag-rubrik konkateneras nu tills nästa
  rubrik/sektion. Fixade den trunkerade måndagsrätten.
- **lunch.html:** ombyggd design (kort med badge per ställe, sticky dag-rail,
  veg-chip, ljus/mörk palett). Tog bort gamla `mudhead.se`-resterna. Sidan
  läser sitt eget `lt.json` nu. Snapshot vecka 35.
- CLAUDE.md borttagen ur git + gitignore:ad. `.venv/` gitignore:ad.

## Gjort 2026-08-29 (fortsättning)
- **PR öppnad:** https://github.com/qlik-pas/lunch/pull/1 (`fix-kantin-veg-line` → `main`).
- **Eatery:** `scraper.py` konstruerar inte längre PDF-URL:en. Den skrapas nu
  från `eatery.se/anlaggningar/lund` (poäng på `lund_sv` + veckonummer).
  Veckans fil hette `Lund_sv_V35indd.pdf` — därför 404:ade den gamla gissningen.
  `EATERY_PDF_URL` överstyr fortfarande.
- **Robusthet:** `build()` behåller förra körningens meny för en källa som
  failar (samma vecka), märkt "(kept previous)" i `errors`. Utlöst av att
  Edison/Bricks då och då ger bot-blockerad HTML till CI-runnern.
- **GitHub Action verifierad:** körd manuellt mot branchen 2x. Scrape + commit
  fungerar; Edison/Bricks failade server-side men behöll sin data tack vare
  fallbacken. Alla 5 ställen fyllda i committad `lt.json`.

## Kvar / nästa
- **Merga PR #1.**
- Edison/Bricks blockeras ibland från GitHub-runnern ("parsed 0 dishes").
  Fallbacken maskerar det, men menyn kan bli inaktuell om det håller i sig —
  kolla `errors`-nyckeln i `lt.json`. Ev. behövs annan User-Agent / proxy.
- `parse_eatery` delar en PDF-radbruten rätt i två poster vissa dagar (t.ex.
  onsdag). `< 4`-taket begränsar skadan. Pre-existerande.
- Workflow committar varje körning (nya `generated`-tidsstämpeln räcker) även
  utan menyändring — kosmetiskt.

## Testloop
    python3 -m venv .venv && .venv/bin/pip install requests beautifulsoup4 pdfminer.six
    .venv/bin/python scraper.py      # skriver lt.json
    python3 -m http.server 4173      # öppna http://localhost:4173/lunch.html

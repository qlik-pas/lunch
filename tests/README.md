# Tests

Run from the repo root, with the scraper's deps plus Playwright installed
(`pip install requests beautifulsoup4 playwright==1.63.0 && playwright install chromium`).

| Command | What it checks | Needs |
|---|---|---|
| `python tests/test_scraper.py` | week logic, parsers, translation cache and batching, the Gemini retry/model fallback, the extraction guard | nothing (offline, mocked) |
| `python tests/test_ui.py` | `index.html` in headless Chromium: days, weekend, fallbacks, classification, fixed list, roulette, copy button (text + links), layout, themes, tap targets | Chromium; reads the committed `lt.json` |
| `python tests/check_links.py` | every restaurant link still answers | internet |

Each prints one line per check and exits non-zero on any failure.
`test_ui.py` fakes the browser clock (a Wednesday, a Sunday), so it passes any day of the week.
A 503 from `check_links.py` can be a site that's really down — look in a browser before changing a link.

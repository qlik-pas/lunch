"""Network check: does every restaurant link still answer? Run by hand now and then.

    python tests/check_links.py

A 403/455/503 from a plain `requests` call is often bot-blocking, not a dead site;
the script retries with a browser User-Agent before reporting it.
"""
import os, re, json, sys, requests
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
urls = set(re.findall(r'url:\s*"(https?://[^"]+)"', html))
urls |= {r["url"] for r in json.load(open(os.path.join(ROOT, "lt.json")))["restaurants"]}
BROWSER = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36",
           "Accept-Language": "sv"}
bad = 0
for u in sorted(urls):
    try:
        code = requests.get(u, headers=BROWSER, timeout=20).status_code
    except requests.RequestException as e:
        code = type(e).__name__
    ok = code == 200
    bad += not ok
    print(("ok   " if ok else "FAIL ") + str(code), u)
sys.exit(1 if bad else 0)

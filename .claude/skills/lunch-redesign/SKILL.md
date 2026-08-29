---
name: lunch-redesign
description: >-
  Redesign the lunch page (index.html) in this repo. Use this whenever the user
  wants the lunch page to look different, nicer, cleaner, more modern, or wants
  to change its layout, colours, typography, spacing, day navigation, or overall
  feel — even phrased loosely ("sidan är inte snygg", "gör om designen", "kan vi
  fräscha upp den", "I don't love how it looks"). Start by interviewing the user
  about the visual direction with AskUserQuestion, then implement and verify.
  Do NOT use this for scraper.py, lt.json, the GitHub Action, or parsing bugs —
  only the presentation layer in index.html.
---

# Redesigning the lunch page

`index.html` is a single, self-contained, dependency-free page served on GitHub
Pages. It shows today's lunch for five Lund restaurants and lets you flip between
weekdays. The user thinks it could look better. Your job is to find out what
*they* want it to look like, then rebuild the presentation without breaking the
machinery underneath.

The most common failure here is skipping straight to code and producing another
competent-but-generic card layout. Don't. The interview is the point — a lunch
page someone checks every morning should feel like *theirs*.

## 1. Interview first

Before touching the file, run a short design interview with **AskUserQuestion**.
Look at the current `index.html` so your questions are grounded in what's there
now, then ask 4–7 questions across two calls. Adapt to their answers — if they
say "surprise me", ask fewer and lean on your own judgement.

Cover these axes (pick the ones that matter for their answers, phrase them
concretely, and offer an "as it is now" option where it helps them anchor):

- **Overall feeling** — what mood should it strike? e.g. calm & editorial /
  bold & playful / minimal & utilitarian / warm neighbourhood café / newspaper
  food section. Give 3–4 named directions with a one-line description each.
- **Density** — one restaurant at a time with room to breathe, or the whole
  day visible at a glance with tighter spacing?
- **What leads the page** — today's menus big and first, a single "pick of the
  day", or an even list of all places?
- **Day navigation** — keep the sticky segmented rail, switch to plain tabs,
  a dropdown, swipe, or just show the whole week stacked?
- **Colour** — warm earthy (current), fresh food greens, near-monochrome with
  one accent, per-restaurant colour coding, or a specific palette they name.
- **Typography** — a characterful display face (current is Bricolage Grotesque),
  clean system sans, a serif for warmth, or a specific font.
- **References** — any site, app, menu, or poster whose look they like. This one
  answer is worth more than the rest; ask it every time, as free text if needed.

Also confirm scope: a restyle of the current structure, or a free hand to change
layout and interaction too?

## 2. Know what must not break

The look is yours to change. This behaviour is not — it's why the page works
offline, loads instantly, and stays correct. Read
`references/contract.md` for the full data shape and edge cases; the essentials:

- **One file, no build, no dependencies.** Inline all CSS and JS. The only
  external resource the page may load is Google Fonts (`fonts.googleapis.com` /
  `fonts.gstatic.com`) — nothing else. Always give every web font a real
  fallback stack.
- **Data comes from `./lt.json`**, fetched with `cache: "no-store"` at boot.
  Shape: `{ week, range, dates[5], generated, restaurants:[{name, url,
  menus:{ "Måndag":[dish,…], … }}] }`. Keep the fetch and its shape.
- **The embedded snapshot stays.** If the fetch fails the page renders a copy of
  the data baked into the `<script>`. After redesigning, refresh that snapshot
  from the current `lt.json` (see step 3) so the fallback isn't stale.
- **Today-first.** On load, select the current weekday; on weekends show Monday
  with a "Helg" note. Mon–Fri only.
- **Swedish UI.** All visible strings in Swedish. Keep `<html lang="sv">`.
- **Five restaurants, per-weekday menus.** Two kinds of line get their own
  marker, kept separate from the pick-one lunch options: `Vegetariskt:` (Kantin's
  weekly veg option) and `På huset:` (a free weekday extra — Bricks' Thursday
  äppelpaj, Eatery's pancakes). Restaurants with no menu, or the identical menu
  every day, are demoted out of the main view — keep that distinction, however
  you style it.
- **Light and dark.** Both must be deliberate, not an afterthought. Update the
  two `<meta name="theme-color">` tags to match the new backgrounds.
- **Mobile-first and fast.** Most visits are on a phone at 08:30. No layout
  shift after the fetch resolves, comfortable tap targets, and it must read well
  from ~320px up.
- **Accessible.** Day switcher reachable by keyboard with visible focus, honour
  `prefers-reduced-motion`, real contrast in both themes.

## 3. Implement

Prefer keeping the data/render JavaScript (classification, `dishItem`, rail
building, boot/fetch) and changing the markup it emits plus the CSS. Rewrite the
JS too if the interview calls for a genuinely different interaction — just
re-check every item in `references/contract.md` afterwards.

Work in `index.html` directly. Keep the code at the current level of tidiness:
CSS custom properties for the palette, one `<style>` block, readable sections.

To refresh the fallback snapshot, run the scraper and copy `lt.json`'s contents
into the `let WEEK = {…}` object (drop the `generated` key, keep it compact):

```bash
python scraper.py            # writes lt.json for the current week
```

## 4. Verify before handing back

Serve it and look — don't just diff the CSS:

```bash
python -m http.server 4173   # then open http://localhost:4173/
```

Check, and tell the user you checked:

- Today's weekday is selected on load; clicking through all five days works.
- All five restaurants render; the `Vegetariskt:` and `På huset:` lines each
  have their own marker;
  demoted places (no menu / same daily) appear in their lesser slot.
- Light and dark both look intentional (toggle your OS or DevTools).
- Narrow viewport (~320–375px): no horizontal scroll, nothing clipped.
- Fallback path: temporarily rename `lt.json`, reload, confirm the embedded
  snapshot renders with a "Sparad meny" status, then restore it.
- `prefers-reduced-motion` kills the entrance animation.

Then take a screenshot of the result (both themes if you can) so the user sees
it without starting a server themselves.

## 5. Iterate

Expect 2–3 rounds. Show the result, ask what's off, adjust. Design feedback is
often "not quite" before it's "yes" — treat the first version as a proposal, not
a delivery.

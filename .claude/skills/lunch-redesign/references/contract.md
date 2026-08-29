# index.html — data contract & edge cases

Everything the redesign must keep working. The visual layer is free; this is not.

## Data source

- `fetch("lt.json", { cache: "no-store" })` at boot. Same directory as the page.
- On success with a non-empty `restaurants` array, replace the in-memory data
  and re-render. On any failure (network, non-200, empty), keep the embedded
  snapshot and show a "saved menu" status instead of "Live".

## JSON shape

```jsonc
{
  "week": 35,                          // ISO week number (int)
  "range": "24–28 aug",                // human date range for the week
  "dates": ["2026-08-24", …],          // 5 ISO dates, Mon–Fri
  "generated": "2026-08-29T12:44:19+02:00",  // when the scrape ran; may be absent
  "restaurants": [
    {
      "name": "Restaurang Edison",     // stable display name (used for colour keys)
      "url": "https://…",              // linked from the restaurant title
      "menus": {
        "Måndag":  ["dish 1", "dish 2", "dish 3"],
        "Tisdag":  [ … ],
        "Onsdag":  [ … ],
        "Torsdag": [ … ],
        "Fredag":  [ … ]
      }
    }
    // exactly these five, in the order scraper.py's SOURCES list defines:
    // "Bricks Eatery", "Eatery", "Smaka på Kina", "Restaurang Edison", "Kantin"
    // (render them in the order they arrive — don't re-sort)
  ],
  "errors": ["Eatery: …"]              // optional; present when a source failed
}
```

- A day's menu can be `[]` (that restaurant has no dishes that day).
- Dish counts vary 0–4 per day per restaurant.
- Dishes are plain strings. Smaka på Kina appends Chinese in parens:
  `"Gongbao kyckling (宫保鸡丁)"`. Some strings have stray double spaces.
- Kantin includes one line per day starting `Vegetariskt: ` — its weekly
  vegetarian option, repeated on every weekday. Render it visually distinct
  (currently a "Grönt" chip). Match case-insensitively: `/^vegetarisk[t]?\s*:\s*/i`.
- Some days carry a line starting `Bonus: ` — a free weekday extra the
  restaurant throws in (Bricks' Thursday äppelpaj, Eatery's Tuesday sweet /
  Thursday pancakes). Also a magic-prefixed entry in the day's list, rendered
  with its own marker (currently a "Bonus" chip). Match `/^bonus\s*:\s*/i`.
  Keep it visually separate from the pick-one lunch options — it's a freebie,
  not a choice.

## Weekday handling

- `DAYS = ["Måndag","Tisdag","Onsdag","Torsdag","Fredag"]` — keys into `menus`
  and the labels shown.
- Today = `new Date().getDay()`, mapped 1–5 → index 0–4. Saturday/Sunday →
  no "today"; default the view to Monday and show a "Helg" (weekend) note.
- The selected day drives which dish array is shown per restaurant.

## Restaurant classification (keep the behaviour, restyle freely)

Each restaurant is sorted into one of:

1. **Full card** — has real menus that differ across days. The main content.
2. **Demoted / "others"** — either:
   - no menu any day (`why: "ingen meny"`), or
   - the exact same menu every day for ≥4 days (`why: "samma varje dag"`),
     in which case that single menu is shown once as static text.

The demoted places currently live in a collapsed `<details>` below the cards.
The redesign can present them differently, but the two-tier distinction (this
place has a real daily menu vs. it doesn't) must survive — it's the difference
between useful and noise.

## Status indicator

Three states, currently a coloured dot + label in the header:

- **Live** — `lt.json` loaded OK.
- **Sparad meny** — fetch failed, showing the embedded snapshot.
- Loading — brief, before the fetch resolves.

The `generated` timestamp is shown in the footer as `Uppdaterad <date time>`
(Swedish locale) when present.

## Embedded snapshot

`let WEEK = { … }` near the top of the `<script>` is a hardcoded copy of a real
`lt.json` (minus `generated`). It is the offline/failure fallback and the
first paint before the fetch returns. Refresh it whenever you redesign so it
structurally matches whatever the render code now expects, and so a reader with
a failed fetch sees a plausible current-ish menu.

## Non-negotiables checklist

- [ ] Single `index.html`, no build step, no JS/CSS dependencies
- [ ] Only external loads allowed: Google Fonts. Everything else inline.
- [ ] `fetch("lt.json", {cache:"no-store"})` kept, shape unchanged
- [ ] Embedded snapshot kept and refreshed
- [ ] Today-first; weekend → Monday + "Helg" note
- [ ] All visible text in Swedish; `<html lang="sv">`
- [ ] Five restaurants, correct order, per-day menus
- [ ] `Vegetariskt:` and `Bonus:` lines visually distinct from lunch options
- [ ] Two-tier restaurant classification (card vs demoted) preserved
- [ ] Deliberate light AND dark themes; `<meta name="theme-color">` updated
- [ ] Reads well 320px → desktop; no layout shift after fetch
- [ ] Day switcher keyboard-accessible with visible focus
- [ ] `prefers-reduced-motion` respected

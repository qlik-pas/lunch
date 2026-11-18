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
      "en": { "Måndag": ["short English dish name", …] },   // optional: same shape as menus, aligned
                                       // 1:1 with the Swedish entries; feeds the share button
      "weekly": true,                  // optional: ONE menu for the whole week (Troppo) —
                                       // identical every day, but still a full card
      "menus": {
        "Måndag":  ["dish 1", "dish 2", "dish 3"],
        "Tisdag":  [ … ],
        "Onsdag":  [ … ],
        "Torsdag": [ … ],
        "Fredag":  [ … ]
      }
    }
    // the scraped places, in the order scraper.py's SOURCES list defines:
    // "Bricks Eatery", "Eatery", "Smaka på Kina", "Restaurang Edison", "Kantin",
    // "Troppo", "Matstudio Kungsmarken", "Mat och Harmoni", "Linnea Basilika"
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

1. **Full card** — has real menus that differ across days, or is flagged
   `weekly` (one weekly menu, deliberately the same every day). The main content.
2. **Demoted / "others"** — either:
   - no menu any day (`why: "ingen meny"`), or
   - the exact same menu every day for ≥4 days (`why: "samma varje dag"`),
     in which case that single menu is shown once as static text.

The demoted places currently live in a collapsed `<details>` below the cards.
The redesign can present them differently, but the two-tier distinction (this
place has a real daily menu vs. it doesn't) must survive — it's the difference
between useful and noise.

## Fixed-menu places (not from lt.json)

Separate from the five scraped restaurants: `FIXED_PLACES` in `index.html` is a
hand-curated array of places with one standing menu instead of a dish of the
day — `{ name, blurb, url }`, blurbs kept verbatim in the team's own words
(some English, some jokes — don't translate or tidy them). They are static, so
rendered once at load rather than per day. Two places they must show up:

- a collapsed "Fast meny (N)" `<details>` — name (a link: the official site
  where one was found, otherwise a Google Maps search — keep the underline + ↗
  so it reads as clickable), blurb, and the same
  hue-tinted initial shield used elsewhere (hues come from `HUES`, keyed by
  name, so the shield matches the pick card);
- the "Vad blir det?" pick pool (the result name is a link too, same ↗ treatment) — one entry each (`dish` = the blurb), so the
  wheel can land on "go to Troppo", not just on a dish.

## "Copy today's lunch" (share text)

A button in the day heading row (right of the Idag/date tag) that builds the day's lunch as a Teams/Slack-ready English
post and puts it **on the clipboard** (so a plain Ctrl+V pastes it), with a
(no preview — only on a failed copy). Format: a `🎡 Lunch wheel of the day:` header,
then per place an `🧱 Label:` line (real Unicode emoji — `:shortcodes:` stay literal in Teams) and its dishes joined with ` | `, places
sorted by label (accents ignored). The `SLACK` map in `index.html` holds each
place's emoji + short label (Bricks Eatery → "Bricks", Restaurang Edison →
"Edison", Orvars burgers → "Örvars"). Rules a redesign must keep:

- the clipboard carries **both** `text/plain` and `text/html`; in the HTML each place's emoji + label is a link to the place (scraped `url` / fixed-menu `url`), so Teams pastes clickable names. Falls back to a `copy`-event handler that sets both flavours;
- the clipboard write happens synchronously inside the click handler (browsers
  refuse it otherwise) — never `await` a model/network call before it;
- dishes come from `en` (translated at scrape time); a place without `en` falls
  back to its Swedish text and is named in the status line ("Ej översatt än");
- a scraped place with no dishes that day (menu not published/updated yet) is listed as `no menu yet`, not skipped;
- Laziza reads `CRISPY CHICKEN!` on Wednesdays of even ISO weeks (a running joke);
- `Vegetariskt:` and `Bonus:` lines are left out (main dishes only), fixed-menu
  blurbs go in verbatim (jokes and Swedish included), `·` becomes ` | `;
- a note (and, only if the copy was refused, the text itself) shows under the heading; it is hidden again on day switch.

## Mobile affordances

- **Tap targets ≥ 44px** (the pick button, "Fast meny"/"Meny inte uppdaterad"/"Stängt denna vecka" summaries,
  each fixed-menu row); a card's whole header row (shield, name, ↗) is its link, via a
  stretched `::after`. The share button is 40px so it stays in line with the IDAG tag.

## Layout switch (wide screens) and TV mode

From 900px a three-segment switch next to SV/EN offers **Lista**, **Rutnät** and
**TV-läge**. Below 900px it is hidden and the page is always the list.

- List/grid is remembered in localStorage (`layout`); switching animates with a
  View Transition (cards named only for the duration, staggered — first card
  leads into the grid, last card leads back to the list). Reduced motion or no
  View Transitions → instant switch.
- TV mode is *not* remembered. It covers the page (`#kiosk`), asks for full
  screen, and shows today's full cards that have dishes one at a time, moving
  on every 15 s with a countdown bar; ←/→/space and the dots jump, Esc or ✕
  (or leaving full screen) exits. It re-reads lt.json every 10 minutes and
  follows the weekday. Cursor and ✕ hide after 3 s idle.

## Spin mode (phones)

Below 900px a round toggle bottom-right (`#wFab`, same button and place in both
states, icon swaps wheel ↔ list) switches **spin mode** (`#wheel`) on and off — a port
of ScheduleIT's thumb "ratt" (LivingIT/scheduleit, HANDOFF.md §5–7): the day's
full cards with dishes as a vertical wheel — the centred card open with its
dishes, neighbours collapsed to name + dish count — flick for momentum with a
detent tick (a note of the day's chord; Android also vibrates; mutable),
overdamped landing; swipe sideways for another day; "Idag" springs back. The
choice is remembered (`view` in localStorage) and the day carries over to the
page on leaving. Keep its physics constants (softened ones live in `FEEL`) and the one-loop rule;
never read layout per frame (open heights are measured once per build).

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
- [ ] Eleven scraped restaurants, correct order, per-day menus (`weekly` ones stay cards)
- [ ] Fixed-menu places: collapsed list + included in the pick pool
- [ ] `Vegetariskt:` and `Bonus:` lines visually distinct from lunch options
- [ ] Two-tier restaurant classification (card vs demoted) preserved
- [ ] Deliberate light AND dark themes; `<meta name="theme-color">` updated
- [ ] Reads well 320px → desktop; no layout shift after fetch
- [ ] Day switcher keyboard-accessible with visible focus
- [ ] `prefers-reduced-motion` respected

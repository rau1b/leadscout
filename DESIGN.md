---
name: LeadScout
description: A local outreach dashboard kept like a shop's bahi-khata, one page per day with a fixed capacity, bound in Bordeaux wine and warm sand.
colors:
  bordeaux: "#531B24"
  wine: "#6A2931"
  ink-soft: "#EADBD0"
  sand: "#C6B7A2"
  linen: "#E7D8C3"
  green: "#2E7D32"
  green-deep: "#1B5E20"
  danger: "#B42318"
  danger-soft: "#FBE3DF"
  text: "#2A1A1D"
  muted: "#6B5A55"
  chip-text: "#4A3A36"
  porcelain: "#F3ECE2"
  input: "#FFFCF8"
  sunk: "#EBE1D3"
  rule: "#DCCDB8"
  row: "#E6DACA"
  white: "#FFFFFF"
typography:
  display:
    fontFamily: "Mukta, Segoe UI, sans-serif"
    fontSize: "30px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.01em"
    fontFeature: "tnum"
  headline:
    fontFamily: "Mukta, Segoe UI, sans-serif"
    fontSize: "18px"
    fontWeight: 700
    lineHeight: 1.2
    fontFeature: "tnum"
  title:
    fontFamily: "Mukta, Segoe UI, sans-serif"
    fontSize: "16px"
    fontWeight: 700
    lineHeight: 1.2
    fontFeature: "tnum"
  figure:
    fontFamily: "Mukta, Segoe UI, sans-serif"
    fontSize: "24px"
    fontWeight: 700
    lineHeight: 1.2
    fontFeature: "tnum"
  body:
    fontFamily: "Mukta, Segoe UI, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
    fontFeature: "tnum"
  table:
    fontFamily: "Mukta, Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
    fontFeature: "tnum"
  label:
    fontFamily: "Mukta, Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 600
    lineHeight: 1.5
  hint:
    fontFamily: "Mukta, Segoe UI, sans-serif"
    fontSize: "13.5px"
    fontWeight: 400
    lineHeight: 1.5
  chip:
    fontFamily: "Mukta, Segoe UI, sans-serif"
    fontSize: "12.5px"
    fontWeight: 600
    lineHeight: 1.4
  button:
    fontFamily: "Mukta, Segoe UI, sans-serif"
    fontSize: "14.5px"
    fontWeight: 600
    lineHeight: 1
  brand:
    fontFamily: "Mukta, Segoe UI, sans-serif"
    fontSize: "21px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.01em"
rounded:
  code: "4px"
  radius: "6px"
  panel: "8px"
  chip: "10px"
spacing:
  s1: "4px"
  s2: "8px"
  s3: "12px"
  s4: "16px"
  s5: "24px"
  s6: "32px"
  s7: "48px"
components:
  button-primary:
    backgroundColor: "{colors.bordeaux}"
    textColor: "{colors.white}"
    typography: "{typography.button}"
    rounded: "{rounded.radius}"
    padding: "10px 16px"
  button-primary-hover:
    backgroundColor: "{colors.wine}"
  button-quiet:
    backgroundColor: "{colors.input}"
    textColor: "{colors.wine}"
    typography: "{typography.button}"
    rounded: "{rounded.radius}"
    padding: "10px 16px"
  button-quiet-hover:
    backgroundColor: "{colors.ink-soft}"
  button-danger:
    backgroundColor: "{colors.input}"
    textColor: "{colors.danger}"
    typography: "{typography.button}"
    rounded: "{rounded.radius}"
    padding: "10px 16px"
  button-danger-hover:
    backgroundColor: "{colors.danger-soft}"
  button-small:
    padding: "6px 10px"
  input-text:
    backgroundColor: "{colors.input}"
    textColor: "{colors.text}"
    typography: "{typography.body}"
    rounded: "{rounded.radius}"
    padding: "7px 10px"
  rail:
    backgroundColor: "{colors.bordeaux}"
    textColor: "{colors.white}"
    width: "216px"
  rail-link-hover:
    backgroundColor: "{colors.wine}"
  rail-link-current:
    backgroundColor: "{colors.linen}"
    textColor: "{colors.bordeaux}"
  day-page:
    backgroundColor: "{colors.input}"
    rounded: "{rounded.panel}"
    padding: "{spacing.s4}"
    width: "300px"
  side-panel:
    backgroundColor: "{colors.input}"
    rounded: "{rounded.panel}"
    padding: "{spacing.s4}"
  finder:
    backgroundColor: "{colors.input}"
    rounded: "{rounded.panel}"
    padding: "{spacing.s5}"
    width: "400px"
  status-chip:
    typography: "{typography.chip}"
    rounded: "{rounded.chip}"
    padding: "3px 9px 1px"
  status-new:
    backgroundColor: "{colors.linen}"
    textColor: "{colors.chip-text}"
  status-drafted:
    textColor: "{colors.wine}"
  status-approved:
    backgroundColor: "{colors.wine}"
    textColor: "{colors.white}"
  status-contacted:
    backgroundColor: "{colors.sand}"
    textColor: "{colors.text}"
  status-replied:
    backgroundColor: "{colors.green}"
    textColor: "{colors.white}"
  status-won:
    backgroundColor: "{colors.green-deep}"
    textColor: "{colors.white}"
  status-lost:
    backgroundColor: "{colors.linen}"
    textColor: "{colors.muted}"
  status-opted-out:
    textColor: "{colors.danger}"
  status-bounced:
    backgroundColor: "{colors.danger}"
    textColor: "{colors.white}"
  status-excluded:
    textColor: "{colors.muted}"
  note:
    backgroundColor: "{colors.linen}"
    textColor: "{colors.text}"
    rounded: "{rounded.radius}"
    padding: "8px 12px"
---

# Design System: LeadScout

## Overview

**Creative North Star: "The Day's Bahi-khata"**

The dashboard is kept like a shop's cloth-bound account book, bound in Bordeaux wine. Each day is one page with a fixed number of lines (the warm-up cap), filled in wine ink as sends go out, ruled off in Bordeaux at the close, with what is left carried forward to tomorrow. Everything else on screen is the ledger's working pages: dense ruled rows, figures in tabular numerals, one status colour per entry.

The world sits on a warm porcelain working ground with a single strong frame: a Bordeaux rail down the left edge, stitched with a dashed sand seam. Cards and fields sit a step lighter than the page, like fresh leaves laid on the desk. Inside that frame the surface is quiet and dense. Depth comes from rules and that one tonal step, not shadows; emphasis comes from ink colour and weight, not from tiles. The build refuses the default SaaS shell of stat-card tiles over a grey table: totals live inside the page they belong to.

Density is a feature for two people doing a daily sit-down review on a laptop. Rows are tight (6px vertical padding), headers are short, and every lead row carries the measured fact behind it.

**Key Characteristics:**
- Bordeaux cloth rail with a sand stitched edge; warm porcelain working ground, cards and fields one step lighter.
- Wine ink for names, links and figures; Bordeaux for primary actions and the book's closing rules.
- Mukta throughout, tabular figures everywhere.
- One colour code per lead status, identical on every surface.
- Ruled rows and bordered panels; no shadows, no card tiles.
- The day page: a fixed-capacity slot column closed with a Bordeaux double rule.

## Colors

A two-family account-book palette (Bordeaux wine and warm sand) over warm brown-black and porcelain neutrals, with green reserved for good outcomes and one clear red for failures.

### Primary
- **Bordeaux** (bordeaux): the rail, primary button fill, the active-tab underline, the day page's closing double rule and its carry-forward line, the reply form's top double rule, the measured fact under each pitch, and the "waiting" marker. It binds the book and marks what must not be missed.

### Secondary
- **Wine Ink** (wine): lead names, the day page's figures and filled slots, links, the details Show/Hide toggle, primary button hover, rail link hover, quiet-button text, focus outlines, caret and checkbox accent, and the drafted and approved chips. If it was written in by hand in a ledger, it is wine ink. The stylesheet aliases it as the ink and rail-hover roles.
- **Wine Wash** (ink-soft): quiet button and back-link hover, and the soft outer ring on focused fields.

### Tertiary
- **Warm Sand** (sand): the rail's stitched seam, field borders, the scrollbar thumb, outlined-chip lines (excluded, hidden), and the "contacted" chip. It is the thread.
- **Linen** (linen): the current rail link (Bordeaux text on linen), rail counts and footer text, text selection, the status note, and the new and lost chips. It is the highlighter.
- **Ledger Green** (green) and **Deep Ledger Green** (green-deep): replied and won chips only. Meaning, not brand.
- **Clear Red** (danger): bounced and opted-out chips, the danger button, and the hover on link-style remove buttons. Kept distinct from Bordeaux so a failure never reads as the book's frame.
- **Red Wash** (danger-soft): hover fill behind the danger button.

### Neutral
- **Bordeaux Black** (text): body text, the 2px rule under table headers and over table footers, the type on sand surfaces.
- **Warm Pencil** (muted): meta lines, table headers, hints, slot times, tab counts, lost and excluded chip text, secondary row text. The stylesheet's quiet role is the same value.
- **Chip Ink** (chip-text): text on the new chip.
- **Porcelain** (porcelain): the working page (the ground role).
- **Card Paper** (input): fields, quiet and danger button fills, and the bordered cards (day page, finder, lead side sections), a step lighter than the page.
- **Sunk Paper** (sunk): row hover and inline code.
- **Panel Rule** (rule): panel borders, pitch and message top rules, and the tab baseline.
- **Row Rule** (row): the 1px line between table rows and day-page slots.
- **White** (white): text on the rail, on primary buttons, and on the filled approved, replied, won and bounced chips.

### Named Rules
**The One Code Rule.** Each lead status has exactly one chip treatment (new linen, drafted wine outline, approved wine fill, contacted sand, replied green, won deep green, lost linen struck through, opted-out red outline, bounced red fill, excluded sand outline, hidden dashed sand outline) and it is the same on Today, Pitches, Replies, Leads and the lead page. Never restyle a status locally.

**The Ink Rule.** Names and figures are written in wine ink; prose stays Bordeaux black. Bordeaux is for the book's frame, its primary actions and its closing rules; the clear red is only for bounced and opt-out. Neither is used for ordinary links.

## Typography

**Display Font:** Mukta (self-hosted, 400/500/600/700, with Segoe UI, sans-serif fallback)
**Body Font:** Mukta
**Label/Mono Font:** Mukta; inline code uses the browser monospace on a sunk chip.

**Character:** One Indian-made humanist sans for everything, set with tabular numerals on the body so counts, scores and times line up like ledger columns.

### Hierarchy
- **Display** (700, 30px, 1.2, -0.01em; 26px under 820px): the page title in the header ("Today", a lead's name).
- **Headline** (700, 18px, 1.2): section heads on Today, with a 400 14px muted aside.
- **Title** (700, 16px, 1.2): day page and side panel heads, pitch business names.
- **Figure** (700, 24px, wine): the day's "sent / cap" total inside the day page head.
- **Body** (400, 15px, 1.5): default text; pitch and message bodies cap at 72ch.
- **Table** (400, 14px, 1.5): all table rows; names 600 in wine, score 700 right-aligned.
- **Label** (600, 14px): form labels, fieldset legends and table headers (headers in muted).
- **Hint** (400, 13.5px, muted): help lines, slot rows, the "when" line.
- **Button** (600, 14.5px, line-height 1): button labels; 13.5px on small buttons. Rail links are 15.5px.
- **Chip** (600, 12.5px, 1.4): status chips.
- **Brand** (700, 21px, -0.01em): the LeadScout wordmark on the rail.

### Named Rules
**The Ledger Figures Rule.** Tabular numerals are set on the body and inherited everywhere; never switch a numeric column to proportional figures.

## Layout

A two-column shell: a 216px sticky rail and a fluid main column (24px top, 32px sides, 48px bottom padding). Spacing runs on a 4/8/12/16/24/32/48px scale (s1 to s7).

The Today page is a 300px sticky day page beside the tables (24px row gap, 32px column gap); the lead page is the editor beside a 340px side column; Find leads is a 400px finder card beside its results; a pitch row is 260px identity, fluid copy, and an action column of at least 128px. Section blocks stack 32px apart.

At 1100px and below every two-column body collapses to one column, the day page stops sticking, and pitch actions wrap into a row. At 820px and below the rail becomes a top band with horizontally scrolling nav, the seam turns horizontal along its bottom, the rail footer hides, main padding drops to 16px, and secondary table columns hide. At 520px the finder's business-type checklist drops to one column.

## Elevation & Depth

The system is flat. There are no shadows anywhere. Depth and grouping come from rules and one tonal step: a 1px panel border, a 1px row rule, a 2px Bordeaux-black rule under table headers, a 3px Bordeaux double rule closing the day page and opening the reply form, and the 2px dashed sand seam on the rail. Bordered cards sit on card paper, a step lighter than the porcelain page. Row hover is a tonal shift to sunk paper.

### Named Rules
**The Ruled Book Rule.** Separate with lines, not lifts. If a new surface needs grouping, give it a rule or a panel border before anything else; the only tonal lift is card paper on porcelain.

## Shapes

Small, practical corners: 6px on controls (buttons, fields, notes, the back link), 8px on bordered panels (the day page, finder, side sections), 10px pill ends on status chips, 4px on inline code. Rail links are squared on the left and rounded on the right, so they read as tabs pulled from the book's spine; on mobile they round fully. Tables and pitch rows are unrounded ruled strips.

## Components

### Buttons
Plain, confident wine stamps.
- **Shape:** gently rounded (6px), 1px border in the same colour as the fill (quiet and danger take their text colour).
- **Primary:** Bordeaux fill, white 600 14.5px label, 10px 16px padding, line-height 1.
- **Hover / Focus:** background and border ease to wine over 150ms ease-out; focus is a 2px wine outline offset 2px.
- **Quiet:** card paper with wine text and a wine border; hover fills with wine wash.
- **Danger:** card paper with clear-red text and border; hover fills with red wash. Used only for opt-out.
- **Link-style:** transparent border, muted text; hover turns clear red and underlined. Used for remove actions.
- **Small:** 6px 10px padding, 13.5px. Disabled buttons drop to 45% opacity.

### Chips
- **Style:** 600 12.5px, 3px 9px 1px padding (optically centred for Mukta), 10px pill corners, 1px border (transparent unless outlined).
- **State:** one treatment per status per The One Code Rule; colour changes animate over 300ms when HTMX swaps a pitch.

### Cards / Containers
- **Corner Style:** 8px.
- **Background:** card paper, a step lighter than the porcelain page.
- **Shadow Strategy:** none (see Elevation & Depth).
- **Border:** 1px panel rule.
- **Internal Padding:** 16px; the finder card uses 24px.

### Inputs / Fields
- **Style:** card paper, 1px sand border, 6px corners, 7px 10px padding, 15px Mukta. Textareas resize vertically from 220px; the email body grows with its content. Checkboxes take the wine accent at 16px.
- **Focus:** border turns wine with a 2px wine-wash ring; the caret is wine.

### Navigation
- **Rail:** white 15.5px links with right-aligned linen counts; hover fills wine; the current page fills linen with Bordeaux 600 text and counts.
- **Status tabs:** muted 500 links on a 1px baseline; the current tab is Bordeaux black 600 with a 3px Bordeaux underline; counts sit beside in muted.
- **Back link:** wine 600 14.5px with an inline arrow; hover fills wine wash.

### Day Page (signature)
The day's sheet: a bordered 300px card-paper panel headed "Today's page" with the wine sent/cap figure. Below it, an ordered list of exactly cap slots, each 22px tall on a row rule: sent names in wine with their time, queued names in muted, empty slots in muted italic. A 3px Bordeaux double rule closes the page, followed by the carry-forward line in Bordeaux 600.

### Pitch Row (signature)
A ruled strip, not a card: business identity with the measured fact in Bordeaux 600, then subject and pre-wrapped body, then the status chip and stacked actions. Approved pitches mute their body.

## Do's and Don'ts

### Do:
- **Do** keep the Bordeaux rail and its dashed sand seam as the only heavy colour field on any screen.
- **Do** write names, links and figures in wine ink (#6A2931), primary actions in Bordeaux (#531B24), and prose in Bordeaux black.
- **Do** use the one status chip treatment for a status wherever it appears.
- **Do** separate content with rules and 1px panel borders; keep rows dense (6px vertical padding).
- **Do** show the measured fact behind a lead in Bordeaux 600 next to its name.
- **Do** set cards and fields on card paper (#FFFCF8) over the porcelain page (#F3ECE2).

### Don't:
- **Don't** add stat-card tiles or KPI boxes; totals belong inside the page they count, as the day page does.
- **Don't** add drop shadows; the book is flat.
- **Don't** use radii larger than 10px or round a table.
- **Don't** introduce a second typeface or proportional figures in numeric columns.
- **Don't** use the clear red for anything but bounced, opt-out and remove actions, or Bordeaux for a failure state.

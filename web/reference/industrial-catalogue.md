# Note: industrial catalogue system

Source: https://styles.refero.design/style/aecf9dda-5cba-4dc7-9e73-59b65d895cdf (Refero Styles entry for
teenage engineering). Summary in our words.

## What the system does
- A near-white canvas `#f6f8f7` with one near-black band colour `#0f0e12` (slight violet cast) used as a "display
  case wall" for hero and footer bands. Hard cut between the two; no gradients.
- Neutrals only: text `#000000`, hairlines `#e5e5e5` and `#b2b2b2`. A single chromatic note (an amber warning
  triangle, roughly `#f0a000`..`#f5b800`) is reserved for a warning state.
- 0px radius on every component; zero shadows; 1px rules organise the page like a technical drawing.
- Type: an ultra-thin custom sans (weights 100/300), compressed scale 13 / 19 / 24 / 26 / 40 px, line-height 1.11
  headings, 1.5 body; left-aligned only.
- Spacing: 15px element gap, 22px gutters, 66px section gap, 1200px max width; the product image is the card
  (no padding inside image cells).

## Taken
Flat chassis (0px radius, no shadow, no gradient), 1px hairlines as structure, mist canvas `#f6f8f7` with a
near-black band, colour rationed to states, left alignment.

## Changed
- Band colour: the deck's ink `#15141f` instead of `#0f0e12`, so the site matches the CodeQuest deck.
- Weight 100 body text rejected: it fails readability at 13px for a console people make money decisions in. Body is
  17px at weight 400; display at 500.
- One amber warning note becomes a three-signal system (ALLOW, REVIEW, DENY), each with its own shape and word.
- Spacing moved to a 4px base (4..144) and a 12/4-column grid.

# Notices and credits

WarCounsel is MIT licensed (see [LICENSE](LICENSE)). This file records the
third-party material bundled or vendored here, where our own numbers come
from, and how we'd like you to treat all of it.

## Using this yourself

**Take what's useful.** The MIT licence already permits it, but to say it
plainly: copy the parser, lift the verification-gate pattern, vendor the
data files, fork the whole thing. No permission needed and no obligation
to ask.

**A mention is appreciated, not required.** If something here saved you an
afternoon, a link back is kind. If it didn't, take it anyway — this exists
because half a dozen other people in this community published their work
first, and most of them asked for nothing either.

Two things that are genuinely required, because they aren't ours to give
away:

- **Wiki-derived content stays CC BY-SA 4.0.** `backend/zem_levels.wiki` is
  a verbatim snapshot of an [eqlwiki](https://eqlwiki.com) page, and the
  item, spell and vendor data fetched at runtime comes from the same place.
  Attribute the wiki and keep derivatives share-alike.
- **Vendored third-party code and data keep their own licences**, listed
  below. MIT on this repo doesn't relicense them.

## Vendored material, with thanks

- Community-measured spell durations and raid triggers in
  `backend/alert_data.py`, and the real-log test fixture under
  `tests/fixtures/`, derive from **kpxcoolx/eql-alerts** and
  **kpxcoolx/eql-meter** (MIT).
  - EXCEPT the `SPELL_TIMERS` rows marked `[eqlbuilds]`, whose durations
    come from the eqlbuilds.com dataset's `durationTicks` (x6 = seconds).
    That is wiki-derived, so those values are **CC BY-SA 4.0**, not MIT —
    one file, two licences, which is why the marker has to stay on the
    row. The alerts pack is a raid trigger list and carries almost no
    low-level content, so these fill gaps it will never cover; a
    regenerate from that pack must preserve the marked rows. These are
    exact game data rather than community measurement, and so are the
    only entries here that do NOT deliberately under-promise.
- Zone travel and translocator/ritual routing data in
  `backend/map_system.py` follows **rari/eqltools** (CC0).
- The curated spell-line stacking table in `backend/spell_lines.json`
  (112 lines, 344 spells) is **rari/eqlfinest**'s `paths` table (CC0).
- `backend/zem_levels.wiki` is a snapshot of eqlwiki's *Recommended Levels
  and ZEM List* — community-maintained, **CC BY-SA 4.0**.
- `maps/newsebexp.txt`, the New Sebilis Expedition chart, is
  community-contributed. Its original author is unknown to us; if it is
  yours, tell us and we'll credit or remove it as you prefer.
- The item acquisition extraction approach in `backend/game_data.py`
  follows **DavisChappins/eql-tooltip** (MIT).
- The weapon damage-bonus model in `backend/game_data.py` follows
  **xaziaver/eql-weapon-inflection-analyzer** (MIT).
- Wine prefix locations and the command-line process check used for macOS
  and Linux follow **sowoky/osxEQL** and **jkatsnelson/osxeql-qol**.
- Stagger and mesmerize parsing came from reading **sardonicsloth/eqlc**
  (MIT) and **GiuffreLab/eql-metrics** — most of what we checked was
  already handled, but those two lines were not.
- Packaged builds may embed a copy of the eqlbuilds dataset snapshot from
  **ArtSabintsev/everquest-legends-mcp**. MIT covers that project's CODE and
  packaging; it does NOT relicense the data. The snapshot's own
  `manifest.json` records the eqlwiki revision it was extracted against
  (`wikiRevisionId`), so the dataset is wiki-derived and stays
  **CC BY-SA 4.0** -- the same terms as everything else mined from the wiki.
  This applies to ALL of it, not only the `[eqlbuilds]` rows in
  `backend/alert_data.py`: `builds_data.py` feeds spell levels, AA ladders
  and skills into the advisor throughout.
- [eqltools.com](https://eqltools.com) is linked from the Atlas and its
  published sourcing discipline is the model for this file.

## Where our own numbers come from

Not everything the app shows carries the same confidence, so:

- **Log-parsed** — read directly from lines the game writes. Damage,
  heals, misses, loot, XP, coin, zone, casts, timers. This is the floor
  the whole app stands on and it is verified against real logs.
- **Export-parsed** — from `/outputfile` dumps you generate yourself:
  spellbook, inventory, missing spells, achievements. Game-authoritative.
- **Wiki-mined** — item stats, spell records, vendor locations, the
  hunting table. Community-submitted and occasionally wrong or stale; we
  gate LLM suggestions against it rather than the other way round.
- **Modeled** — computed from published formulas, never measured by us:
  the item-level scaling ported from the wiki's own slider, the weapon
  white-DPS indices, the merge progression. Labelled as indices or
  estimates wherever shown, because they are.
- **Deliberately absent** — ZEM multipliers. The wiki withholds them on
  purpose, so nothing here estimates them.

## Trademarks

EverQuest and EverQuest Legends are trademarks of their respective owners.
This project is an unaffiliated, passive, read-only companion: it parses
log files the game itself writes, and does not modify, inject into, or
automate the game.

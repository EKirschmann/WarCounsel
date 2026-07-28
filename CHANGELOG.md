# Changelog

Notable changes per release. Check for updates by clicking the version badge
in the app header; update by closing the companion and running
`update_companion.bat`.

## Unreleased

**"none loaded" no longer looks like a problem.** Ollama unloads a model
after five minutes idle and loads it again on the next request, so an
idle server showing nothing resident is normal. The check now says
"loads on first use" and reserves the warning colour for what actually
stops a consult: the model you configured not being among the ones
installed.

## v2.1.4 — 2026-07-28

**Check server.** Settings has a button beside LM Studio and Ollama that
asks the local server whether it is actually running, which models it
has, and which is loaded right now — rather than finding out when a
consult fails. It also says when your configured model is not among the
ones the server offers.

That last part had a bug worth naming, since it would have hit anyone
setting Ollama up for the first time: checking a provider before saving
it compared the server's models against the *previously* selected
provider's model, and wrongly reported yours as missing.

## v2.1.3 — 2026-07-28

**All-time totals start at launch.** Beta play is no longer counted —
a beta character need not have survived, so including it would credit a
fresh character with someone else's history.

**Beta exports are called out.** Launch day means the `/outputfile` dumps
on your disk are probably from beta — and a beta character need not have
survived, so the advisor could be judging what you own from a character
that no longer exists. Exports written before 2026-07-28 now read
**"from BETA — re-export"** instead of an hour count, and the sync hint
is marked urgent. It was already telling you they were 166 hours old;
that reads as slightly stale rather than possibly wrong.


**Fixed: the wrong model name after switching providers.** Picking LM
Studio or Ollama could report a Claude model, because anything the
builder did not recognise silently became Anthropic, and because only
OpenAI and Custom remembered their own model. Every provider now reports
and keeps its own, and an unknown one fails loudly instead of quietly
becoming something else.

**Fixed: "no JSON in LLM reply" from models that answer in their
reasoning.** Some builds — QAT quantisations especially — return an empty
`content` and put the whole answer in `reasoning_content`. The reply is
now read from wherever the model put it.

## v2.1.2 — 2026-07-28

**All-time stats.** The Vitals panel has a small **all time** button next
to the session summary: lifetime kills, deaths, loot, levels, AAs, zones,
fights, damage dealt and taken, healing, best DPS and hours in combat —
per character and server, so switching characters switches the numbers
and nothing blends. It reads your existing history, so it is populated
from the first launch rather than starting at zero. Coin and XP are the
exception: they were never stored before, so those two begin
accumulating now.

**Anthropic is selectable now** — the client was already bundled in the
.exe, it just could not be picked. **Grok** needs no new support: it is
OpenAI-compatible, so point the Custom endpoint at
`https://api.x.ai/v1`, which the provider menu now says out loud.

**Ollama is selectable now.** It was wired into the backend all along but
unreachable — missing from both provider menus and rejected outright by
the API. Pick "Local — Ollama" in Settings, or set `LLM_PROVIDER=local`.
The model and server address are fields in Settings — no `.env` editing —
so it can point at another machine, which is the usual setup when the
desktop has the GPU and you play on a laptop. It works in the packaged **.exe** as well — it is the only provider
needing no key and no account, which suits a one-file download, so it now
ships alongside the OpenAI and Anthropic clients. Source installs get it
from `pip install -r requirements.txt`.

## v2.1.1 — 2026-07-28

**Routes now show the druid and wizard lines.** Under the walking route,
each porting class gets its own line with the level you need in parens on
the zone the port lands in, and how many hops it saves. Ritual ports
persist once leveled, so this answers the question people actually ask.

**Clickies you own.** Items with an effect you activate yourself, listed
in the gear tab, with whether they are worn or sitting in the bank.
Weapon procs are excluded — they fire on their own.

**The shopping list says where to buy.** Missing spells now name the
zone, the vendor, their guild and their coordinates. It also fixes a bug
that hid the list entirely: the 25-spell cap kept the lowest levels, so
anyone with a backlog of skipped spells saw nothing at all.

**Launch-day patch.** The new **Void-touched Potential** raid token is
counted with your motes — it merges the same way but is named nothing
like one, so it was invisible. Both spellings of the Iksar city resolve
to its map, since the patch notes and the game disagree. And the advisor
will no longer suggest spending points on the new autogranted **Unbound**
AAs, which arrive free at level.

**The Atlas links out to eqltools' whole-world atlas**, which shows every
zone connected in 3D with coordinate lookup. Ours tracks where you are
inside a zone; that one is for planning where to go.

## v2.1.0 — 2026-07-27

**Mac and Linux.** Neither has a native EQL client, so people play under
Wine — CrossOver, Whisky or osxEQL on a Mac; Lutris, Bottles or plain
Wine on Linux. From the host side a bottle is just a folder, so the
combat log is a normal file and the tailer reads it directly.

The game folder is found automatically across all of those layouts, and
`start_companion.sh` runs the app on both platforms. The overlay and
screen-OCR stay Windows-only; play windowed with the browser beside the
game. Everything else is the same build.

Untested on real hardware — verified against each bottle layout by
construction, then confirmed end to end on a real Ubuntu 25.10 box: the
probe found a bottle on a case-sensitive filesystem, the backend booted
and tailed a log, and the UI built and served. If yours is not found, an
issue with the path fixes it.

**New Sebilis Expedition draws its map now.** v2.0.1 left it unmapped
rather than guess, since its name suggests the Kunark dungeon but it is
an EQL-only Iksar city. It turns out to ship its own assets —
`newsebexp.s3d` and `newsebexp.txt` — so the 3D view works out of the
box, and the chart now ships with WarCounsel itself, so the 2D view
works with no setup. Every zone name in a 90MB log now resolves.

## v2.0.1 — 2026-07-26

**Zones that never drew a map.** An audit of every "You have entered"
name in a real 90MB log found 9 of 38 resolved to nothing — the panel
just showed blank, with no error. Fixed: Temple of Cazic-Thule, the
Karana plains under their EQL names, and the Estate of Unrest — whose
alias pointed at a key that did not exist and so suppressed the direct
hit that would otherwise have worked. 8 of the 9 now resolve, in both
the 2D chart and the 3D view.

The ninth, New Sebilis Expedition, is deliberately left unmapped. It is
not the Kunark dungeon its name suggests but an EQL-only Iksar
underground city off The Northern Desert of Ro, so the obvious mapping
would have drawn a level 40-60 dungeon for a starting city. No map
beats the wrong map.

EQL's `<Zone> Expedition` wrapper is now stripped like a difficulty
suffix, so future instanced zones resolve without a code change, and an
unresolved zone logs itself once instead of failing silently.

**The overlay shows what you choose.** Every section switches off, and
every field inside one — keep the kill count, drop the coin; keep
cooldowns, drop the buffs you refreshed. Presets: Everything, Combat
focus, Meter only. Changes reach a running overlay in about half a
second. Timers are now depleting tracks coloured by kind, and an
expiring one washes the whole row red.

**Settings no longer steals the caret.** The panel re-focused the game
folder several times a second, so clicking anything else bounced you
back to the path field.

**Advisor corrections.** Pet weapons were ranked by damage/delay ratio;
pets keep their own attack delay, so ratio means nothing to them — a
weapon's damage counts only when it beats the pet's innate hit, while
procs apply either way. AA counsel now prefers General/Archetype ranks
(bought once, kept in every combo) and never spends points on
achievement-granted ones.

**Zone names link to the wiki** from the leveling chart and the hunting
picks. The gear-farm list links to a wiki *search* instead, because
those names are not gated against the zone table.

**Three parsing gaps, found by reading two other EQL tools.** EQL prints
`<mob> staggers.` when a stun lands — about 14,000 times in a 90MB log,
and we parsed none of it. Abilities now carry a stagger count, credited
only when the staggered target matches the one we just hit (roughly half
of them are other players' strikes and stay uncredited). Mez application
is tracked, pairing with the fade we already had. And the trailing tags
beyond Critical — Slay Undead, Finishing Blow, Crippling Blow — are kept
as per-ability counts instead of being collapsed into a crit flag.

**The hunting table now ships with the app.** Previously fetched live
only; when that failed the location verifier silently switched off and
passed unchecked zone picks through. A packaged .exe with no network hit
that on every consult.

## v2.0.0 — 2026-07-25 — now **WarCounsel**

Renamed, in time for EverQuest Legends' launch on July 28.

"Companion" is the most crowded word in this corner of GitHub, and it
undersold what this actually is. **War** is the live combat half — DPS meter,
overlay, encounter breakdowns, the War Ledger, drop tracking. **Counsel** is
the advisor — wiki-grounded loadouts, gear recommendations, exaltation
tracking, one-click spell-set writing. Nothing else in this space does both,
and now the name says so.

**What this means for you**

- **The download is now `WarCounsel.exe`.** Put it in the same folder as the
  old one and it picks up your existing `data` folder automatically — every
  session, setting and mined map survives. Then delete `EQLCompanion.exe`.
- **Any desktop shortcut needs remaking**, since the filename changed. This
  is the one-off cost of the rename, and the reason it is happening before
  launch rather than after.
- **If your data lived in `%LOCALAPPDATA%`** (the case when the .exe sits
  somewhere Windows will not let programs write), it stays exactly where it
  is. The app looks for the old folder and keeps using it rather than
  starting empty — nothing is moved, so nothing can be half-moved.
- **The old GitHub URL still works.** GitHub redirects it, including clones
  and the update check.

**Also in this release**

- **A real icon.** The executable had none, and no version resource either —
  Properties → Details was blank. It now carries an icon at seven sizes and
  reports its version, product name and description, which is what Windows,
  antivirus and support all read.
- **Build actions updated** off the deprecated Node 20 runtime.

## v1.16.0 — 2026-07-25

**Group numbers you can compare.** An ally's pet used to fold into its
owner's damage row, while your own pet is shown apart from "You". So this
app's view of a groupmate was them *plus* their pet, while that groupmate's
own copy split the two — for any pet class the two readouts could never
agree. Since comparing figures with someone else running the same tool is a
main reason to have it open in a group, an ally's pet now gets its own row
and the numbers reconcile.

**Heals that were never counted.** Two forms were silently dropped: heals
logged without a trailing `by <Spell>` (common for direct heals), and
healers whose names are not player-shaped — mobs, with lowercase multi-word
names. On the 90MB log this project is developed against, `other_heal` went
from 26,730 to 45,638 events. Roughly nineteen thousand heals were
happening and never counted, most of them mobs healing themselves, which is
frequently the reason a fight is not ending. Unattributed heals still count;
they group under a "Direct heal" row instead of a spell name.

**Third-person casts.** "A froglok novice begins casting Inner Fire." is the
only warning before a mob lands something, and only your own casts were
parsed before. First person is "begin" and third is "begins", so the two
cannot collide. They appear in the ledger and per-encounter, so you can see
what is being cast at you and by whom. The vendored test fixture gained 14
events from this alone.

**Overlay: a tray icon and global hotkeys.** The overlay has no title bar
and is click-through most of the time, so once hidden — or dragged
off-screen — there was nothing left to click, and every control needed a
window that is never focused while you play.

| Keys | Does |
|---|---|
| `Ctrl+Alt+O` | show / hide |
| `Ctrl+Alt+C` | compact mode |
| `Ctrl+Alt+↑ / ↓` | opacity |
| `Ctrl+Alt+X` | force interactive (no Scroll Lock needed) |

The tray icon offers the same plus **Reset position**, the rescue for an
overlay dragged off the edge. Windows 11 tucks new tray icons into the `^`
overflow until you drag one out.

**Also**

- The release build now self-checks the overlay's own dependencies. The
  overlay is a child process the server smoke test never reaches and its
  tray fails soft, so a missing packaged import would have shipped silently
  — the way the spell-line table did in 1.15.1.

## v1.15.2 — 2026-07-25

Fixes v1.15.1's headline feature in the build most people actually download.

- **The spell-line table was never bundled into the .exe.** PyInstaller's
  `--collect-submodules` gathers Python modules; a `.json` sitting beside
  them is not code and has to be declared. So `backend/spell_lines.json` was
  missing from the packaged build, and because a missing data file fails
  soft by design, the buff-slot stacking gate silently did nothing there.
  Source installs were unaffected. Now declared in both `build_exe.bat` and
  the release workflow.
- **The release build now asserts its own data arrived.** The smoke test
  already proved the exe boots; it now also checks the spell-line count is
  non-zero, so a bundled file that goes missing fails the build instead of
  shipping a feature that quietly does nothing. `GET /api/settings` reports
  the counts under `data`.
- Corrected the download size in the docs: a clean-runner build is ~42 MB,
  not the ~59 MB a developer machine produced.

## v1.15.1 — 2026-07-25

**The advisor now knows about buff slots.** EverQuest buffs occupy effect
slots, and two spells in the same slot do not add — the second overwrites
the first. So a loadout holding both Center and Bravery (both `ac-slot-1`)
had quietly spent a gem on nothing, and the existing supersession check
could not see it: it reasons from effect ids and magnitudes, and slot
occupancy is not in that data.

- `_gate_stacking` keeps the **strongest** spell per slot — curated lines run
  weakest to strongest, and the strongest is what you end up with whatever
  order you cast in. It runs across must_have + should_have together (they
  are one slot fill) and *before* the promote step, so a freed gem refills
  from the alternatives; the promote loop skips anything that would recreate
  the clash.
- Prebuffs get the same gate. Long-duration buffs are the worst place to
  stack two of a slot, because the second cast silently throws away the
  first one's mana and remaining duration.
- Data is rari/eqlfinest's hand-curated spell lines (CC0, from the same
  author as the routing data already used here), vendored as
  `backend/spell_lines.json` — 112 lines over 344 spells. Coverage is
  partial against the client's ~66,000 spell records, so a spell that is not
  in the table is **never** dropped: absence of data is not evidence that two
  buffs are compatible.

**"Nothing is happening" now says which nothing.** The app reads the game's
own `eqclient.ini` to tell apart two states that look identical from the
outside — logging was never switched on (you need to type `/log on`) versus
logging is on but nothing has happened yet (just play). If the game is
*running* and its `Log=` setting is off, the hint is promoted to a banner
rather than sitting in the quiet advisory line, because in that state
nothing you do is being recorded at all. It fires even when an old log file
exists, which is the case that used to be silently misleading.

This is a read-only check, deliberately. Other companions set `Log=1`
themselves so the step disappears; this one will not write to a game file it
was not asked to write to.

**Also**

- The MCP setup instructions pointed at a different project that happens to
  share the name `everquest-legends-mcp`. It has no tags and no eqlbuilds
  data, so following them left every spell/AA unlock level falling back to
  the wiki. Now points at ArtSabintsev's, the one actually in use.
- Recorded that the loot-filter action codes are only half confirmed: 4=sell
  is provable from the log and 3=merge is agreed, but a dedicated editor for
  those files documents 1 and 2 the other way round. Only a display label is
  affected, and it is flagged rather than guessed at.
- Repo now has a description and topics, and releases are built by CI on a
  clean runner rather than a laptop.

## v1.15.0 — 2026-07-25

**A standalone .exe** — one 59 MB file, nothing to install. Plus a settings
panel, because a downloaded executable has no `.env` to edit.

**Download and run**

- `build_exe.bat` produces `dist\EQLCompanion.exe`: no Python, no Node, no
  pip. It finds your game through the Windows registry, opens a native
  WebView2 window, and keeps its data in a `data` folder beside itself
  (or `%LOCALAPPDATA%\EQLCompanion` when that folder is read-only).
  ~4s first start; everything works except screen OCR — HUD, overlay,
  Atlas 3D with textures, timers, alerts, and LLM counsel all included.
- The build is now verified rather than theoretical, and finding out how
  fixed five defects — four of which were bugs in the source install too:
  - **Optional dependencies could abort startup.** `ocr_system` caught only
    `ImportError`, but a half-present rapidocr raises `FileNotFoundError`
    when its model manifest is missing, killing the whole app over a
    feature that build does not even ship. The guard is deliberately broad
    now.
  - **One bad texture cost the whole zone.** A failure in the 3D texture
    export aborted the entire payload; it degrades to an untextured view.
  - **Helper windows**: `/api/overlay` ran `[sys.executable, "-m", ...]`,
    which frozen would boot a second server. Flags now (`--overlay`).
  - **No console in a windowed build**: `sys.stdout` is None and uvicorn's
    formatter calls `.isatty()` on it. Streams adopt a log file, and
    pywebview's main-thread requirement moved uvicorn to a worker, so
    closing the window shuts down through the normal lifespan.
  - **Paths**: `backend/paths.py` splits read-only bundled assets from
    writable state, so nothing lands in a temp dir that is wiped on exit.

**Settings — the gear in the header**

- Game folder with a **Test** button that reports what it actually found
  ("3 character log(s)") or what is wrong, and a one-click fill from
  registry detection. Saving re-derives the paths and restarts the tailer;
  no restart needed.
- Advisor model, including an API key field. Providers the running build
  cannot support are greyed out rather than silently falling back.
- **Keys live in `data/secrets.json` and nowhere else.** Never logged
  (field names only), never returned to the browser (`GET /api/settings`
  reports booleans), and explicitly gitignored. A key field omitted from a
  save is left untouched, so saving a game folder cannot wipe it; an
  explicit empty value clears it.

**Also**

- `requirements-lite.txt` now lists the LLM clients deliberately.
  PyInstaller bundles only what the build machine has installed, so
  omitting them produced an exe whose API key field could never work —
  depending on who ran the build.
- "MCP server not found" was logged on every wiki lookup; said once now.
- README and INSTALL.md cover both installs, including the SmartScreen
  warning an unsigned binary raises and how to verify it yourself.

## v1.14.1 — 2026-07-22

An efficiency pass over the two slowest user-facing paths and the log
parser, plus smoother live position tracking. Every figure below was
measured on this repo's fixture log and a real 15MB zone payload.

**Faster**

- **Wiki requests stop rebuilding the TLS context every call.** Building
  it parses certifi's entire CA bundle — 190ms — and every HTTP wiki fetch
  paid that toll. Cached once, so a page fetch drops from ~0.40s to
  ~0.22s. The update check reuses the same context instead of building a
  second one.
- **Zone geometry is served straight from its cache.** `/api/geometry` and
  `/api/geometry3d` were parsing their own JSON cache purely so the
  response layer could re-serialize it — 251ms + 300ms on the 15MB
  Greater Faydark payload. Those bytes now reach the client untouched.
  A zone payload is fixed for a given .s3d, so its gzip is cached beside
  it as well and the middleware no longer re-compresses 15MB per request:
  **~1.5s -> ~69ms** for a cached zone. Clients that do not accept gzip
  still get plain JSON. Cache writes are atomic (temp file + rename) and
  reads carry a shape check, since nothing parses the cache anymore to
  notice a truncated one.
- **Log parsing is ~35% faster** — 15.4 -> 10.0 us/line. The timestamp is
  fixed-width, so it is sliced rather than run through `strptime` (which
  re-reads the locale on every call), and a combat burst's repeated stamps
  hit a small bounded memo. Unusual shapes still fall back to `strptime`;
  the fast path was verified to agree with it on every stamp in the
  fixture, and parser coverage is unchanged at 3045 events / 283 unparsed.

**Smoother**

- **Live position tracking no longer moves in little steps.** The 2D chart
  eased out over a fixed 700ms, so it braked to a standstill inside every
  ~1s OCR tick and then sat there; the 3D hero snapped with no
  interpolation at all. Both now interpolate linearly over the feed's
  *measured* cadence (`frontend/lib/glide.ts`), so consecutive fixes chain
  into continuous motion instead of stuttering. Sub-unit movements glide
  rather than hop; zone-line-sized jumps, the first fix, and
  `prefers-reduced-motion` still snap.
## v1.14.0 — 2026-07-22

Combat intelligence round (ideas surveyed from EQBuddy and itsspin/spinips
— no license on either, so everything here is an independent
implementation), plus a zero-skill install path and a visual README.

**Deeper combat tracking**
- **Cooldown oracle**: the game's "You can use the ability X again in
  M minute(s) S seconds." line now SNAPS the matching cooldown timer
  exact whenever it prints — vendored estimates only bridge the gaps.
- **Buff fades carry their target** ("worn off of <target>" — the
  mez/charm-break tell): fades cancel the matching spell timer and can
  fire "fade" tracked rules; "Your pet's X" fades recognized and excluded.
- **Built-in alerts with zero setup**: "You have been summoned!" and your
  name spoken in group/guild/raid chat always raise the overlay banner —
  no tracked_rules.json entry needed.
- **Composition line** ("Your active classes are ...") sets the trio just
  like /who when all three names resolve.
- New session counters: stuns taken, mends, stealth state, OVERHEAL (the
  parenthesized potential value on heal lines), and motes looted by tier.

**Overlay (EQBuddy parity, phase 3)**
- **Hero band**: FIGHT | SESSION | BEST DPS strip at the top of the
  overlay, always visible even with every section collapsed.
- **Pinnable mini-strip**: star a section to keep it in compact mode;
  Ctrl+Alt+X forces the overlay interactive without Scroll Lock.

**Trio analytics**
- `GET /api/trio-compare` + a Vitals table: per-trio DPS/kills/deaths
  comparison across archived sessions — see which class mix farms best.
- Encounter **timeline sparkline**: 2s damage buckets per fight rendered
  in the Encounter panel (peak marked).

**Install & docs**
- INSTALL.md rewritten for people who have never installed anything:
  numbered checkpoints, the ZIP-extraction trap called out, expanded
  troubleshooting table.
- `setup_wizard.py` finds the game via the Windows uninstall registry
  first (DGC "EverQuest Legends" key), directory scan as fallback.
- README: StoneGlass SVG logo + an "In action" showcase — four real HUD
  screenshots plus the desktop overlay mid-fight (alert banner, timers,
  damage bars, drop rates).
## v1.13.0 — 2026-07-22

Built-in timers and alerts — no companion apps needed (durations and
raid triggers vendored from kpxcoolx/eql-alerts, MIT):

- **Spell countdowns**: casting any of 159 spells with
  community-measured EQL durations starts a timer (Splurt 102s,
  Mesmerize 24s, Clarity 27m, ...). A fizzle, interrupt, or resist of
  that spell cancels it — no false countdowns on a resisted mez.
  Durations don't model tier scaling, so timers err short.
- **Raid mechanic warnings**: Nagafen/Vox breath and Dragon Roar
  cooldowns, Cazic Thule's add-spawn shout, Death Touch timers for all
  seven Plane of Sky bosses and Master Yael — recognized straight from
  the log.
- **Where you see them**: a new TIMERS section in the overlay (soonest
  first, red under 5 seconds, gold for raid mechanics) and a matching
  list under the DPS gauge in the Vitals panel.
- **Tracked alerts**: edit data/tracked_rules.json (created for you
  with an example) — plain substring rules on loot / kill / death /
  zone. A match flashes a gold banner across the overlay for 6 seconds
  and plays a Windows chime (per-rule sound toggle, 5s cooldown, never
  fires during the startup replay). The file reloads automatically
  when you save it. No text-to-speech by design — if you want voice
  callouts, the standalone eql-alerts app remains the tool for that.
## v1.12.0 — 2026-07-22

The overlay grows up (EQBuddy-inspired), and the companion learns what
a "session" is:

- **The overlay is now a session widget**, not just a damage meter.
  Four sections: COMBAT (the familiar ranked bars), SESSION (kills,
  deaths, XP% with XP/hr, coin with coin/hr, crits, hit rate), LOOT
  (recent drops + your best observed drop-rate mobs), and PROGRESS
  (level, an honest hours-to-ding estimate, session vs active time).
  With Scroll Lock on: click a section header to fold it, press c for
  a compact one-line strip, +/- to adjust opacity — position, opacity,
  and layout persist between launches. Click-through, the singleton
  guard, and auto-close on game exit are unchanged.
- **Honest per-hour rates**: XP/coin/kills per hour are computed
  against ACTIVE time (2-minute activity buckets) as well as elapsed —
  a 30-minute AFK no longer drags your rates down. Hours-to-level says
  "(max)" until you ding once in the session, then turns exact.
- **Session history**: the login banner now rolls the session over —
  the finished session's summary (kills, XP, coin, loot count, damage,
  max DPS, active hours) is archived, counters reset, and a new "Past
  sessions" table in the Vitals panel shows your recent sessions.
  Empty sessions are never recorded. What the app KNOWS (pet mappings,
  rosters, owned AAs) survives the rollover.
- **Screen-OCR position feed rescues misread coordinates**: classic
  letter/digit confusions (O/0, l/1, S/5, B/8) are corrected inside
  numbers — "X: -1O2" parses as -102, and a fully-misread "Z: -SO"
  after its label parses as -50 — frames that used to be dropped now
  land. Zone names are never altered.
- The main Consult now shows the same dimming veil over stale counsel
  that the gear consult has — no more wondering whether it heard you.
## v1.11.0 — 2026-07-21

Community-sourced upgrades (with thanks to kpxcoolx/eql-meter,
Velkenn/EQL-Effects-Finder, xaziaver/eql-weapon-inflection-analyzer,
terry-wilkerson/EQL-Loot-Filter-Manager, and rari/eqltools):

- **Exaltation tracking is now game-authoritative.** Your inventory
  export lists every socket on your gear (type included) — the app now
  reads them directly: stone types come from the game, "can socket
  into" requires a genuinely EMPTY socket of the right type, and since
  real exports show proc sockets on earrings and faces, the export
  overrides the old proc-goes-in-weapons assumption.
- **Loot filter awareness**: the app passively reads your LF_*.ini —
  merge notices now warn when an item is set to auto-sell or
  auto-merge, and /api/loot-filter summarizes your filter.
- **Smarter weapon advice**: 1H weapons show main-hand / off-hand
  white-DPS indices built on the real combat model — the main-hand
  damage bonus is a flat, delay-independent add (fast MH weapons beat
  their ratio) and the off-hand swings part-time with no bonus, so the
  best MH is often not the best OH.
- **Travel routes use rituals and translocators**: the route finder
  knows naval translocator dock cliques (Freeport–Butcherblock in one
  hop) and druid/wizard port rituals castable from anywhere —
  Rivervale to Erudin is now "cast Circle of Toxxulia, walk to Erudin"
  instead of nine zone lines.
- **Combat log accuracy**: rune absorption is tracked (new session
  stat), "magical skin absorbs the blow" counts as its own defense,
  self-inflicted damage (cannibalize, damage-shield ticks) counts as
  damage taken instead of polluting DPS, faction-cap lines parse,
  raid /who rows no longer misread the group number as your race, and
  other players' pets swinging as "Name`s warder" fold into their
  owner instead of vanishing.
- **Encounters**: each fight now shows its peak 3-second burst DPS,
  and a "copy" button produces a one-line shareable parse.
- Exaltation stones in the gear tab show where their base item drops
  on hover. A real-log regression fixture and
  `scripts/parser_coverage.py` make the after-patch parser check
  reproducible.
## v1.10.1 — 2026-07-21

Smarter merge notices and exaltation-aware weapon advice:

- **Merging worn pairs is no longer suggested blindly.** When both
  copies of an item are worn (ears/wrists/fingers), the merge notice
  shows the real trade in red — e.g. wearing two +4 bracers gives
  AC 20 / HP 18 while the merged +5 alone gives AC 11 / HP 10 — and
  says to keep both unless a better filler exists for the freed slot.
- **Weapon swaps respect exaltation stones.** Item lines in the
  consult now show which stones they host, and the advisor follows the
  real rules: stones move between your items for free, so they follow
  the better weapon instead of anchoring the worse one — but proc
  stones may only fire from the Primary slot, so a swap that would
  strand a proc off-hand now says "move its stone into your primary
  first" instead of silently wasting it.
## v1.10.0 — 2026-07-21

The knowledge release: the advisor now consults curated class guides,
item names grew where-to-get-it hover cards, and duplicate gear
surfaces merge opportunities.

- **Class guides** (`class_guides/*.md`, editable): every consult now
  reads curated guide files for your trio — a cross-class mechanics &
  meta file (combat-roll math, the two-highest-classes HP rule, healer/
  slower requirements, mote strategy), reference files for races,
  stances & invocations (including how invocation bonuses scale with
  your trio composition), and rituals, plus one file per class: deep
  community-sourced guides for Enchanter (Cavepig) and Necromancer
  (Haitsmelol/Necrotalk) and wiki-baseline files for the other 14.
  Update them freely after patches — see class_guides/README.md.
- **Item hover cards**: hover any item name in the Gear tab (slots,
  farm targets, merges, pet hand-overs) to see where it comes from —
  Drops From (zone + mob), Sold by, quests, and crafting, mined from
  the wiki's rendered item pages.
- **Merge opportunities**: owning two copies of the same equipment
  (bags/bank/worn) now lists them under the slot table with the
  predicted merge result from the wiki's progression model — equal
  ranks merge to exactly one rank up; a +0 into a +6 shows the tiny
  fractional gain honestly. Copies hosting exaltation stones are
  flagged first.
- **Honest survivability framing**: set your Max HP/Mana in the Vitals
  panel (the log never prints them) and gear advice frames HP swaps as
  percentages; with recent combat observed, it can say "+75 HP ≈ 2
  average incoming hits". Magnitude adjectives without data are now
  banned from gear counsel.
- **Log accuracy** (from the July patch notes, verified against real
  logs): heal crits are now parsed and counted (they only started
  logging on 7/7), and tier-suffixed spell names ("Lay on Hands VI")
  match correctly everywhere — proc labeling, lifetap detection, cast
  evidence.
- **Hunting keeps up with patches**: dev-revamped zones override the
  community sheet's stale bands — Crushbone now advertises 4-22 and
  Splitpaw 25-42, each tagged with the patch note.
- Reliability: item names that miss the wiki fuzzy-resolve via search
  + edit distance; wiki caches serve the last good data when a refresh
  fails; the OCR position feed gains a contrast boost for small text
  (thanks to DavisChappins/eql-tooltip for the techniques).
## v1.9.1 — 2026-07-21

The panels catch up with everything v1.9.0 started tracking:

- **Vitals & Session**: new "Coin earned" tile — a real session money
  total (corpse coin + group splits + vendor sales, shown as
  "3p 2g 6s 7c") that survives restarts — and a "Crits ✦" tile.
- **Session hunting table**: per-mob Coin and Drops columns — Drops is
  your observed drop rate (items dropped ÷ kills), so farming spots
  show their real yield; hovering a row still lists the items.
- **Encounter panel**: ability rows show per-ability crit counts
  ("12 ✦3") in the current fight, the pet section, and the last-5-
  fights aggregate; a "resisted" line lists which spells the foe
  resisted and how often; damage-shield damage appears as its own
  gold-accented row instead of hiding in the totals; and lifetap
  self-healing (synthesized in v1.9.0) shows in the Healing section.
## v1.9.0 — 2026-07-21

Big combat-log accuracy release: the parser now recognizes a large set
of real EQL line formats it previously dropped (found by studying two
excellent community projects — EQBuddy and eql-log-reader), pets map
themselves with zero setup, and the game's own spell file grounds proc
and lifetap detection.

- **Damage numbers are more complete.** Newly parsed: incoming DoT
  ticks (damage you take from dots was invisible before), plain and
  incoming non-melee nukes, damage shields in all three directions
  (yours counts toward damage/DPS but never inflates swing accuracy),
  and casterless proc/poison ticks. One real log had 38,000+ damage
  shield hits that were simply missing.
- **Crits are tracked.** Trailing tags — "(Critical)", stacked
  "(Riposte) (Critical)", "(Crippling Blow)" — are recognized, counted
  per session and per ability, and marked with ✦ in the War Ledger.
- **More of the world parses**: named spell fizzles and interrupts
  (bard forms too), resists in both directions (shown per fight),
  faction hits, item merges, advanced-loot destroys, group coin
  splits, vendor sales, multi-stack auto-sells, banked-to-depot loot,
  and Berserker frenzy / cleave / smite / reave / shoot verbs. The
  "You now have N ability points" total now drives the unspent-AA
  counter authoritatively.
- **Chat can no longer pollute combat stats**: speech lines are
  excluded before combat matching, so players quoting combat text in
  /say or /tell don't register as damage.
- **Pets map themselves.** The pet's own "Attacking X Master." tell
  (printed only to your log) registers it automatically — no /pet
  leader needed (it still works). Charm handling: a "pet" that turns
  on you un-maps instantly; slain pets un-map.
- **The game's spell file grounds the tricky calls** (spells_us.txt,
  read from the game folder — nothing installed): exaltation effects
  that are also scribed spells now label "(exaltation)" when the data
  says proc-granted and you never cast them; and lifetap self-healing
  is synthesized — your own taps log no heal line at all, so that
  healing never counted before.
- **Fairer XP and coin attribution**: corpse coin now converts to
  copper and credits the mob like XP does; rewards that print AFTER a
  kill (looting the corpse later, trailing party XP) fall back to that
  kill instead of being dropped. Per-mob stats now track coin and
  drop counts.
- Log reading hardened: correct cp1252 decoding (accented names no
  longer risk breaking parses), a log-staleness signal on /health, and
  the game folder is auto-discovered from the Daybreak registry entry
  when the configured path doesn't exist.
## v1.8.0 — 2026-07-21

- **Gear advice now uses REAL +N stats.** The wiki's Item Level slider
  formula (eqlwiki computes upgraded stats client-side from the base
  item) is ported into the app and verified to match the site
  bit-for-bit: primary stats gain ~10% of base per level (+1/level for
  small values), weapon damage gains floor(base×N/10), haste/regen +1
  per level, weight drops, and items with 2+ stats grow the emergent
  "SV VOID: +N" resist. Every owned item in the gear consult is shown
  at its actual owned rank ("[stats at +4]"), so comparisons are
  honest both ways — a higher +N no longer auto-wins, and a strong +0
  drop can rightfully beat a worn +2.
- Deterministic mode (LLM "none", and the fallback when a model call
  fails) got real cross-item recommendations: besides same-item
  higher-rank detection it now suggests a bags/bank item when it is
  strictly better than the worn one — equal or higher on every scaled
  stat, higher on at least one — slot- and class-checked.
- **Pet hand-overs are verified before display.** The consult now
  shows the model the pet's currently-held items WITH their scaled
  stats (they aren't in your inventory export, so they were previously
  compared as bare names), asks it to name what each hand-over
  replaces, and a new deterministic gate drops any suggestion that is
  strictly worse than something the pet already holds — no more
  "replace the 19 AC breastplate with a 17 AC coat".
- Exaltations: stones whose base item carries a **Focus Effect**
  (a separate wiki field that our parser missed — it even renders
  glued onto the Race line) now show that effect and type as focus
  stones with correct "can socket into" rules, instead of
  "no listed effect (stat stone?)".
- Gear tab layout: Pet gear now sits directly under the player slot
  table, with Exaltations after it.
- Pet mechanics corrected per the definitive spec (since v1.7.0):
  pet gear is a flat bag of N generic slots — no invented Head/Arms
  rows; every pet is base Warrior plus a secondary class by pet type
  (set via the new "pet 2nd class" dropdown); it can equip gear usable
  by its two classes or any of your trio (Attunable only, never
  No-Drop); the slot count auto-computes from your class combo and
  stays overridable; gear persists through death and re-summon.
- Quieter logs: wiki pages that don't exist (the HTTP fallback covers
  them) no longer warn on every consult.
## v1.7.0 — 2026-07-19

- Fixed the launcher serving a stale (older-version) interface in
  production mode: start_companion.bat now rebuilds the UI automatically
  whenever the source changed since the last build.
- Pet tracking: reads /pet inventory check to know the pet's real loadout;
  a mapped pet shows as its own "(pet)" row in group DPS with its abilities
  tracked; gear consult fills the pet's empty slots and respects the slot
  count you set; an emptied pet is recognized and cleared.
- Exaltations: "can socket into" now uses the real class/slot rules
  (eqlwiki) — proc stones need a shared class with the target weapon, etc.
- AA counsel drops already-owned/maxed ranks (rank recovered from data
  since the log omits it); gear recs are slot- and class-checked.
- Groundwork for a dependency-free single executable (deterministic, no-OCR
  build; single-process serving).

## v1.6.1 — 2026-07-17

- Hunting recommendations follow the community's redesigned
  Recommended-Levels table: per-level efficiency ratings (efficient /
  doable / not recommended), explicit level ranges, and zone types.
  The advisor now strongly prefers zones the community rates EFFICIENT at
  your level, cities are excluded by their own Type column, and the
  leveling chart reflects the rated bands (gaps included).
- Encounter parse labels exaltation proc damage "(exaltation)" — except
  effects that are also scribed spells, which stay attributed to your
  casting.

## v1.6.0 — 2026-07-15

- **Much lighter on your PC**: the interface now runs as a production
  build (~350MB less RAM, no file watchers) and the backend drops its
  dev-mode reloader; the installer/updater build the interface once
  (about a minute). Developers: `start_companion.bat dev` keeps the old
  hot-reload behavior.
- OCR position tracking skips its neural-net pass entirely when the
  captured pixels haven't changed — standing still or sitting in menus
  now costs (almost) no CPU.
- Session snapshots write only when something actually happened.

## v1.5.3 — 2026-07-14

- Fixed "CERTIFICATE_VERIFY_FAILED" when checking or downloading updates:
  Python now validates GitHub with the bundled certifi certificate store
  (some Windows Pythons and antivirus HTTPS-scanning break the default
  one). If you are already stuck on it: run `pip install certifi` once,
  or download the ZIP in your browser — then updates work normally.
- Update checks fall back to the plain GitHub website when the API is
  rate-limited (shared IPs), and error messages show the real cause.

## v1.5.2 — 2026-07-14

- OCR on Python 3.13 actually works now: the rapidocr v2 engine needs the
  onnxruntime package installed separately (CPU package — no graphics
  card requirement) and it was missing from the requirements. Update and
  the calibrator's "onnxruntime is not installed" error goes away.

## v1.5.1 — 2026-07-14

- Fixed installs failing on Python 3.13: the OCR engine package now
  selects per Python version (rapidocr-onnxruntime up to 3.12, its
  successor rapidocr on 3.13+) — screen-OCR position tracking works on
  both. The installer also offers to install Python and Node.js for you
  via winget, and its window can no longer vanish before you read it.
- Downloads and one-click updates now track tagged releases, not
  in-development code.

## v1.5.0 — 2026-07-14

- **Update available, one click**: the app checks GitHub quietly (on load
  and every 6 hours) and shows an "Update available — vX.Y.Z" button next
  to the version; clicking it runs the updater in its own window. Updates
  no longer need git at all — ZIP installs update themselves via a
  built-in downloader that never touches your settings or data. Plus
  INSTALL.md: a plain-language install guide (no git, no command line).
- **Pet support, properly**: set your pet's equipment slot count in the
  Advisor and the gear consult builds it a loadout from spare bags/bank
  items (player keeps stat priority; at least one weapon). Pet abilities
  get their own encounter section; a mapped pet's kills and damage count
  as yours; a Vitals hint reminds you to /pet leader after summoning.
- **Encounter tables**: per-ability hit/cast counts (the Details-style x
  column); group heals show WHO healed; every fight shows a defense line.
- **Session hunting fixed**: XP attribution follows EQL's real line order
  (XP prints before its kill) — chain pulls no longer mis-credit; sorted
  by XP; per-level XP resets on ding; auto-sold loot shows "(sold)".
- **Advisor**: saved counsel restores after any restart (marked stale when
  your context moved on); exaltation moves respect class restrictions;
  keep-rows render dimmed; collapsed-ledger width goes to the encounter
  panel; vendor shopping list; loadout warnings ignore rituals and
  item-granted casts.

## v1.4.2 — 2026-07-14

- Collapsing the War Ledger in the normal layout now actually frees its
  column (slim vertical strip, like the Atlas/Advisor one) instead of
  leaving an empty panel.

## v1.4.1 — 2026-07-14

- The HUD is locked to the viewport on desktop: tall panels (encounter,
  advisor) scroll internally instead of stretching every column below the
  screen; the Atlas chart flexes to the available height.

## v1.4.0 — 2026-07-14

- **Combat dashboard**: hide the Atlas/Advisor panel and the encounter view
  reflows into side-by-side columns across the freed width; the War Ledger
  becomes a short strip and can collapse entirely; encounter text size is
  adjustable (A− / A+); the Companion chat tab is gone
- **Defense stats**: every fight now shows the tanking line — avoided %
  with dodge / parry / block / riposte / miss counts
- **Spell sets**: gems auto-ordered (DD, DoTs, AoE, heals from gem 8,
  utility, pets); pick-and-choose checkboxes (max 14) with a bigger,
  auto-backfilled nice-to-have list; the pre-buff set fills to 14 with
  permanents first then longest-duration buffs
- **Vendor shopping list**: near-level missing spells worth buying, marked
  "buy ahead" when above your level (spells scribe early)
- Loot lines that auto-sold show "(sold)"; loadout-change warnings no longer
  misfire on travel rituals or exaltation-granted casts; the overlay closes
  with the game and never doubles

## v1.3.1 — 2026-07-14

- **Pre-buff spell set**: a second write button on the Pre-buffs section
  creates a "prebuffs" in-game set (permanent buffs first) — /memspellset
  prebuffs, buff up, then /memspellset companion for combat.
- **The advisor now knows which buffs are permanent** (self-target,
  zero-duration in the spell data — Instrument of Nife, Shielding line,
  Banshee Aura…) and is instructed never to suggest "refreshing" them.
- Spell-set write confirmations stay on screen until the next consult.

## v1.3.0 — 2026-07-14

- **Write in-game spell sets**: a button next to "Memorize now" writes the
  advisor's picks (priority order = gem order) straight into the game's
  saved spell sets as "companion" — then one command in game loads the whole
  bar: `/memspellset companion`. Existing sets are never touched and a
  one-time backup of the file is kept. Note: the game reads this file at
  login, so camp to character select and back before using the command.
- Saved sets are readable via /api/spellsets with spell ids decoded to names.

## v1.2.0 — 2026-07-14

- **Details-style damage meter overlay**: ranked class-colored bars over the
  game (like the WoW Details! addon) — bar length shows share of the leader,
  each row shows damage (or DPS) and percent of the group total, up to raid
  size. Two modes (Damage | DPS — click the title) and two segments (this
  fight | last 5 fights — click the right side of the header) while Scroll
  Lock is ON; click-through as always when it's OFF.

## v1.1.0 — 2026-07-14

- **Update checker**: click the version badge in the header to compare your
  install against the latest release; `update_companion.bat` pulls it.
- **Deterministic spell/AA grounding**: the advisor reads the eqlbuilds.com
  dataset snapshot directly (exact unlock levels, AA rank costs) instead of
  scraping wiki tables; spell verification works even without the MCP server.
- **Pet fix**: summoned-pet lines are compared by unlock level — the advisor
  can no longer recommend a lower-level pet than you own (necromancer bug).
- **Typed exaltation sockets**: focus / clicky / worn / proc (taxonomy per
  eqlegendstools.com); socket-move advice is constrained to same-type
  sockets, and proc stones to weapon slots.
- MCP data source repointed to the up-to-date ArtSabintsev repository.

## v1.0.0 — 2026-07-13

First shared release.

- Live HUD: vitals, War Ledger, encounter history with group/raid breakdowns
- Atlas: Brewall charts with live position (/loc + optional screen OCR with
  a guided setup), true-wall mined geometry, textured 3D with follow camera
- Advisor: wiki-grounded spell loadout tiers, AA counsel, upgrade warnings,
  hunting spots gated to the in-era community level table + leveling chart
- Gear: full 24-slot roster (both Any Slots), exaltation tracking, farming
  targets; machine-verified against your actual exports
- Counsel models: none (deterministic) / LM Studio / OpenAI / any
  OpenAI-compatible endpoint — switchable at runtime
- Sessions survive backend restarts; guided installer (`install_companion.bat`)

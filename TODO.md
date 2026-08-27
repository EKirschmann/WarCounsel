# TODO

Shelved ideas and known gaps, with enough context to pick up cold. Not a
roadmap — nothing here is committed to a release.

---

## Trio capability data from eqltools' picker

**Status:** DONE 2026-08-19. Vendored, read, and in the advisor prompt.
Shipped after v2.11.0, so it lands in the next release.

`backend/picker_capabilities.json` — 32 capabilities x 16 classes, 16 KB
trimmed from their 105 KB `https://eqltools.com/picker/data.js`, refreshed
by `scripts/refresh_picker.py` (mirrors `refresh_zem.py`, same
refuse-on-zero and refuse-on-big-drop guards). Read by
`backend/capabilities.py`; `trio_capability_line()` goes into the prompt
between the character facts and the spell lists, split at the character's
level into HAS NOW / LATER / LACKS.

**Licensing settled and narrower than expected.** robots.txt still says
"Building on this data? Cite eqltools.com", cited in NOTICE.md, in the
snapshot, and on every emitted line. Each capability carries their own
`seal`: `client-mined` 31, `model` 5, `chat` 3, `wiki` 1. Only `atkAA` is
wiki-sealed, so — unlike the eqlbuilds snapshot — this is almost entirely
NOT wiki-derived and only that one row carries CC BY-SA 4.0.

**The trap that was designed IN, and had to be designed out.** The shelved
plan said to filter capabilities returning level `None`. `track` is
`{BRD, DRU, RNG}` with EMPTY entries — nobody who has it has a level — so
that filter deletes tracking from the table and every trio then reports
that it LACKS it, a Ranger's included. Membership in `byClass` IS the
capability; `level` is optional detail. Same shape as the gear rule in
issue #10: a lookup that returned nothing is not a verdict. There is a test
named after it — do not re-introduce the filter.

The other exclusions from that plan were right: `tierCC`/`tierDps`/
`tierHeal` are sealed `chat` (letter grades from community discussion, and
this app gates model output against fact rather than feeding it consensus),
and `manaPool`/`plate`/`tone`/`weaponCaps`/`tankModel` are ratings, not
abilities. Its worked example reproduced EXACTLY three weeks on, every
level matching, which is the evidence the data is stable enough to vendor.

**What is left:**

- **One gate uses it: the pet gate (2026-08-20).** `_summons_a_pet` reads the
  `pets` capability alongside its spell scan, which found a live bug -- see
  tests/test_pet_gate_sources.py. The bigger prize is still open: no gate
  constrains STRATEGY. Kiting advice given to a trio with neither snare nor
  SoW is the motivating case, and it cannot be gated as things stand --
  every existing gate takes a NAMED thing in a structured field and looks a
  fact up about it, while a tactic lives in free prose (`note`,
  `class_notes[].advice`). Gating prose means matching model text, which is
  the fuzzy matching this project bans for zone names. The way in is a
  constrained `tactics` field in the advisor's JSON (kite / root-park /
  pull / charm / fear-kite / travel-on-foot) plus a table in our code
  mapping each tactic to the capabilities it needs. Prompt + schema + gate
  + tests, and it changes the model's output shape, so it wants its own
  release.
- **A consistency check would find more of these cheaply.** The Beastlord
  bug was found by comparing the capability table against the spell
  snapshot class by class. Doing that on every consult -- trio LACKS pets
  while the spellbook holds a pet spell -- surfaces disagreements between
  two sources instead of silently trusting whichever was read first.
- **`ladder` is not vendored** — the per-level spell progression, which would
  let the line say what the upgrade at 23 is rather than only when a
  capability starts. Doubles the snapshot; take it if a gate wants it.
- **Not seen in a live consult.** Verified by unit test and by rendering the
  prompt, not by watching a model use it.

---

## Verify Mac and Linux against a real Wine install

**Status:** shipped in v2.1.0. First real-hardware report arrived 2026-08-19
as issue #12 — CachyOS, Faugus Launcher — and it found BOTH halves wrong.

Detection was verified against seven simulated bottle layouts and then end
to end on Ubuntu 25.10 — but with a synthetic game folder, because that box
has no wine or lutris and no EQL install. #12 is the first time anyone has
pointed it at a real bottle with the game in it.

**What #12 already settles:**

- **The reported symptom was not detection at all.** Typing the correct
  path by hand ALSO failed, because the save gate rejected any folder without
  `Logs/eqlog_*.txt` — a file that only exists after `/log on`, which the
  player cannot reach through an app refusing to accept the game's location.
  Fixed 2026-08-19: `ok` now means "is this the install folder", "nothing to
  tail yet" is a warning that saves, and only a non-install is refused. The
  lesson generalises past Wine — on Windows the registry key hides this, so
  the manual path had never been the only way in.
- **Faugus is a confirmed miss in `_drive_c_roots()`.** It is umu-launcher
  (Proton), so the layout is probably `PREFIX/pfx/drive_c`, and the only
  `pfx/drive_c` glob we carry is hardcoded to Steam's compatdata. Prefix
  roots to add, pending the `find` output asked for on the issue: `~/Faugus/`
  (its README's default), `~/.config/faugus-launcher/prefixes/` (older builds),
  and the flatpak under `~/.var/app/io.github.Faugus.faugus-launcher/`.

- **The launcher never installed the Python dependencies (fixed 2026-08-20).**
  `install_companion.bat` runs `pip install -r requirements.txt`; `start_companion.sh`
  installed `node_modules` and nothing else, so INSTALL.md's "three commands"
  left Mac and Linux with no fastapi. The UI came up on :3000 and the backend
  died on import, which reads as a pathing problem — #12 spent a day there.
  Two untested platforms and the whole install path was one command short.
  Now builds a private `.venv` (PEP 668 refuses system pip on Arch, Fedora
  and Homebrew) and checks the import before launching.

Still unknown:

- **`game_running()` is inferred, not observed.** Off Windows it scans the
  process command line for `eqgame`, borrowed from osxEQL's `pgrep -f`
  health check. If it is wrong the `/log on` banner mis-fires. Cosmetic,
  but unverified.
- Whether the probe list misses layouts BEYOND Faugus. The same `find ~
  -maxdepth 8 -type d -name "EverQuest Legends"` settles each one, and
  a miss stays a one-line fix — but assume more launchers, not fewer:
  the list was written from Lutris/Bottles/Steam and the first real user
  turned up on none of them.

---

## Overlay on a webview instead of tkinter

**Status:** deferred by the user, 2026-07. Rationale corrected 2026-08-13 —
the entry previously argued itself backwards.

**The reason to do it is the SHARED UI, not Mac.** A webview overlay would
draw in real HTML/CSS against the frontend's StoneGlass tokens and
components instead of duplicating them in tkinter drawing calls, which is
where the effort currently goes every time the overlay gains a section.

**The old entry said "worth revisiting only if the overlay becomes a
priority on Mac", which is exactly backwards for WebView2** — it is
Windows-only, so choosing it would convert "we do not ship a Mac overlay"
from a policy into an architectural fact. If Mac ever matters, the target
is **pywebview**, not WebView2: pywebview picks `edgechromium` (WebView2) on
Windows, `cocoa` (WKWebView) on macOS and `gtk`/`qt` on Linux, and its
`create_window` already takes `transparent`, `frameless` and `on_top`.

**We already ship pywebview**, so this adds no runtime. It is not in
`requirements-lite.txt` — `build_exe.bat` and the release workflow append it
to the pip line — which is worth knowing because that file's own comment
claims to decide what the exe can do.

**The spike is DONE (2026-08-13): edgechromium honours it.** Measured in
pixels rather than trusted from the API — baseline the desktop, put the
window over it drawing one opaque box, compare. The desktop pixel under the
transparent area came back byte-identical (delta 0) while the box rendered
pure #ff0000, and `WS_EX_TOPMOST` was set. `transparent`, `frameless` and
`on_top` all work together. Script kept at `scratchpad/spike2.py` shape —
re-run it after any pywebview upgrade.

Two things the spike also settled:

- **Click-through is NOT provided.** The window came back with neither
  `WS_EX_LAYERED` nor `WS_EX_TRANSPARENT`, so the Win32 ex-style dance stays
  exactly as it is today — including the trap that rewriting the ex-style
  drops the layer attributes and paints the window solid black. Port that
  code across unchanged rather than rewriting it.
- **DPI scaling is real and must be handled.** Asking for `x=300, y=300,
  420x320` produced a window at `(450, 450)` sized `608x424` on a 150%
  display. `data/overlay_ui.json` persists position and size, so a port that
  ignores this will drift saved geometry on every launch.

**The renderer is not what blocks Mac.** `backend/overlay.py` is about ten
Win32 calls deep — `windll.user32` for the layered/transparent ex-styles and
`SetLayeredWindowAttributes`, `GetAsyncKeyState` for hotkey polling,
`GetKeyState(VK_SCROLL)` as the interact toggle, `CreateMutexW` for the
singleton, `winsound`, and an `eqgame.exe` watch to self-close. A Mac
overlay is a rewrite of the INTERACTION model whatever draws the pixels, and
macOS still will not reliably draw over a fullscreen Wine game. Do not let
"keeps Mac open" be the justification; several other things close it first.

**Whatever is chosen, the process boundary stays.** `main.py` imports only
`overlay_prefs`, never `overlay`, and the overlay launches through
`child_command()`. That is why the server runs on Mac and Linux at all, and
it is the one thing not to trade away for a nicer overlay — see the Electron
comparison in "Adopting from everquest-companion", where their single
process owning five overlay windows is precisely what this boundary forbids.

---

## Richer class guides

**Status:** deferred by the user until after launch.

`class_guides/*.md` are curated by hand and nothing regenerates them.
Necromancer and Enchanter are the model for depth; the rest are thinner. A
pass through Reddit and the class forums after the 2026-07-28 launch was
the plan, once post-launch consensus exists.

---

## Audio triggers

**Status:** requested 2026-07-28. Audio not started; the TRIGGER half was
done 2026-08-08 (see "GINA-style triggers" below) — rule kinds now cover
interrupt/fizzle/cast/mechanic/mez and the rules are editable under
Settings ▸ Triggers, so `sound` has somewhere obvious to become a filename.

Today the only sound the app makes is a single `winsound.MessageBeep` from
the overlay when a tracked rule fires — one chime for everything, and only
if the overlay is running. TTS was deliberately left out, pointing people
at the standalone eql-alerts app for voice callouts.

What "audio triggers" should mean, roughly in order of value:

- **A sound per rule.** `data/tracked_rules.json` already carries `kind`,
  `pattern`, `enabled` and `sound` (currently a bool). Making `sound` a
  filename turns one chime into "that was a named spawn" versus "that was
  a tell" without looking away from the game.
- **Distinct built-ins.** The summon warning and your name in group/guild/
  raid chat are the two that already bypass the rules table; they deserve
  to be distinguishable by ear, since they mean very different things.
- **Volume, and a mute that survives restart.** Overlay prefs
  (`overlay_prefs.json`) is the natural home, and the settings panel
  already renders that schema from the backend.
- **Optional TTS**, revisiting the earlier decision. Mudmouth shows the
  local-only shape: Kokoro-FastAPI, nothing leaving the machine. If it is
  ever added it should stay opt-in and offline by default, and it should
  not become a reason to duplicate eql-alerts.

**Constraints worth knowing before starting:**

- **The overlay is the only thing that beeps**, on purpose — the browser
  cannot be relied on to have focus or permission, and two sources would
  double up. Anything added should keep that single-source rule.
- `winsound` is **Windows-only**. Now that macOS and Linux are supported,
  audio needs a per-platform seam (`afplay` / `paplay` / `winsound`), and
  it must fail soft the way the tray already does.
- Sound files have to ship or be user-supplied. Bundling a handful means
  `--add-data` and a CI assertion, exactly like `maps/`.

---

## GINA-style triggers (the rest of the way)

**Status:** asked again on Discord 2026-08-08 — "can you make triggers with
this tool (like GINA, e.g. spell interrupted, charm break)?" Charm break
already worked (`{"kind":"fade","pattern":"Charm"}`); spell interrupt did
not, for no better reason than that no rule kind reached an event that was
already being parsed. Both work now, and rules are editable in the app.

What is still missing before "like GINA" is honest:

- **Matching on ARBITRARY log lines.** Rules watch twelve event kinds; GINA
  watches the raw line. This is the big one, and it is a different shape:
  the tracked-rule table is fed by parsed events, so a raw-line rule needs
  its own path down in the watcher, before/beside `parse_line`.
- **Regex with capture groups**, and displaying the captures ("Fear kiting
  {1}"). Note the standing decision: matching is substring-only *on
  purpose*, per EQBuddy — nobody should have to escape an apostrophe in a
  mob's name to watch for it. If regex arrives it should be an OPT-IN per
  rule (`"regex": true`), never the default, so the simple case stays
  simple and a bad pattern cannot break the whole table.
- **Per-trigger display text**, rather than echoing what matched.
- **Trigger-started timers.** The timer machinery already exists
  (`_start_timer`, kinds spell/cooldown/raid) — a rule would just need to
  name a duration. Probably the cheapest high-value item here.
- **Importing GINA packages** (their shared XML trigger sets). Attractive
  because the community already has good ones; a parser plus a mapping
  onto whatever the rule model looks like by then.

**Constraint worth restating:** TODO's audio entry warns this must not
become a reason to duplicate eql-alerts. Triggers that feed the OVERLAY and
the existing timer/alert surfaces are ours; a second voice-callout engine
is not.

## Launch-day patch follow-ups (2026-07-28)

Checked at launch; these are the ones needing real-world data before they
can be finished.

- **OCR calibration vs the UI Scaling option — SAID IN THE UI 2026-08-19.**
  The launch patch added UI scaling (1-5) and text filtering; the 2026-08-18
  patch widened it to eleven steps in 0.25 increments and added Cursor
  Scaling, so the odds of somebody moving it went up sharply. The screen-
  OCR feeds read fixed screen regions, so a scale change moves what is
  under them and the read is silently wrong — no error, nothing to diagnose
  from. The OCR panel now says so above the three region rows, naming the
  Windows display scale too, which is what actually bit the owner on a
  2560x1600 laptop at 125%. Still not done: nothing DETECTS a scale change
  and invalidates the saved regions. That needs a scale reading from
  eqclient.ini, and is only worth it if a warning turns out not to be enough.
- **Ornamentation slots** were added to model-visible Crushbone items.
  `SOCKET_TYPES` maps `{7 focus, 8 clicky, 9 worn, 10 proc}`; if
  ornamentation uses a new slot number it will read as `None` and be
  treated as unknown. Fails soft, so nothing breaks — but the number is
  unknown until an export with one shows up. Grab an Inventory export
  from a character holding an ornamented Crushbone item.
- **Rampage cooldown.** Cleave and Frenzy now reduce it, mirroring the
  Smite/Reave shaves in `COOLDOWN_SHAVES`. Rampage is not in
  `ABILITY_COOLDOWNS` and the patch does not state its duration, so no
  shave was added — inventing the number would be worse than omitting it.
  The game's own readout line creates the timer regardless, so Rampage
  already times correctly once activated; only the shave is missing. Add
  it once someone reports the base cooldown.

## 08/25/2026 patch follow-ups

Read against the code the day the notes landed; these are the pieces that
cannot be finished yet. Two of them are WAITING ON SOMEBODY ELSE'S DATA
rather than on work here, so they are written as triggers — the thing to
watch for, and the one command that settles it:

| When | Do | Settles |
|---|---|---|
| Your client actually downloads the 08/25 patch (this machine was still on 08-17 when this was written) | `python scripts/zone_coverage.py` | Whether Rujarkian Hills ships assets, and with them a short name we can evidence |
| Any MCP release lands | `git show <tag>:src/data/eqlbuilds/meta.json` — read `revisionId`, not the tag | Whether the AA table has moved past eqlwiki 151303 (2026-06-27) and finally carries Strike As One |

- **Bulk quest turn-ins — REVERTED the same day, and they will be back.**
  The notes describe pre-calculated bulk turn-ins that "display clearly in
  chat (max 4 'chat' blocks)", multi-item reward lines that state HOW MANY
  rewards you got, coin NPCs accepting any denomination and refunding
  overage in the highest one. Every one of those is a new shape for lines
  `parser.py` already matches one-at-a-time — `RE_LOOT*`, `RE_COIN*` — and
  a summarised block is exactly the case where the old per-item regex sees
  nothing and the ledger silently under-counts a turn-in. The 08-25
  hotfixes reverted the lot, so there is nothing to match against today.
  When it ships again: capture the real lines first, then add forms — do
  not guess them from the patch note wording.
- **A new AA is invisible to counsel until the eqlbuilds snapshot catches
  up, and that is the gate working.** 8/25 added the Beastlord AA "Strike
  As One" (L35, 6 points) and made "Full Potential" grantable. The
  snapshot the MCP clone ships is pinned to eqlwiki revision 151303
  (2026-06-27) and carries neither — checked at MCP v1.4.3 AND at the
  newest tag v1.4.7, so this is the wiki page not being edited yet, not a
  stale clone. `_gate_aas` drops any AA name the class data does not list,
  so until the page is edited and re-mined, an LLM naming Strike As One
  has the rec removed with an `info` log line. That is the correct
  failure — the alternative is trusting the model on whether an AA
  exists — but it means the fix is a data refresh, not a code change:
  re-check `dist/data/eqlbuilds/meta.json`'s revision after each MCP
  release. The class guide carries the ability in prose meanwhile.
- **`Rujarkian Hills` (zone id 901) is live in the client roster and has
  no assets we can point at.** `Resources/ZoneNames.txt` lists it `12^60`
  — a real level band, not one of the ten `0^0` LDoN-shaped
  "The Rujarkian Hills: <wing>" rows — so `scripts/zone_coverage.py`
  reports one MISS. Nothing resolves it: no `*ruj*` file in the game
  folder, no chart in the stock `maps/`, nothing in eqlbuilds' client-mined
  `zones.json` (checked at v1.4.7), and no `spells_us.txt` teleport row
  naming a short zone. The Brewall packs ship `ruja`..`rujg`, which are the
  LDoN instance wings — aliasing 901 to one of those is precisely the
  wrong-dungeon failure the no-fuzzy rule exists to prevent, so it stays
  unresolved. The client on this machine is dated 08-17, so the assets may
  simply arrive with the patch: re-run the coverage script after the client
  actually updates, and only then look for the short name.

## Smaller items

- **Three dead rows in `MECHANICS`.** The table holds 16 rows for 13 distinct
  mechanics: Dragon Roar, Feared (Dragon Roar landed) and Frost Breath each
  appear twice, byte-identical. Inert — the parser loop `return`s on the
  first match — so this is tidying, not a fix. Noticed 2026-08-19 while
  counting mechanics for the trigger starter set.
- **Loot filter action codes are contested.** `backend/loot_filter.py`
  maps `{1 store, 2 loot, 3 merge, 4 sell}`; 1 vs 2 was never confirmed
  against the game's own UI. Everything downstream is read-only, so a
  wrong label is cosmetic — but it is wrong in the merge notices if so.
- **The leveling Gantt caps at 8 rows** (`.slice(0, 8)`). Fine for
  readability; raise it if anyone wants every candidate for their level.
- **Item wiki coverage is partial.** 53 of 79 owned items resolved a wiki
  line during the clicky work, so ~1 in 3 items contributes nothing to
  clicky detection or gear comparison. Worth measuring properly before
  assuming it is a name-resolution bug rather than genuinely absent pages.
- **Macro / social export**, seen on the EQL tool codex. We already tell
  people to type `/log on`, `/who`, three `/outputfile` commands,
  `/alternateadv list` and `/pet inventory check`, and we already write
  `LO*.ini` spell sets, so a copy-paste social block has precedent. Small,
  low differentiation.

## Unparsed log lines worth having (measured 2026-08-04)

Prompted by a taxonomy in Moonchopper/EQDeeps (MIT) and cross-checked
against a real 90MB EQL log rather than taken on trust. Counts are actual
occurrences in that log, so the value of each is known before any work
starts. Nothing below is parsed today.

- **Consider messages carry the MOB LEVEL — 885 occurrences.** `A large
  plague rat scowls at you, ready to attack -- looks kind of risky, but
  you might win. (Lvl: 22)`. We have no source of mob level anywhere. It
  would let hunting advice say what the player is ACTUALLY killing instead
  of inferring from a community zone table, and would give encounters a
  difficulty axis. Highest value of the set.
- **Mez break — 142.** `A greater skeleton has been awakened by Bellrain.`
  We already broadcast the mez APPLY half and CLAUDE.md calls breaking a
  mez the classic group error; this is the half that names who did it.
  Small, and an alert people would want.
- **Taunt — 737 success, 737 failure.** `Kenann has captured a Teir`Dal
  ranger's attention!` / `Konektik failed to taunt a necro initiate.`
  Real, but only matters to a tank. Leave until someone asks.
- **`<Player> activates <Ability>` — 371.** Other people's ability usage.
- **Stance changes — 46.** `You assume a defensive stance.` We surface
  stances from the MCP data but never notice one being taken.

NOT worth adding, verified absent from EQL logs: INVULNERABLE, tell-window
echo (`A -> B: text`), custom channels, fellowship chat, and the classic
direction-only faction lines ("got better"). All are live/TLP formats.

EQDeeps also warns that two log entries can concatenate onto one physical
line. That appeared twice in 90MB and BOTH were a player pasting a log
line into guild chat, which the existing chat guard already handles — so
the hazard is real for live EQ and not for us.

## Pet names may be a lookup, not a guess

EQDeeps notes that game-generated pet names follow consonant-cluster
patterns (its examples: `Xobtik`, `Jobekn`) and that reliable
classification wants a **petnames list**.

This matters because it contradicts something already written down as
unfixable. The group filter currently guesses at pets from absence of
evidence — never appeared in a /who, never spoke — and marks the row
`pet?`. A real player's filtered list was `Gabartik`, `Xektik`,
`Libektik`, `Kebantik`, `Jabeker`: obviously the same generator.

EQ builds these from a fixed syllable table, so a complete list is an
EXACT lookup and does not breach the no-fuzzy-matching rule that governs
zone names. If a usable list exists (EQDeeps may vendor one; live-EQ
tables have been published), the `pet?` heuristic becomes a fact, the
not-counted list stops being cluttered by other people's pets, and ally
pets could fold into their owner properly.

Worth checking whether such a list exists and what licence it carries
before assuming it can be vendored.

---

## Adopting from everquest-companion (jmoyers)

**Status:** compared 2026-08-13 against its README and feature site
(<https://github.com/jmoyers/everquest-companion>,
<https://jmoyers.github.io/everquest-companion/>). Source not read; claims
below are from its own documentation, so verify before copying a mechanism.
MIT-adjacent check needed before vendoring anything — see NOTICE.md rules.

Same premise as ours: log file only, no memory reading, no injection. It is
Electron/TypeScript, Windows-only, borderless mode required. So its wins are
in PRESENTATION and RETENTION, not in access to better data — everything it
draws, our parser already sees.

### 1. Per-hit retention, and the two features it unlocks

**The one architectural gap.** `state_tracker.apply()` folds every hit
straight into counters (`abilities[name] = {hits, total, crits}`), so an
encounter remembers totals and nothing else. `timeline` is 2s buckets of
TOTAL damage — one lane, no attribution.

They keep the individual events, which buys them two things we cannot
currently build at any price:

- **A fight timeline with one lane per skill**, marking hit / miss / resist
  along the fight, with scroll-to-zoom, drag-to-pan and a Fit button.
- **Per-hit drill-down**: click a fight, see every hit, miss and resist that
  made the total.

Cost is smaller than it sounds: a 4-minute fight at ~2 swings/sec is ~500
events; cap per encounter and retain only for the encounters already held in
memory. `PERSISTED_EVENTS` should NOT grow — this is in-memory per fight,
dropped when the encounter rolls off, exactly like `timeline` today.

Do this first. It is the only item that unblocks others, and "why did that
fight go badly" is a question our Encounter panel currently cannot answer
beyond totals.

### 2. Zone-scoped "Overall" aggregate

Theirs aggregates every fight in a zone to answer "is this ability worth
casting" over a long session. Ours stops at `ability_summary()` — the last 5
pulls — which is a different and much shorter question.

Cheap for us: encounters already carry `zone` in the payload
(`_persist_milestone`), so this is a rollup over stored rows, not new
plumbing.

**Belongs in the WEB panel, not the overlay.** The overlay dropped its
last-5 aggregate deliberately (see CLAUDE.md, "The overlay meter is the
CURRENT fight only") and that reasoning holds here — it is a planning
question, and the overlay is a glance surface.

### 3. Sort quests by closest to completion

Their Plane of Sky tracker sorts class Test quests by nearest-to-done so you
can see what is actually achievable. Trivial for us — the Quests tab already
computes `have`/`needed` for rows where the count is known. Sort those
first, descending by fraction complete, ahead of the rows with no bar.

Smallest good idea on this list. No data work at all.

### 4. Shareable trigger strings

They share alerts as paste-safe strings that PREVIEW before importing, and
export a whole config bundle that deliberately contains "no file paths, no
window positions, and no character progress".

We already have the hard half: `data/tracked_rules.json`, and
`POST /api/tracked-rules` replaces the set whole. What is missing is
encode/decode plus a preview step.

Worth doing because a guild can standardise on one trigger set. It does NOT
reopen the TTS decision (CLAUDE.md: voice callouts stay out, point people at
eql-alerts) — sharing rules and speaking them are separate questions.

Copy the exclusion list verbatim as a principle: a shared bundle must carry
no paths, no window geometry, no character state.

### 5. Named / raid-target kill history

They track raid boss defeats across difficulty tiers with kill counts and
dates. We have per-mob `kills/xp/coin_copper/loot_drops` and lifetime totals
derived from `log_events`, but nothing distinguishes a named from a trash
mob.

**Do not guess at "named" from the mob's name.** No leading article, title
case, apostrophes — every heuristic here is the fuzzy-matching trap the zone
table exists to avoid.

What IS evidence, and is new since 2026-08-12: we now parse the instance
difficulty tier (`RE_DIFF_TIER`, "Plane of Hate D2"). Recording the tier on
the kill gives a real axis without inventing one. A curated named list from
the wiki would be the other honest route.

### 6. Config bundle export

Same shape as 4, one level up: overlay prefs, panel prefs, triggers, and the
non-secret half of app_config. `secrets.json` must never be in it — that
separation is the entire reason the file exists (CLAUDE.md, Settings &
secrets).

### Deliberately NOT adopting

- **Voice packs / TTS.** Standing decision, unchanged.
- **Recipe consumption in item knowledge.** We model no tradeskills at all,
  and the data cost is high for a question our Quests tab does not ask.
- **Telemetry, even off by default.** We collect nothing; that is a feature.
  Their optional log scrubbing on feedback submission is a good idea IF a
  "send your log" bug flow ever exists here. It does not.

### Where we are ahead, and should not regress chasing this list

Advisor and gear counsel with deterministic verification gates; the Quests
tab across every item rather than one raid zone; the whole Atlas (charts,
mined geometry, textured 3D, routing); buff timers — theirs is documented as
"early, still rough" while ours does tier scaling, cooldown shaves and
oracle-line snapping; the group-filtered meter built on the EQL
shared-damage rule; session persistence across restarts; pet adoption and
un-mapping; Mac and Linux under Wine against their Windows-only Electron;
and a 43MB single .exe against an Electron runtime.

---

## More from everquest-companion, measured against a real log (2026-08-14)

Follow-up to the adoption list above. Each item below was TESTED against
1,755,201 lines of this project owner's logs rather than judged from their
docs, so the numbers are what we would actually get, not what they get.

Their proc analytics were the first thing taken from this survey and are
already done (see the per-event cast window in state_tracker).

### 1. Attack rounds — the one genuinely new measurement

Their `attack-round-stats.md` groups swings per (second, target) and reads
double/triple attack out of the round size. Our timestamps are second-
granular, so this drops straight in. Measured:

```
rounds (second+target+verb)  86,808
multi-swing rounds           13,140   15.1%
swings per round             1:73,668  2:12,066  3:916  4:137  5:17  6:3
```

**Their caveat is the important part**: "same-second 2x on a WEAPON verb may
be two hands, not a double". So the headline 15.1% conflates dual wield with
double attack. The way through is to read it off verbs that cannot be dual
wielded:

```
verb      rounds   multi%    dual-wieldable?
kick      14,687    14.1%    no  <- clean double-attack read
bash       4,132     7.3%    no  <- clean
slash     22,096    16.6%    yes (contaminated)
crush     15,644    22.4%    yes (contaminated)
```

Kick and bash are the honest signal. That is a real skill/AA effect a player
would want to watch improve, and nothing in the app measures it today.

### 2. Special-attack RATES, which we have the counts for but not the denominator

We already parse and keep the stacked mods. Over the same logs: Riposte 557,
Slay Undead 477, Finishing Blow 424, plus stacked forms (Riposte Critical
40, Riposte Slay Undead 3). What we show is raw counts per ability; their
doc normalises "flurry rate over primary attack rounds". Rounds from item 1
ARE that denominator, so this comes almost free once rounds exist.

### 3. Incoming attack profile

What is actually hitting you, by the attacker's verb, over the same logs:
punch 24,662 · hit 20,691 · bash 18,374 · kick 16,231 · slash 12,597 ·
cleave 8,500 · pierce 7,548 · crush 4,040. We keep `damage_taken` and a
last-5-pulls incoming profile; a session/lifetime breakdown of what is
landing on you does not exist and needs no new parsing.

### 4. Buff uptime — feasible, but NOT as simple as pairing cast to fade

67 distinct spells faded across the logs. The trap is that fades mix three
different things: our self-buffs, our debuffs on mobs, and mob debuffs on
us. `tangling weeds` shows 62 fades against 0 casts by us, which is proof
the set is not ours alone. Buff-fade lines carry a target (the mez/charm
break signal), so the split is available — but it has to be done, not
assumed, and the naive version would report uptime for spells the player
never cast.

### Not worth taking

- **Proc SOURCE attribution** (`ProcLink`, concentration ratios,
  `MIN_INACTIVE_SWINGS = 200`). Good work, and their instinct matches ours —
  they refuse to call Instrument of Nife "exclusive" on 1,084 active hits vs
  12 across 289 inactive swings because the control group is too small. But
  it is a feature rather than a fix, and it claims a source the log never
  names. Revisit only with a clear appetite for correlation-grade answers.
- Anything requiring lockout state: the log carries none, see the raid
  section above.

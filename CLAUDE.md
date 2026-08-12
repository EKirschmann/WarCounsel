# CLAUDE.md

Guidance for AI coding assistants (and humans) working in this repository.

# WarCounsel — Real-Time Log-Aware Assistant

A real-time companion for EverQuest Legends: tails the combat log, tracks the
character, and provides a live HUD (vitals, war ledger, encounters), an Atlas
(charts / mined geometry / textured 3D), and a wiki-grounded Advisor (spells,
AAs, gear, hunting spots). Passive by design — it never touches game files or
memory. User setup lives in **README.md**; this file is architecture,
invariants, and conventions.

**Stack**: FastAPI backend + polling log tailer + Next.js 14 frontend (app
router, TypeScript, hand-rolled CSS) + WebSocket live feed + optional LLM.

## Running for development

`start_companion.bat dev` — or by hand:

```
uvicorn backend.main:app --reload      # backend :8000 (from the repo root)
cd frontend && npm run dev             # UI :3000
```

END USERS run production mode (`start_companion.bat` with no args): uvicorn
WITHOUT --reload + `next start` serving the build from `.next-prod`
(~350MB lighter, no file watchers). Production builds use a SEPARATE dist
dir (`NEXT_DIST_DIR=.next-prod`), so a running dev server and a prod build
can no longer corrupt each other. The launcher **auto-rebuilds** the prod
UI when any frontend source is newer than the last build (a stale
`.next-prod` once served an old version). While iterating, prefer `dev`
mode — its `--reload` has occasionally wedged in production launches, and
a lite deterministic mode powers a planned single .exe (see below).

**Single executable** (`build_exe.bat` -> PyInstaller onefile, ~44MB,
~4s cold start; BUILT AND VERIFIED on Windows 11). Everything works
except screen OCR: HUD, overlay, Atlas 3D with textures, and LLM counsel.
FastAPI serves the static `frontend/out` at `/` (same-origin, `api.ts`
auto-detects; `next.config` `NEXT_EXPORT=1` static-exports — REBUILD IT or
the exe ships a stale UI); `run_companion.py` is the only entrypoint and
also dispatches the helper windows.

Hard-won, all of it load-bearing:

- **`backend/paths.py` owns the two roots.** `bundle_path()` = read-only
  assets from `sys._MEIPASS` (a temp dir wiped on exit); `data_dir()` =
  writable state beside the .exe, or `%LOCALAPPDATA%` when that is
  read-only. NEVER write state under the bundle. Source mode is unchanged
  (`./data`).
- **Helper windows go through `child_command()`**: frozen, `sys.executable`
  IS the app and `-m backend.overlay` would boot a second server, so the
  overlay/OCR calibrator use `--overlay` / `--ocr-overlay` flags.
- **Windowed builds have no console.** `sys.stdout` is None; uvicorn's
  colour formatter calls `.isatty()` on it, so `run_companion` adopts the
  streams onto `data/companion.log` and passes `log_config=None`. pywebview
  demands the MAIN thread, so uvicorn runs on a worker and closing the
  window shuts down through the normal lifespan.
- **Optional deps must never abort startup.** `ocr_system` catches
  `Exception`, not `ImportError` — a half-present rapidocr raises
  `FileNotFoundError`. Texture export failures degrade the 3D view to
  untextured rather than losing the zone.
- **`requirements-lite.txt` decides what the exe can do**, because
  PyInstaller only bundles what the BUILD MACHINE has installed. The LLM
  clients are in it deliberately: the settings panel offers an API key
  field. `llm_runtime.available()` probes at runtime and the panel greys
  out what is missing.
- **There is a SECOND packaged variant: `WarCounsel-OCR.zip`**
  (`requirements-heavy.txt`, `build_exe.bat heavy`, the `build-ocr` CI job
  — same app, screen OCR included). Three things about it are deliberate:
  - **It is `--onedir`, not `--onefile.`** A one-file bundle re-extracts
    its whole payload to a temp dir on EVERY launch — that IS the ~4s cold
    start — so the cost scales with size. At 200MB that tax would land on
    every start, which is also why OCR is not simply added to the lean
    build: the people who never enable it would pay for it forever.
  - **The size is opencv, not the OCR engine.** Measured 2026-08-08:
    cv2 112.4MB, onnxruntime 42.5, numpy 30.8, rapidocr 15.6, mss 0.4 —
    204.6MB total, against a 43.6MB exe. `mss` is 0.4MB and is never the
    problem, whatever the error message suggests. **opencv-python-headless
    does NOT help** (112.0MB — the same 82MB `cv2.pyd` on Windows; the
    ~40MB figure quoted for it is the WHEEL). What IS droppable is
    opencv's 29.4MB `opencv_videoio_ffmpeg*.dll`, a video codec that OCR
    on still screenshots cannot reach; the build deletes it.
  - **CI asserts `/api/ocr/status.deps_ok` on the built artifact.** The
    import guard in `ocr_system` is broad on purpose (a half-present
    rapidocr raises `FileNotFoundError`, not `ImportError`), so a broken
    OCR bundle looks exactly like a working one until someone enables it.
    `deps_ok` alone proved too weak — `run_companion.py --ocr-check`
    (mirroring `--overlay-check`) runs the REAL engine over a rendered
    "X: 1234" and fails unless the digits come back.
  - **Build the OCR release on PYTHON 3.12.** The engine renamed itself and
    the two packages are not interchangeable: 3.12 gets
    `rapidocr-onnxruntime` v1, which SHIPS its ONNX models; 3.13 gets
    `rapidocr` v2, which ships none and DOWNLOADS them on first use.
    `--collect-all` cannot bundle what does not exist, so the 3.13 build
    passed every import check and then hung inside the engine waiting on a
    download — 114 minutes of CI before anyone looked. A packaged build
    must work offline, the same reason `maps/` and `zem_levels.wiki` are
    bundled. Every CI step that runs the engine carries `timeout-minutes`,
    because this class of failure WAITS rather than erroring.
  - **Verify on the Python CI actually builds with.** The v1/v2 split meant
    a local check on 3.12 passed while the shipped 3.13 build was broken —
    the local run never touched the same package.
  - The two jobs are INDEPENDENT (no `needs:`): the optional download must
    never hold back the exe most people use.
  - `Windows.Media.Ocr` is not an alternative — it silently drops short
    lines like "Z: 4", which is precisely the data this reads.
- The packaged updater cannot pull or rebuild a source tree, and the exe
  cannot overwrite itself while running — it points at the releases page.

- `--reload` restarts on .py changes and re-reads `.env`; editing `.env`
  alone does NOT trigger a reload — touch a backend file or restart.
- Typecheck with `npx tsc --noEmit` (from frontend/).
- The backend needs the configured `EQL_GAME_DIR` (see `.env.example`);
  without a log file it runs in a degraded no-data mode.

## Backend map

```
backend/
├── main.py              # FastAPI app, REST + /ws, lifespan, flush loops, caches
├── config.py            # pydantic-settings; EQL_GAME_DIR derives Logs/ + maps/
├── llm_runtime.py       # runtime-switchable LLM (none|lmstudio|openai|custom|...)
├── session_state.py     # tracker snapshot/restore — sessions survive restarts
├── wiki_http.py         # no-Node wiki fallback (MediaWiki api.php -> text)
├── mcp_client.py        # stdio client for the EQL MCP server (+ HTTP fallbacks)
├── builds_data.py       # direct reader of the eqlbuilds snapshot (levels, ids)
├── spell_file.py        # client spells_us.txt reader (proc + lifetap sets)
├── spellsets.py         # read/WRITE the game's LO*.ini saved spell sets
├── game_data.py         # wiki/builds grounding, verification helpers, ZEM table
├── spellbook.py         # /outputfile export parsing (spellbook/inventory/...)
├── state_tracker.py     # CharacterTracker — session state, DPS, ledger, encounters
├── ws_manager.py        # WS connection list + broadcast
├── models.py            # SQLAlchemy: characters, chat_messages, log_events
├── map_system.py        # Atlas charts: map-file parsing + zone travel graph
├── geometry_system.py   # .s3d/.wld mesh extraction (2D floors/walls + 3D)
├── ocr_system.py        # screen OCR position feed (RapidOCR; Windows)
├── overlay.py           # sectioned session overlay (tkinter; Windows)
├── overlay_prefs.py     # which overlay sections/fields are shown
├── log_system/          # events.py (pydantic), parser.py (ALL regex), watcher.py
└── agent/               # advisor.py (LLM counsel + gates + builtin mode),
                         # graph.py (chat), prompts.py, tools.py, state.py
```

Frontend: `app/page.tsx` (3-panel HUD), `components/` (CharacterPanel,
AtlasPanel + Atlas3D, CompanionPanel, AdvisorPanel, WarLedger,
EncounterPanel), `hooks/useWebSocket.ts`, `lib/api.ts` + `lib/types.ts`.
All styling is CSS custom properties in `app/globals.css` — **no Tailwind**.

## Log pipeline (the spine of everything)

- **watcher.py**: polling tailer (0.4s), binary reads with byte offsets,
  cp1252 decode (EQ logs are NOT utf-8), truncation guard (size < offset
  resets to 0), `last_growth` staleness stamp surfaced via `/health`.
  On startup it either restores the previous session (below) or replays the
  last 1MB as *uncounted* seed events to establish zone/level/ledger.
- **parser.py**: every regex lives in one table at the top. Verified against
  real EQL logs — melee/miss both directions (verbs incl. frenzy "on"/
  cleave/smite/reave/shoot), EQL DoT ticks all THREE shapes ("from your X",
  incoming "You have taken N from X by Y", casterless proc "has taken N
  damage by X"), plain + incoming non-melee, damage shields (ours = ds_out
  aux damage: totals yes, swings/crits no; others -> other_out), exp
  percent lines, upgrade-loot (count/sold/merged/banked-to-depot forms),
  coin (corpse/split/vendor-sale/from-that-item), casts (casting|singing),
  named fizzles/interrupts + bard forms, resists both directions, faction,
  item merges, destroys, kills, `/who` char_info, `/loc`, AA list bursts +
  the "You now have N ability points" total (authoritative for unspent),
  pet ownership. STACKED trailing tags "(Riposte) (Critical)" peel before
  matching -> `crit` flag on damage events (session + per-ability counts).
  A CHAT GUARD drops speech lines before combat matching (players quote
  combat text); pet tells parse before it. PC-name patterns allow
  backticks/apostrophes (Asaka L`Rei).
- **Third-person casts** parse as `other_cast` ("A froglok novice begins
  casting Inner Fire."). First person is "begin", third is "begins", so the
  two never collide. Mob casts are the only warning before something lands;
  they surface per-encounter as `other_casts`.
- **Heals: the trailing " by <Spell>" is OPTIONAL and the healer is NOT
  player-shaped.** Requiring both silently dropped ~19k mob self-heals in a
  90MB log — a mob healing itself is often why a fight will not end.
  Unattributed heals group under a "Direct heal" row.
- **An ally's pet gets its OWN row**, mirroring how ours is split from
  "You". Folded in, this app's view of a groupmate would be them PLUS their
  pet while their own copy shows the two apart — the numbers could never be
  compared, which is the main reason a group runs this side by side.
- Other players' hits parse as `other_out` but are never broadcast — they
  only feed per-encounter group DPS. Own pets fold into the player
  ("Pet: <source>" rows, incl. pet DoTs via the "by <caster>" form);
  others' pets fold into their owner's ally row. Pets AUTO-MAP with zero
  user action: the pet's tell ("<pet> told you, 'Attacking X Master.'")
  only ever prints in the OWNER's log ("/pet leader" still works and is
  the hint fallback). A mapped "pet" that damages YOU un-maps instantly
  (charm broke); a mapped pet slain (or killed by us as a mob) un-maps.
- `/pet inventory check` logs a burst ("Your pet has the following items
  equipped:" or "does not have any items equipped") + slot lines, parsed
  into `tracker.pet_inventory`. A MAPPED pet (`/pet leader`) appears as its
  own "(pet)" row in the group-DPS breakdown ("You" there is player-only
  so the split never double-counts); its abilities show in the encounter
  Pet section. Exaltation proc damage is labeled "(exaltation)"; effects
  that are ALSO scribed spells label only when the client spell file marks
  them proc-granted AND no cast was seen this session (spell_file.py; log
  evidence beats static data).
- XP AND corpse-coin attribution are FORWARD-FIRST: EQL prints the reward
  lines BEFORE their kill line, so both hold as pending and are claimed by
  the next kill (own, mapped pet, or ally "has been slain by X") within
  3s. A pending reward whose window EXPIRES unclaimed falls back to the
  kill just before it (≤3s) — covers loot-the-corpse-later coin and
  trailing party XP; naive backward attribution mis-credited every tick
  during chain pulls, so forward claims always win. Per-mob stats carry
  kills/xp/coin_copper/loot_drops (drop-rate groundwork). Per-mob XP and
  the XP box reset on level-up.
- Heals name their healer ("Bosh healed itself for 159 (210) hit points
  by Spirit Tap") — encounter heal rows key "Spell — Healer". Incoming
  avoidance parses per defense verb (block/dodge/parry/riposte/miss) into
  the per-fight defense line. Loot-and-auto-sell lines tag "(sold)".
- Exaltation procs share the spell-damage line shape; effects granted by
  owned stones (wiki-mined into tracker.exalt_effects at startup/export
  refresh/character switch) label ability rows "(exaltation)" — MINUS any
  effect that is also a scribed spell UNLESS spell_file.py marks it
  proc-granted and the session never saw it cast (mislabeling real casts
  is the worse error, so ambiguity still resolves toward no label).
- **Trailing tags are KEPT, not just crit-folded** (`mods` on the outgoing
  damage events → per-ability counts). EQL prints Slay Undead, Finishing
  Blow, Crippling Blow, Strikethrough, Flurry and Double Bow Shot beside
  Critical; collapsing them all to a bool threw away the only record that a
  class proc fired. Stacked tags stay whole ("Riposte Slay Undead" is one
  annotation in the log, not two).
- **"<mob> staggers." is a stun landing on a mob** — ~14k lines in a 90MB
  log, previously unparsed entirely. "YOU" is never the subject, and the
  line names no attacker, so crediting it means remembering the last
  ability WE landed *and on whom*: the gate requires the staggered target
  to match, within 2s. Without the target check it credited whatever we
  last swung, which produced obvious nonsense (Crush, Damage Shield
  (thorns)). About HALF the staggers in a group log are other players'
  strikes and are deliberately left uncredited. Attribution can still
  over-credit when two people hit the same mob in the same second — the
  log carries nothing that would resolve that.
- **`staggered` is aggregate-only, never broadcast** (`PERSISTED_EVENTS`'
  sibling list in main.py): 14k raw rows would bury the War Ledger.
  `mesmerized` (~200) IS broadcast — the mez APPLY half, pairing with the
  fade half we already had, and breaking a mez is the classic group error.
- **Adding an event type**: model in `events.py` → regex + branch in
  `parser.py` → (optional) count in `state_tracker.apply()` → (optional) add
  to `PERSISTED_EVENTS` in main.py → `case` in WarLedger `classify()`.
  Unknown types render as dim raw rows, so nothing breaks if you skip the UI.
- **Parser coverage test** (run after any EQL patch):
  `python scripts/parser_coverage.py` — runs the vendored real-log
  fixture (tests/fixtures/, from kpxcoolx/eql-meter, MIT) AND your
  newest live log; a category dropping to zero means a format broke.
  Also parsed: rune absorption, the "magical skin absorbs" defense verb
  (both directions), self-hurt lines (damage TAKEN, never dealt, no
  encounter), faction caps, random rolls, raid /who rows (Group: N is
  not a race; AFK prefix tolerated), and possessive pet swings
  ("Kenkyo`s warder bites" rewrites to the "<Owner> pet" convention).

## characters is UNIQUE on (name, server)

It was UNIQUE on `name` alone until 2026-07-28, which failed two ways:

- **Startup crashed outright.** A row written before the server was known
  has `server` NULL, which no `(name, server)` lookup can match, so
  `_sync_character_row()` inserted — and hit the name constraint.
  `IntegrityError` inside the lifespan means "Application startup failed".
  It now ADOPTS a server-less row and backfills the server.
- Two characters sharing a name on different servers could not both exist,
  which quietly contradicts the per-character isolation the lifetime totals
  depend on.

The old constraint was a plain unique INDEX, so the migration drops and
recreates rather than rebuilding the table. It REFUSES and logs if
duplicate `(name, server)` pairs exist rather than deleting anyone's rows
to force the index through.

## When the numbers stop moving

A stalled tailer is INDISTINGUISHABLE from a quiet night: the overlay
simply shows the last values forever. Log health therefore rides the
snapshot, not only `/health`, so both surfaces can explain themselves.

- `log_stale_s` — seconds since the file last grew; `log_seen_growth` is
  False when it has not grown ONCE since startup, which is the frozen case
  and must not look like healthy idling.
- `newer_log` — a log NEWER than the watched one belonging to a DIFFERENT
  character. `discover_log_file()` picks at startup only, so rolling a new
  character leaves the backend tailing the old file with no symptom beyond
  frozen numbers. This is the launch-day report.
- The overlay renders one red line for these and nothing at all when
  healthy — silence while idling is normal and must stay silent.
- **Never rewrite the ex-style without re-asserting the alpha.**
  `_set_click_through()` adds WS_EX_LAYERED/WS_EX_TRANSPARENT via
  `SetWindowLongW`, but Tk ALREADY made the window layered when it applied
  `-alpha`. Touching the layering style bit drops the layer attributes, and
  a layered window without them paints solid BLACK — the whole widget, with
  the render loop ticking normally and nothing in any log. Reported as "the
  overlay was just black" while the web UI updated fine. The call now
  re-applies `SetLayeredWindowAttributes` immediately after. Symptom is
  machine-dependent (DWM/driver), so it will not reproduce everywhere.
- **`_render()` has no try/except and reschedules itself on its LAST
  line**, so any exception there freezes the overlay permanently while
  leaving the window on screen. The pollers already swallow their own
  errors. Exercise the render sweep (56 snapshot × preset × compact
  combinations) after touching that path.

## Pets on the meter

- **A pet fights BEFORE it identifies itself.** Its first swings land while
  it is still an unknown name, so they go to `allies` — which never feeds
  `total_out` — and the mapping that arrives later only redirects FUTURE
  damage to `own_pet`. The result was the same pet on two rows and its
  early damage credited to a stranger and missing from the session.
  `_adopt_pet_damage()` folds the ally bucket in on mapping and raises
  `total_out` AND `damage_dealt` by the same amount. That adjustment is
  REQUIRED: the "You" row is `total_out - pet_total`, so folding without it
  drops You by whatever was adopted. Both mapping routes (pet tell and
  `/pet leader`) call it.
- Own pets are labelled `<name> (pet)`, matching the `<owner> (pet)` that
  ally pets already used. A generated pet name on a meter is otherwise
  indistinguishable from a player. The `<name> pet` convention stays plain
  "Pet" — it already says pet.

## The overlay meter is the CURRENT fight only

No last-5 aggregate: that is a slower question and the web Encounter panel
answers it with room. Removing it also removed the encounters poller —
`section_summary` took `history`/`segment` and used NEITHER, so once the
aggregate went, nothing read `/api/encounters` and the overlay had been
fetching five encounters every five seconds for data it never drew. The
whole header now toggles Damage/DPS.

**Hint lines must be MEASURED against W, not eyeballed.** The interactive
hint was 455px of Consolas 7pt in a 300px window, so the last 40% — the
lock and close shortcuts, the two you need when the overlay is in your way
— was off the edge with nothing hinting more existed. Two lines now, 235px
and 255px, checked with a font metric rather than by looking.

## Sessions (rollover + history)

"Welcome to EverQuest Legends!" (login banner) is the ONE session
boundary: a live banner archives the current session summary (only if
meaningful — kills/xp/loot/damage/deaths) into tracker.pending_sessions
(drained to the DB as event_type="session" rows by the flush loop) and
ZEROES per-session state; knowledge (roster, pet owners, owned AAs,
cast evidence) survives. `tracker.rates()` supplies per-hour numbers
per ELAPSED and per ACTIVE hour (2-min activity buckets, log-time
clocks — AFK never poisons rates; pattern per EQBuddy) plus an
hours-to-level estimate (exact only after a same-session ding).
`GET /api/sessions` = live summary + history; the Vitals panel shows a
"Past sessions" table.

## Timers & alerts (no TTS by design)

- **Spell timers** start from OUR cast lines (tier-stripped name looked
  up in backend/alert_data.py SPELL_TIMERS — community-measured EQL
  durations vendored from kpxcoolx/eql-alerts, MIT; collisions kept the
  SHORTEST) and CANCEL on own fizzle/interrupt/outgoing resist. Tier
  scaling of durations is NOT modeled — timers under-promise.
- **Raid mechanics** (MECHANICS battery) match at the very END of
  parse_line — only lines nothing else recognized — and emit
  ev.MechanicTimer (boss shouts survive the chat guard: NPC shouts have
  no comma). Timers surface in snapshot["timers"], the overlay TIMERS
  section, and a Vitals list.
- **Tracked rules** (backend/alerts.py, data/tracked_rules.json):
  SUBSTRING-only matches (never regex) on loot/kill/death/zone/tell/
  fade/interrupt/fizzle/cast/mechanic/mez ("*" = match all) plus
  "bighit" (pattern = damage threshold); 5s per-rule cooldown; live
  events only; mtime-reloaded on edit.
  - **A rule kind is only half the work — the event must FIRE it.** The
    last five kinds were added in 2026-08 for a Discord question ("can you
    trigger on a spell interrupt, like GINA?") whose answer was no for no
    good reason: `ev.CastInterrupted` had been parsed all along, spell name
    and all, with nothing wired to it. When adding a kind, grep
    `_fire_alerts` in state_tracker.py — a kind that reaches no event is
    invisible and looks exactly like a rule that never matches.
  - `KIND_HELP` states what each pattern is compared AGAINST ("fade" sees
    `"<spell> (<target>)"`, "cast" sees `"<caster>: <spell>"`). The panel
    renders it, because a pattern aimed at the wrong half of the string
    fails silently and forever.
  - **`load_rules()` drops disabled rules; `all_rules()` does not.** An
    editor needs the disabled ones — they are what it exists to switch back
    on — and the seeded examples all ship disabled, so the enabled-only
    `GET /api/tracked-rules` reported an EMPTY list on every fresh install.
  - `POST /api/tracked-rules` replaces the set WHOLE (no merge: a list has
    no per-field identity, and merging makes deletion impossible — the
    opposite of the API-key rule). Written atomically; every reader,
    including the overlay in its own process, picks it up by mtime.
  - "cast" fires OUTSIDE the encounter window on purpose: a mob's cast line
    is the only warning before it lands, and the most useful one is the
    fight that has not started yet.
  BUILT-INS need no rules: "You have been summoned!" and your name in
  group/guild/raid chat always alert. Tells parse BEFORE the chat guard
  (Tell/GroupChat events; group_chat never enters the ledger/WS). Fired
  alerts ride snapshot["alerts"]; the OVERLAY renders the banner and
  plays the winsound chime (nothing else beeps) — it paints
  `"<kind>: <text>"` generically, so a NEW kind needs no overlay change.
  Rules are edited under Settings ▸ Triggers (TriggerSettings.tsx, which
  renders the kind list from the API the way the overlay switchboard
  does). TTS deliberately omitted — point users at the standalone
  eql-alerts app for voice callouts.
  - Still NOT GINA: no matching on arbitrary log lines (only the kinds
    above), no regex or capture groups, no per-trigger text/sound/timer,
    no package import. Those are in TODO.md, and the no-regex rule is a
    decision to revisit deliberately, not to erode.
- **Overlay hotkeys are POLLED, not registered** (`_poll_hotkeys`, extending
  what Ctrl+Alt+X already did): the overlay is click-through and unfocused, so
  it receives no key events, and `RegisterHotKey` would need its own message
  pump. Ctrl+Alt+<key> because EQ binds bare and shifted keys but leaves that
  combination alone. Keyboard, hotkeys and the tray menu ALL route through the
  `act_*` methods so the three cannot drift.
- **The overlay is a glance surface, not a small dashboard.** The webapp
  already covers session analytics with room to breathe; the overlay's job
  is answering "how am I doing right now?" without pulling your eyes off
  the fight. So its contents are a CHOICE (`backend/overlay_prefs.py` ->
  `data/overlay_prefs.json`, edited under Settings ▸ Overlay): every section
  toggles, and every field WITHIN a section toggles, because "session line
  but not the coin" is a real preference a section switch cannot express.
  For TIMERS the fields are the KINDS (spell / cooldown / raid) — that is
  the distinction that actually matters there.
  - Defaults are ALL ON, so a missing file behaves exactly like before.
  - The overlay re-reads the file on every repaint (mtime-cached, the same
    shape as `alerts.load_rules()`) rather than over HTTP — it is a separate
    process on the same box painting twice a second. Changes land in ~0.5s
    with no relaunch, which is why the Settings block saves on click instead
    of on the modal's Save button.
  - `save()` merges onto CURRENT prefs, so an omitted key is left alone
    rather than springing back on — the same rule the settings panel already
    follows for API keys. Only the file-READ path falls back to defaults (a
    section a newer version added).
  - `SECTIONS`/`PRESETS` are the single source of truth: the panel renders
    from them over the API, so the switchboard cannot drift from what the
    overlay paints. Presets are `Everything`, `Combat focus`, `Meter only`.

## The WEB panels have their own switchboard

`backend/panel_prefs.py` -> `data/panel_prefs.json`, edited under Settings,
and DELIBERATELY separate from the overlay's. A 42px strip and a 340px
column answer different questions -- you want a damage meter and nothing
else while fighting, and the full session ledger while planning -- so one
shared set of toggles would mean hiding deaths mid-fight also hides them
when you sit down. Same SHAPE as the overlay's (per section, per field,
defaults all on, `save()` merges onto current, `SECTIONS`/`PRESETS` are the
source of truth the panel renders from), so there is one pattern to learn.

- `frontend/lib/panelPrefs.ts` fetches once and re-reads on an
  `eql:panel-prefs` event the Settings pane fires after each save, so a
  toggle lands without a reload. **`show()` returns TRUE when the prefs have
  not arrived or the key is unknown** — a settings feature that blanks the
  UI while loading its own config is worse than no settings feature.
- Ledger rows key on the EVENT TYPE (`LEDGER_FIELD`), not on `classify()`'s
  colour kind: "milestone" covers a level-up, a coin split and a faction hit
  at once, so hiding loot by colour would take the ding with it. An unlisted
  or brand-new type falls to `misc` and still renders.
- **The HUD grid's column widths now live in `page.tsx`, not CSS.** They
  depend on three things at once — which panels Settings left on, which are
  collapsed to a 42px strip, and the viewport — and the old form was four
  hand-written `:has()` combinations that each assumed all four panels
  existed. Switching one off made every one of them wrong. React writes
  `--hud-cols` / `--hud-cols-wide`; the stylesheet's rules consume them so
  the media queries still decide which applies. The panels announce a
  collapse with an `eql:collapse` window event.
- Combat-mode and slim-ledger rules address `.vitals-panel` / `.enc-panel`
  by CLASS. `> .panel:last-child` silently retargeted the ledger the moment
  the encounter panel was switched off.
- Quests is a TAB, not a column, so its switch hides the tab button; if it
  was the open tab the Advisor shows rather than an empty stack.
  - When exactly ONE section survives, its header is SUPPRESSED — there is
    nothing to tell it apart from, and the 15px buys another row.
- **Timers are depleting tracks, not a text list** — the one place besides
  the damage meter that gets a bar, because it is the one place a
  sub-second read changes what you do next. Fill = `remaining/seconds`
  (both already in the snapshot), colored by kind. Under 5s the WHOLE row
  washes red with bright text: an expiring timer has almost no fill left,
  so it cannot use bar length to carry the warning. Do not "fix" that back
  to dark-on-fill — the most urgent row becomes the least readable.
- **Tray icon** (`backend/overlay_tray.py`, pystray): the way back to an
  overlay that is hidden or dragged off-screen — it has no title bar and is
  usually click-through, so otherwise there is nothing to click. Runs
  `run_detached` (its own thread + message pump) and marshals every callback
  through `root.after`, because Tk calls must happen on the thread owning the
  window. Fails soft. pystray imports its backend lazily, so packaged builds
  need `--hidden-import pystray._win32`; the release build runs
  `--overlay-check` to prove it, since the overlay is a child process the
  server smoke test never reaches.
- **Ability cooldowns**: cast/activation of ABILITY_COOLDOWNS entries
  (LoH 900s, Harm Touch 1200s, Quick Buff 600s) starts a "cooldown"
  timer under the TIER-STRIPPED canonical name; a landed Smite/Reave
  SHAVES 60s off its cooldown (COOLDOWN_SHAVES); the game's oracle
  line ("You can use the ability X again in M minute(s) S seconds.")
  SNAPS the timer exact whenever it prints.
- **Buff-fade lines carry a target** ("worn off of <target>" — the
  mez/charm-break signal): fades cancel the matching spell timer and
  fire "fade"-kind rules; "Your pet's X" fades are recognized and
  excluded.
- "Your active classes are ..." (Composition) sets the trio like /who
  when all three names resolve. Session stats also track stuns_taken,
  OVERHEAL (the parenthesized potential heal value), and motes by
  tier. Encounters carry "trio" (per-trio DPS comparison via
  GET /api/trio-compare) and a 2s-bucket damage "timeline" (the
  Encounter panel sparkline).
- **`class_str` has TWO writers with DIFFERENT orderings, and anything
  keyed on the string must expect both.** The /who parse keeps the GAME's
  order ("[3 WIZ/BST]" -> "Wizard/Beastlord"); a manual trio edit joins
  the Advisor dropdowns in SLOT order (AdvisorPanel `next.join("/")`).
  One real loadout therefore reaches the DB under two spellings, which
  split trio-compare into two rows that could not be compared to each
  other -- the whole point of the panel. `/api/trio-compare` now keys on
  the SORTED class set and displays the newest spelling. Stored payloads
  are NEVER rewritten: they record what the app believed at the time.
  The manual edit is also why a trio can change BEFORE the /who that
  confirms it (observed: 33 minutes early) -- do not treat a clean
  timeline break as proof of a real class change.
- **Encounters carry `zone` and `level` in the PAYLOAD.** `LogEventRow`
  has five columns (id/character_id/event_type/payload/ts) and no zone.
  `_persist_milestone` takes the queue dict's `zone`/`level` and writes
  them to the CHARACTER row, so reading `r.zone` off an event row raised
  AttributeError on every trio-compare request once ANY encounter carried
  a trio tag. Both are captured at encounter CREATION, not at flush time:
  a fight is often the last thing before a zone line, so `tracker.zone`
  has already moved on by the time `pending_encounters` drains.

## All-time totals (`GET /api/lifetime`)

DERIVED from the stored `log_events` rows, not accumulated into a counter.
Those rows are already written per character as play happens, so there is
no second source of truth to drift, and the live session is included for
free — a kill persists the moment it happens.

- **Totals start at LAUNCH** (`settings.eql_launch_iso`), not at the first
  log ever read. Beta play belongs to a character that need not have
  survived, so counting it would inflate a fresh character with someone
  else's history. NOTE the stored `ts` uses a SPACE separator
  ("2026-07-05 13:16:57") while the setting is ISO with a "T" — compared as
  strings the mismatch silently matches nothing, which has bitten this
  codebase twice, so the bound is normalised before use.
- **Isolation is `character_id`.** Two characters never blend, and neither
  do same-named characters on different servers, which get separate rows.
  The panel refetches on character change and resets to the session view.
- Counts come from event rows (`kill`, `death`, `loot`, `level`, `aa`,
  distinct `zone`); combat totals are SUMmed out of the persisted
  `encounter` payloads via `json_extract`, which already carry
  total_damage / damage_taken / total_healing / duration / peak_dps.
- **`coin` and `exp` joined PERSISTED_EVENTS on 2026-07-28** so lifetime
  could show them at all; they were headline session numbers with no
  stored row. All-time coin and XP therefore begin at that date while
  everything else reaches back to the first log this install read, which
  is why the response carries a `partial` list and the panel says so.
- `Coin.copper` is resolved at PARSE time. `amount` is prose ("3 gold, 5
  silver"), so a stored row could not be summed without re-parsing every
  string.
- The view defaults to the session, not all-time: the session answers "how
  is tonight going", which is what a glance mid-play wants.

## Session persistence (survives restarts)

`session_state.py` snapshots the tracker (counters, ledger, encounters,
mob stats, rosters, owned AAs) plus the log byte offset to
`data/session_state.json` every 3s and on shutdown. On startup, if the
snapshot matches the active log file, the tracker restores and the watcher
resumes from the saved offset — downtime lines replay through the normal
live path (counted once, persisted once). The 60s DPS window is deliberately
not restored. Advisor/gear consults persist to `data/advice_cache.json`
(signatures normalized to strings — see `_sig_norm` in main.py).

## REST + WS surface

WS `/ws`: `hello` (snapshot) on connect, `events` batches (~6 frames/s),
throttled `state` pushes. REST highlights (see main.py for all):

- `GET /api/character` (snapshot) · `PATCH /api/character` (trio/level/AA/slots)
- `GET /api/characters` + `POST /api/character/select` — multi-log switching
- `GET /api/events|encounters|chat/history` · `POST /api/chat`
- `GET /api/advisor` / `GET /api/gear` — LLM consults; `?refresh=1` forces,
  `?cached=1` returns the cache instantly or `{"cached": false}` WITHOUT
  running the LLM (the tab restores results on load; consults are
  button-press only, never automatic)
- `GET/POST /api/llm` — runtime model switch; clears both consult caches
- `GET /api/hunting` — deterministic leveling-zone candidates (Gantt chart)
- `GET /api/spellbook|aas|exports` · `POST /api/exports/refresh|aas/rescan`
- `GET /api/spellsets` · `POST /api/spellsets/generate` — read the game's
  saved spell sets / write the counsel as one (source=loadout|prebuffs,
  optional names[] from the UI checkboxes; gems auto-stacked DD, DoT, AoE,
  heals from gem 8, utility, pets; loadout set "companion", buff set
  "prebuffs"; one-time .companion-backup beside the LO*.ini)
- `GET /api/update-check` (badge click + 6-hourly poll; API with plain
  tags-page fallback) · `POST /api/update/run` (spawns the updater in its
  own console window)
- `GET /api/map|zones|route|geometry|geometry3d|texture/{short}/{name}`
- `POST /api/overlay` — toggle (launches or kills; `GET` reports state)
- `GET/POST /api/overlay/prefs` — section/field visibility (below); the
  GET also serves the SCHEMA and PRESETS the Settings panel renders from
- `GET/POST /api/tracked-rules` — alert rules; GET includes DISABLED rules
  and the kind list, POST replaces the set whole
- `GET/POST /api/ocr/*` — screen-OCR position feed config

## Atlas invariants (hard-won — do not "fix")

- Map files store (-locX, -locY): a `/loc` position plots at `(-x, -y)`.
- WLD axes are swapped vs `/loc` (wld_x = locY): geometry vertices plot at
  `(-wld_y, -wld_x)`; the 3D hero sits at (locY, locX, z).
- **EQ winds triangles CLOCKWISE**: classification negates the geometric
  normal and the 3D payload re-emits CCW for three.js FrontSide culling.
- Materials with render method 0 are invisible collision shells — dropped
  (they read as phantom ceilings). Ceilings are never extracted.
- 3D camera: follow mode translates camera + orbit target by the hero's
  delta (user angle/zoom preserved); panning off-target releases the lock.
- **Difficulty comes in TWO shapes.** `RE_DIFFICULTY` handled the
  parenthetical form ("Befallen 4 (Refined)") and nothing handled the bare
  tier EQL appends to instanced zones ("Plane of Hate D1"), so a public D1
  instance charted as nothing at all — issue #7. `RE_DIFF_TIER` strips it.
  Verified against the client's own `Resources/ZoneNames.txt` first: no zone
  in any of the 699 rows ends in D<digits>, so the strip cannot eat a real
  name. That check is the evidence the no-fuzzy rule demands.
- Zone names: `normalize_zone()` strips DECORATORS only — difficulty suffix
  ("Befallen 4 (Refined)"), leading article, and EQL's "Expedition" instance
  wrapper ("New Sebilis Expedition" → "New Sebilis"). New zone = `ZONE_FILES`
  (+ `ZONE_ALIASES`, `ZONE_GRAPH` adjacency) in map_system.py.
  - **Deliberately NO fuzzy/edit-distance matching.** The names most likely
    to be confused are exactly the near-identical pairs — Upper vs Lower
    Guk, North vs South Karana, New vs Old Sebilis — so a close-enough
    match silently draws the WRONG dungeon. Anything past decorator
    stripping goes in ZONE_ALIASES by hand.
  - **A mapping needs EVIDENCE, not name resemblance.** "New Sebilis
    Expedition" is an EQL-only Iksar city off Northern Desert of Ro (the
    community table types it City 1-5; Old Sebilis is 40-60). Aliasing it
    to Old Sebilis on the strength of the name drew a Kunark dungeon for a
    starting city — the same wrong-map failure the no-fuzzy rule exists to
    prevent, just reached by hand. It has its OWN assets, `newsebexp.s3d`
    and `newsebexp.txt`, which is what finally settled it. The `.s3d`
    ships with the game so 3D works for everyone; the chart does NOT, so
    `newsebexp.txt` is VENDORED in the repo's `maps/` folder.
  - **`_maps_dirs()` searches bundled maps LAST**, after the custom pack and
    the stock `<game>/maps`, so a chart the user installs always wins. The
    folder exists only to fill gaps where a zone ships geometry but no
    chart — which reads to the user as a blank panel with no explanation.
    `/api/settings` reports `bundled_maps` and CI fails the build at zero,
    since a missing data file fails soft and would ship silently.
  - An earlier version stripped a trailing "Expedition" from zone names,
    guessing it was an instance wrapper like the difficulty tier. It is
    not — the one zone it applied to is a real zone — so that rule is
    gone. Do not reintroduce it.
  - An alias must point at a key that EXISTS and is spelled the way
    `normalize_zone()` leaves it. "estate of unrest" → "The Estate of
    Unrest" pointed at a nonexistent key (the article is already stripped)
    and suppressed the direct hit that would otherwise have worked.
  - **The ZEM sheet and map_system are TWO NAME SPACES — bridge them with
    `game_data.zem_entry_for()`, never by comparing strings.** The hunting
    sheet keys on WIKI names ("The Hole", "Mistmoore Castle", "Western
    Karana"); the log, tracker and map_system key on the GAME's ("Ruins of
    Old Paineel", "Castle Mistmoore", "West Karana"). Nine zones spelled
    differently and nothing reconciled them, which broke BOTH directions:
    the leveling chart could recommend a zone that `find_route_ex` then
    could not resolve ("no route known" for a zone two hops away), and
    looking up the zone you are STANDING in answered "not in the sheet"
    while its row sat there under the other spelling — a camp-value
    prototype cheerfully advised moving to The Hole while standing in it.
    Both sides reduce to `_canonical()` first, the same fix
    `/api/trio-compare` uses for `class_str`. `hunting_candidates()` now
    also returns `key` (the map spelling, or None when genuinely
    unplaceable). `scripts/zone_coverage.py` fails if any sheet name stops
    bridging; it was 64/73 before 2026-08-09 and is 73/73 now.
  - **The client ships the authoritative roster: `Resources/ZoneNames.txt`**
    (`id^long name^lo^hi`). The long name is EXACTLY what "You have entered
    X." prints, and `lo`/`hi` are `0^0` for every zone EQL does not run — 77
    live zones at launch, out of 699 rows. `scripts/zone_coverage.py` walks
    it through `_canonical()`, so a zone we cannot chart is found BEFORE a
    player walks into it. **Do not guess a short name from the long one**:
    `spells_us.txt` teleport rows carry `name^0^<short zone>` (row 54915 is
    how "The Ruins of Old Paineel" was proven to be `hole`), and the .s3d
    must exist on disk. That pairing is the evidence the no-fuzzy rule
    demands.
  - `_canonical()` logs an unresolved zone once. A miss fails SILENTLY —
    the panel just shows nothing — which is how New Sebilis Expedition went
    53 visits with no chart while sebilis.txt/.s3d sat in the game folder,
    and how 14 more (The Hole, both Neriak dash spellings, the Planes, the
    Warrens, Runnyeye, Splitpaw, Mistmoore, the Qeynos Aqueducts) survived
    to 2026-08. Run the coverage script after a patch rather than waiting
    for the report.
  - **An alias is consulted BEFORE the direct `ZONE_FILES` hit, so a bad one
    is worse than none.** `"castle mistmoore" -> "Mistmoore Castle"` pointed
    at a key that does not exist AND suppressed `"Castle Mistmoore"`, which
    was right there and would have worked. Same shape as the Estate of
    Unrest note above; the coverage script catches both.
  - Zones reached only by ritual (the Planes) get ZONE_FILES entries but no
    ZONE_GRAPH edges — chart and 3D work, routing to them does not.
    `Lake Nerius` is an .eqg zone: chart-only, since geometry_system reads
    s3d/wld. `Plane of Hate` resolves to the 2001 revamp `hateplaneb` (the
    client keeps both files; only hateplaneb has EQL emitter resources), with
    the original as fallback — swap the candidate order if a layout is wrong.
- Routing (`find_route_ex`, /api/route): walk edges + NAVAL TRANSLOCATOR
  dock cliques (any dock -> any dock on the route, one hop; boats do not
  exist on EQL) + druid/wizard PORT RITUALS as jump-from-anywhere edges
  (?ports= overrides the trio-based default — rituals persist once
  leveled). Data per rari/eqltools (CC0). `path` stays a plain zone list
  for old clients; `steps` carries {zone, via} labels.
- **`backend/eqclient.py` reads eqclient.ini to tell two failure modes
  apart**: logging never switched on (user must type `/log on`) vs logging on
  but quiet (just wait). Both look like "no data" otherwise. When the game is
  RUNNING and its own `Log=` is 0, `_sync_hints` raises an `urgent` hint that
  the UI renders as a banner. Deliberately READ-ONLY — other companions flip
  `Log=1` themselves; this one does not write a game file it was not asked to
  write. Both the ini read and the process scan are cached (the hint runs on
  every snapshot, ~6/s).
- Position feeds: `/loc` lines always; optional screen OCR (RapidOCR — the
  Windows OCR engine silently drops short lines like "Z: 4").
- **Position is INTERPOLATED, linearly, over the feed's measured cadence**
  (`frontend/lib/glide.ts`, used by both the 2D chart and the 3D hero).
  Fixes arrive ~1/s, so easing out — or snapping — makes tracking visibly
  step: an ease-out brakes to a standstill inside every tick and waits.
  Do not "improve" this back to an easing curve or a fixed duration.
  First fix, zone-line jumps, and reduced-motion snap on purpose.
- **Geometry endpoints serve CACHED BYTES, never a dict**: the payload is
  already JSON on disk, so parsing it just to have FastAPI re-serialize
  cost ~0.55s on a 15MB zone. Its gzip is cached beside it too (immutable
  per .s3d), which is why the response sets Content-Encoding itself —
  GZipMiddleware leaves an already-encoded response alone. Cache writes
  are atomic + shape-checked on read, since nothing parses them anymore.

## Advisor — "the LLM proposes, structured data disposes"

The house pattern: **every LLM suggestion is machine-verified before
display**; failing entries are dropped and logged, never shown. The gates
(game_data.py + advisor.py):

- Loadout picks must be OWNED and at/below the character's level; the
  spellbook is split into "usable now" vs "scribed for later" in the prompt.
- Travel magic (SPAs 26/83/88/104 + name patterns) is stripped — rings/
  circles/zephyrs/gate/succor are RITUALS in EQL, never memorized.
- Resurrection lines (SPA 81) are dead slots for solo focuses.
- `supersedes_for_slots`: same primary effect + sign + target + identical
  class set, higher magnitude (NONCOMPARABLE_SPAS {32,33,85,113}; zero-base
  rank-1 records fall back past id-10 charisma spacers). Owned picks
  superseded by another owned usable spell are dropped.
- Long-duration buffs route to a separate `prebuffs` section.
- **A pre-buff is decided by TARGET and EFFECT, not by duration.** Owning a
  spell that lasts 14 minutes says nothing about whether you cast it on
  yourself before a pull. Ensnare was offered as a pre-buff because nothing
  asked who it lands on, and Treeform because nothing asked what it does —
  self-target, 36 minutes, and it roots you in place. `_is_prebuff()` is the
  one test all three paths share (`_long_buffs` for the prompt,
  `_backfill_prebuffs` for the deterministic additions, `_gate_prebuffs` for
  the verifier); before it, each checked a different subset.
  - `_BUFFABLE_TARGETS = {6, 41, 43, 51}` — self, single friendly, and the
    two group forms. Read off spells whose purpose is unambiguous (Stun,
    Fear and Ensnare are 5; Befriend Animal is 9; Feral Spirit is 14) rather
    than assumed from the id, the same evidence rule the zone table follows.
  - Root (SPA 99) and charm (22) joined `_NOT_A_BUFF_SPAS` alongside
    invisibility and the remote eye.
- **Cap AFTER supersession, never before.** The spellbook runs low level to
  high, so truncating it kept Skin like Rock and Center and cut the Skin
  like Steel and Symbol of Transal that replace them. Identical in shape to
  the `missing_spells` shopping list, where an ascending cap kept the 25
  LOWEST and anyone with a backlog got an empty list.
- **`_gate_stacking` must consider EVERY claimed slot.** It used to `break`
  at the first one, so a spell occupying two slots resolved one conflict and
  stopped: Skin like Steel displaced Center on `ac-slot-1` and never reached
  `druid-spell-lines-hp-ac`, where Skin like Rock was still sitting, so the
  pair it supersedes survived beside it. Displaced entries are TOMBSTONED
  rather than removed — `claimed` holds indices into `kept`, and compacting
  mid-loop invalidates them.
- **Equal magnitudes are broken by the PLAYSTYLE, not by list order.** Skin
  like Steel and Protection of Steel are the same 50 AC / 50 HP for the same
  36 minutes; the only difference is who else it lands on. `_effect_shape`'s
  fallback kept whichever came first, which handed a `solo_dps` character
  the group form of every armour buff. `_prefers_group()` decides it —
  solo prefers the single-target twin, grouped prefers the group one. A
  TIE-BREAK only: a stronger group buff still beats a weaker single one.
- A group form the curated table does not carry inherits its twin's verdict
  when the player owns that twin (paired on identical effect SHAPE and
  magnitude, never on the name — "Protection of" resembling "Skin like" is
  what the no-fuzzy rule exists to prevent). When the twin is NOT owned the
  group form survives uncompared, which is the partial-coverage rule working
  as intended. **Do not "fix" that with a subset rule** — Holy Armor's
  effects are a subset of Skin like Steel's at lower magnitudes, and it
  occupies `ac-slot-4`, so the two genuinely stack; a subset rule would drop
  exactly the buff this section was fixed to restore.
- **Pre-buffs are capped at `spell_slots`, the same gem count as the
  loadout** (`_cap_prebuffs`). They are cast by memorizing one, casting it
  and swapping the gem back, so a seventeen-entry routine against a
  fourteen-slot book describes something nobody can do in one pass — and the
  overflow was silent. PERMANENTS are kept first wherever they were
  proposed: cast once, held until death, so they earn a gem far more cheaply
  than anything re-cast between pulls. The prompt states the same limit; the
  cap enforces it, per the house rule that the gate is authoritative.
- **Magnitude orders the pre-buff list; it must not decide membership.**
  "hit points 50" over "armor class 21" over "strength 5" ranks three
  unrelated numbers. Sorting by it and then capping at 8 is how Holy Armor,
  Strength of Earth and Shield of Brambles went missing — small numbers,
  real buffs, nothing superseding them.
- **Locations are gated against the community Recommended-Levels table**:
  the raw WIKITEXT is parsed (the rendered page collapses empty cells) from
  in-era sections only (Antonica/Odus/Faydwer + Planes of Fear/Hate/Sky —
  Kunark/Velious never parsed). Live wiki first, then the VENDORED snapshot
  `backend/zem_levels.wiki` (same raw wikitext, so one tested parser reads
  both — refresh with `scripts/refresh_zem.py`, which refuses a fetch that
  parses to zero or loses a quarter of its zones). The fallback is not
  cosmetic: `_gate_locations()` reads an EMPTY table as "no table" and lets
  the model's zone picks through UNGATED, so before this a failed fetch —
  or any packaged .exe with no network — silently disarmed the location
  verifier. The snapshot is never cached under the live key, or it would
  suppress the next real fetch for a day. `/api/settings` reports its zone
  count and CI fails the build if it did not survive packaging.
  **ZEM multipliers remain deliberately unpublished** by the wiki ("we have
  opted not to publish specific Zone Experience Multipliers") — that
  section is measurement methodology only, so there is nothing to mine. The 2026-07 redesign carries per-level
  QUALITY circles (efficient/ok/poor/special), explicit level ranges, and
  a zone Type column: candidates rank efficient > ok > stretch, cities
  exclude themselves by Type (efficient-marked rows exempt — the sheet is
  mid-edit), bands merge range+marks when they disagree, and the prompt
  says to strongly prefer EFFICIENT zones. At most ONE stretch pick
  survives; deterministic backfill if the model under-picks. Same data
  feeds `GET /api/hunting` and the Leveling-chart Gantt.
- **Buff SLOTS are checked (`backend/spell_lines.py`)**: EQ buffs occupy
  effect slots and two spells in one slot OVERWRITE each other, so a loadout
  holding both Center and Bravery (`ac-slot-1`) has wasted a gem. The
  SPA-based `supersedes_for_slots` cannot see this — slot occupancy is not in
  the effect data. `_gate_stacking` keeps the STRONGEST spell per slot
  (curated lines run weakest to strongest) across must_have+should_have
  together, runs BEFORE the promote step so a freed gem refills, and gates
  prebuffs too (worst place to stack: the second cast silently wastes the
  first's mana). Data is rari/eqlfinest's curated `paths` table (CC0),
  vendored as `backend/spell_lines.json` — 112 lines, 344 spells. Coverage is
  PARTIAL (~66k spell records exist), so every helper answers "don't know"
  rather than guessing, and a spell outside the table is never dropped:
  absence of data is not evidence of compatibility.
- **Clickies** (`_clickies`, deterministic, every gear consult): owned items
  whose wiki `Effect:` line classifies as clicky via `_exalt_socket_type` --
  the same classifier the exaltation code uses, so the word means one thing.
  Worn/focus/PROC effects are excluded: they fire on their own, and listing
  them buries the ones needing a keypress (a real inventory was 7 procs to
  1 clicky). A clicky is invisible unless you remember the item has one.
- **Spell vendors** (`game_data.spell_vendors`): the wiki spell page's
  `where_to_obtain` table gives zone, NPC, guild and COORDS -- but only in
  the WIKITEXT; the rendered page flattens it, hence
  `wiki_http.fetch_page_wikitext`. Parse notes: de-pipe `[[A|B]]` BEFORE
  splitting rows on `|`, or a piped zone link splits into two fields; and
  use function replacements in `_delink`, since a mis-escaped `` silently
  substitutes a control character instead of the capture. Attached to
  `advice["purchase"]` for spells buyable NOW only -- a buy-ahead entry is a
  reminder, not a shopping trip, and each lookup is a wiki round-trip.
  - `missing_spells` is capped at 25 but now sorted level-DESCENDING first.
    Ascending kept the 25 LOWEST, so anyone with a backlog of skipped
    low-level spells had the cap fall below their own level and got an
    EMPTY shopping list, silently, since an empty section just hides.
- **Permanent buffs** (self-target + zero durationTicks, minus
  travel/summon/pet/FD/res SPAs) are listed in the prompt with a
  never-say-"refresh" instruction — Instrument of Nife-class buffs last
  until death.
- Deterministic extras: a vendor "purchase" list (near-level missing
  spells, buy-ahead marked), nice_to_have backfilled with owned
  non-superseded alternatives when the LLM lists few, and cached counsel
  restores after ANY restart via `?cached=1` — marked `stale` when the
  context moved on instead of being discarded. Consults are button-press
  ONLY, never automatic.
- Tiered loadout: must_have / should_have fill the spell slots exactly;
  nice_to_have offers swaps. Spell levels annotated from the spellbook.
- **AA counsel is gated**: `/alternateadv list` never prints ranks (it just
  lists each ability once), so the roster's rank counter is unreliable. The
  OWNED rank is RECOVERED by matching the log's current-effect number
  against the eqlbuilds per-rank ladder ("memorize 1/2/3/4/5/6 additional
  spell" + log "6 additional" => rank 6). Maxed AAs and already-owned/
  beyond-max ranks are dropped.

- **A pre-launch PET INVENTORY is flagged too.** `pet_inventory` is
  deliberately NOT cleared on a session roll, because pet gear genuinely
  survives death and re-summon — only a fresh `/pet inventory check` clears
  it, and it persists across restarts. That is right within an era and wrong
  across a wipe: a beta list describes a pet that no longer exists while
  still gating what the advisor suggests handing over. `_pet_inv_ts` (now
  persisted) is compared against the launch boundary; the snapshot carries
  `pet_inventory_stale`, the panel reads "Was holding (BETA)", and the sync
  hint is urgent.
- **Pre-launch exports are flagged, not just aged.** `_pre_launch()` compares
  a file's mtime against `settings.eql_launch_iso` (2026-07-28). An export
  from beta is not merely stale: a character need not survive a launch, so
  every owned-spell and owned-item gate could be reasoning about someone who
  no longer exists. "146h old" reads as slightly out of date and gets
  ignored; "from BETA — re-export" does not. Exports carry `pre_launch`, the
  chips say `beta`, and the sync hint is URGENT. The exports themselves have
  no internal timestamp — mtime is the only signal available.

**Owned state** comes from `/outputfile` exports parsed in spellbook.py
(`<Name>_<server>-...-<Kind>.txt` in the game dir): Spellbook, MissingSpells,
Inventory, Achievements — plus owned AA ranks from `/alternateadv list` log
bursts. Sync chips + `sync_hints` tell the user the exact command when
something is missing/stale. Bump the version int in the export cache key
whenever the Inventory parse changes.

## Gear advisor

- **An ANY SLOT item is not swung: it contributes STATS ONLY.** No damage,
  no delay, no white-DPS index — those apply to Primary and Secondary
  alone. `item_stat_vector` includes DMG and DELAY, so comparing the raw
  vector let a weapon win an Any Slot on damage it will never deal:
  reported live, where a 3.5-index blade was offered over a Cracked Femur
  for a slot that swings neither. Stripped of DMG/DELAY the femur has
  `SV_DISEASE 5` and the blade has NOTHING, which is the real comparison.
  The gear prompt states this too — the model was reading the index
  annotations, which are emitted for any 1H weapon regardless of slot.
  ONE exception: a Piercing dagger in an Any Slot enables Backstab for a
  trio containing a Rogue. The deterministic path does not model backstab
  and will therefore under-recommend a dagger there — the safe direction.
- The slot table shows the 23-slot EQL roster (CANON_SLOTS): two generic
  **Any Slots** (any equippable item, stats live), paired Ear/Wrist/
  Fingers, Ammo — **no Charm or Power Source in EQL**, and **no Held**.
  The client writes a Held location in the export, but the in-game UI has
  no such slot and nothing is known to fit it, so a row permanently
  reading "nothing owned equips here" was noise. It is not deleted so much
  as unlisted: `_fits_slot` still demands an explicit HELD token, and
  `_full_slot_table` appends any WORN slot outside the roster, so the row
  returns by itself the day an item appears there.
  Unaddressed slots backfill as keep/empty rows (`_full_slot_table`).
- Wiki item stats are BASE (+0) values, and the eqlwiki Item Level
  slider's formula (ext.itemLevelSlider JS) is PORTED into game_data.py
  (`scale_item_line`, mirroring its Excel rounding + float op order):
  gear-context lines are pre-scaled to each item's owned +N — primary
  stats +1/level at base<=10 else ~+10% of base/level, DMG
  +floor(base*N/10), haste/regen +1/level, weight −9%/level, emergent
  "SV VOID: +N" when 2+ qualifier stats — so the LLM compares REAL
  numbers (a strong +0 can honestly beat a worn +2). Never re-scale an
  already-scaled line. STATS UNKNOWN items are still never replaced.
- Gear is usable if ANY ONE of the trio can use it (`[USABLE]` pre-tags;
  wiki Race: lines are stale classic-era data and are stripped).
- **Merge notices** (`_merge_opportunities`, deterministic, every gear
  consult incl. builtin): 2+ owned copies of one base item (any mix of
  worn/bags/bank; wiki-gated to real equipment so stacks never flag) list
  under "Merge opportunities" with the predicted result from the wiki
  slider progression model — an item at +N embodies 2^N base copies, so
  equal ranks merge to exactly +N+1, unequal ranks to partial progress
  ("+4 + 1/16"). Copies hosting an exaltation stone are flagged.
- A 2H primary recommendation deterministically drops the secondary rec.
- Deterministic gates every gear rec must pass: it must be OWNED, fit the
  item's wiki **Slot** line, be **trio-usable** (the `[USABLE]` tag is
  advisory — the gate enforces), not a same-item lower/equal rank, and a
  recommended 2H primary empties the Secondary ROW. Rows whose rec IS the
  worn item render dimmed (status, not a suggestion).
- **Exaltation sockets are in the Inventory export** (game-authoritative):
  gear child-rows Slot7..Slot10 encode socket TYPE {7 focus, 8 clicky,
  9 worn, 10 proc}; the number outranks the wiki-wording heuristic BUT
  only when the stone sits in real gear (bags reuse 1-10 as positions —
  `_socket_type_from_export`). Move targets require an EMPTY socket of
  the stone's number when the export has data (real exports show proc
  sockets on earrings/faces, so export data OVERRIDES the wiki
  "proc->weapon" rule); wiki heuristics remain the fallback.
- **Loot filter** (backend/loot_filter.py, read-only): LF_<Char>_<server>
  .ini in <game>/userdata; caret rows id^filter^icon^name; actions
  {1 store, 2 loot, 3 merge, 4 sell}; skip `[..]`/`#` lines; the game
  REWRITES it live (mtime-cached). Feeds merge notices + /api/loot-filter.
- **Weapon white-DPS indices** (`weapon_indices`; model per
  xaziaver/eql-weapon-inflection-analyzer, MIT): the 1H MAIN-HAND damage
  bonus is a FLAT delay-independent add (floor((level-25)/3), L28+) so
  fast MH wins beyond ratio; off-hand swings ~(6*level+5)/400 of the
  time with NO bonus. Gear lines carry [white-DPS index: MH x / OH y]
  for 1H weapons; INDEX not absolute (ATK/AC unknown), procs excluded.
  The DETERMINISTIC path uses it too (`_wpn_index`/`_weapon_beats` in
  advisor.py): a 1H swap needs a strictly higher index for its hand (MH
  Primary / OH Secondary) AND no OTHER stat lower. **DMG and DELAY are
  deliberately EXCLUDED from that stat check** — judging them apart is
  what makes a fast weapon lose (7/30 "loses" to 7/42 on delay alone
  under a plain Pareto vector, which is how a real upgrade stayed
  invisible), and combining them is the index's whole job. Not decidable,
  so skipped: 2H (empties the secondary), any non-Focus `Effect:` (a
  proccing weapon can beat a higher index), and RANGE (bows/thrown are
  not modeled — that row SAYS it was not compared rather than letting the
  backfill claim nothing better was found). Both sides scale to their
  owned +N first, so a MERGE re-decides the swap in either direction.
  The loop walks CANON_SLOTS, **not `worn.items()`** — an EMPTY slot is
  absent from `worn`, so iterating it meant empty slots were never
  compared while `_full_slot_table` backfilled "nothing owned equips
  here", a verdict on a comparison that never ran (same shape as the
  RANGE message above). An empty slot compares against a ZERO baseline.
  CANON_SLOTS is ordered Primary before Secondary because the builtin
  path now needs its own 2H guard: "a 2H primary drops the secondary
  rec" lived ONLY in the LLM path, which was harmless while weapons were
  skipped and became reachable the moment an empty off-hand could be
  filled.
- **Exaltations** (informational, NOT prescriptive moves — the real
  socketing rules per eqlwiki/eqlegendstools are now known): a stone shows
  its granted effect, ACTIVE vs DORMANT-until-LN (Effect "at Level N" vs
  the character's level), stat-stone/class-usable status, current host,
  and **"can socket into"** — the OWNED items it may legally move to.
  Rule: PROC (Combat) stones need a shared class between SOURCE and TARGET
  item (weapon->weapon, 2H proc -> Primary only); focus/clicky/worn need
  shared class + same slot. All from wiki Class/Slot/Skill lines.
- **Pet loadout** — pets are a BAG of N generic slots, NOT the player's
  slot layout (do not invent Head/Arms/Chest rows). Mechanics encoded:
  every pet is base Warrior + a secondary by pet type (Water=Rogue,
  Fire=Wizard, Earth=Ranger, Enchanter=Paladin, Beastlord=Berserker,
  Necro/SK=Shadow Knight — user picks via the "pet 2nd class" dropdown).
  It equips gear usable by its TWO base classes PLUS the player's trio
  (up to FIVE classes), Attunable only (No-Drop excluded). Slots
  auto-compute: 4 base + per-class modifiers (Beastlord/Magician +3,
  Necro +2, Enchanter/Druid/Shaman +1) when a pet-summoning class is in
  the combo; `pet_slots` field overrides. `/pet inventory check` (in the
  outputs macro) is parsed as a burst -> `tracker.pet_inventory`; the gate
  drops items already on the pet / not class-usable / not spare. Priorities
  in the prompt: up to 2 weapons — a pet keeps its OWN attack delay, so
  weapon DELAY and the damage/delay RATIO mean nothing to it (we said
  "by damage/delay" until 2026-07; wrong per eqltools/learn/pets). Its
  damage counts only when it BEATS the pet's innate hit, while procs and
  damage type apply either way — so a low-damage proccing weapon is a TOP
  pick, not a poor one. Then haste belt, AC over HP, no duplicate
  categories, 510 stat cap. Slot count caps at 12, which the 4+3+3+2
  maximum reaches exactly, so the cap never binds. Pet gear
  PERSISTS through death/re-summon. `pet_slots`/`pet_classes` are user-set
  columns; controls live inline in the Equipment header.

## Item facts learned from exports (`backend/item_facts.py`)

The wiki is NOT the only slot authority. For a WORN row the Inventory
export's Location column IS the slot, and the game only allowed the item
there if the character could use it — so slot and trio-usability come free
and exact. Stats stay wiki-only and are still REFUSED when missing.

- **Keyed on item ID, never the name.** An id is stable across +N merges
  (`Boots of the Long Road` and its `+2` share `177708`), so one wearing
  teaches the fact once and forever, on any character.
- **`Any Slot` is excluded from learning** — it accepts anything
  equippable, so an item sitting there proves nothing about where it
  belongs.
- **The slot of an item never yet worn is NOT inferred.** That guess would
  read as knowledge and be wrong invisibly — the same failure the no-fuzzy
  zone rule exists to prevent.
- `set_stats()` takes numbers a PLAYER read off the item, stored as a
  wiki-shaped compact line so `_fits_slot` / `item_stat_vector` /
  `weapon_indices` consume it unchanged. Those lines carry **`PRE-SCALED`**
  and `scale_item_line()` REFUSES to touch a line bearing it: a player
  reads stats at the item's CURRENT rank, and the slider formula expects
  base values. The rule used to be "callers must not re-scale"; the line
  now says so and it is enforced.
- Launch added a block around id 69xxx with no wiki pages, including worn
  gear. Wiki-less items with a `+N` are the ACTIONABLE `unknown` set — only
  equipment merges to a rank, so no consumable pollutes the list — while
  the prompt still lists every wiki-less item as STATS UNKNOWN so the model
  cannot invent numbers.
- **`HELD` is not a wildcard.** `_fits_slot` treated it like `Any Slot`,
  which put a Secondary-only dagger there. Only `Any Slot` is permissive.
- **Specific slots resolve before `Any Slot`.** `CANON_SLOTS` lists the
  wildcards first for DISPLAY; iterating that order let one claim a Chest
  robe before Chest was considered, after which `used` blocked its real
  home.

## Group-filtered meter rows

**AN EQL GROUP HOLDS FOUR.** Not the six of the EverQuest this reimagines.
Player-supplied; nothing in the log states it, and assuming the classic
number is the same error the wiki's classic-era item pages make. It is a
WARNING (`over_cap` on `/api/group`), never an enforced cap: the roster
gates the meter and extends the combat clock, so dropping a name silently
would hide real damage, whereas an over-full roster only means something
wants a look.


**EQL DOES NOT ALLOW SHARED DAMAGE.** Once a mob is tagged, only the tagger
and their group can damage it. That single game rule is what makes the
meter tractable: a non-groupmate landing hits on something that looks like
our mob is DEFINITIONALLY on a different one that shares a name. There is
no case where crediting a stranger is correct, so the gate fails CLOSED —
an empty roster means solo, and a solo player has no allies.

It used to fail OPEN on an empty roster, reasoning "no evidence, credit
everyone". That was wrong: the game rule IS the evidence. Randoms kept
appearing in the overlay for precisely that reason.

The ally gate checks the TARGET ("did they hit one of our foes"), and
`_foe_key` can only compare mob NAMES because the log carries no mob IDs —
so a stranger fighting a DIFFERENT mob of the same name is credited as an
ally. Observed live: two "Spirit of Dessication" at once. That half is
unfixable, so the gate moved to the side that CAN be verified — the
contributor.

- Roster from `<Name> has joined/left the group.` PLUS group-chat senders.
  Join lines cannot cover logging in already grouped (nobody ever joined),
  so a join-only filter would hide a real group.
- **"You have joined Dad Bods." is a GUILD line** — both self forms anchor
  on "the group" or the roster gets seeded with a guild name.
- **An empty roster credits NOBODY but you and your pets** — see the game
  rule above. The cost is a real groupmate landing in the bucket when we
  never saw them join (logging in already grouped, before anyone speaks),
  which is why filtered damage is lumped and SHOWN: a wrongly-excluded
  contributor stays visible and one line of group chat fixes it.
- Filtered damage is LUMPED, never dropped: a silently missing contributor
  is indistinguishable from a quiet fight, and the gate CAN be wrong (an
  unmapped groupmate's pet has a generated name that proves nothing).
  Synthetic overlay rows are parenthesised and `_class_color` refuses them
  a class colour, or a meta row reads as another person in the fight.
- `class_str` still has two writers with different orderings — see the log
  pipeline section.

## The overlay toggle and `--reload`

`_overlay_proc` is MODULE state and uvicorn `--reload` cycles the worker on
every edit, resetting it to None while the overlay child keeps running. The
toggle then took the LAUNCH branch, the named-mutex singleton blocked the
second copy, and the overlay became impossible to dismiss from the web UI —
while still DRAGGABLE, which is how it gets reported. A pid file outlives
the reload and a process scan covers one orphaned before the file existed.
Both paths confirm the target really is an overlay first: pids are recycled.
**Match `backend.overlay` or `--overlay` as an exact argv TOKEN** — a
substring test on "overlay" also matches `--ocr-overlay`, so the combat
toggle could kill the OCR calibrator.

**Finding the reload worker at all: never grep its command line.** uvicorn
`--reload` runs the app in a MULTIPROCESSING SPAWN child whose argv is
`python -c "from multiprocessing.spawn import spawn_main; spawn_main(...)"
--multiprocessing-fork` — containing neither `uvicorn` nor `backend.main`.
Every search for those strings returns nothing while the server is plainly
serving, and `netstat` credits the LISTEN socket to the reloader PARENT,
which may already be dead: `taskkill /PID <that>` answers "process not
found" while the port stays bound and answers HTTP. Symptoms are a stale
version served forever and a fresh launch dying on `[Errno 10048]`. Find it
by walking the process tree — its MCP `node` child names it via
ParentProcessId — or from the parent pid netstat reports, then kill the
tree. Two corollaries learned the hard way: a process match on command-line
text also matches the SHELL RUNNING THE SEARCH (this killed the debugging
shell twice), and Git Bash rewrites `/PID` into a path, so `taskkill` must
run from PowerShell or cmd.

## LLM runtime (backend/llm_runtime.py)

- Providers: `none` (deterministic) | `lmstudio` | `openai` | `custom` (any
  OpenAI-compatible base URL) | `anthropic` | `local` (Ollama).
  - Ollama gets a REAL client, not the `custom` OpenAI shim, because it
    speaks its own protocol. `OLLAMA_BASE_URL`/`OLLAMA_MODEL` exist so it
    can live on another machine — a common setup.
  - `langchain-ollama` is in BOTH requirements files. The exe carries the
    LLM clients deliberately (see requirements-lite's own comment) and
    Ollama is the only keyless one, so it fits a single-file download
    best. CI now asserts openai/anthropic/local all report available in
    the packaged build — omitting a client once shipped an exe whose key
    field could do nothing, and nothing caught it because the advisor
    falls back silently.
  - **Grok needs no provider of its own** — xAI is OpenAI-compatible at
    `https://api.x.ai/v1`, so it is a `custom` endpoint. The menu names it
    so nobody asks for a Grok provider that would just duplicate `custom`.
  - **Adding a provider means FOUR places**, and missing any of them makes
    it invisible: `get_llm()`, the `POST /api/llm` allow-list, the
    `GET /api/llm` options list, and SettingsModal's `PROVIDERS` (plus
    `keyFieldFor` if it needs a key). Both Ollama AND Anthropic were
    implemented and shipped yet unreachable for exactly this reason —
    Anthropic was even bundled into the .exe, so we paid to package a
    client nobody could select.
  - It was supported in `get_llm()` from the start yet unreachable until
    2026-07-28: absent from both provider lists AND rejected by
    `POST /api/llm`'s allow-list. If you add a provider, that guard, the
    `/api/llm` options list and SettingsModal's PROVIDERS all need it. Switch at
  runtime via the Advisor tab / `POST /api/llm`; persists to
  `data/llm_config.json`; switching clears consult caches.
- `none` never builds a chat model — advisor/gear branch to
  `_builtin_counsel` / `_builtin_gear`: effect-categorized loadout
  (damage/heal/control/buff via spell records), exact supersession warnings,
  horizon from scribed-ahead + purchasable, AA cost ranking, hunting picks,
  gear upgrades (same-item higher ranks + strict-Pareto swaps on scaled
  stats). Also the automatic fallback when any LLM
  call FAILS — the tab never breaks.
- LM Studio only: `_lmstudio_budget` sizes max_tokens to the loaded context
  window (prevents cryptic 400 overflows; thinking models burn reasoning
  tokens against the completion budget). Frontier models get no knobs —
  o-series/gpt-5.x reject temperature.
- **Every provider has its OWN model setting**, and `active()` must return
  it. It used to fall back to `settings.model` for anything but
  openai/custom, so picking Ollama or Anthropic displayed — and USED — the
  LM Studio model id. `set_active()` likewise persists per provider, or
  switching away and back silently loses the choice.
- **`_build()` raises on an unknown provider.** It used to FALL THROUGH to
  Anthropic, so a stale or misspelled provider quietly became Claude on
  langchain's default model — which is how "I chose LM Studio" reported
  claude-3-5-sonnet. Failing loudly is safe: the advisor catches it and
  drops to the deterministic path.
- **Read the reply with `_reply_text()`, never `response.content`.** QAT
  and reasoning builds served through LM Studio return an EMPTY content
  with the whole answer in `reasoning_content`, so content-only parsing
  reported "no JSON in LLM reply" while the raw reply plainly contained
  some. It also flattens Anthropic-style block lists and checks
  `response_metadata`.
- **`custom` REFUSES to build without a base URL.** `ChatOpenAI` silently
  defaults to api.openai.com when `base_url` is empty, so a missing URL did
  not fail — it sent the user's key to OpenAI and returned 401. Reported by
  someone configuring Groq. The panel also never rendered a base-URL field
  at all, so the endpoint was unreachable from the UI even though
  `app_config` had always allow-listed it; a provider needing an endpoint
  needs an INPUT for it, not just storage.
- **`probe()` / `GET /api/llm/probe` answers a different question from
  `available()`.** Available = "is the client library installed"; probe =
  "is a server actually listening, and is a model loaded". LM Studio and
  Ollama can be selected, importable and completely unreachable, and the
  first symptom is otherwise a failed consult. LM Studio's native
  `/api/v0/models` distinguishes downloaded from LOADED where the
  OpenAI-shaped `/models` cannot, so it is tried first and falls back;
  Ollama uses `/api/tags` plus `/api/ps` for what is resident. Cloud keys
  are NOT probed — verifying one costs a paid request — so they return
  `checked: false` rather than a misleading failure. 2.5s timeout, never
  raises: it sits behind a button in the settings panel.
  - It resolves the model via `model_for(provider)`, NOT `active()`. You
    check a provider you have not saved yet — switching the dropdown to
    Ollama while LM Studio is still active — so comparing against the
    active model reported "your model is not in the list" for a model
    plainly present. `model_for()` is now the single place that knows
    which model belongs to which provider; `active()` delegates to it.
  - Ollama tags carry a `:latest` suffix the configured name usually
    omits, so the presence check matches on both the full tag and the
    part before the colon.
  - **"none loaded" is the NORMAL idle state and must not read as a
    fault.** Ollama unloads after `keep_alive`, default 5m, and LM Studio
    JIT-loads too, so both sit at zero between requests and load on the
    first call. What actually decides whether a consult works is whether
    the CONFIGURED model is among those installed — so that is what the
    status line leads with, and the only thing that turns it amber.
- Chat (agent/graph.py) uses the same `get_llm()` seam.

## Prompt sizing is adaptive (`context_limit` / `guide_budget`)

`_lmstudio_budget` always read the LOADED context to size max_tokens; the
INPUT side ignored it and used a fixed guide budget picked for an 8k model,
so a 32k window was mostly wasted. `llm_runtime.context_limit()` resolves
manual > probed > default and `game_data.guide_budget()` scales the
per-guide cap from it (floor 3200, ceiling 9000 — beyond that guides crowd
out the gear/spell context they exist to inform, and a 10k-token prompt
measured ~3.9s locally).

- **Cloud providers are never scaled up.** Ample context, billed tokens.
- **The manual override lives in `app_config.json`, not `llm_config.json`.**
  Reading the wrong file made a pinned value silently do nothing. The
  settings panel writes every non-secret override to app_config.
- **Blank clears the pin**, so the save must be unconditional — a
  provider-scoped send cannot express "stop overriding".
- Probed value is cached 60s: this is consulted while BUILDING a prompt, so
  an unreachable server would pay the 2.5s timeout per consult (2.09s cold
  vs 0.0005s warm).
- **Splitting one consult into concurrent sub-prompts was measured and
  REJECTED.** LM Studio does batch genuinely (4 requests returned within
  0.01s of each other), but the speedup collapses as prompts grow — 3.30x
  at 20 tokens, 1.83x at 2600 — and splitting duplicates shared context:
  one 10,206-token prompt took 3.94s against 5.86s for four 2,767-token
  ones sending 1.08x the tokens. Do not revisit without new measurements.

## Spell timer tiers

Upgrading a spell lengthens it (+10%/tier buffs and debuffs, +5% DoTs and
HoTs, from eqltools /learn/spell-upgrades). The log carries the tier as a
roman numeral, so `parser.spell_tier()` reads what `strip_tier()` drops.

- Scaled ONLY for `BASE_DURATION_ROWS` — the 94 rows whose value is the
  game's own durationTicks. A community-measured pack row was timed at an
  unknown tier; scaling it again compounds a tier already baked in and
  produces a timer that outlives its spell. An unmarked row stays flat,
  which is the safe default for anything added later.
- The DoT rate is applied to everything (telling a DoT from a debuff needs
  data the snapshot lacks) and results round DOWN. Every remaining error
  therefore points at under-promising.

## The ZEM sheet's Type column is OPTIONAL

61 of 119 rows omit it, including the whole Faydark block. Assigning
columns by position put a level RANGE into `type`, left lo/hi None, and
shifted every quality circle one column left — Crushbone parsed as
efficient at level 1 when its row says poor, seven zones lost their band
and were dropped, and the City exclusion (`type == "City"`) silently
stopped applying to half the table. Detect the row shape: a leading cell
matching a level range means Type is absent.

**Do not filter candidates to `type == "Dungeon"`.** 15 in-era rows carry
no Type at all and Crushbone is one of them, so a hard filter drops the
zone most often wanted at that level. Dungeons outrank open zones at EQUAL
quality instead — a tiebreak, never a gate.

## Wiki grounding

`spell_file.py` reads the game's own `spells_us.txt` (caret-delimited, in
`EQL_GAME_DIR`; format per Amerzel/eql-info, effects blob located by "1|"
content scan): proc-granted spell names (SPA 85/323/339/360/361/365/383/
419/427/429) drive exaltation-proc disambiguation, and lifetap target
types (13/20) drive the synthesized self-heal — your OWN taps log no heal
line at all. Loaded in a worker thread at startup (~0.4s); fail-soft
empty sets without the file. Item-granted weapon procs are NOT in the
spell file (known limit).

Item pages also feed **acquisition hover cards** (`item_acquisition` in
game_data.py -> `GET /api/item-acquisition` -> ItemHover.tsx on every item
name in the gear tab): Drops From / Sold by / quests / crafting parsed
from the RENDERED page HTML (`fetch_page_html`) — those sections exist
ONLY in rendered HTML ({{Itempage}} emits them; wikitext lacks them).
Extraction pattern from DavisChappins/eql-tooltip (MIT). Misses on exact
titles fuzzy-resolve via wiki search + normalized edit distance
(`_resolve_item_title`; strict search gets a trailing-s-stripped retry),
and wiki caches serve STALE data when a refresh fails (`Cache.get_stale`
— expired entries are kept, never deleted on read).

**Class guides** (`class_guides/*.md`, one per full class name lowercase/
underscored): curated community playstyle wisdom injected into BOTH
consults for each class in the trio (first ~2600 chars advisor / ~1500
gear — front-load the decision-relevant facts). See class_guides/README.md
for curation rules; update after patches by hand — nothing regenerates
them.

`builds_data.py` reads the eqlbuilds.com dataset snapshot that ships inside
the MCP clone (dist/data/eqlbuilds — CI-refreshed): per-class spell lists
with EXACT unlock levels, AA ranks/costs, skills. When present it feeds the
advisor's spell/AA context directly (no scraping), backs `spell_record`
when the MCP server can't answer, and decides pet-line supersession (pet
SPAs 33/71 carry no magnitude — unlock level IS strength). No clone = every
helper returns None and callers fall back.

`mcp_client.py` prefers the EQL MCP server (structured `eql_builds_*`
spells/AAs/skills/stances; clone of ArtSabintsev/everquest-legends-mcp,
Node 22+, `MCP_SERVER_DIR`) and **falls back to plain HTTP** (wiki_http.py,
MediaWiki api.php → text in the same line-per-cell shape) when it is absent
— adopters need no Node beyond the UI. Page/context caches are 1-24h;
failed fetches are not cached. Melee classes have no Spells section on
their wiki page — expected, not a parser bug.

## Mac and Linux (Wine)

There is no native EQL client on either, so players run it under Wine —
CrossOver/Whisky/osxEQL on macOS, Lutris/Bottles/plain wine on Linux. This
costs less than it sounds: **a bottle is an ordinary directory from the
host**, so the log is a normal file and the tailer, parser, byte offsets
and cp1252 decode all work untouched. We never talk to Wine.

- **The layout below the bottle is IDENTICAL to Windows.** Windows
  `G:\Daybreak Game Company\Installed Games\EverQuest Legends` vs macOS
  `<prefix>/drive_c/users/Public/Daybreak Game Company/Installed Games/
  EverQuest Legends` — same tail, so `Logs/` and `maps/` derive exactly as
  before and only the ROOT has to be found.
- `config.detect_game_dir()` = registry (Windows) → `_wine_game_dir()`.
  The probe list is `$WINEPREFIX`, osxEQL's `prefix` **and `prefix-cx`**
  (their launcher falls back to the latter when `prefix` has no
  `system.reg`, and one machine can have both), CrossOver and Whisky
  bottles, Lutris `~/Games`, flatpak Bottles, plain `~/.wine`, and Steam
  Proton. Each is joined with the tails above and confirmed by an
  `eqclient.ini`/`eqgame.exe`/`Logs` probe, so an empty folder never wins.
  Paths per sowoky/osxEQL `engine/lib.sh`.
- **`game_running()` must match the COMMAND LINE off Windows.** Under Wine
  the process name is wine/wine64-preloader; matching `eqgame.exe` by name
  would always report "not running" and mis-drive the `/log on` banner.
  Same technique as osxEQL's own `pgrep -f` health check.
- The overlay and OCR stay Windows-only and are never imported by the
  server (the overlay is a CHILD PROCESS via `child_command()`), which is
  the reason the rest ports for free. Do not import either from main.py.
- No packaged build for these platforms on purpose: an unsigned .app needs
  `xattr -dr com.apple.quarantine` before it opens — right-click→Open no
  longer reliably bypasses Gatekeeper — which is a worse first run than
  `git clone`. `start_companion.sh` covers both platforms.

## Configuration (.env — see .env.example for the annotated version)

`EQL_GAME_DIR` is the one path most installs must set; `Logs/`, `maps/`, and
the Brewall custom-map dir derive from it. LLM fields: `LLM_PROVIDER`,
`MODEL` (local id), `OPENAI_API_KEY`/`OPENAI_MODEL`, `CUSTOM_BASE_URL`/
`CUSTOM_API_KEY`/`CUSTOM_MODEL`, `ANTHROPIC_API_KEY`. `MCP_SERVER_DIR`
empty = wiki over HTTP. Key changes need a backend restart; the provider/
model selection itself is runtime-switchable in the UI.

## Settings & secrets (the gear in the header)

- **`app_config` stores every override as a STRING, and neither caller
  validates on assignment** — so `"false"` lands on a bool field intact and
  reads as TRUE. `allow_spellset_write` saved correctly, the file on disk was
  right, and the flag stayed on. `app_config.apply(target)` is now the single
  place that pushes overrides onto a settings object and coerces against what
  the field already holds; the startup validator and `POST /api/settings` had
  each written that loop themselves, so the bug existed twice.
- **`allow_spellset_write` is OFF by default** (`config.py`, allow-listed in
  `app_config.FIELDS`, switched under Settings ▸ General). Writing the
  `[SpellLoadouts]` section of `LO*.ini` is the ONLY thing this app writes
  inside the game folder, and it is the one place a strict reading of the
  Daybreak Terms has anything to bite on — so it is the player's decision,
  not the installer's. Same reasoning that keeps `eqclient.ini` read-only.
  The gate lives on the ENDPOINT, not only in the UI: a hidden button is not
  a closed endpoint.
- **Three layers, and they do not mix.** `.env` is the base; the UI writes
  non-secret overrides to `data/app_config.json` (applied in `config.py`'s
  validator BEFORE Logs/ and maps/ derive, so a folder chosen in the panel
  behaves exactly like one in `.env`); API KEYS go to `data/secrets.json`
  and nowhere else.
- **Keys are write-only from the browser's point of view.** `GET
  /api/settings` reports `keys_set: {field: bool}` — never a value, and
  `secrets_store` logs field NAMES only. If a diagnostics/support dump is
  ever added, it must exclude `secrets.json`; that separation is the entire
  reason the file exists rather than living in `app_config.json`, which is
  exactly the sort of file users paste into bug reports.
- A key field ABSENT from a POST body is left untouched (so saving a game
  folder never wipes a key); an explicit `""` clears it. Both are covered
  by tests in the API — keep that behaviour if you extend the panel.
- `secrets_store.FIELDS` / `app_config.FIELDS` are ALLOW-LISTS: a typo in a
  caller must not silently mint a new setting.
- Changing the game folder re-derives the paths and restarts the tailer via
  `switch_character()` — no restart required.

## Frontend conventions

- **StoneGlass design tokens** (inherited from an earlier in-game skin
  project): dark glass `rgba(18,21,26,.82)`, gold `#c8aa6e`, hairline
  `rgba(200,170,110,.34)`, flat square-ended gauges, zero border-radius.
  Semantic colors: out-damage gold, in-damage `#d4574a`, heal `#1fb38c`,
  cast `#b07cc6` — all ≥3:1 contrast on the dark surface.
- Fonts: Cinzel (display), IBM Plex Sans (UI), IBM Plex Mono (numerals).
- Ledger rows color via `data-kind`; dim/disabled table rows via `data-dim`.
- Accessibility floor: `:focus-visible` outlines, `prefers-reduced-motion`
  kills animation, color never carries meaning alone.
- WS hook auto-reconnects (2.5s); ledger pins to bottom unless the user
  scrolled up; events batch through `page.tsx`.
- **Layout modes** (all persisted in localStorage): the center
  Atlas/Advisor panel collapses ("◂ hide") into a combat dashboard —
  encounter sections reflow into CSS multi-columns across the freed width,
  the ledger becomes a short strip; the War Ledger collapses in EITHER
  mode (its freed column goes to the encounter panel, which then also
  reflows); encounter text scales via A−/A+ (CSS zoom); the whole HUD is
  viewport-locked >=1200px (panels scroll internally, never the page).
  The Companion chat tab was removed.
- The Encounter panel shows per-ability hit counts (×), a defense line,
  healer-attributed heal rows, and a separate Pet section when a mapped
  pet contributes. The overlay (backend/overlay.py) is an EQBuddy-style
  sectioned widget: COMBAT (ranked class-colored bars, Damage|DPS,
  this-fight|last-5), SESSION (kills/xp+rate/coin+rate/crits), LOOT
  (recent + best drop-rate mobs), PROGRESS (hours-to-ding) — sections
  collapse by clicking their header (Scroll Lock ON), c toggles a
  compact one-line strip, +/- adjusts opacity; layout/position persist
  to data/overlay_ui.json. Named-mutex singleton, click-through when
  Scroll Lock is OFF, self-closes when eqgame.exe exits.

## Testing

- **Parser coverage** (after any EQL patch): iterate your real log through
  `parse_line`, `Counter` the event types — a vanished category means the
  log format changed; fix `parser.py`.
- **Zone coverage** (after any EQL patch, and whenever a zone is added):
  `python scripts/zone_coverage.py` — runs every zone in the client's own
  `Resources/ZoneNames.txt` through `_canonical()`. `MISS` is a bug in
  ZONE_FILES/ZONE_ALIASES; `NOFILE` usually just means the zone ships no
  stock chart. Exits non-zero on any MISS.
- **Simulated combat** (no game needed): append a line to the watched log —
  `[<timestamp>] You crush a test dummy for 42 points of damage.` — the
  ledger updates within ~0.5s. Tag synthetic rows unmistakably ("test
  dummy") so cleanup can target them precisely.
- Manual API checks: `/health`, `/api/character`, `/api/advisor?cached=1`.
- Backend tests import `backend.*` — run from the repo root with the
  project's Python environment.

## Known limitations

- Regex parser breaks silently if EQL changes log formats (run the coverage
  test after patches).
- Level/class unknown until `/who` is typed in-game; loadout swaps write
  nothing to the log (cast-mismatch detection hints at `/who`).
- One ACTIVE character at a time (header dropdown switches).
- OCR position + overlay are Windows-only. Dungeon vector charts mostly
  do not exist (classic behavior) — True-walls / 3D modes cover them.
- The chat agent (backend/agent/graph.py) still exists server-side but has
  no tab — the Advisor is the grounded path.
- The community hunting sheet is mid-edit: Type/range/circle data can
  disagree (parser merges and tolerates); ZEM multipliers are withheld
  by the wiki on purpose, not merely missing.

## Releasing

Latest: **v2.8.1**. MCP server clone at `MCP_SERVER_DIR` is
**ArtSabintsev/everquest-legends-mcp** — note a DIFFERENT project shares that
name (Sergeantfirstclass...); it has no tags and no `src/data/eqlbuilds`, so
builds_data.py finds nothing there. Local clone is on **v1.3.4**; **v1.3.5**
is out (dependency bumps incl. the TypeScript 6->7 one previously unreleased,
plus an atomic-release CI fix) and is safe to take. Data snapshot refreshed
twice weekly; stay on release tags, not main. Update the MCP
with `git merge --ff-only <tag> && npm install && npm run build` in its
clone. Benign `eql_wiki_page returned isError` lines (pages that don't
exist; HTTP fallback covers them) log at DEBUG.


Bump `APP_VERSION` in backend/main.py AND frontend/lib/version.ts (same
string), add a CHANGELOG.md section, commit, then `git tag vX.Y.Z` and push
with `--tags`. **Pushing the tag is now the whole release**:
`.github/workflows/release.yml` builds the .exe on a clean windows-latest
runner and attaches it (plus a .sha256) to that tag's release, creating the
release if it does not exist. `gh` is installed and authenticated locally if
you need to do it by hand.

Build the exe on a CLEAN runner, never a laptop: PyInstaller bundles what
the build machine has installed, so a dev box with extra packages produces
something `requirements-lite.txt` does not describe. That already shipped
once. The workflow fails the build if `frontend/out` lacks the current
version (a stale export once shipped a UI eight versions old) or if the
built exe cannot serve `/api/settings` in 120s with the right version —
a windowed build that cannot boot fails silently otherwise.

**If a release gets flagged by antivirus** (likely eventually; packed
PyInstaller one-file builds trip heuristics): first REPRODUCE it —
`MpCmdRun.exe -Scan -ScanType 3 -File <exe>` for Defender, or VirusTotal for
a multi-engine view. v1.15.0 scanned clean on Defender, so there was nothing
to report. Only submit to <https://www.microsoft.com/wdsi/filesubmission>
when a detection actually exists: choose "Software developer", give the
detection name, the release download URL, and the published SHA256. Code
signing does NOT remove the SmartScreen prompt — since 2024 Microsoft treats
OV and EV alike and reputation accrues per file hash — so signing is worth
pursuing for the publisher name and fewer AV flags, not for that warning. Untagged pushes are invisible to users: the in-app check
(badge click + 6-hourly poll; API with tags-page fallback for rate-limited
IPs) compares against the newest tag, and update_companion.py downloads
THAT TAG's ZIP (git clones pull main instead). The updater preserves
.env/data/node_modules/.next*, side-files changes to running scripts as
*.new, uses certifi for TLS (never disables verification), and rebuilds
the frontend into .next-prod. Install path is git-free: releases-page ZIP
-> install_companion.bat (offers Python/Node via winget, PATH-refreshes
in-window, cmd /k so the window never vanishes) — see INSTALL.md.

## Notes for assistants

- **NOTICE.md is the sourcing record, and it must stay current.** Anything
  vendored gets an entry with its real licence; MIT on this repo does NOT
  relicense it. Two obligations are non-optional: wiki-derived content
  (`zem_levels.wiki`, and everything mined at runtime) stays CC BY-SA 4.0,
  and third-party data keeps its own terms. It also records which KIND of
  source each number comes from — log-parsed, export-parsed, wiki-mined,
  modeled — which is the honest version of "how much should I trust this".
  Six vendored files went uncredited before 2026-07-28; check NOTICE when
  you add a data file, not later.
- **TODO.md holds shelved ideas**, each with enough context to resume cold —
  why it is worth doing, what shape it should take, and any trap already
  found while prototyping. Add to it rather than letting a deferred idea
  live only in a conversation. It is explicitly NOT a roadmap.


- Git: never commit `.env` (real keys) or `data/` (runtime state) — both
  gitignored. Commit when the user asks.
- Before ANY destructive SQL against `data/companion.db`: SELECT the exact
  predicate first, eyeball the rows, delete by id list — never by pattern.
- The verification-gate pattern is the house style: when adding an
  LLM-driven feature, pair it with a deterministic verifier and a
  deterministic fallback so the UI never depends on model correctness.

<p align="center">
  <img src="docs/logo.svg" alt="WarCounsel" width="640">
</p>

A real-time companion app for **EverQuest Legends**. It tails your combat log
and gives you a live HUD in the browser — nothing injected, nothing touching
the game process. The one thing it can write is optional: recommended spell
sets into your character's saved-loadout file (with a backup), so one
in-game `/memspellset companion` loads the whole advised bar.

## In action

**The HUD and the 3D Atlas** — live vitals and countdown timers on the left,
Najena mined from your own game files in the middle (drag to orbit; the dot
is you), and the fight breakdown on the right with per-ability crits, your
pet's line, and every group member's damage:

![Live HUD: vitals, timers, encounter breakdown](docs/screenshots/hud-overview.jpg)

The 3D view tracks you as you move — the dot is your `/loc`, and the
camera follows it through geometry mined from your own game files:

<p align="center"><img src="docs/screenshots/atlas-3d-tracking.gif" width="420" alt="3D Atlas following the player through Najena"></p>

**The Advisor** — a wiki-grounded spell loadout for your exact trio and
level, with one-click write-back into the game's saved spell sets, and
permanent pre-buffs called out so you never waste a slot:

![Advisor: tiered loadout counsel](docs/screenshots/advisor-loadout.jpg)

**Where to hunt** — zones ranked against the community level table, above a
Gantt of the bands around you so you can see what you are about to outgrow.
Then the full 24-slot gear table, with every stat scaled to your items'
actual upgrade ranks:

![Where to hunt and the leveling chart](docs/screenshots/hunting-and-leveling.jpg)

**Exaltations and farming** — every stone you own: what it grants, whether
it is active or dormant until a later level, and exactly which of your items
it can legally socket into — then where to farm your next upgrades, and
per-class notes for your trio:

![Exaltation tracking and farming targets](docs/screenshots/exaltations-and-farming.jpg)

**The in-game overlay** — a compact always-on-top meter that lives
over the game: ranked damage bars, draining spell/cooldown timers,
session rates, drop tracking, and loot/kill alerts with an attention
banner. Click-through by default; Scroll Lock makes it interactive.

You choose what it shows. Under **Settings ▸ Overlay** every section
switches off, and so does every field inside one — keep the kill count
but drop the coin, keep cooldowns but not every buff you refreshed.
Start from **Combat focus** (the meter and your timers) or **Meter
only**, then adjust. Changes reach a running overlay in about half a
second, so you can watch it shrink while you tune it. Anything you
turn off is still in the web view, which has room for it:

<p align="center"><img src="docs/screenshots/overlay.png" width="340" alt="Overlay: damage meter, timers, session rates, alert banner"></p>

**What you get**

- **Vitals & War Ledger** — live DPS, session stats, hit rate, XP, loot
  (with sold tags), a streaming combat feed, per-pull encounter breakdowns
  with group/raid DPS and a defense line (dodge/parry/block/riposte)
- **Group numbers you can actually compare** — everyone in the group gets a
  damage and DPS row, with pets on their own row rather than folded into
  their owner. That means if two people in the group both run this, one
  person's "You" matches what the other sees for them, so the figures are
  worth arguing over. Mob casts land in the encounter too, so you can see
  what is being cast at you and by whom
- **Combat dashboard** — hide the Atlas/Advisor panel and the encounter view
  spreads across the freed width; the ledger collapses to a strip;
  encounter text size is adjustable
- **Atlas** — zone charts with a live position dot, zone-to-zone routing,
  "true walls" mined from the game's own map geometry, and a textured 3D
  dollhouse view with a follow camera
- **Advisor** — spell loadout with pick-and-choose checkboxes, AA spending,
  upgrade warnings, a vendor shopping list, gear-slot recommendations,
  exaltation tracking (typed sockets), and where-to-hunt picks — grounded in
  your actual spellbook/inventory exports and the EQL wiki, with every
  suggestion machine-verified (owned, level-legal, not superseded, and not
  fighting another pick for the same buff slot — two buffs in one slot
  overwrite each other, so recommending both wastes a gem).
  One click writes the picks as in-game spell sets — a combat loadout
  (gems auto-ordered: DD, DoTs, AoE, heals at gem 8, utility, pets) and a
  pre-buff set (permanent buffs first, then longest-duration)
- **Overlay** — a Details-style damage meter over the game: ranked
  class-colored bars up to raid size, damage/DPS modes, this-fight or
  last-5-fights segments; closes itself when the game exits

## Get it

Two ways to run it, and **the .exe is the one to pick if you just want to
play**.

| | Single .exe | Source install |
|---|---|---|
| You must already have | nothing | Python 3.11+ and Node 18+ |
| Setup | download, double-click | run `install_companion.bat` |
| HUD, War Ledger, encounters, timers, alerts | yes | yes |
| In-game overlay | yes | yes |
| Atlas — charts, true walls, textured 3D | yes | yes |
| Advisor + gear counsel | deterministic **or** an LLM | same |
| Screen-OCR position tracking | no | yes |
| Download | ~42 MB, one file | a repo plus its dependencies |

**[Download WarCounsel.exe →](https://github.com/EKirschmann/WarCounsel/releases/latest)**

It needs nothing installed, finds your game through the Windows registry,
and keeps its data in a `data` folder beside itself. First launch takes a
few seconds (a one-file build unpacks itself each time); after that it is
the same app as the source install.

Windows **will** warn you that it does not recognise the publisher — the
file is unsigned. [INSTALL.md](INSTALL.md#option-a--the-single-exe) shows
exactly which button to press, and how to check the download yourself if
you would rather not take my word for it.

Paste an API key into the gear panel if you want LLM-backed counsel; leave
it empty and the built-in deterministic advisor does the job.

Everything below this point is about the **source install**, which you want
for OCR position tracking or to hack on the code.

## Requirements

*(For the .exe you need none of this — just Windows and the game.)*

- **Windows 10/11**, or **macOS / Linux** running the game under Wine
  (see [Mac and Linux](#mac-and-linux) — the overlay and OCR are
  Windows-only there)
- **Python 3.11+**
- **Node.js 18+** (serves the web UI)
- EverQuest Legends with logging enabled (type `/log on` in game once)

**Optional — pick zero or one LLM for reasoned counsel:**

| Option | Needs | Notes |
|---|---|---|
| None (deterministic) | nothing | default-ready; mechanical but honest counsel, instant |
| LM Studio | a local model | free, private; ~26B MoE models work well |
| Ollama | `ollama pull <model>` | free, private, no key — works in the .exe too |
| OpenAI | an API key | best quality; a consult is ~7k tokens |
| Anthropic | an API key | Claude; also in the .exe |
| Custom endpoint | any OpenAI-compatible URL | **Grok** (`https://api.x.ai/v1`) / Groq / OpenRouter / LAN — free tiers work |

**Optional — EQL MCP server** ([ArtSabintsev/everquest-legends-mcp](https://github.com/ArtSabintsev/everquest-legends-mcp),
Node 22+) for structured spell/AA data. Without it the app fetches the wiki
over plain HTTP automatically — no Node beyond the UI is required.

## Setup — the easy way

> Never installed anything like this before? **[INSTALL.md](INSTALL.md)**
> walks through every click — no git or command line knowledge needed
> (download the ZIP, extract, run `install_companion.bat`).

```
git clone https://github.com/EKirschmann/WarCounsel
cd WarCounsel
install_companion.bat
```

No git? Download the newest **Source code (zip)** from the
[releases page](https://github.com/EKirschmann/WarCounsel/releases),
extract, run `install_companion.bat`.

The installer pulls dependencies, then a short wizard finds your EverQuest
Legends install (scans all drives; or paste the path), offers to download
the [Brewall map pack](https://www.eqmaps.info/eq-map-files/) for the 2D
Atlas charts (the 3D view mines the game's own files — nothing to download),
and asks which counsel model to use — including **none**. Every answer just
fills in `.env`; change any of it later by editing that file, or re-run
`python setup_wizard.py`.

## Setup — by hand

```
pip install -r requirements.txt
cd frontend && npm install && cd ..
copy .env.example .env
```

You usually do NOT need to set `EQL_GAME_DIR`: the backend tries the
launcher's standard path and then the game's own registry entry, so even
custom installs are found automatically (logs and maps derive from it).
Set it in `.env` only when detection fails. Optional 2D dungeon charts:
extract the Brewall pack from
<https://www.eqmaps.info/eq-map-files/> into `<game dir>\maps\Dark Brewall`.

## Run

`start_companion.bat` — or two terminals:

```
uvicorn backend.main:app --reload     # backend on :8000
cd frontend && npm run dev            # UI on :3000
```

Open **http://localhost:3000**, then in game type:

| Command | Why |
|---|---|
| `/log on` | start writing the combat log (once per character) |
| `/who` | teaches the app your level + class trio |
| `/outputfile spellbook` · `inventory` · `missingspells` | grounds the Advisor in what you own |
| `/alternateadv list` | syncs your AA ranks |
| `/loc` | drops a position fix on the Atlas (or enable OCR tracking) |

Then press **check exports** and **Consult** in the Advisor tab.

## Mac and Linux

There is no native EQL client for either, so people play under **Wine** —
and that turns out to suit this app well. From the host side a Wine bottle
is an ordinary folder, so the combat log is a normal file: WarCounsel reads
it directly, without going through Wine at all.

**First get the game running**, using whichever the community recommends:

| macOS | Linux |
|---|---|
| [osxEQL](https://github.com/sowoky/osxEQL) — free, open-source Wine + Metal | [Lutris](https://lutris.net) |
| [CrossOver](https://www.codeweavers.com/crossover) — paid, commercially supported Wine | [Bottles](https://usebottles.com) |
| [Whisky](https://getwhisky.app) | plain `wine` in `~/.wine` |

**Then run WarCounsel from source:**

```bash
git clone https://github.com/EKirschmann/WarCounsel.git
cd WarCounsel
./start_companion.sh          # add "dev" for hot reload
```

You need Python 3.11+ and Node 20+ (`brew install python node`, or your
distro's packages). Everything else is handled on first run.

The game folder is found automatically in the usual bottle locations —
osxEQL's `prefix` and `prefix-cx`, CrossOver and Whisky bottles, Lutris
under `~/Games`, Bottles, and plain `~/.wine`. If yours lives somewhere
else, point at it and skip the guessing:

```bash
EQL_GAME_DIR="$WINEPREFIX/drive_c/users/Public/Daybreak Game Company/Installed Games/EverQuest Legends"   ./start_companion.sh
```

Then `/log on` in game, exactly as on Windows.

### What you do not get

- **No in-game overlay.** It relies on Win32 click-through windows, global
  hotkeys and a tray icon; macOS has no Scroll Lock key and will not
  reliably draw over a fullscreen Wine game anyway. **Run the game
  windowed** and keep the browser beside it — that is the intended shape
  here.
- **No screen-OCR position feed.** Typing `/loc` still plots you on the
  Atlas; only the automatic tracking is missing.
- **No packaged download.** Run from source. An unsigned Mac app would
  need `xattr -dr com.apple.quarantine` before it would open, which is a
  worse first run than `git clone`.

Everything else is the same build: HUD, War Ledger, encounters, Atlas 2D
and 3D, the Advisor, sessions and settings.

> Tested by construction against every bottle layout above, but not yet on
> real hardware — if the game folder is not found on yours, please open an
> issue with the path and it will be a one-line fix.

## Updating

**Using the .exe?** Download the new one and replace the old file. Your
`data` folder beside it is untouched, so sessions, settings, and mined
geometry all survive. The in-app version badge tells you when a newer
release exists.

**Source install:** click the version badge in the app header to check for a newer release.
To update: close the companion, run `update_companion.bat`, start it again —
works for both git clones (pull) and ZIP installs (a built-in downloader;
git is never required). What changed is in [CHANGELOG.md](CHANGELOG.md).

## Overlay shortcuts

Global, so they work while the game has focus:

| Keys | Does |
|---|---|
| `Ctrl+Alt+O` | show / hide |
| `Ctrl+Alt+C` | compact mode |
| `Ctrl+Alt+↑ / ↓` | opacity |
| `Ctrl+Alt+X` | force interactive (no Scroll Lock needed) |

A tray icon near the clock offers the same, plus **Reset position** for an
overlay dragged off-screen. Windows 11 tucks new tray icons into the `^`
overflow until you drag one out.

## License

MIT — see [LICENSE](LICENSE).

**Take what's useful.** Copy the parser, lift the verification-gate
pattern, vendor the data files, fork the whole thing. No permission
needed. A mention is appreciated, not required — this exists because
other people in this community published their work first, and most of
them asked for nothing either.

Two exceptions, because they aren't ours to give away: wiki-derived
content stays **CC BY-SA 4.0**, and vendored third-party data keeps its
own licence. Both are listed in [NOTICE.md](NOTICE.md), along with credits
for the projects this is built on and a note on where each kind of number
in the app comes from.

## Who's in your group

The log never says. It records what people *do*, not who they are, and that
turns out to be the hardest thing this app does.

EQL only lets the tagger's group damage a mob, which sounds like it settles
the question — anyone hitting your target is with you. But the log carries no
mob IDs, so a stranger fighting a *different* mob of the same name is
indistinguishable from a groupmate helping with yours. Two
`Spirit of Dessication` up at once and the meter has nothing to separate
them.

So the app watches for the signals that do exist — a join line, an invite
accepted, a word in group chat — and credits nobody it can't place. Every one
of those is momentary. A group that formed by invite and plays quietly emits
none of them, and its damage sits under **Not counted** until someone happens
to speak. That's why the panel lets you say so by hand.

Pets make it worse. A summoned pet with a generated name reads exactly like a
player — `Jabeker hits a froglok` could be either — and the possessive
form we *can* recognise (``Kenkyo`s warder``) is the minority case.
The app falls back on absence of evidence: never in a `/who`, never spoke,
probably a pet. It's a guess, and it's marked as one.

None of this is settled. If you've parsed EQ logs before and know a line that
names a group member, or a way to separate pets from players more reliable
than *"they never talk"*, [open an issue](../../issues). The mechanics here
are community knowledge, and this is where the app leans on it most thinly.

## Notes

- Sessions survive backend restarts (state snapshots to `data/`)
- One active character at a time; the header dropdown switches between every
  `eqlog_*.txt` in the folder
- Everything stays local: logs, exports, and counsel never leave your machine
  unless you point the LLM at a hosted API
- Full architecture and extension docs: `CLAUDE.md`

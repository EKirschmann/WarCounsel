# Changelog

Notable changes per release. Check for updates by clicking the version badge
in the app header; update by closing the companion and running
`update_companion.bat`.

## v2.10.1 — 2026-08-16

**Fixed: the app could be using a max HP many levels out of date.** It was
stored only when you typed one in — the stats-panel reading updated the live
value but never wrote it back, while startup loaded the stored one. So every
restart began with whatever you last typed and stayed there until you next
opened the inventory window. On one character the stored value was 1948
against an actual 3379.

That was harmless until v2.10.0 started recording how far your health dropped
in each fight. Measured against a stale maximum, a fight costing 1,900 damage
reads as 2.5% health remaining instead of 44% — a comfortable fight logged as
a near-death, in exactly the data meant to weigh survivability. The stored
value now keeps up with what the app reads, and a value you type by hand still
wins.

## v2.10.0 — 2026-08-16

**Fixed: gear advice could not see item effects at all.** A swap was offered
as "+14 AC and no loss of other stats" — while quietly costing Spell Haste II,
a 15% cast-time reduction. The stat vector has no term for an effect, so
anything an item *does* was invisible to every comparison. Slot rows now name
what a swap gives up.

That took two wrong turns to get right, both corrected: an item's Effect line
is its own and applies without a stone, and a socketed stone overrides it. The
socket is exposed by **levelling** — across 23 worn items, all 20 at +1 or
more had one and none of the 3 at +0 did — so a +0 item's focus cannot be
moved at all, and the advice now says to merge the item first rather than just
warning you.

**Fixed: an item the wiki spells differently was invisible.** A Skull-shaped
Barbute +3 was never offered for Head even though it strictly beats the worn
helm (AC 17 vs 13, +46 HP, +13 SV Magic, nothing worse). Wiki titles are
case-sensitive, the game writes Title Case, and the retry that should have
caught it compared case-insensitively — so the item resolved to nothing and
was silently excluded. An item with no stats never appears and nothing says
why, which is the worst shape a bug can take here.

**Fixed: spell sets saved in game could vanish.** The client keeps them in
memory and rewrites the file wholesale when it flushes, so writing while it
runs loses data in both directions. Writing is now refused during a session,
with the remedy named: camp to desktop first.

**Fixed: the AA counter never went down.** Purchases were not parsed at all
and batched awards were missed — 199 spent points unaccounted across 128
purchases in one log. Thanks to @soaringswine for the fix and the regression
tests. (#11)

**Fixed: ranged items were never compared.** The Range row said "not compared"
because bows and thrown are outside the white-DPS index — but only their
*damage* is. Stats compare like anything else, and now do, with only the
damage half disclaimed.

**Fixed: coordinates split across OCR boxes.** An X of 1540 could read as 1.

**New: deterministic passes run before the model.** Spell candidates are
pre-gated so a loadout slot cannot be spent on a pick that gets dropped
afterwards (91 → 56 on a real spellbook). The wiki context is fitted per
section instead of truncated at the tail — that tail was the AA list, and at
the production budget **0 of 73 AA entries** were reaching the model while it
was asked to recommend AAs "using the per-rank costs in the data". Now 26.

**New: pet gear is compared, not guessed.** A deterministic pass does the
arithmetic first and hands the model the trade-offs. Clear upgrades fill in
automatically; genuine trade-offs deliberately do not, because choosing
between +6 damage and −10 strength is a judgement call. Its candidate pool was
also ranked alphabetically and cut at 40, hiding 20 items — including the
highest-damage weapon owned.

**New: encounters record how close the fight was.** A death is the tail of a
distribution: 2.6% of fights ended in one, while 5.3% cost over half of max HP
and 8.5% ran past 90 seconds. Each fight now carries the deepest HP reached,
whether mana ran out, and the mob's level from `/con` — groundwork for
weighting gear by what actually threatens you rather than by what killed you.

Also fixed along the way: healing received counted **zero**. Every heal landing
on you is logged as "you" rather than by name, and the check only matched the
name — 17,954 hp unaccounted in a single log.

## v2.9.1 — 2026-08-14

**Fixed: a consult could disappear when you saved settings.** Run a consult,
open Settings, change anything at all, and the advisor and gear counsel were
both discarded — because the settings panel sends the advisor provider on
every save, and any mention of it was treated as "the model changed". Only a
real model change clears counsel now.

Worse, the counsel was never actually gone. It is written to disk after
every consult, and the tab simply was not looking there — so a cleared
memory cache reported "no counsel" while the file held the whole thing. Both
tabs now fall back to the file, and a consult superseded by a genuine model
change stays on screen marked stale instead of vanishing.

**Fixed: weapon procs were being counted as spells you cast.** If a spell is
BOTH scribed and granted by an exaltation — Ignite, off a Shimmering Ruby
Stiletto — casting it once made every later proc count as a cast for the
rest of the session. In one log that was 407 procs filed as casts. Whether
damage was cast is now decided per hit, in a 12-second window measured from
18,721 real cast-to-damage pairs.

**Fixed: quests that do not want what you are carrying.** The tab claimed
five quests wanted a Water Flask and two more wanted a Backpack. An item
page's "Related quests" list names a quest whether it takes the item, hands
it out, or just mentions it — so the Journeyman's Boots Quest was listed as
wanting Journeyman's Boots, which are its reward. Rewards and unmentioned
items are filtered out; 56 rows became 36 with every real turn-in kept.
Gnoll Bounty no longer lists water flasks beside a bar counting gnoll fangs.

**Fixed: items in Shared Bank, Equipment, Dragon's Hoard and Personal Depot
were reported as carried in your bags.** Thanks to **@soaringswine**, who
found this, wrote the regression fixture first, and fixed it (#9). Follow-up
here so the gear consult accepts the newly-named storage — one player had 21
items in an Equipment tab that would otherwise have gone quiet.

**The Quests and Progression tabs got a design pass.** Progression rows no
longer repeat their own heading sixteen times ("Primary Class Unlock -
Bard" under CLASS UNLOCKS is now just "Bard"), a finished unlock reads as
gold and leads its section instead of being dimmed to near-invisible at the
bottom, and empty progress rails are gone. On Quests, the requirement now
sits beside the bar that measures it, the giver and zone read as one place,
and rewards are labelled — they were an unlabelled list of item names next
to a list of required item names.

## v2.9.0 — 2026-08-13

**New: a Progression tab.** Class unlocks, raid targets, keys, race and
deity unlocks, factions, exploration, hunter, slayer and tradeskills — read
straight from the game's own `/outputfile achievements` dump, which carries
a complete/incomplete mark on every single criterion.

That matters most for **Plane of Sky**. Every other Sky tracker infers your
progress from an inventory dump, and inference is wrong in two directions:
an item you already turned in has left your bags while its criterion stays
complete, and a class confirmed at creation autocompletes without the items
ever being held. This reads the game's answer instead of guessing at it.

Sorted closest-to-done, with the item list tucked behind a click for
anything you have not started — sixteen class unlocks at 0/6 is ninety-six
lines of things you have not done, which buries the ones you have. Type
`/outputfile achievements` in-game and press check exports; there is a
reminder in Vitals if you have not.

**Pre-launch progression is withheld rather than labelled.** A beta export
on a real character claimed a class unlock was finished, with all six Plane
of Sky items obtained. The current export for the same character attributes
that unlock to an entirely different class. That is not stale data, it is a
confident wrong answer to "have I finished this" — so the panel shows the
warning in place of the data, with a button to look anyway.

**Fixed: counsel could survive its own fix.** Advisor and gear results
persist between launches, and opening the tab deliberately never starts an
LLM call — so freshness was judged only from your character and exports,
never from the code that produced the counsel. Installing a release that
corrected an advisor gate left the old counsel on screen marked current.
Thanks to **@soaringswine**, who found this, wrote the regression test
first, and fixed it (#8). Extended afterwards to cover every module holding
a gate rather than just the advisor's own.

**Fixed: Ensnare and Treeform were offered as pre-buffs, and four real
buffs were missing.** Nothing checked who a spell lands on, so a snare — a
fourteen-minute effect cast on an enemy — passed every test for something
to cast before a pull. Nothing checked what the effect does, so Treeform
qualified too: self-target, thirty-six minutes, and it roots you in place.
Levitate and see-invisibility are gone from the list for the same reason
invisibility already was. Symbol of Transal, Strength of Earth, Holy Armor
and Shield of Brambles are back. And the spell-set writer kept its own copy
of these rules that disagreed with the advisor's in both directions, so
`/memspellset` could write Treeform into a pre-buff bar.

**Fixed: a solo focus was handed the group version of its buffs.** Skin
like Steel and Protection of Steel are the same 50 AC and 50 HP for the
same 36 minutes, so the only difference is who else it lands on — and the
tie was being settled by list order. It asks your playstyle now.

**Pre-buffs are capped at your spell slots.** You cast them by memorizing
one, casting it and swapping the gem back, so a seventeen-entry routine
against a fourteen-slot book describes something nobody can do in one pass.

## v2.8.2 — 2026-08-12

**New: a search line on the Quests tab.** You loot something and want to
know whether it is quest fodder before you vendor it. Type the name. It
matches item names, quest names, givers, zones, unlocks and rewards — so
searching a zone answers "what can I finish while I am here" from the same
box.

Searching looks at every quest, not just the 25 the list shows, and lifts
the cap while you type. A filter that only saw what was already on screen
would miss matches silently.

**An empty result now tells you which kind of empty it is.** Searching for
something you are carrying that no quest wants used to return a blank list,
which reads exactly like a broken search. It now says so by name: "You are
carrying Tanned Split Paw Skin, and no quest page references it." Searching
for something you do not have says that instead.

It deliberately stops short of calling anything safe to sell. The wiki
failing to tie an item to a quest is not evidence that nothing does.

## v2.8.1 — 2026-08-12

**Writing spell sets into the game folder is now OFF until you switch it
on.** Settings ▸ General. If you use the Advisor's "save this as a spell
set" button with `/memspellset`, turn it back on there — nothing else
changed about how it works.

Why: editing the `[SpellLoadouts]` section of your `LO*.ini` is the only
thing this app writes inside the game folder, and it is the one place a
strict reading of the Daybreak Terms of Service has anything to bite on.
That should be your decision rather than the installer's. It is the same
reasoning that has always kept `eqclient.ini` read-only — other companions
flip `Log=1` for you; this one does not write a game file it was not asked
to write.

**Fixed: instanced zones at difficulty 1 or higher charted nothing.**
Reported as issue #7 — standing in Plane of Hate D1 showed no map, no
geometry, no route. Difficulty comes in two shapes and only one was
handled: `Befallen 4 (Refined)` was recognised, `Plane of Hate D1` was not,
so the zone resolved to nothing at all and the Atlas simply sat blank. This
affects every zone at D1 and above, not just Hate.

**Fixed: a saved settings checkbox could not be turned back off.** Settings
overrides are stored as text, and the string `"false"` was being read as
true — so the switch saved, the file on disk was correct, and the setting
stayed on. Found while building the toggle above. The two places that
applied overrides had each written the same logic separately, so the bug
existed twice; there is now one.

## v2.8.0 — 2026-08-12

**Settings has a side-nav, and you choose what each panel shows.** A rail
down the left — General, then one entry per panel, then the Overlay,
Triggers, Screen reading and model blocks that were already there. Each
panel entry lists its own sections as switches: turn off Deaths if you do
not care about deaths, or Past sessions, or the whole War Ledger. Three
presets to start from: Everything, Combat focus, Planning.

Deliberately separate from the overlay's switchboard. A 42px strip and a
340px column answer different questions — you want a damage meter and
nothing else while fighting, and the full session ledger while planning —
so one shared set of toggles would mean hiding deaths mid-fight also hides
them when you sit down. Choices live in `data/`, which the updater
preserves, so they survive both a restart and an upgrade.

**Fixed: Ensnare and Treeform were being offered as pre-buffs.** Nothing
checked who a spell lands on, so a snare — a 14-minute effect cast on an
enemy — passed every test for something to cast before a pull. And nothing
checked what the effect does, so Treeform qualified too: self-target, 36
minutes, and it roots you in place.

**Fixed: real buffs were missing from the pre-buff list.** Symbol of
Transal, Strength of Earth, Holy Armor and Shield of Brambles never
appeared. Three causes stacked: the candidate list was capped before
supersession ran, so it kept Skin like Rock and Center and cut the Skin
like Steel and Symbol of Transal that replace them; the stacking gate
stopped at the first shared slot, so a spell occupying two slots resolved
one conflict and left the other standing; and the deterministic backfill
ranked by raw magnitude before cutting to eight, which drops small numbers
that are nonetheless real buffs with nothing superseding them.

**Fixed: a solo focus was handed the group version of its buffs.** Skin
like Steel and Protection of Steel are the same 50 AC and 50 HP for the
same 36 minutes, so the only difference is who else it lands on — and the
tie was resolved by list order. It now asks your playstyle. Solo keeps the
single-target twin; grouped keeps the group one.

**Pre-buffs are capped at your spell slots.** You cast them by memorizing
one, casting it and swapping the gem back, so a seventeen-entry routine
against a fourteen-slot book describes something nobody can do in one pass.
Permanents are kept first — cast once, held until death, so they earn a gem
far more cheaply than anything re-cast between pulls.

**New: a plain statement about third-party tools and the Daybreak Terms of
Service**, in README.md and NOTICE.md. Game Jawn and Daybreak do not review
or endorse any add-on, including this one. What the app reads, the one file
it writes inside the game folder, and what leaves your machine are all
itemised so you can weigh it yourself.

## v2.7.0 — 2026-08-10

**New: a Quests tab.** Your inventory export says what you are carrying,
item wiki pages say which quests want each item, and quest pages carry the
giver, zone, level and reward. Joined together, a bag of oddments becomes a
list of things you are already partway through. On one character, 127 items
matched 54 quests — including a Thex Mallet with both the hilt and the head
sitting in different places.

Grouped by what the quest is FOR — race unlocks, class quests, equipment,
spells, faction turn-ins — using the wiki's own categories rather than
labels we invented. Race unlocks name the race, class quests name the
classes. Out-of-era content (Kunark and later, which this game does not
implement) sits in its own section at the bottom: the items are real and in
your bags, so the section answers "why am I carrying this".

**Progress bars, where the number is actually known.** The race-unlock table
states exact totals and your export states exact stack sizes, so those rows
show real progress — 42/800 toward Froglok. Wiki quests get no bar, because
their counts live in walkthrough prose and a number scraped from a sentence
would send you farming the wrong amount. A bar on some rows and not others
is the honest version of knowing one number and not the other.

**Fixed: stack sizes were being thrown away.** The inventory export's count
column was parsed and discarded, so 27 gnoll fangs and 42 phosphorous
powder both read as one item. This affected anything that counted what you
own.

**Fixed: a wiki outage used to persist after the wiki recovered.** A timeout
and a missing page looked identical to the code, so a timeout was cached as
"this item has no data" — for an hour, or a day for vendor lookups. One
outage could empty the quest tab and keep it empty. Failures are now told
apart from answers, and never cached.

**The Encounter panel can be collapsed**, like the War Ledger, and the
Quests tab has the same A−/A+ text size control the Encounter panel has.

## v2.6.2 — 2026-08-10

**Leveling-chart zones now route.** The community hunting sheet spells some
zones the wiki's way ("Mistmoore Castle", "The Hole", "Western Karana")
while the log and the map use the game's ("Castle Mistmoore", "Ruins of Old
Paineel", "West Karana"). Nine of its 73 zones differed and nothing
reconciled them, so the chart could recommend somewhere the route finder
then called unknown — and standing in a zone could report it as missing
from the sheet while its row sat there under the other name.

**Gear advice now looks at what your pet is carrying.** Pet inventory
arrives from `/pet inventory check` and never reached the gear consult, so
the app would hand items down to the pet but never notice the pet holding
something better than you wear.

**New: a surplus list** of things you can clear out. Deliberately ignores
your classes — you will swap trios, so "your current classes cannot use
this" is no reason to sell anything. Only two things qualify: a lower rank
of an item you already own, and anything the wiki calls vendor trash. If
the app is not sure, it says nothing rather than guessing, because the
action it suggests cannot be undone.

**Fixed: the updater blamed the wrong thing.** A failed update told everyone
to `git stash`, which only helps if you have edited files. If you had
committed something locally the advice did nothing and you stayed stuck.
It now asks git which case it is and prints the command that actually
applies — stash for edits, rebase or reset for commits.

**Fixed: the packaged OCR build.** The v2.6.1 build job hung for nearly two
hours because CI runs Python 3.13, where the OCR engine ships without its
models and downloads them on first use. Pinned to 3.12, where the models
travel with the package.

## v2.6.1 — 2026-08-09

**The OCR download from v2.6.0 never made it out.** Its build failed a
check on the way — the image-recognition models were left out of the
bundle, so screen reading would have broken the moment anyone switched it
on. `WarCounsel-OCR.zip` is attached to this release instead, and the build
now proves the engine works by having it read a test image before shipping,
rather than trusting that the pieces are present.

`WarCounsel.exe` for v2.6.0 was built and released normally and is
unaffected — the two are built separately on purpose. Everything else in
v2.6.0, including the new Triggers panel, is unchanged and already in it.

## v2.6.0 — 2026-08-08

**Triggers you can actually set up.** Watching the log for the things you
would otherwise miss now lives under **Settings ▸ Triggers**, instead of a
JSON file you had to find and hand-edit. Add a row, pick what it watches,
type the text — matches are plain text, so there is nothing to escape, and
`*` catches every one of a kind.

Five new things can be watched, all of which the app was already reading
and simply had nowhere to report:

- **your spell being interrupted**, and separately, **fizzling**
- **someone else starting a cast** — a mob's cast line is the only warning
  before it lands
- **a raid mechanic firing**
- **a mob being mesmerized**

Charm and mez breaks were already possible and still are: watch `fade` for
`Charm`. Each trigger says what its text is compared against, because a
pattern aimed at the wrong part of the line fails silently forever.

Also fixed: the trigger list showed nothing at all on a fresh install. The
examples ship switched off, and the list was only reporting switched-on
ones — so the one screen meant to explain the feature looked empty.

**New download: `WarCounsel-OCR.zip`.** Reading your position off the screen
was the one thing the single .exe could not do. It now can — as a separate
download, because the image-recognition packages weigh about 200 MB against
the app's 44 MB, and a one-file build unpacks everything on *every* launch.
Folding them in would have slowed the start for everyone who never turns the
feature on. The OCR build ships as a folder for the same reason: it unpacks
once, not each time.

`WarCounsel.exe` is unchanged — same download, same speed. Take the OCR one
only if you want screen reading; both keep their data in the same place, so
switching between them costs nothing.

The settings panel used to answer "screen reading needs its optional
packages: `pip install …`" for this, which could never work in the .exe and
asked people with no Python to run a Python command. It now names the right
download — or, in a source install, the exact interpreter to install into,
since a plain `pip` frequently belongs to a different Python than the one
running the app.

## v2.5.3 — 2026-08-08

**Fixed: the full install could fail with "'pip' is not recognized".** Windows
ships a fake `python.exe` — a Microsoft Store shortcut that does nothing and
*reports success* — and it is on your PATH by default. The installer believed
it, skipped the offer to install Python, and then died on pip with no useful
explanation. It now checks whether Python can say where it lives, which the
fake one cannot.

**It also stops asking you to install things you already have.** Python and
Node.js are often installed but simply not on PATH (the python.org installer
only adds it if you tick the box; Anaconda and Node both do this too). Both
the installer and the launcher now look in the usual places before asking,
and use what they find for that run — without changing your system PATH.

**Fixed: the launcher could start the backend with the wrong Python.** It
tried to activate its own environment, but that command quietly does nothing
in a plain command window, so the backend started against an installation
that had none of its dependencies and stopped with an import error. It now
uses the environment's own Python directly.

If you hit any of this, re-running `install_companion.bat` is enough — and
INSTALL.md now lists the symptom, including how to switch the Store shortcuts
off if you would rather clear them out.

Nothing here affects the single .exe, which carries its own Python.

## v2.5.2 — 2026-08-08

**Fixed: 14 zones had no map or 3D geometry, including The Hole.** The Atlas
looks a zone up by the name the log prints, and EQL prints the old long
names — "The Ruins of Old Paineel" for The Hole, "The Liberated Citadel of
Runnyeye", "Neriak - Commons" with a dash. None of those matched, so the
panel said "no zone geometry for this place" for zones whose art was sitting
in the game folder the whole time.

Now charted and rendering: **The Hole**, The Warrens, Planes of Sky, Fear
and Hate, the Temple of Solusek Ro, Runnyeye, the Lair of the Splitpaw, the
Qeynos Aqueducts, the Castle of Mistmoore, and all three Neriak gates. Two
of those (Mistmoore, Runnyeye) were broken by an entry that was *supposed*
to help and instead hid a working one.

Routing reaches the new zones too — The Hole and The Warrens connect through
Paineel, the Temple through Lavastorm. Lake Nerius is still unmapped: it is
the one EQL zone whose art ships in a format the 3D extractor does not read.

Checked against the client's own zone list (`Resources/ZoneNames.txt`) —
all 77 live zones now resolve. `scripts/zone_coverage.py` re-runs that check
after a patch, so the next renamed zone shows up as a failure instead of an
empty panel.

## v2.5.1 — 2026-08-04

**Fixed: Ollama consults returned an almost empty loadout.** Ollama uses a
2048-token context unless told otherwise, and it cuts a longer prompt
without reporting it — so the advisor was answering from the tail end of
its own prompt, with your spellbook missing entirely. A level 46 character
was offered two spells for fourteen slots.

WarCounsel now tells Ollama how large a context to use, and **Settings has
a context field for Ollama** — previously the one provider that most needed
the setting was the only one without it. 16384 is a good starting point for
an 8B model on a 12 GB card; raise it if consults still come back thin.

If a prompt does overflow whatever limit is set, the consult now says so
and names the likely casualty, instead of presenting the remains as an
answer.

**Also:** INSTALL.md now names the actual Windows Defender detections seen
in the wild (`Trojan:Win32/Wacatac.B!ml` on the exe, `Trojan:Script/...`
on the source zip), explains that the `!ml` suffix means a machine-learning
verdict rather than a signature, and tells you to update definitions before
reporting one. Both cleared server-side on their own.

## v2.5.0 — 2026-08-03

**Spell picks now use what your log says your spells actually do.** The
advisor was choosing from spell level and name alone, which is how it made
Smite a primary nuke while Careless Lightning was hitting five times harder
in the same fights. Your encounters already recorded per-ability damage;
that goes into the consult now.

**Pre-buffs rebuilt.** The section listed permanent buffs reasoned as
"Permanent buff." and little else, because the prompt only ever sent
names. Buffs now carry their effects and duration, the long defensive ones
you would actually re-cast between pulls are guaranteed a place, and
anything a buff you own overwrites is removed rather than listed and
crossed out. Invisibility and camouflage are no longer treated as
pre-buffs — you cast those for a pull, not as part of buffing up.

**No pet, no pet spells.** A Paladin/Druid/Monk was being told to slot pet
haste and pet shrink. None of those classes summons anything, so those
gems were dead.

**Upgrade warnings point at what you can cast today**, and say what comes
next with its level, instead of naming a rung you passed ten levels ago.

**Consults stopped failing on local reasoning models.** They spend their
thinking against the same budget as the answer, and the budget was too
small — one run used 5,997 of 6,000 tokens deliberating and never
answered. It is now sized from the real context window, and when a reply
is cut short the message says so instead of blaming the parser.

**The gear consult no longer waits on the spell consult.** They read
different data and the gear one was unreachable until the other had run.

**Also**

- Focus moved next to the Consult button it steers; the trio pickers fold
  away, since /who sets the trio now
- Max HP and mana say when the screen supplied them
- The horizon looks five levels ahead, and the heading says so
- "Nice to have" no longer repeats spells already in a slot
- The vendor shopping list is gone — the in-game find tool is better at it
- The tab icon is back, and the OCR boxes are documented in the README

## v2.4.0 — 2026-08-02

**Melee loadouts, measured from your own fights.** A new section in the gear
tab groups every stored encounter by the weapon verbs that appeared and
reports what each actually did — DPS, average hit, hits per minute — so
"do I lose damage giving up dual wield for a two-hander" is answered with
your data instead of a formula.

It has to be measured, because it cannot honestly be modelled: eqlwiki does
not publish the two-handed damage bonus, it links out to a classic
EverQuest table, and classic values have been wrong for this game before.

**Proc rate now counts in weapon comparisons.** Weapons with a combat effect
carry their expected procs per minute, computed from your DEX. The
important part is counterintuitive and the advisor is now told it outright:
proc chance is a per-MINUTE budget, not a per-swing roll, so a faster
weapon does not proc more often. What changes is how many hands carry a
budget — the main hand gets the full rate and the off-hand half, so dual
wielding yields about 1.5x a two-hander's procs. That was a real dual-wield
advantage the white-DPS index could never see.

**Dual-wield context.** The panel reports how often an off-hand can land at
your level, from the skill cap — at 24 that is 50%, so a second weapon adds
up to half again, never double. Owning Ambidexterity raises it, and both
readings of the AA's "+32%" are shown because its text does not say whether
that is points or relative.

**What it will not tell you.** Hand count is not inferred. Two weapons of
the same type both log the same verb and the log genuinely cannot separate
them, so the panel reports the rate and leaves the reading to you. Two
earlier attempts at guessing it were both wrong, and both were caught by a
player saying what they had actually equipped.

Figures are HITS per minute, not swings — a missed off-hand swing is not
recorded, so an off-hand is worth at least what is shown.

## v2.3.0 — 2026-08-02

**The app can read your character sheet.** An optional second screen-reading
box over the Inventory window picks up HP, mana, AC, your attributes and
your resists — including the `196/510` caps. It only reads while the
Inventory window is open with the Equipment tab focused, once every 15
seconds, and it checks for the yellow label text before spending an OCR
pass so a closed window is never mistaken for a screenful of zeroes.

**Gear advice stops recommending stats you cannot raise.** At 510 an
attribute is done, and further points on an item are worth nothing. The
advisor now values each candidate at what it would ACTUALLY deliver —
full value when there is room, the remainder when there is little, zero
when the rest of your gear already caps it. A like-for-like swap between
two items carrying the same capped stat correctly ties. Without a stats
reading nothing changes.

**Race unlock turn-ins are flagged as you loot them.** A Gnoll Fang reads
as vendor trash and is 1/1200th of a Barbarian. Looting one now names the
race, the NPC and the zone, and Vitals keeps a running tally against the
target — `37 / 1200` tells you whether to keep going. Seven lootable
turn-ins from the community race-unlock guide.

**Spell sets are named after your trio.** They were all called "companion"
and "prebuffs", so every trio overwrote the last one and keeping two meant
regenerating and logging out each time you swapped. Now
`pal/dru/mnk` and `pal/dru/mnk-buffs`, which simply coexist.

**Screen-reading setup moved into Settings**, under Overlay, with a Place
box and Test read for each region. Test read reports the measured yellow
level next to the threshold, because a closed window and a badly placed box
otherwise look identical. The Atlas keeps a status line.

**Groundwork: reading your group window.** The in-game group box is the only
place that states who is actually with you — the log never does — and it
lists players without their pets. The region, capture and calibration are
in; the reader itself is deliberately unwritten until it can be built
against a real capture rather than a guess.

**Fixed**

- Item hover cards were clipped by their panel and painted behind
  everything below them. They now float free and are fully opaque.
- The LM Studio model box showed `o3`, an OpenAI-only model. The stored
  settings were right all along; the panel was reading the wrong field.
- After "Check server", the model list behaved as a filter — the dropdown
  opened on nothing until you emptied the box. The probed models are now
  shown as buttons, with a dot marking what is loaded.
- The API key field no longer summons the browser's password manager.
- Opening the UI on `127.0.0.1` instead of `localhost` left every REST
  feature silently dead while the page looked alive. Both now work.

## v2.2.1 — 2026-08-01

**Mend now shows a timer.** Monk Mend has a 90-second re-use and nothing
was tracking it. The ability was already parsed; it simply never started a
countdown.

Improved Mend ("You magically mend your wounds...") is recognised as the
same ability — it had been firing and matching nothing at all.

Note that Mend, unlike Lay on Hands, never prints a "you can use the
ability again in..." line, so this timer has nothing to correct itself
against. The 90 seconds was measured across 547 uses in a real log and
confirmed in game.

## v2.2.0 — 2026-08-01

**You can now tell the app who is in your group.** It could only ever
guess, from signals that are all momentary — a join line, an invite, a
word in group chat. A group that formed by invite and plays quietly emits
none of them, so real groupmates sat under "not counted" while their
damage went uncredited. The Encounter panel now lists them with the one
number that decides it — how many of your fights they turned up in — and
Add / Ignore buttons, plus Add all / Ignore all. Ignore holds only until a
join, invite or group line proves otherwise. Names drop off on their own
five minutes after they stop fighting, and likely pets are marked and
listed last rather than burying the names you can actually act on.

**Fixed: a backend reload emptied your party.** The roster was never
saved, which was harmless while unknown contributors were credited by
default and became a disappearing act once they were not.

**Fixed: the advisor could have your race wrong forever.** Race was
recorded once and never updated, so a value left over from beta outranked
every /who since. It reached real output — the advisor states race, and
class advice is race-influenced.

**Gear advice got several things right that it had been getting wrong:**

- An off-hand weapon is no longer suggested to classes that cannot Dual
  Wield. It would never swing, so its damage was never going to happen.
- Items whose wiki page lists no stats can now fill an EMPTY slot. An
  earring in an empty ear beats nothing, whatever the page says.
- Resist lines written as "SV Cold" instead of "SV COLD" are no longer
  dropped. Affected items compared as though they had no resist at all.
- **Trade-offs are shown instead of hidden.** A candidate that wins some
  stats and loses others used to be discarded silently while the row read
  "no better owned option flagged". It now says what you would gain and
  what you would give up, and leaves the call to you.
- **You can correct an item's stats yourself** — the "stats?" button beside
  any worn item. Some wiki pages are stubs and some carry stats from the
  original EverQuest for items EQL rebalanced; nothing in the app can catch
  that, but you are holding the item.

**Charmed pets count properly.** A charm fights before it identifies
itself, and everything it did before `/pet leader` used to be thrown away.

**Group fights no longer split into fragments** when you go OOM, step away
to heal, or die — confirmed groupmates hold the fight open for up to 20
seconds past your own last action.

**Your class can be inferred from your spells.** 80% of spells belong to
exactly one class, so casting one is proof. Shown as a /who hint rather
than written in: a cast proves a class is slotted, not what the other two
slots hold.

**Beta play no longer shows up as this character's history.** Lifetime
totals already excluded it; the encounter list, session history and trio
comparison did not.

## v2.1.13 — 2026-08-01

**Strangers no longer appear on your damage meter.** Someone fighting
nearby could show up as if they were helping, because their mob shared a
name with yours and nothing could tell the two apart.

EverQuest Legends does not allow shared damage — once a mob is tagged, only
the tagger and their group can hurt it. So anyone who is not in your group
is, by definition, fighting something else. The meter now credits your
group and your pets, and nobody else. Previously, with no group, it
credited everyone present.

Anything excluded still shows as one "filtered" line rather than vanishing.
That matters if you logged in already grouped and the app has not seen your
group yet — a real groupmate would sit in that line until someone speaks in
group chat, and you can see it happening rather than wondering where their
damage went.

## v2.1.12 — 2026-07-31

**Your pet's damage was partly going to a stranger.** A pet fights before
it tells the app who it belongs to, so its opening swings were credited to
an unknown name and never counted toward your session at all — and once it
was recognised you saw it twice on the meter, as itself and as "someone".
Its earlier damage is now claimed the moment it is recognised, and your own
pet is labelled "(pet)" the way other people's pets already were.

**The overlay meter shows the fight you are in.** It used to hide a
last-five-fights mode behind a click on the right of the header. That is a
slower question, and the Encounter panel in the app answers it with room to
spare — so the overlay does one thing, and the whole header now switches
Damage/DPS.

**The overlay's shortcut list was cut off.** With Scroll Lock on, the hint
ran past the edge of the window and everything after "opacity" was
invisible — including how to lock it back to click-through and how to close
it. It wraps onto two lines now.

**LM Studio: you can choose the model, and the choice sticks.** Loading a
different model, then watching the app load the old one back, was the app
never reading the model you picked — and there was no way to pick one in
the first place. Settings now lists what your server has, and warns when
the loaded model is not the one counsel will use.

**Gear advice fixes.**
- Items in an "Any Slot" are judged on stats alone. A weapon there is never
  swung, so its damage was being counted for a slot that cannot use it.
- The "Held" row is gone. Nothing goes in it, so a row permanently reading
  "nothing owned equips here" was noise. It returns if an item ever fits.
- Pet suggestions respect what a pet can wear: no two chests, and no extra
  weapon when it is already holding a two-hander.
- An AA has to exist. Recommendations naming abilities that are not in the
  game are dropped rather than shown.

**Per-mob coin is gone from Session hunting.** Coin is useful as a session
total, which is still there; split across a mob list it was noise.

## v2.1.11 — 2026-07-30

**Spell timers now account for the upgrade tier.** Upgrading a spell makes
it last longer, and timers were ignoring that entirely — a rank-10 spell
showed roughly half its real duration. Timers scale with the tier you
actually cast, but only for spells whose base duration comes from the
game's own data; anything measured by the community stays as it was,
because scaling it twice would produce a timer that outlives its spell.

**The levelling chart was misreading half the table.** The community
levels sheet leaves the "Type" column out on many rows, and the parser was
reading columns by position — so those zones had their quality ratings
shifted by one, seven lost their level range entirely and were dropped,
and the rule that hides cities stopped applying to them. Crushbone was
being rated as an efficient level-1 zone when the sheet says the opposite.
Eight more zones now appear at all, and dungeons rank above open zones
when the quality is equal.

**The advisor uses more of your model's context.** If you run a local
model, the app already knew how large a window it had loaded but sized its
questions for a much smaller one. It now scales to what is actually
available, and Settings takes an override if you would rather cap it — the
detected value is shown next to the field. Paid models are unchanged on
purpose, since more context there means a larger bill.

**Class guides say more in less space.** The enchanter guide was more than
twice the length the advisor could read, so a third of it — the spell
priorities, the trio synergies, both patch updates — was never being used.
Rewritten to fit, along with the necromancer guide. Druid and shaman
gained control mechanics: what charms what, that raid bosses cannot be
rooted or snared, and that slows do not stack.

**The settings icon looks like a gear now.**

## v2.1.10 — 2026-07-30

**Shaman offensive spells now have timers** — thanks again to
**@soaringswine**. Twenty spells that produced no timer at all: the DoT
line, and just as importantly the slows, roots, blinds and resist debuffs.
Those never tick and never announce themselves, so a timer is the only way
to know a slow has dropped off the mob you are still fighting.

**Druid too.** Nineteen more, covering the root and snare lines, the DoTs
and the lull family — which also picks up nine ranger spells that share a
name. Necromancer, shaman and druid now have complete coverage.

**Six timers that outlived their spell were corrected.** Found by checking
every row against the game's own data rather than only the ones being
edited: `spirit of the puma` ran 25 seconds long, `drifting death` six, and
four others by a second or two. A timer that keeps counting after its
effect has ended is the one mistake this list must not make.

**Fixed: the update message in the header was unreadably small** — and it
told you the app would restart itself, which it does not. It now says to
restart when the updater finishes, at a size you can actually read.

## v2.1.9 — 2026-07-29

Thanks to **@soaringswine** for three contributions in this release.

**Gear the wiki has never heard of is now usable.** Launch shipped a block
of items eqlwiki has no page for, and several are pieces people are already
wearing. Without a page there was no slot, so a perfectly good chest piece
sat in a bag with the chest slot empty and nothing said a word. The app now
learns an item's slot from your own export — where you have worn something,
the game has already told us where it goes — and you can fill in stats for
anything still missing. Empty slots get suggestions at all now, which they
never did without a model configured.

**The damage meter no longer credits strangers.** Someone fighting nearby
could appear in your meter, including their pet, even when they were on a
different mob that merely shares a name with yours. Only confirmed group
members are credited now, learned from join and leave lines and from group
chat. Anything excluded shows as one "filtered" row rather than vanishing —
if the app is wrong about who is in your group, you can see that it is.

**A hostile spell's timer ends when its target dies.** A damage-over-time
timer used to run its full duration whether or not the mob was still alive.
It now learns its victim from the first tick and ends with them, whoever
landed the killing blow.

**Every necromancer offensive spell with a duration now has a timer.**
Clinging Darkness, Disease Cloud, Poison Bolt and 39 others produced no
timer at all — and a missing timer looks exactly like a spell that has
none. Six existing timers that ran longer than the spell actually lasts
were also corrected downward.

**Fixed: the OCR calibration box could not be moved or resized.** It
snapped back to where it started on every drag.

**Fixed: the overlay could become impossible to close.** While the app was
being edited, the Overlay button stopped dismissing it — you could still
drag it around, but nothing would close it.

**Fixed: two slots lied about being checked.** A weapon could be suggested
for "Held", which nothing goes in, and empty slots claimed nothing you
owned would fit them without having looked.

## v2.1.8 — 2026-07-29

**Empty slots get suggestions.** Gear advice without a model only ever
looked at slots you had something in, so an empty off-hand, hands or
waist was passed over and then labelled "nothing owned equips here" —
again a verdict on a comparison that never happened. Every slot is now
checked, and an empty one is filled by anything owned that fits and your
classes can use. Slots that still read "nothing owned equips here" have
actually been looked at.

**A two-handed weapon no longer gets an off-hand partner.** The rule that
a two-hander occupies both hands existed only on the model-backed path.
That was harmless while weapons were skipped entirely, and became a real
risk the moment an empty off-hand could be filled. The deterministic path
now leaves the off-hand alone behind a two-handed primary and says why.

## v2.1.7 — 2026-07-29

**Weapon upgrades are found without an LLM.** Gear advice running with no
model configured skipped your weapon slots entirely and still reported
"no better owned option flagged" — so a plainly better weapon sitting in
your bags went unmentioned, and the wording implied it had been checked.
One-handed weapons are now compared properly, using the same white-DPS
index the gear list already showed you: a swap is suggested only when the
new weapon scores higher in the hand it goes in and gives up nothing
else.

Damage and delay are judged **together**, which is the point — a 7 damage
/ 30 delay weapon beats a 7 damage / 42 delay one, but compared stat by
stat the faster weapon looks worse on delay and loses. That is exactly
how a real upgrade stayed hidden.

Both weapons are measured at the rank you actually own, so **merging
either one re-decides the swap** — merge the challenger and it wins by
more; merge what you are holding far enough and it correctly keeps what
you have. Two-handers, anything with a proc, and ranged weapons are left
alone on purpose: procs are not in the index, so a proccing weapon can
beat a higher score. The ranged row now says it was not compared instead
of claiming nothing better was found.

## v2.1.6 — 2026-07-29

**Fixed: the Trio comparison panel returned a server error.** It read a
zone off the stored event, but encounters never carried one — the zone
was being written to the character record instead. The panel failed on
every request as soon as any fight was tagged with a trio, which is to
say for anyone who had typed `/who`. Fights now record the zone and your
level as they happen.

**Fixed: gear advice claimed you could not use your own items.** Items
whose class line reads "ALL except NEC WIZ MAG ENC" were not being read
at all, so a quarter of a real inventory reached the advisor with no
verdict on whether you could equip it — and it guessed. A Shadow
Knight/Wizard was told to hand a mace to their pet because "your Wizard
cannot use it", when their Shadow Knight could. Those items are now
read correctly, and the advisor is told not to reason about class
restrictions it has already been given the answer to.

**Fixed: saving a spell set failed if you had never saved one in game.**
The game only creates its spell-set section the first time you save a
set yourself, and the app refused to write into a file that lacked it —
exactly the person the feature is meant to help. It now creates the
section. Write your set while logged out: the game rewrites this file
when you camp.

**One loadout, recorded two ways, is now one row.** Your class trio
reaches the app from two places — `/who`, which uses the game's order,
and the Advisor dropdowns, which use yours — so a single loadout could
appear twice under different spellings and split its own fights in half.
Trio comparison now groups by the classes themselves. Each row also
shows the levels you played it at and when, so you can tell an honest
comparison from one that is really just measuring levels. Come back to a
trio later and it adds to the same row, with a run count so the dates
are not mistaken for continuous play.


**Beta pet gear is called out.** The pet's equipment list is kept between
sessions on purpose, since pet gear survives death and re-summon — but it
does not survive a wipe. A list read before launch now says so and asks
for a fresh `/pet inventory check`, instead of presenting a vanished
pet's gear as current.

**Fixed: a custom endpoint sent requests to OpenAI.** Settings had no
field for the endpoint address, so choosing Custom left it empty — and an
empty address falls through to OpenAI, which answers 401 because your key
belongs to Groq or OpenRouter. There is now a field for it, a warning
while it is blank, and the app refuses to send anything rather than
posting your key to the wrong provider.

## v2.1.5 — 2026-07-28

**Fixed: the app could refuse to start**, with a database error about a
character name already existing. Character records were keyed by name
alone, so a record saved before the server was known became unfindable —
and the app tried to add it a second time. Records are now keyed by name
AND server, which also means two characters sharing a name on different
servers can finally both exist. Existing databases migrate on startup.

**Fixed: the overlay could render solid black.** Making the window
click-through rewrote its window style, which on some machines discards
the transparency settings Tk had already applied — leaving the widget
painting black while everything behind it kept working normally. The
settings are now re-applied whenever the style changes.

**The overlay says when it has stopped reading.** Frozen numbers used to
look identical to a quiet night. If the log has not grown, or a newer log
exists for a different character — what happens the moment you roll one,
since the app picks its log at startup — the overlay now says so instead
of silently showing stale values.

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

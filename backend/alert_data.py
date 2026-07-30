"""Vendored alert/timer data for EQL.

Distilled from kpxcoolx/eql-alerts `eql_starter.triggers.json` (MIT)
— community-measured EQL spell durations and raid-mechanic timers.
SPELL_TIMERS keys are lowercase spell names matched against OUR cast
lines (tier suffix stripped); name collisions kept the SHORTEST
duration (safer to under-promise a mez). MECHANICS regexes run at
the END of the parser chain, only on lines nothing else matched.
Regenerate from the eql-alerts pack if EQL rebalances durations.

Entries marked `[eqlbuilds]` come from the eqlbuilds.com snapshot's
`durationTicks` (x6 = seconds) instead, NOT the alerts pack — that
pack is a raid trigger list and carries almost nothing below the
high-end, so most low-level content is simply absent from it. The
marked rows are every NECROMANCER, SHAMAN and DRUID spell cast at an
enemy that has a duration (hostile targetTypeId + durationTicks > 0):
DoTs, plus the roots, snares, fears, charms, slows and resist
debuffs, which need timers just as much and never tick — a shaman
has no other way to know when a slow or a malaise has dropped.
The druid pass incidentally covers nine RANGER spells that share a
name and an identical duration.

Still pack-only, and still missing every hostile spell with a
duration: Enchanter (36, INCLUDING the whole charm/mez line at
1230s — breaking a mez is the classic group error and it has no
timer at all), Bard (18), Ranger (5 beyond the shared ones), Cleric
(9), Shadow Knight (4), Paladin (4), Wizard (3), Beastlord (2),
Magician (1). Verified with the same selection rule; none of those
90 names collide across classes on duration, so filling them needs
no judgement, only the extraction.

These values are exact rather than community-measured, so a
regenerate must PRESERVE them; they are also CC BY-SA (see
NOTICE.md), which the MIT alerts data is not. Keep the marker on
every such row.

Where the two sources disagree and the PACK IS LONGER, the eqlbuilds
value wins: a timer that outlives its effect is the one failure this
table must not have, and the pack's own rule was already "keep the
shortest on collision". Six necro rows were lowered on that basis
(asystole, boil blood, chilling embrace, envenomed bolt, scourge,
venom of the snake), one shaman row (plague 132 -> 78; the spell is
Shaman-only, so there is no cross-class reading of that name to
preserve), and six more once the audit was run across ALL rows
rather than only the hostile ones: spirit of the puma 85 -> 60 (the
largest over-run left, and nothing to do with the bard question),
drifting death 60 -> 54, harmshield 20 -> 18, glimpse 13 -> 12,
breeze 1626 -> 1620 and sight graft 1625 -> 1620. Where the pack is
SHORTER it stands, since it already under-promises -- cajole undead
1140 vs 1230 is left alone, as is shaman vision 720 vs 840.

NOT yet reconciled: TWELVE bard songs, every one of them 18 in the
pack against 12 in the game data. One identical gap repeated twelve
times reads as a pack CONVENTION, not twelve separate errors, and
guessing wrong either shortens every song timer a bard owns or
leaves them all long. It wants one measurement, not a sweep: sing a
song, stop, and the gap between the cast line and "worn off" settles
all twelve. A non-bard's log cannot supply it — songs others sing on
you produce no fade line at all (checked against a 90MB log: 2495
"begins singing" lines, zero song fades).

Two entries run the other way -- nimble 12 vs 3240, strengthen death
420 vs 3600 -- and are almost certainly NAME COLLISIONS between
different spells, which is why nothing here is reconciled by name
match alone."""
import re

SPELL_TIMERS = {
    "aanya's q": 1440,
    "aegis of ro": 420,
    "affliction": 84,          # [eqlbuilds] 14 ticks
    "agilmente's aria of eagles": 18,
    "angstlich's assonance": 60,
    "anthem de arms": 18,
    "argli": 120,
    "asphyxiate": 120,
    "asystole": 42,            # [eqlbuilds] 7 ticks
    "augment": 1560,
    "augmentation": 850,
    "auspice": 54,             # [eqlbuilds] 9 ticks
    "avatar": 360,
    "bane": 45,
    "bash!": 5,
    "bedlam": 420,
    "beguile undead": 1230,    # [eqlbuilds] 205 ticks
    "berserk": 300,
    "bewitching bravura": 18,
    "bind sight": 720,
    "bind wound": 10,
    "blinding luminance": 24,  # [eqlbuilds] 4 ticks
    "boil blood": 42,          # [eqlbuilds] 7 ticks
    "bond of death": 54,
    "boon of the garou": 360,
    "breath of ro": 60,
    "breeze": 1620,            # [eqlbuilds] 270 ticks
    "brilliance": 2400,
    "burnout iv": 900,
    "cadeau of flame": 420,
    "cajole undead": 1140,
    "call of fire": 600,
    "cancelling of life": 60,  # [eqlbuilds] 10 ticks
    "cascading darkness": 96,  # [eqlbuilds] 16 ticks
    "cassindra's elegy": 18,
    "celestial cleansing": 24,
    "celestial elixir": 24,
    "cessation": 60,
    "cessation of life": 96,   # [eqlbuilds] 16 ticks
    "ch": 10,
    "ch | ${2} <--": 10,
    "chilling embrace": 36,    # [eqlbuilds] 6 ticks
    "chloroblast | ${2} <--": 3,
    "clarity": 1620,
    "clarity ii": 1980,
    "clinging darkness": 48,   # [eqlbuilds] 8 ticks
    "coe": 3600,
    "coth cool down timer": 15,
    "creeping crud": 48,       # [eqlbuilds] 8 ticks
    "curse": 30,               # [eqlbuilds] 5 ticks
    "curse of the spirits": 87,
    "dark soul": 30,           # [eqlbuilds] 5 ticks
    "defensive": 180,
    "deftdance": 15,
    "di": 600,
    "dictate": 48,
    "disease cloud": 360,      # [eqlbuilds] 60 ticks
    "disempower": 120,         # [eqlbuilds] 20 ticks
    "divine aura": 18,
    "divine barrier": 18,
    "divine favor": 300,
    "divine glory": 3000,
    "divine str": 3000,
    "dl | ${2} <--": 4,
    "dominate undead": 1230,   # [eqlbuilds] 205 ticks
    "donal's chestplate of mourning": 480,
    "dooming darkness": 90,    # [eqlbuilds] 15 ticks
    "dread": 48,
    "drifting death": 54,      # [eqlbuilds] 9 ticks
    "drones": 60,
    "drones of doom": 48,      # [eqlbuilds] 8 ticks
    "drowsy": 210,             # [eqlbuilds] 35 ticks
    "duelist": 12,
    "elemental rhythms": 18,
    "elixir | ${2} <--": 4,
    "engulfing darkness": 60,  # [eqlbuilds] 10 ticks
    "engulfing roots": 180,    # [eqlbuilds] 30 ticks
    "ensnare": 840,            # [eqlbuilds] 140 ticks
    "ensnaring roots": 96,     # [eqlbuilds] 16 ticks
    "enthrall": 48,
    "entrance": 72,
    "enveloping roots": 60,    # [eqlbuilds] 10 ticks
    "envenomed bolt": 36,      # [eqlbuilds] 6 ticks
    "envenomed breath": 42,    # [eqlbuilds] 7 ticks
    "eternities torment": 126, # [eqlbuilds] 21 ticks
    "evade": 10,
    "evasive": 180,
    "fascination": 36,
    "fear": 18,                # [eqlbuilds] 3 ticks
    "fire": 12,                # [eqlbuilds] 2 ticks
    "fixation of ro": 600,     # [eqlbuilds] 100 ticks
    "flame lick": 36,          # [eqlbuilds] 6 ticks
    "flash of light": 12,      # [eqlbuilds] 2 ticks
    "flying kick!": 4,
    "fufil's": 18,
    "furious": 9,
    "glimpse": 12,             # [eqlbuilds] 2 ticks
    "grasping roots": 48,      # [eqlbuilds] 8 ticks
    "guardian rhythms": 18,
    "harmony": 120,            # [eqlbuilds] 20 ticks
    "harmony of nature": 42,   # [eqlbuilds] 7 ticks
    "harmshield": 18,          # [eqlbuilds] 3 ticks
    "haste": 18,
    "heart flutter": 36,       # [eqlbuilds] 6 ticks
    "heat blood": 36,          # [eqlbuilds] 6 ticks
    "hungry earth": 48,        # [eqlbuilds] 8 ticks
    "ice": 18,                 # [eqlbuilds] 3 ticks
    "ignite blood": 42,        # [eqlbuilds] 7 ticks
    "ignite bones": 12,        # [eqlbuilds] 2 ticks
    "immo": 66,
    "immolate": 48,            # [eqlbuilds] 8 ticks
    "incapacitate": 390,       # [eqlbuilds] 65 ticks
    "infectious cloud": 126,   # [eqlbuilds] 21 ticks
    "innerflame": 12,
    "insidious fever": 840,    # [eqlbuilds] 140 ticks
    "insidious malady": 840,   # [eqlbuilds] 140 ticks
    "insidious retrogression": 96,  # [eqlbuilds] 16 ticks
    "insipid ditty": 18,
    "instill": 96,             # [eqlbuilds] 16 ticks
    "invoke fear": 42,         # [eqlbuilds] 7 ticks
    "jaxan's jig o' vigor": 18,
    "jonthan's inspiration": 18,
    "jonthan's whistling warsong": 12,
    "kick!": 8,
    "kintaz": 30,
    "largo's absonant": 18,
    "lay on hands": 900,
    "leech": 54,               # [eqlbuilds] 9 ticks
    "listless power": 390,     # [eqlbuilds] 65 ticks
    "lugubrious lament": 12,
    "lyssa's solidarity of vision": 18,
    "malaise": 840,            # [eqlbuilds] 140 ticks
    "malaisement": 840,        # [eqlbuilds] 140 ticks
    "malosi": 840,             # [eqlbuilds] 140 ticks
    "mend": 90,
    "mesmerize": 24,
    "negation of life": 90,    # [eqlbuilds] 15 ticks
    "nillipus' march of the wee": 18,
    "nimble": 12,
    "niv's harmonic": 18,
    "niv's melody of preservation": 18,
    "nt | ${2} <--": 5,
    "numb the dead": 120,      # [eqlbuilds] 20 ticks
    "occlusion of sound": 18,
    "odium": 30,
    "orb of mastery": 301,
    "pact of shadow": 24,      # [eqlbuilds] 4 ticks
    "panic the dead": 54,      # [eqlbuilds] 9 ticks
    "paralyzing earth": 180,   # [eqlbuilds] 30 ticks
    "pick pocket": 10,
    "plague": 78,              # [eqlbuilds] 13 ticks
    "poison bolt": 24,         # [eqlbuilds] 4 ticks
    "pox": 110,
    "precision": 180,
    "psalm of cooling": 18,
    "psalm of mystic shielding": 18,
    "psalm of purity": 18,
    "psalm of vitality": 18,
    "psalm of warmth": 18,
    "puretone": 240,
    "purifying rhythms": 18,
    "pyrocuror": 114,
    "quivering veil of xarn": 18,
    "rapture": 24,
    "remedy | ${2} <--": 3,
    "rest the dead": 180,      # [eqlbuilds] 30 ticks
    "root": 48,                # [eqlbuilds] 8 ticks
    "sanctification": 15,
    "scent of darkness": 840,  # [eqlbuilds] 140 ticks
    "scent of dusk": 840,      # [eqlbuilds] 140 ticks
    "scent of shadow": 840,    # [eqlbuilds] 140 ticks
    "scourge": 72,             # [eqlbuilds] 12 ticks
    "screaming terror": 18,
    "sha's ferocity": 1057,
    "sha's lethargy": 204,
    "shackle of bone": 210,    # [eqlbuilds] 35 ticks
    "shackle of spirit": 210,  # [eqlbuilds] 35 ticks
    "shadow compact": 24,      # [eqlbuilds] 4 ticks
    "shadow vortex": 450,      # [eqlbuilds] 75 ticks
    "shadowbond": 24,
    "shauri's sonorous clouding": 18,
    "shield of flame": 360,
    "shield of song": 18,
    "shifting sight": 1140,
    "shroud of death": 1200,
    "shroud of hate": 600,
    "shroud of pain": 600,
    "shroud of undeath": 1200,
    "sicken": 84,              # [eqlbuilds] 14 ticks
    "sight graft": 1620,       # [eqlbuilds] 270 ticks
    "siphon strength": 360,    # [eqlbuilds] 60 ticks
    "snare": 234,              # [eqlbuilds] 39 ticks
    "solon's charismatic concord": 18,
    "song: jonthan's provocation": 18,
    "soul consumption": 30,
    "soul well": 73,
    "spirit of cheetah": 48,
    "spirit of oak": 2160,
    "spirit of the puma": 60,  # [eqlbuilds] 10 ticks
    "splurt": 102,
    "spook the dead": 18,      # [eqlbuilds] 3 ticks
    "stab!": 4,
    "stinging swarm": 54,      # [eqlbuilds] 9 ticks
    "stonestance": 12,
    "strengthen death": 420,
    "sunbeam": 12,             # [eqlbuilds] 2 ticks
    "surge of enfeeblement": 360,  # [eqlbuilds] 60 ticks
    "tagar's insects": 210,    # [eqlbuilds] 35 ticks
    "tainted breath": 42,      # [eqlbuilds] 7 ticks
    "tangling weeds": 18,      # [eqlbuilds] 3 ticks
    "tarew's aquatic ayre": 24,
    "taunt": 6,
    "togor's insects": 210,    # [eqlbuilds] 35 ticks
    "tos": 96,
    "totu": 96,
    "translocate": 306,
    "trickster's augmentation": 204,
    "trueshot": 120,
    "tuyen's": 18,
    "twilight": 18,
    "valiant companion": 210,
    "vampiric": 54,
    "vampiric curse": 54,      # [eqlbuilds] 9 ticks
    "velocity": 2160,
    "vengeance of the wild": 30,# [eqlbuilds] 5 ticks
    "venom of the snake": 36,  # [eqlbuilds] 6 ticks
    "verses of victory": 18,
    "vex": 60,
    "vilia's chorus of celerity": 18,
    "vision": 720,
    "vog": 2520,
    "voice of the berserker": 1200,
    "voiddance": 8,
    "walking sleep": 210,      # [eqlbuilds] 35 ticks
    "wave of enfeeblement": 240,  # [eqlbuilds] 40 ticks
    "weapon shield": 20,
    "whirlwind": 9,
    "winged death": 60,
    "wrath": 30,
    "wrath of nature": 180,
}

# (name, compiled pattern, seconds)
MECHANICS = [
    ("Lava Breath",
     re.compile("^(Your body combusts as the lava hits you\\.|([\\w -'`]+)'s body combusts as the lava hits them\\.|You resist the Lava Breath spell\\!)$"),
     12),
    ("Dragon Roar",
     re.compile("^(You flee in terror\\.|You resist the Dragon Roar spell\\!)$"),
     36),
    ("Feared (Dragon Roar landed)",
     re.compile("^You flee in terror\\.$"),
     18),
    ("Frost Breath",
     re.compile("^(Your body freezes as the frost hits you\\.  You have taken \\d+ points of damage\\.|You resist the Frost Breath spell\\!|([\\w]+)'s body freezes as the frost hits them\\.)$"),
     12),
    ("Dragon Roar",
     re.compile("^(You flee in terror\\.|You resist the Dragon Roar spell\\!)$"),
     36),
    ("Feared (Dragon Roar landed)",
     re.compile("^You flee in terror\\.$"),
     18),
    ("Frost Breath",
     re.compile("^(Your body freezes as the frost hits you\\.  You have taken \\d+ points of damage\\.|You resist the Frost Breath spell\\!|([\\w]+)'s body freezes as the frost hits them\\.)$"),
     12),
    ("Cazic Thule Pop",
     re.compile("^Cazic Thule shouts 'Denizens of Fear, your master commands you to come forth to his aid\\!\\!'$"),
     40),
    ("Bazzt Zzzt DT",
     re.compile("Bazzt Zzzt shouts"),
     45),
    ("The Spiroc Lord DT",
     re.compile("The Spiroc Lord shouts"),
     45),
    ("Keeper of Souls DT",
     re.compile("Keeper of Souls shouts"),
     45),
    ("Overseer of Air DT",
     re.compile("Overseer of Air shouts"),
     45),
    ("Sister of the Spire DT",
     re.compile("Sister of the Spire shouts"),
     45),
    ("Eye of Veeshan DT",
     re.compile("Eye of Veeshan shouts"),
     45),
    ("the Hand of Veeshan DT",
     re.compile("the Hand of Veeshan shouts"),
     45),
    ("Master Yael",
     re.compile("Master Yael shouts"),
     45),
]

# Ability cooldowns (seconds) started on cast/activation and SNAPPED to
# the game's own "You can use the ability X again in M minute(s) S
# seconds." readout whenever it prints. Shaves: landing the listed verb
# reduces the named cooldown (facts per GiuffreLab/eql-metrics README).
ABILITY_COOLDOWNS = {
    "lay on hands": 900,
    "harm touch": 1200,
    "quick buff": 600,
}
# melee verb -> (cooldown timer to reduce, seconds shaved per landing)
COOLDOWN_SHAVES = {
    "smite": ("Lay on Hands", 60),
    "reave": ("Harm Touch", 60),
}

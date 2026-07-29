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
42 marked rows are every NECROMANCER spell cast at an enemy that
has a duration (hostile targetTypeId + durationTicks > 0): DoTs,
plus the roots, snares, fears and charms, which need timers just
as much and never tick. Other classes are still pack-only.

These values are exact rather than community-measured, so a
regenerate must PRESERVE them; they are also CC BY-SA (see
NOTICE.md), which the MIT alerts data is not. Keep the marker on
every such row.

Where the two sources DISAGREE the pack's value was kept, since
its collision rule was a deliberate choice and other classes read
the same row. Seven necro spells differ and are worth a look if a
timer ever reads long: asystole 72/42, boil blood 108/42, cajole
undead 1140/1230, chilling embrace 96/36, envenomed bolt 42/36,
scourge 126/72, venom of the snake 42/36 (pack/eqlbuilds)."""
import re

SPELL_TIMERS = {
    "aanya's q": 1440,
    "aegis of ro": 420,
    "agilmente's aria of eagles": 18,
    "angstlich's assonance": 60,
    "anthem de arms": 18,
    "argli": 120,
    "asphyxiate": 120,
    "asystole": 72,
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
    "boil blood": 108,
    "bond of death": 54,
    "boon of the garou": 360,
    "breath of ro": 60,
    "breeze": 1626,
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
    "chilling embrace": 96,
    "chloroblast | ${2} <--": 3,
    "clarity": 1620,
    "clarity ii": 1980,
    "clinging darkness": 48,   # [eqlbuilds] 8 ticks
    "coe": 3600,
    "coth cool down timer": 15,
    "curse of the spirits": 87,
    "dark soul": 30,           # [eqlbuilds] 5 ticks
    "defensive": 180,
    "deftdance": 15,
    "di": 600,
    "dictate": 48,
    "disease cloud": 360,      # [eqlbuilds] 60 ticks
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
    "drifting death": 60,
    "drones": 60,
    "duelist": 12,
    "elemental rhythms": 18,
    "elixir | ${2} <--": 4,
    "engulfing darkness": 60,  # [eqlbuilds] 10 ticks
    "enthrall": 48,
    "entrance": 72,
    "envenomed bolt": 42,
    "eternities torment": 126, # [eqlbuilds] 21 ticks
    "evade": 10,
    "evasive": 180,
    "fascination": 36,
    "fear": 18,                # [eqlbuilds] 3 ticks
    "flying kick!": 4,
    "fufil's": 18,
    "furious": 9,
    "glimpse": 13,
    "guardian rhythms": 18,
    "harmshield": 20,
    "haste": 18,
    "heart flutter": 36,       # [eqlbuilds] 6 ticks
    "heat blood": 36,          # [eqlbuilds] 6 ticks
    "hungry earth": 48,        # [eqlbuilds] 8 ticks
    "ignite blood": 42,        # [eqlbuilds] 7 ticks
    "ignite bones": 12,        # [eqlbuilds] 2 ticks
    "immo": 66,
    "infectious cloud": 126,   # [eqlbuilds] 21 ticks
    "innerflame": 12,
    "insidious retrogression": 96,  # [eqlbuilds] 16 ticks
    "insipid ditty": 18,
    "invoke fear": 42,         # [eqlbuilds] 7 ticks
    "jaxan's jig o' vigor": 18,
    "jonthan's inspiration": 18,
    "jonthan's whistling warsong": 12,
    "kick!": 8,
    "kintaz": 30,
    "largo's absonant": 18,
    "lay on hands": 900,
    "leech": 54,               # [eqlbuilds] 9 ticks
    "lugubrious lament": 12,
    "lyssa's solidarity of vision": 18,
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
    "plague": 132,
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
    "scourge": 126,
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
    "sight graft": 1625,
    "siphon strength": 360,    # [eqlbuilds] 60 ticks
    "solon's charismatic concord": 18,
    "song: jonthan's provocation": 18,
    "soul consumption": 30,
    "soul well": 73,
    "spirit of cheetah": 48,
    "spirit of oak": 2160,
    "spirit of the puma": 85,
    "splurt": 102,
    "spook the dead": 18,      # [eqlbuilds] 3 ticks
    "stab!": 4,
    "stonestance": 12,
    "strengthen death": 420,
    "surge of enfeeblement": 360,  # [eqlbuilds] 60 ticks
    "tarew's aquatic ayre": 24,
    "taunt": 6,
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
    "venom of the snake": 42,
    "verses of victory": 18,
    "vex": 60,
    "vilia's chorus of celerity": 18,
    "vision": 720,
    "vog": 2520,
    "voice of the berserker": 1200,
    "voiddance": 8,
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

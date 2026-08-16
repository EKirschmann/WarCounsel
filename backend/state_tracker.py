"""In-memory character/session state built from the live event stream.

Seed events (log history replayed at startup) establish zone/level/class
and pre-fill the ledger buffer; only LIVE events count toward session
stats (kills, damage, DPS) so numbers reflect this play session.
"""
import logging
import re
from collections import deque
from datetime import datetime, timedelta
from typing import Optional

from backend import alerts, builds_data, race_unlocks, spell_file
from backend.alert_data import (ABILITY_COOLDOWNS, BASE_DURATION_ROWS,
                                COOLDOWN_SHAVES, SPELL_TIMERS,
                                TIER_DURATION_RATE)
from backend.log_system import events as ev
from backend.log_system.parser import CLASS_ABBREV, spell_tier, strip_tier

logger = logging.getLogger(__name__)

# How long after our own cast that spell's damage may still be arriving.
# See CharacterTracker._cast_less for the measurement behind it.
PROC_CAST_WINDOW_S = 12.0

DPS_WINDOW_SECONDS = 60
COMBAT_TIMEOUT_SECONDS = 8

# How far past YOUR last action a groupmate's swings may hold the fight
# open. A group fight does not pause because you ran out of mana, went to
# heal, or died -- but an unbounded extension would let a busy zone hold
# one "encounter" open all night, and the DPS clock would run through
# every quiet stretch. Bounded per EQBuddy, which uses ~20s for the same
# reason. Only CONFIRMED groupmates extend: before the roster was
# trustworthy this could not be done at all.
GROUP_EXTEND_SECONDS = 20

# How long a filtered contributor stays on the "not counted" list after
# their last hit. Long enough to decide, short enough that the list stays
# a question rather than a session ledger.
FILTERED_TTL_S = 300

# EQL groups hold FOUR, not the six of the EverQuest this is reimagined
# from. Player-supplied and worth writing down: nothing in the log states
# it, and assuming the classic number is the same mistake the wiki's
# classic-era item pages make. Used as a WARNING, never a cap -- the
# roster gates the meter and extends the combat clock, so silently
# dropping a name would hide damage, while an over-full roster only means
# something needs a look.
GROUP_CAP = 4
LEDGER_SIZE = 300
REWARD_WINDOW_SECONDS = 3  # XP/coin <-> kill attribution window

_COIN_RE = re.compile(r"(\d+)\s+(platinum|gold|silver|copper)")
_COIN_VALUE = {"platinum": 1000, "gold": 100, "silver": 10, "copper": 1}


def _coin_copper(amount: str) -> int:
    """'3 gold, 5 silver and 7 copper' -> 357 (copper)."""
    return sum(int(n) * _COIN_VALUE[d]
               for n, d in _COIN_RE.findall(amount or ""))

_FULL_TO_ABBR = {v.lower(): k for k, v in CLASS_ABBREV.items()}


def _abbrev_classes(class_str) -> str:
    """'Paladin/Druid/Monk' -> 'PAL/DRU/MNK' (unknown names pass through)."""
    if not class_str:
        return ""
    return "/".join(_FULL_TO_ABBR.get(p.strip().lower(), p.strip())
                    for p in str(class_str).split("/"))


RE_MOTE = re.compile(r"^Mote of (.+?) Potential$")
# raid token, launch-day patch: merges like a mote for +1 rank
RE_VOID_TOKEN = re.compile(r"^(?:A )?Void[-\s]?touched Potential$",
                           re.IGNORECASE)


def _tier_scaled(base: str, secs: int, cast_name: str) -> int:
    """Duration at the tier actually cast, where that is knowable.

    Upgrading a spell lengthens it (eqltools /learn/spell-upgrades), and
    the log names the tier as a roman-numeral suffix, so a flat base
    duration was showing a rank-10 spell at HALF its real length.

    Scaled ONLY for BASE_DURATION_ROWS -- rows taken from the game's own
    durationTicks. A community-measured pack row was timed at some
    unknown tier, and scaling it again would compound a tier already
    baked in, producing a timer that outlives its spell. That is the one
    failure this table must not have, so an unknown row stays flat.

    Rounded DOWN, and at the DoT rate rather than the debuff rate, both
    for the same reason: every remaining error points at under-promising.
    """
    tier = spell_tier(cast_name)
    if tier <= 0 or base not in BASE_DURATION_ROWS:
        return secs
    return int(secs * (1 + TIER_DURATION_RATE * tier))


# "A froglok ghoul", "the guard" -- an attacker carrying an article is an
# NPC, never a player.
_NPC_NAME = re.compile(r"^(?:[Aa]n?|[Tt]he) ")


def _foe_key(name: str) -> str:
    """Log lines capitalize the article at sentence start ("A dread bone
    kicks YOU") but not mid-sentence ("You crush a dread bone") -- fold the
    article case so one mob is one foe row. Named mobs (no article) pass
    through untouched. Note: the log carries no unique mob IDs, so two
    distinct mobs sharing a name still merge into one row by design."""
    for art in ("A ", "An ", "The "):
        if name.startswith(art):
            return art.lower() + name[len(art):]
    return name


class CharacterTracker:
    def __init__(self, name: Optional[str], server: Optional[str]):
        self.name = name or "Unknown"
        self.server = server or "unknown"
        # Enrichment (from who-lines / level-ups / DB / user edits)
        self.level: Optional[int] = None
        self.class_str: Optional[str] = None
        self.race: Optional[str] = None
        self.playstyle: Optional[str] = None
        self.aa_available: Optional[int] = None  # unspent AA points (user-set; +1 per gain)
        self.spell_slots: Optional[int] = None   # spell slots unlocked via AAs (user-set)
        self.pet_slots: Optional[int] = None     # pet equipment slots (user-set)
        self.pet_classes: Optional[str] = None   # pet's equip class(es), user-set
        self.max_hp: Optional[int] = None        # user-reported (log has no max HP)
        # /con results, keyed by mob name. EQL prints the mob's LEVEL
        # outright, which is the only objective per-mob difficulty the
        # log carries -- colour and verdict prose are not comparable
        # across levels. Kept across encounters so a mob considered
        # once stays classified for every later fight with it.
        self.considered: dict = {}
        self.oom_count = 0
        self.max_mana: Optional[int] = None      # user-reported
        self.zone: Optional[str] = None
        # Session counters (live events only)
        self.damage_dealt = 0
        self.damage_taken = 0
        self.healing_received = 0
        self.healing_done = 0
        self.kills = 0
        self.deaths = 0
        self.xp_ticks = 0
        self.xp_percent = 0.0   # summed from EQL's "(1.107%)" exp lines
        self.aa_points = 0
        self.skill_ups = 0
        self.swings_hit = 0     # melee accuracy
        self.swings_missed = 0
        self.loots: deque[str] = deque(maxlen=20)
        self.last_target: Optional[str] = None
        self.last_event_at: Optional[datetime] = None
        self.position: Optional[dict] = None  # from /loc lines
        self.session_max_dps: float = 0.0
        # Rolling buffers
        self._dmg_window: deque[tuple[datetime, int]] = deque()
        self.ledger: deque[dict] = deque(maxlen=LEDGER_SIZE)
        # Current/last encounter: per-ability damage breakdown. Persists after
        # combat ends; a new pull archives it into encounter_history.
        self.encounter: Optional[dict] = None
        self.encounter_history: deque[dict] = deque(maxlen=5)  # finished pulls, newest first
        # Loadout staleness: cast spells not castable by the saved trio
        self.unknown_casts: dict[str, str] = {}
        self.loadout_hint: Optional[str] = None
        # Death recap: frozen slice of incoming damage at the moment of death
        self.last_death: Optional[dict] = None
        # Per-mob session stats (kills, attributed xp, loot seen on corpses)
        self.mob_stats: dict[str, dict] = {}
        self._last_kill: Optional[tuple] = None  # (foe key, ts) for xp attribution
        self._pending_xp: Optional[tuple] = None  # (ts, pct): XP printed pre-kill
        # Finished pulls awaiting DB persistence (drained by the flush loop)
        self.pending_encounters: list[dict] = []
        # Injected by main: spellbook loader + whether a log file exists
        self.spellbook_loader = None
        self.has_log = False
        # Level + abbreviated trio per player seen in /who output
        self.who_roster: dict[str, dict] = {}
        # Pet name -> owner name, learned from "My leader is X" lines
        self.pet_owners: dict[str, str] = {}
        self.pet_owners_dirty = False
        # POSITIVE proof of who is grouped with us. Needed because a
        # stranger fighting a mob that merely SHARES a name with ours is
        # otherwise credited as an ally: the ally gate checks the TARGET
        # ("did they hit one of our foes"), and _foe_key can only compare
        # names because the log has no mob IDs. Gating on the CONTRIBUTOR
        # is the only side of that comparison we can actually verify.
        # EMPTY means "no evidence", which FAILS OPEN -- never hide rows we
        # cannot disprove. Not persisted: a restart re-opens the filter,
        # which is the safe direction.
        self.group_members: set = set()  # flush loop persists when set
        # Everyone whose damage we HID, with enough context to judge them:
        # how many of our fights they turned up in. A groupmate who never
        # speaks is invisible to every automatic signal, but they are in
        # nearly every fight -- so the count is the tell, and the player is
        # the only one who can read it. Survives restarts with the roster.
        self.filtered_seen: dict = {}
        # class -> the class-unique spell that proved it. Evidence only:
        # never written into class_str (see _infer_class).
        # Names the player said are NOT grouped. Held until EVIDENCE
        # contradicts it -- a join line, an invite, a word in group chat --
        # because those are the signals that would have added them anyway,
        # and a dismissal should not outlive the thing it was about.
        self.ignored_contributors: dict = {}
        # Inventory-panel numbers read from the screen (optional OCR)
        # race-unlock turn-ins seen this session: item -> tally + where it goes
        self.unlock_loot: dict = {}
        self._unlock_alerted: set = set()
        self.ocr_stats: dict = {}
        # which vitals the screen supplied (vs the player typing them)
        self.vitals_ocr: set = set()
        self.ocr_stats_at = None
        # anyone who has spoken in any channel -- pets never do
        self._chat_seen: set = set()
        self.inferred_classes: dict = {}
        self._infer_at: dict = {}
        self._infer_seen: set = set()
        self.session_fights = 0
        self._aa_from_db = False       # roster restored from DB, not the log
        # Owned AA ranks from '/alternateadv list' (one line per rank)
        self.owned_aas: dict[str, dict] = {}
        self._last_aa_seen: Optional[datetime] = None
        self._last_aa_name: Optional[str] = None
        # set when a pet summon is cast but no pet maps to us — the pet's
        # damage lands in the ally rows until /pet leader is typed
        self.pet_hint = False
        # /pet inventory check output: slot -> item the pet actually wears
        self.pet_inventory: dict[str, str] = {}
        self._pet_inv_ts: Optional[datetime] = None
        # session persistence writes only when something changed
        self._dirty = True
        # lowercase effect names granted by owned exaltation stones — damage
        # "by <one of these>" is a proc, labeled "(exaltation)" in the parse
        self.exalt_effects: set = set()
        # exalt effects that are ALSO scribed spells: labeled only when the
        # client spell file marks them proc-granted AND no cast was seen
        self.exalt_ambiguous: set = set()
        # spells this character has been SEEN casting (log evidence)
        self.spell_casts: set = set()
        # WHEN each spell was last cast, not merely whether it ever was.
        # A name you both cast and proc -- Ignite, off an owned stone, 532
        # casts and 407 proc hits in one log -- collapses to whichever the
        # session saw first if all you keep is a set.
        self.spell_cast_at: dict = {}
        self.crits = 0
        self.coin_copper = 0  # session coin total, all sources (in copper)
        self.rune_absorbed = 0  # damage eaten by rune buffs this session
        self.loot_count = 0     # total items looted this session
        # live countdowns (spell durations from OUR casts + raid
        # mechanics) and fired tracked-rule alerts — transient, never
        # persisted
        self.active_timers: list = []
        # cast names already reported as having no SPELL_TIMERS entry —
        # diagnostic only, so it is never persisted or snapshotted
        self._timer_misses: set = set()
        # timers a kill removed, held until their original expiry so a
        # later tick can prove the kill was a same-named impostor
        self._reaped: list = []
        self.alerts: deque = deque(maxlen=8)
        self._alert_seq = 0
        self._alert_cooldown: dict = {}
        self.stuns_taken = 0
        self.stuns_landed = 0     # staggers pinned on OUR OWN hit; about
                                  # half of a log's are other players'
        self.mez_applied = 0
        self.mods: dict = {}      # 'Slay Undead' -> times seen
        self._last_ability: tuple = (None, None, None)
        self.overheal = 0          # attempted-minus-landed healing
        self.motes: dict = {}      # mote tier -> count looted
        # finished sessions awaiting DB persistence (login banner rolls
        # the session over; drained by the flush loop like encounters)
        self.pending_sessions: list = []
        # session clock (LOG time, so replays stay honest) + active-hours
        # buckets (2-min buckets touched by any live event — AFK time
        # cannot poison per-hour rates; pattern per EQBuddy)
        self.session_started = None
        self._active_buckets: set = set()
        self._dinged = False  # leveled this session -> hours-to-level exact
        self._pending_coin: Optional[tuple] = None  # (ts, copper) pre-kill

    def _touch_encounter(self, ts: datetime) -> None:
        if (self.encounter is None or
                (ts - self.encounter["last"]).total_seconds() > COMBAT_TIMEOUT_SECONDS):
            if self.encounter is not None:
                self.encounter_history.appendleft(self.encounter)
                self.pending_encounters.append(
                    self._encounter_view(self.encounter, live=False))
                del self.pending_encounters[:-10]
            self.session_fights += 1
            self.encounter = {"started": ts, "last": ts, "last_own": ts,
                              "target": None,
                              "total_out": 0, "total_in": 0, "abilities": {},
                              "foes": {}, "trio": self.class_str,
                              # captured HERE, not at flush time: a fight
                              # is often the last thing before a zone line,
                              # so tracker.zone has already moved on by the
                              # time pending_encounters drains
                              "zone": self.zone, "level": self.level,
                              # survivability signal, richer than a death:
                              # hp_floor tracks the deepest point reached by
                              # walking damage/heals against max_hp, and oom
                              # counts a loss condition that leaves no other
                              # trace. Both are None/0 when unknowable.
                              "hp": self.max_hp, "hp_floor": self.max_hp,
                              "oom": 0,
                              # stamped from /con at creation, so a later
                              # re-con cannot rewrite a finished fight
                              "mob_level": None, "mob_rare": False}
        else:
            self.encounter["last"] = ts
            # ...and OUR clock, which is what bounds how long a groupmate
            # may hold the fight open. Kept apart from "last" so their
            # damage cannot bootstrap its own extension window.
            self.encounter["last_own"] = ts

    def _note_unlock_loot(self, item: str, count: int, ts: datetime) -> None:
        """Flag loot that is a race-unlock turn-in, and keep a running tally.

        Nothing in the game says this at the moment it matters. A Gnoll Fang
        reads as vendor trash and is 1/1200th of a Barbarian, and the cost of
        not knowing is not a wasted click -- it is having sold four hundred
        of them.

        Alerted ONCE per item per session. These drop in bulk by design, so
        alerting per loot would bury every other alert under the very grind
        it is describing; the tally on the panel carries the repeats.
        """
        rec = race_unlocks.match(item)
        if not rec:
            return
        prog = self.unlock_loot.setdefault(
            rec["item"], {"count": 0, "race": rec["race"], "npc": rec["npc"],
                          "zone": rec["zone"], "total": rec.get("total"),
                          "factions": rec.get("factions") or [],
                          "note": rec.get("note")})
        prog["count"] += count
        if rec["item"] in self._unlock_alerted:
            return
        self._unlock_alerted.add(rec["item"])
        need = rec.get("total")
        self._push_alert(
            "unlock",
            f"{rec['item']} — {rec['race']} unlock turn-in "
            f"({rec['npc']}, {rec['zone']}"
            + (f"; {need} needed)" if need else ")"),
            ts)

    def _looks_like_pet(self, name: str) -> bool:
        """No player evidence for a name that is fighting alongside us.

        A groupmate's pet with a generated name ("Jabeker hits X") is
        TEXTUALLY IDENTICAL to a player, so there is no hard signal --
        EQLogParser reaches the same conclusion. What we do have is the
        absence of player evidence: a real player in the zone turns up in
        /who and usually says something eventually, while a pet does
        neither, ever.

        Only applied once we HAVE /who data. With an empty roster this
        would call everyone a pet, which is the failure it exists to
        prevent. And it never drops anyone -- these move to their own
        group, because the one case it gets wrong is a silent groupmate
        who was not in the /who, and that is precisely who the list is for.
        """
        if not self.who_roster:
            return False
        if name in self.who_roster or name in self.group_members:
            return False
        return name not in self._chat_seen

    def apply_ocr_stats(self, stats: dict) -> None:
        """Adopt numbers read off the Inventory panel.

        max_hp and max_mana were previously TYPED IN by the player -- the
        log never prints them -- and everything else here (AC, ATK, the
        attributes, the resists) had no source at all. This is the only
        place the app can learn them without asking.

        Screen-read, so treated as a reading and not as truth: values are
        kept under `ocr_stats` with their own timestamp, and only max_hp /
        max_mana are promoted into the fields the rest of the app uses --
        and only when the player has not set them by hand, since a typed
        value is a deliberate statement and a misread is not.
        """
        if not stats:
            return
        self.ocr_stats = dict(stats)
        self.ocr_stats_at = self.last_event_at
        for src, dest, manual in (("max_hp", "max_hp", "_max_hp_manual"),
                                  ("max_mana", "max_mana", "_max_mana_manual")):
            v = stats.get(src)
            if v and v > 0 and not getattr(self, manual, False):
                setattr(self, dest, v)
                # remembered rather than inferred from ocr_stats: that dict
                # is live-only, so after a restart an OCR-supplied number
                # looked exactly like a typed one
                self.vitals_ocr.add(dest)

    def trust_all(self, action: str) -> dict:
        """Apply one verdict to everyone currently on the not-counted list.

        Server-side rather than a loop of single calls from the browser:
        the list ages and grows as the log moves, so a client iterating a
        snapshot it fetched a moment ago would act on names that have since
        left it and miss ones that arrived.
        """
        names = [r["name"] for r in self.filtered_view()]
        for n in names:
            self.trust_member(n, action == "add", action=action)
        return {"ok": True, "action": action, "names": names,
                "group": sorted(self.group_members),
                "over_cap": len(self.group_members) > GROUP_CAP}

    def _infer_class(self, spell: str, ts=None) -> None:
        """Learn a class from a spell only WE could have cast.

        Class stays unknown until someone types /who, which gates the whole
        advisor -- but 80% of the ~1200 spells in the builds dataset belong
        to exactly one class, and casting one is proof. EQLogParser
        (Apache-2.0) ranks its class signals roster > targeting > /who >
        class-unique spell for the same reason; this is that last rung.

        Deliberately does NOT write class_str. A cast proves a class is IN
        the trio, never which of three slots it fills nor what the other
        two are, so writing a partial trio would state more than the
        evidence supports -- and class_str already has two writers whose
        orderings disagree. This records the evidence and lets the player
        confirm it.
        """
        if not spell:
            return
        base = strip_tier(spell)
        if base.lower() in self._infer_seen:
            return
        self._infer_seen.add(base.lower())
        try:
            owners = builds_data.spell_levels(base) or {}
        except Exception:
            return
        if len(owners) != 1:
            return  # shared spell lines prove nothing
        cls = next(iter(owners))
        self.inferred_classes[cls] = base
        self._infer_at[cls] = ts or self._infer_at.get(cls)

    def inferred_view(self) -> list[dict]:
        """Classes proven this session, most recently proven first."""
        rows = [{"cls": c, "spell": sp, "at": self._infer_at.get(c)}
                for c, sp in self.inferred_classes.items()]
        rows.sort(key=lambda r: (r["at"] is not None, r["at"]), reverse=True)
        return [{"cls": r["cls"], "spell": r["spell"]} for r in rows[:3]]

    def _adopt_pet_damage(self, pet: str) -> None:
        """Move damage this pet already dealt out of the ALLY bucket.

        A pet fights before it identifies itself: its first swings land
        while it is still an unknown name, so they are credited to
        `allies`, and the mapping that arrives later only redirects FUTURE
        damage to `own_pet`. The meter then showed the same pet twice --
        "Jabekn (pet)" for what came after, plain "Jabekn" for what came
        before, the second looking exactly like another player.

        total_out is raised by the same amount because the ally bucket
        never fed it: the damage was ours all along and was simply filed
        under a stranger. Without that the "You" row, computed as
        total_out minus the pet total, would drop by whatever we adopted.
        """
        enc = self.encounter
        if not enc:
            return
        moved = (enc.get("allies") or {}).pop(pet, 0)
        # A CHARMED pet was never in the ally bucket: an NPC-shaped attacker
        # we cannot tie to us is held in npc_pending instead, so that the
        # thousands of mob-vs-mob swings in a busy zone do not read as
        # "contributors we hid from you". Claim it here on the same terms.
        moved += (enc.get("npc_pending") or {}).pop(pet, 0)
        if not moved:
            return
        op = enc.setdefault("own_pet", {})
        op[pet] = op.get(pet, 0) + moved
        enc["total_out"] = enc.get("total_out", 0) + moved
        self.damage_dealt += moved

    def _mob(self, mob: str) -> dict:
        stats = self.mob_stats.setdefault(
            mob, {"kills": 0, "xp_percent": 0.0, "loots": []})
        stats.setdefault("coin_copper", 0)   # restored sessions may lack
        stats.setdefault("loot_drops", 0)    # the newer counters
        return stats

    def _absorb_pending_rewards(self, mob: str, ts: datetime) -> None:
        """XP/coin lines precede their kill line in EQL — claim any held
        within the reward window (forward attribution; _sweep_pending is
        the post-kill fallback)."""
        if (self._pending_xp and
                (ts - self._pending_xp[0]).total_seconds() <= REWARD_WINDOW_SECONDS):
            self._mob(mob)["xp_percent"] += self._pending_xp[1]
        self._pending_xp = None
        if (self._pending_coin and
                (ts - self._pending_coin[0]).total_seconds() <= REWARD_WINDOW_SECONDS):
            self._mob(mob)["coin_copper"] += self._pending_coin[1]
        self._pending_coin = None

    def _sweep_pending(self, ts: datetime) -> None:
        """Rewards whose window expired with NO kill line following fall
        BACK to the kill just before them — covers loot-the-corpse-later
        coin and trailing party XP without mis-crediting chain pulls
        (a forward claim always wins; this only runs at expiry)."""
        for attr, key in (("_pending_xp", "xp_percent"),
                          ("_pending_coin", "coin_copper")):
            pend = getattr(self, attr)
            if pend and (ts - pend[0]).total_seconds() > REWARD_WINDOW_SECONDS:
                if (self._last_kill and 0 <= (pend[0] - self._last_kill[1])
                        .total_seconds() <= REWARD_WINDOW_SECONDS):
                    self._mob(self._last_kill[0])[key] += pend[1]
                setattr(self, attr, None)

    def _fx_label(self, spell: str, ts=None) -> str:
        """Exaltation procs share the spell-damage line shape — the effect
        name gives them away. Names that are ALSO scribed are decided PER
        EVENT: damage with no cast of that spell behind it was not cast.

        This used to ask "did the session ever see a cast", which collapses
        a name you both cast and proc onto whichever came first. Ignite is
        exactly that — granted by an owned Shimmering Ruby Stiletto and also
        scribed — and in one 138MB log it was hand-cast 532 times and fired
        cast-less 407 more. All 407 were reported as casts.

        The old rule also required spell_file.is_proc(), which is False for
        Ignite and Burn: item-granted procs are not marked in the client
        spell file at all. So the static answer was "not a proc" while the
        log said otherwise 407 times. Log evidence beats static data — the
        comment always said so; now the code does.
        """
        low = (spell or "").lower()
        base = strip_tier(low)
        if low in self.exalt_effects or base in self.exalt_effects:
            return f"{spell} (exaltation)"
        if ((low in self.exalt_ambiguous or base in self.exalt_ambiguous)
                and self._cast_less(low, base, ts)):
            return f"{spell} (exaltation)"
        return spell

    def _cast_less(self, low: str, base: str, ts) -> bool:
        """Did this damage arrive without one of OUR casts behind it?

        12 seconds, measured rather than borrowed: across 18,721 cast/damage
        pairs in a real log the gap is 2.0s at the median, 6.0s at p99, and
        99.8% land inside 12s — with the curve flat from there to 30s, so a
        wider window buys nothing and only risks calling a proc a cast.

        NOT a general "is this a proc" test, and deliberately not used as
        one. Smite proves why: the Paladin ABILITY is a melee verb whose
        rider, Smiting Strike, lands 6,608 times and is never cast, while
        the Smite SPELL is cast 1,209 times. Cast-less says a cast did not
        cause it; it says nothing about what did. Source claims stay with
        the owned-stone evidence.
        """
        if ts is None:
            return False
        seen = [t for t in (self.spell_cast_at.get(low),
                            self.spell_cast_at.get(base)) if t is not None]
        if not seen:
            return True
        try:
            return (ts - max(seen)).total_seconds() > PROC_CAST_WINDOW_S
        except TypeError:
            return False

    def _encounter_heal(self, ts: datetime, label: str, amount: int,
                        crit: bool = False) -> None:
        enc = self.encounter
        if (enc is None or
                (ts - enc["last"]).total_seconds() > COMBAT_TIMEOUT_SECONDS):
            return
        hl = enc.setdefault("heals", {}).setdefault(
            label, {"hits": 0, "total": 0, "crits": 0})
        hl["hits"] += 1
        hl["total"] += amount
        if crit:
            hl["crits"] = hl.get("crits", 0) + 1

    def _encounter_ability(self, ts: datetime, name: str, kind: str, damage: int,
                           target: Optional[str] = None,
                           crit: bool = False,
                           mods: Optional[list] = None) -> None:
        self._touch_encounter(ts)
        enc = self.encounter
        ab = enc["abilities"].setdefault(
            name, {"kind": kind, "hits": 0, "total": 0, "crits": 0})
        ab["hits"] += 1
        ab["total"] += damage
        if crit:
            ab["crits"] = ab.get("crits", 0) + 1
        for m in mods or ():
            ab.setdefault("mods", {})[m] = ab.get("mods", {}).get(m, 0) + 1
            self.mods[m] = self.mods.get(m, 0) + 1
        # A stagger prints on the line AFTER the hit that caused it and names
        # no attacker, so crediting it means remembering what we just landed
        # -- and on WHOM, since other players' strikes stagger things too and
        # time alone would credit our last swing for their stun.
        self._last_ability = (ts, name, target)
        enc["total_out"] += damage
        sec = int(ts.timestamp())
        tl = enc.setdefault("secs", {})
        tl[sec] = tl.get(sec, 0) + damage
        if target:
            enc["target"] = target
            self._encounter_foe(target, dealt=damage)
            # /con almost always precedes the pull, so the level is usually
            # already known by the time the first hit names the target
            if enc.get("mob_level") is None:
                seen = self.considered.get(target.lower())
                if seen:
                    enc["mob_level"] = seen.get("level")
                    enc["mob_rare"] = bool(seen.get("rare"))

    def _is_self(self, who: Optional[str]) -> bool:
        """Does this name refer to the tracked character?

        EQL writes the PLAYER as the literal word "you" in lines addressed to
        them -- measured on a real log, all 161 heals landing on the player
        read "healed you" and NONE used the character name. A bare
        name-equality test therefore matched nothing, and healing_received
        silently counted zero of 17,954 hp of incoming heals.
        """
        w = (who or "").strip().lower()
        return bool(w) and (w in ("you", "yourself")
                            or w == (self.name or "").lower())

    def _hp_walk(self, delta: int) -> None:
        """Track the deepest HP reached inside a fight.

        A DEATH is the tail of a distribution we can measure all of: on one
        character 2.6% of fights ended in death while 5.3% cost over half of
        max HP, so waiting for a death discards every near-miss -- which are
        exactly the fights more mitigation would have changed.

        Reconstructed from the log's own damage and heal events rather than
        OCR: the stats panel only reads while the inventory window is open,
        which is not when you are being hit. Regen ticks are NOT logged, so
        this drifts pessimistic over a long fight; it is a floor, not a
        gauge, and it is None whenever max HP is unknown.
        """
        enc = self.encounter
        if enc is None or enc.get("hp") is None:
            return
        enc["hp"] = max(0, min(self.max_hp or enc["hp"], enc["hp"] + delta))
        if enc["hp_floor"] is None or enc["hp"] < enc["hp_floor"]:
            enc["hp_floor"] = enc["hp"]

    def _encounter_foe(self, name: str, dealt: int = 0, taken: int = 0,
                       slain: bool = False) -> None:
        """Aggregate per-mob totals for the multi-mob pull display."""
        name = _foe_key(name)
        foe = self.encounter.setdefault("foes", {}).setdefault(
            name, {"dealt": 0, "taken": 0, "slain": False})
        foe["dealt"] += dealt
        foe["taken"] += taken
        if slain:
            foe["slain"] = True

    # ---- event ingestion -------------------------------------------------
    def apply(self, e: ev.LogEvent, live: bool) -> None:
        if isinstance(e, ev.ZoneChange):
            self.zone = e.zone
            self.position = None  # old coords are meaningless in a new zone
            if live:
                self._fire_alerts("zone", e.zone, e.ts)
        elif isinstance(e, ev.LocUpdate) and live:
            self.position = {"x": e.x, "y": e.y, "z": e.z, "ts": e.ts.isoformat()}
        elif isinstance(e, ev.LevelUp):
            self.level = e.level
            # XP boxes + hunting XP are per-LEVEL: a ding resets them (kills,
            # loot, and damage stay session-wide)
            self.xp_ticks = 0
            self.xp_percent = 0.0
            for stats in self.mob_stats.values():
                stats["xp_percent"] = 0.0
        elif isinstance(e, ev.CharacterInfo):
            self.level = e.level
            if e.class_str:
                # /who reports the LIVE loadout (full trio) -- always trust it
                # over stale saved trios; loadout swaps write nothing else.
                self.class_str = e.class_str
                self.unknown_casts.clear()
                self.loadout_hint = None
            if e.race:
                # Take EVERY race /who reports, not just the first. This was
                # write-once, guarding against raid /who rows -- which print
                # the group number where a zone /who prints the race, so the
                # parser sets race None there and an overwrite would blank
                # it. Testing for a value covers that without latching.
                #
                # Race genuinely changes: a character need not survive a
                # launch, and the name gets reused. The reporting player
                # was an Iksar in beta and is an Ogre now, and the beta
                # value -- restored from the character row at startup --
                # outranked fourteen /who lines that said otherwise. The
                # advisor gates gear and race-influenced class advice on
                # this, so it was wrong in a way that reached real output.
                self.race = e.race
        elif isinstance(e, ev.OtherCharInfo):
            self.who_roster[e.name] = {"level": e.level, "classes": e.classes}
        elif isinstance(e, ev.PetInvHeader):
            # start of a "/pet inventory check" burst — begin a fresh capture
            self._pet_inv_ts = e.ts
            self.pet_inventory = {}
        elif isinstance(e, ev.PetGearLine):
            # slot lines only count within ~10s of the header
            if (self._pet_inv_ts is not None
                    and (e.ts - self._pet_inv_ts).total_seconds() <= 10):
                self.pet_inventory[e.slot] = e.item
        elif isinstance(e, ev.PetLeader):
            if e.owner.lower() == (self.name or "").lower():
                self.pet_hint = False
            if self.pet_owners.get(e.pet) != e.owner:
                self.pet_owners[e.pet] = e.owner
                if (e.owner or "").lower() == (self.name or "").lower():
                    self._adopt_pet_damage(e.pet)   # /pet leader path
                self.pet_owners_dirty = True
        elif isinstance(e, ev.PetAttack):
            # the pet tells ONLY its master — zero-config mapping, no
            # /pet leader needed
            self.pet_hint = False
            if self.pet_owners.get(e.pet) != self.name:
                self.pet_owners[e.pet] = self.name
                self.pet_owners_dirty = True
                self._adopt_pet_damage(e.pet)
        elif isinstance(e, ev.CastBegin):
            if e.spell:  # log evidence for proc-vs-cast disambiguation
                self.spell_casts.add(e.spell.lower())
                self.spell_casts.add(strip_tier(e.spell).lower())
                self.spell_cast_at[e.spell.lower()] = e.ts
                self.spell_cast_at[strip_tier(e.spell).lower()] = e.ts
                self._infer_class(e.spell, e.ts)
                if live:
                    base = strip_tier(e.spell).lower()
                    if base in ABILITY_COOLDOWNS:
                        # cooldown abilities get ONE timer (the pack also
                        # lists some as "durations" — the cooldown wins)
                        self._start_cooldown(e.spell, e.ts)
                    else:
                        secs = SPELL_TIMERS.get(base)
                        if secs:
                            secs = _tier_scaled(base, secs, e.spell)
                            self._start_timer(e.spell, secs, "spell", e.ts)
                        elif base not in self._timer_misses:
                            # A miss is SILENT otherwise — no timer simply
                            # never appears, which is indistinguishable from
                            # a spell that has no duration. SPELL_TIMERS is a
                            # raid trigger pack and its low-level coverage is
                            # thin, so this is the only way to find out which
                            # of YOUR spells it does not know. Once per name
                            # per session: casts repeat constantly.
                            self._timer_misses.add(base)
                            logger.debug("no SPELL_TIMERS entry for %r "
                                         "(cast, no timer started)", base)
        elif isinstance(e, ev.GroupMember):
            if e.name is None:
                self.group_members.clear()   # removed/disbanded
            elif e.joined:
                self.group_members.add(e.name)
                # A join line is proof, and proof outranks a dismissal made
                # before it: whoever was ignored has now demonstrably
                # joined, so the ignore has nothing left to describe.
                self.ignored_contributors.pop(e.name, None)
            else:
                self.group_members.discard(e.name)
        elif isinstance(e, ev.GroupChat):
            # Seeds the roster where join lines cannot: log in ALREADY
            # grouped and no one ever "joined", so a join-only filter would
            # hide your real group. Speaking in group chat proves membership.
            if e.sender:
                self._chat_seen.add(e.sender)
            if e.channel == "group" and e.sender:
                self.group_members.add(e.sender)
                self.ignored_contributors.pop(e.sender, None)
        elif isinstance(e, ev.Composition):
            # the log's own trio line — authoritative like /who
            from backend.log_system.parser import CLASS_ABBREV as _CA
            names = [p.strip() for p in
                     re.split(r"[,/&]| and ", e.class_str) if p.strip()]
            full = [next((v for v in _CA.values()
                          if v.lower() == n.lower()), None) for n in names]
            if len(full) == 3 and all(full):
                self.class_str = "/".join(full)
                self.unknown_casts.clear()
                self.loadout_hint = None
        elif isinstance(e, ev.AAListEntry):
            # ownership data, not session data: applies in seed replay too.
            # Skip listings OLDER than what we already hold (e.g. the seed
            # replays a burst that predates the DB-restored roster).
            if self._last_aa_seen is not None and e.ts < self._last_aa_seen:
                return_early = True
            else:
                return_early = False
            if not return_early:
                if (self._aa_from_db or self._last_aa_seen is None or
                        (e.ts - self._last_aa_seen).total_seconds() > 5):
                    # fresh listing (or a replay of the persisted one)
                    self.owned_aas.clear()
                    self._aa_from_db = False
                entry = self.owned_aas.setdefault(
                    e.name, {"id": e.aa_id, "ranks": 0, "cost": None, "desc": None})
                entry["ranks"] += 1
                self._last_aa_seen = e.ts
                self._last_aa_name = e.name
        elif isinstance(e, ev.AAListMeta):
            if (self._last_aa_name and self._last_aa_seen is not None and
                    0 <= (e.ts - self._last_aa_seen).total_seconds() <= 5):
                entry = self.owned_aas.get(self._last_aa_name)
                if entry:
                    if e.cost is not None:
                        entry["cost"] = e.cost
                    if e.desc and not entry["desc"]:
                        entry["desc"] = e.desc[:150]

        if live:
            self.last_event_at = e.ts
            if self.session_started is None:
                self.session_started = e.ts
            self._active_buckets.add(int(e.ts.timestamp()) // 120)
            if isinstance(e, ev.LevelUp):
                self._dinged = True
            self._sweep_pending(e.ts)
            if isinstance(e, ev.DotDamage) and e.proc and (
                    e.target.lower() == "you"
                    or e.target in self.who_roster
                    or (self.pet_owners.get(e.target) or "").lower()
                    == (self.name or "").lower()):
                # casterless proc tick aimed at us / a player / our own
                # pet — not our outgoing damage
                if e.target.lower() == "you":
                    self.damage_taken += e.damage
            elif isinstance(e, (ev.MeleeOut, ev.SpellDamageOut, ev.DotDamage)):
                self.damage_dealt += e.damage
                self.last_target = e.target
                self._dmg_window.append((e.ts, e.damage))
                if e.crit:
                    self.crits += 1
                if isinstance(e, ev.MeleeOut):
                    self.swings_hit += 1
                    shave = COOLDOWN_SHAVES.get(e.verb)
                    if shave:
                        # a landed Smite/Reave shaves its big cooldown
                        for t in self.active_timers:
                            if (t["kind"] == "cooldown" and
                                    t["name"].lower().startswith(
                                        shave[0].lower())):
                                t["ends"] -= timedelta(seconds=shave[1])
                    self._encounter_ability(e.ts, e.verb.capitalize(), "melee",
                                            e.damage, e.target, crit=e.crit,
                                            mods=e.mods)
                elif isinstance(e, ev.SpellDamageOut):
                    self._encounter_ability(e.ts, self._fx_label(e.spell, e.ts),
                                            "spell", e.damage, e.target,
                                            crit=e.crit, mods=e.mods)
                else:  # DotDamage
                    self._encounter_ability(e.ts, self._fx_label(e.spell, e.ts),
                                            "dot", e.damage, e.target,
                                            crit=e.crit)
                    # first tick names the victim — bind the running timer
                    self._bind_timer_target(e.spell, e.target, e.ts)
                # own lifetaps log NO heal line — synthesize the self-heal
                # 1:1 from the damage (the client spell file flags taps)
                spell = getattr(e, "spell", None)
                if spell and spell_file.is_lifetap(spell):
                    self.healing_received += e.damage
                    self._encounter_heal(e.ts, f"{spell} (lifetap) — You",
                                         e.damage)
            elif isinstance(e, ev.DamageShieldOut):
                # aux damage: counts to totals/DPS, never swings or crits
                self.damage_dealt += e.damage
                self._dmg_window.append((e.ts, e.damage))
                self._encounter_ability(e.ts, f"Damage Shield ({e.kind})",
                                        "ds", e.damage, e.target)
            elif isinstance(e, ev.MissOut):
                self.swings_missed += 1
            elif isinstance(e, ev.OtherDamageOut):
                owner = self.pet_owners.get(e.attacker)
                if (e.attacker.lower() == f"{self.name} pet".lower()
                        or (owner and owner.lower() == self.name.lower())):
                    # OUR pet (by "<name> pet" convention, or a named summon
                    # mapped via a "My leader is" line): player-side damage.
                    self.damage_dealt += e.damage
                    self._dmg_window.append((e.ts, e.damage))
                    self._encounter_ability(e.ts, f"Pet: {e.source}", "pet",
                                            e.damage, e.target)
                    # also credit the pet as a distinct group-DPS contributor
                    enc2 = self.encounter
                    if enc2 is not None and (e.ts - enc2["last"]).total_seconds() <= COMBAT_TIMEOUT_SECONDS:
                        op = enc2.setdefault("own_pet", {})
                        op[e.attacker] = op.get(e.attacker, 0) + e.damage
                else:
                    # Group DPS: credit other players/pets only while an
                    # encounter is live AND they hit one of OUR foes. Never
                    # extends the window (bystanders would keep it alive).
                    enc = self.encounter
                    if (enc is not None
                            and (e.ts - enc["last"]).total_seconds() <= COMBAT_TIMEOUT_SECONDS
                            and _foe_key(e.target) in enc.get("foes", {})):
                        # The target test above CANNOT be trusted alone:
                        # _foe_key compares mob NAMES and the log has no mob
                        # IDs, so a stranger fighting a DIFFERENT mob of the
                        # same name passes it (observed live -- two "Spirit
                        # of Dessication" at once, the other one someone
                        # else's). Group membership is the only side of that
                        # comparison we can positively verify.
                        #
                        # EQL does not allow shared damage: once a mob is
                        # tagged, only the tagger and their group can hurt
                        # it. So a non-groupmate landing hits is not helping
                        # on our mob -- they are DEFINITIONALLY on a
                        # different one that happens to share a name. There
                        # is no case where crediting a stranger is correct.
                        #
                        # This gate therefore fails CLOSED. It used to fail
                        # open on an empty roster, which read as "no
                        # evidence, so credit everyone" -- but the game rule
                        # IS the evidence, and a solo player has no allies
                        # by definition. Randoms kept appearing in the
                        # overlay for exactly that reason.
                        #
                        # The cost is a real groupmate landing in the bucket
                        # when we never saw them join (logging in already
                        # grouped, before anyone speaks). That is why the
                        # damage is LUMPED and shown rather than dropped: a
                        # wrongly-excluded contributor stays visible, and
                        # one line of group chat fixes it.
                        who = owner or e.attacker
                        # An NPC attacker we cannot tie to us is ambient
                        # combat -- mobs fighting each other, or someone
                        # else's charmed pet. Parsing those is what makes a
                        # CHARMED pet of ours visible at all, but they must
                        # not land in the filtered bucket: that number means
                        # "contributors we hid from you", and burying it
                        # under thousands of mob-vs-mob swings would make it
                        # meaningless. Dropped outright, not counted.
                        if (who not in self.group_members
                                and _NPC_NAME.match(who or "")):
                            # Ambient combat -- mobs fighting each other, or
                            # someone else's charmed pet -- EXCEPT that our
                            # OWN charmed pet looks exactly like this until
                            # /pet leader identifies it, and it fights first
                            # and identifies second. Held aside so mapping
                            # can claim it, the same way _adopt_pet_damage
                            # claims a summoned pet's opening swings out of
                            # the ally bucket. Never displayed and never
                            # summed: if no mapping arrives it was ambient
                            # after all, and the encounter takes it away.
                            pend = enc.setdefault("npc_pending", {})
                            if who in pend or len(pend) < 40:
                                pend[who] = pend.get(who, 0) + e.damage
                            return
                        if who not in self.group_members:
                            ua = enc.setdefault("unattributed", {})
                            first = e.attacker not in ua
                            ua[e.attacker] = ua.get(e.attacker, 0) + e.damage
                            seen = self.filtered_seen.setdefault(
                                e.attacker, {"damage": 0, "fights": 0})
                            seen["damage"] += e.damage
                            seen["last"] = e.ts
                            if first:
                                seen["fights"] += 1
                        elif owner:
                            # An ally's pet gets its OWN row, mirroring the
                            # way our pet is split out of "You". Folded in,
                            # our view of that player would be them PLUS
                            # their pet while their own companion shows the
                            # two apart — the numbers could never be
                            # compared, which is the main reason a group
                            # runs this side by side.
                            pets = enc.setdefault("ally_pets", {})
                            pets[owner] = pets.get(owner, 0) + e.damage
                        else:
                            allies = enc.setdefault("allies", {})
                            allies[e.attacker] = (
                                allies.get(e.attacker, 0) + e.damage)
                        if who in self.group_members or owner:
                            # A CONFIRMED groupmate (or our own pet) keeps
                            # the fight open past our own last swing. A
                            # group fight does not end because we went OOM,
                            # stepped away to heal or died -- but until the
                            # roster could be trusted, honouring that meant
                            # letting any passer-by hold the clock, so it
                            # was refused outright and long fights split
                            # into fragments whenever we stopped acting.
                            #
                            # Bounded by OUR last action, never by theirs,
                            # so a fight cannot walk itself forward on
                            # other people's damage indefinitely.
                            own = enc.get("last_own") or enc["last"]
                            if (e.ts - own).total_seconds() <= GROUP_EXTEND_SECONDS:
                                enc["last"] = max(enc["last"], e.ts)
            elif isinstance(e, (ev.MeleeIn, ev.SpellDamageIn)):
                self.damage_taken += e.damage
                thr = alerts.bighit_threshold()
                if thr and e.damage >= thr:
                    src = getattr(e, "spell", None) or getattr(e, "verb", "hit")
                    self._push_alert(
                        "bighit", f"-{e.damage} from {e.attacker} ({src})",
                        e.ts)
                # a "pet" that hits US is charmed no longer — drop the claim
                if ((self.pet_owners.get(e.attacker) or "").lower()
                        == (self.name or "").lower()):
                    self.pet_owners.pop(e.attacker, None)
                    self.pet_owners_dirty = True
                self._touch_encounter(e.ts)
                self.encounter["total_in"] += e.damage
                self.encounter["in_hits"] = self.encounter.get("in_hits", 0) + 1
                self._encounter_foe(e.attacker, taken=e.damage)
                self._hp_walk(-e.damage)
            elif isinstance(e, ev.MissIn):
                # tanking view: which defense ate each incoming swing
                enc = self.encounter
                if (enc is not None and
                        (e.ts - enc["last"]).total_seconds() <= COMBAT_TIMEOUT_SECONDS):
                    d = enc.setdefault("defense", {})
                    d[e.defense] = d.get(e.defense, 0) + 1
            elif isinstance(e, ev.HealReceived):
                self.healing_received += e.amount
            elif isinstance(e, ev.HealOut):
                self.healing_done += e.amount
                if e.potential and e.potential > e.amount:
                    self.overheal += e.potential - e.amount
                if e.crit:
                    self.crits += 1
                # unattributed heals still count; they just group under a
                # generic row rather than a spell name
                self._encounter_heal(e.ts, f"{e.spell or 'Direct heal'} — You",
                                     e.amount, crit=e.crit)
            elif isinstance(e, ev.OtherHeal):
                if self._is_self(e.target):
                    self.healing_received += e.amount
                    self._hp_walk(e.amount)
                healer = self.pet_owners.get(e.healer, e.healer)
                self._encounter_heal(e.ts,
                                     f"{e.spell or 'Direct heal'} — {healer}",
                                     e.amount, crit=e.crit)
            elif isinstance(e, ev.OtherCast):
                enc = self.encounter
                if (enc is not None and (e.ts - enc["last"]).total_seconds()
                        <= COMBAT_TIMEOUT_SECONDS):
                    casts = enc.setdefault("other_casts", {})
                    key = f"{e.spell} — {e.caster}"
                    casts[key] = casts.get(key, 0) + 1
                # Fired OUTSIDE the encounter window on purpose: a mob casting
                # is the only warning before it lands, and the one you most
                # want warned about is the one that has not hit you yet.
                self._fire_alerts("cast", f"{e.caster}: {e.spell}", e.ts)
            elif isinstance(e, ev.Kill):
                self.kills += 1
                self._fire_alerts("kill", e.target, e.ts)
                mob = _foe_key(e.target)
                self._mob(mob)["kills"] += 1
                self._last_kill = (mob, e.ts)
                self._absorb_pending_rewards(mob, e.ts)
                self._cancel_timers_for_target(e.target)
                if self.pet_owners.pop(e.target, None):  # charm pet died
                    self.pet_owners_dirty = True
                if self.encounter and (e.ts - self.encounter["last"]).total_seconds() <= COMBAT_TIMEOUT_SECONDS:
                    self.encounter["last"] = e.ts
                    self._encounter_foe(e.target, slain=True)
            elif isinstance(e, ev.OtherDeath):
                # pet/ally killing blows: "A shin ghoul knight has been slain
                # by Gonekab!" — OUR pet's kill counts as ours; any group kill
                # that pays us XP shows up in Session hunting
                killer = self.pet_owners.get(e.killer, e.killer)
                mob = _foe_key(e.victim)
                if killer.lower() == (self.name or "").lower():
                    self.kills += 1
                    self._mob(mob)["kills"] += 1
                self._last_kill = (mob, e.ts)
                self._absorb_pending_rewards(mob, e.ts)
                # someone else's killing blow ends OUR DoT just the same
                self._cancel_timers_for_target(e.victim)
                if self.pet_owners.pop(e.victim, None):  # mapped pet slain
                    self.pet_owners_dirty = True
                if (self.encounter and
                        (e.ts - self.encounter["last"]).total_seconds() <= COMBAT_TIMEOUT_SECONDS
                        and mob in self.encounter.get("foes", {})):
                    self._encounter_foe(e.victim, slain=True)
            elif isinstance(e, ev.MechanicTimer):
                self._start_timer(e.name, e.seconds, "raid", e.ts)
                self._fire_alerts("mechanic", e.name, e.ts)
            elif isinstance(e, ev.AbilityActivate):
                self._start_cooldown(e.name, e.ts)
            elif isinstance(e, ev.Mend):
                # Mend announces its RESULT, never its activation -- no cast
                # line, and unlike Lay on Hands no "you can use the ability
                # again" readout ever prints, so nothing will correct this
                # timer later. The heal message is the only evidence it
                # fired, and the duration has to stand on its own.
                self._start_cooldown("Mend", e.ts)
            elif isinstance(e, ev.CooldownReadout):
                # the game's own remaining-time oracle — snap to it
                self._start_timer(f"{strip_tier(e.name)} ready", e.seconds,
                                  "cooldown", e.ts)
            elif isinstance(e, ev.Summoned):
                self._push_alert("summon", "You have been summoned!", e.ts)
            elif isinstance(e, ev.Stunned):
                self.stuns_taken += 1
            elif isinstance(e, ev.Staggered):
                # credit the ability that just landed, within 2s -- the same
                # window the log's own ordering implies
                lts, lname, ltarget = self._last_ability
                same = (ltarget or "").lower() == (e.target or "").lower()
                if lts and lname and same and (e.ts - lts).total_seconds() <= 2:
                    ab = (self.encounter or {}).get("abilities", {}).get(lname)
                    if ab is not None:
                        ab["stuns"] = ab.get("stuns", 0) + 1
                        self.stuns_landed += 1
            elif isinstance(e, ev.Mesmerized):
                self.mez_applied += 1
                self._fire_alerts("mez", e.target, e.ts)
            elif isinstance(e, ev.Tell):
                self._fire_alerts("tell", f"{e.sender}: {e.text}", e.ts)
            elif isinstance(e, ev.GroupChat):
                if self.name and self.name.lower() in e.text.lower():
                    self._push_alert(
                        "mention", f"[{e.channel}] {e.sender}: {e.text}", e.ts)
            elif isinstance(e, ev.BuffFade):
                if not e.pet:
                    self._cancel_timer(e.spell)
                    label = e.spell + (f" ({e.target})" if e.target else "")
                    self._fire_alerts("fade", label, e.ts)
            elif isinstance(e, ev.CastFizzle):
                self._cancel_timer(e.spell)
                self._fire_alerts("fizzle", e.spell or "your spell", e.ts)
            elif isinstance(e, ev.CastInterrupted):
                self._cancel_timer(e.spell)
                # The bard/melody form names no spell, so a "*" rule is the
                # only way to catch every interrupt -- give it something to
                # match rather than an empty string, which "*" would still
                # match but a named pattern never could explain missing.
                self._fire_alerts("interrupt", e.spell or "your casting", e.ts)
            elif isinstance(e, ev.SessionStart):
                summ = self.session_summary()
                if (summ["kills"] or summ["xp_percent"] or summ["loot_count"]
                        or summ["damage_dealt"] or summ["deaths"]):
                    self.pending_sessions.append(summ)
                    del self.pending_sessions[:-5]
                self._reset_session(e.ts)
            elif isinstance(e, ev.Rune):
                self.rune_absorbed += e.amount
            elif isinstance(e, ev.SelfHurt):
                # cannibalize / DS self-ticks: damage taken, NEVER dealt,
                # and never opens an encounter
                self.damage_taken += e.damage
            elif isinstance(e, ev.MyDeath):
                self._fire_alerts("death", "slain by " + e.killer, e.ts)
                self.deaths += 1
                self.last_death = self._death_recap(e)
            elif isinstance(e, ev.ExpGain):
                self.xp_ticks += 1
                if e.percent:
                    self.xp_percent += e.percent
                    # EQL always prints the XP line BEFORE its kill line —
                    # hold it for the kill landing next. (Attributing
                    # backward to the previous kill mis-credits every XP
                    # tick during chain pulls, where the prior kill is
                    # seconds old.)
                    self._pending_xp = (e.ts, e.percent)
            elif isinstance(e, ev.AAPoint):
                self.aa_points += e.count
                if e.total is not None:
                    self.aa_available = e.total  # the log's own running total
                elif self.aa_available is not None:
                    self.aa_available += e.count
            elif isinstance(e, ev.AASpend):
                # Spend lines carry no running total. Keep an unknown starting
                # value unknown, and do not let a missed gain drive a known
                # value below zero. Cost-zero messages are toggle state, not
                # a purchase.
                if e.cost and self.aa_available is not None:
                    self.aa_available = max(0, self.aa_available - e.cost)
            elif isinstance(e, ev.Consider):
                # remembered across fights: a mob considered once stays
                # classified, and /con usually happens BEFORE the pull
                self.considered[e.name.lower()] = {
                    "level": e.level, "rare": e.rare, "ts": e.ts}
                enc = self.encounter
                if enc is not None and enc.get("mob_level") is None:
                    tgt = (enc.get("target") or "").lower()
                    if tgt and tgt == e.name.lower():
                        enc["mob_level"] = e.level
                        enc["mob_rare"] = e.rare
            elif isinstance(e, ev.OutOfMana):
                self.oom_count += 1
                enc = self.encounter
                if (enc is not None and (e.ts - enc["last"]).total_seconds()
                        <= COMBAT_TIMEOUT_SECONDS):
                    enc["oom"] = enc.get("oom", 0) + 1
            elif isinstance(e, ev.SkillUp):
                self.skill_ups += 1
            elif isinstance(e, ev.Loot):
                label = f"{e.item} → {e.upgraded_to}" if e.upgraded_to else e.item
                if e.count > 1:
                    label = f"{e.count}× {label}"
                if e.sold:
                    label += " (sold)"
                elif e.stored:
                    label += " (banked)"
                self.loots.appendleft(label)
                self.loot_count += max(e.count, 1)
                self._fire_alerts("loot", e.item, e.ts)
                self._note_unlock_loot(e.item, max(e.count, 1), e.ts)
                # loot lines name the corpse: exact per-mob attribution
                # Upgrade currency. The 2026-07-28 launch patch added
                # "Void-touched Potential", a raid token that merges exactly
                # like a mote (+1 rank to an item OR a spell) but does NOT
                # carry the "Mote of <tier>" naming, so the old pattern
                # missed it entirely. Counted under its own tier name.
                mote = RE_MOTE.match(e.item) or RE_VOID_TOKEN.match(e.item)
                if mote:
                    tier = (mote.group(1) if mote.re is RE_MOTE
                            else "Void-touched")
                    self.motes[tier] = self.motes.get(tier, 0) + max(e.count, 1)
                if e.source and "'s corpse" in e.source:
                    mob = _foe_key(e.source.split("'s corpse")[0].strip())
                    stats = self._mob(mob)
                    stats["loot_drops"] += max(e.count, 1)
                    if e.item not in stats["loots"] and len(stats["loots"]) < 8:
                        stats["loots"].append(e.item)
            elif isinstance(e, ev.Coin):
                copper = _coin_copper(e.amount)
                self.coin_copper += copper
                if copper and not e.vendor and not e.from_item:
                    # corpse coin prints just BEFORE its kill line — hold
                    # it for forward attribution exactly like XP
                    self._pending_coin = (e.ts, copper)
            elif isinstance(e, ev.Resist) and e.direction == "out":
                self._cancel_timer(e.spell)
                enc = self.encounter
                if (enc is not None and
                        (e.ts - enc["last"]).total_seconds() <= COMBAT_TIMEOUT_SECONDS):
                    rs = enc.setdefault("resists", {})
                    rkey = e.spell or "spell"
                    rs[rkey] = rs.get(rkey, 0) + 1

        self._dirty = True
        if e.type not in ("other_out", "aa_list", "aa_meta", "who_other",
                          "pet_inv_header", "pet_gear", "pet_attack",
                          "group_chat"):
            # other_out is too spammy; aa listing bursts are metadata
            self.ledger.append({**e.model_dump(mode="json"), "live": live})

    # ---- derived ----------------------------------------------------------
    def dps(self) -> float:
        cutoff = datetime.now() - timedelta(seconds=DPS_WINDOW_SECONDS)
        while self._dmg_window and self._dmg_window[0][0] < cutoff:
            self._dmg_window.popleft()
        if not self._dmg_window:
            return 0.0
        total = sum(d for _, d in self._dmg_window)
        span = (self._dmg_window[-1][0] - self._dmg_window[0][0]).total_seconds()
        value = total / max(span, 1.0)
        self.session_max_dps = max(self.session_max_dps, value)
        return round(value, 1)

    def _start_timer(self, name: str, seconds: int, kind: str,
                     ts: datetime) -> None:
        self.active_timers = [t for t in self.active_timers
                              if t["name"] != name][-9:]
        # `target` is set ONLY by a tick that names the victim
        # (_bind_timer_target) — never guessed. Guessing from `last_target`
        # at cast time was tried and reverted: that value survives its
        # mob's death, opening a pull with a root/snare is exactly when it
        # is stalest, and a spell that never ticks has no way to correct a
        # wrong guess — so a same-named kill later could reap a live timer
        # for good. A never-ticking spell keeps None and runs out instead.
        self.active_timers.append({
            "name": name, "kind": kind, "seconds": seconds, "target": None,
            "ends": ts + timedelta(seconds=seconds)})

    def _bind_timer_target(self, spell: Optional[str], target: str,
                           ts: datetime) -> None:
        """Adopt the victim a DoT actually landed on — or undo a bad reap.

        "You begin casting X." names NOTHING, so a DoT timer starts
        targetless and the tick line ("a dread bone has taken 8 damage from
        your Clinging Darkness.") is the first hard evidence of what it is
        on. A tick also PROVES the spell is still running, so it resurrects
        a timer a kill reaped by mistake — which is the only defence
        against two mobs sharing a name, since the log carries no mob IDs
        and `_foe_key` necessarily folds them together.
        """
        if not spell:
            return
        low = strip_tier(spell).lower()
        foe = _foe_key(target)
        for t in self.active_timers:
            if (t["kind"] == "spell"
                    and strip_tier(t["name"]).lower() == low):
                t["target"] = foe
                return
        # nothing live under that name — was it reaped a moment ago?
        self._reaped = [r for r in self._reaped if r["ends"] > ts]
        for r in self._reaped:
            if strip_tier(r["name"]).lower() == low:
                self._reaped.remove(r)
                r["target"] = foe
                self.active_timers = [t for t in self.active_timers
                                      if t["name"] != r["name"]][-9:]
                self.active_timers.append(r)
                logger.debug("timer %r resurrected by a tick on %r "
                             "(reaped by a same-named kill)", r["name"], foe)
                return

    def _cancel_timers_for_target(self, name: str) -> None:
        """The mob died, so everything we put ON it is gone.

        Removes ONLY timers a tick confirmed on this foe. A hostile spell
        that never ticked still has target=None and deliberately runs its
        full duration — same as before this feature existed. Buffs and
        ability cooldowns never bind and are never touched. Reaped rows
        are kept until their original expiry so a tick can undo the
        removal — losing a timer that is still running is the worse
        error, and a same-named kill makes that genuinely ambiguous.
        """
        foe = _foe_key(name)
        keep, reap = [], []
        for t in self.active_timers:
            (reap if t.get("target") == foe else keep).append(t)
        self.active_timers = keep
        self._reaped = ([r for r in self._reaped if r not in reap] + reap)[-10:]

    def _cancel_timer(self, spell: Optional[str]) -> None:
        """Fizzle/interrupt/resist: the effect never landed."""
        if not spell:
            return
        low = strip_tier(spell).lower()
        self.active_timers = [
            t for t in self.active_timers
            if strip_tier(t["name"]).lower() != low]

    def timers_view(self) -> list:
        now = datetime.now()
        self.active_timers = [t for t in self.active_timers
                              if t["ends"] > now]
        return sorted(
            ({"name": t["name"], "kind": t["kind"],
              "seconds": t["seconds"], "target": t.get("target"),
              "remaining": round((t["ends"] - now).total_seconds())}
             for t in self.active_timers),
            key=lambda t: t["remaining"])

    def _push_alert(self, kind: str, text: str, ts: datetime,
                    sound: bool = True) -> None:
        key = "builtin:" + kind
        last = self._alert_cooldown.get(key)
        if last and (ts - last).total_seconds() < 5:
            return
        self._alert_cooldown[key] = ts
        self._alert_seq += 1
        self.alerts.append({"id": self._alert_seq, "ts": ts.isoformat(),
                            "kind": kind, "text": text, "sound": sound})

    def _fire_alerts(self, kind: str, text: str, ts: datetime) -> None:
        for rule in alerts.match(kind, text):
            key = rule["kind"] + ":" + rule["pattern"]
            last = self._alert_cooldown.get(key)
            if last and (ts - last).total_seconds() < 5:
                continue
            self._alert_cooldown[key] = ts
            self._alert_seq += 1
            self.alerts.append({
                "id": self._alert_seq, "ts": ts.isoformat(),
                "kind": rule["kind"], "text": text,
                "sound": bool(rule.get("sound", True))})

    def _start_cooldown(self, name: str, ts: datetime) -> None:
        base = strip_tier(name)  # canonical: cast tiers and the game
        secs = ABILITY_COOLDOWNS.get(base.lower())  # oracle share a name
        if secs:
            self._start_timer(f"{base} ready", secs, "cooldown", ts)

    def session_summary(self) -> dict:
        """Snapshot of the CURRENT session's headline numbers — archived
        on rollover, also served live by /api/sessions."""
        r = self.rates() or {}
        return {
            "started": (self.session_started.isoformat()
                        if self.session_started else None),
            "ended": (self.last_event_at.isoformat()
                      if self.last_event_at else None),
            "elapsed_hours": r.get("elapsed_hours"),
            "active_hours": r.get("active_hours"),
            "kills": self.kills, "deaths": self.deaths,
            "xp_percent": round(self.xp_percent, 2),
            "coin_copper": self.coin_copper,
            "crits": self.crits,
            "loot_count": self.loot_count,
            "damage_dealt": self.damage_dealt,
            "damage_taken": self.damage_taken,
            "healing_done": self.healing_done,
            "max_dps": round(self.session_max_dps, 1),
            "level": self.level,
            "class_str": self.class_str,
            "zone": self.zone,
        }

    def _reset_session(self, ts: datetime) -> None:
        """Login banner: zero the per-session state. Knowledge (roster,
        pet owners, owned AAs, cast evidence) survives."""
        self.damage_dealt = self.damage_taken = 0
        self.healing_received = self.healing_done = 0
        self.kills = self.deaths = 0
        self.xp_ticks = 0
        self.xp_percent = 0.0
        self.aa_points = self.skill_ups = 0
        self.swings_hit = self.swings_missed = 0
        self.crits = self.coin_copper = self.rune_absorbed = 0
        self.loot_count = 0
        self.stuns_taken = self.overheal = 0
        self.stuns_landed = self.mez_applied = 0
        # NOT durable knowledge, unlike cast evidence: classes are swapped
        # freely in EQL, so accumulating these across a log names every
        # class ever played (nine, on the reporting character) instead of
        # the three slotted now. A cast only proves a class is slotted at
        # the time of the cast.
        self.inferred_classes = {}
        self._infer_at = {}
        self._infer_seen = set()
        self.mods = {}
        self.motes = {}
        self.loots.clear()
        self.mob_stats = {}
        self._last_kill = None
        self._pending_xp = self._pending_coin = None
        self.encounter = None
        self.encounter_history.clear()
        self._dmg_window.clear()
        self.session_max_dps = 0.0
        self.session_started = ts
        self._active_buckets = set()
        self._dinged = False

    def rates(self) -> Optional[dict]:
        """Per-hour session rates, per ELAPSED and per ACTIVE hour.
        hours_to_level is EXACT when a ding happened this session (the
        XP box counts from 0 after it), else an upper bound (we cannot
        see the level progress that predates the session)."""
        if not self.session_started or not self.last_event_at:
            return None
        elapsed_h = max((self.last_event_at - self.session_started)
                        .total_seconds() / 3600.0, 1 / 60.0)
        active_h = min(len(self._active_buckets) * 120 / 3600.0, elapsed_h)
        active_h = max(active_h, 1 / 60.0)

        def pair(v, nd=1):
            return {"hr": round(v / elapsed_h, nd),
                    "active_hr": round(v / active_h, nd)}

        out = {
            "elapsed_hours": round(elapsed_h, 2),
            "active_hours": round(active_h, 2),
            "xp": pair(self.xp_percent, 2),
            "coin": pair(self.coin_copper, 0),
            "kills": pair(self.kills),
        }
        xp_active = out["xp"]["active_hr"]
        if xp_active > 0:
            remain = max(0.0, 100.0 - self.xp_percent)
            out["hours_to_level"] = round(remain / xp_active, 1)
            out["hours_to_level_exact"] = self._dinged
        return out

    def in_combat(self) -> bool:
        if not self._dmg_window:
            return False
        return (datetime.now() - self._dmg_window[-1][0]).total_seconds() < COMBAT_TIMEOUT_SECONDS

    def _encounter_view(self, enc: dict, live: bool) -> dict:
        duration = max((enc["last"] - enc["started"]).total_seconds(), 1.0)
        # best 3-second burst window (keys re-int'd: JSON restores strings)
        secs = {int(k): v for k, v in (enc.get("secs") or {}).items()}
        peak = 0
        for k in secs:
            peak = max(peak, secs.get(k, 0) + secs.get(k + 1, 0)
                       + secs.get(k + 2, 0))
        # 2s-bucket damage timeline for the sparkline (capped at 4 min)
        timeline: list = []
        if secs:
            start_s = int(enc["started"].timestamp())
            buckets: dict = {}
            for k, v in secs.items():
                b = (k - start_s) // 2
                if 0 <= b < 120:
                    buckets[b] = buckets.get(b, 0) + v
            if buckets:
                timeline = [buckets.get(i, 0)
                            for i in range(max(buckets) + 1)]
        abilities = [
            {
                "name": name,
                "kind": ab["kind"],
                "hits": ab["hits"],
                "crits": ab.get("crits", 0),
                "stuns": ab.get("stuns", 0),
                "mods": ab.get("mods") or {},
                "total": ab["total"],
                "avg": round(ab["total"] / ab["hits"], 1),
                "dps": round(ab["total"] / duration, 1),
            }
            for name, ab in enc["abilities"].items()
        ]
        abilities.sort(key=lambda a: (a["avg"], a["total"]), reverse=True)
        foes = [
            {"name": name, "damage": f["dealt"], "taken": f["taken"],
             "slain": f["slain"]}
            for name, f in enc.get("foes", {}).items()
        ]
        foes.sort(key=lambda f: (f["slain"], -f["damage"]))
        heals = [
            {"name": name, "kind": "heal", "hits": hl["hits"],
             "crits": hl.get("crits", 0), "total": hl["total"],
             "avg": round(hl["total"] / hl["hits"], 1),
             "dps": round(hl["total"] / duration, 1)}
            for name, hl in enc.get("heals", {}).items()
        ]
        heals.sort(key=lambda a: a["total"], reverse=True)
        allies = []
        for name, dmg in enc.get("allies", {}).items():
            who = self.who_roster.get(name, {})
            allies.append({"name": name, "damage": dmg,
                           "dps": round(dmg / duration, 1),
                           "level": who.get("level"),
                           "classes": who.get("classes")})
        for owner, dmg in (enc.get("ally_pets") or {}).items():
            allies.append({"name": f"{owner} (pet)", "damage": dmg,
                           "dps": round(dmg / duration, 1),
                           "level": None, "classes": None, "is_pet": True})
        own_pet = enc.get("own_pet", {})
        pet_total = sum(own_pet.values())
        for pname, pdmg in own_pet.items():
            # A mapped pet carries a GENERATED name (Jabekn, Kobantik), which
            # on a meter reads exactly like another player -- and the whole
            # point of splitting it out of "You" is that you can tell them
            # apart. Ally pets were already tagged "<owner> (pet)"; own pets
            # were not, so they were the one contributor row with no clue
            # what it was. The "<name> pet" convention needs no suffix: it
            # already says pet.
            label = ("Pet" if pname.lower() == f"{self.name} pet".lower()
                     else f"{pname} (pet)")
            allies.append({"name": label, "damage": pdmg,
                           "dps": round(pdmg / duration, 1),
                           "level": None, "classes": None, "is_pet": True})
        # "You" in the group breakdown is player-only (pet shown separately);
        # session/personal DPS still counts the pet
        if (allies or own_pet) and enc["total_out"] > 0:
            you_dmg = max(0, enc["total_out"] - pet_total)
            allies.append({"name": "You", "damage": you_dmg,
                           "dps": round(you_dmg / duration, 1),
                           "level": self.level,
                           "classes": _abbrev_classes(self.class_str)})
        allies.sort(key=lambda a: a["damage"], reverse=True)
        active = live and (datetime.now() - enc["last"]).total_seconds() < COMBAT_TIMEOUT_SECONDS
        return {
            "active": active,
            "allies": allies,
            "started": enc["started"].isoformat(),
            "target": enc["target"],
            "foes": foes,
            "heals": heals,
            "total_healing": sum(h["total"] for h in heals),
            "duration": round(duration, 1),
            "total_damage": enc["total_out"],
            "damage_taken": enc["total_in"],
            "in_hits": enc.get("in_hits", 0),
            "defense": dict(enc.get("defense") or {}),
            "resists": dict(enc.get("resists") or {}),
            "dps": round(enc["total_out"] / duration, 1),
            "peak_dps": round(peak / 3.0, 1),
            "other_casts": [
                {"name": k, "count": v}
                for k, v in sorted((enc.get("other_casts") or {}).items(),
                                   key=lambda kv: -kv[1])[:12]
            ],
            "trio": enc.get("trio"),
            "zone": enc.get("zone"),
            "level": enc.get("level"),
            # difficulty: the mob's OWN level from /con, and the gap to ours.
            # A mob far below the player is a gimme and should carry no
            # weight when judging gear -- but that is a decision for the
            # consumer, so the raw numbers are published rather than a verdict.
            "mob_level": enc.get("mob_level"),
            "mob_rare": bool(enc.get("mob_rare")),
            "level_delta": ((enc["mob_level"] - enc["level"])
                            if enc.get("mob_level") is not None
                            and enc.get("level") is not None else None),
            # survivability: how deep the fight went, and whether mana ran out
            "hp_floor": enc.get("hp_floor"),
            "hp_floor_pct": (round(100.0 * enc["hp_floor"] / self.max_hp, 1)
                             if enc.get("hp_floor") is not None and self.max_hp
                             else None),
            "oom": enc.get("oom", 0),
            # one lumped row, with how many sources it covers -- enough to
            # tell "the filter is hiding something" from "nobody helped"
            "unattributed": ({"damage": sum((enc.get("unattributed") or {}).values()),
                              "sources": len(enc.get("unattributed") or {})}
                             if enc.get("unattributed") else None),
            "timeline": timeline,
            "abilities": abilities,
        }

    def encounter_snapshot(self) -> Optional[dict]:
        if not self.encounter:
            return None
        return self._encounter_view(self.encounter, live=True)

    def filtered_view(self) -> list[dict]:
        """Contributors we hid, and how to judge them.

        `fights` over `session_fights` is the whole signal: EQL only lets
        the tagger's group damage a mob, so someone appearing in most of
        our pulls is almost certainly grouped -- while a passer-by fighting
        a same-named mob shows up once or twice. That is a judgement the
        player makes instantly and no log line states outright.
        """
        now = self.last_event_at
        out = []
        for n, v in self.filtered_seen.items():
            if n in self.ignored_contributors:
                continue
            # A contributor who stopped contributing is a question that
            # answered itself -- they zoned, died or moved on. Keeping them
            # turns a short decision list into a session-long ledger.
            # Measured in LOG time, so an idle night does not age out a
            # group that is simply between pulls.
            last = v.get("last")
            if now and last and (now - last).total_seconds() > FILTERED_TTL_S:
                continue
            out.append({"name": n, "damage": v["damage"],
                        "fights": v["fights"],
                        "pet": self._looks_like_pet(n),
                        "share": (round(100 * v["fights"] / self.session_fights)
                                  if self.session_fights else 0)})
        out.sort(key=lambda r: r["damage"], reverse=True)
        # People first: a pet is not a decision the player can act on, and
        # a list led by eleven of them buries the one name that is.
        return ([r for r in out if not r["pet"]][:12]
                + [r for r in out if r["pet"]][:12])

    def trust_member(self, name: str, trust: bool = True,
                     action: str = "") -> dict:
        """Add or remove someone from the group roster by hand.

        The automatic signals -- an invite accepted, a join line, a line of
        group chat -- are all momentary, and a group that formed by invite
        and plays quietly emits NONE of them. The player always knows the
        answer, so let them say it.

        Trusting ADOPTS what we already hid in the current fight, the same
        move `_adopt_pet_damage` makes on mapping: otherwise approving
        mid-pull shows nothing until the next one and reads as broken.
        """
        name = (name or "").strip()
        if not name:
            return {"ok": False, "error": "no name"}
        if action == "ignore":
            self.ignored_contributors[name] = self.last_event_at
            self.group_members.discard(name)
            return {"ok": True, "name": name, "ignored": True,
                    "group": sorted(self.group_members)}
        if not trust:
            self.group_members.discard(name)
            self.ignored_contributors.pop(name, None)
            return {"ok": True, "name": name, "trusted": False,
                    "group": sorted(self.group_members)}
        self.ignored_contributors.pop(name, None)
        self.group_members.add(name)
        self.filtered_seen.pop(name, None)
        moved = 0
        for enc in ([self.encounter] if self.encounter else []) + list(
                self.encounter_history):
            ua = enc.get("unattributed") or {}
            if name in ua:
                dmg = ua.pop(name)
                allies = enc.setdefault("allies", {})
                allies[name] = allies.get(name, 0) + dmg
                moved += dmg
                if not ua:
                    enc.pop("unattributed", None)
        return {"ok": True, "name": name, "trusted": True, "adopted": moved,
                "group": sorted(self.group_members)}

    def encounters_snapshot(self) -> list[dict]:
        """Current/last pull first, then previous pulls (5 total max)."""
        out = []
        if self.encounter:
            out.append(self._encounter_view(self.encounter, live=True))
        for enc in self.encounter_history:
            if len(out) >= 5:
                break
            out.append(self._encounter_view(enc, live=False))
        return out

    def ability_summary(self) -> dict:
        """Per-ability aggregate across the last 5 pulls — surfaces which
        abilities actually hit hardest over time, not just this fight."""
        encs = ([self.encounter] if self.encounter else []) + list(self.encounter_history)
        encs = encs[:5]
        if not encs:
            return {"encounters": 0, "duration": 0, "abilities": []}
        total_dur = sum(
            max((e["last"] - e["started"]).total_seconds(), 1.0) for e in encs)
        merged: dict[str, dict] = {}
        for e in encs:
            for name, ab in e["abilities"].items():
                m = merged.setdefault(name, {"kind": ab["kind"], "hits": 0,
                                             "total": 0, "crits": 0,
                                             "stuns": 0, "mods": {}})
                m["hits"] += ab["hits"]
                m["total"] += ab["total"]
                m["crits"] += ab.get("crits", 0)
                m["stuns"] += ab.get("stuns", 0)
                for k, v in (ab.get("mods") or {}).items():
                    m["mods"][k] = m["mods"].get(k, 0) + v
        abilities = [
            {"name": n, "kind": m["kind"], "hits": m["hits"],
             "crits": m["crits"], "stuns": m["stuns"], "mods": m["mods"],
             "total": m["total"],
             "avg": round(m["total"] / m["hits"], 1),
             "dps": round(m["total"] / total_dur, 1)}
            for n, m in merged.items()
        ]
        abilities.sort(key=lambda a: (a["avg"], a["total"]), reverse=True)
        merged_heals: dict[str, dict] = {}
        for e in encs:
            for name, hl in e.get("heals", {}).items():
                m = merged_heals.setdefault(name, {"hits": 0, "total": 0})
                m["hits"] += hl["hits"]
                m["total"] += hl["total"]
        heals = [
            {"name": n, "kind": "heal", "hits": m["hits"], "total": m["total"],
             "avg": round(m["total"] / m["hits"], 1),
             "dps": round(m["total"] / total_dur, 1)}
            for n, m in merged_heals.items()
        ]
        heals.sort(key=lambda a: (a["avg"], a["total"]), reverse=True)
        return {"encounters": len(encs), "duration": round(total_dur, 1),
                "abilities": abilities, "heals": heals}

    def combat_profile(self) -> Optional[dict]:
        """Observed incoming-damage profile over the last 5 pulls — lets
        the gear advisor express HP deltas in real units ("+75 HP is two
        average hits") instead of unearned adjectives. None = no data."""
        encs = ([self.encounter] if self.encounter else []) + list(self.encounter_history)
        encs = encs[:5]
        hits = sum(e.get("in_hits", 0) for e in encs)
        taken = sum(e.get("total_in", 0) for e in encs)
        if not encs or taken <= 0:
            return None
        return {
            "fights": len(encs),
            "avg_incoming_hit": round(taken / hits) if hits else None,
            "avg_taken_per_fight": round(taken / len(encs)),
        }

    def _death_recap(self, e: ev.MyDeath) -> dict:
        """The last 15s of incoming damage, frozen at the moment of death."""
        cutoff = e.ts - timedelta(seconds=15)
        hits: list[dict] = []
        for r in reversed(self.ledger):
            if r["type"] not in ("melee_in", "spell_in"):
                continue
            try:
                ts = datetime.fromisoformat(r["ts"])
            except (KeyError, ValueError, TypeError):
                continue
            if ts < cutoff:
                break
            hits.append({"attacker": r.get("attacker"),
                         "damage": r.get("damage", 0),
                         "source": r.get("spell") or r.get("verb") or "hit",
                         "ts": r["ts"]})
            if len(hits) >= 12:
                break
        hits.reverse()
        return {"ts": e.ts.isoformat(), "killer": e.killer,
                "total": sum(h["damage"] for h in hits), "hits": hits}

    def recent_casts(self, limit: int = 20) -> list:
        """Distinct spells recently cast, newest first (includes seed replay
        so the advisor sees the loadout in use even right after startup)."""
        seen: list = []
        for r in reversed(self.ledger):
            if r["type"] == "cast":
                s = r.get("spell")
                if s and s not in seen:
                    seen.append(s)
            if len(seen) >= limit:
                break
        return seen

    def recent_activity_summary(self, limit: int = 8) -> str:
        """Short prose summary of recent notable events, fed to the AI agent."""
        notable = [r for r in list(self.ledger)[-60:] if r["type"] in
                   ("zone", "kill", "death", "level", "aa", "loot", "cast")]
        if not notable:
            return "No recent notable activity."
        parts = []
        for r in notable[-limit:]:
            t = r["type"]
            if t == "zone":
                parts.append(f"entered {r['zone']}")
            elif t == "kill":
                parts.append(f"slew {r['target']}")
            elif t == "death":
                parts.append(f"was slain by {r['killer']}")
            elif t == "level":
                parts.append(f"reached level {r['level']}")
            elif t == "aa":
                parts.append("earned an AA point")
            elif t == "loot":
                parts.append(f"looted {r['item']}")
            elif t == "cast":
                parts.append(f"cast {r['spell']}")
        return "Recently: " + ", ".join(parts) + "."

    def _pet_inv_pre_launch(self) -> bool:
        """Was the pet list read before the game launched?

        Pet gear legitimately survives death and re-summon, so this is NOT
        cleared on a session roll — but it does not survive a wipe, and a
        beta reading describes a pet that no longer exists while still
        gating what the advisor will suggest handing over.
        """
        if not self._pet_inv_ts:
            return False
        try:
            from backend.config import settings
            return self._pet_inv_ts < datetime.fromisoformat(
                settings.eql_launch_iso)
        except (TypeError, ValueError):
            return False

    def _sync_hints(self, book: Optional[dict]) -> list:
        """In-game commands worth running, with why. Rendered in Vitals."""
        hints = []
        # Class gates the whole advisor and is unknown until /who is typed.
        # A class-unique cast proves one WITHOUT it, so say what we already
        # worked out -- it makes the ask concrete instead of generic, and
        # tells the player what we will not otherwise get right.
        if not self.class_str:
            inf = self.inferred_view()
            if inf:
                names = ", ".join(r["cls"] for r in inf)
                hints.append({"command": "/who",
                              "reason": f"Your spells this session point to "
                                        f"{names} — /who confirms the trio "
                                        f"and your level, which the advisor "
                                        f"needs"})
        # Distinguish "logging was never turned on" from "logging is on but
        # quiet": both look like no data, and only one is the user's to fix.
        try:
            from backend import eqclient
            log_off_now = eqclient.logging_off_in_game()
        except Exception:
            log_off_now = False
        if log_off_now:
            hints.append({"command": "/log on",
                          "urgent": True,
                          "reason": "The game is running but its own settings "
                                    "have logging OFF — nothing you do is "
                                    "being recorded"})
        elif not self.has_log:
            hints.append({"command": "/log on",
                          "reason": "No log file found — the companion is blind without one"})
        if self._pet_inv_pre_launch():
            hints.append({"command": "/pet inventory check",
                          "urgent": True,
                          "reason": "The pet gear list is from BEFORE launch — "
                                    "that pet is gone, and the advisor is still "
                                    "gating hand-overs against it"})
        if self.pet_hint:
            hints.append({"command": "/pet leader",
                          "reason": "A summoned pet is unmapped — its damage is "
                                    "counting as an ally's, not yours"})
        # Achievements gets its OWN hint rather than riding the spellbook's.
        # They go stale independently -- this character's spellbook was
        # current while its achievements export was 633 hours old, from
        # before launch -- and the Progression tab would have presented beta
        # progress as fact with nothing on screen to say otherwise.
        try:
            from backend.spellbook import load_export as _le
            ach = _le(self.name, self.server, "Achievements")
        except Exception:
            ach = None
        if ach is None:
            hints.append({"command": "/outputfile achievements",
                          "reason": "No achievements export — class and race "
                                    "unlocks, keys and raid progress all come "
                                    "from it"})
        elif ach.get("pre_launch"):
            hints.append({"command": "/outputfile achievements",
                          "urgent": True,
                          "reason": "Your achievements export is from BEFORE "
                                    "launch — the progression it shows belongs "
                                    "to a beta character"})
        if book is None:
            hints.append({"command": "/outputfile spellbook",
                          "reason": "No spellbook export found; the advisor cannot see owned spells"})
        elif book.get("pre_launch"):
            # Beta data is not merely stale. A character need not survive a
            # launch at all, so every owned-spell and owned-item gate could
            # be reasoning about someone who no longer exists.
            hints.append({"command": "/outputfile spellbook",
                          "urgent": True,
                          "reason": "Your exports are from BEFORE launch — the "
                                    "advisor is judging what you own from beta "
                                    "data. Re-run the output files."})
        else:
            stale = None
            try:
                exported = datetime.fromisoformat(book["updated"])
                for r in reversed(self.ledger):
                    if r["type"] == "level":
                        if datetime.fromisoformat(r["ts"]) > exported:
                            stale = "you have leveled since the last export"
                        break
            except (KeyError, ValueError, TypeError):
                pass
            if not stale and book.get("age_hours", 0) > 24:
                stale = f"the export is {round(book['age_hours'])}h old"
            if stale:
                hints.append({"command": "/outputfile spellbook",
                              "reason": f"Spellbook may be outdated — {stale}"})
        if self._last_aa_seen is None:
            hints.append({"command": "/alternateadv list",
                          "reason": "AA ranks unsynced; the advisor cannot see owned AAs"})
        else:
            for r in reversed(self.ledger):
                if r["type"] == "aa":
                    try:
                        if datetime.fromisoformat(r["ts"]) > self._last_aa_seen:
                            hints.append({
                                "command": "/alternateadv list",
                                "reason": "AA points earned since the last sync — re-list after spending them"})
                    except (KeyError, ValueError, TypeError):
                        pass
                    break
        return hints

    def snapshot(self) -> dict:
        book = None
        if self.spellbook_loader:
            try:
                book = self.spellbook_loader(self.name, self.server)
            except Exception:
                book = None
        return {
            "name": self.name,
            "server": self.server,
            "level": self.level,
            "class_str": self.class_str,
            "race": self.race,
            "playstyle": self.playstyle,
            "aa_available": self.aa_available,
            "spell_slots": self.spell_slots,
            "pet_slots": self.pet_slots,
            "pet_classes": self.pet_classes,
            # Where these came from, so the panel can stop presenting a
            # screen reading as something the player typed. A typed value
            # still wins -- apply_ocr_stats refuses to overwrite one.
            "vitals_source": {
                k: ("manual" if getattr(self, f"_{k}_manual", False)
                    else "ocr" if k in self.vitals_ocr else None)
                for k in ("max_hp", "max_mana")
            },
            "max_hp": self.max_hp,
            "max_mana": self.max_mana,
            "pet_inventory": dict(self.pet_inventory),
            "pet_inventory_at": (self._pet_inv_ts.isoformat()
                                 if self._pet_inv_ts else None),
            "pet_inventory_stale": self._pet_inv_pre_launch(),
            "loadout_hint": self.loadout_hint,
            "owned_aas": {
                "distinct": len(self.owned_aas),
                "ranks": sum(v["ranks"] for v in self.owned_aas.values()),
                "synced": self._last_aa_seen.isoformat() if self._last_aa_seen else None,
            },
            "spellbook": {
                "file": book["file"], "updated": book["updated"],
                "age_hours": book["age_hours"],
                "count": len(book["castable"]),
            } if book else None,
            "sync_hints": self._sync_hints(book),
            "last_death": self.last_death,
            "mob_stats": sorted(
                ({"name": k, **v} for k, v in self.mob_stats.items()),
                key=lambda s: s["kills"], reverse=True)[:10],
            "zone": self.zone,
            "rates": self.rates(),
            "timers": self.timers_view(),
            "alerts": list(self.alerts),
            "in_combat": self.in_combat(),
            "dps": self.dps(),
            "session_max_dps": round(self.session_max_dps, 1),
            "last_target": self.last_target,
            "position": self.position,
            "encounter": self.encounter_snapshot(),
            "encounters": self.encounters_snapshot(),
            "filtered": self.filtered_view(),
            "inferred_classes": self.inferred_view(),
            "ocr_stats": dict(self.ocr_stats),
            "unlock_loot": dict(self.unlock_loot),
            "ability_summary": self.ability_summary(),
            "session": {
                "damage_dealt": self.damage_dealt,
                "damage_taken": self.damage_taken,
                "healing_received": self.healing_received,
                "healing_done": self.healing_done,
                "kills": self.kills,
                "deaths": self.deaths,
                "xp_ticks": self.xp_ticks,
                "xp_percent": round(self.xp_percent, 3),
                "aa_points": self.aa_points,
                "skill_ups": self.skill_ups,
                "crits": self.crits,
                "coin_copper": self.coin_copper,
                "rune_absorbed": self.rune_absorbed,
                "stuns_taken": self.stuns_taken,
                "stuns_landed": self.stuns_landed,
                "mez_applied": self.mez_applied,
                "mods": dict(sorted(self.mods.items(),
                                    key=lambda kv: -kv[1])),
                "overheal": self.overheal,
                "motes": dict(self.motes),
                "hit_rate": round(
                    100 * self.swings_hit / max(self.swings_hit + self.swings_missed, 1), 1),
                "loots": list(self.loots),
            },
            "updated": datetime.now().isoformat(),
        }

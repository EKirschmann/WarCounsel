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

from backend import alerts, spell_file
from backend.alert_data import (ABILITY_COOLDOWNS, COOLDOWN_SHAVES,
                                SPELL_TIMERS)
from backend.log_system import events as ev
from backend.log_system.parser import CLASS_ABBREV, strip_tier

logger = logging.getLogger(__name__)

DPS_WINDOW_SECONDS = 60
COMBAT_TIMEOUT_SECONDS = 8
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
            self.encounter = {"started": ts, "last": ts, "target": None,
                              "total_out": 0, "total_in": 0, "abilities": {},
                              "foes": {}, "trio": self.class_str,
                              # captured HERE, not at flush time: a fight
                              # is often the last thing before a zone line,
                              # so tracker.zone has already moved on by the
                              # time pending_encounters drains
                              "zone": self.zone, "level": self.level}
        else:
            self.encounter["last"] = ts

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

    def _fx_label(self, spell: str) -> str:
        """Exaltation procs share the spell-damage line shape — the effect
        name gives them away. Names that are ALSO scribed label only when
        the client spell file marks them proc-granted AND this session
        never saw a cast (log evidence beats static data)."""
        low = (spell or "").lower()
        base = strip_tier(low)
        if low in self.exalt_effects or base in self.exalt_effects:
            return f"{spell} (exaltation)"
        if ((low in self.exalt_ambiguous or base in self.exalt_ambiguous)
                and low not in self.spell_casts
                and base not in self.spell_casts
                and spell_file.is_proc(low)):
            return f"{spell} (exaltation)"
        return spell

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
            self.race = self.race or e.race
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
                self.pet_owners_dirty = True
        elif isinstance(e, ev.PetAttack):
            # the pet tells ONLY its master — zero-config mapping, no
            # /pet leader needed
            self.pet_hint = False
            if self.pet_owners.get(e.pet) != self.name:
                self.pet_owners[e.pet] = self.name
                self.pet_owners_dirty = True
        elif isinstance(e, ev.CastBegin):
            if e.spell:  # log evidence for proc-vs-cast disambiguation
                self.spell_casts.add(e.spell.lower())
                self.spell_casts.add(strip_tier(e.spell).lower())
                if live:
                    base = strip_tier(e.spell).lower()
                    if base in ABILITY_COOLDOWNS:
                        # cooldown abilities get ONE timer (the pack also
                        # lists some as "durations" — the cooldown wins)
                        self._start_cooldown(e.spell, e.ts)
                    else:
                        secs = SPELL_TIMERS.get(base)
                        if secs:
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
            else:
                self.group_members.discard(e.name)
        elif isinstance(e, ev.GroupChat):
            # Seeds the roster where join lines cannot: log in ALREADY
            # grouped and no one ever "joined", so a join-only filter would
            # hide your real group. Speaking in group chat proves membership.
            if e.channel == "group" and e.sender:
                self.group_members.add(e.sender)
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
                    self._encounter_ability(e.ts, self._fx_label(e.spell),
                                            "spell", e.damage, e.target,
                                            crit=e.crit, mods=e.mods)
                else:  # DotDamage
                    self._encounter_ability(e.ts, self._fx_label(e.spell),
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
                        # An EMPTY roster means no evidence, so it FAILS
                        # OPEN and credits everyone exactly as before.
                        # Filtered damage is LUMPED, never dropped: a
                        # silently missing row looks identical to a quiet
                        # fight, and this gate can be wrong (an unmapped
                        # groupmate's pet has a generated name that proves
                        # nothing, so it lands here too).
                        who = owner or e.attacker
                        if self.group_members and who not in self.group_members:
                            ua = enc.setdefault("unattributed", {})
                            ua[e.attacker] = ua.get(e.attacker, 0) + e.damage
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
                if e.target.lower() == (self.name or "").lower():
                    self.healing_received += e.amount
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
            elif isinstance(e, ev.AbilityActivate):
                self._start_cooldown(e.name, e.ts)
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
            elif isinstance(e, ev.CastInterrupted):
                self._cancel_timer(e.spell)
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
                self.aa_points += 1
                if e.total is not None:
                    self.aa_available = e.total  # the log's own running total
                elif self.aa_available is not None:
                    self.aa_available += 1
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
            label = pname if pname.lower() != f"{self.name} pet".lower() else "Pet"
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

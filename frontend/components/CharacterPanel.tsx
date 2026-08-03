"use client";

import { memo, useEffect, useState } from "react";
import { apiGet, apiSend } from "@/lib/api";

/** 3,614,400 -> "3.6M" — lifetime numbers outgrow a table cell. */
function fmtBig(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}
import type { Lifetime, SessionSummary, Snapshot, TrioCompareRow } from "@/lib/types";

const PLAYSTYLES = [
  "solo_dps", "group_dps", "tank", "healer", "support", "pet_focused", "balanced",
];

const fmt = (n: number) => n.toLocaleString("en-US");

/** 3267 copper -> "3p 2g 6s 7c" (zero denominations omitted). */
const fmtCoin = (c: number) => {
  if (!c) return "0c";
  const parts = [
    [Math.floor(c / 1000), "p"],
    [Math.floor((c % 1000) / 100), "g"],
    [Math.floor((c % 100) / 10), "s"],
    [c % 10, "c"],
  ] as const;
  return parts.filter(([n]) => n > 0).map(([n, u]) => `${n}${u}`).join(" ") || "0c";
};

const MD = { month: "short", day: "numeric" } as const;

/** "Jul 28" for a single day, "Jul 22 – Jul 28" across days, plus a run
 *  marker: a trio you return to stays ONE cumulative row, so the span is
 *  not necessarily continuous play. */
function trioWhen(tr: TrioCompareRow): string {
  const a = new Date(tr.first_seen);
  const b = new Date(tr.last_seen);
  if (Number.isNaN(a.valueOf()) || Number.isNaN(b.valueOf())) return "";
  const fa = a.toLocaleDateString(undefined, MD);
  const fb = b.toLocaleDateString(undefined, MD);
  const span = fa === fb ? fa : `${fa} – ${fb}`;
  return tr.stints > 1 ? `${span} · ${tr.stints} runs` : span;
}

/** Levels ride encounters recorded since this shipped, so an older trio
 *  legitimately has none — a dash, never a fake 0. */
function trioLevels(tr: TrioCompareRow): string {
  const { level_min: lo, level_max: hi } = tr;
  if (lo == null || hi == null) return "—";
  return lo === hi ? String(lo) : `${lo}–${hi}`;
}

function trioTitle(tr: TrioCompareRow): string | undefined {
  const parts = [tr.top_zones.join(", ")];
  if (tr.stints > 1) {
    parts.push(`${tr.stints} separate runs — dates span time on other trios`);
  }
  return parts.filter(Boolean).join(" · ") || undefined;
}

export const CharacterPanel = memo(function CharacterPanel({
  snap,
  onSnapChange,
}: {
  snap: Snapshot | null;
  onSnapChange: (s: Snapshot) => void;
}) {
  const [hpDraft, setHpDraft] = useState("");
  const [manaDraft, setManaDraft] = useState("");
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [trios, setTrios] = useState<TrioCompareRow[]>([]);
  const [lifetime, setLifetime] = useState<Lifetime | null>(null);
  // Session is the default: it answers "how is tonight going", which is
  // what someone glances at mid-play. All-time is a deliberate look.
  const [showAllTime, setShowAllTime] = useState(false);
  useEffect(() => {
    if (!snap?.name) return;
    apiGet<{ history: SessionSummary[] }>("/api/sessions")
      .then((d) => setSessions(d.history ?? []))
      .catch(() => setSessions([]));
    apiGet<{ trios: TrioCompareRow[] }>("/api/trio-compare")
      .then((d) => setTrios(d.trios ?? []))
      .catch(() => setTrios([]));
    // Refetched whenever the character changes, so totals can never carry
    // over from whoever was loaded before.
    apiGet<Lifetime>("/api/lifetime")
      .then((d) => setLifetime(d.available ? d : null))
      .catch(() => setLifetime(null));
    setShowAllTime(false);
  }, [snap?.name, snap?.server]);
  useEffect(() => {
    setHpDraft(snap?.max_hp != null ? String(snap.max_hp) : "");
  }, [snap?.max_hp]);
  useEffect(() => {
    setManaDraft(snap?.max_mana != null ? String(snap.max_mana) : "");
  }, [snap?.max_mana]);
  if (!snap) {
    return (
      <section className="panel">
        <div className="panel-title">Vitals &amp; Session</div>
        <div className="panel-body">
          <p className="chat-empty">
            Waiting for the backend. Start it with{" "}
            <code>uvicorn backend.main:app --reload</code>.
          </p>
        </div>
      </section>
    );
  }

  const s = snap.session;
  const dpsPct = snap.session_max_dps > 0
    ? Math.min(100, (snap.dps / snap.session_max_dps) * 100)
    : 0;

  const patchVitals = async (field: "max_hp" | "max_mana", raw: string) => {
    const v = parseInt(raw, 10);
    if (!Number.isFinite(v) || v <= 0) return;
    if (v === (snap[field] ?? null)) return;
    try {
      const updated = await apiSend<Snapshot>("/api/character", { [field]: v }, "PATCH");
      onSnapChange(updated);
    } catch {
      /* backend offline — leave as-is */
    }
  };

  const setPlaystyle = async (playstyle: string) => {
    try {
      const updated = await apiSend<Snapshot>("/api/character", { playstyle }, "PATCH");
      onSnapChange(updated);
    } catch {
      /* backend offline — leave as-is */
    }
  };

  return (
    <section className="panel">
      <div className="panel-title">Vitals &amp; Session</div>
      <div className="panel-body">
        <div className="level-row">
          <div className="level-num">{snap.level ?? "?"}</div>
          <div className="level-meta">
            Level
            <br />
            {snap.in_combat ? (
              <span className="combat-flag">
                In combat{snap.last_target ? ` — ${snap.last_target}` : ""}
              </span>
            ) : (
              <span>At ease</span>
            )}
          </div>
        </div>

        <div
          className="vitals-edit"
          data-src={snap.vitals_source?.max_hp ?? undefined}
          title={
            snap.vitals_source?.max_hp === "ocr"
              ? "Read from your Inventory window by the stats OCR. Type over either box to pin it yourself — a typed value is never overwritten by a screen reading."
              : "The log never prints your max HP/mana — type them once, or turn on the character-stats OCR in Settings and they keep themselves current."
          }
        >
          <label htmlFor="maxhp">
            Max HP
            {snap.vitals_source?.max_hp === "ocr" && (
              <span className="vitals-src" title="from the stats OCR">screen</span>
            )}
            <input
              id="maxhp"
              type="number"
              min={1}
              placeholder="?"
              value={hpDraft}
              onChange={(e) => setHpDraft(e.target.value)}
              onBlur={() => patchVitals("max_hp", hpDraft)}
              onKeyDown={(e) => e.key === "Enter" && patchVitals("max_hp", hpDraft)}
            />
          </label>
          <label htmlFor="maxmana">
            Max Mana
            {snap.vitals_source?.max_mana === "ocr" && (
              <span className="vitals-src" title="from the stats OCR">screen</span>
            )}
            <input
              id="maxmana"
              type="number"
              min={1}
              placeholder="?"
              value={manaDraft}
              onChange={(e) => setManaDraft(e.target.value)}
              onBlur={() => patchVitals("max_mana", manaDraft)}
              onKeyDown={(e) => e.key === "Enter" && patchVitals("max_mana", manaDraft)}
            />
          </label>
        </div>

        {snap.level === null && (
          <p style={{ fontSize: 12, color: "var(--muted)", marginBottom: 10 }}>
            Level unknown — type <code>/who</code> in-game once and the
            companion learns your level and class from the log.
          </p>
        )}

        {snap.loadout_hint && (
          <p className="loadout-hint" role="status">{snap.loadout_hint}</p>
        )}

        {snap.sync_hints.length > 0 && (
          <div className="sync-hints" role="status">
            {snap.sync_hints.map((h) => (
              <p
                key={h.command + h.reason}
                className="sync-hint"
                data-urgent={h.urgent ? "1" : undefined}
              >
                {h.reason} — type <code>{h.command}</code> in-game.
              </p>
            ))}
          </div>
        )}

        <div className="gauge">
          <div className="gauge-label">
            <span>DPS (60s)</span>
            <span className="gauge-value">{snap.dps}</span>
          </div>
          <div className="gauge-track">
            <div className="gauge-fill" style={{ width: `${dpsPct}%` }} />
          </div>
        </div>

        {(snap.timers?.length ?? 0) > 0 && (
          <ul className="vital-timers" aria-label="Active timers">
            {(snap.timers ?? []).slice(0, 5).map((tm) => (
              <li key={tm.name} data-kind={tm.kind} data-short={tm.remaining <= 5 ? "1" : undefined}>
                <span>{tm.name}</span>
                <span className="vital-timer-clock">
                  {tm.remaining >= 60
                    ? `${Math.floor(tm.remaining / 60)}:${String(tm.remaining % 60).padStart(2, "0")}`
                    : `${tm.remaining}s`}
                </span>
              </li>
            ))}
          </ul>
        )}

        <div className="tiles">
          <div className="tile" data-accent="out">
            <div className="tile-value">{fmt(s.damage_dealt)}</div>
            <div className="tile-label">Damage dealt</div>
          </div>
          <div className="tile" data-accent="in">
            <div className="tile-value">{fmt(s.damage_taken)}</div>
            <div className="tile-label">Damage taken</div>
          </div>
          <div className="tile" data-accent="heal">
            <div className="tile-value">{fmt(s.healing_received)}</div>
            <div className="tile-label">Healing received</div>
          </div>
          <div className="tile" data-accent="heal">
            <div className="tile-value">{fmt(s.healing_done)}</div>
            <div className="tile-label">Healing done</div>
          </div>
          <div className="tile" data-accent="milestone">
            <div className="tile-value">{s.kills}</div>
            <div className="tile-label">Kills</div>
          </div>
          <div className="tile" data-accent="in">
            <div className="tile-value">{s.deaths}</div>
            <div className="tile-label">Deaths</div>
          </div>
          <div className="tile" data-accent="milestone">
            <div className="tile-value">
              {s.xp_percent > 0 ? `${s.xp_percent.toFixed(1)}%` : s.xp_ticks}
            </div>
            <div className="tile-label">XP gained</div>
          </div>
          <div className="tile" data-accent="milestone">
            <div className="tile-value">{s.aa_points}</div>
            <div className="tile-label">AA points</div>
          </div>
          <div className="tile">
            <div className="tile-value">{s.hit_rate}%</div>
            <div className="tile-label">Hit rate</div>
          </div>
          <div className="tile">
            <div className="tile-value">{s.skill_ups}</div>
            <div className="tile-label">Skill-ups</div>
          </div>
          <div className="tile" data-accent="milestone">
            <div className="tile-value">{fmtCoin(s.coin_copper ?? 0)}</div>
            <div className="tile-label">Coin earned</div>
          </div>
          <div className="tile" data-accent="out">
            <div className="tile-value">{s.crits ?? 0}</div>
            <div className="tile-label">Crits ✦</div>
          </div>
        </div>

        {s.loots.length > 0 && (
          <div className="loot-list">
            <h3>Recent loot</h3>
            <ul>
              {s.loots.slice(0, 6).map((item, i) => (
                <li key={`${item}-${i}`}>{item}</li>
              ))}
            </ul>
          </div>
        )}

        {Object.keys(snap.unlock_loot ?? {}).length > 0 && (
          <div className="loot-list unlock-list">
            {/* Nothing in the game says a Gnoll Fang is 1/1200th of a
                Barbarian at the moment you loot it, and the cost of not
                knowing is not a wasted click — it is having sold four
                hundred of them. */}
            <h3>Race unlock turn-ins</h3>
            <ul>
              {Object.entries(snap.unlock_loot ?? {}).map(([item, u]) => (
                <li key={item} title={u.note ?? undefined}>
                  <span className="unlock-item">{item}</span>
                  <span className="unlock-count">
                    {u.count}
                    {u.total ? ` / ${u.total}` : ""}
                  </span>
                  <span className="unlock-where">
                    {u.race} — {u.npc}, {u.zone}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {trios.length > 1 && (
          <div className="loot-list hunt-list">
            <h3>Trio comparison</h3>
            <table className="hunt-table">
              <thead>
                <tr>
                  <th scope="col">Trio</th>
                  <th scope="col" title="Character level while running this trio">Lvl</th>
                  <th scope="col">Fights</th>
                  <th scope="col" title="Total damage / total fight seconds">DPS</th>
                </tr>
              </thead>
              <tbody>
                {trios.slice(0, 5).map((tr) => (
                  <tr key={tr.trio} title={trioTitle(tr)}>
                    <td className="hunt-name">
                      {tr.trio}
                      <div className="trio-when">{trioWhen(tr)}</div>
                    </td>
                    <td>{trioLevels(tr)}</td>
                    <td>{tr.fights}</td>
                    <td>{tr.avg_dps}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {lifetime && (
          <div className="loot-list hunt-list">
            <div className="lt-head">
              <h3>{showAllTime ? "All time" : "This session"}</h3>
              <button
                type="button"
                className="lt-toggle"
                onClick={() => setShowAllTime((v) => !v)}
                title={`${lifetime.character}@${lifetime.server} — totals are per character and server`}
              >
                {showAllTime ? "session" : "all time"}
              </button>
            </div>
            {showAllTime ? (
              <table className="hunt-table lt-table">
                <tbody>
                  <tr><td className="hunt-name">Kills</td><td>{lifetime.kills.toLocaleString()}</td>
                      <td className="hunt-name">Deaths</td><td>{lifetime.deaths.toLocaleString()}</td></tr>
                  <tr><td className="hunt-name">Loot</td><td>{lifetime.loot.toLocaleString()}</td>
                      <td className="hunt-name">Levels</td><td>{lifetime.levels}</td></tr>
                  <tr><td className="hunt-name">Fights</td><td>{lifetime.fights.toLocaleString()}</td>
                      <td className="hunt-name">Zones</td><td>{lifetime.zones}</td></tr>
                  <tr><td className="hunt-name">Damage</td><td>{fmtBig(lifetime.damage_dealt)}</td>
                      <td className="hunt-name">Taken</td><td>{fmtBig(lifetime.damage_taken)}</td></tr>
                  <tr><td className="hunt-name">Healed</td><td>{fmtBig(lifetime.healing_done)}</td>
                      <td className="hunt-name">Best DPS</td><td>{lifetime.best_dps}</td></tr>
                  <tr><td className="hunt-name">In combat</td>
                      <td>{Math.round(lifetime.fight_seconds / 3600)}h</td>
                      <td className="hunt-name">AAs</td><td>{lifetime.aas}</td></tr>
                </tbody>
              </table>
            ) : null}
            {showAllTime && (
              <p className="lt-note">
                {lifetime.character}@{lifetime.server} — since launch
                {lifetime.since ? ` (${lifetime.since.slice(0, 10)})` : ""}.
                Beta play is not counted. Coin and XP began recording a little
                later than the rest.
              </p>
            )}
          </div>
        )}

        {sessions.length > 0 && !showAllTime && (
          <div className="loot-list hunt-list">
            <h3>Past sessions</h3>
            <table className="hunt-table">
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col" title="Active hours (2-min activity buckets)">Hrs</th>
                  <th scope="col">Kills</th>
                  <th scope="col">XP</th>
                  <th scope="col">Coin</th>
                </tr>
              </thead>
              <tbody>
                {sessions.slice(0, 8).map((sess, i) => (
                  <tr key={sess.started ?? i}>
                    <td className="hunt-name">
                      {sess.started
                        ? new Date(sess.started).toLocaleDateString("en-GB", {
                            day: "2-digit",
                            month: "short",
                          })
                        : "?"}
                    </td>
                    <td>{sess.active_hours ?? "?"}</td>
                    <td>{sess.kills}</td>
                    <td>{sess.xp_percent > 0 ? `${sess.xp_percent}%` : "—"}</td>
                    <td>{fmtCoin(sess.coin_copper ?? 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {snap.mob_stats.length > 0 && (
          <div className="loot-list hunt-list">
            <h3>Session hunting</h3>
            <table className="hunt-table">
              <thead>
                <tr>
                  <th scope="col">Mob</th>
                  <th scope="col">Kills</th>
                  <th scope="col">XP</th>
                  {/* No per-mob Coin column: coin is worth knowing as a
                      session total, which the tile above already gives.
                      Split across a mob list it is noise — and the width
                      is better spent on kills, XP and drop rate. The data
                      is still tracked; it feeds drop-rate work and the
                      all-time totals. */}
                  <th scope="col" title="Observed drop rate — items dropped / kills">
                    Drops
                  </th>
                </tr>
              </thead>
              <tbody>
                {[...snap.mob_stats]
                  .sort((a, b) => (b.xp_percent ?? 0) - (a.xp_percent ?? 0) || b.kills - a.kills)
                  .slice(0, 8)
                  .map((m) => (
                  <tr key={m.name} title={m.loots.join(", ") || undefined}>
                    <td className="hunt-name">{m.name}</td>
                    <td>{m.kills}</td>
                    <td>{m.xp_percent > 0 ? `${m.xp_percent.toFixed(1)}%` : "—"}</td>
                    <td>
                      {m.kills > 0 && (m.loot_drops ?? 0) > 0
                        ? `${Math.round((100 * (m.loot_drops ?? 0)) / m.kills)}%`
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Focus moved to the Advisor header — it steers the counsel
            and belongs beside the button that asks for it, not at the
            bottom of a session summary it has nothing to do with. */}
      </div>
    </section>
  );
});

"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import { ItemHover } from "./ItemHover";

/* Quests your bags are already carrying items for.
 *
 * There is no progress percentage here on purpose. Required counts live in
 * walkthrough prose on the wiki ("Bring me two tufts of bat fur"), not in
 * any structured field, and a number scraped from a sentence would send
 * someone farming the wrong amount. What IS exact is how many you hold, so
 * that is what the panel shows, next to a link to read the requirement at
 * the source. */

interface QuestItem {
  name: string;
  count: number;
  where: string[];
}
interface QuestRow {
  quest: string;
  url: string;
  items: QuestItem[];
  giver?: string | null;
  zone?: string | null;
  min_level?: number | null;
  classes?: string | null;
  races?: string | null;
  rewards?: string[] | null;
  disambiguation?: boolean;
  below_level?: boolean;
  era?: string | null;
  out_of_era?: boolean;
  kind?: string;
  /** What this unlocks or is restricted to — the race, or the classes. */
  unlocks?: string | null;
  /** Race-unlock rows only: total turn-ins and the size of one. */
  needed?: number | null;
  have?: number | null;
  per_turnin?: number | null;
  note?: string | null;
}

/** Section order is the order a player works through them: what unlocks a
 *  race, what a class needs, then gear, then the grinds. Labels are the
 *  wiki's own categories, not ones we invented. */
const SECTIONS: { key: string; label: string; note: string }[] = [
  { key: "race", label: "Race unlocks", note: "Turn-ins on a race-unlock faction path." },
  { key: "class", label: "Class quests", note: "Restricted to particular classes — shown whatever you are playing now." },
  { key: "equipment", label: "Equipment", note: "Rewards you can wear or wield." },
  { key: "spell", label: "Spells", note: "Rewards a spell or tome." },
  { key: "faction", label: "Faction & repeatables", note: "Turn in as often as you like; the reward is standing." },
  { key: "other", label: "Other", note: "The wiki page did not say enough to place these." },
];

export function QuestPanel({ level }: { level?: number | null }) {
  const [rows, setRows] = useState<QuestRow[] | null>(null);
  const [scanned, setScanned] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  // Same control the Encounter panel uses, for the same reason: this is a
  // dense list people read at a glance, and one text size does not suit
  // every monitor. Persisted under its own key.
  const [scale, setScale] = useState(1);
  useEffect(() => {
    const v = parseFloat(localStorage.getItem("eql.questScale") || "1");
    if (v >= 0.8 && v <= 1.6) setScale(v);
  }, []);
  const bumpScale = (d: number) => {
    setScale((v) => {
      const n = Math.min(1.6, Math.max(0.8, Math.round((v + d) * 20) / 20));
      localStorage.setItem("eql.questScale", String(n));
      return n;
    });
  };

  const scan = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      const d = await apiGet<{
        quests: QuestRow[];
        items_scanned?: number;
        note?: string;
      }>("/api/quests");
      setRows(d.quests ?? []);
      setScanned(d.items_scanned ?? null);
      if (d.note) setErr(d.note);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "scan failed");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void scan();
  }, [scan]);

  const all = rows ?? [];
  // Out-of-era quests are the Kunark-and-later content EQL does not
  // implement. Kept, because the ITEMS are real and sit in your bags —
  // but moved below, because they are not things you can go and do.
  const inEra = all.filter((q) => !q.out_of_era);
  const outEra = all.filter((q) => q.out_of_era);
  const shown = showAll ? inEra : inEra.slice(0, 25);

  return (
    <section className="panel quest-panel">
      <div className="panel-head">
        <h2>Quests</h2>
        <span className="atlas-zone">
          {scanned != null ? `${scanned} items scanned` : ""}
        </span>
        <span className="font-scale" aria-label="Quest text size">
          <button type="button" onClick={() => bumpScale(-0.1)} title="Smaller text">A−</button>
          <button type="button" onClick={() => bumpScale(0.1)} title="Larger text">A+</button>
        </span>
        <button type="button" className="adv-rescan" onClick={scan} disabled={busy}>
          {busy ? "scanning…" : "rescan"}
        </button>
      </div>

      <div className="panel-body" style={{ zoom: scale }}>
        {/* One line, not five. The rationale that used to sit here — and
            under every section heading — explained the design to someone who
            only wants to know whether they can finish a quest. It lives in
            tooltips now, where it is available and not in the way. */}
        <p
          className="adv-note"
          title="From your /outputfile inventory export joined to the wiki. Counts are what you hold; the required amount lives in each quest's walkthrough, so follow the link rather than trusting a number here. Class and level are shown but never used to hide a row — you will change trio and the items keep."
        >
          Quests that want something you are already carrying.
        </p>

        {err && <p className="set-note" data-ok="0">{err}</p>}
        {busy && !rows && <p className="adv-note">Reading item pages…</p>}
        {rows && rows.length === 0 && !err && (
          <p className="adv-note">
            Nothing you are carrying is referenced by a quest page.
          </p>
        )}

        {SECTIONS.map((sec) => {
          const rowsIn = shown.filter((q) => (q.kind || "other") === sec.key);
          if (rowsIn.length === 0) return null;
          return (
            <div key={sec.key}>
              <div className="adv-sub" style={{ marginTop: 12 }} title={sec.note}>
                {sec.label} — {rowsIn.length}
              </div>
              {rowsIn.map((q) => (
          <div className="quest-row" key={q.quest}>
            <div className="quest-head">
              <a href={q.url} target="_blank" rel="noreferrer noopener">
                {q.quest}
              </a>
              {/* A chip, not a suffix. "Gnoll Bounty L1" read as the quest's
                  name; the level is a gate on it. */}
              {q.min_level != null && (
                <span
                  className="quest-lvl"
                  data-warn={q.below_level ? "1" : undefined}
                  title={q.below_level
                    ? `Needs level ${q.min_level}; you are ${level ?? "?"}`
                    : `Minimum level ${q.min_level}`}
                >
                  L{q.min_level}
                </span>
              )}
              {q.unlocks && (
                <span className="quest-unlocks" title="What this quest is for">
                  {q.unlocks}
                </span>
              )}
              {q.disambiguation && (
                <span className="enc-tag" title="Several quests share this name — the page lists them">
                  several
                </span>
              )}
            </div>

            <div className="quest-items">
              {q.items.map((i) => (
                <span className="quest-item" key={i.name}>
                  <ItemHover name={i.name} />
                  <strong>×{i.count}</strong>
                  {i.where.length > 0 && (
                    <span className="adv-cls"> ({i.where.join("/")})</span>
                  )}
                </span>
              ))}
            </div>

            {/* A bar only where the requirement is STATED — the vendored
                unlock table gives exact totals, a walkthrough gives prose.
                Showing one on some rows and not others is the honest
                version of "we know this number and not that one". */}
            {q.needed != null && q.have != null && (
              <div className="quest-progress" title={`${q.have} of ${q.needed}`}>
                <div
                  className="quest-progress-fill"
                  style={{ width: `${Math.min(100, (q.have / q.needed) * 100)}%` }}
                />
                <span>
                  {q.have} / {q.needed}
                  {" · "}
                  {Math.floor((q.have / q.needed) * 100)}%
                </span>
              </div>
            )}
            <div className="quest-meta">
              {q.needed != null && (
                <span title={q.note ?? undefined}>
                  {/* Counts from the vendored unlock table, which states them
                      outright — unlike a walkthrough, where they are prose. */}
                  {q.needed} needed
                  {q.per_turnin ? `, ${q.per_turnin} per turn-in` : ""}
                </span>
              )}
              {q.giver && <span>{q.giver}</span>}
              {q.zone && <span>{q.zone}</span>}
              {q.classes && q.classes.toLowerCase() !== "all" && (
                <span>{q.classes}</span>
              )}
              {q.rewards && q.rewards.length > 0 && (
                <span className="quest-reward">{q.rewards.slice(0, 4).join(", ")}</span>
              )}
            </div>
          </div>
              ))}
            </div>
          );
        })}

        {inEra.length > 25 && !showAll && (
          <button type="button" className="adv-rescan" onClick={() => setShowAll(true)}>
            show the other {inEra.length - 25}
          </button>
        )}

        {outEra.length > 0 && (
          <>
            <div className="adv-sub" style={{ marginTop: 14 }}>
              Out of era — {outEra.length}
            </div>
            <p className="adv-note">
              Not implemented in this game — listed so you know why the items
              are in your bags.
            </p>
            {outEra.map((q) => (
              <div className="quest-row" key={q.quest} data-dim="1">
                <div className="quest-head">
                  <a href={q.url} target="_blank" rel="noreferrer noopener">
                    {q.quest}
                  </a>
                  {q.era && <span className="adv-cls"> {q.era}</span>}
                </div>
                <div className="quest-items">
                  {q.items.map((i) => (
                    <span className="quest-item" key={i.name}>
                      <ItemHover name={i.name} />
                      <strong>×{i.count}</strong>
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </>
        )}
      </div>
    </section>
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import { usePanelPrefs } from "@/lib/panelPrefs";

/* What the game says you have and have not done.
 *
 * Read straight from the /outputfile achievements dump, which carries a
 * complete/incomplete marker on every criterion. That is the whole reason
 * this exists rather than inferring progress from your bags: an item you
 * already turned in has left your inventory while its criterion stays
 * complete, and a class confirmed at creation autocompletes without the
 * items ever being held. Every other Plane of Sky tracker guesses at both. */

interface Criterion {
  text: string;
  done: boolean;
  note: boolean;
}
interface Achievement {
  name: string;
  done: boolean;
  steps: number;
  steps_done: number;
  criteria: Criterion[];
}
interface Section {
  section: string;
  kind: string;
  done: number;
  total: number;
  achievements: Achievement[];
}

/** Lead with what a player is actually chasing; bulk collections last. */
const ORDER = ["class", "raid", "key", "race", "deity", "faction",
               "explore", "hunter", "slayer", "tradeskill", "other"];
const LABEL: Record<string, string> = {
  class: "Class unlocks — Plane of Sky",
  raid: "Raid targets",
  key: "Keys",
  race: "Race unlocks",
  deity: "Deity",
  faction: "Factions",
  explore: "Exploration",
  hunter: "Hunter",
  slayer: "Slayer",
  tradeskill: "Tradeskills",
  other: "Other",
};

/** The part of a row's name the section header already told you.
 *
 * Sixteen rows reading "Primary Class Unlock - Bard" under a heading that
 * says CLASS UNLOCKS spend 23 characters restating the section before the
 * one word that differentiates them. Taken from the section's own longest
 * common prefix rather than a hardcoded list, so Keys — whose four names
 * share nothing — keeps its full labels without a special case.
 */
function sharedPrefix(names: string[]): string {
  if (names.length < 2) return "";
  let p = names[0];
  for (const n of names.slice(1)) {
    let i = 0;
    while (i < p.length && i < n.length && p[i] === n[i]) i++;
    p = p.slice(0, i);
    if (!p) return "";
  }
  // Only strip a real label prefix, and never the whole name.
  const cut = p.replace(/[^ ]*$/, "");
  return cut.length >= 4 && names.every((n) => n.slice(cut.length).trim()) ? cut : "";
}

function pct(a: Achievement): number {
  return a.steps > 0 ? a.steps_done / a.steps : a.done ? 1 : 0;
}

export function ProgressionPanel() {
  const { show } = usePanelPrefs();
  const [data, setData] = useState<{
    available: boolean; sections: Section[]; done?: number; count?: number;
    note?: string; pre_launch?: boolean; age_hours?: number;
  } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [openRow, setOpenRow] = useState<Record<string, boolean>>({});
  // Pre-launch data is WITHHELD, not merely labelled. A beta export on this
  // character claimed "Primary Class Unlock - Monk — DONE, all six Sky items"
  // while the real one says Monk 0/6 and Paladin 4/4. That is not stale, it
  // is a confident wrong answer to "have I finished this", and a banner above
  // it does not stop the body of the panel asserting it. Flagging has to be
  // remembered on every surface and fails silently where it was not;
  // withholding fails safe.
  const [showBeta, setShowBeta] = useState(false);
  const [scale, setScale] = useState(1);

  useEffect(() => {
    const v = parseFloat(localStorage.getItem("eql.progScale") || "1");
    if (v >= 0.8 && v <= 1.6) setScale(v);
  }, []);
  const bumpScale = (d: number) =>
    setScale((v) => {
      const n = Math.min(1.6, Math.max(0.8, Math.round((v + d) * 20) / 20));
      localStorage.setItem("eql.progScale", String(n));
      return n;
    });

  const load = useCallback(async () => {
    setErr(null);
    setShowBeta(false);      // a reload re-blocks; the reveal is per-look
    try {
      setData(await apiGet("/api/progression"));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "could not load progression");
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  if (err) return <section className="panel"><div className="panel-body">
    <p className="set-note" data-ok="0">{err}</p></div></section>;
  if (!data) return <section className="panel"><div className="panel-body">
    <p className="adv-note">Reading achievements…</p></div></section>;

  const sections = [...(data.sections || [])]
    .filter((s) => show("progression", s.kind))
    .sort((a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind));

  return (
    <section className="panel prog-panel">
      <div className="panel-head">
        <h2>Progression</h2>
        <span className="atlas-zone">
          {data.available ? `${data.done} of ${data.count} done` : ""}
        </span>
        <span className="font-scale" aria-label="Text size">
          <button type="button" onClick={() => bumpScale(-0.1)} title="Smaller text">A−</button>
          <button type="button" onClick={() => bumpScale(0.1)} title="Larger text">A+</button>
        </span>
        <button type="button" className="adv-rescan" onClick={load}>reload</button>
      </div>

      <div className="panel-body" style={{ zoom: scale }}>
        {!data.available && <p className="adv-note">{data.note}</p>}

        {/* Beta progress presented as fact is worse than no panel. The
            export goes stale on its own schedule — this character's
            spellbook was current while this file was 633 hours old. */}
        {data.pre_launch && (
          <div className="sync-hint" data-urgent="1" role="status">
            <p>
              This export is from BEFORE launch, so it describes a beta
              character — including which unlocks it calls finished. Type{" "}
              <code>/outputfile achievements</code> in-game, then reload.
            </p>
            {!showBeta && (
              <button type="button" className="adv-rescan"
                      onClick={() => setShowBeta(true)}>
                show it anyway
              </button>
            )}
          </div>
        )}

        {!(data.pre_launch && !showBeta) && sections.map((s) => {
          const isOpen = open[s.section] ?? (s.kind === "class" || s.kind === "raid");
          // Finished first, then closest to done. They used to sink to the
          // bottom, which put the one class unlock this character had
          // completed off-screen under fifteen rows of 0/6 — defensible while
          // "done" was dim and easy to read as clutter, wrong now that it is
          // the row wearing the gold.
          const rows = [...s.achievements].sort(
            (a, b) => Number(b.done) - Number(a.done) || pct(b) - pct(a));
          const strip = sharedPrefix(s.achievements.map((a) => a.name));
          return (
            <div key={s.section} className="prog-sec">
              <button
                type="button"
                className="prog-head"
                aria-expanded={isOpen}
                onClick={() => setOpen((o) => ({ ...o, [s.section]: !isOpen }))}
              >
                <span className="prog-caret">{isOpen ? "▾" : "▸"}</span>
                {LABEL[s.kind] ?? s.section}
                <span className="prog-count">{s.done}/{s.total}</span>
              </button>

              {isOpen && rows.map((a) => {
                // Criteria are shown for anything STARTED, and hidden behind a
                // click otherwise. Sixteen class unlocks at 0/6 is 96 lines of
                // things you have not done, which buries the two you have.
                const rowOpen = openRow[a.name] ?? (a.steps_done > 0 && !a.done);
                return (
                <div className="prog-row" key={a.name} data-done={a.done ? "1" : undefined}>
                  <button
                    type="button"
                    className="prog-name"
                    aria-expanded={rowOpen}
                    onClick={() => setOpenRow((o) => ({ ...o, [a.name]: !rowOpen }))}
                  >
                    <span className="prog-caret">{rowOpen ? "▾" : "▸"}</span>
                    {a.done && <span className="prog-done-mark">✦</span>}
                    {strip ? a.name.slice(strip.length) : a.name}
                    {a.steps > 0 && (
                      <span className="prog-frac">
                        {a.done ? "done" : `${a.steps_done}/${a.steps}`}
                      </span>
                    )}
                  </button>
                  {a.steps_done > 0 && !a.done && (
                    <div className="prog-track" title={`${a.steps_done} of ${a.steps}`}>
                      <div className="prog-fill" style={{ width: `${pct(a) * 100}%` }} />
                    </div>
                  )}
                  {rowOpen && (
                    <ul className="prog-crit">
                      {a.criteria.filter((c) => !c.note).map((c) => (
                        <li key={c.text} data-done={c.done ? "1" : undefined}>
                          <span className="prog-tick">{c.done ? "✓" : "○"}</span>
                          {c.text.replace(/^Obtain /, "").replace(/\.$/, "")}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                );
              })}
            </div>
          );
        })}
      </div>
    </section>
  );
}

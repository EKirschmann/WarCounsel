"use client";

import { useEffect, useMemo, useState } from "react";
import { apiGet } from "@/lib/api";

/** One retained row: [seconds from fight start, kind, name, amount, target, tag]. */
type HitRow = [number, string, string, number, string, string];

interface HitsView {
  started: string;
  duration: number;
  hits: HitRow[];
  dropped: number;
  cap: number;
}

interface Lane {
  key: string;
  label: string;
  /** out | in | heal — decides the colour, which is the app's semantic set. */
  side: "out" | "in" | "heal";
  rows: HitRow[];
  total: number;
  max: number;
}

const MAX_LANES = 12;

/** Group rows into lanes: one per outgoing ability, one per incoming
 *  source, one for heals. Outgoing lanes rank by total damage; past the
 *  cap they fold into "other" rather than vanish, because a lane that is
 *  missing reads as a skill that was never used. */
function toLanes(hits: HitRow[]): Lane[] {
  const by = new Map<string, Lane>();
  for (const h of hits) {
    const [, kind, name, amount] = h;
    const side: Lane["side"] = kind === "in" ? "in" : kind === "heal" ? "heal" : "out";
    const key = side === "heal" ? "heal" : `${side}:${name}`;
    let lane = by.get(key);
    if (!lane) {
      lane = { key, label: side === "heal" ? "Heals" : name, side, rows: [], total: 0, max: 0 };
      by.set(key, lane);
    }
    lane.rows.push(h);
    lane.total += amount;
    if (amount > lane.max) lane.max = amount;
  }
  const out = Array.from(by.values()).filter((l) => l.side === "out").sort((a, b) => b.total - a.total);
  const inc = Array.from(by.values()).filter((l) => l.side === "in").sort((a, b) => b.total - a.total);
  const heal = Array.from(by.values()).filter((l) => l.side === "heal");
  const fold = (lanes: Lane[], keep: number, label: string, side: Lane["side"]) => {
    if (lanes.length <= keep) return lanes;
    const head = lanes.slice(0, keep);
    const rest = lanes.slice(keep);
    const other: Lane = { key: `${side}:other`, label, side, rows: [], total: 0, max: 0 };
    for (const l of rest) {
      other.rows.push(...l.rows);
      other.total += l.total;
      other.max = Math.max(other.max, l.max);
    }
    return [...head, other];
  };
  const outKeep = Math.max(3, MAX_LANES - Math.min(inc.length, 3) - heal.length);
  return [
    ...fold(out, outKeep, `other (${out.length - outKeep} more)`, "out"),
    ...fold(inc, 3, "other incoming", "in"),
    ...heal,
  ];
}

/** Gridline spacing that keeps roughly 6–12 lines on screen. */
function gridStep(duration: number, zoom: number): number {
  const target = duration / (8 * zoom);
  for (const s of [1, 2, 5, 10, 15, 30, 60, 120, 300]) if (s >= target) return s;
  return 600;
}

function describe(h: HitRow): string {
  const [t, kind, name, amount, target, tag] = h;
  const what =
    tag === "miss" ? `${name} missed`
    : tag === "resist" ? `${name} resisted`
    : kind === "in" && amount === 0 ? `${name} — ${tag}`
    : `${name} ${amount.toLocaleString("en-US")}${tag ? ` (${tag})` : ""}`;
  const who = target ? (kind === "in" ? ` from ${target}` : ` → ${target}`) : "";
  return `${t}s · ${what}${who}`;
}

export function FightTimeline({ started, active }: { started: string; active: boolean }) {
  const [data, setData] = useState<HitsView | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);

  // Fetch on demand and, while the fight is live, keep up with it. Hits
  // are not in the socket snapshot on purpose (hundreds of rows at six
  // frames a second), so this is the one place they are read.
  useEffect(() => {
    let alive = true;
    const load = () =>
      apiGet<HitsView>(`/api/encounter/hits?started=${encodeURIComponent(started)}`)
        .then((d) => { if (alive) { setData(d); setErr(null); } })
        .catch((e: unknown) => {
          if (!alive) return;
          setErr(e instanceof Error && /404/.test(e.message)
            ? "This fight's individual hits are no longer held — only the current fight and the last five keep them."
            : "Could not load the timeline.");
        });
    load();
    const id = active ? setInterval(load, 2000) : undefined;
    return () => { alive = false; if (id) clearInterval(id); };
  }, [started, active]);

  const lanes = useMemo(() => (data ? toLanes(data.hits) : []), [data]);

  if (err) return <p className="ft-note">{err}</p>;
  if (!data) return <p className="ft-note">Loading the timeline…</p>;
  if (data.hits.length === 0) return <p className="ft-note">No hits retained for this fight.</p>;

  const dur = Math.max(data.duration, 1);
  const step = gridStep(dur, zoom);
  const grid: number[] = [];
  for (let s = step; s < dur; s += step) grid.push(s);
  const pct = (t: number) => `${Math.min(100, (t / dur) * 100)}%`;

  return (
    <div className="ft" aria-label="Fight timeline: one lane per ability, a mark per hit">
      <div className="ft-bar">
        <span className="ft-legend">
          <i className="ft-mark" data-side="out" /> hit
          <i className="ft-mark" data-side="out" data-tag="miss" /> miss
          <i className="ft-mark" data-side="out" data-tag="resist" /> resist
          <i className="ft-mark" data-side="in" /> taken
          <i className="ft-mark" data-side="heal" /> heal
        </span>
        <span className="ft-zoom" aria-label="Zoom">
          {[1, 2, 4, 8].map((z) => (
            <button key={z} type="button" data-on={zoom === z ? "1" : undefined}
                    onClick={() => setZoom(z)} title={`${z}× — scroll sideways to pan`}>
              {z}×
            </button>
          ))}
        </span>
        {data.dropped > 0 && (
          <span className="ft-dropped" title={`Only the first ${data.cap} hits of a fight are kept`}>
            {data.dropped.toLocaleString("en-US")} later hits not drawn
          </span>
        )}
      </div>
      <div className="ft-scroll">
        <div className="ft-lanes" style={{ width: `${100 * zoom}%` }}>
          <div className="ft-axis" aria-hidden="true">
            {grid.map((s) => (
              <span key={s} className="ft-grid" style={{ left: pct(s) }}>
                <b>{s >= 60 ? `${Math.floor(s / 60)}m${s % 60 ? `${s % 60}s` : ""}` : `${s}s`}</b>
              </span>
            ))}
          </div>
          {lanes.map((lane) => (
            <div className="ft-lane" key={lane.key} data-side={lane.side}>
              <div className="ft-label" title={`${lane.label}: ${lane.rows.length} rows, ${lane.total.toLocaleString("en-US")} total`}>
                <span>{lane.label}</span>
                <em>{lane.total.toLocaleString("en-US")}</em>
              </div>
              <div className="ft-track">
                {grid.map((s) => (
                  <span key={s} className="ft-grid" style={{ left: pct(s) }} aria-hidden="true" />
                ))}
                {lane.rows.map((h, i) => {
                  const [t, , , amount, , tag] = h;
                  const zero = amount === 0;
                  const tagKind =
                    tag === "miss" ? "miss"
                    : tag === "resist" ? "resist"
                    : zero && lane.side === "in" ? "avoid"
                    : /Critical/.test(tag) ? "crit"
                    : undefined;
                  // Height carries magnitude within the lane; a zero row
                  // (miss, resist, avoided swing) is drawn hollow at full
                  // height so it is never mistaken for a small hit.
                  const h_ = zero ? 100 : Math.max(18, Math.round((amount / lane.max) * 100));
                  return (
                    <i key={i} className="ft-mark" data-side={lane.side} data-tag={tagKind}
                       style={{ left: pct(t), height: `${h_}%` }} title={describe(h)} />
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

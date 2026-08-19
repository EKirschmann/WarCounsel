"use client";

/* Tracked triggers — the alert rules table.
 *
 * Rules used to live only in data/tracked_rules.json, hand-edited, which
 * made a feature nobody could find look like a feature nobody had. This is
 * the same table with somewhere to click.
 *
 * The KIND list comes from backend/alerts.py over the API (as the overlay
 * switchboard does), so a kind added there appears here without a second
 * edit — that mismatch is exactly how "spell interrupted" stayed
 * unreachable while the event was already parsed.
 *
 * Matching is SUBSTRING, never regex, and deliberately so: per EQBuddy,
 * nobody should have to escape a mob's apostrophe to watch for it. Each
 * kind therefore says what its pattern is compared against, since a rule
 * that never matches is indistinguishable from a quiet night.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiSend } from "@/lib/api";

type Rule = {
  kind: string;
  pattern: string;
  enabled: boolean;
  sound: boolean;
};
type KindDef = { kind: string; matches: string };
type Starter = Rule & { group: string; label: string; why: string };
type Payload = {
  file: string;
  rules: Rule[];
  kinds: KindDef[];
  starter: Starter[];
};

export function TriggerSettings() {
  const [data, setData] = useState<Payload | null>(null);
  const [rules, setRules] = useState<Rule[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [browsing, setBrowsing] = useState(false);
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    apiGet<Payload>("/api/tracked-rules")
      .then((d) => {
        setData(d);
        setRules(d.rules);
      })
      .catch((e) => setError(String(e)));
    return () => {
      if (savedTimer.current) clearTimeout(savedTimer.current);
    };
  }, []);

  const push = useCallback(async (next: Rule[]) => {
    // Blank patterns are dropped by the backend, so a half-typed new row
    // would vanish under the cursor. Keep it on screen and send the rest.
    const sendable = next.filter((r) => r.pattern.trim());
    try {
      await apiSend<{ rules: Rule[] }>("/api/tracked-rules", {
        rules: sendable,
      });
      setError(null);
      setSaved(true);
      if (savedTimer.current) clearTimeout(savedTimer.current);
      savedTimer.current = setTimeout(() => setSaved(false), 1600);
    } catch (e) {
      setError(String(e).replace(/^Error:\s*/, ""));
    }
  }, []);

  // Checkboxes, the kind dropdown and delete save immediately; the pattern
  // box saves on blur instead, or every keystroke would be a POST.
  const edit = (i: number, patch: Partial<Rule>, save = true) => {
    setRules((prev) => {
      const next = prev.map((r, n) => (n === i ? { ...r, ...patch } : r));
      if (save) void push(next);
      return next;
    });
  };

  const add = () => setRules((prev) => [
    ...prev,
    { kind: "loot", pattern: "", enabled: true, sound: true },
  ]);

  // Copied in DISABLED, exactly as it ships: a starter rule is a suggestion
  // to look at, never something that starts firing because the panel was
  // opened. Switching it on is the deliberate act.
  const addStarter = (st: Starter) =>
    setRules((prev) => {
      const next = [
        ...prev,
        { kind: st.kind, pattern: st.pattern, enabled: false, sound: st.sound },
      ];
      void push(next);
      return next;
    });

  const remove = (i: number) => {
    setRules((prev) => {
      const next = prev.filter((_, n) => n !== i);
      void push(next);
      return next;
    });
  };

  if (error && !data) return <p className="set-note" data-ok="0">{error}</p>;
  if (!data) return <p className="set-note">Loading…</p>;

  const helpFor = (kind: string) =>
    data.kinds.find((k) => k.kind === kind)?.matches ?? "";

  // Grouped in the order the backend lists them, so the catalogue reads
  // the way it was written rather than alphabetically.
  const groups: [string, Starter[]][] = [];
  for (const st of data.starter ?? []) {
    const row = groups.find(([g]) => g === st.group);
    if (row) row[1].push(st);
    else groups.push([st.group, [st]]);
  }

  return (
    <>
      <ul className="ov-list">
        {rules.map((r, i) => (
          <li
            key={i}
            className="ov-item trg-item"
            data-on={r.enabled ? "1" : "0"}
          >
            <div className="trg-row">
              <label className="ov-check" title="Watch for this">
                <input
                  type="checkbox"
                  checked={r.enabled}
                  onChange={() => edit(i, { enabled: !r.enabled })}
                  aria-label={`Enable ${r.kind} trigger`}
                />
              </label>
              <select
                value={r.kind}
                onChange={(e) => edit(i, { kind: e.target.value })}
                aria-label="Trigger kind"
              >
                {data.kinds.map((k) => (
                  <option key={k.kind} value={k.kind}>{k.kind}</option>
                ))}
              </select>
              <input
                value={r.pattern}
                spellCheck={false}
                autoComplete="off"
                placeholder={r.kind === "bighit" ? "800" : "text to watch for"}
                onChange={(e) => edit(i, { pattern: e.target.value }, false)}
                onBlur={() => push(rules)}
                aria-label="Trigger pattern"
              />
              <label className="ov-check" title="Play the chime too">
                <input
                  type="checkbox"
                  checked={r.sound}
                  onChange={() => edit(i, { sound: !r.sound })}
                  aria-label="Play a sound"
                />
                <span className="ov-label">♪</span>
              </label>
              <button
                type="button"
                className="ov-more"
                onClick={() => remove(i)}
                aria-label={`Delete ${r.kind} trigger`}
                title="Delete"
              >
                ×
              </button>
            </div>
            <span className="ov-hint trg-hint">
              {r.pattern.trim() === "*"
                ? `every ${r.kind} — ${helpFor(r.kind)}`
                : helpFor(r.kind)}
            </span>
          </li>
        ))}
      </ul>

      <div className="set-row trg-foot">
        <button type="button" onClick={add}>+ Add trigger</button>
        <button type="button" onClick={() => setBrowsing((b) => !b)}>
          {browsing ? "Hide starter set" : "Starter set…"}
        </button>
        <span className="set-note" data-ok={saved ? "1" : undefined}>
          {saved ? "Saved ✓" : ""}
        </span>
      </div>

      {browsing && (
        <div className="trg-starter">
          <p className="set-note">
            Common watches, added switched <strong>off</strong> so nothing
            starts firing on its own. Edit the pattern afterwards to narrow
            it — every one of these is a starting point, not a setting.
          </p>
          {groups.map(([group, rows]) => (
            <div key={group} className="trg-starter-group">
              <h4>{group}</h4>
              <ul className="ov-list">
                {rows.map((st) => {
                  const already = rules.some(
                    (r) => r.kind === st.kind && r.pattern === st.pattern,
                  );
                  return (
                    <li key={st.kind + st.pattern} className="ov-item trg-item">
                      <div className="trg-row">
                        <button
                          type="button"
                          onClick={() => addStarter(st)}
                          disabled={already}
                          title={
                            already ? "Already in your list" : `Add ${st.kind} ${st.pattern}`
                          }
                        >
                          {already ? "Added" : "Add"}
                        </button>
                        <strong>{st.label}</strong>
                        <code>
                          {st.kind} {st.pattern}
                        </code>
                      </div>
                      <span className="ov-hint trg-hint">{st.why}</span>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      )}
      {error && <p className="set-note" data-ok="0">{error}</p>}
      <p className="set-note">
        Matches are plain text, not patterns — no escaping, and{" "}
        <code>*</code> catches every one of that kind. A match raises the
        overlay banner (and the chime when ♪ is on), at most once every five
        seconds per trigger. The overlay has to be running to show it.
      </p>
    </>
  );
}

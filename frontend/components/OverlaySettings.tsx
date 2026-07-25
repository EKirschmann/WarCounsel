"use client";

/* What the overlay shows — the section/field switchboard.
 *
 * Saves on every click rather than waiting for the modal's Save button, on
 * purpose: the whole point of tuning an overlay is watching it change while
 * you tune it. A running overlay re-reads the file on its next repaint, so
 * the effect is visible in about half a second.
 *
 * The section and field lists are NOT declared here — they come from
 * backend/overlay_prefs.py over the API, so the switchboard cannot drift
 * out of step with what the overlay actually paints.
 */

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiSend } from "@/lib/api";

type FieldDef = { label: string; hint: string };
type SectionDef = { label: string; hint: string; fields: Record<string, FieldDef> };
type Prefs = {
  sections: Record<string, boolean>;
  fields: Record<string, Record<string, boolean>>;
};
type PresetDef = { label: string; hint: string };
type Payload = {
  prefs: Prefs;
  schema: Record<string, SectionDef>;
  presets: Record<string, PresetDef>;
  preset: string | null;
};

export function OverlaySettings() {
  const [data, setData] = useState<Payload | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiGet<Payload>("/api/overlay/prefs")
      .then(setData)
      .catch((e) => setError(String(e)));
  }, []);

  const push = useCallback(
    async (body: Record<string, unknown>) => {
      try {
        const r = await apiSend<{ prefs: Prefs; preset: string | null }>(
          "/api/overlay/prefs",
          body,
        );
        setData((d) => (d ? { ...d, prefs: r.prefs, preset: r.preset } : d));
        setError(null);
      } catch (e) {
        setError(String(e).replace(/^Error:\s*/, ""));
      }
    },
    [],
  );

  if (error && !data) return <p className="set-note" data-ok="0">{error}</p>;
  if (!data) return <p className="set-note">Loading…</p>;

  const { prefs, schema, presets } = data;

  const toggleSection = (key: string) =>
    push({
      ...prefs,
      sections: { ...prefs.sections, [key]: !prefs.sections[key] },
    });

  const toggleField = (key: string, field: string) =>
    push({
      ...prefs,
      fields: {
        ...prefs.fields,
        [key]: { ...prefs.fields[key], [field]: !prefs.fields[key][field] },
      },
    });

  return (
    <>
      <div className="ov-presets" role="group" aria-label="Overlay presets">
        {Object.entries(presets).map(([id, p]) => (
          <button
            key={id}
            type="button"
            className="ov-preset"
            data-on={data.preset === id ? "1" : "0"}
            title={p.hint}
            onClick={() => push({ preset: id })}
          >
            {p.label}
          </button>
        ))}
        <span className="ov-preset-state">
          {data.preset ? "" : "Custom"}
        </span>
      </div>

      <ul className="ov-list">
        {Object.entries(schema).map(([key, sec]) => {
          const secOn = prefs.sections[key];
          const expanded = open === key;
          const fields = Object.entries(sec.fields);
          const kept = fields.filter(([f]) => prefs.fields[key]?.[f]).length;
          return (
            <li key={key} className="ov-item" data-on={secOn ? "1" : "0"}>
              <div className="ov-row">
                <label className="ov-check">
                  <input
                    type="checkbox"
                    checked={secOn}
                    onChange={() => toggleSection(key)}
                  />
                  <span className="ov-label">{sec.label}</span>
                </label>
                <span className="ov-hint">{sec.hint}</span>
                <button
                  type="button"
                  className="ov-more"
                  aria-expanded={expanded}
                  aria-label={`${sec.label} details`}
                  onClick={() => setOpen(expanded ? null : key)}
                >
                  {kept}/{fields.length} {expanded ? "▾" : "▸"}
                </button>
              </div>
              {expanded && (
                <ul className="ov-fields">
                  {fields.map(([f, def]) => (
                    <li key={f}>
                      <label className="ov-check">
                        <input
                          type="checkbox"
                          checked={!!prefs.fields[key]?.[f]}
                          disabled={!secOn}
                          onChange={() => toggleField(key, f)}
                        />
                        <span className="ov-label">{def.label}</span>
                      </label>
                      {def.hint && <span className="ov-hint">{def.hint}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>

      {error && <p className="set-note" data-ok="0">{error}</p>}
      <p className="set-note">
        Applies to a running overlay within half a second — no need to save or
        relaunch it.
      </p>
    </>
  );
}

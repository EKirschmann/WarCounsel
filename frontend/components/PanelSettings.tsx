"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiSend } from "@/lib/api";
import { panelPrefsChanged } from "@/lib/panelPrefs";

/* What each web panel shows.
 *
 * Separate from the overlay's switchboard on purpose: a 42px strip and a
 * 340px column answer different questions, and one shared set of toggles
 * would mean hiding deaths mid-fight also hides them when you sit down to
 * plan. Same SHAPE as the overlay's, so there is one pattern to learn.
 *
 * Renders from the schema the backend serves rather than a hardcoded list,
 * so the switches cannot drift from what the panels draw. Saves on click,
 * merged onto what is stored — an omitted key is left alone rather than
 * springing back on. */

interface Field {
  label: string;
  hint?: string;
}
interface Section {
  label: string;
  hint?: string;
  fields: Record<string, Field>;
}
interface Preset {
  label: string;
  hint?: string;
}
interface Prefs {
  sections: Record<string, boolean>;
  fields: Record<string, Record<string, boolean>>;
}
interface Schema {
  sections: Record<string, Section>;
  presets: Record<string, Preset>;
  prefs: Prefs;
}

export function PanelSettings({ active }: { active: string }) {
  const [data, setData] = useState<Schema | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await apiGet<Schema>("/api/panel/prefs"));
    } catch {
      setData(null);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const push = async (body: unknown) => {
    setBusy(true);
    try {
      const r = await apiSend<{ prefs: Prefs }>("/api/panel/prefs", body);
      setData((d) => (d ? { ...d, prefs: r.prefs } : d));
      // The panels are mounted behind this modal -- tell them now rather
      // than making the change wait for a reload.
      panelPrefsChanged(r.prefs);
    } catch {
      /* backend offline — the panel keeps what it last showed */
    } finally {
      setBusy(false);
    }
  };

  if (!data) return <p className="set-note">Panel settings are unavailable.</p>;
  const sec = data.sections[active];
  if (!sec) return null;
  const on = data.prefs.sections[active] !== false;
  const fields = data.prefs.fields[active] ?? {};

  return (
    <div className="pp">
      <label className="pp-section">
        <input
          type="checkbox"
          checked={on}
          disabled={busy}
          onChange={() => push({ sections: { [active]: !on } })}
        />
        Show this panel
      </label>
      {/* The modal's Save button covers the game folder and the API keys.
          These land the moment you click them, and saying so is cheaper
          than a second person wondering why Cancel did not undo it. */}
      <p className="pp-saved">Changes here apply straight away.</p>

      <div className="pp-fields" data-off={on ? undefined : "1"}>
        {Object.entries(sec.fields).map(([key, f]) => (
          <label key={key} className="pp-field">
            <input
              type="checkbox"
              checked={fields[key] !== false}
              disabled={busy || !on}
              onChange={() =>
                push({ fields: { [active]: { [key]: fields[key] === false } } })
              }
            />
            <span>
              {f.label}
              {f.hint ? <span className="pp-hint"> — {f.hint}</span> : null}
            </span>
          </label>
        ))}
      </div>
    </div>
  );
}

/** Preset buttons, shown once under General rather than repeated per panel. */
export function PanelPresets() {
  const [presets, setPresets] = useState<Record<string, Preset> | null>(null);
  useEffect(() => {
    apiGet<Schema>("/api/panel/prefs")
      .then((d) => setPresets(d.presets))
      .catch(() => setPresets(null));
  }, []);
  if (!presets) return null;
  return (
    <div className="pp-presets">
      {Object.entries(presets).map(([key, p]) => (
        <button
          key={key}
          type="button"
          title={p.hint}
          onClick={() =>
            void apiSend<{ prefs: Prefs }>("/api/panel/prefs", { preset: key })
              .then((r) => panelPrefsChanged(r.prefs))
              .catch(() => undefined)
          }
        >
          {p.label}
        </button>
      ))}
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";

/** What each panel is allowed to show.
 *
 * Fetched once and refreshed when the Settings modal reports a change, so a
 * toggle takes effect without a reload. Everything defaults to VISIBLE:
 * until the prefs arrive — and if they never do, because the backend is
 * unreachable — panels render exactly as they did before this existed. A
 * settings feature that blanks the UI when it cannot load its own config is
 * worse than no settings feature. */

export interface PanelPrefs {
  sections: Record<string, boolean>;
  fields: Record<string, Record<string, boolean>>;
}

const EVENT = "eql:panel-prefs";
let cache: PanelPrefs | null = null;

/** Settings calls this after a save so open panels re-read immediately. */
export function panelPrefsChanged(next?: PanelPrefs) {
  cache = next ?? null;
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(EVENT, { detail: next }));
  }
}

export function usePanelPrefs() {
  const [prefs, setPrefs] = useState<PanelPrefs | null>(cache);

  useEffect(() => {
    let alive = true;
    const pull = () =>
      apiGet<{ prefs: PanelPrefs }>("/api/panel/prefs")
        .then((d) => {
          if (!alive) return;
          cache = d.prefs;
          setPrefs(d.prefs);
        })
        .catch(() => {
          /* leave everything visible */
        });
    if (!cache) pull();
    const onChange = (e: Event) => {
      const next = (e as CustomEvent).detail as PanelPrefs | undefined;
      if (next) setPrefs(next);
      else pull();
    };
    window.addEventListener(EVENT, onChange);
    return () => {
      alive = false;
      window.removeEventListener(EVENT, onChange);
    };
  }, []);

  /** Is this field switched on? Unknown or unloaded means yes. */
  const show = (section: string, field?: string): boolean => {
    if (!prefs) return true;
    if (prefs.sections[section] === false) return false;
    if (!field) return true;
    return prefs.fields[section]?.[field] !== false;
  };
  return { prefs, show };
}

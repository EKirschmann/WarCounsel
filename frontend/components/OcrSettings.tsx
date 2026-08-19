"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiSend } from "@/lib/api";

/* Screen-OCR setup, both regions.
 *
 * These controls used to sit at the bottom of the Atlas panel, which made
 * sense while there was one of them and it fed the map. Two regions with a
 * toggle, a placement button and a test read each is a setup screen, and it
 * belongs with the other setup. The Atlas keeps a read-only status line —
 * knowing whether position tracking is alive is worth having in front of
 * the map it moves, and that is not a control.
 *
 * Nothing here polls unless the modal is open, which is also an improvement:
 * the status endpoint was being hit every 4s for the whole session. */

interface OcrStatus {
  deps_ok: boolean;
  deps_error?: string | null;
  packaged?: boolean;
  python?: string;
  enabled: boolean;
  game_running: boolean;
  last_ok: string | null;
  last_text?: string | null;
  error: string | null;
  stats_enabled?: boolean;
  stats_seen?: string | null;
  stats_yellow?: number | null;
  stats_yellow_min?: number;
  stats_interval?: number;
  stats?: Record<string, number>;
}

export function OcrSettings() {
  const [ocr, setOcr] = useState<OcrStatus | null>(null);
  const [posMsg, setPosMsg] = useState<string | null>(null);
  const [statsMsg, setStatsMsg] = useState<string | null>(null);
  const [groupMsg, setGroupMsg] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setOcr(await apiGet<OcrStatus>("/api/ocr/status"));
    } catch {
      setOcr(null);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 4000);
    return () => clearInterval(id);
  }, [refresh]);

  const toggle = async (which: "position" | "stats") => {
    const path = which === "stats" ? "/api/ocr/stats-enabled" : "/api/ocr/enabled";
    const now = which === "stats" ? ocr?.stats_enabled : ocr?.enabled;
    try {
      await apiSend(path, { enabled: !now });
      await refresh();
    } catch {
      /* backend offline */
    }
  };

  const place = async (which: "position" | "stats" | "group") => {
    try {
      await apiSend("/api/ocr/overlay", which === "position" ? {} : { target: which });
    } catch {
      /* backend offline */
    }
  };

  const testPosition = async () => {
    setPosMsg("reading…");
    try {
      const r = await apiGet<{
        text: string | null;
        parsed: { x: number; y: number; z: number } | null;
        error?: string;
      }>("/api/ocr/preview");
      if (r.error) setPosMsg(r.error);
      else if (r.parsed) setPosMsg(`Read X ${r.parsed.x} · Y ${r.parsed.y} · Z ${r.parsed.z}`);
      else if (r.text) setPosMsg(`Box sees "${r.text.slice(0, 60)}" — that is not an X/Y/Z readout`);
      else setPosMsg("Box sees nothing — open the in-game map so the coordinates show");
    } catch {
      setPosMsg("Backend offline");
    }
  };

  const testGroup = async () => {
    setGroupMsg("reading…");
    try {
      const r = await apiGet<{ text?: string; error?: string }>("/api/ocr/group-preview");
      setGroupMsg(r.error ? r.error : r.text ? `Box sees: ${r.text}` : "Box sees nothing");
    } catch {
      setGroupMsg("Backend offline");
    }
  };

  const testStats = async () => {
    setStatsMsg("reading…");
    try {
      const r = await apiGet<{
        gated?: boolean;
        yellow?: number;
        yellow_min?: number;
        hint?: string;
        error?: string;
        parsed?: Record<string, number>;
      }>("/api/ocr/stats-preview");
      if (r.error) {
        setStatsMsg(r.error);
      } else if (r.gated) {
        // The measured ratio IS the diagnosis: a closed window and a badly
        // placed box both produce nothing, and only this number tells them
        // apart.
        setStatsMsg(`${r.hint} (yellow ${r.yellow}, needs ${r.yellow_min})`);
      } else {
        const p = r.parsed ?? {};
        const n = Object.keys(p).length;
        setStatsMsg(
          n
            ? `Read ${n} values — ${Object.entries(p)
                .slice(0, 5)
                .map(([k, v]) => `${k} ${v}`)
                .join(", ")}${n > 5 ? "…" : ""}`
            : "Box is on the panel but nothing parsed — cover the labels and their numbers together",
        );
      }
    } catch {
      setStatsMsg("Backend offline");
    }
  };

  // Two very different failures used to share one message — and the advice
  // it gave ("pip install…") cannot work in the packaged build at all,
  // which is where the person least likely to have Python is standing.
  if (ocr && !ocr.deps_ok && ocr.packaged) {
    return (
      <p className="set-note" data-ok="0">
        Screen reading is <strong>not in this download</strong>. Its image
        packages weigh about 200&nbsp;MB — five times the rest of the app —
        so they ship as a separate build rather than slowing every launch
        for everyone. Grab{" "}
        <strong>WarCounsel-OCR.zip</strong> from the{" "}
        <a
          href="https://github.com/EKirschmann/WarCounsel/releases/latest"
          target="_blank"
          rel="noreferrer"
        >
          releases page
        </a>
        , unzip it anywhere and run the WarCounsel.exe inside. It is the
        same app with screen reading added — your <code>data</code> folder
        and settings carry over.
      </p>
    );
  }

  if (ocr && !ocr.deps_ok) {
    return (
      <p className="set-note" data-ok="0">
        Screen reading needs its optional packages. Install them into{" "}
        <strong>the Python that runs WarCounsel</strong> — if plain{" "}
        <code>pip</code> says they are already there, it belongs to a
        different Python than this one:
        <br />
        <code>
          {ocr.python ? `"${ocr.python}" -m pip` : "python -m pip"} install -r
          requirements.txt
        </code>
        {ocr.deps_error ? (
          <>
            <br />
            <span style={{ opacity: 0.75 }}>({ocr.deps_error})</span>
          </>
        ) : null}
      </p>
    );
  }

  return (
    <div className="ocr-set">
      {/* The 2026-08-18 patch turned UI Scaling into eleven steps with
          0.25 increments and added Cursor Scaling. Every region below is
          FIXED screen pixels, so a scale change moves what is under them
          and reading silently returns the wrong thing -- there is no
          error to show, which is exactly why this has to be said up
          front rather than diagnosed after. */}
      <p className="set-note">
        Boxes are screen positions. If you change{" "}
        <strong>Options ▸ Interface ▸ UI Scaling</strong> or your Windows
        display scaling, the game moves underneath them and reads go wrong
        with no error — place the boxes again after either change.
      </p>
      <div className="ocr-set-row">
        <div className="ocr-set-head">
          <label className="ocr-toggle">
            <input
              type="checkbox"
              checked={ocr?.enabled ?? false}
              onChange={() => toggle("position")}
              disabled={!ocr}
            />
            Position
          </label>
          <span className="ocr-set-state" data-live={!!(ocr?.enabled && ocr?.last_ok && !ocr?.error)}>
            {!ocr
              ? "backend offline"
              : !ocr.game_running
                ? "game not running"
                : !ocr.enabled
                  ? "off"
                  : ocr.error
                    ? ocr.error
                    : ocr.last_ok
                      ? `reading, last ${ocr.last_ok}`
                      : "searching"}
          </span>
        </div>
        <p className="set-note">
          Reads your coordinates off the in-game map so the Atlas can follow you between{" "}
          <code>/loc</code> calls.
        </p>
        <div className="ocr-set-actions">
          <button type="button" onClick={() => place("position")} disabled={!ocr}>
            Place box
          </button>
          <button type="button" onClick={testPosition} disabled={!ocr}>
            Test read
          </button>
        </div>
        {posMsg && <p className="ocr-preview">{posMsg}</p>}
      </div>

      <div className="ocr-set-row">
        <div className="ocr-set-head">
          <label className="ocr-toggle">
            <input
              type="checkbox"
              checked={ocr?.stats_enabled ?? false}
              onChange={() => toggle("stats")}
              disabled={!ocr}
            />
            Character stats
          </label>
          <span className="ocr-set-state" data-live={!!(ocr?.stats_enabled && ocr?.stats_seen)}>
            {!ocr
              ? "backend offline"
              : !ocr.stats_enabled
                ? "off"
                : ocr.stats_seen
                  ? `read at ${ocr.stats_seen}`
                  : "waiting for the Equipment tab"}
          </span>
        </div>
        <p className="set-note">
          Reads HP, mana, AC and your attributes from the Inventory window — including the{" "}
          <code>196/510</code> caps, so gear advice stops recommending stats that can no longer
          rise. Only reads while the Inventory window is open with the Equipment tab focused, once
          every {ocr?.stats_interval ?? 15}s.
        </p>
        <div className="ocr-set-actions">
          <button type="button" onClick={() => place("stats")} disabled={!ocr}>
            Place box
          </button>
          <button type="button" onClick={testStats} disabled={!ocr}>
            Test read
          </button>
        </div>
        {statsMsg && <p className="ocr-preview">{statsMsg}</p>}
      </div>

      <div className="ocr-set-row">
        <div className="ocr-set-head">
          <span className="ocr-toggle">Group window</span>
          <span className="ocr-set-state">calibrating</span>
        </div>
        <p className="set-note">
          The group box is the only place the game states who is actually with you
          — the log never does, and it lists players without their pets. Place the
          box and send the read for both states (alone, and in a group) so the
          reader can be written against what your client really shows.
        </p>
        <div className="ocr-set-actions">
          <button type="button" onClick={() => place("group")} disabled={!ocr}>
            Place box
          </button>
          <button type="button" onClick={testGroup} disabled={!ocr}>
            Test read
          </button>
        </div>
        {groupMsg && <p className="ocr-preview">{groupMsg}</p>}
      </div>
    </div>
  );
}

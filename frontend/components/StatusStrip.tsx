"use client";

import type { Snapshot } from "@/lib/types";

/**
 * Why the numbers are not moving — the one strip no toggle can hide.
 *
 * Two problems put this here. Log health rode the snapshot for both
 * surfaces, but only the overlay ever drew it, so the web HUD froze in
 * silence with a "Linked" badge confirming all was well — the badge reports
 * the browser-to-backend socket, and the link that actually breaks is
 * backend-to-log-file. And `sync_hints` rendered only inside CharacterPanel,
 * which Settings can switch off, taking "logging is OFF in-game" with it.
 *
 * So this sits between the header and the grid, outside every panel pref.
 * SILENCE WHILE IDLING IS NORMAL and must stay that way: a quiet log is a
 * quiet night until it has been quiet long enough to be odd. Only two
 * states are red — a feed that has never moved, and a newer log belonging
 * to somebody else.
 */

interface CharacterEntry {
  name: string;
  server: string | null;
  file: string;
}

interface Row {
  key: string;
  tone: "alert" | "caution";
  text: string;
  /** in-game command to type, rendered as the fix */
  command?: string;
  action?: { label: string; run: () => void };
}

/** Mirrors backend/overlay.py `_log_warning` — same precedence, same 10
 *  minute threshold. Two surfaces, one rule; if you change it, change both. */
const QUIET_LOG_S = 600;

export function StatusStrip({
  snap,
  chars,
  onSwitch,
}: {
  snap: Snapshot | null;
  chars: CharacterEntry[];
  onSwitch: (file: string) => void;
}) {
  if (!snap) return null;

  const rows: Row[] = [];

  // A `/log on` hint means the app has nothing to read at all, so it belongs
  // here whether or not the backend marked it urgent. Every other hint is
  // strip-worthy only when it is.
  const hints = snap.sync_hints.filter(
    (h) => h.urgent || h.command === "/log on",
  );
  const logHintShown = hints.some((h) => h.command === "/log on");

  const other = snap.newer_log;
  if (other) {
    const match = chars.find(
      (c) => c.name.toLowerCase() === other.toLowerCase(),
    );
    rows.push({
      key: "newer-log",
      tone: "alert",
      text: `${other}'s log is newer — these numbers are still ${snap.name}'s.`,
      action: match
        ? { label: `Switch to ${other}`, run: () => onSwitch(match.file) }
        : undefined,
    });
  }

  // When we know the CAUSE, do not also print the symptom: a log that went
  // quiet because they are playing somebody else needs one row, not two.
  const causeKnown = Boolean(other) || logHintShown;

  if (snap.log_seen_growth === false && !causeKnown) {
    rows.push({
      key: "no-growth",
      tone: "alert",
      text: "No log activity since WarCounsel started.",
      command: "/log on",
    });
  } else if (
    typeof snap.log_stale_s === "number" &&
    snap.log_stale_s > QUIET_LOG_S &&
    !causeKnown
  ) {
    rows.push({
      key: "quiet",
      tone: "caution",
      text: `Your log has been quiet for ${Math.floor(snap.log_stale_s / 60)} minutes.`,
    });
  }

  for (const h of hints) {
    rows.push({
      key: h.command + h.reason,
      tone: "alert",
      text: h.reason.replace(/[.\s]+$/, "") + ".",
      command: h.command,
    });
  }

  if (rows.length === 0) return null;

  return (
    <div className="status-strip" role="status" aria-live="polite">
      {rows.map((r) => (
        <p key={r.key} className="status-row" data-tone={r.tone}>
          <span className="status-rune" aria-hidden />
          <span className="status-text">
            {r.text}
            {r.command && (
              <>
                {" Type "}
                <code>{r.command}</code>
                {" in-game."}
              </>
            )}
          </span>
          {r.action && (
            <button type="button" className="status-action" onClick={r.action.run}>
              {r.action.label}
            </button>
          )}
        </p>
      ))}
    </div>
  );
}

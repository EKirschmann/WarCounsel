"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { SettingsModal } from "@/components/SettingsModal";
import { apiGet, apiSend } from "@/lib/api";
import type { LedgerRow, Snapshot, WsMessage } from "@/lib/types";
import { useWebSocket } from "@/hooks/useWebSocket";
import { APP_VERSION } from "@/lib/version";
import { AdvisorPanel } from "@/components/AdvisorPanel";
import { QuestPanel } from "@/components/QuestPanel";
import { ProgressionPanel } from "@/components/ProgressionPanel";
import { AtlasPanel } from "@/components/AtlasPanel";
import { CharacterPanel } from "@/components/CharacterPanel";
import { EncounterPanel } from "@/components/EncounterPanel";
import { WarLedger } from "@/components/WarLedger";
import { StatusStrip } from "@/components/StatusStrip";
import { usePanelPrefs } from "@/lib/panelPrefs";

const MAX_ROWS = 300;

type CenterTab = "atlas" | "advisor" | "quests" | "progression";

interface CharacterEntry {
  name: string;
  server: string | null;
  file: string;
}

export default function Home() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [overlayOn, setOverlayOn] = useState(false);
  const [updateMsg, setUpdateMsg] = useState<{ text: string; newer: boolean } | null>(null);
  const [updateAvail, setUpdateAvail] = useState<string | null>(null);

  // quiet periodic check: on load and every 6 hours (GitHub is fine with it)
  useEffect(() => {
    const check = () =>
      apiGet<{ latest: string | null; update_available?: boolean }>("/api/update-check")
        .then((r) => setUpdateAvail(r.update_available && r.latest ? r.latest : null))
        .catch(() => {});
    check();
    const id = setInterval(check, 6 * 60 * 60 * 1000);
    return () => clearInterval(id);
  }, []);

  const runUpdate = async () => {
    try {
      const r = await apiSend<{ note: string }>("/api/update/run", {});
      setUpdateMsg({ text: r.note, newer: true });
    } catch {
      setUpdateMsg({ text: "couldn't launch the updater — run update_companion.bat by hand", newer: false });
    }
  };

  const checkUpdates = async () => {
    setUpdateMsg({ text: "checking…", newer: false });
    try {
      const r = await apiGet<{ current: string; latest: string | null; update_available?: boolean; error?: string }>(
        "/api/update-check",
      );
      if (r.error) setUpdateMsg({ text: r.error, newer: false });
      else if (r.update_available)
        setUpdateMsg({ text: `v${r.latest} available — close the app and run update_companion.bat`, newer: true });
      else setUpdateMsg({ text: "up to date", newer: false });
    } catch {
      setUpdateMsg({ text: "backend offline", newer: false });
    }
    setTimeout(() => setUpdateMsg(null), 10000);
  };

  useEffect(() => {
    apiGet<{ running: boolean }>("/api/overlay")
      .then((r) => setOverlayOn(r.running))
      .catch(() => {});
  }, []);
  const [rows, setRows] = useState<LedgerRow[]>([]);
  const [centerTab, setCenterTab] = useState<CenterTab>("atlas");
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const [centerOpen, setCenterOpen] = useState(true);

  useEffect(() => {
    setCenterOpen(localStorage.getItem("eql.centerOpen") !== "0");
  }, []);
  const toggleCenter = () => {
    setCenterOpen((v) => {
      localStorage.setItem("eql.centerOpen", v ? "0" : "1");
      return !v;
    });
  };

  // Monotonic id stamped on receipt — stable React keys for ledger rows.
  const idRef = useRef(0);
  const stamp = useCallback(
    (rs: LedgerRow[]) => rs.map((r) => ({ ...r, _id: ++idRef.current })),
    [],
  );

  const onMessage = useCallback(
    (msg: WsMessage) => {
      if (msg.type === "hello" || msg.type === "state") {
        setSnap(msg.data);
      } else if (msg.type === "events") {
        // one batched frame per ~150ms instead of one render per swing
        setRows((prev) => [...prev, ...stamp(msg.data)].slice(-MAX_ROWS));
      } else if (msg.type === "event") {
        setRows((prev) => [...prev, ...stamp([msg.data])].slice(-MAX_ROWS));
      }
    },
    [stamp],
  );

  const status = useWebSocket(onMessage);
  const [chars, setChars] = useState<CharacterEntry[]>([]);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { show } = usePanelPrefs();
  // Collapsed side panels shrink to a 42px strip. Tracked here, not only in
  // CSS, because the number of tracks depends on which panels Settings left
  // switched on -- the two facts have to be resolved together.
  const [collapsed, setCollapsed] = useState({ ledger: false, enc: false });
  useEffect(() => {
    const read = () =>
      setCollapsed({
        ledger: localStorage.getItem("eql.ledgerOpen") === "0",
        enc: localStorage.getItem("eql.encOpen") === "0",
      });
    read();
    window.addEventListener("eql:collapse", read);
    return () => window.removeEventListener("eql:collapse", read);
  }, []);
  const showVitals = show("vitals");
  const showLedger = show("ledger");
  const showEnc = show("encounter");
  const showQuests = show("quests");
  const showProgression = show("progression");
  const centerTabs: { id: CenterTab; label: string }[] = [
    { id: "atlas", label: "Atlas" },
    { id: "advisor", label: "Advisor" },
    ...(showQuests ? [{ id: "quests" as CenterTab, label: "Quests" }] : []),
    ...(showProgression ? [{ id: "progression" as CenterTab, label: "Progression" }] : []),
  ];
  // Settings can switch off the tab that is currently open, which used to
  // leave the row with nothing marked selected while Advisor rendered.
  const activeTab: CenterTab = centerTabs.some((x) => x.id === centerTab)
    ? centerTab
    : "advisor";
  // Arrows move focus, Enter/Space selects — the MANUAL activation half of
  // the ARIA tabs pattern, because opening Atlas fetches zone geometry and
  // arrowing across the row must not fire four panel loads on the way past.
  const onTabKey = (e: React.KeyboardEvent, i: number) => {
    const n = centerTabs.length;
    const next =
      e.key === "ArrowRight" ? (i + 1) % n
      : e.key === "ArrowLeft" ? (i - 1 + n) % n
      : e.key === "Home" ? 0
      : e.key === "End" ? n - 1
      : -1;
    if (next < 0) return;
    e.preventDefault();
    tabRefs.current[next]?.focus();
  };
  // Only set when something is OFF, so the default layout stays exactly
  // the stylesheet's — including its media queries, which a blanket
  // inline override would have flattened.
  // The single description of this grid, because the widths depend on three
  // things at once: which panels Settings left on, which are collapsed to a
  // 42px strip, and the viewport. It used to be four CSS combinations that
  // each assumed all four panels existed.
  //
  // A collapsed OR hidden side panel hands its width to the OTHER side
  // panel, not to the centre — the encounter breakdown is what people widen
  // the ledger away for, and it reflows into columns once it has the room.
  const ledgerSlim = !showLedger || collapsed.ledger;
  const encSlim = !showEnc || collapsed.enc;
  const cols = (vitals: string, centre: string, ledger: string, enc: string) =>
    [showVitals && vitals, centre, showLedger && ledger, showEnc && enc]
      .filter(Boolean)
      .join(" ");
  const hudCols = {
    "--hud-cols": cols(
      "320px",
      "minmax(380px, 1fr)",
      collapsed.ledger ? "42px" : encSlim ? "minmax(380px, 1fr)" : "380px",
      collapsed.enc ? "42px" : ledgerSlim ? "minmax(560px, 640px)" : "300px",
    ),
    "--hud-cols-wide": cols(
      "340px",
      "minmax(760px, 1fr)",
      collapsed.ledger ? "42px" : encSlim ? "minmax(420px, 1fr)" : "420px",
      collapsed.enc ? "42px" : ledgerSlim ? "minmax(640px, 760px)" : "340px",
    ),
  } as React.CSSProperties;
  const [activeFile, setActiveFile] = useState<string | null>(null);

  useEffect(() => {
    apiGet<{ characters: CharacterEntry[]; active_file: string | null }>("/api/characters")
      .then((r) => {
        setChars(r.characters);
        setActiveFile(r.active_file);
      })
      .catch(() => {});
  }, []);

  const switchChar = async (file: string) => {
    if (!file || file === activeFile) return;
    try {
      const s = await apiSend<Snapshot>("/api/character/select", { file });
      setSnap(s);
      setActiveFile(file);
      setRows([]);
      apiGet<{ events: LedgerRow[] }>("/api/events?limit=120")
        .then((r) => setRows(stamp(r.events)))
        .catch(() => {});
    } catch {
      /* backend offline or unknown character */
    }
  };

  useEffect(() => {
    apiGet<Snapshot>("/api/character").then(setSnap).catch(() => {});
    apiGet<{ events: LedgerRow[] }>("/api/events?limit=120")
      .then((r) => setRows(stamp(r.events)))
      .catch(() => {});
  }, [stamp]);

  const statusLabel =
    status === "linked" ? "Linked" : status === "connecting" ? "Linking" : "Link lost";

  return (
    <main className="hud">
      <header className="hud-header">
        <div>
          <div className="eyebrow">
            WarCounsel{" "}
            <button
              type="button"
              className="app-version"
              onClick={checkUpdates}
              title="Check for updates (compares against the latest release on GitHub)"
            >
              v{APP_VERSION}
            </button>
            {updateAvail && !updateMsg && (
              <button
                type="button"
                className="update-avail"
                onClick={runUpdate}
                title={`v${updateAvail} is out — click to update (runs update_companion.bat in its own window)`}
              >
                Update available — v{updateAvail}
              </button>
            )}
            {updateMsg && (
              <span className="update-msg" data-newer={updateMsg.newer ? "1" : undefined}>
                {updateMsg.text}
              </span>
            )}
          </div>
          <h1 className="nameplate">{snap?.name ?? "—"}</h1>
          <div className="nameplate-sub">
            {snap?.server ?? ""}
            {snap?.class_str ? ` — ${snap.class_str}` : ""}
            {snap?.race ? ` — ${snap.race}` : ""}
          </div>
        </div>
        <div className="header-right">
          {chars.length > 1 && (
            <div className="zone-now">
              <div className="zone-label">Character</div>
              <select
                className="char-select"
                value={activeFile ?? ""}
                onChange={(e) => switchChar(e.target.value)}
                aria-label="Active character"
              >
                {!activeFile && <option value="">—</option>}
                {chars.map((c) => (
                  <option key={c.file} value={c.file}>
                    {c.name}{c.server ? ` — ${c.server}` : ""}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="zone-now">
            <div className="zone-label">Current zone</div>
            <div className="zone-name">{snap?.zone ?? "Unknown"}</div>
          </div>
          <button
            type="button"
            className="gear-btn"
            title="Settings — game folder, advisor model"
            aria-label="Settings"
            onClick={() => setSettingsOpen(true)}
          >
            <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
              {/* teeth generated on a circle so they are actually
                  even -- the hand-drawn path this replaced had
                  irregular spacing and read as a cartoon at 15px */}
              <path
                fill="currentColor"
                fillRule="evenodd"
                d="M8.98 4.70L9.80 1.63L14.20 1.63L15.02 4.70L17.77 3.11L20.89 6.23L19.30 8.98L22.37 9.80L22.37 14.20L19.30 15.02L20.89 17.77L17.77 20.89L15.02 19.30L14.20 22.37L9.80 22.37L8.98 19.30L6.23 20.89L3.11 17.77L4.70 15.02L1.63 14.20L1.63 9.80L4.70 8.98L3.11 6.23L6.23 3.11ZM15.50 12.00A3.5 3.5 0 1 0 8.50 12.00A3.5 3.5 0 1 0 15.50 12.00Z"
              />
            </svg>
          </button>
          <button
            type="button"
            className="overlay-btn"
            data-on={overlayOn ? "1" : undefined}
            onClick={() =>
              apiSend<{ running: boolean }>("/api/overlay", {})
                .then((r) => setOverlayOn(r.running))
                .catch(() => {})
            }
            title="Toggle the always-on-top combat strip (Scroll Lock ON = move it, OFF = click-through)"
          >
            {overlayOn ? "Overlay ✕" : "Overlay"}
          </button>
          {/* Announced, because losing the backend freezes every number on
              screen and the only other tell is a small diamond changing
              colour. */}
          <div className="link" data-status={status} role="status" aria-live="polite">
            <span className="link-rune" aria-hidden />
            {statusLabel}
          </div>
        </div>
      </header>

      {/* Outside the grid and outside every panel pref on purpose: this is
          the surface that explains why the panels are empty. */}
      <StatusStrip snap={snap} chars={chars} onSwitch={switchChar} />

      <div
        className="hud-grid"
        data-combat={centerOpen ? undefined : "1"}
        style={hudCols}
      >
        {showVitals && <CharacterPanel snap={snap} onSnapChange={setSnap} />}
        {centerOpen ? (
          <div className="center-stack">
            <div className="tab-row">
              <div className="tab-group" role="tablist" aria-label="Center panel">
                {centerTabs.map((tab, i) => (
                  <button
                    key={tab.id}
                    type="button"
                    role="tab"
                    id={`tab-${tab.id}`}
                    aria-controls="center-tabpanel"
                    aria-selected={activeTab === tab.id}
                    tabIndex={activeTab === tab.id ? 0 : -1}
                    data-active={activeTab === tab.id}
                    ref={(el) => {
                      tabRefs.current[i] = el;
                    }}
                    onKeyDown={(e) => onTabKey(e, i)}
                    onClick={() => setCenterTab(tab.id)}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
              <button
                type="button"
                className="tab-collapse"
                onClick={toggleCenter}
                title="Hide the Atlas/Advisor panel — combat layout: vitals + encounters up top, full-width ledger below"
              >
                ◂ hide
              </button>
            </div>
            <div
              className="center-tabpanel"
              id="center-tabpanel"
              role="tabpanel"
              aria-labelledby={`tab-${activeTab}`}
            >
              {activeTab === "atlas" ? (
                <AtlasPanel zone={snap?.zone ?? null} position={snap?.position ?? null} />
              ) : activeTab === "progression" ? (
                <ProgressionPanel />
              ) : activeTab === "quests" ? (
                <QuestPanel level={snap?.level ?? null} />
              ) : (
                <AdvisorPanel snap={snap} onSnapChange={setSnap} />
              )}
            </div>
          </div>
        ) : (
          <button
            type="button"
            className="center-reopen"
            onClick={toggleCenter}
            title="Show the Atlas/Advisor panel"
          >
            Atlas · Advisor ▸
          </button>
        )}
        {showLedger && <WarLedger rows={rows} />}
        {showEnc && (
        <EncounterPanel
          encounters={snap?.encounters ?? []}
          summary={snap?.ability_summary ?? null}
          lastDeath={snap?.last_death ?? null}
          filtered={snap?.filtered}
        />
        )}
      </div>
      {settingsOpen && (
        <SettingsModal onClose={() => setSettingsOpen(false)} />
      )}
    </main>
  );
}

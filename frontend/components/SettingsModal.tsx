"use client";

/* Settings — the gear in the header.
 *
 * Deliberately small: the two things a fresh install actually has to be
 * told (where the game is, and which model to counsel with) plus where its
 * data lives. Everything else stays discoverable in .env for source users.
 *
 * API keys are write-only here. The backend reports a boolean, never the
 * key, so a saved key shows as "saved" and can be replaced or cleared but
 * never read back out of the browser.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiSend } from "@/lib/api";

type GameVerdict = {
  path: string;
  ok: boolean;
  reason: string;
  logs?: string;
  log_count?: number;
};

type SettingsData = {
  game: GameVerdict;
  detected_game_dir: string | null;
  data_dir: string;
  packaged: boolean;
  version: string;
  llm: {
    active: { provider: string; model: string };
    openai_model: string;
    custom_model: string;
    custom_base_url: string;
    lmstudio_base_url: string;
    keys_set: Record<string, boolean>;
    available: Record<string, boolean>;
  };
};

const PROVIDERS = [
  { id: "none", label: "None — deterministic (no LLM, no key needed)" },
  { id: "lmstudio", label: "Local — LM Studio" },
  { id: "openai", label: "OpenAI" },
  { id: "custom", label: "Custom — any OpenAI-compatible endpoint" },
];

/** Which secret field a provider needs, or null when it needs none. */
function keyFieldFor(provider: string): string | null {
  if (provider === "openai") return "openai_api_key";
  if (provider === "custom") return "custom_api_key";
  return null;
}

export function SettingsModal({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<SettingsData | null>(null);
  const [gameDir, setGameDir] = useState("");
  const [provider, setProvider] = useState("none");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [verdict, setVerdict] = useState<GameVerdict | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const firstField = useRef<HTMLInputElement>(null);

  useEffect(() => {
    apiGet<SettingsData>("/api/settings")
      .then((d) => {
        setData(d);
        setGameDir(d.game.path ?? "");
        setProvider(d.llm.active.provider);
        setModel(
          d.llm.active.provider === "custom" ? d.llm.custom_model : d.llm.openai_model,
        );
        setVerdict(d.game);
      })
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    firstField.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const test = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setVerdict(
        await apiSend<GameVerdict>("/api/settings/validate-game-dir", {
          game_dir: gameDir,
        }),
      );
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }, [gameDir]);

  const save = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        eql_game_dir: gameDir,
        llm_provider: provider,
      };
      if (provider === "openai") body.openai_model = model;
      if (provider === "custom") body.custom_model = model;
      // Only send a key when one was typed. Omitting it leaves whatever is
      // stored untouched — saving the game folder must never wipe a key.
      const field = keyFieldFor(provider);
      if (field && apiKey.trim()) body[field] = apiKey.trim();
      await apiSend("/api/settings", body);
      setSaved(true);
      setApiKey("");
      const fresh = await apiGet<SettingsData>("/api/settings");
      setData(fresh);
      setVerdict(fresh.game);
      setTimeout(onClose, 700);
    } catch (e) {
      setError(String(e).replace(/^Error:\s*/, ""));
    } finally {
      setBusy(false);
    }
  }, [gameDir, provider, model, apiKey, onClose]);

  const clearKey = useCallback(async () => {
    const field = keyFieldFor(provider);
    if (!field) return;
    setBusy(true);
    try {
      await apiSend("/api/settings", { [field]: "" });
      setApiKey("");
      setData(await apiGet<SettingsData>("/api/settings"));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }, [provider]);

  const field = keyFieldFor(provider);
  const keyStored = field ? data?.llm.keys_set?.[field] : false;

  return (
    <div className="modal-veil" onMouseDown={onClose} role="presentation">
      <div
        className="modal-card"
        role="dialog"
        aria-modal="true"
        aria-label="Settings"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h2>Settings</h2>
          <button type="button" className="modal-x" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        {!data && !error && <p className="chat-empty">Loading…</p>}

        {data && (
          <div className="modal-body">
            <section className="set-block">
              <label htmlFor="set-game">Game folder</label>
              <div className="set-row">
                <input
                  id="set-game"
                  ref={firstField}
                  value={gameDir}
                  spellCheck={false}
                  onChange={(e) => {
                    setGameDir(e.target.value);
                    setVerdict(null);
                  }}
                  placeholder="…\EverQuest Legends"
                />
                <button type="button" onClick={test} disabled={busy || !gameDir}>
                  Test
                </button>
              </div>
              {data.detected_game_dir && data.detected_game_dir !== gameDir && (
                <button
                  type="button"
                  className="set-link"
                  onClick={() => {
                    setGameDir(data.detected_game_dir as string);
                    setVerdict(null);
                  }}
                >
                  Use detected: {data.detected_game_dir}
                </button>
              )}
              {verdict && (
                <p className="set-note" data-ok={verdict.ok ? "1" : "0"}>
                  {verdict.ok ? "✓" : "✕"} {verdict.reason}
                </p>
              )}
            </section>

            <section className="set-block">
              <label htmlFor="set-provider">Advisor model</label>
              <select
                id="set-provider"
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
              >
                {PROVIDERS.map((p) => {
                  const usable = data.llm.available?.[p.id] !== false;
                  return (
                    <option key={p.id} value={p.id} disabled={!usable}>
                      {p.label}
                      {usable ? "" : " — not available in this build"}
                    </option>
                  );
                })}
              </select>

              {(provider === "openai" || provider === "custom") && (
                <>
                  <div className="set-row">
                    <input
                      value={model}
                      spellCheck={false}
                      onChange={(e) => setModel(e.target.value)}
                      placeholder="model name"
                      aria-label="Model name"
                    />
                  </div>
                  <div className="set-row">
                    <input
                      type="password"
                      value={apiKey}
                      autoComplete="off"
                      spellCheck={false}
                      onChange={(e) => setApiKey(e.target.value)}
                      placeholder={keyStored ? "•••••••• saved — type to replace" : "API key"}
                      aria-label="API key"
                    />
                    {keyStored && (
                      <button type="button" onClick={clearKey} disabled={busy}>
                        Clear
                      </button>
                    )}
                  </div>
                  <p className="set-note">
                    Stored in <code>secrets.json</code> in your data folder, separate
                    from every other setting, and never shown again.
                  </p>
                </>
              )}
              {data.llm.available?.[provider] === false && (
                <p className="set-note" data-ok="0">
                  This build does not include the libraries that model needs,
                  so counsel would quietly fall back to the built-in advisor.
                  The packaged .exe is deterministic by design — use the
                  source install if you want an LLM.
                </p>
              )}
              {provider === "none" && (
                <p className="set-note">
                  Counsel comes from the built-in deterministic advisor. Nothing
                  leaves your PC.
                </p>
              )}
              {provider === "lmstudio" && (
                <p className="set-note">
                  Uses LM Studio&apos;s local server at{" "}
                  <code>{data.llm.lmstudio_base_url}</code>. No key needed.
                </p>
              )}
            </section>

            <section className="set-block">
              <p className="set-note">
                Data folder: <code>{data.data_dir}</code>
                <br />
                Version {data.version}
                {data.packaged ? " (packaged build)" : ""}
              </p>
            </section>

            {error && <p className="set-note" data-ok="0">{error}</p>}

            <div className="modal-foot">
              <button type="button" onClick={onClose} disabled={busy}>
                Cancel
              </button>
              <button
                type="button"
                className="set-primary"
                onClick={save}
                disabled={busy}
              >
                {saved ? "Saved ✓" : busy ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

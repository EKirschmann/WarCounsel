"use client";

/* Settings — the gear in the header.
 *
 * Deliberately small: the two things a fresh install actually has to be
 * told (where the game is, and which model to counsel with), what the
 * overlay shows, and where its data lives. Everything else stays
 * discoverable in .env for source users.
 *
 * The overlay block saves on click through its own endpoint rather than on
 * Save — see OverlaySettings.
 *
 * API keys are write-only here. The backend reports a boolean, never the
 * key, so a saved key shows as "saved" and can be replaced or cleared but
 * never read back out of the browser.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiSend } from "@/lib/api";
import type { LlmProbe } from "@/lib/types";
import { OverlaySettings } from "./OverlaySettings";

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
    ollama_base_url: string;
    ollama_model: string;
    anthropic_model: string;
    keys_set: Record<string, boolean>;
    available: Record<string, boolean>;
  };
};

const PROVIDERS = [
  { id: "none", label: "None — deterministic (no LLM, no key needed)" },
  { id: "lmstudio", label: "Local — LM Studio" },
  { id: "local", label: "Local — Ollama" },
  { id: "openai", label: "OpenAI" },
  { id: "anthropic", label: "Anthropic — Claude" },
  { id: "custom", label: "Custom — OpenAI-compatible (Grok, Groq, OpenRouter…)" },
];

/** Which secret field a provider needs, or null when it needs none. */
function keyFieldFor(provider: string): string | null {
  if (provider === "openai") return "openai_api_key";
  if (provider === "custom") return "custom_api_key";
  if (provider === "anthropic") return "anthropic_api_key";
  return null;
}

/** "Is anything actually listening?" — rendered under the local providers.
 *  Kept out of the save path: checking is free and reversible, so it is a
 *  button rather than something that happens on every render. */
function ProbeRow({ provider, probe, probing, onCheck }: {
  provider: string;
  probe: LlmProbe | null;
  probing: boolean;
  onCheck: () => void;
}) {
  const mine = probe && probe.provider === provider ? probe : null;
  // "none loaded" is the NORMAL idle state: Ollama unloads after 5 minutes
  // (keep_alive default) and LM Studio JIT-loads too, so both sit at zero
  // between requests. Reporting that as a deficiency sends people hunting a
  // fault that is not there. What actually decides whether a consult works
  // is whether the CONFIGURED model is among the ones the server offers.
  const status = (): { ok: boolean; text: string } => {
    if (!mine) return { ok: true, text: "" };
    if (!mine.reachable)
      return { ok: false, text: `not reachable — ${mine.reason ?? "no response"}` };
    if (!mine.models.length)
      return { ok: false, text: "up, but no models installed yet" };
    if (mine.model_present === false)
      return {
        ok: false,
        text: `up, but your model is not among the ${mine.models.length} installed`,
      };
    if (mine.loaded?.length)
      return { ok: true, text: `up · ${mine.loaded[0]} loaded` };
    return {
      ok: true,
      text: `up · ${mine.models.length} model${mine.models.length === 1 ? "" : "s"} installed, loads on first use`,
    };
  };
  const s = status();
  return (
    <div className="set-row probe-row">
      <button type="button" onClick={onCheck} disabled={probing}>
        {probing ? "Checking…" : "Check server"}
      </button>
      {mine && (
        <span className="probe-result" data-ok={s.ok ? "1" : "0"}>
          {s.text}
        </span>
      )}
    </div>
  );
}

export function SettingsModal({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<SettingsData | null>(null);
  const [gameDir, setGameDir] = useState("");
  const [provider, setProvider] = useState("none");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  // Ollama's host is its own field: unlike LM Studio it is commonly on
  // ANOTHER machine, so it cannot be a fixed default.
  const [ollamaUrl, setOllamaUrl] = useState("");
  const [probe, setProbe] = useState<LlmProbe | null>(null);
  const [probing, setProbing] = useState(false);
  const [verdict, setVerdict] = useState<GameVerdict | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const firstField = useRef<HTMLInputElement>(null);
  const didFocus = useRef(false);

  useEffect(() => {
    apiGet<SettingsData>("/api/settings")
      .then((d) => {
        setData(d);
        setGameDir(d.game.path ?? "");
        setProvider(d.llm.active.provider);
        setModel(
          d.llm.active.provider === "custom" ? d.llm.custom_model
          : d.llm.active.provider === "local" ? d.llm.ollama_model
          : d.llm.openai_model,
        );
        setOllamaUrl(d.llm.ollama_base_url ?? "");
        setVerdict(d.game);
      })
      .catch((e) => setError(String(e)));
  }, []);

  // Focus the game folder EXACTLY ONCE, on the render where it first
  // exists. Two traps here, both previously live:
  //   * the panel shows "Loading…" until /api/settings answers, so a
  //     mount-only effect finds a null ref and never focuses anything;
  //   * page.tsx passes a fresh onClose arrow every render and the HUD
  //     re-renders several times a second off the WebSocket, so keying
  //     this to onClose (as it was) re-focused the field continuously
  //     and stole the caret mid-click.
  // The ref latch is what lets it wait for the field without repeating.
  useEffect(() => {
    if (!data || didFocus.current) return;
    didFocus.current = true;
    firstField.current?.focus();
  }, [data]);

  useEffect(() => {
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

  // One `model` field serves every provider, so switching the dropdown
  // has to reseed it — otherwise picking Ollama inherits the OpenAI model
  // and the hint reads "ollama pull o3".
  const switchProvider = useCallback(
    (next: string) => {
      setProvider(next);
      if (!data) return;
      setModel(
        next === "custom" ? data.llm.custom_model
        : next === "local" ? data.llm.ollama_model
        : next === "anthropic" ? data.llm.anthropic_model
        : next === "openai" ? data.llm.openai_model
        : "",
      );
    },
    [data],
  );

  // Asks the local server directly. `available` only says the client
  // library is installed, which is a different question from "is anything
  // listening and is a model loaded".
  const runProbe = useCallback(async (which: string) => {
    setProbing(true);
    setProbe(null);
    try {
      setProbe(await apiGet<LlmProbe>(`/api/llm/probe?provider=${which}`));
    } catch (e) {
      setProbe({ provider: which, checked: true, reachable: false,
                 models: [], loaded: [], reason: String(e) });
    } finally {
      setProbing(false);
    }
  }, []);

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
      if (provider === "anthropic") body.anthropic_model = model;
      if (provider === "local") {
        body.ollama_model = model;
        body.ollama_base_url = ollamaUrl.trim();
      }
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
  }, [gameDir, provider, model, apiKey, ollamaUrl, onClose]);

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
                onChange={(e) => switchProvider(e.target.value)}
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

              {(provider === "openai" || provider === "custom"
                || provider === "anthropic") && (
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
                <>
                  <ProbeRow
                    provider="lmstudio"
                    probe={probe}
                    probing={probing}
                    onCheck={() => runProbe("lmstudio")}
                  />
                <p className="set-note">
                  Uses LM Studio&apos;s local server at{" "}
                  <code>{data.llm.lmstudio_base_url}</code>. No key needed.
                </p>
                </>
              )}
              {provider === "local" && (
                <>
                  <div className="set-row">
                    <input
                      value={model}
                      spellCheck={false}
                      onChange={(e) => setModel(e.target.value)}
                      placeholder="model, e.g. llama3.1"
                      aria-label="Ollama model"
                    />
                  </div>
                  <div className="set-row">
                    <input
                      value={ollamaUrl}
                      spellCheck={false}
                      onChange={(e) => setOllamaUrl(e.target.value)}
                      placeholder="http://localhost:11434"
                      aria-label="Ollama server address"
                    />
                  </div>
                  <ProbeRow
                    provider="local"
                    probe={probe}
                    probing={probing}
                    onCheck={() => runProbe("local")}
                  />
                  <p className="set-note">
                    No key needed. Install Ollama and run{" "}
                    <code>ollama pull {model || "llama3.1"}</code>. Point the
                    address at another machine if Ollama runs on your desktop
                    while you play elsewhere.
                  </p>
                </>
              )}
            </section>

            <section className="set-block">
              <label>Overlay</label>
              <p className="set-note">
                Pick what the in-game overlay shows. The rest stays here in the
                web view, where there is room for it.
              </p>
              <OverlaySettings />
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

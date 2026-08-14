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
import { OcrSettings } from "./OcrSettings";
import { PanelPresets, PanelSettings } from "./PanelSettings";
import { OverlaySettings } from "./OverlaySettings";
import { TriggerSettings } from "./TriggerSettings";

type GameVerdict = {
  path: string;
  ok: boolean;
  reason: string;
  logs?: string;
  log_count?: number;
};

type SettingsData = {
  allow_spellset_write?: boolean;
  game: GameVerdict;
  detected_game_dir: string | null;
  data_dir: string;
  packaged: boolean;
  version: string;
  llm: {
    active: { provider: string; model: string };
    openai_model: string;
    lmstudio_model?: string;
    custom_model: string;
    custom_base_url: string;
    lmstudio_base_url: string;
    context?: {
      limit: number;
      source: "manual" | "probed" | "default";
      detected: number | null;
      guide_budget: number;
      manual: string;
    };
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

/** Which model belongs to a provider.
 *
 * This mapping was written out twice -- once to seed the panel, once when
 * switching provider -- and BOTH copies omitted lmstudio. One fell through
 * to the OpenAI model and showed "o3" in the local model box; the other
 * fell through to "" and blanked it. Two chances to be wrong about the
 * same fact is one too many. */
function modelFor(provider: string, llm: SettingsData["llm"]): string {
  switch (provider) {
    case "custom":
      return llm.custom_model ?? "";
    case "local":
      return llm.ollama_model ?? "";
    case "anthropic":
      return llm.anthropic_model ?? "";
    case "openai":
      return llm.openai_model ?? "";
    case "lmstudio":
      return llm.lmstudio_model ?? llm.active.model ?? "";
    default:
      return "";
  }
}

/** Left-rail entries. Panels sit between the general settings and the
 *  peripheral ones, because they are what people actually adjust. */
const PANEL_TABS = [
  { key: "vitals", label: "Vitals & Session" },
  { key: "encounter", label: "Encounter" },
  { key: "quests", label: "Quests" },
  { key: "progression", label: "Progression" },
  { key: "ledger", label: "War Ledger" },
];
const RAIL = [
  { key: "general", label: "General" },
  ...PANEL_TABS,
  { key: "overlay", label: "Overlay" },
  { key: "triggers", label: "Triggers" },
  { key: "ocr", label: "Screen reading" },
  { key: "llm", label: "Advisor model" },
];

export function SettingsModal({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<SettingsData | null>(null);
  const [allowSetWrite, setAllowSetWrite] = useState(false);
  const [gameDir, setGameDir] = useState("");
  const [provider, setProvider] = useState("none");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  // Can this browser mask a plain text field? Checked once, at mount: if it
  // can, the key box is not a password field at all and no password manager
  // takes an interest in it.
  const [maskable] = useState(
    () => typeof CSS !== "undefined"
      && CSS.supports?.("-webkit-text-security", "disc"),
  );
  // Ollama's host is its own field: unlike LM Studio it is commonly on
  // ANOTHER machine, so it cannot be a fixed default.
  const [ollamaUrl, setOllamaUrl] = useState("");
  const [ctxLimit, setCtxLimit] = useState("");
  const [tab, setTab] = useState("general");
  const [customUrl, setCustomUrl] = useState("");
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
        // No lmstudio branch here meant it fell through to the OpenAI
        // model, so opening this panel with LM Studio active displayed
        // "o3" -- a model that exists only at OpenAI -- in the local
        // model box. Every provider names its own field now.
        setModel(modelFor(d.llm.active.provider, d.llm));
        setOllamaUrl(d.llm.ollama_base_url ?? "");
        setCtxLimit(d.llm.context?.manual ?? "");
        setCustomUrl(d.llm.custom_base_url ?? "");
        setAllowSetWrite(d.allow_spellset_write === true);
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
      setModel(modelFor(next, data.llm));
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
      if (provider === "custom") {
        body.custom_model = model;
        // Without this the endpoint was never settable from the panel,
        // and an empty base URL sends the key to OpenAI.
        body.custom_base_url = customUrl.trim();
      }
      if (provider === "anthropic") body.anthropic_model = model;
      if (provider === "lmstudio") body.model = model.trim();
      if (provider === "local") {
        body.ollama_model = model;
        body.ollama_base_url = ollamaUrl.trim();
      }
      // Always sent, for every provider: an empty string CLEARS the pin and
      // returns to following the server, which a conditional send could not
      // express.
      body.llm_context_limit = ctxLimit.trim();
      // Sent as a string because app_config stores every override that way;
      // "" would CLEAR the override rather than set it false, so both states
      // are spelled out.
      body.allow_spellset_write = allowSetWrite ? "true" : "false";
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
  }, [gameDir, provider, model, apiKey, ollamaUrl, customUrl, onClose]);

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
          <div className="modal-body set-split">
            {/* A rail, because the modal had grown to six stacked blocks and
                finding the overlay switches meant scrolling past the model
                picker. Panels get their own entries so "stop showing me
                deaths" has somewhere obvious to live. */}
            <nav className="set-rail" aria-label="Settings sections">
              {RAIL.map((r) => (
                <button
                  key={r.key}
                  type="button"
                  data-active={tab === r.key}
                  onClick={() => setTab(r.key)}
                >
                  {r.label}
                </button>
              ))}
            </nav>
            <div className="set-pane">
            {tab === "general" && (
<section className="set-block">
              <label htmlFor="set-game">Game folder</label>
              <div className="set-row">
                <input
                  id="set-game"
                  ref={firstField}
                  value={gameDir}
                  spellCheck={false}
                      autoComplete="off"
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

              <label className="set-check" htmlFor="set-spellset-write">
                <input
                  id="set-spellset-write"
                  type="checkbox"
                  checked={allowSetWrite}
                  onChange={(e) => setAllowSetWrite(e.target.checked)}
                />
                Write spell sets into the game folder
              </label>
              <p className="set-note">
                Lets the Advisor save a suggested bar as an in-game spell set,
                so <code>/memspellset</code> loads the whole thing at once. It
                edits the <code>[SpellLoadouts]</code> section of your{" "}
                <code>LO*.ini</code> and backs the file up first. This is the
                only file WarCounsel writes inside the game folder, so it is
                off until you switch it on — everything else it stores stays
                in its own data folder.
              </p>
            </section>
)}

            {tab === "llm" && (
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
                      autoComplete="off"
                      onChange={(e) => setModel(e.target.value)}
                      placeholder="model name"
                      aria-label="Model name"
                    />
                  </div>
                  {provider === "custom" && (
                    <div className="set-row">
                      <input
                        value={customUrl}
                        spellCheck={false}
                      autoComplete="off"
                        onChange={(e) => setCustomUrl(e.target.value)}
                        placeholder="https://api.groq.com/openai/v1"
                        aria-label="Custom endpoint base URL"
                      />
                    </div>
                  )}
                  <div className="set-row">
                    <input
                      // NOT type="password". Chrome attaches its password
                      // manager to those fields whatever the autocomplete
                      // hint says, and "new-password" actively invites the
                      // generate-a-password offer -- reported twice. An API
                      // key is a secret but it is not a login, and the
                      // browser has no business filing it with one.
                      //
                      // Masked with -webkit-text-security instead, falling
                      // back to a real password field where that is not
                      // supported (Firefox), which is also where Chrome's
                      // password UI does not exist.
                      type={maskable ? "text" : "password"}
                      className={maskable ? "set-secret" : undefined}
                      name="wc-provider-secret"
                      data-1p-ignore
                      data-lpignore="true"
                      value={apiKey}
                      spellCheck={false}
                      autoComplete="off"
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
              {provider === "custom" && !customUrl.trim() && (
                <p className="set-note" data-ok="0">
                  Add the endpoint above, or the request — and your key — go
                  to OpenAI instead. Groq is{" "}
                  <code>https://api.groq.com/openai/v1</code>.
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
                  <div className="set-row">
                    <input
                      value={model}
                      spellCheck={false}
                      autoComplete="off"
                      onChange={(e) => setModel(e.target.value)}
                      placeholder="model id, e.g. gemma-4-26b-a4b-it"
                      aria-label="LM Studio model"
                    />
                  </div>
                  {/* A <datalist> was here and behaved as a FILTER, not a
                      picker: with a model already in the box nothing else
                      prefix-matched, so the dropdown arrow appeared and
                      opened on nothing until the field was cleared. The
                      models are already probed -- showing them is simpler
                      than making someone empty a box to discover them.

                      Chat models only: the server also lists embedding
                      models, which would fail silently as a counsel model. */}
                  {probe?.provider === "lmstudio" &&
                    (probe.models ?? []).filter((m) => !m.toLowerCase().includes("embed"))
                      .length > 0 && (
                      <div className="model-picks">
                        {(probe.models ?? [])
                          .filter((m) => !m.toLowerCase().includes("embed"))
                          .map((m) => (
                            <button
                              key={m}
                              type="button"
                              className="model-pick"
                              data-on={m === model.trim() ? "1" : undefined}
                              data-loaded={(probe.loaded ?? []).includes(m) ? "1" : undefined}
                              title={
                                (probe.loaded ?? []).includes(m)
                                  ? `${m} — loaded in LM Studio right now`
                                  : `${m} — installed; LM Studio loads it on the first request`
                              }
                              onClick={() => setModel(m)}
                            >
                              {m}
                            </button>
                          ))}
                      </div>
                    )}
                  {probe?.provider === "lmstudio" &&
                    (probe.loaded ?? []).length > 0 &&
                    !(probe.loaded ?? []).includes(model.trim()) && (
                      <p className="set-note" data-ok="0">
                        LM Studio currently has{" "}
                        <strong>{(probe.loaded ?? []).join(", ")}</strong>{" "}
                        loaded, but counsel is set to{" "}
                        <strong>{model.trim() || "nothing"}</strong>. Requests
                        name the model, so LM Studio will load that one back
                        and unload what you picked.{" "}
                        <button
                          type="button"
                          className="link-btn"
                          onClick={() => setModel((probe.loaded ?? [])[0])}
                        >
                          Use the loaded one
                        </button>
                      </p>
                    )}
                <p className="set-note">
                  Uses LM Studio&apos;s local server at{" "}
                  <code>{data.llm.lmstudio_base_url}</code>. No key needed.
                </p>
                <div className="set-row">
                  <input
                    value={ctxLimit}
                    spellCheck={false}
                      autoComplete="off"
                    inputMode="numeric"
                    onChange={(e) => setCtxLimit(e.target.value)}
                    placeholder={
                      data.llm.context?.detected
                        ? `auto: ${data.llm.context.detected}`
                        : "context tokens, e.g. 8192"
                    }
                    aria-label="Context limit override"
                  />
                </div>
                <p className="set-note">
                  {data.llm.context?.detected ? (
                    <>
                      Detected <strong>{data.llm.context.detected}</strong>{" "}
                      tokens loaded. Prompts are sized to this
                      {data.llm.context.source === "manual" && (
                        <> — currently overridden to{" "}
                        <strong>{data.llm.context.limit}</strong></>
                      )}
                      . Leave blank to follow the server; set a smaller
                      number if a reload brings the model back with less.
                    </>
                  ) : (
                    <>
                      No loaded model detected, so prompts use a
                      conservative {data.llm.context?.limit ?? 8192} tokens.
                      Check the server above, or pin a value here.
                    </>
                  )}
                </p>
                </>
              )}
              {provider === "local" && (
                <>
                  <div className="set-row">
                    <input
                      value={model}
                      spellCheck={false}
                      autoComplete="off"
                      onChange={(e) => setModel(e.target.value)}
                      placeholder="model, e.g. llama3.1"
                      aria-label="Ollama model"
                    />
                  </div>
                  <div className="set-row">
                    <input
                      value={ollamaUrl}
                      spellCheck={false}
                      autoComplete="off"
                      onChange={(e) => setOllamaUrl(e.target.value)}
                      placeholder="http://localhost:11434"
                      aria-label="Ollama server address"
                    />
                  </div>
                  {/* Ollama had no context field at all, which mattered more
                      here than anywhere: it defaults to 2048 tokens and
                      TRUNCATES a longer prompt silently, so the advisor was
                      being handed the tail of its own prompt. */}
                  <div className="set-row">
                    <input
                      value={ctxLimit}
                      spellCheck={false}
                      autoComplete="off"
                      inputMode="numeric"
                      onChange={(e) => setCtxLimit(e.target.value)}
                      placeholder="context tokens, e.g. 16384"
                      aria-label="Ollama context limit"
                    />
                  </div>
                  <p className="set-note">
                    Ollama defaults to a <strong>2048-token</strong> context and
                    quietly cuts anything longer, which leaves the advisor
                    answering from a fraction of its prompt — a near-empty
                    loadout is the usual symptom. WarCounsel asks for{" "}
                    {data.llm.context?.limit ?? 8192} unless you set a number
                    here. 16384 suits an 8B model on a 12&nbsp;GB card; raise it
                    if consults still come back thin, lower it if the model
                    will not load.
                  </p>
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
)}

            {tab === "overlay" && (
<section className="set-block">
              <label>Overlay</label>
              <p className="set-note">
                Pick what the in-game overlay shows. The rest stays here in the
                web view, where there is room for it.
              </p>
              <OverlaySettings />
            </section>
)}

            {tab === "triggers" && (
<section className="set-block">
              <label>Triggers</label>
              <p className="set-note">
                Watch the log for the things you would otherwise miss — a
                charm or mez breaking, a named spawn, a mob starting a nasty
                cast. Each one raises a banner on the overlay.
              </p>
              <TriggerSettings />
            </section>
)}

            {tab === "ocr" && (
<section className="set-block">
              <label>Screen reading (OCR)</label>
              <p className="set-note">
                Optional and Windows-only. The app reads two small boxes on your
                screen — nothing is sent anywhere and the game is never touched.
              </p>
              <OcrSettings />
            </section>
)}

            {tab === "general" && (
<section className="set-block">
              <p className="set-note">
                Data folder: <code>{data.data_dir}</code>
                <br />
                Version {data.version}
                {data.packaged ? " (packaged build)" : ""}
              </p>
            </section>
)}

            {error && <p className="set-note" data-ok="0">{error}</p>}

            {PANEL_TABS.some((t) => t.key === tab) && (
              <section className="set-block">
                <label>{PANEL_TABS.find((t) => t.key === tab)!.label}</label>
                <p className="set-note">
                  Choose what this panel shows. Kept separate from the overlay:
                  a glance strip and a full column want different things.
                </p>
                <PanelSettings active={tab} />
              </section>
            )}
            {tab === "general" && (
              <section className="set-block">
                <label>Panel presets</label>
                <p className="set-note">
                  Starting points for every panel at once. Adjust individual
                  panels from the list on the left.
                </p>
                <PanelPresets />
              </section>
            )}
            </div>
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

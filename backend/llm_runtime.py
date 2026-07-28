"""Runtime-selectable LLM: local (LM Studio) vs frontier (OpenAI).

The Advisor tab switches providers at runtime; the choice persists to
data/llm_config.json and applies to the next consult without a restart.
Chat models are built lazily and cached per (provider, model).
"""
import json
import logging
import threading
from pathlib import Path

from backend.config import settings

logger = logging.getLogger(__name__)

from backend.paths import data_path
from backend.secrets_store import resolve as _key

_CONFIG = data_path("llm_config.json")
_lock = threading.Lock()
_cache: dict = {}


def _load() -> dict:
    try:
        return json.loads(_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def openai_model() -> str:
    return _load().get("openai_model") or settings.openai_model


def custom_model() -> str:
    return _load().get("custom_model") or settings.custom_model or "unset"


def model_for(provider: str) -> str:
    """The model configured for a GIVEN provider, active or not.

    probe() needs this: checking Ollama while LM Studio is still the active
    provider must compare against the OLLAMA model, or it reports "your
    model is not in the list" for a model that is plainly there.
    """
    cfg = _load()
    if provider == "openai":
        return openai_model()
    if provider == "custom":
        return custom_model()
    if provider == "none":
        return "builtin"
    if provider == "local":
        return cfg.get("ollama_model") or settings.ollama_model
    if provider == "anthropic":
        return cfg.get("anthropic_model") or settings.anthropic_model
    return settings.model                      # lmstudio


def active() -> dict:
    cfg = _load()
    provider = cfg.get("provider") or settings.llm_provider
    return {"provider": provider, "model": model_for(provider)}


def set_active(provider: str, model: str | None = None) -> dict:
    cfg = _load()
    cfg["provider"] = provider
    # Persist per provider, or switching away and back loses the choice.
    per_provider = {"openai": "openai_model", "custom": "custom_model",
                    "local": "ollama_model", "anthropic": "anthropic_model",
                    "lmstudio": "model"}
    key = per_provider.get(provider)
    if key and model:
        cfg[key] = model.strip()
    _CONFIG.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    logger.info("LLM switched to %s / %s", provider,
                model or active()["model"])
    return active()


def _build(provider: str, model: str):
    if provider == "none":
        raise RuntimeError("deterministic mode has no chat model — callers "
                           "must branch on active()['provider'] first")
    if provider == "custom":
        # any OpenAI-compatible endpoint: Groq, OpenRouter, Together,
        # Gemini's compat layer, a friend's LM Studio over LAN, ...
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            base_url=_load().get("custom_base_url") or settings.custom_base_url,
            api_key=_key("custom_api_key", settings.custom_api_key) or "unset")
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        # Reasoning models (o-series, gpt-5.x) reject temperature and use
        # max_completion_tokens internally — pass nothing but the model.
        return ChatOpenAI(
            model=model,
            api_key=_key("openai_api_key", settings.openai_api_key) or "unset")
    if provider == "lmstudio":
        # LM Studio speaks the OpenAI API. Start its local server (Developer
        # tab); enable JIT model loading + idle auto-unload.
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, base_url=settings.lmstudio_base_url,
                          api_key="lm-studio", temperature=0.3)
    if provider == "local":
        # Ollama. Its own server, not an OpenAI-compatible shim, so it gets
        # a real client rather than being folded into "custom".
        from langchain_ollama import ChatOllama
        return ChatOllama(model=model or settings.ollama_model,
                          base_url=settings.ollama_base_url,
                          temperature=0.3)
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model or settings.anthropic_model, max_tokens=8000,
            api_key=_key("anthropic_api_key", settings.anthropic_api_key)
            or "unset")
    # Anything unrecognised used to FALL THROUGH to Anthropic, silently: a
    # stale or misspelled provider became Claude on a default model, which
    # is how "I chose LM Studio" could report claude-3-5-sonnet. Fail loudly
    # instead — the advisor catches this and drops to the built-in path.
    raise RuntimeError(
        f"unknown LLM provider {provider!r} — expected none|lmstudio|openai|"
        "custom|local|anthropic")


def available() -> dict:
    """Which providers THIS BUILD can actually run.

    The packaged exe DOES carry the LLM clients — requirements-lite.txt
    lists them deliberately, because a settings panel offering an API key
    field that can never do anything is worse than one that says so. What
    it omits is OCR. (This docstring previously claimed the opposite; the
    exe has shipped with openai and anthropic working for some time.)

    PyInstaller bundles only what the BUILD MACHINE has installed, so this
    probes at runtime rather than trusting the requirements file, and the
    panel greys out whatever is genuinely missing.
    """
    from importlib.util import find_spec

    def has(module: str) -> bool:
        try:
            return find_spec(module) is not None
        except (ImportError, ValueError):
            return False

    openai_stack = has("langchain_openai")
    return {
        "none": True,                    # the built-in advisor, always there
        "lmstudio": openai_stack,        # LM Studio speaks the OpenAI API
        "openai": openai_stack,
        "custom": openai_stack,
        "anthropic": has("langchain_anthropic"),
        "local": has("langchain_ollama"),
    }


def probe(provider: str | None = None) -> dict:
    """Is the local model server actually up, and is anything loaded?

    `available()` only answers "is the client library installed", which is
    a different question: LM Studio and Ollama can be selected, importable
    and completely unreachable, and the first sign is a failed consult.
    Asking the server costs one short HTTP call.

    Never raises and never blocks for long -- a 2.5s timeout, because this
    runs behind a settings panel, not a background job.
    """
    import json as _json
    import urllib.request

    provider = provider or active()["provider"]
    out: dict = {"provider": provider, "checked": True, "reachable": False,
                 "models": [], "loaded": [], "reason": None}

    def get(url: str):
        with urllib.request.urlopen(url, timeout=2.5) as r:
            return _json.loads(r.read())

    try:
        if provider == "lmstudio":
            base = settings.lmstudio_base_url.rstrip("/")
            try:
                # LM Studio's own API distinguishes downloaded from LOADED;
                # the OpenAI-compatible /models does not.
                data = get(base.rsplit("/v1", 1)[0] + "/api/v0/models")
                rows = data.get("data", [])
                out["models"] = [m.get("id") for m in rows if m.get("id")]
                out["loaded"] = [m.get("id") for m in rows
                                 if m.get("state") == "loaded"]
            except Exception:
                data = get(base + "/models")          # OpenAI shape fallback
                out["models"] = [m.get("id") for m in data.get("data", [])]
            out["reachable"] = True
        elif provider == "local":
            base = settings.ollama_base_url.rstrip("/")
            data = get(base + "/api/tags")
            out["models"] = [m.get("name") for m in data.get("models", [])
                             if m.get("name")]
            try:                                      # /api/ps = in memory now
                ps = get(base + "/api/ps")
                out["loaded"] = [m.get("name") for m in ps.get("models", [])
                                 if m.get("name")]
            except Exception:
                pass
            out["reachable"] = True
        elif provider == "custom":
            base = (_load().get("custom_base_url")
                    or settings.custom_base_url or "").rstrip("/")
            if not base:
                out.update(checked=False, reason="No custom base URL set")
                return out
            data = get(base + "/models")
            out["models"] = [m.get("id") for m in data.get("data", [])]
            out["reachable"] = True
        else:
            # A cloud key cannot be verified without spending a request, and
            # "none" has nothing to reach.
            out.update(checked=False,
                       reason="Nothing to probe for this provider")
            return out
    except Exception as exc:
        out["reason"] = f"{type(exc).__name__}: {exc}"[:160]
        return out

    want = model_for(provider)
    if out["reachable"] and want and out["models"]:
        # Ollama tags carry a :tag suffix the model id may omit
        names = {m.split(":")[0] for m in out["models"]} | set(out["models"])
        out["model_present"] = want in names or want.split(":")[0] in names
    return out


def clear_cache() -> None:
    """Drop built chat models so the next consult picks up a new key."""
    with _lock:
        _cache.clear()


def get_llm():
    a = active()
    key = (a["provider"], a["model"])
    with _lock:
        if key not in _cache:
            _cache[key] = _build(*key)
        return _cache[key]

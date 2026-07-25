from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.paths import data_path

# Sentinel: only a database_url still equal to this gets re-pointed at the
# resolved state dir, so an explicit DATABASE_URL in .env always wins.
_DEFAULT_DB_URL = "sqlite:///./data/companion.db"


def _registry_game_dir() -> str | None:
    """EQL install dir from the Daybreak uninstall key (DisplayIcon /
    UninstallString point at an exe inside it). Fail-soft: None off
    Windows or when the key is absent."""
    try:
        import winreg
    except ImportError:
        return None
    subkey = (r"Microsoft\Windows\CurrentVersion\Uninstall"
              r"\DGC-EverQuest Legends")
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for root in ("SOFTWARE", r"SOFTWARE\WOW6432Node"):
            try:
                with winreg.OpenKey(hive, root + "\\" + subkey) as k:
                    for value in ("DisplayIcon", "UninstallString"):
                        try:
                            raw, _ = winreg.QueryValueEx(k, value)
                        except OSError:
                            continue
                        exe = str(raw).strip().strip('"').split('"')[0]
                        parent = Path(exe).parent
                        if parent.is_dir():
                            return str(parent)
            except OSError:
                continue
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    # LLM — swap provider/model here (see CLAUDE.md "Model Swapping")
    anthropic_api_key: str = ""
    llm_provider: str = "anthropic"           # "anthropic" | "openai" | "lmstudio" | "local"
    model: str = "claude-3-5-sonnet-20241022"
    lmstudio_base_url: str = "http://localhost:1234/v1"
    openai_api_key: str = ""                  # frontier option (Advisor tab)
    openai_model: str = "o3"                  # default when provider=openai
    custom_base_url: str = ""                 # any OpenAI-compatible server
    custom_api_key: str = ""                  # (Groq, OpenRouter, Gemini, ...)
    custom_model: str = ""

    # Database
    database_url: str = _DEFAULT_DB_URL

    # EQL install — set EQL_GAME_DIR in .env; Logs/ and maps/ derive from it
    # unless individually overridden. Default = the launcher's standard path.
    eql_game_dir: str = (r"C:\Users\Public\Daybreak Game Company"
                         r"\Installed Games\EverQuest Legends")
    eql_log_dir: str = ""                     # default: <game dir>\Logs
    eql_maps_dir: str = ""                    # default: <game dir>\maps
    eql_maps_custom_dir: str = ""             # default: <maps>\Dark Brewall (Brewall pack; optional)
    eql_log_path: str | None = None           # full path override (wins over dir scan)
    eql_character_name: str | None = None     # prefer this character's log file

    @model_validator(mode="after")
    def _derive_game_paths(self):
        # Settings chosen in the UI override .env. Applied BEFORE Logs/ and
        # maps/ derive, so a game folder picked from the settings panel
        # behaves exactly like one written into .env. (Secrets are resolved
        # separately, at use time -- see backend/secrets_store.py.)
        from backend.app_config import load as _overrides
        for _field, _value in _overrides().items():
            if hasattr(self, _field):
                setattr(self, _field, _value)
        game = Path(self.eql_game_dir)
        if not game.is_dir():
            # custom install path: the Daybreak uninstall registry key
            # names the real dir — zero-config discovery (Windows only)
            reg = _registry_game_dir()
            if reg:
                self.eql_game_dir = reg
                game = Path(reg)
        if not self.eql_log_dir:
            self.eql_log_dir = str(game / "Logs")
        if not self.eql_maps_dir:
            self.eql_maps_dir = str(game / "maps")
        if not self.eql_maps_custom_dir:
            self.eql_maps_custom_dir = str(Path(self.eql_maps_dir) / "Dark Brewall")
        # The packaged app keeps state outside its (temporary) bundle dir, so
        # the default DB has to follow data_dir() rather than the CWD. Posix
        # separators: a sqlite URL with backslashes is not portable.
        if self.database_url == _DEFAULT_DB_URL:
            self.database_url = "sqlite:///" + data_path("companion.db").as_posix()
        return self

    # MCP (optional -- the advisor degrades to ungrounded counsel when absent)
    mcp_enabled: bool = True
    mcp_server_dir: str = ""                  # clone path; empty = wiki over HTTP
    mcp_node_path: str = "node"

    # App
    environment: str = "development"
    debug: bool = False
    frontend_origin: str = "http://localhost:3000"


settings = Settings()

# Resolved writable state root (see backend/paths.py); created on first use.
DATA_DIR = data_path()

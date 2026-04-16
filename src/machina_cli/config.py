"""Configuration management for machina-cli."""

import json
import os
from pathlib import Path
from typing import Optional

CONFIG_DIR = Path.home() / ".machina"
CONFIG_FILE = CONFIG_DIR / "config.json"
CREDS_FILE = CONFIG_DIR / "credentials.json"

DEFAULT_CONFIG = {
    "api_url": "https://api.machina.gg",
    "session_url": "https://session.machina.gg",
    "default_organization_id": "",
    "default_project_id": "",
    "client_api_url": "",
    "output_format": "table",
}


def ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    ensure_config_dir()
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    return dict(DEFAULT_CONFIG)


def save_config(config: dict):
    ensure_config_dir()
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    os.chmod(CONFIG_FILE, 0o600)


def get_config(key: str) -> Optional[str]:
    config = load_config()
    return config.get(key)


def set_config(key: str, value: str):
    config = load_config()
    config[key] = value
    save_config(config)


def _load_creds() -> dict:
    ensure_config_dir()
    if CREDS_FILE.exists():
        with open(CREDS_FILE) as f:
            return json.load(f)
    return {}


def _save_creds(creds: dict):
    ensure_config_dir()
    with open(CREDS_FILE, "w") as f:
        json.dump(creds, f, indent=2)
    os.chmod(CREDS_FILE, 0o600)


def store_credential(key: str, value: str):
    """Store a credential in ~/.machina/credentials.json (chmod 600)."""
    creds = _load_creds()
    creds[key] = value
    _save_creds(creds)


def get_credential(key: str) -> Optional[str]:
    """Retrieve a credential from ~/.machina/credentials.json."""
    return _load_creds().get(key)


def _clear_credential(key: str):
    """Remove a single credential from ~/.machina/credentials.json."""
    creds = _load_creds()
    if key in creds:
        del creds[key]
        _save_creds(creds)


def clear_credentials():
    """Remove all stored credentials."""
    if CREDS_FILE.exists():
        CREDS_FILE.unlink()


def get_api_url() -> str:
    return os.environ.get("MACHINA_API_URL") or get_config("api_url") or DEFAULT_CONFIG["api_url"]


def _is_jwt_expired(token: str) -> bool:
    """Check if a JWT token is expired by decoding the payload."""
    import base64
    import time
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return payload.get("exp", 0) < time.time()
    except Exception:
        return False


def resolve_auth_token() -> tuple[str, str]:
    """
    Resolve authentication token.
    Returns (header_name, token_value).
    Priority: env var > stored api_key > stored session_token
    """
    # 1. Environment variable
    env_key = os.environ.get("MACHINA_API_KEY")
    if env_key:
        return ("X-Api-Token", env_key)

    # 2. Stored API key
    stored_key = get_credential("api_key")
    if stored_key:
        return ("X-Api-Token", stored_key)

    # 3. Stored session token (check expiry)
    stored_session = get_credential("session_token")
    if stored_session:
        if _is_jwt_expired(stored_session):
            # Clear expired token so user gets a clear "not authenticated" message
            _clear_credential("session_token")
            return ("", "")
        return ("X-Session-Token", stored_session)

    return ("", "")

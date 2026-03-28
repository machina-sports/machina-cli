"""Configuration management for machina-cli."""

import json
import os
from pathlib import Path
from typing import Optional

import keyring

CONFIG_DIR = Path.home() / ".machina"
CONFIG_FILE = CONFIG_DIR / "config.json"
KEYRING_SERVICE = "machina-cli"

DEFAULT_CONFIG = {
    "api_url": "https://api.machina.gg",
    "default_organization_id": "",
    "default_project_id": "",
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
    # Restrict permissions on config file
    os.chmod(CONFIG_FILE, 0o600)


def get_config(key: str) -> Optional[str]:
    config = load_config()
    return config.get(key)


def set_config(key: str, value: str):
    config = load_config()
    config[key] = value
    save_config(config)


def store_credential(key: str, value: str):
    """Store a credential in the OS keyring, fallback to file."""
    try:
        keyring.set_password(KEYRING_SERVICE, key, value)
    except Exception:
        # Fallback: store in config file
        creds_file = CONFIG_DIR / "credentials.json"
        creds = {}
        if creds_file.exists():
            with open(creds_file) as f:
                creds = json.load(f)
        creds[key] = value
        with open(creds_file, "w") as f:
            json.dump(creds, f, indent=2)
        os.chmod(creds_file, 0o600)


def get_credential(key: str) -> Optional[str]:
    """Retrieve a credential from the OS keyring, fallback to file."""
    try:
        value = keyring.get_password(KEYRING_SERVICE, key)
        if value:
            return value
    except Exception:
        pass

    # Fallback: read from file
    creds_file = CONFIG_DIR / "credentials.json"
    if creds_file.exists():
        with open(creds_file) as f:
            creds = json.load(f)
        return creds.get(key)
    return None


def clear_credentials():
    """Remove all stored credentials."""
    for key in ("api_key", "session_token"):
        try:
            keyring.delete_password(KEYRING_SERVICE, key)
        except Exception:
            pass

    creds_file = CONFIG_DIR / "credentials.json"
    if creds_file.exists():
        creds_file.unlink()


def get_api_url() -> str:
    return os.environ.get("MACHINA_API_URL") or get_config("api_url") or DEFAULT_CONFIG["api_url"]


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

    # 3. Stored session token
    stored_session = get_credential("session_token")
    if stored_session:
        return ("X-Session-Token", stored_session)

    return ("", "")

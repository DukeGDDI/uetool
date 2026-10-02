"""Steam / Apple passwords in the OS keychain. Never written to a file.

They reach uetool only as UETOOL_STEAM_PASSWORD / UETOOL_APPLE_APP_PASSWORD in the
child process's environment (see env_for).
"""
import keyring
from keyring.errors import KeyringError

SERVICE = "uetool-ui"


def _name(kind: str, account: str) -> str:
    return f"{kind}:{account}"


def available() -> bool:
    try:
        from keyring.backends import fail
        return not isinstance(keyring.get_keyring(), fail.Keyring)
    except Exception:
        return False


def get(kind: str, account: str) -> str | None:
    if not account:
        return None
    try:
        return keyring.get_password(SERVICE, _name(kind, account))
    except KeyringError:
        return None


def has(kind: str, account: str) -> bool:
    return bool(get(kind, account))


def set(kind: str, account: str, secret: str) -> None:
    keyring.set_password(SERVICE, _name(kind, account), secret)


def delete(kind: str, account: str) -> None:
    try:
        keyring.delete_password(SERVICE, _name(kind, account))
    except KeyringError:
        pass


def env_for(steam_user: str, apple_id: str) -> dict[str, str]:
    """Env vars carrying whichever secrets exist for the configured accounts."""
    env = {}
    if (pw := get("steam", steam_user)):
        env["UETOOL_STEAM_PASSWORD"] = pw
    if (pw := get("apple", apple_id)):
        env["UETOOL_APPLE_APP_PASSWORD"] = pw
    return env

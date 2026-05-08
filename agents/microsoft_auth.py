import os
import logging
import pathlib

import msal

logger = logging.getLogger("jarvis.microsoft")

TOKEN_FILE = "/root/.jarvis/microsoft_tokens.json"
TOKEN_DIR = "/root/.jarvis"
SCOPES = ["Mail.ReadWrite", "Mail.Send", "Tasks.ReadWrite", "Tasks.ReadWrite.Shared"]
AUTHORITY = "https://login.microsoftonline.com/consumers"
REDIRECT_URI = "https://herrlich.dev/oauth/microsoft/callback"


def _ensure_token_dir():
    p = pathlib.Path(TOKEN_DIR)
    if not p.exists():
        p.mkdir(mode=0o700, parents=True)
    else:
        os.chmod(TOKEN_DIR, 0o700)


def _load_token_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            cache.deserialize(f.read())
    return cache


def _save_token_cache(cache: msal.SerializableTokenCache):
    if cache.has_state_changed:
        _ensure_token_dir()
        with open(TOKEN_FILE, "w") as f:
            f.write(cache.serialize())
        os.chmod(TOKEN_FILE, 0o600)


def _get_msal_app(cache=None) -> msal.ConfidentialClientApplication:
    client_id = os.environ["MICROSOFT_CLIENT_ID"]
    client_secret = os.environ["MICROSOFT_CLIENT_SECRET"]
    return msal.ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=AUTHORITY,
        token_cache=cache,
    )


def get_login_url(state: str) -> str:
    app = _get_msal_app()
    return app.get_authorization_request_url(
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
        state=state,
    )


def handle_callback(code: str) -> dict:
    cache = _load_token_cache()
    app = _get_msal_app(cache=cache)
    result = app.acquire_token_by_authorization_code(
        code=code,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    if "access_token" not in result:
        logger.error(f"OAuth-Callback fehlgeschlagen: {result}")
        _save_token_cache(cache)
        raise Exception(
            f"Token-Abruf fehlgeschlagen: "
            f"{result.get('error')} — {result.get('error_description')}"
        )
    _save_token_cache(cache)
    logger.info("Microsoft OAuth: Token erfolgreich gespeichert")
    return result


def get_access_token() -> str:
    cache = _load_token_cache()
    app = _get_msal_app(cache=cache)
    accounts = app.get_accounts()
    if not accounts:
        raise RuntimeError(
            "Kein gültiger Token, bitte /oauth/microsoft/login im Browser aufrufen"
        )
    result = app.acquire_token_silent(scopes=SCOPES, account=accounts[0])
    if not result or "access_token" not in result:
        raise RuntimeError(
            "Kein gültiger Token, bitte /oauth/microsoft/login im Browser aufrufen"
        )
    _save_token_cache(cache)
    return result["access_token"]

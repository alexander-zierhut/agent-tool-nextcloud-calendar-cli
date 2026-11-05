"""Authentication — log in (browser login flow or app password), log out, inspect."""

from __future__ import annotations

import os
import sys
import time

import httpx
import typer

from ..config import Config, Profile, system_timezone
from ..errors import AuthError, ConfigError, OpError
from ..spec import SPEC, app_password_url, credentials
from ._shared import ctx_obj

app = typer.Typer(no_args_is_help=True)

_FLOW_TIMEOUT = 600  # seconds; Nextcloud's own flow token lives 20 min


def _prompt(text: str) -> str:
    """Prompt on stderr so stdout stays a clean machine channel."""
    sys.stderr.write(text)
    sys.stderr.flush()
    return (sys.stdin.readline() or "").strip()


def _normalize_server(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url:
        raise ConfigError("a Nextcloud address is required, e.g. https://cloud.example.com")
    if not url.startswith(("http://", "https://")):
        # Nobody types the scheme. Assume TLS rather than rejecting.
        url = "https://" + url
    return url


def _login_flow(base: str, verify: bool) -> tuple[str, str]:
    """Nextcloud Login Flow v2: the human approves in the browser, we receive a
    fresh app password. Nothing is typed or pasted, nothing lands in shell history.

    Uses its own httpx client (the flow endpoints are unauthenticated), so every
    transport failure is mapped to a ConfigError here; otherwise a typo'd host
    would surface as a traceback instead of the JSON error contract."""
    try:
        with httpx.Client(verify=verify, timeout=20, headers={"User-Agent": "agent-tool-nextcloud-calendar-cli"}) as h:
            r = h.post(f"{base}/index.php/login/v2")
            if r.status_code != 200:
                raise ConfigError(f"{base} does not offer the Nextcloud login flow (HTTP {r.status_code}). Use --token-stdin with an app password.")
            data = r.json()
            login_url, poll = data["login"], data["poll"]
            sys.stderr.write(
                "\nOpen this URL, log in and grant access (it creates an app password for this tool):\n"
                f"  {login_url}\n\nWaiting for approval (up to {_FLOW_TIMEOUT // 60} min)...\n"
            )
            sys.stderr.flush()
            try:
                import webbrowser

                webbrowser.open(login_url)
            except Exception:  # noqa: BLE001, S110 - no browser is fine, the URL is printed
                pass
            deadline = time.monotonic() + _FLOW_TIMEOUT
            while time.monotonic() < deadline:
                time.sleep(2)
                p = h.post(poll["endpoint"], data={"token": poll["token"]})
                if p.status_code == 200:
                    got = p.json()
                    return got["loginName"], got["appPassword"]
                if p.status_code != 404:
                    raise ConfigError(f"login flow failed (HTTP {p.status_code}).")
    except httpx.HTTPError as exc:
        raise ConfigError(f"cannot reach {base}: {exc.__class__.__name__}: {exc}. Check the address (or --insecure for self-signed test servers).") from exc
    except (KeyError, ValueError, TypeError) as exc:
        raise ConfigError(f"{base} answered the login flow with an unexpected response ({exc!r}). Is this a Nextcloud server?") from exc
    raise ConfigError("login flow timed out: nobody approved the request in the browser.")


@app.command("login")
def login(
    ctx: typer.Context,
    url: str = typer.Option(None, "--url", help="Your Nextcloud address, e.g. https://cloud.example.com (env: NEXTCLOUDCALENDAR_URL)."),
    user: str = typer.Option(None, "--user", help="Login name (env: NEXTCLOUDCALENDAR_USER). Not needed with the browser flow."),
    token: str = typer.Option(None, "--token", help="An existing app password. Prefer --token-stdin (keeps it out of argv) or the browser flow."),
    token_stdin: bool = typer.Option(False, "--token-stdin", help="Read an existing app password from stdin (keeps it out of argv and shell history)."),
    web: bool = typer.Option(False, "--web", help="Browser login flow even without a terminal (prints the URL, waits for approval)."),
    address: list[str] = typer.Option(None, "--address", help="Extra e-mail address that means 'me' in invitations (repeatable)."),
    timezone: str = typer.Option(None, "--timezone", help="IANA zone for floating times and output (default: this machine's)."),
    profile: str = typer.Option(None, "--profile", help="Profile to write (default: the active one)."),
    insecure: bool = typer.Option(False, "--insecure", help="Skip TLS verification (self-signed test servers only)."),
) -> None:
    """Log in and store the app password in the OS keyring.

    Example: `nextcloud-calendar auth login --url https://cloud.example.com --web`
    opens the browser; approve there. With an existing app password:
    `printf %s "$PW" | nextcloud-calendar auth login --url ... --user alex --token-stdin`.
    The login is verified BEFORE anything is saved. Headless agents skip this and
    set NEXTCLOUDCALENDAR_URL, _USER and _TOKEN instead.
    """
    obj = ctx_obj(ctx)

    raw_url = url or os.environ.get(SPEC.env("URL")) or os.environ.get("NEXTCLOUD_URL") or ""
    if not raw_url:
        if not sys.stdin.isatty():
            raise ConfigError("--url is required when stdin is not a terminal.")
        raw_url = _prompt("Nextcloud address (https://...): ")
    base = _normalize_server(raw_url)
    user = user or os.environ.get(SPEC.env("USER")) or os.environ.get("NEXTCLOUD_USER")

    if token_stdin:
        token = sys.stdin.readline().strip()
        if not token:
            raise ConfigError("--token-stdin was given but stdin was empty.")
    if token:
        if not user:
            raise ConfigError("--user is required with an app password.")
    else:
        if not (web or sys.stdin.isatty() or sys.stderr.isatty()):
            raise ConfigError("no terminal. Pass --web for the browser login flow, or --token-stdin with an app password.")
        user, token = _login_flow(base, not insecure)

    from ..client import Client
    from ..dav import Dav

    # Verify BEFORE persisting: storing a bad password just moves the failure to a
    # later, more confusing command that no longer has "I just typed this" context.
    client = Client(base, user, token, verify_ssl=not insecure)
    try:
        principal = Dav(client).principal()
    except AuthError as exc:
        raise AuthError(f"{base} rejected that login: {exc.message} Create an app password at {app_password_url(base)}.") from exc
    finally:
        client.close()

    name = profile or obj.config.active_profile_name()
    addresses = list(dict.fromkeys([*(a.lower() for a in principal.get("addresses", [])), *(a.lower() for a in (address or []))]))
    # Token first, config second: a failed keyring write must not leave a profile
    # behind that looks configured but has no credentials.
    backend = credentials.store_token(name, token)
    cfg = Config.load()
    p = Profile(name=name, base_url=base, username=user, addresses=addresses,
                default_calendar=principal.get("defaultCalendar"),
                timezone=timezone or system_timezone(), verify_ssl=not insecure)
    cfg.upsert_profile(p)
    cfg.save()
    obj.emitter.emit({
        "profile": name, "baseUrl": base, "user": user, "displayName": principal.get("displayName"),
        "addresses": addresses, "timezone": p.timezone, "defaultCalendar": p.default_calendar, "storedIn": backend,
    })


@app.command("status")
def status(ctx: typer.Context) -> None:
    """Which login/backend is in use, and whether the server accepts it. Never fails."""
    obj = ctx_obj(ctx)
    name = obj.config.active_profile_name()
    out: dict = {
        "profile": name,
        "tokenEnvVars": list(SPEC.token_env_names()),
        "configPath": str(SPEC.config_file()),
    }
    try:
        prof = obj.config.resolve()
    except OpError as exc:
        out.update({"configured": False, "reason": exc.message})
        obj.emitter.emit(out)
        return
    has = bool(credentials.get_token(name))
    out.update({
        "configured": True,
        "baseUrl": prof.base_url,
        "user": prof.username,
        "addresses": prof.addresses,
        "timezone": prof.timezone or system_timezone(),
        "hasToken": has,
        "tokenBackend": credentials.backend_name() if has else None,
        "tokenUrl": app_password_url(prof.base_url),
    })
    # Say it out loud when the environment is beating the keyring/file.
    hit = credentials._env_token_hit()
    if hit and (SPEC.config_file().exists() or obj.config.profiles):
        out["note"] = f"${hit[0]} is set and takes precedence over any keyring login. Unset it to use your stored credentials."
    if has:
        try:
            pr = obj.dav().principal()
            out.update({"reachable": True, "displayName": pr.get("displayName"), "serverAddresses": pr.get("addresses")})
        except OpError as exc:
            out.update({"reachable": False, "reason": exc.message})
    obj.emitter.emit(out)


@app.command("profiles")
def profiles(ctx: typer.Context) -> None:
    """List every configured profile and which one is active."""
    obj = ctx_obj(ctx)
    cfg: Config = obj.config
    active = cfg.active_profile_name()
    rows = [
        {
            "profile": pname,
            "active": pname == active,
            "baseUrl": p.base_url,
            "user": p.username,
            "timezone": p.timezone,
            "hasToken": bool(credentials.get_token(pname)),
        }
        for pname, p in sorted(cfg.profiles.items())
    ]
    obj.emitter.emit(rows, columns=[("Profile", "profile"), ("Active", "active"), ("Server", "baseUrl"),
                                    ("User", "user"), ("Token", "hasToken")])


@app.command("whoami")
def whoami(ctx: typer.Context) -> None:
    """The logged-in principal: display name, e-mail addresses, default calendar."""
    obj = ctx_obj(ctx)
    pr = obj.dav().principal()
    obj.emitter.emit({**pr, "me": obj.me()})


@app.command("logout")
def logout(ctx: typer.Context, profile: str = typer.Option(None, "--profile", help="Profile to log out (default: the active one).")) -> None:
    """Delete the stored app password (revoke it in Nextcloud too: Settings -> Security).

    The profile's address and settings stay; `auth login --profile <name>` re-adds
    just the password.
    """
    obj = ctx_obj(ctx)
    name = profile or obj.config.active_profile_name()
    credentials.delete_token(name)
    obj.emitter.emit({"status": "logged out", "profile": name,
                      "note": "the app password still exists on the server; revoke it under Settings -> Security."})

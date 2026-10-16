"""Filing issues on GitHub as the org's GitHub App (#1677).

The backend acts as UCSH Github Org Automation App, the same app org-automation's workflows post as.
An app has no long-lived token: it signs a short JWT with its private key, trades it for an
installation token that lasts an hour, and acts with that. So nothing here ever expires - a
fine-grained personal token was the alternative, and the org caps those at a month.

Three settings, all on the backend service:
- `GITHUB_APP_CLIENT_ID` - the app's client id, the JWT's issuer (GitHub recommends it over the app id).
- `GITHUB_APP_PRIVATE_KEY` - a PEM private key of the app. Railway's own, generated for it alone, so
  it can be revoked without touching the key org-automation holds.
- `GITHUB_REPORT_REPO` - owner/name of the repository reports are filed on.

Unconfigured means disabled, as with email: a PR environment has none of them and files nothing.
"""

import calendar
import logging
import os
import threading
import time
from dataclasses import dataclass

import httpx
import jwt

logger = logging.getLogger(__name__)

API = "https://api.github.com"
_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "uc-nexus",
}
# GitHub refuses a JWT whose exp is more than 10 minutes out. iat is set back 60s for clock drift,
# as GitHub's own guide does, and exp stays a minute short of the cap for the same reason.
_JWT_BACKDATE_SECONDS = 60
_JWT_LIFETIME_SECONDS = 540
# An installation token lasts an hour. It is replaced this long before it runs out, so a request never
# leaves with one that expires on the way.
_TOKEN_REFRESH_MARGIN_SECONDS = 300


class GitHubError(Exception):
    """GitHub refused or could not be reached."""


@dataclass(frozen=True)
class GitHubAppConfig:
    client_id: str
    private_key: str
    repo: str


def get_config() -> GitHubAppConfig | None:
    client_id = (os.getenv("GITHUB_APP_CLIENT_ID") or "").strip()
    private_key = (os.getenv("GITHUB_APP_PRIVATE_KEY") or "").strip()
    repo = (os.getenv("GITHUB_REPORT_REPO") or "").strip()
    if not (client_id and private_key and repo):
        return None
    # A key pasted somewhere that cannot hold line breaks arrives with them escaped.
    if "\n" not in private_key:
        private_key = private_key.replace("\\n", "\n")
    return GitHubAppConfig(client_id=client_id, private_key=private_key, repo=repo)


def is_configured() -> bool:
    return get_config() is not None


@dataclass
class _CachedToken:
    token: str
    # time.time() seconds, from GitHub's expires_at.
    expires_at: float
    repo: str


_lock = threading.Lock()
_cached: _CachedToken | None = None
_client = httpx.Client(base_url=API, timeout=20.0, headers=_HEADERS)


def app_jwt(config: GitHubAppConfig, *, now: float | None = None) -> str:
    """The app's own JWT, good for asking GitHub for an installation token and nothing else."""
    issued = int(now if now is not None else time.time()) - _JWT_BACKDATE_SECONDS
    payload = {"iat": issued, "exp": issued + _JWT_BACKDATE_SECONDS + _JWT_LIFETIME_SECONDS, "iss": config.client_id}
    return jwt.encode(payload, config.private_key, algorithm="RS256")


def _parse_expiry(value: str) -> float:
    # GitHub's form: 2026-10-16T14:05:00Z, always UTC.
    return calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ"))


def _request(method: str, path: str, *, bearer: str, json: dict | None = None) -> dict:
    try:
        resp = _client.request(method, path, headers={"Authorization": f"Bearer {bearer}"}, json=json)
    except httpx.HTTPError as exc:
        raise GitHubError(f"GitHub could not be reached: {exc}") from exc
    if resp.status_code >= 400:
        # GitHub's message names the problem (bad credentials, not installed, no permission); the body
        # carries nothing secret.
        try:
            message = resp.json().get("message") or resp.text
        except ValueError:
            message = resp.text
        raise GitHubError(f"GitHub refused {method} {path}: {resp.status_code} {message}")
    try:
        data = resp.json()
    except ValueError as exc:
        # A proxy or an outage page answering 200 with HTML is GitHub not answering.
        raise GitHubError(f"GitHub answered {method} {path} with something that is not JSON") from exc
    if not isinstance(data, dict):
        raise GitHubError(f"GitHub answered {method} {path} with an unexpected shape")
    return data


def _field(data: dict, key: str, what: str):
    try:
        return data[key]
    except KeyError as exc:
        raise GitHubError(f"GitHub's {what} carried no {key}") from exc


def installation_token(config: GitHubAppConfig) -> str:
    """An installation token for the report repository, minted once and reused until near expiry."""
    global _cached
    with _lock:
        now = time.time()
        if _cached and _cached.repo == config.repo and _cached.expires_at - _TOKEN_REFRESH_MARGIN_SECONDS > now:
            return _cached.token
        app_token = app_jwt(config, now=now)
        # The repository names its own installation, so there is no installation id to configure.
        installation = _request("GET", f"/repos/{config.repo}/installation", bearer=app_token)
        installation_id = _field(installation, "id", "installation")
        minted = _request("POST", f"/app/installations/{installation_id}/access_tokens", bearer=app_token)
        try:
            expires_at = _parse_expiry(_field(minted, "expires_at", "installation token"))
        except ValueError as exc:
            raise GitHubError("GitHub's installation token carried an unreadable expiry") from exc
        _cached = _CachedToken(
            token=_field(minted, "token", "installation token"), expires_at=expires_at, repo=config.repo
        )
        return _cached.token


def forget_token() -> None:
    """Drop the cached installation token. For tests, and after GitHub says it is no longer good."""
    global _cached
    with _lock:
        _cached = None


@dataclass(frozen=True)
class FiledIssue:
    number: int
    url: str


def create_issue(*, title: str, body: str) -> FiledIssue:
    """File one issue on the report repository. Raises GitHubError when it is not filed."""
    config = get_config()
    if config is None:
        raise GitHubError("GitHub is not configured on this deployment")
    token = installation_token(config)
    try:
        issue = _request("POST", f"/repos/{config.repo}/issues", bearer=token, json={"title": title, "body": body})
        filed = FiledIssue(number=_field(issue, "number", "issue"), url=_field(issue, "html_url", "issue"))
    except GitHubError:
        # A token revoked or rotated under the cache: the next report mints a fresh one.
        forget_token()
        raise
    logger.info("Filed issue #%s on %s", filed.number, config.repo)
    return filed

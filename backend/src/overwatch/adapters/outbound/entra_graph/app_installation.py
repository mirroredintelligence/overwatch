"""Is our staff app installed in this directory, and what has it been granted? (DEC-1316 item 5)

Two calls, both in the organisation's own directory, so this is proof that no redirect can give:

1. An application token for the directory (client credentials: `POST
   https://login.microsoftonline.com/<directory>/oauth2/v2.0/token`, scope
   `https://graph.microsoft.com/.default`, our client secret from the secret store entry
   `entra-staff-client-secret`). The directory refuses to issue one when our app has no service
   principal there (AADSTS700016): that is the answer "not installed", not a fault.
2. `GET /v1.0/servicePrincipals(appId='<client id>')` with that token (404 means not installed),
   then `GET /v1.0/servicePrincipals/{id}/appRoleAssignments`, with each resource's `appRoles`
   read to turn an assignment's role id into the permission name (so no role GUID is hard coded).

Anything else that goes wrong (a refused secret, a 5xx, a throttle, a body that is not what Graph
sends, a timeout) is `GraphUnavailable`: the invite is left as it was. The client secret, the
token and every response body are never logged or put in an error; only fixed words are.

[VERIFY] The shapes follow Microsoft's published Graph and token-endpoint documentation; the
real call has not been made from the build session (no consent exists yet).
"""

import logging
from typing import Any, Final

import httpx

from overwatch.application.ports.outbound.admin_consent import AppInstallation, GraphUnavailable
from overwatch.application.ports.outbound.tokens import SecretStore
from overwatch.domain.errors import NotFound

_log = logging.getLogger(__name__)
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

CLIENT_SECRET_NAME: Final = "entra-staff-client-secret"
TOKEN_URL: Final = "https://login.microsoftonline.com/{directory}/oauth2/v2.0/token"
GRAPH: Final = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE: Final = "https://graph.microsoft.com/.default"
_APP_NOT_IN_DIRECTORY: Final = 700016
_TIMEOUT_S: Final = 20.0
_MAX_PAGES: Final = 5
_MAX_RESOURCES: Final = 5

NOT_INSTALLED_REASON: Final = "our app has no service principal in this directory"


class GraphAppInstallationCheck:
    def __init__(self, http: httpx.AsyncClient, secrets: SecretStore, client_id: str) -> None:
        self._http = http
        self._secrets = secrets
        self._client_id = client_id

    async def check(self, directory_id: str) -> AppInstallation:
        token = await self._token(directory_id)
        if token is None:
            return AppInstallation(False, reason=NOT_INSTALLED_REASON)
        headers = {"Authorization": f"Bearer {token}"}
        principal = await self._get(
            f"{GRAPH}/servicePrincipals(appId='{self._client_id}')?$select=id", headers, ok_404=True
        )
        if principal is None:
            return AppInstallation(False, reason=NOT_INSTALLED_REASON)
        principal_id = principal.get("id")
        if type(principal_id) is not str or not principal_id.replace("-", "").isalnum():
            raise GraphUnavailable("graph answered with an unexpected body")
        assignments = await self._pages(
            f"{GRAPH}/servicePrincipals/{principal_id}/appRoleAssignments", headers
        )
        return AppInstallation(True, await self._role_values(assignments, headers))

    # ------------------------------------------------------------------ the token

    async def _token(self, directory_id: str) -> str | None:
        try:
            secret = self._secrets.get(CLIENT_SECRET_NAME).decode("utf-8").strip()
        except NotFound, UnicodeDecodeError:
            raise GraphUnavailable("the client secret is not available") from None
        if not secret:
            raise GraphUnavailable("the client secret is not available")
        try:
            response = await self._http.post(
                TOKEN_URL.format(directory=directory_id),
                data={
                    "client_id": self._client_id,
                    "client_secret": secret,
                    "scope": GRAPH_SCOPE,
                    "grant_type": "client_credentials",
                },
                timeout=_TIMEOUT_S,
            )
        except httpx.HTTPError:
            raise GraphUnavailable("the token endpoint could not be reached") from None
        if response.status_code == 200:
            body = _json(response)
            token = None if body is None else body.get("access_token")
            if type(token) is not str or not token:
                raise GraphUnavailable("the token endpoint answered with an unexpected body")
            return token
        if response.status_code in (400, 401):
            body = _json(response)
            codes = None if body is None else body.get("error_codes")
            if isinstance(codes, list) and _APP_NOT_IN_DIRECTORY in codes:
                return None
        _log.warning("the token endpoint refused: status %s", response.status_code)
        raise GraphUnavailable("the token endpoint refused the request")

    # ------------------------------------------------------------------ graph reads

    async def _get(
        self, url: str, headers: dict[str, str], *, ok_404: bool = False
    ) -> dict[str, Any] | None:
        try:
            response = await self._http.get(url, headers=headers, timeout=_TIMEOUT_S)
        except httpx.HTTPError:
            raise GraphUnavailable("graph could not be reached") from None
        if response.status_code == 404 and ok_404:
            return None
        if response.status_code != 200:
            _log.warning("graph refused: status %s", response.status_code)
            raise GraphUnavailable("graph refused the request")
        body = _json(response)
        if body is None:
            raise GraphUnavailable("graph answered with an unexpected body")
        return body

    async def _pages(self, url: str, headers: dict[str, str]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_url: str | None = url
        for _ in range(_MAX_PAGES):
            if next_url is None:
                return items
            body = await self._get(next_url, headers)
            assert body is not None
            value = body.get("value")
            if not isinstance(value, list):
                raise GraphUnavailable("graph answered with an unexpected body")
            items.extend(item for item in value if isinstance(item, dict))
            link = body.get("@odata.nextLink")
            next_url = link if type(link) is str and link.startswith(GRAPH + "/") else None
        raise GraphUnavailable("graph answered with too many pages")

    async def _role_values(
        self, assignments: list[dict[str, Any]], headers: dict[str, str]
    ) -> frozenset[str]:
        by_resource: dict[str, set[str]] = {}
        for item in assignments:
            resource, role = item.get("resourceId"), item.get("appRoleId")
            if type(resource) is str and type(role) is str:
                by_resource.setdefault(resource, set()).add(role)
        if len(by_resource) > _MAX_RESOURCES:
            raise GraphUnavailable("graph answered with too many resources")
        values: set[str] = set()
        for resource, role_ids in by_resource.items():
            if not resource.replace("-", "").isalnum():
                raise GraphUnavailable("graph answered with an unexpected body")
            body = await self._get(
                f"{GRAPH}/servicePrincipals/{resource}?$select=appRoles", headers
            )
            assert body is not None
            roles = body.get("appRoles")
            if not isinstance(roles, list):
                raise GraphUnavailable("graph answered with an unexpected body")
            for role in roles:
                if isinstance(role, dict) and role.get("id") in role_ids:
                    value = role.get("value")
                    if type(value) is str:
                        values.add(value)
        return frozenset(values)


def _json(response: httpx.Response) -> dict[str, Any] | None:
    try:
        body = response.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None

"""The groups of an organisation's directory, over Microsoft Graph (DEC-1317).

Every call carries an application token for the organisation's directory (client credentials, our
staff app, the secret `entra-staff-client-secret` from the secret store, scope
`https://graph.microsoft.com/.default`), so it is limited to what the administrator consented to
(`Group.ReadWrite.All`, `GroupMember.ReadWrite.All`, `User.Read.All`,
`AppRoleAssignment.ReadWrite.All`, `Application.Read.All`, and, to invite a person from another
organisation, `User.Invite.All`, which a consent given earlier may lack: the refusal is then
`InviteNotPermitted`). The token is cached in memory for its
life, per directory, and never logged. A name or address that reaches a URL is checked first and
quoted for OData; an id that reaches a URL path is checked as a GUID.

Failures. A group Graph says is not there (404) is `GroupMissing`. Anything else that is not what
we expected (a refused secret, a 4xx or 5xx, a throttle, a body of another shape, a timeout, more
than one group of a name, more than one user of an address) is `GraphUnavailable` with fixed words.
No response body, token, secret or directory id is put in an error or a log line.

[VERIFY] The request shapes follow Microsoft's published Graph documentation (create group, list
groups, appRoleAssignedTo, members/$ref); none has been called from the build session.
"""

import asyncio
import logging
import re
import time
from typing import Any, Final

import httpx

from overwatch.application.ports.outbound.admin_consent import GraphUnavailable
from overwatch.application.ports.outbound.entra_groups import (
    DirectoryMember,
    GroupMissing,
    InviteNotPermitted,
)
from overwatch.application.ports.outbound.tokens import SecretStore
from overwatch.domain.errors import NotFound
from overwatch.domain.rules.entra_groups import SEARCH_RESULTS_MAX

_log = logging.getLogger(__name__)
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

CLIENT_SECRET_NAME: Final = "entra-staff-client-secret"
TOKEN_URL: Final = "https://login.microsoftonline.com/{directory}/oauth2/v2.0/token"
GRAPH: Final = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE: Final = "https://graph.microsoft.com/.default"
# Where a guest lands after redeeming the invitation: their own apps page, which lists Overwatch.
INVITE_REDIRECT: Final = "https://myapplications.microsoft.com"
_TIMEOUT_S: Final = 20.0
_MAX_PAGES: Final = 10
_EARLY_S: Final = 120
# A group made a moment ago is not yet visible to the service that assigns app roles: it answers
# 400 (Request_BadRequest) until it is. Assigning waits and tries again, a few times, for that case
# only.
_ASSIGN_ATTEMPTS: Final = 6
_ASSIGN_WAIT_S: Final = 5.0
_GUID: Final = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_NAME: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}")
_ADDRESS: Final = re.compile(r"[A-Za-z0-9._%+'-]{1,64}@[A-Za-z0-9][A-Za-z0-9.-]{0,251}")
_SEARCH_TERM: Final = re.compile(r"[A-Za-z0-9 .'@+_-]{2,64}")


def _guid(value: str) -> str:
    if type(value) is not str or _GUID.fullmatch(value.lower()) is None:
        raise GraphUnavailable("an id is not in the form the directory uses")
    return value.lower()


def _odata_quote(value: str) -> str:
    return value.replace("'", "''")


_GUID_IN_PATH: Final = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_CODE: Final = re.compile(r"[A-Za-z][A-Za-z0-9_.]{0,63}")


def _shape(url: str) -> str:
    """The path of a Graph call with every id taken out, for the log."""
    return _GUID_IN_PATH.sub("{id}", url.removeprefix(GRAPH))


def _error_code(response: httpx.Response) -> str:
    body = _json(response)
    error = None if body is None else body.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) and _CODE.fullmatch(code) else "none"


def _request_id(response: httpx.Response) -> str:
    value = response.headers.get("request-id", "")
    return value if _GUID_IN_PATH.fullmatch(value) else "none"


class GraphEntraGroups:
    def __init__(
        self,
        http: httpx.AsyncClient,
        secrets: SecretStore,
        client_id: str,
        *,
        clock: Any = time.monotonic,
        sleep: Any = asyncio.sleep,
        site_url: str | None = None,
    ) -> None:
        # The site's own address (scheme and host). With it, an invited guest who accepts lands on
        # the organisation's own sign-in link and is signed in; without it, on their apps page.
        self._site_url = None if site_url is None else site_url.rstrip("/")
        self._http = http
        self._sleep = sleep
        self._secrets = secrets
        self._client_id = client_id
        self._clock = clock
        self._tokens: dict[str, tuple[str, float]] = {}

    # ------------------------------------------------------------------ the port

    async def find_group(self, directory_id: str, name: str) -> str | None:
        if _NAME.fullmatch(name) is None:
            raise GraphUnavailable("a group name is not in the form we make")
        body = await self._request(
            directory_id,
            "GET",
            f"{GRAPH}/groups",
            params={
                "$filter": f"displayName eq '{_odata_quote(name)}'",
                "$select": "id,displayName",
            },
        )
        assert body is not None
        found = [
            item["id"]
            for item in _values(body)
            if item.get("displayName") == name and type(item.get("id")) is str
        ]
        if len(found) > 1:
            raise GraphUnavailable("more than one group has that name")
        return _guid(found[0]) if found else None

    async def create_group(self, directory_id: str, name: str, description: str) -> str:
        if _NAME.fullmatch(name) is None:
            raise GraphUnavailable("a group name is not in the form we make")
        body = await self._request(
            directory_id,
            "POST",
            f"{GRAPH}/groups",
            json={
                "displayName": name,
                "description": description[:200],
                "mailEnabled": False,
                "mailNickname": name[:64],
                "securityEnabled": True,
            },
            ok=(201,),
        )
        assert body is not None
        new_id = body.get("id")
        if type(new_id) is not str:
            raise GraphUnavailable("the directory answered with an unexpected body")
        return _guid(new_id)

    async def group_name(self, directory_id: str, group_id: str) -> str:
        body = await self._request(
            directory_id,
            "GET",
            f"{GRAPH}/groups/{_guid(group_id)}",
            params={"$select": "displayName"},
            missing_is_group=True,
        )
        assert body is not None
        name = body.get("displayName")
        if type(name) is not str:
            raise GraphUnavailable("the directory answered with an unexpected body")
        return name

    async def assign_app_role(
        self, directory_id: str, service_principal_id: str, group_id: str, app_role_id: str
    ) -> bool:
        principal = _guid(service_principal_id)
        group = _guid(group_id)
        role = _guid(app_role_id)
        url = f"{GRAPH}/servicePrincipals/{principal}/appRoleAssignedTo"
        for item in await self._pages(directory_id, url, {"$top": "100"}, missing_is_group=False):
            if str(item.get("principalId", "")).lower() == group and (
                str(item.get("appRoleId", "")).lower() == role
            ):
                return False
        body = {"principalId": group, "resourceId": principal, "appRoleId": role}
        for attempt in range(1, _ASSIGN_ATTEMPTS + 1):
            response = await self._send(directory_id, "POST", url, json=body)
            if response.status_code == 201:
                return True
            if response.status_code == 404:
                raise GroupMissing
            if (
                response.status_code == 400
                and _error_code(response) == "Request_BadRequest"
                and attempt < _ASSIGN_ATTEMPTS
            ):
                await self._sleep(_ASSIGN_WAIT_S)
                continue
            self._refused("POST", url, response)
        raise GraphUnavailable("the directory refused the request")

    async def find_user(self, directory_id: str, address: str) -> str | None:
        if _ADDRESS.fullmatch(address) is None:
            raise GraphUnavailable("an address is not in the form we accept")
        quoted = _odata_quote(address)
        body = await self._request(
            directory_id,
            "GET",
            f"{GRAPH}/users",
            params={
                "$filter": f"mail eq '{quoted}' or userPrincipalName eq '{quoted}'",
                "$select": "id",
            },
        )
        assert body is not None
        ids = {_guid(item["id"]) for item in _values(body) if type(item.get("id")) is str}
        if len(ids) > 1:
            raise GraphUnavailable("more than one person has that address")
        return next(iter(ids), None)

    async def invite_user(self, directory_id: str, address: str) -> str:
        if _ADDRESS.fullmatch(address) is None:
            raise GraphUnavailable("an address is not in the form we accept")
        response = await self._send(
            directory_id,
            "POST",
            f"{GRAPH}/invitations",
            json={
                "invitedUserEmailAddress": address,
                "inviteRedirectUrl": self._invite_redirect(directory_id),
                "sendInvitationMessage": True,
            },
        )
        if response.status_code == 403:
            # The administrator has not given `User.Invite.All`, or guests are not allowed.
            _log.warning("graph refused an invitation: status 403 code %s", _error_code(response))
            raise InviteNotPermitted
        if response.status_code != 201:
            self._refused("POST", f"{GRAPH}/invitations", response)
        body = _json(response)
        invited = None if body is None else body.get("invitedUser")
        user_id = invited.get("id") if isinstance(invited, dict) else None
        if type(user_id) is not str:
            raise GraphUnavailable("the directory answered with an unexpected body")
        return _guid(user_id)

    def _invite_redirect(self, directory_id: str) -> str:
        if self._site_url is None:
            return INVITE_REDIRECT
        return f"{self._site_url}/api/bff/auth/entra/start?org={_guid(directory_id)}"

    async def search_users(self, directory_id: str, term: str) -> tuple[DirectoryMember, ...]:
        if _SEARCH_TERM.fullmatch(term) is None:
            raise GraphUnavailable("a search term is not in the form we accept")
        quoted = _odata_quote(term)
        body = await self._request(
            directory_id,
            "GET",
            f"{GRAPH}/users",
            params={
                "$filter": (
                    f"startswith(displayName,'{quoted}') or startswith(mail,'{quoted}') "
                    f"or startswith(userPrincipalName,'{quoted}')"
                ),
                "$select": "id,displayName,mail,userPrincipalName,userType",
                # More than the eight kept, so leaving out guests and sorting still fills them.
                "$top": "25",
            },
        )
        assert body is not None
        found: list[DirectoryMember] = []
        for item in _values(body):
            object_id = item.get("id")
            if type(object_id) is not str or item.get("userType") == "Guest":
                continue
            name = item.get("displayName")
            mail = item.get("mail") or item.get("userPrincipalName")
            found.append(
                DirectoryMember(
                    _guid(object_id),
                    name if type(name) is str else None,
                    mail if type(mail) is str else None,
                )
            )
        found.sort(key=lambda m: ((m.display_name or m.mail or "").lower(), m.object_id))
        return tuple(found[:SEARCH_RESULTS_MAX])

    async def add_member(self, directory_id: str, group_id: str, user_id: str) -> bool:
        group = _guid(group_id)
        user = _guid(user_id)
        response = await self._send(
            directory_id,
            "POST",
            f"{GRAPH}/groups/{group}/members/$ref",
            json={"@odata.id": f"{GRAPH}/directoryObjects/{user}"},
        )
        if response.status_code == 204:
            return True
        if response.status_code == 404:
            raise GroupMissing
        if response.status_code == 400 and _already_member(response):
            return False
        _log.warning("graph refused adding a member: status %s", response.status_code)
        raise GraphUnavailable("the directory refused the request")

    async def remove_member(self, directory_id: str, group_id: str, user_id: str) -> bool:
        group = _guid(group_id)
        user = _guid(user_id)
        response = await self._send(
            directory_id, "DELETE", f"{GRAPH}/groups/{group}/members/{user}/$ref"
        )
        if response.status_code == 204:
            return True
        if response.status_code == 404:
            # Graph answers 404 for a group that is gone and for a person who is not in it. Ask
            # the group, so the two are told apart.
            await self.group_name(directory_id, group)
            return False
        _log.warning("graph refused removing a member: status %s", response.status_code)
        raise GraphUnavailable("the directory refused the request")

    async def members(self, directory_id: str, group_id: str) -> tuple[DirectoryMember, ...]:
        items = await self._pages(
            directory_id,
            f"{GRAPH}/groups/{_guid(group_id)}/members/microsoft.graph.user",
            {"$select": "id,displayName,mail,userPrincipalName", "$top": "100"},
            missing_is_group=True,
        )
        out: list[DirectoryMember] = []
        for item in items:
            object_id = item.get("id")
            if type(object_id) is not str:
                continue
            name = item.get("displayName")
            mail = item.get("mail") or item.get("userPrincipalName")
            out.append(
                DirectoryMember(
                    _guid(object_id),
                    name if type(name) is str else None,
                    mail if type(mail) is str else None,
                )
            )
        return tuple(out)

    # ------------------------------------------------------------------ the token

    async def _token(self, directory_id: str) -> str:
        directory = _guid(directory_id)
        cached = self._tokens.get(directory)
        if cached is not None and cached[1] > self._clock():
            return cached[0]
        try:
            secret = self._secrets.get(CLIENT_SECRET_NAME).decode("utf-8").strip()
        except NotFound, UnicodeDecodeError:
            raise GraphUnavailable("the client secret is not available") from None
        if not secret:
            raise GraphUnavailable("the client secret is not available")
        try:
            response = await self._http.post(
                TOKEN_URL.format(directory=directory),
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
        body = _json(response) if response.status_code == 200 else None
        token = None if body is None else body.get("access_token")
        if type(token) is not str or not token:
            _log.warning("the token endpoint refused: status %s", response.status_code)
            raise GraphUnavailable("the token endpoint refused the request")
        lifetime = body.get("expires_in") if body is not None else None
        seconds = lifetime if type(lifetime) is int and lifetime > 0 else 300
        self._tokens[directory] = (token, self._clock() + max(seconds - _EARLY_S, 0))
        return token

    # ------------------------------------------------------------------ requests

    async def _send(
        self,
        directory_id: str,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {await self._token(directory_id)}"}
        try:
            return await self._http.request(
                method, url, headers=headers, params=params, json=json, timeout=_TIMEOUT_S
            )
        except httpx.HTTPError:
            raise GraphUnavailable("the directory could not be reached") from None

    @staticmethod
    def _refused(method: str, url: str, response: httpx.Response) -> None:
        """Log what was asked and Graph's own error code, so a refusal can be told from a delay:
        never the message (it can name a group or a person) and never the token. Then refuse."""
        _log.warning(
            "graph refused: %s %s status %s code %s request-id %s",
            method,
            _shape(url),
            response.status_code,
            _error_code(response),
            _request_id(response),
        )
        raise GraphUnavailable("the directory refused the request")

    async def _request(
        self,
        directory_id: str,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        ok: tuple[int, ...] = (200,),
        missing_is_group: bool = False,
    ) -> dict[str, Any] | None:
        response = await self._send(directory_id, method, url, params=params, json=json)
        if response.status_code == 404 and missing_is_group:
            raise GroupMissing
        if response.status_code not in ok:
            self._refused(method, url, response)
        body = _json(response)
        if body is None:
            raise GraphUnavailable("the directory answered with an unexpected body")
        return body

    async def _pages(
        self,
        directory_id: str,
        url: str,
        params: dict[str, str],
        *,
        missing_is_group: bool,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_url: str | None = url
        next_params: dict[str, str] | None = params
        for _ in range(_MAX_PAGES):
            if next_url is None:
                return items
            body = await self._request(
                directory_id, "GET", next_url, params=next_params, missing_is_group=missing_is_group
            )
            assert body is not None
            items.extend(_values(body))
            link = body.get("@odata.nextLink")
            next_url = link if type(link) is str and link.startswith(GRAPH + "/") else None
            next_params = None
        raise GraphUnavailable("the directory answered with too many pages")


def _values(body: dict[str, Any]) -> list[dict[str, Any]]:
    value = body.get("value")
    if not isinstance(value, list):
        raise GraphUnavailable("the directory answered with an unexpected body")
    return [item for item in value if isinstance(item, dict)]


def _json(response: httpx.Response) -> dict[str, Any] | None:
    try:
        body = response.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _already_member(response: httpx.Response) -> bool:
    body = _json(response)
    error = None if body is None else body.get("error")
    message = error.get("message") if isinstance(error, dict) else None
    return type(message) is str and "already exist" in message.lower()

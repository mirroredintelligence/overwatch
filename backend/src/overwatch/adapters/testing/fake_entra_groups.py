"""An in-memory Entra directory for tests (DEC-1317): the `EntraGroupDirectory` port, no network.

It holds groups, users, members and app role assignments for one or more directories, records every
call in `calls` (the method and the ids it was given, never an address), and can be made to fail.
Ids are deterministic. Addresses are matched case-insensitively, as the directory does.
"""

from itertools import count

from overwatch.application.ports.outbound.admin_consent import GraphUnavailable
from overwatch.application.ports.outbound.entra_groups import DirectoryMember, GroupMissing


class FakeEntraGroups:
    def __init__(self) -> None:
        self.groups: dict[str, dict[str, str]] = {}
        self.members_of: dict[tuple[str, str], list[str]] = {}
        self.assignments: set[tuple[str, str, str, str]] = set()
        self.users: dict[str, dict[str, str]] = {}
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.unavailable = False
        self._ids = count(1)

    def new_id(self, kind: str) -> str:
        return f"{next(self._ids):08x}-0000-4000-8000-{kind[:1].encode().hex():0>12}"

    def add_user(self, directory_id: str, address: str) -> str:
        user_id = self.new_id("user")
        self.users.setdefault(directory_id, {})[address.lower()] = user_id
        return user_id

    def delete_group(self, directory_id: str, group_id: str) -> None:
        self.groups.get(directory_id, {}).pop(group_id, None)
        self.members_of.pop((directory_id, group_id), None)

    def named(self, directory_id: str, name: str) -> str | None:
        return next((g for g, n in self.groups.get(directory_id, {}).items() if n == name), None)

    def _call(self, method: str, *ids: str) -> None:
        self.calls.append((method, ids))
        if self.unavailable:
            raise GraphUnavailable("the directory could not be reached")

    def _require(self, directory_id: str, group_id: str) -> None:
        if group_id not in self.groups.get(directory_id, {}):
            raise GroupMissing

    async def find_group(self, directory_id: str, name: str) -> str | None:
        self._call("find_group", directory_id)
        return self.named(directory_id, name)

    async def create_group(self, directory_id: str, name: str, description: str) -> str:
        self._call("create_group", directory_id)
        group_id = self.new_id("group")
        self.groups.setdefault(directory_id, {})[group_id] = name
        return group_id

    async def group_name(self, directory_id: str, group_id: str) -> str:
        self._call("group_name", directory_id, group_id)
        self._require(directory_id, group_id)
        return self.groups[directory_id][group_id]

    async def assign_app_role(
        self, directory_id: str, service_principal_id: str, group_id: str, app_role_id: str
    ) -> bool:
        self._call("assign_app_role", directory_id, service_principal_id, group_id, app_role_id)
        self._require(directory_id, group_id)
        key = (directory_id, service_principal_id, group_id, app_role_id)
        if key in self.assignments:
            return False
        self.assignments.add(key)
        return True

    async def find_user(self, directory_id: str, address: str) -> str | None:
        self._call("find_user", directory_id)
        return self.users.get(directory_id, {}).get(address.lower())

    async def add_member(self, directory_id: str, group_id: str, user_id: str) -> bool:
        self._call("add_member", directory_id, group_id, user_id)
        self._require(directory_id, group_id)
        held = self.members_of.setdefault((directory_id, group_id), [])
        if user_id in held:
            return False
        held.append(user_id)
        return True

    async def remove_member(self, directory_id: str, group_id: str, user_id: str) -> bool:
        self._call("remove_member", directory_id, group_id, user_id)
        self._require(directory_id, group_id)
        held = self.members_of.setdefault((directory_id, group_id), [])
        if user_id not in held:
            return False
        held.remove(user_id)
        return True

    async def members(self, directory_id: str, group_id: str) -> tuple[DirectoryMember, ...]:
        self._call("members", directory_id, group_id)
        self._require(directory_id, group_id)
        by_id = {uid: addr for addr, uid in self.users.get(directory_id, {}).items()}
        return tuple(
            DirectoryMember(uid, f"Person {i}", by_id.get(uid))
            for i, uid in enumerate(self.members_of.get((directory_id, group_id), []), 1)
        )

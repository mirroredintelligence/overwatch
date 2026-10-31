"""KeyVaultSecretStore: the platform's secrets read from Azure Key Vault (B8, DEC-1304).

It implements `SecretStore` (`get(name) -> bytes`, synchronous, so no caller changes) over a client
shaped like azure-keyvault-secrets' `SecretClient`, which the caller injects: the process wires
the real one behind the app's managed identity, a test wires a fake. Nothing here opens a
connection until the first read.

Names. `vault_secret_name` maps a reference to the vault's alphabet. A reference with no vault name
is `NotFound` and the vault is not called.

Cache (in memory, one per process, safe for threads):
- a good value is held for `cache_seconds` (default 600, `DIUCS_SECRET_CACHE_SECONDS`), so a
  rotation reaches a running process within ten minutes, and the vault is called at most once for
  a name in that time;
- only a success is cached: a miss, a refused name and an outage are never held;
- stale-if-error: when a refresh fails and a good value is held, that value is served for up to
  `stale_seconds` past its expiry (default 3600, `DIUCS_SECRET_STALE_SECONDS`), with a warning that
  names the secret and the type of the failure. The value is already in the process's memory, so
  this exposes nothing more, and an outage does not stop a clinical service within ten
  minutes. While
  serving stale the vault is asked again at most every `STALE_RETRY_SECONDS`, so a dead vault is not
  hammered by every request. Past the window the read fails closed. `stale_seconds=0` is strict;
- two threads reading one cold name make one vault call (a lock for each name; other names do not
  wait for it).

Errors. A secret the vault does not hold (the client's `ResourceNotFoundError`), or holds with no
value, is `NotFound`, and a held copy of it is dropped. Any other failure is
`SecretStoreUnavailable`, which no caller treats as "not configured". The text names the secret.

Values. A value is never in a log line, a repr, `vars()`, an exception message or a traceback: the
cache holds it behind a repr that hides it, the log names only the secret and the failure's type
(the provider's own text can carry a request id or a URL), and the exception that is raised does
not chain the provider's.

A read that misses blocks the calling thread for one vault round trip (tens to a few hundred
milliseconds; seconds while the client retries a throttled call). A caller on the event loop stalls
the loop for that long on a cold or refreshed read: `prefetch` reads a list of names at start-up so
the first requests are warm, and a refresh happens once per name per `cache_seconds`.
"""

import logging
import threading
import time
from collections.abc import Callable, Iterable
from typing import Any, Final, Protocol

from azure.core.exceptions import ResourceNotFoundError

from diucs.application.ports.outbound.tokens import SecretStoreUnavailable
from diucs.domain.errors import NotFound
from diucs.domain.rules.secret_names import vault_secret_name

log = logging.getLogger(__name__)

DEFAULT_CACHE_SECONDS: Final = 600
DEFAULT_STALE_SECONDS: Final = 3600
STALE_RETRY_SECONDS: Final = 30


class _Bundle(Protocol):
    @property
    def value(self) -> str | None: ...


class SecretClientLike(Protocol):
    """The part of `azure.keyvault.secrets.SecretClient` the store uses."""

    def get_secret(self, name: str, version: str | None = None, **kwargs: Any) -> _Bundle: ...

    def close(self) -> None: ...


class _Held:
    """A good value and when it was read. The repr shows neither, so printing the cache is safe."""

    __slots__ = ("fetched_at", "retry_after", "value")

    def __init__(self, value: bytes, fetched_at: float) -> None:
        self.value = value
        self.fetched_at = fetched_at
        self.retry_after = 0.0  # not before this time is the vault asked again (serving stale)

    def __repr__(self) -> str:
        return "<held secret>"


class KeyVaultSecretStore:
    def __init__(
        self,
        client: SecretClientLike,
        *,
        cache_seconds: float = DEFAULT_CACHE_SECONDS,
        stale_seconds: float = DEFAULT_STALE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        if cache_seconds < 0 or stale_seconds < 0:
            raise ValueError("the cache and stale seconds must not be negative")
        self._client = client
        self._ttl = float(cache_seconds)
        self._stale = float(stale_seconds)
        self._clock = clock
        self._on_close = on_close
        self._held: dict[str, _Held] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def get(self, name: str) -> bytes:
        vault_name = vault_secret_name(name)
        if vault_name is None:
            raise NotFound("secret name is not a valid reference")
        with self._lock_for(vault_name):
            return self._get_locked(name, vault_name)

    def prefetch(self, names: Iterable[str]) -> None:
        """Read each name now, so the first request does not wait for the vault. A name that is
        absent or unreadable is skipped (it fails closed when it is used)."""
        for name in names:
            try:
                self.get(name)
            except NotFound, SecretStoreUnavailable:
                continue

    def close(self) -> None:
        """Close the client and what the builder gave (the credential); held values are dropped."""
        self._held.clear()
        try:
            self._client.close()
        finally:
            if self._on_close is not None:
                self._on_close()

    def __repr__(self) -> str:
        return f"KeyVaultSecretStore(<{len(self._held)} secrets held>)"

    def _lock_for(self, vault_name: str) -> threading.Lock:
        with self._guard:
            lock = self._locks.get(vault_name)
            if lock is None:
                lock = self._locks[vault_name] = threading.Lock()
            return lock

    def _get_locked(self, name: str, vault_name: str) -> bytes:
        now = self._clock()
        held = self._held.get(vault_name)
        if held is not None:
            age = now - held.fetched_at
            if age < self._ttl:
                return held.value
            if age < self._ttl + self._stale and now < held.retry_after:
                return held.value  # a refresh failed a moment ago: do not ask again yet
        try:
            text = self._client.get_secret(vault_name).value
        except ResourceNotFoundError:
            self._held.pop(vault_name, None)
            raise NotFound(f"secret {name}") from None
        except Exception as error:
            return self._after_failure(name, vault_name, held, now, error)
        if text is None:
            self._held.pop(vault_name, None)
            raise NotFound(f"secret {name}")
        value = text.encode("utf-8")
        self._held[vault_name] = _Held(value, now)
        return value

    def _after_failure(
        self, name: str, vault_name: str, held: _Held | None, now: float, error: Exception
    ) -> bytes:
        if held is not None and now - held.fetched_at < self._ttl + self._stale:
            held.retry_after = now + STALE_RETRY_SECONDS
            log.warning(
                "secret %s could not be refreshed (%s): serving the value held",
                name,
                type(error).__name__,
            )
            return held.value
        if held is not None:
            self._held.pop(vault_name, None)
        log.warning("secret %s could not be read (%s)", name, type(error).__name__)
        raise SecretStoreUnavailable(f"secret {name} could not be read") from None

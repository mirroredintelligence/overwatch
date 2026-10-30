"""The tenant of the actors a test builds (TEN-018).

An `Actor` is built for one tenant. A test that does not care which uses the harness's run tenant,
the tenant its data is seeded under and its scope is bound to, so the actor and the scope agree.
With no harness (a plain import) it is the sample tenant.
"""

import os
from typing import Final

ACTOR_TENANT: Final = os.environ.get("DIUCS_TEST_TENANT") or "example-icb"

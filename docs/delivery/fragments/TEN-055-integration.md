# TEN-055 integration run: the emulator config

The Service Bus emulator in compose project `diucs-b3sb` mounted `/home/user/overwatch/infra/servicebus-config.json`
(the owner's checkout on `main`), which has none of the wave-5 entities, so `projection.work` and the four
`network-projector` subscriptions were "not found". The emulator reads its config at start only, so
it was recreated with the `integration/build` config, under the emulator lock, with
`docker compose -p diucs-b3sb -f /home/user/overwatch/infra/docker-compose.yml -f /home/user/diucs-sb-config/override.yml up -d --no-deps servicebus-emulator`.
`override.yml` replaces only the config bind mount with a copy at `/home/user/diucs-sb-config/servicebus-config.json`
(identical to `infra/servicebus-config.json` on `integration/build`; a path outside any worktree, so
removing a worktree cannot break the mount). Redis, SQL and the probe container were not touched.
Once `main` carries the same config, `docker compose -p diucs-b3sb up -d --no-deps servicebus-emulator`
from `infra/` (no override) returns the emulator to the repository's own file. Result: `test_infra_up.py` and
`tests/contract/test_event_bus_contract.py` pass (65 tests, run exclusive).

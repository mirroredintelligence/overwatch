# Local infrastructure

Docker Compose runs the services DIUCS needs when you run it by hand:

| Service | Image (pinned) | Port | Notes |
|---|---|---|---|
| Neo4j (the only database) | `neo4j:5.26.32-community` | Bolt 7687, browser 7474 | Data in the named volume `neo4j-data` |
| Redis (cache) | `redis:7.4.11-alpine` | 6379 | Transient only, no volume |
| Azure Service Bus emulator | `azure-messaging/servicebus-emulator:2.0.1` | AMQP 5672, management and health 5300 | Entities come from `servicebus-config.json`; they do not survive a restart |
| SQL Server (emulator storage) | `mssql/server:2022-CU27-ubuntu-22.04` | internal | Needed by the emulator |
| `servicebus-ready` | same SQL image | none | Probe container: healthy only when the emulator's `/health` answers 200. The emulator image has no shell, so it cannot check itself |

The credentials are local-only and are for this stack alone. Never put a real secret in this folder.

The test suite does not depend on this stack for its own Neo4j: each pytest run starts a throwaway Neo4j (DEC-008). `backend/tests/integration/test_infra_up.py` is the exception: it checks this stack.

## Start

From the repository root:

```
docker compose -f infra/docker-compose.yml up -d --wait
```

`--wait` returns only when every service is healthy. On the first run Docker pulls the images, which takes several minutes.

To change the SQL password, copy `infra/.env.example` to `infra/.env` and edit it. Compose reads that file automatically. Keep it out of git.

## Stop

```
docker compose -f infra/docker-compose.yml stop
```

`stop` keeps the Neo4j data. `docker compose -f infra/docker-compose.yml restart neo4j` also keeps it.

## Reset

```
docker compose -f infra/docker-compose.yml down -v
```

`down -v` removes the containers and the `neo4j-data` volume, so every node and relationship is gone. Run `up -d --wait` again afterwards.

## Open the Neo4j browser

Open <http://localhost:7474>, connect to `bolt://localhost:7687`, user `neo4j`, password `diucs-test-password`.

## Run the infrastructure smoke tests

With the stack healthy, from `backend/`:

```
uv run pytest tests/integration/test_infra_up.py
```

Known limit: the queue test sends message id `smoke-1` to `inbound.replies`, which has duplicate detection on (a 20 second history window). If you run it again within 20 seconds, the second send is treated as a duplicate and the test fails. Wait 20 seconds and run it again.

## Troubleshooting

- `docker compose ... ps` shows a service `unhealthy`: run `docker compose -f infra/docker-compose.yml logs <service>`.
- Emulator stuck starting: it waits for SQL. Check that `servicebus-sql` is healthy first.
- Port already in use: another local process holds 5672, 5300, 6379, 7474 or 7687. Stop it, or change the host port in the compose file and in your environment variables.

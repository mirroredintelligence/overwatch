# TEN-028 integration run (fix round F5B)

The integration tests of TEN-028 were run on the shared Neo4j (the registry tests and the generated isolation test on a private container) and are green.

## What the run found

- Test: the provisioning helper approved a configuration twice; wording keys are not clinical, so one approval completes it and a second is `InvalidTransition`. It approves as many times as the draft needs. The test that no invitation data is at rest scanned every node and found the number in the protected contact store, which is where it belongs; it now asserts that the only node holding the number is the `ProtectedContact`.
- Seven `Q-TENANT-REG-*` platform statements: `tests/integration/graph_store/test_tenant_registry.py` now runs each one for tenant A with A's values and with values of B, and requires every node that is not A's, every link of those nodes and (for the foreign run) A's own nodes to be unchanged; a data node of each tenant with the registry's words (a host, a number) is in the world. A mutant of each statement (the key, the epoch and status compare, or CREATE turned into MERGE taken out) is run in a fresh world and must differ from the statement; the mutants are also refused by the digest pin at registration. A coverage test fails when a platform statement has no case or no mutant. The graph invariants (no unstamped node but the registry labels, no relationship between two tenants) hold after the registry writes.
- `test_tenant_isolation.py`: the generated test runs tenant statements only. A new test pins that the statements it leaves out are exactly the allowlisted global and platform ones (pinned by digest, seven platform statements named `Q-TENANT-REG-*`), and that a tenant statement cannot be registered as platform or global. The predicate-removal check still covers every tenant statement.

## Known issues

| ID | what | where | trigger |
|---|---|---|---|
| TEN-028 | The mutants of the platform statements are run through raw Cypher on the private container (a registered mutant is refused by design) | `test_tenant_registry.py` | a platform statement is added: it needs a case and a mutant |

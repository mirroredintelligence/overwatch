# TEN-027 integration run (fix round F5B)

The integration tests of TEN-027 were run on the shared Neo4j and are green.

## What the run found

- Product: `SendPrompts` and `MissedReportLadder` took the tenant from the unit scope and did not compare `command.actor.tenant_id` with it (DEC-501 item 2 left that as a known issue). Both now do: `SendPrompts` calls `require_actor_in_bound_tenant` before the early replay read and `tenant_scope_of_unit` inside the unit; the ladder calls `tenant_scope_of_unit` before any read or lock. A mismatch is `TenantMismatch` and nothing is read or written. Production callers already build the actor from the bound tenant (`ladder_handlers` uses `system_actor(current_tenant(), ...)`). Tests: `test_send_prompts_tenants.py` (three), `test_missed_report_ladder_tenants.py` (one); they fail on the old code.
- Product (TEN-041): `CapacityLinkHandler.renew` called `_render` without the zone, so a renewed prompt was worded in London time for every tenant. It now passes `zone=self._zone`. Test: `test_link_access.py::test_the_renewed_prompt_words_its_times_in_the_tenants_zone` (New York fails on the old code); `build_link_rig` takes `zone=`.
- Test: `ConfirmCapacity` tests built a new `SequentialIds` per call, so two confirmations wrote the same Observation id; one generator per tenant now.
- Test: the use-case differential compared the whole message, and the ladder's message echoes the id the caller sent; the echo is masked before two answers are compared.
- Test: `test_send_prompts.py`, `test_send_prompts_grouped.py` and `test_handle_inbound_text.py` passed the fixed tenant `tenant-a` to `SendPrompts`, which is now compared with the unit's scope; they use the run tenant (`ACTOR_TENANT`). The test that said the content is sealed under the constructor's tenant was rewritten for DEC-501 (sealed under the unit's tenant; a constructor for another tenant is refused). A monkeypatch of `next_due` had the old two-argument signature.
- Test rig: `Rig` (`tests/support/ladder_rig.py`) builds the actor of its own tenant and binds it for each call, so a rig of the second tenant no longer carries the run tenant's actor.

## Known issues

| ID | what | where | trigger |
|---|---|---|---|
| TEN-027 | Supersedes the TEN-027 line "SendPrompts and the ladder do not compare the command's actor tenant": they do now | `send_prompts.py`, `missed_report_ladder.py` | none |
| TEN-027 | `test_routes_admin.py::test_a_lead_suspends_a_service_...` (500, `UnitOfWorkAlreadyOpen`) and two tests of `test_routes_criteria.py` (415 on a post with no body) fail on this branch; they are not in the wave 5 files and were not touched | `tests/integration/adapters/inbound/fhir_rest/` | the next run of the FHIR route tests |

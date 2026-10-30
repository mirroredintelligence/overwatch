# TEN-041 integration run (fix round F5B)

`test_pre_session_resolution.py` and `test_tenancy_link_tokens.py` are green on the shared Neo4j. The setup errors of the first run no longer occur (the TEN-033 to TEN-035 fixtures).

- Product: `CapacityLinkHandler.renew` words the renewed prompt in the handler's zone (`_render(..., zone=self._zone)`), see TEN-027-integration.md.

## Known issues

None added.

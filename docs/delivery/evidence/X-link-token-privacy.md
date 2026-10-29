# X-link-token-privacy: a random link token no longer matches the privacy guard

There is no ledger task for this fix. It was found by a verifier of U03 and fixed outside the ledger, so nothing here is claimed as a delivery or a verification. Branch `task/fix-link-token-privacy`, from `main` at `ba27993`. Decision: DEC-152 (`docs/delivery/decisions.md`).

## The defect

`SendPrompts` builds the link as `<link_base_url>/<token>` and calls `render`, which runs the D17 guard (`find_patient_data`) over every field, including `link`. The token was 128 bits as 22 characters of base64url. In base64url "-" is a word boundary to the postcode pattern (`\b[A-Z]{1,2}[0-9][A-Z0-9]?\s*[0-9][A-Z]{2}\b`), and the digits can complete the shape, so a segment between "-" characters (or at either end of the token) can read as a full postcode. `render` then raised `ValidationFailed` with "link: a patient-data shape is not allowed", `SendPrompts` failed, the prompt was not sent, the service went overdue and an alert could fire.

## Reproduction (measured, seeded, deterministic)

A script (session scratch directory, `fixtoken-measure.py`) over 300000 tokens made from `random.Random(20261029).randbytes(16)`, link `diucs.example/<token>`, patterns taken from `privacy_guard`:

| Token | Guard matches | Rate | Pattern |
|---|---|---|---|
| Legacy: base64url, 22 characters (before the fix) | 544 of 300000 | 0.181 percent | postcode 544, NHS number 0, titled name 0 |
| New: letters only, 23 characters (after the fix) | 0 of 300000 | 0 percent | none |

The verifier's figure was 556 of 300000 (0.19 percent) on its own sample; this seed gives 544. Test `test_the_legacy_encoding_matches_the_guard_at_the_reported_rate` pins the 544 and that all are postcode shapes. The NHS-number shape also occurs in principle (a run of ten digits, or a grouped 3-3-4 with hyphens) but did not occur in 300000 draws; the forced tests cover it with hand-made tokens.

Through the real code path, on the red commit (`b18fe89`), with the 128 bits that made a postcode token forced into `SendPrompts` (a temporary patch of the token source, not committed; output in the session scratch directory `fixtoken-red-realpath.txt`):

    diucs.domain.errors.ValidationFailed: link: a patient-data shape is not allowed
    src/diucs/domain/messages/templates.py:416: ValidationFailed

## Red and green

| Commit | Content |
|---|---|
| `b18fe89` | `fix-link-token-privacy: failing tests (red)`, tests only |
| `388f513` | `fix-link-token-privacy: letters-only link token, injectable token source (green)` |

Red run of the unit tests: 10 failed, 64 passed. The failures were the seeded sample (matches found), `render` of a forced matching token (4 cases: postcode in the middle, postcode at the start, NHS number contiguous, NHS number grouped), the exact-token test, the 23-character length and the token-source tests. The two integration forced tests failed with `TypeError: LinkTokenService.__init__() got an unexpected keyword argument 'rng'` (the new injection point does not exist yet); that is a red for a missing seam, and the real-path reproduction above shows the defect itself through `SendPrompts`. The new alphabet tests fail on import of `LINK_TOKEN_ALPHABET` before the change.

## The fix, and why option (b)

`new_link_token` writes the 128 random bits as one number in base 52 with exactly 23 letters (A to Z, a to z). No digit, no "-", no "_", no whitespace.

Proof from the guard's patterns (the tests assert each premise):
- Postcode: needs a digit, and a word boundary on both sides of the match. A token with no "-" or whitespace is one unbroken word of 23 letters (`\w{23}`), so there is no boundary inside it, and the longest postcode without whitespace is 7 characters. The link prefix ends in "/" and what follows the token is a space, a quote or a line break (never a letter), so no match can start before the token and end inside it, or start inside it and end after it.
- NHS number: needs ten digits. The token has none.
- Titled name: needs whitespace (`\s`) after the title. The token has none.

So no token of this form can match, whatever the random bits. This is proved from the patterns, and then sampled (300000 seeded tokens, 0 matches; 20000 whole C1 messages; the extreme inputs all-zero, all-one-bits and 0..15). Option (a), a bounded regenerate loop, was not needed: nothing is rejected, there is no retry and no new failure mode. The loop-bound mutant of the prompt therefore does not apply (there is no loop).

Entropy (DEC-115, domain-rules 7: at least 128 bits):

| | Alphabet | Length | Bits of space | Bits used |
|---|---|---|---|---|
| Before | 64 (base64url) | 22 | 132.0 | 128 |
| After | 52 (letters) | 23 | 23 x log2(52) = 131.11 | 128 |

52 ** 23 is 8.63 times 2 ** 128, so the 16 random bytes map one to one into 23 letters: no bit is lost and no bias is added (a test checks that 50000 distinct 16-byte inputs give 50000 distinct tokens). The source still asks for exactly 16 bytes. The cost is one more character in the SMS (23, was 22).

The privacy guard is not changed, weakened or skipped for the link field. Exemption: the guard's own spec does not exempt a link host or token. Domain-rules section 9 says "No message (text, email or push) ever contains a patient name, a full postcode, an NHS number or free text" and names no exemption; DEC-047 item 5 says the guard runs on every value a caller passes, in whichever field. So the fix is on the token side only.

`LinkTokenService` gained a last constructor argument `rng` (default `secrets.token_bytes`) so a test can force particular 128 bits through the real `issue` path. Tokens already sent (22 characters, base64url) still resolve: `hash_token` still accepts any URL-safe text (known issue for L01 and L02).

Tenancy: no Cypher is added or changed, and the tenant-pending statements of U03 are unchanged.

## Tests

| What | Test |
|---|---|
| Seeded reproduction of the defect (544 of 300000, all postcode) | `test_link_token_privacy.py::test_the_legacy_encoding_matches_the_guard_at_the_reported_rate` |
| Forced tokens really match the guard on the old encoding | `test_each_forced_legacy_token_really_matches_the_guard` (4) |
| Zero guard matches over 300000 seeded tokens (three link forms) | `test_no_seeded_token_matches_the_guard_in_a_link`; distinctness `test_the_seeded_tokens_are_distinct` |
| Whole C1 text with seeded tokens renders | `test_whole_c1_messages_with_seeded_tokens_render` |
| Forced matching bits now give a clean link and a rendered prompt | `test_bytes_that_made_a_matching_legacy_token_now_give_a_clean_link` (4); extremes `test_the_extreme_inputs_give_clean_links` |
| Forced through `SendPrompts` on Neo4j: the prompt is still sent, the token resolves | `test_send_prompts.py::test_a_token_that_once_matched_the_privacy_guard_still_sends_the_prompt` (postcode, nhs) |
| Alphabet letters only, no digit, separator or space; one unbroken word | `test_link_token_alphabet.py::test_the_alphabet_is_letters_only_so_no_pattern_can_match`, `test_every_token_is_one_unbroken_word_of_the_fixed_length` |
| Entropy: 52 letters, 23 long, 52 ** 23 at least 2 ** 128, 23 x log2(52) at least 128, 16 bytes in | `test_the_token_space_holds_at_least_128_bits`, `test_different_random_bytes_never_give_the_same_token`, `test_the_largest_input_fits_in_the_token_length` |
| Exact token for fixed bytes (base 52, most significant first) | `test_tokens.py::test_a_fixed_rng_gives_the_expected_letters_only_token` |
| Sealed round trip and the link-token service still work | `test_link_token_service.py` (issue, resolve, burn, 23 letters), `test_send_prompts.py` (seal and unseal of the content, token resolves) |
| The token source is injectable, default is the system source | `test_link_token_service_source.py` (2) |

## Other random identifiers through the guard (point 4 of the brief)

Seeded, 300000 draws each (the pairing code is exhaustive), same patterns:

| Identifier | Where it goes | Guard matches |
|---|---|---|
| Link token, new | `link` field of C1 and C2 | 0 of 300000 (and none possible) |
| Pairing code `482 913` | wall screen, not yet in a message | 0 of 1000000 codes, both plain and formatted (exhaustive test) |
| Support code `XXXX-XXXX` | support screen | 0 of 300000 (each half is 4 characters; a postcode needs 5 or more in one word) |
| UUID4 (id generator, audit, outbox, Message-ID header) | never passed to `render` or the guard | 2502 of 300000 (0.83 percent), all NHS-number shape (ten digits in the last 12-character group) |

The UUID rate is real but not reachable today: the only fields `render` receives are service name, figures, times, `link` and `reply_by` (checked in `send_prompts.py` and `report_capacity.py`), and the guard is called nowhere else. Listed in `docs/delivery/known-issues.md` with a trigger. The SMTP Message-ID is a header, not scanned. The K1 text code and invitation codes (I1, I2) have no generator yet; known issue says to give them a letters-only form.

## Mutants

Each applied to the source, the unit tests for the token run, then restored with `git checkout` (`git status` clean after each; script in the session scratch directory `fixtoken-mutate.py`, output `fixtoken-mutants.txt`).

| Mutant | Result | Tests that fail (first ones) |
|---|---|---|
| M1 base64url encoding restored (the alphabet change reverted) | killed, 11 failed | `test_no_seeded_token_matches_the_guard_in_a_link`, `test_bytes_that_made_a_matching_legacy_token_now_give_a_clean_link`, `test_whole_c1_messages_with_seeded_tokens_render`, `test_a_fixed_rng_gives_the_expected_letters_only_token`, `test_every_token_is_one_unbroken_word_of_the_fixed_length` |
| M2 alphabet gains the ten digits | killed, 6 failed | `test_the_alphabet_is_letters_only_so_no_pattern_can_match`, `test_the_token_space_holds_at_least_128_bits`, `test_a_fixed_rng_gives_the_expected_letters_only_token` |
| M3 length cut to 22 (under 128 bits at 52 letters) | killed, 5 failed | `test_the_token_space_holds_at_least_128_bits`, `test_a_fixed_rng_gives_the_expected_letters_only_token` |
| M4 alphabet cut to 26 letters (under 128 bits at 23) | killed, 4 failed | `test_the_token_space_holds_at_least_128_bits`, `test_the_alphabet_is_letters_only_so_no_pattern_can_match` |
| M5 the service ignores the injected source | killed, 1 failed | `test_issue_draws_the_token_from_the_injected_source` |
| M6 base-52 digits written least significant first | killed, 2 failed | `test_a_fixed_rng_gives_the_expected_letters_only_token`, `test_the_largest_input_fits_in_the_token_length` |
| M7 a "-" inserted in the token | killed, 5 failed | `test_every_token_is_one_unbroken_word_of_the_fixed_length`, `test_a_fixed_rng_gives_the_expected_letters_only_token` |
| Regenerate loop removed, loop bound removed | not applicable: option (b) has no loop | |

Limit, stated: M5 is killed only by the unit test; the integration forced test passes with M5 because the fix makes the generated token clean either way, so the integration test proves "the prompt is sent" and not "the source was used". The unit test proves the second.

## Coverage

Line and branch, unit tests of `tests/unit/domain/rules` plus the token service unit test, plus the integration tests that run the token service (`test_link_token_service.py`, `test_link_token_repository.py`, `test_send_prompts.py`), 1179 passed, `coverage report --fail-under=100` exit 0:

| Module | Statements | Branches | Missed | Cover |
|---|---|---|---|---|
| `src/diucs/domain/rules/tokens.py` | 92 | 32 | 0 | 100 percent |
| `src/diucs/application/ports/outbound/tokens.py` | 44 | 12 | 0 | 100 percent |

Command: `flock /tmp/diucs-neo4j-tests.lock uv run --with coverage python -m coverage run --branch --include=<the two modules> -m pytest <those tests> -q`.

## Files changed

`backend/src/diucs/domain/rules/tokens.py`, `backend/src/diucs/application/ports/outbound/tokens.py`; tests `tests/unit/domain/rules/test_link_token_privacy.py` (new), `test_link_token_alphabet.py` (new), `test_tokens.py`, `tests/unit/application/ports/outbound/test_link_token_service_source.py` (new), `tests/integration/application/test_link_token_service.py`, `test_send_prompts.py`; docs `decisions.md` (DEC-152), `known-issues.md`, `docs/spec/domain-rules.md` section 7, `docs/spec/contracts.md`, `docs/plan/prompts/D26.md`, `P10.md`.

## Checks (generated)
Generated by `record_checks.py` at 2026-10-29 02:04 UTC on `e1786ef` (clean working tree).

| Check | Command | Exit | Last line |
|---|---|---|---|
| unit and architecture tests | `uv run pytest tests/unit tests/architecture -q` | 0 | 4095 passed in 88.06s (0:01:28) |
| lint | `uv run ruff check .` | 0 | All checks passed! |
| format | `uv run ruff format --check .` | 0 | 398 files already formatted |
| types | `uv run mypy src` | 0 | Success: no issues found in 149 source files |
| import contracts | `uv run lint-imports` | 0 | Contracts: 5 kept, 0 broken. |
| U03 | `flock /tmp/diucs-neo4j-tests.lock uv run pytest tests/integration/application/test_send_prompts.py -q` | 0 | 47 passed in 34.12s |
| link token service | `flock /tmp/diucs-neo4j-tests.lock uv run pytest tests/integration/application/test_link_token_service.py -q` | 0 | 13 passed in 15.40s |
| link token repository | `flock /tmp/diucs-neo4j-tests.lock uv run pytest tests/integration/graph_store/test_link_token_repository.py -q` | 0 | 16 passed in 15.67s |

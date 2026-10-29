# Build wave 1: fragments folded

The per-task fragments in `docs/delivery/fragments/` (build-wave-rules.md) were folded into `decisions.md`, `hazard-log.md`, `known-issues.md` and `docs/spec/contracts.md` on 2026-10-29, and the fragment files were deleted (they stay in git history, last present at the commit before the one that removes them). This file is the audit of what was numbered how.

Rules used. A number a fragment already held (a reserved one, or an id defined by the tenancy audit) was kept if nothing else used it. A placeholder (`H-NEW-n`, or no number at all) got the next free number after the highest in the shared file, in fragment order (G, I, O, P, R, S, TEN, U, W; numeric inside a name), skipping W09's reserved blocks (ten decision numbers from DEC-210, five hazard numbers from H-65). Highest before the fold: DEC-196 and H-42.

## Decisions

| Fragment | Old id | New id | Note |
|---|---|---|---|
| G11 | (no number) | DEC-197 | |
| G13 | (no number) | DEC-198 | |
| I10 | (no number) | DEC-199 | |
| I11 | (no number) | DEC-200 | |
| I12 | (no number) | DEC-201 | |
| I13 | (no number) | DEC-202 | |
| I15 | (no number) | DEC-203 | |
| O01 | (no number) | DEC-204 | |
| O02 | (no number) | DEC-205 | |
| O06 | (no number) | DEC-206 | |
| O07 | (no number) | DEC-207 | |
| O09 | (no number) | DEC-208 | |
| P17 | (no number) | DEC-209 | |
| W09 | DEC-210 (reserved) | DEC-210 | kept; the evidence and `frontend/proxy.ts`, `frontend/lib/auth/oidc.ts` cite it |
| P18 | (no number) | DEC-220 | |
| P19 | (no number) | DEC-221 | |
| P20 | (no number) | DEC-222 | |
| R14 | (no number) | DEC-223 | |
| R15 | (no number) | DEC-224 | |
| R16 | (no number) | DEC-225 | |
| S01 | (no number) | DEC-226 | |
| TEN-012 | (no number) | DEC-227 | |
| TEN-013 | (no number) | DEC-228 | |
| TEN-014 | (no number) | DEC-229 | |
| TEN-016 | (no number) | DEC-230 | |
| TEN-017 | (no number) | DEC-231 | |
| TEN-019 | (no number) | DEC-232 | |
| TEN-021 | (no number) | DEC-233 | |
| TEN-022 | (no number) | DEC-234 | |
| TEN-036 | (no number) | DEC-235 | |
| TEN-063 | (no number) | DEC-236 | |
| U11 | (no number) | DEC-237 | |
| U15 | (no number) | DEC-238 | |
| U16 | (no number) | DEC-239 | |
| U17 | (no number) | DEC-240 | |
| U23 | (no number) | DEC-241 | |
| U25 | (no number) | DEC-242 | |
| U26 | (no number) | DEC-243 | |
| U30 | (no number) | DEC-244 | |
| U35 | (no number) | DEC-245 | |
| U39 | (no number) | DEC-246 | |

The informal reference `DEC-186` in the docstring of `backend/src/diucs/adapters/inbound/fhir_rest/routes_screens.py` (the proxy remark) meant the R15 decision and now reads `DEC-224 item 18`. U11's fragment said its integration-test comments cited `DEC-200` and `DEC-204`, which never existed; it had already changed them to DEC-067 item 1 and the CaseRepository port, and the folded text no longer names those two numbers (they are now other tasks' decisions).

## Hazards

| Fragment | Old id | New id | Note |
|---|---|---|---|
| G11 | H-NEW-1 | H-43 |  |
| G11 | H-NEW-2 | H-44 |  |
| G13 | H-NEW-3 | H-45 |  |
| I10 | H-NEW-I10-1 | H-46 |  |
| I10 | H-NEW-I10-2 | H-47 |  |
| I11 | H-NEW-I11-1 | H-48 |  |
| I11 | H-NEW-I11-2 | H-49 |  |
| I12 | H-NEW-I12-1 | H-50 |  |
| I12 | H-NEW-I12-2 | H-51 |  |
| I12 | H-NEW-I12-3 | H-52 |  |
| I13 | H-NEW-1 | H-53 |  |
| I13 | H-NEW-2 | H-54 |  |
| I13 | H-NEW-3 | H-55 |  |
| I13 | H-NEW-4 | H-56 |  |
| I15 | H-NEW-5 | H-57 |  |
| I15 | H-NEW-6 | H-58 |  |
| I15 | H-NEW-7 | H-59 |  |
| O01 | H-NEW-1 | H-60 |  |
| O01 | H-NEW-2 | H-61 |  |
| O02 | H-NEW-3 | H-62 |  |
| O02 | H-NEW-4 | H-63 |  |
| O06 | H-NEW-5 | H-64 |  |
| W09 | H-NEW-1 | H-65 | kept (reserved) |
| O06 | H-NEW-6 | H-70 |  |
| O07 | H-NEW-1 | H-71 |  |
| O07 | H-NEW-2 | H-72 |  |
| O07 | H-NEW-3 | H-73 |  |
| O09 | H-NEW-4 | H-74 |  |
| O09 | H-NEW-5 | H-75 |  |
| R14 | H-NEW-4 | H-76 |  |
| R15 | H-NEW-1 | H-77 |  |
| R15 | H-NEW-2 | H-78 |  |
| R15 | H-NEW-3 | H-79 |  |
| R15 | H-NEW-4 | H-80 |  |
| R15 | H-NEW-5 | H-81 |  |
| R16 | H-NEW-1 | H-82 |  |
| R16 | H-NEW-2 | H-83 |  |
| R16 | H-NEW-3 | H-84 |  |
| R16 | H-NEW-4 | H-85 |  |
| R16 | H-NEW-5 | H-86 |  |
| S01 | H-NEW-5 | H-87 |  |
| TEN-016 | H-NEW-1 | H-88 |  |
| TEN-017 | H-NEW-2 | H-89 |  |
| TEN-019 | H-NEW-3 | H-90 |  |
| TEN-019 | H-NEW-4 | H-91 |  |
| U11 | H-NEW-1 | H-92 |  |
| U11 | H-NEW-2 | H-93 |  |
| U15 | H-NEW-1 | H-94 |  |
| U17 | H-NEW-1 | H-95 |  |
| U25 | H-NEW-2 | H-96 |  |
| U25 | H-NEW-3 | H-97 |  |
| U26 | H-NEW-1 | H-98 |  |
| U26 | H-NEW-2 | H-99 |  |
| U30 | H-NEW-1 | H-100 |  |
| U30 | H-NEW-2 | H-101 |  |
| U35 | H-NEW-1 | H-102 |  |
| U35 | H-NEW-2 | H-103 |  |
| U39 | H-NEW-1 | H-104 |  |
| U39 | H-NEW-2 | H-105 |  |

Hazard ids that came from the tenancy audit (F section 8.2) and were kept: H-N02, H-N03, H-N04, H-N05, H-N08, H-N09, H-N12, H-N13, H-N15. TEN-036 and TEN-063 both carried H-N08 (a left member still shown live); it is one row that lists both tasks and both sets of tests. The code comments that cite H-N09 and H-N12 (`domain/model/network.py`, `domain/rules/listing.py`, `tests/unit/domain/rules/test_listing.py`) now point at rows that exist.

`H-NEW-2` in `backend/src/diucs/application/use_cases/text_code.py` (two docstrings) and `backend/tests/unit/application/use_cases/test_text_code_timing.py` meant U25's H-NEW-2 and now reads `H-96`.

### Existing hazard rows amended

- H-37: the residual "a wrong secret at claim is not throttled here (R15)" now reads "throttled per address by R15" and points at DEC-224 item 9, H-79 and the integration test. (R15's fragment named H-NEW-3 in the hazard note and H-NEW-5 in decision item 21(e); H-NEW-3 is the per-address limit, so the folded text says H-NEW-3.)
- H-09, H-13, H-15, H-25, H-T14 and H-T15: TEN-021 and TEN-022 touched the control; their tests were appended to "Verified by" (the existing text is unchanged).
- H-39, H-40 and H-41 each appeared twice in `hazard-log.md` before this fold (a merge had kept both sides, with a blank line between). The older copy of each was removed: the old H-40 (before DEC-173), the old H-39 (before TEN-015 converted the statements) and the old H-41 (without the W04 front-end part). The kept rows are the later, fuller ones. No other existing row text was changed.

## Known issues

Folded as one-line rows in the existing format. Not folded: R14-1 (marked SUPERSEDED in its own text: fixed on that branch), R16-2 (closed by the merge), and P18's second row (the same limit as its first; the two were merged into one). Shortened to one line each: TEN-012, TEN-013, R14-2, U11-1 (meaning unchanged). Known-issue labels such as `I10-1`, `R14-3` and `U11-2` are kept as the Task column.

## Contracts

One section per task at the end of `docs/spec/contracts.md`, in decision order. Not added: TEN-013 and TEN-014 ("none added"). O09's fragment repeated O07's telemetry-query names in its contracts; they are under O07 only. For TEN-021 and TEN-022 the line "for the owner to fold" was folded as an ordinary bullet.

## Tenant pending and Assumed

The build-wave fragments also carried "Tenant pending" and "Assumed" sections, which have no shared file. They were kept as bold paragraphs at the end of each decision (omitted when the fragment said "None"). G11's "Tenant pending" was dropped because its own merge note says the eight statements are converted on the integration branch.

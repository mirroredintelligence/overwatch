# Build waves 4 to 7: fragments folded

The per-task fragments in `docs/delivery/fragments/` of build waves 4 to 7 (98 files besides `README.md`: the harness and contract tasks TEN-033 to TEN-035, the back-end bundles W5A to W5E, the front-end bundles W6A to W6J, the integration fixes F5A, F5D, F6A and F6B with the TEN-0xx integration notes, and the back-end gap bundles W7A, W7B and W7C with their `-routes.md` files) were folded into `decisions.md`, `hazard-log.md`, `known-issues.md` and `docs/spec/contracts.md`, and the fragment files were deleted (they stay in git history, last present at the commit before the one that removes them). This file is the audit of what was numbered how. Earlier folds: `fragments-folded-wave1.md`, `fragments-folded-wave2.md`, `fragments-folded-wave3.md`.

This was a documentation fold. Nothing was run as part of it beyond the checks listed under "Not verified". Counts: 222 decision entries (DEC-460 to DEC-856: 216 from the fragments, 2 from the F6B report, 1 consolidated decision and 3 open decisions written on folding), 229 hazard rows (H-225 to H-523: 228 from the fragments and 1 raised on folding) and 1 amended, 378 known-issue rows added, 16 existing rows closed and 3 edited.

## Rules used

- A number a fragment carried was kept if no entry held it: the shared files had DEC-450 and H-223 as their highest before the fold. Blocks the waves used: DEC-460 to 466, 500 to 507, 520 to 530, 540 to 548, 600 to 608, 630 to 653 (and 654 to 659), 660 to 674, 680 to 692, 700 to 729, 740 to 753, 760 to 761, 770 to 781, 790 to 826; hazards H-225 to 235, 250 to 289, 300 to 333, 335 to 379, 385 to 414, 430 to 439, 450 to 459.
- A second use of a number got the next free number (a counter from DEC-830 for decisions and from H-470 for hazards, in fragment order: back-end bundles first, then the front-end bundles in numeric order, then W7A, W7B, W7C, F6A and F6B). A fragment with no number (items numbered 1 to n, the W19 to W22 and W32 style, R09, R10, R12, R13, L02, TEN-066, F6A) took the next free number from DEC-830, one decision per fragment unless the fragment split its text. Hazard placeholders (`H-NEW-n`, and the R10, R12 and R13 placeholders `H-NEW-245` to `H-NEW-249`) took H-470 and up, in the same order. Placeholder text inside a fragment (a decision or a known issue naming its own `H-NEW-n`) was rewritten to the new number inside that fragment's entries only.
- The fragment order inside the files is that order. Bullets of the "Tenant pending" and "Assumed" sections are bold paragraphs after the last decision of their fragment, omitted where the fragment said "None" alone (as in wave 3). The "Not run", "Tests", "Test changes after red", "Test correction", "Zone ratchet", "Lessons" and "Evidence" sections have no shared file and were not folded.
- Collision check, run on the tree before and after: no decision heading and no hazard id is defined twice (a script compared every heading and id with the tree at the base commit and within the fold). Highest after: DEC-856 and H-523. The gaps inside the blocks stay unused.

## Decisions

Fragments with no decision of their own: F5A, F5D, F6B (two decisions written from its text, see below), the TEN-027, TEN-028, TEN-041, TEN-055, TEN-060 and TEN-073 integration notes, R17 (its fix is a hazard and a contract note; its route decisions are inside R09's). O03 and O05 only restated DEC-330 and DEC-333 ("stands"); those decisions already exist and were not folded again.

| Fragment | Old id | New id | Note |
|---|---|---|---|
| L02 | (no number) | DEC-830 | no number in the fragment; next free number from DEC-830 |
| O02 | DEC-740 | DEC-740 | kept |
| R09 | (no number) | DEC-831 | no number in the fragment; next free number from DEC-830 |
| R10 | (no number) | DEC-832 | no number in the fragment; next free number from DEC-830 |
| R12 | (no number) | DEC-833 | no number in the fragment; next free number from DEC-830 |
| R13 | (no number) | DEC-834 | no number in the fragment; next free number from DEC-830 |
| S01 | DEC-741 | DEC-741 | kept |
| TEN-027 | DEC-500 | DEC-500 | kept |
| TEN-027 | DEC-501 | DEC-501 | kept |
| TEN-028 | DEC-503 | DEC-503 | kept |
| TEN-028 | DEC-504 | DEC-504 | kept |
| TEN-028 | DEC-505 | DEC-505 | kept |
| TEN-028 | DEC-506 | DEC-506 | kept |
| TEN-033 | DEC-460 | DEC-460 | kept |
| TEN-034 | DEC-461 | DEC-461 | kept |
| TEN-035 | DEC-462 | DEC-462 | kept |
| TEN-035 | DEC-463 | DEC-463 | kept |
| TEN-035 | DEC-464 | DEC-464 | kept |
| TEN-035 | DEC-465 | DEC-465 | kept |
| TEN-035 | DEC-466 | DEC-466 | kept |
| TEN-037 | DEC-540 | DEC-540 | kept |
| TEN-041 | DEC-520 | DEC-520 | kept |
| TEN-043 | DEC-522 | DEC-522 | kept |
| TEN-043 | DEC-523 | DEC-523 | kept |
| TEN-043 | DEC-524 | DEC-524 | kept |
| TEN-043 | DEC-525 | DEC-525 | kept |
| TEN-043 | DEC-526 | DEC-526 | kept |
| TEN-043 | DEC-527 | DEC-527 | kept |
| TEN-044 | DEC-600 | DEC-600 | kept |
| TEN-044 | DEC-601 | DEC-601 | kept |
| TEN-044 | DEC-602 | DEC-602 | kept |
| TEN-045 | DEC-604 | DEC-604 | kept |
| TEN-046 | DEC-603 | DEC-603 | kept |
| TEN-047 | DEC-607 | DEC-607 | kept |
| TEN-048 | DEC-608 | DEC-608 | kept |
| TEN-049 | DEC-606 | DEC-606 | kept |
| TEN-050 | DEC-605 | DEC-605 | kept |
| TEN-051 | DEC-541 | DEC-541 | kept |
| TEN-053 | DEC-542 | DEC-542 | kept |
| TEN-054 | DEC-543 | DEC-543 | kept |
| TEN-055 | DEC-545 | DEC-545 | kept |
| TEN-057 | DEC-546 | DEC-546 | kept |
| TEN-058 | DEC-547 | DEC-547 | kept |
| TEN-059 | DEC-548 | DEC-548 | kept |
| TEN-060 | DEC-544 | DEC-544 | kept |
| TEN-066 | (no number) | DEC-835 | no number in the fragment; next free number from DEC-830 |
| TEN-073 | DEC-507 | DEC-507 | kept |
| TEN-084 | DEC-528 | DEC-528 | kept |
| TEN-084 | DEC-529 | DEC-529 | kept |
| TEN-084 | DEC-530 | DEC-530 | kept |
| W08 | DEC-761 | DEC-761 | kept |
| W09 | DEC-760 | DEC-760 | kept |
| W10 | DEC-630 | DEC-630 | kept |
| W10 | DEC-631 | DEC-631 | kept |
| W10 | DEC-632 | DEC-632 | kept |
| W10 | DEC-645 | DEC-645 | kept |
| W11 | DEC-633 | DEC-633 | kept |
| W11 | DEC-634 | DEC-634 | kept |
| W12 | DEC-635 | DEC-635 | kept |
| W12 | DEC-646 | DEC-646 | kept |
| W13 | DEC-636 | DEC-636 | kept |
| W13 | DEC-643 | DEC-643 | kept |
| W14 | DEC-637 | DEC-637 | kept |
| W14 | DEC-638 | DEC-638 | kept |
| W14 | DEC-639 | DEC-639 | kept |
| W14 | DEC-648 | DEC-648 | kept |
| W15 | DEC-640 | DEC-640 | kept |
| W15 | DEC-641 | DEC-641 | kept |
| W16 | DEC-642 | DEC-642 | kept |
| W17 | DEC-650 | DEC-650 | kept |
| W17 | DEC-651 | DEC-651 | kept |
| W17 | DEC-659 | DEC-659 | kept |
| W18 | DEC-652 | DEC-652 | kept |
| W18 | DEC-653 | DEC-653 | kept |
| W18 | DEC-655 | DEC-655 | kept |
| W19 | (no number) | DEC-836 | no number in the fragment; next free number from DEC-830 |
| W20 | (no number) | DEC-837 | no number in the fragment; next free number from DEC-830 |
| W21 | (no number) | DEC-838 | no number in the fragment; next free number from DEC-830 |
| W22 | (no number) | DEC-839 | no number in the fragment; next free number from DEC-830 |
| W23 | DEC-680 | DEC-680 | kept |
| W23 | DEC-681 | DEC-681 | kept |
| W23 | DEC-682 | DEC-682 | kept |
| W24 | DEC-685 | DEC-685 | kept |
| W25 | DEC-686 | DEC-686 | kept |
| W25 | DEC-687 | DEC-687 | kept |
| W26 | DEC-688 | DEC-688 | kept |
| W26 | DEC-689 | DEC-689 | kept |
| W26 | DEC-690 | DEC-690 | kept |
| W27 | DEC-691 | DEC-691 | kept |
| W27 | DEC-692 | DEC-692 | kept |
| W28 | DEC-702 | DEC-702 | kept |
| W28 | DEC-703 | DEC-703 | kept |
| W28 | DEC-704 | DEC-704 | kept |
| W28 | DEC-708 | DEC-708 | kept |
| W29 | DEC-705 | DEC-705 | kept |
| W29 | DEC-706 | DEC-706 | kept |
| W29 | DEC-707 | DEC-707 | kept |
| W29 | DEC-709 | DEC-709 | kept |
| W30 | DEC-700 | DEC-700 | kept |
| W30 | DEC-701 | DEC-701 | kept |
| W31 | DEC-701 | DEC-840 | renumbered: DEC-701 is held by an earlier entry |
| W32 | (no number) | DEC-841 | no number in the fragment; next free number from DEC-830 |
| W33 | DEC-660 | DEC-660 | kept |
| W33 | DEC-662 | DEC-662 | kept |
| W33 | (no number) | DEC-842 | no number in the fragment; next free number from DEC-830 |
| W33 | (no number) | DEC-843 | no number in the fragment; next free number from DEC-830 |
| W33 | DEC-664 | DEC-664 | kept |
| W34 | DEC-661 | DEC-661 | kept |
| W34 | DEC-663 | DEC-663 | kept |
| W35-W37 | DEC-665 | DEC-665 | kept |
| W35-W37 | DEC-666 | DEC-666 | kept |
| W35-W37 | DEC-667 | DEC-667 | kept |
| W35-W37 | DEC-668 | DEC-668 | kept |
| W35-W37 | DEC-669 | DEC-669 | kept |
| W38-W55 | DEC-670 | DEC-670 | kept |
| W38-W55 | DEC-671 | DEC-671 | kept |
| W38-W55 | DEC-672 | DEC-672 | kept |
| W38-W55 | DEC-673 | DEC-673 | kept |
| W38-W55 | DEC-674 | DEC-674 | kept |
| W39 | DEC-710 | DEC-710 | kept |
| W39 | DEC-711 | DEC-711 | kept |
| W40 | DEC-712 | DEC-712 | kept |
| W40 | DEC-713 | DEC-713 | kept |
| W40 | DEC-714 | DEC-714 | kept |
| W41 | DEC-715 | DEC-715 | kept |
| W41 | DEC-716 | DEC-716 | kept |
| W41 | DEC-717 | DEC-717 | kept |
| W42 | DEC-657 | DEC-657 | kept |
| W42 | DEC-658 | DEC-658 | kept |
| W42 | DEC-652 | DEC-844 | renumbered: DEC-652 is held by an earlier entry |
| W43 | DEC-654 | DEC-654 | kept |
| W43 | DEC-652 | DEC-845 | renumbered: DEC-652 is held by an earlier entry |
| W43 | DEC-651 | DEC-846 | renumbered: DEC-651 is held by an earlier entry |
| W44 | DEC-718 | DEC-718 | kept |
| W44 | DEC-719 | DEC-719 | kept |
| W44 | DEC-720 | DEC-720 | kept |
| W45 | DEC-728 | DEC-728 | kept |
| W45 | DEC-729 | DEC-729 | kept |
| W46 | DEC-721 | DEC-721 | kept |
| W46 | DEC-722 | DEC-722 | kept |
| W46 | DEC-723 | DEC-723 | kept |
| W46 | DEC-724 | DEC-724 | kept |
| W47 | DEC-656 | DEC-656 | kept |
| W47 | DEC-653 | DEC-847 | renumbered: DEC-653 is held by an earlier entry |
| W47 | DEC-657 | DEC-848 | renumbered: DEC-657 is held by an earlier entry |
| W48 | DEC-742 | DEC-742 | kept |
| W48 | DEC-743 | DEC-743 | kept |
| W48 | DEC-744 | DEC-744 | kept |
| W49 | DEC-745 | DEC-745 | kept |
| W49 | DEC-748 | DEC-748 | kept |
| W50 | DEC-644 | DEC-644 | kept |
| W50 | DEC-649 | DEC-649 | kept |
| W50 | DEC-647 | DEC-647 | kept |
| W50 | DEC-643 | DEC-849 | renumbered: DEC-643 is held by an earlier entry |
| W51 | DEC-746 | DEC-746 | kept |
| W51 | DEC-747 | DEC-747 | kept |
| W52 | DEC-749 | DEC-749 | kept |
| W52 | DEC-753 | DEC-753 | kept |
| W53 | DEC-750 | DEC-750 | kept |
| W53 | DEC-751 | DEC-751 | kept |
| W53 | DEC-752 | DEC-752 | kept |
| W54 | DEC-683 | DEC-683 | kept |
| W54 | DEC-684 | DEC-684 | kept |
| W56 | DEC-725 | DEC-725 | kept |
| W56 | DEC-726 | DEC-726 | kept |
| W56 | DEC-727 | DEC-727 | kept |
| W7A | DEC-770 | DEC-770 | kept |
| W7A | DEC-773 | DEC-773 | kept |
| W7A | DEC-781 | DEC-781 | kept |
| W7A | DEC-779 | DEC-779 | kept |
| W7A | DEC-771 | DEC-771 | kept |
| W7A | DEC-774 | DEC-774 | kept |
| W7A | DEC-780 | DEC-780 | kept |
| W7A | DEC-778 | DEC-778 | kept |
| W7A | DEC-772 | DEC-772 | kept |
| W7A | DEC-775 | DEC-775 | kept |
| W7A | DEC-776 | DEC-776 | kept |
| W7A | DEC-777 | DEC-777 | kept |
| W7B | DEC-790 | DEC-790 | kept |
| W7B | DEC-791 | DEC-791 | kept |
| W7B | DEC-792 | DEC-792 | kept |
| W7B | DEC-793 | DEC-793 | kept |
| W7B | DEC-794 | DEC-794 | kept |
| W7B | DEC-795 | DEC-795 | kept |
| W7B | DEC-796 | DEC-796 | kept |
| W7B | DEC-797 | DEC-797 | kept |
| W7B | DEC-798 | DEC-798 | kept |
| W7B | DEC-799 | DEC-799 | kept |
| W7B | DEC-800 | DEC-800 | kept |
| W7B | DEC-801 | DEC-801 | kept |
| W7B | DEC-802 | DEC-802 | kept |
| W7B | DEC-803 | DEC-803 | kept |
| W7B | DEC-804 | DEC-804 | kept |
| W7B | DEC-805 | DEC-805 | kept |
| W7B | DEC-806 | DEC-806 | kept |
| W7B | DEC-807 | DEC-807 | kept |
| W7B | DEC-808 | DEC-808 | kept |
| W7B | DEC-809 | DEC-809 | kept |
| W7C | DEC-810 | DEC-810 | kept |
| W7C | DEC-811 | DEC-811 | kept |
| W7C | DEC-812 | DEC-812 | kept |
| W7C | DEC-813 | DEC-813 | kept |
| W7C | DEC-814 | DEC-814 | kept |
| W7C | DEC-815 | DEC-815 | kept |
| W7C | DEC-816 | DEC-816 | kept |
| W7C | DEC-817 | DEC-817 | kept |
| W7C | DEC-818 | DEC-818 | kept |
| W7C | DEC-819 | DEC-819 | kept |
| W7C | DEC-820 | DEC-820 | kept |
| W7C | DEC-821 | DEC-821 | kept |
| W7C | DEC-822 | DEC-822 | kept |
| W7C | DEC-823 | DEC-823 | kept |
| W7C | DEC-824 | DEC-824 | kept |
| W7C | DEC-825 | DEC-825 | kept |
| W7C | DEC-826 | DEC-826 | kept |
| F6A | (no number) | DEC-850 | no number in the fragment; next free number from DEC-830 |
| F6B | (no number) | DEC-851 | no number in the fragment; written from its section 1 (the racing save) |
| F6B | (no number) | DEC-852 | no number in the fragment; written from its section 2 (the cover address of the senders) |
| (fold) | - | DEC-853 | consolidated decision: pre-session routes take the tenant from the Host only |
| (fold) | - | DEC-854 | OPEN: withdrawal acknowledged on the first action |
| (fold) | - | DEC-855 | OPEN: clinical advice screens without the case |
| (fold) | - | DEC-856 | OPEN: plain-text phone numbers on ProtectedContact |

Other notes. W39, W40, W41, W44, W45, W46 and W56 reserved their numbers in an introductory line ("item 1 is DEC-710; items 2 to 6 are DEC-711"); items that share a number are one entry. W33's items 3 and 4 had no number and are DEC-842 and DEC-843 (W33's DEC-662 entry ends before them). W31's items 6 to 9 reuse the number DEC-701 of W30 and are DEC-840; W50's text that extends DEC-643 is DEC-849; W42, W43 and W47 restate DEC-651, DEC-652, DEC-653 and DEC-657 of W17 and W18 and took DEC-844 to DEC-848 (the text of each says "see W18" or "see W42"; the references inside the text were not rewritten). Headings of the plain-line forms (W7A, W7B, W17, W28 and the like) are short titles written for this fold; the text is the body, unchanged. Where a fragment's text had no `Status:` line, one was added in the form of the earlier folds. Decisions the builders of W23 to W27 and W54 marked "for the owner to confirm" carry the added words "accepted by the orchestrator on folding under DEC-133" (see the owner decisions below for the three whose text raises a product question).

## Hazards

| Fragment | Old id | New id | Severity | Note |
|---|---|---|---|---|
| L02 | H-NEW-4 | H-470 | HIGH | placeholder |
| L02 | H-NEW-5 | H-471 | MEDIUM | placeholder |
| O02 | H-386 | H-386 | LOW | kept |
| O03 | H-387 | H-387 | MEDIUM | kept |
| O05 | H-388 | H-388 | MEDIUM | kept |
| R09 | H-NEW-1 | H-472 | MEDIUM | placeholder |
| R09 | H-NEW-2 | H-473 | HIGH | placeholder |
| R09 | H-NEW-3 | H-474 | LOW | placeholder |
| R10 | H-NEW-245 | H-475 | HIGH | placeholder |
| R10 | H-NEW-246 | H-476 | MEDIUM | placeholder |
| R12 | H-NEW-247 | H-477 | MEDIUM | placeholder |
| R12 | H-NEW-248 | H-478 | MEDIUM | placeholder |
| R13 | H-NEW-249 | H-479 | HIGH | placeholder |
| R17 | H-NEW-3 | H-480 | LOW | placeholder |
| S01 | H-385 | H-385 | LOW | kept |
| TEN-027 | H-250 | H-250 | HIGH | kept |
| TEN-027 | H-251 | H-251 | MEDIUM | kept |
| TEN-027 | H-252 | H-252 | MEDIUM | kept |
| TEN-027 | H-253 | H-253 | HIGH | kept |
| TEN-028 | H-254 | H-254 | HIGH | kept |
| TEN-028 | H-255 | H-255 | HIGH | kept |
| TEN-028 | H-256 | H-256 | HIGH | kept |
| TEN-028 | H-257 | H-257 | MEDIUM | kept |
| TEN-028 | H-258 | H-258 | HIGH | kept |
| TEN-028 | H-259 | H-259 | HIGH | kept |
| TEN-033 | H-225 | H-225 | LOW | kept |
| TEN-033 | H-226 | H-226 | LOW | kept |
| TEN-034 | H-227 | H-227 | LOW | kept |
| TEN-034 | H-228 | H-228 | LOW | kept |
| TEN-034 | H-229 | H-229 | LOW | kept |
| TEN-034 | H-230 | H-230 | MEDIUM | kept |
| TEN-035 | H-231 | H-231 | LOW | kept |
| TEN-035 | H-232 | H-232 | LOW | kept |
| TEN-035 | H-233 | H-233 | LOW | kept |
| TEN-035 | H-234 | H-234 | LOW | kept |
| TEN-035 | H-235 | H-235 | LOW | kept |
| TEN-037 | H-270 | H-270 | HIGH | kept |
| TEN-037 | H-271 | H-271 | MEDIUM | kept |
| TEN-041 | H-260 | H-260 | MEDIUM | kept |
| TEN-043 | H-261 | H-261 | HIGH | kept |
| TEN-043 | H-262 | H-262 | HIGH | kept |
| TEN-043 | H-263 | H-263 | HIGH | kept |
| TEN-043 | H-264 | H-264 | MEDIUM | kept |
| TEN-044 | H-300 | H-300 | HIGH | kept |
| TEN-044 | H-301 | H-301 | HIGH | kept |
| TEN-044 | H-302 | H-302 | HIGH | kept |
| TEN-044 | H-303 | H-303 | HIGH | kept |
| TEN-044 | H-304 | H-304 | MEDIUM | kept |
| TEN-044 | H-305 | H-305 | MEDIUM | kept |
| TEN-045 | H-308 | H-308 | HIGH | kept |
| TEN-045 | H-309 | H-309 | HIGH | kept |
| TEN-045 | H-310 | H-310 | MEDIUM | kept |
| TEN-046 | H-306 | H-306 | MEDIUM | kept |
| TEN-046 | H-307 | H-307 | LOW | kept |
| TEN-047 | H-317 | H-317 | MEDIUM | kept |
| TEN-047 | H-318 | H-318 | MEDIUM | kept |
| TEN-048 | H-319 | H-319 | LOW | kept |
| TEN-049 | H-314 | H-314 | MEDIUM | kept |
| TEN-049 | H-315 | H-315 | HIGH | kept |
| TEN-049 | H-316 | H-316 | MEDIUM | kept |
| TEN-050 | H-311 | H-311 | MEDIUM | kept |
| TEN-050 | H-312 | H-312 | MEDIUM | kept |
| TEN-050 | H-313 | H-313 | MEDIUM | kept |
| TEN-051 | H-272 | H-272 | MEDIUM | kept |
| TEN-051 | H-273 | H-273 | MEDIUM | kept |
| TEN-051 | H-274 | H-274 | HIGH | kept |
| TEN-051 | H-275 | H-275 | HIGH | kept |
| TEN-053 | H-276 | H-276 | MEDIUM | kept |
| TEN-053 | H-277 | H-277 | HIGH | kept |
| TEN-053 | H-278 | H-278 | HIGH | kept |
| TEN-053 | H-279 | H-279 | MEDIUM | kept |
| TEN-054 | H-280 | H-280 | MEDIUM | kept |
| TEN-054 | H-281 | H-281 | HIGH | kept |
| TEN-054 | H-282 | H-282 | MEDIUM | kept |
| TEN-054 | H-283 | H-283 | MEDIUM | kept |
| TEN-054 | H-284 | H-284 | HIGH | kept |
| TEN-055 | H-288 | H-288 | HIGH | kept |
| TEN-057 | H-289 | H-289 | HIGH | kept |
| TEN-060 | H-285 | H-285 | HIGH | kept |
| TEN-060 | H-286 | H-286 | HIGH | kept |
| TEN-060 | H-287 | H-287 | MEDIUM | kept |
| TEN-073 | H-260 | H-481 | HIGH | renumbered: H-260 already held |
| TEN-073 | H-261 | H-482 | HIGH | renumbered: H-261 already held |
| TEN-073 | H-262 | H-483 | HIGH | renumbered: H-262 already held |
| TEN-073 | H-263 | H-484 | HIGH | renumbered: H-263 already held |
| TEN-084 | H-265 | H-265 | HIGH | kept |
| TEN-084 | H-266 | H-266 | MEDIUM | kept |
| TEN-084 | H-267 | H-267 | HIGH | kept |
| W08 | H-403 | H-403 | MEDIUM | kept |
| W08 | H-404 | H-404 | MEDIUM | kept |
| W08 | H-405 | H-405 | LOW | kept |
| W08 | H-406 | H-406 | MEDIUM | kept |
| W09 | H-400 | H-400 | HIGH | kept |
| W09 | H-401 | H-401 | HIGH | kept |
| W09 | H-402 | H-402 | HIGH | kept |
| W10 | H-329 | H-329 | MEDIUM | kept |
| W10 | H-320 | H-320 | MEDIUM | kept |
| W11 | H-321 | H-321 | HIGH | kept |
| W11 | H-328 | H-328 | LOW | kept |
| W12 | H-323 | H-323 | MEDIUM | kept |
| W13 | H-324 | H-324 | HIGH | kept |
| W14 | H-325 | H-325 | HIGH | kept |
| W14 | H-327 | H-327 | HIGH | kept |
| W15 | H-322 | H-322 | MEDIUM | kept |
| W17 | H-330 | H-330 | HIGH | kept |
| W17 | H-331 | H-331 | MEDIUM | kept |
| W18 | H-331 | H-485 | MEDIUM | renumbered: H-331 already held |
| W18 | H-332 | H-332 | LOW | kept |
| W19 | H-NEW-1 | H-486 | MEDIUM | placeholder |
| W19 | H-NEW-2 | H-487 | LOW | placeholder |
| W19 | H-NEW-3 | H-488 | MEDIUM | placeholder |
| W19 | H-NEW-4 | H-489 | MEDIUM | placeholder |
| W19 | H-NEW-5 | H-490 | LOW | placeholder |
| W20 | H-NEW-9 | H-491 | LOW | placeholder |
| W20 | H-NEW-10 | H-492 | MEDIUM | placeholder |
| W20 | H-NEW-11 | H-493 | MEDIUM | placeholder |
| W20 | H-NEW-12 | H-494 | MEDIUM | placeholder |
| W21 | H-NEW-13 | H-495 | HIGH | placeholder |
| W21 | H-NEW-14 | H-496 | HIGH | placeholder |
| W21 | H-NEW-15 | H-497 | MEDIUM | placeholder |
| W21 | H-NEW-16 | H-498 | LOW | placeholder |
| W22 | H-NEW-6 | H-499 | MEDIUM | placeholder |
| W22 | H-NEW-7 | H-500 | LOW | placeholder |
| W22 | H-NEW-8 | H-501 | LOW | placeholder |
| W23 | H-350 | H-350 | MEDIUM | kept |
| W23 | H-351 | H-351 | MEDIUM | kept |
| W23 | H-352 | H-352 | LOW | kept |
| W24 | H-355 | H-355 | LOW | kept |
| W24 | H-356 | H-356 | LOW | kept |
| W25 | H-357 | H-357 | MEDIUM | kept |
| W25 | H-358 | H-358 | MEDIUM | kept |
| W26 | H-359 | H-359 | MEDIUM | kept |
| W27 | H-NEW-1 | H-502 | MEDIUM | placeholder |
| W27 | H-NEW-2 | H-503 | MEDIUM | placeholder |
| W28 | H-360 | H-360 | MEDIUM | kept |
| W28 | H-361 | H-361 | MEDIUM | kept |
| W29 | H-362 | H-362 | HIGH | kept |
| W29 | H-363 | H-363 | MEDIUM | kept |
| W29 | H-364 | H-364 | MEDIUM | kept |
| W30 | H-NEW-1 | H-504 | HIGH | placeholder |
| W30 | H-NEW-2 | H-505 | HIGH | placeholder |
| W30 | H-NEW-3 | H-506 | MEDIUM | placeholder |
| W31 | H-NEW-4 | H-507 | HIGH | placeholder |
| W31 | H-NEW-5 | H-508 | HIGH | placeholder |
| W32 | H-335 | H-335 | MEDIUM | kept |
| W33 | H-336 | H-336 | MEDIUM | kept |
| W33 | H-337 | H-337 | LOW | kept |
| W33 | H-338 | H-338 | MEDIUM | kept |
| W34 | H-339 | H-339 | MEDIUM | kept |
| W34 | H-340 | H-340 | LOW | kept |
| W34 | H-341 | H-341 | LOW | kept |
| W35-W37 | H-342 | H-342 | HIGH | kept |
| W35-W37 | H-343 | H-343 | MEDIUM | kept |
| W35-W37 | H-344 | H-344 | HIGH | kept |
| W35-W37 | H-345 | H-345 | MEDIUM | kept |
| W35-W37 | H-346 | H-346 | LOW | kept |
| W38-W55 | H-347 | H-347 | HIGH | kept |
| W38-W55 | H-348 | H-348 | MEDIUM | kept |
| W38-W55 | H-349 | H-349 | MEDIUM | kept |
| W39 | H-365 | H-365 | LOW | kept |
| W39 | H-366 | H-366 | MEDIUM | kept |
| W39 | H-367 | H-367 | LOW | kept |
| W40 | H-368 | H-368 | HIGH | kept |
| W40 | H-369 | H-369 | MEDIUM | kept |
| W40 | H-370 | H-370 | MEDIUM | kept |
| W40 | H-371 | H-371 | MEDIUM | kept |
| W41 | H-372 | H-372 | MEDIUM | kept |
| W41 | H-373 | H-373 | LOW | kept |
| W41 | H-374 | H-374 | LOW | kept |
| W42 | H-NEW-1 | H-509 | MEDIUM | placeholder |
| W42 | H-NEW-2 | H-510 | MEDIUM | placeholder |
| W42 | H-333 | H-333 | MEDIUM | kept |
| W43 | H-331 | H-511 | MEDIUM | renumbered: H-331 already held |
| W43 | H-NEW-3 | H-512 | MEDIUM | placeholder |
| W43 | H-NEW-4 | H-513 | LOW | placeholder |
| W44 | H-375 | H-375 | HIGH | kept |
| W44 | H-376 | H-376 | MEDIUM | kept |
| W44 | H-377 | H-377 | HIGH | kept |
| W45 | H-NEW-4 | H-514 | HIGH | placeholder |
| W45 | H-NEW-5 | H-515 | LOW | placeholder |
| W45 | H-NEW-6 | H-516 | MEDIUM | placeholder |
| W46 | H-378 | H-378 | MEDIUM | kept |
| W46 | H-379 | H-379 | HIGH | kept |
| W47 | H-333 | H-517 | MEDIUM | renumbered: H-333 already held |
| W47 | H-NEW-5 | H-518 | HIGH | placeholder |
| W47 | H-NEW-6 | H-519 | MEDIUM | placeholder |
| W48 | H-389 | H-389 | LOW | kept |
| W48 | H-390 | H-390 | LOW | kept |
| W48 | H-391 | H-391 | MEDIUM | kept |
| W49 | H-392 | H-392 | MEDIUM | kept |
| W49 | H-393 | H-393 | LOW | kept |
| W49 | H-394 | H-394 | LOW | kept |
| W50 | H-326 | H-326 | MEDIUM | kept |
| W51 | H-395 | H-395 | MEDIUM | kept |
| W51 | H-396 | H-396 | LOW | kept |
| W52 | H-397 | H-397 | LOW | kept |
| W53 | H-398 | H-398 | MEDIUM | kept |
| W53 | H-399 | H-399 | LOW | kept |
| W54 | H-353 | H-353 | LOW | kept |
| W54 | H-354 | H-354 | LOW | kept |
| W56 | H-NEW-1 | H-520 | MEDIUM | placeholder |
| W56 | H-NEW-2 | H-521 | MEDIUM | placeholder |
| W56 | H-NEW-3 | H-522 | MEDIUM | placeholder |
| W7A | H-410 | H-410 | HIGH | kept |
| W7A | H-411 | H-411 | MEDIUM | kept |
| W7A | H-412 | H-412 | HIGH | kept |
| W7A | H-413 | H-413 | LOW | kept |
| W7A | H-414 | H-414 | HIGH | kept |
| W7B | H-430 | H-430 | HIGH | kept |
| W7B | H-431 | H-431 | MEDIUM | kept |
| W7B | H-432 | H-432 | MEDIUM | kept |
| W7B | H-433 | H-433 | MEDIUM | kept |
| W7B | H-434 | H-434 | MEDIUM | kept |
| W7B | H-435 | H-435 | MEDIUM | kept |
| W7B | H-436 | H-436 | HIGH | kept |
| W7B | H-437 | H-437 | MEDIUM | kept |
| W7B | H-438 | H-438 | HIGH | kept |
| W7B | H-439 | H-439 | LOW | kept |
| W7C | H-450 | H-450 | LOW | kept |
| W7C | H-451 | H-451 | MEDIUM | kept |
| W7C | H-452 | H-452 | HIGH | kept |
| W7C | H-453 | H-453 | HIGH | kept |
| W7C | H-454 | H-454 | HIGH | kept |
| W7C | H-455 | H-455 | HIGH | kept |
| W7C | H-456 | H-456 | HIGH | kept |
| W7C | H-457 | H-457 | LOW | kept |
| W7C | H-458 | H-458 | MEDIUM | kept |
| W7C | H-459 | H-459 | LOW | kept |
| TEN-066 | H-T21 | H-T21 | (unchanged) | not added: H-T21 is an existing row (TEN-006, TEN-065, TEN-066); the TEN-066 tests and the partial status were appended to its Verified by cell |
| (fold) | - | H-523 | HIGH | raised on folding: plain-text phone numbers (DEC-856) |

### Severity (provisional)

The hazard log had no severity scale (every row, 203 of them before this fold, is `TBD`, and its rule said not to guess). On the orchestrator's instruction the 229 rows of this fold carry a severity on a three-point scale, set conservatively on the consequence before controls, and the rule in the log's header was amended to say so (rows of earlier waves are still `TBD`; filling them was not asked). The scale: **HIGH** a wrong, stale or missing clinical decision or safety escalation, patient-linked data or another tenant's data exposed, or authority a person or component should not have; **MEDIUM** a degraded clinical or operational workflow, non-patient personal or organisational data exposed, or a control whose failure another control contains; **LOW** tests, tooling, wording or cosmetics with no route to a person. Result: 73 HIGH, 103 MEDIUM, 52 LOW among the fragment rows, plus H-523 HIGH. This is a provisional rating by the orchestrator, not the clinical safety officer's; they replace it. No fragment carried `TBD`; the "TBD" the orchestrator named is the log's own.

### Statuses written on folding

- Where a fragment said its integration tests were "written, not run" and a fix-round fragment says they ran green (F5A for R09, R10, R12, R13, R17 and L02; F5B for TEN-027, TEN-028, TEN-041 and TEN-073), the status cell ends "Later: ... ran green in ...". Nothing was re-run here.
- Where W7A, W7B or W7C serves a back-end read or route that an open front-end hazard waited for (H-320, H-321, H-323, H-325, H-350, H-351, H-353, H-355, H-356, H-359, H-361, and the suspension hazard of W42), the status says "back end now serves it (DEC); open until the BFF is wired". None of those was closed.
- Hazards left open and marked OPEN with a decision that is not accepted: H-375 and H-514 (DEC-855), H-495 and H-496 (DEC-854), H-523 (DEC-856). H-329 (a lead opening a call) and the product questions H-357 and H-354 are open and not delegated.
- H-T19 and the other hazards named only inside fragment texts (for example `H-N12`, `H-N05`, `H-N06`, `H-N08` in TEN-051 and TEN-053) are the tenancy audit's own ids and are not rows of the log; not added.

## Known issues

Folded as one-line rows in the existing format, in fragment order, appended at the end of the table. 372 rows from the fragments (the TEN-027 integration row that only said it superseded an earlier row was not added), 3 rows from the F6B report (F6B-1 to F6B-3), and 3 rows that record the open decisions (DEC-854, DEC-855, DEC-856): 378 rows added in all. The row ids are the fragments' own (for example `W7B A1`, `W7A-K3`). Where a fragment row had no trigger, the fragment's wording was copied; no row was invented.

### Front-end rows the back end now serves

77 front-end rows (W10 to W56) name a stub or a gap that W7A, W7B or W7C routes now serve. Each is kept and its text ends "Back end now serves it (<task, decision and route>); the BFF route still answers not-built until it is wired." (or "serves part of it" where the back end sends only some of the fields; the part not sent stays open, for example the service phone, coverage and travel legs of `$filter-options`, W7A-K1). F6A and W7C say the reporter app and the other BFF routes are not wired; no fragment shows any of them wired, so none was marked wired. Rows per fragment: W10 (2), W11 (3), W12 (1), W13 (3), W14 (2), W15 (3), W16 (2), W17 (2), W18 (3), W23 (2), W24 (2), W25 (2), W26 (2), W27 (2), W28 (2), W29 (4), W30 (1), W31 (3), W33 (3), W34 (4), W35-W37 (5), W38-W55 (3), W39 (1), W40 (2), W42 (3), W43 (4), W44 (5), W45 (1), W46 (1), W50 (1), W54 (2), W56 (1).

### Existing rows closed

Deleted from `known-issues.md`, each because a fragment says so (the reason in brackets):

- / TEN-005 / `test_tenant_isolation.py` starts a second Neo4j container (the contracted sch ... (TEN-034 (DEC-461): `contracted_container` and `contract_schema` are removed; the generated test runs on the shared harness)
- / TEN-032 / `contracted_container()` starts a second Neo4j container only to drop keys tha ... (TEN-034 (DEC-461): removed)
- / TEN-038 / `network.events` and `projection.work` are not in `infra/servicebus-config.jso ... (TEN-055 (DEC-545): the queue `projection.work`, the topic `network.events` and the four `network-projector` subscriptions are in the emulator config; `QUEUES` holds `projection.work`)
- / TEN-040 / The unauthenticated routes of the text-code flow (`POST /identity/code`, U25,  ... (TEN-041 (DEC-520): the invitation, device, pairing and inbound-number resolvers are built)
- / TEN-020 / A bound network scope refuses every tenant message, so the projector (TEN-055) ... (TEN-055 (DEC-545 item 2): the projection message is published from the source tenant's binding (`check_publishable` is unchanged))
- / TEN-018 / The front end still mints the back-end token without `tenant` and `epoch` (W09 ... (TEN-043 (DEC-522, DEC-527), TEN-044 (DEC-601) and W09 (DEC-760): the back end issues every token; the BFF holds no signing secret)
- / TEN-026 / The role mappings and binding exist as records but nothing reads them at sign- ... (TEN-043 (DEC-523): the exchange reads the tenant's role mappings and verified Entra binding)
- / O02 / The session carries no tenant claim yet (sealSession writes a fixed set of claims) ... (TEN-044 (DEC-600): the session carries `tenantId` and the `host` it was made on; O02 (W6I) adds `tenant.id` from the session)
- / O06 / The session carries no tenant claim yet, so the edge cannot take the tenant from a ... (TEN-044 (DEC-600) and W09 (DEC-760))
- / W05 / The page redirects to `/screen/pair`, which W08 builds, so until then that address ... (W08 (DEC-761): `/screen/pair` is built)
- / W06 / The wall sends the browser to `/screen/pair` when a refetch is refused; until W08  ... (W08 (DEC-761): `/screen/pair` is built)
- / W04 / The thank-you page's "See the live board" goes to `/sign-in`, which W09 builds. Un ... (W09 (DEC-760): `/sign-in` is built)
- / U20 / The advisor's dialog (W21) and the service's cancelled page (W22) are not built. / ... (W21 and W22 are built (fragments W21, W22))
- / U33 / The prompt's "four Subscription nodes, one per kind" is not built: P17 stores one  ... (R12 (DEC-833): one Subscription per practitioner, one extension per setting, is the accepted mapping)
- / R08 / TEN-018 / Two tenants cannot each hold an AuditHead on the shared schema (old sing ... (TEN-032 (DEC-450 item 5) and TEN-033 (DEC-460 item 2): the shared schema allows a second tenant's head and `clean_graph` gives both run tenants one)
- / U21 / WithdrawBooking and ReportNotReached send no text to the service; the advisor aler ... (W21 (DEC-838): the alert is built)

Edited, not deleted:

- / R11 / `SubmitRegistration` with persist is built by `bootstrap/wiring.submit_r ...
- / U38 / The CodeVerifier is not adapted to U25's VerifyTextCode in the container ...
- / O09 / The advisor journey spec is deferred. Its pages (W10 to W16) are now bui ...

### Rows not added because a later fragment of the same waves closes them

- R10 R10: No route for `StartReview`, `ExplainCheck`, `GetReviewStatus`, `ResendInvitation`, `RecordTestAnswer ... (closed by W7B (DEC-794, DEC-797, DEC-809, A1 and A4 routes))
- R10 R10: The integration tests are written, not run; the approval-blocked 409 and the happy path to `approved ... (closed by fix round F5A (the route tests ran green))
- R12 R12: The integration tests are written, not run ... (closed by fix round F5A)
- R13 R13: The integration tests are written, not run ... (closed by fix round F5A)
- TEN-027 TEN-027: `SendPrompts` and the ladder do not compare the command's actor tenant with the bound tenant (the ac ... (closed by TEN-027-integration (fix round F5B))
- TEN-041 TEN-041: The invitation page (W33) needs the service, role and masked phone of an invitation; `PreSessionReso ... (closed by W7C (DEC-810, `GET /invitations/{token}`))
- W7A W7A-K9: `tests/integration/graph_store/test_person_repository.py::test_sixteen_racing_saves_of_one_new_pract ... (closed by F6B (the racing-save test and `Q-RES-UPSERT-ROOT`))
- W7B W7B C: The test prompt and prompts in general go to the post's own number: a cover's number (`cover-<role i ... (closed by F6B)
- W7C W7C-K2: The text senders address a message by the recipient post's own stored number (`contacts.get_phone(ro ... (closed by F6B (the text and email senders read the cover))
- W7C W7C-K4: `/reporter/...` routes take the reporter token; the issue of that token after a verified code and PI ... (closed by W7B (DEC-790 to DEC-792 issue the reporter token))

### Not closed (for the orchestrator to look at)

These rows or hazards may be stale, but no fragment says they are fixed, so they were not changed:

- TEN-032, "Test comments and docstrings in about thirty integration test files still say 'until TEN-032'": TEN-034 records a similar row of its own (about ten files).
- TEN-039, "`CriteriaApproved` does not rebuild the board: `criteria.events` has no `board-projector` subscription": TEN-055 adds a `network-projector` subscription on `criteria.events`, not a `board-projector` one.
- TEN-065 rows (the use cases and the ratchet allow-list still compute in London): TEN-027 threads the zone through three use cases (SendPrompts, the ladder, the alert use cases) but the row names thirteen files and was not re-counted.
- G11, U12, U35 (network variants of the candidate filter, the options and the week summary): the network scope exists in the back end (TEN-051 to TEN-060), but no fragment wires those use cases to it; R12 still refuses `scope=network`.
- TEN-028, "The first sign-in that consumes the invitation ... is not built": TEN-043 and W09 build the staff sign-in, and W7B the reporter and registration sign-ins; no fragment says the tenant administrator's first sign-in consumes the invitation.
- R09, L02 and R10 ("no link host or referral wording per tenant in production") and the W7B C row ("production has `_no_link_host` until TEN-028"): TEN-027 composes `DirectoryLinkBase`, but no fragment says the container fields are wired in production; the rows were kept.
- TEN-018, "A POST with no body and no JSON content type is answered 415": F5A hit the same behaviour and fixed the tests, not the middleware.
- O02, "The back-end FHIR client makes a new traceparent instead of forwarding the BFF request's": TEN-045 reworks the client but its fragment does not mention the traceparent.
- W05, "`$board` does not yet send an `organisation` part": TEN-049 reads the tenant profile per host; no fragment says the board sends the part.
- The fragments' own "Not run" statements (for example the e2e and Playwright runs of W19 to W56, `e2e/security.spec.ts` of S01, the pinned-collector run of O02) stand as written.

## Contracts

Merged into the existing task sections of `docs/spec/contracts.md` where one fits, and into new sections where none does. Each fragment's contract bullets are a sub-section headed with the fragment's id and decision numbers; the text is the fragment's own.

- Under existing sections: L02 under "Link pages (L01, DEC-167)"; O02, O03, O05 and S01 under their own sections; TEN-027 under "ConfirmCapacity (U02, DEC-112)"; TEN-028 and TEN-073 under "Tenant domain model, settings and lifecycle (TEN-006, DEC-155)"; TEN-033, TEN-034 and TEN-035 under "Tenant per run in the test harness (TEN-003, DEC-147)", with a summary of the shared harness added at the head; TEN-041 and TEN-043 under "REST edge tenant binding (TEN-018, DEC-250)"; TEN-084 under "Support access (O06, DEC-206)"; TEN-051, TEN-057, TEN-058, TEN-059 and TEN-060 under "Network domain model and rules (TEN-036, DEC-235)"; TEN-053, TEN-054 and TEN-055 under "Projection allowlist, DTOs and privacy guard (TEN-052, DEC-270)"; TEN-066 under "Tenant policy in the rules (TEN-021, DEC-233)"; W08 under "Wall screen pairing endpoints (R15, DEC-224)"; W09 and TEN-044 to TEN-050 under "Staff sign-in and role guard (W09, DEC-210)".
- New sections: "Statement scopes: tenant, network, global and platform" (the four-scope query model, with TEN-037's names); "Booking, alert, registration, clinical and admin routes (wave 5)"; the front-end groups "Advisor screens", "Shift lead screens", "Booking link pages and the advisor booking card", "Registration and criteria screens", "Reporter app", "Executive screens", "Clinical, help and support-code screens", "Console, insight, planning, tour and learning screens"; the three back-end route sections for W7A, W7B and W7C, each with the route tables (W7A-routes and W7B-routes as tables; W7C-routes converted from per-route lists to one table of route, caller, BFF route and answers, with the BFF stub table beside it); and "Integration fixes of the build waves" (F5A, F5D, F6A, F6B and the TEN-0xx integration notes).
- Explicit corrections: (1) the BFF no longer holds a signing secret: the "Staff sign-in and role guard" section starts with a correction note and its `lib/auth/staff.ts`, `lib/auth/oidc.ts` and settings bullets are rewritten (`mapRoles`, `mintBackendToken`, `DIUCS_ENTRA_BINDINGS`, `BACKEND_JWT_SECRET`, `Binding`, `bindingFor` and `Identity` are gone; tokens come from `POST /auth/token`, `/auth/device-token` and `/auth/operator-token`, DEC-522 to DEC-530); (2) the session cookie carries `tenantId` and `host` (DEC-600); (3) the shared test harness (parallel, shared Neo4j, `make test-integration`): the "Testing and persistence" text that said tests run serially, the `clean_graph` bullet and the `count_nodes` bullet were rewritten; (4) the four-scope query model: a new section (`platform` scope, `run_platform_query`, `PlatformStatementMisuse`, the network scope kinds `NETWORK_KINDS`/`BOTH_KINDS`, `ScopeKindMismatch`, the read-only unit); (5) `QUEUES` holds `projection.work` (added to the event bus bullet); (6) the planning view is at `/planning/flows` (a note in the repository layout; the W51 fragment said `/planning`, which is the executive home, and the front-end tree has `app/(planning)/planning/flows/page.tsx`).

## Owner decisions delegated to the orchestrator (DEC-133)

### Accepted, with the reasoning written into the entry

- DEC-820 (a reporter may hand their own posts to a cover for at most 14 days): accepted. It stays inside one tenant, covers only posts the reporter owns, ends at 23:59 in the tenant's zone, keeps the number out of the audit, and the lead sees the cover. The 14 days is an [ASSUMED] limit to review. Residual risk is H-456 (HIGH).
- DEC-816 (a confirm from the app is judged at request time): accepted. The app is open only while the reporter is in it; the figure rules (a Y confirms only a current figure, two-hour age, nothing written since, the out-of-range reply and the confirm limit) are not relaxed.
- DEC-772 (W7A B5: the support code read shows that a code is live and until when, not the code): accepted. Keeping the code readable would store a recoverable live code in the graph for four hours; W56's open question is answered.
- DEC-771 (the advisor's criteria history is the current version only): accepted. The dialog must never show an advisor text that is not approved.
- DEC-774 (the clinician's advice note is shown to the advisor who asked and to clinical advisors; W7A B1): accepted. The advisor who asked already holds the case; residual risk H-412 (HIGH): patient detail typed into the note cannot be recognised by the back end.
- DEC-503 (the platform scope for registry writes): accepted; the narrowest door that works.
- DEC-853 (tenant from the Host only on pre-session routes): written as one consolidated accepted decision, since TEN-041, TEN-043, W7B and W7C each applied it without recording it.
- The W23 to W27 and W54 decisions marked "for the owner to confirm": accepted as written, with fold notes on DEC-687 (the product question of the unsaved registration fields stays open, H-357) and DEC-688 (the back end now has `Measure.OTHER`, W7B DEC-793 item 4; the BFF refusal stays until it is wired).
- W56 item 3 (does the sealed session hold the support code): answered by DEC-772: no.

### Left open (not accepted), severity HIGH

- DEC-854 (W21, H-NEW-13 now H-495): a withdrawal alert is acknowledged on any action from it, without phoning; the acknowledgement stops the shift lead's escalation. Not sound as built: it ends the safety net for a patient whose booking failed. Recommended: acknowledge only from an explicit "I have phoned" answer (no back-end change needed). W21 is not to be shipped to a pilot as built.
- DEC-855 (W44 item 4, W45, H-375, H-514): the clinical advice form is shown without the case's details, and the advisor's dialog cannot show the advice. The back end serves both since W7A (DEC-774); the BFF and screens are not wired. Rule to build to: no advice form without the case read; never "waiting" after advice exists. The clinical advice flow is not to be enabled for a pilot until then.
- DEC-856 (R08 known issue, widened by W7B, W7C and F6B; hazard H-523): phone numbers are kept in plain text on ProtectedContact nodes. Needs an information-governance decision (application-level encryption, the managed database's encryption at rest, or an accepted risk for a pilot); not made here.

### Left open, not HIGH, not delegated

- W7A-K8 and H-329: a lead's case calls are a 404 because the case routes admit advisor and clinical and the guard admits advisor and lead (DEC-632); a role decision.
- H-357 (specialty, appointment and notes are not saved) and H-354 (`contactRole` and `partOf`): product questions whether the fields are kept; W7B did not add them.
- H-363 / `numberToCall`: the platform holds no register number for a service not yet listed, so the lead types it (W7B DEC-795); the comparison of the number called with the register is still unbuilt.

## Ledger reconciliation (the orchestrator will deliver these; the ledger was not touched)

The ledger (`delivery.py status`) shows 109 of 301 tasks delivered and, for every task below, `not-started` (or `stale` where marked), although the fragments say the code is on `integration/build`. Where the fragment says verification is still to come (build-wave rules), the task is built, not verified; delivery needs the verification stage.

**This fold (85 task ids):** L02, O02, O03, O05, R09, R10, R12, R13, R17, S01, TEN-027, TEN-028, TEN-033, TEN-034, TEN-035, TEN-037, TEN-041, TEN-043, TEN-044, TEN-045, TEN-046, TEN-047, TEN-048, TEN-049, TEN-050, TEN-051, TEN-053, TEN-054, TEN-055, TEN-057, TEN-058, TEN-059, TEN-060, TEN-066, TEN-073, TEN-084, W08, W09 (stale), W10, W11, W12, W13, W14, W15, W16, W17, W18, W19, W20, W21, W22, W23, W24, W25, W26, W27, W28, W29, W30, W31, W32, W33, W34, W35, W36, W37, W38, W55, W39, W40, W41, W42, W43, W44, W45, W46, W47, W48, W49, W50, W51, W52, W53, W54, W56.

**Waves 1 to 3 (folded earlier, still shown as not delivered; 85 task ids, including R08, R11 and U25 beyond the ones named by the orchestrator):** G11, G13, I10, I11, I12, I13, I14, I15, O01, O04, O06, O07, O08, O09, P17, P18, P19, P20, R07, R08, R11, R14, R15 (stale), R16 (stale), R18, TEN-012, TEN-013, TEN-014, TEN-016, TEN-017, TEN-018, TEN-019, TEN-020, TEN-021, TEN-022, TEN-023, TEN-024, TEN-025, TEN-026, TEN-029, TEN-030, TEN-031, TEN-032, TEN-036, TEN-038, TEN-039, TEN-040, TEN-042, TEN-052, TEN-063, TEN-064, TEN-065, U11 (stale), U12, U13, U14, U15, U16, U17, U18, U19, U20, U21, U22, U23, U24, U25, U26, U27, U28, U29, U30, U31, U32, U33, U34, U35, U36, U37, U38, U39, U40, U41, U42, U43.

The five tasks the ledger shows `stale` are I05, R15, R16, U11 and W09. W7A, W7B, W7C, F5A, F5D, F6A, F6B and the integration notes are bundles and fixes, not ledger tasks. Neither list was checked against git: the ids come from the fold audits and the fragment names. W09's ledger note says "writing red tests", which the fragment W09 contradicts (built and unit-tested in bundle W6J).

## Skill, CLAUDE.md and brief wording

- `CLAUDE.md` in this worktree already states the shared parallel harness and says never to wrap pytest in `flock` (TEN-035 removed the lock rule); verified, not edited. The primary checkout's `CLAUDE.md` on `main` still carries the old one-line rule ("Neo4j tests run one at a time: `flock /tmp/diucs-neo4j-tests.lock`"); it is replaced when `integration/build` is merged into `main`.
- `references/multi-tenancy.md`: item 9 now describes the four statement scopes as built and the network scope; item 10 names DEC-528 and DEC-525 (no standing cross-tenant access). The testing section already described the shared harness (TEN-035); not re-added or changed.
- `SKILL.md`: the tenancy paragraph says the four scopes, the built network scope, no standing cross-tenant access, the back-end token exchange and the lock-free parallel harness.
- `references/collective.md`, `assets/verifier-brief.md`, `assets/builder-brief.md`: the remaining lines that told a verifier or an orchestrator to take the Neo4j lock, to run each directory "under the lock", or to follow the transitional rule, were rewritten (the main-merge lock `flock /tmp/diucs-main.lock` is a different lock and was kept). The line "If a run is waiting on the Neo4j lock, let it wait" now names the harness locks only (a private container being started, an exclusive session waiting).

## Not verified

- This was a documentation fold: nothing was run for it except these checks, run after the fragments were removed: `delivery.py check-messages` printed the clean line (no model name, no trailer on unpushed commits); the back-end keyword run (`uv run pytest tests/unit tests/architecture -q -p no:cacheprovider -k "doc or decision or hazard or ledger or fragment or contract"`) passed (144 selected); `tests/unit/test_parallel_harness_config.py` (which fails if the old lock rule returns in a live instruction) passed (28); the skill's script tests (`.claude/skills/diucs-delivery/scripts`, run with the back end's virtual environment because the system `python3` has no pytest) passed (67). No Neo4j, Docker, Service Bus, Redis, front-end test or e2e test was run.
- Every status, "passed" count, "ran green" and "integration run" in the folded hazards, known issues and the integration sections is copied from the fragments. None was checked in this repository, and the code was not read to confirm a closure, except the three places named here: the `QUEUES` set (`event_bus.py` holds `projection.work`), the planning page path (`frontend/app/(planning)/planning/flows/page.tsx` exists) and the worktree `CLAUDE.md` wording.
- The closures of existing known-issue rows rest on the fragments' own statements and on the dependencies they name (TEN-034 removes `contracted_container`; TEN-055 adds the queue and subscriptions; TEN-043 and TEN-044 replace the BFF's token minting; W08 and W09 build `/screen/pair` and `/sign-in`; W21 and W22 build the booking dialog and cancelled page; R12 decides the Subscription mapping).
- Severity is provisional and conservative (see Hazards); the clinical safety officer has not seen it. The three open decisions are recommendations with their reasons, not decisions.
- The statement that no fragment shows a BFF route wired to a W7A, W7B or W7C route rests on F6A, W7C-routes ("the BFF has not been moved onto these routes") and the W7B and W7A fragments; the front-end tree was not searched for it.
- Contract bullets are the fragments' own text. Paths, names and numbers in them (and in the route tables) were not checked against the code, apart from the three places above.

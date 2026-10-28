# Archived branches (2026-10-28)

DEC-133 keeps `main` as the only long-lived branch. These 22 branches held commits that are not in `main` (pre-rewrite and round backups of rebased task branches, the ledger backup branch, and the original F01 and F03 red-then-green evidence). The remote does not accept tag pushes, so their commits are preserved in `branches-2026-10-28.bundle` (verified with `git bundle verify`).

Restore any of them into a clone:

```bash
git fetch docs/delivery/archive/branches-2026-10-28.bundle 'refs/tags/archive/*:refs/tags/archive/*'
git log --oneline archive/task-F01-green
```

| Archive tag | Commit | Original branch |
|---|---|---|
| `archive/backup-I06-4c83c80` | `4c83c80` | `backup-I06-4c83c80` |
| `archive/backup-I06-e450a65` | `e450a65` | `backup-I06-e450a65` |
| `archive/backup-I06-fb55b8f` | `fb55b8f` | `backup-I06-fb55b8f` |
| `archive/backup-P04-round3` | `989e7ee` | `backup-P04-round3` |
| `archive/backup-P04-round4` | `0a87b64` | `backup-P04-round4` |
| `archive/backup-P04-round5` | `3b26060` | `backup-P04-round5` |
| `archive/backup-P13-tip-984b6f3` | `984b6f3` | `backup-P13-tip-984b6f3` |
| `archive/backup-P14-tip-3cbc66d` | `3cbc66d` | `backup-P14-tip-3cbc66d` |
| `archive/backup-P14-tip-cced09b` | `cced09b` | `backup-P14-tip-cced09b` |
| `archive/backup-P15-1d913cb` | `1d913cb` | `backup-P15-1d913cb` |
| `archive/backup-P15-dcdb660` | `dcdb660` | `backup-P15-dcdb660` |
| `archive/backup-P16-r1` | `6adfca9` | `backup-P16-r1` |
| `archive/backup-P16-r3` | `a347e04` | `backup-P16-r3` |
| `archive/backup-R03-tip-c14ec1c` | `c14ec1c` | `backup-R03-tip-c14ec1c` |
| `archive/backup-U01-pre-rebuild` | `647a2f7` | `backup-U01-pre-rebuild` |
| `archive/ledger-refresh` | `1383d1e` | `ledger-refresh` |
| `archive/r01-pre-rewrite` | `5104564` | `r01-pre-rewrite` |
| `archive/r01-round2-backup` | `b0a482d` | `r01-round2-backup` |
| `archive/r01-round3-backup` | `52dde3d` | `r01-round3-backup` |
| `archive/task-F01-green` | `0f37034` | `task-F01-green` |
| `archive/task-F01-red-green` | `7e4f04f` | `task-F01-red-green` |
| `archive/task-F03-redproof` | `cfcf491` | `task-F03-redproof` |

- `ten-001-seam-warn-2026-10-28.bundle`: tip `2bdca21` of `task/TEN-001-seam-warn`, the withdrawn Cypher-reader seam (DEC-142). Not merged. Read the verifier sections in its `docs/delivery/evidence/TEN-001.md` for the leak shapes found in rounds 3 to 5.

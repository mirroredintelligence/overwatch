# Known issues

Non-blocking findings and residual limits (DEC-141). A verifier may not hold a task for any item here. Each line: task, what, where, trigger to fix.

| Task | What | Where | Trigger to fix |
|---|---|---|---|
| U02 | A report or confirmation with an explicit effective time equal to the latest confirmed figure's time is accepted, and board order then falls back to whole-second `lastUpdated`, which is undefined on a same-second tie. Fix: refuse `<=` against the confirmed time, and update DEC-140 item 3. | `report_capacity.py` (DEC-140 check), `confirm_capacity.py` | Next change to the report or confirm use case, or before two-host deployment. |
| U02 | DEC-139 item 4 and DEC-140 item 4 say a default-time number cannot be earlier than a confirmation. That holds only with one clock across hosts. Fix: clamp the default time to the latest effective time of the service's figures. | `report_capacity.py`, `confirm_capacity.py` | Before more than one application host runs against one database. |
| U02 | A back-dated number behind a later non-confirmed number is accepted and hidden on the board (U01 behaviour, DEC-100, DEC-140 item 5). | `report_capacity.py` | A decision on back-dating, when the board spec is reviewed. |
| F10b | Verifier-authored sections in `docs/delivery/evidence/F10b.md` quote the builder's earlier wording in a way that a later builder paraphrased. The code is correct. The file is about 1,000 lines. | `docs/delivery/evidence/F10b.md` | None. Do not edit verifier sections. |
| F10b | Neo4j harness suite (`tests/integration/support`, 16 tests) was not re-run after rounds 7 to 11, which changed only a regex pattern, docstrings and unit tests. | `backend/tests/integration/support` | Next full integration run. |
| (product) | `check_staff_text` counts digits with `str.isdecimal()`, so non-ASCII digits count as digits. Outside the reaper and harness. | `backend/src/diucs/domain/model/people.py` line 51 | Next privacy review of staff text checks. |
| (repo) | About 633 older commits carry `Co-Authored-By` trailers naming a model. Pushed history is not rewritten. | git history | None. New commits carry no model name. |
| (host) | About ten dangling anonymous Docker volumes remain from the earlier harness leak (DEC-128). | the Docker host | A cleanup run, when someone confirms none is in use. |
| (repo) | 103 stale remote branches. The sandbox proxy refuses ref deletion; a local script was given to the owner. | `origin` | The owner runs the script. |

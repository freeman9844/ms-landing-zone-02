# Final fix wave — 2026-09-29

Base: `4cdd010` (`feat/avnm-ipam-workshop`). Scope: two final-review findings only.

## Finding 1 — shared IPAM parent preflight

- `assert_shared_ipam_pool` still reads the pool first, then issues a read-only `az rest GET` for its exact parent Network Manager, pinned to the selected subscription and API version `2024-05-01`. It rejects unreadable/malformed replies, wrong full manager ID, location, subscription scope, nonempty management-group scope, unexpected scope accesses, and non-`Succeeded` readiness. Neither the manager nor the pool is written by preflight.
- `test_ipam_pool.py` covers a matching parent, read failure, malformed responses and each mismatch. The module 01 block also proves pool or manager failure occurs before `.workshop-state` creation; prior ready fixtures now supply both GET results.
- Participant and operator docs name **IPAM Pool User** (or equivalent pool-use permission) and Network Manager read access, require the operator to verify actual pool-use rights, and explicitly state read-only preflight does **not** prove allocation rights. Permission failures surface on real module 02 deployment. No speculative write or successful-allocation claim was added to preflight.

## Finding 2 — route evidence

- Modules 04–06 now describe the remote Spoke's actual `/20`, alongside the unchanged default `/0`; module 04 and 05 PASS lines print the resolved remote CIDRs instead of `/16`. The underlying dynamic route checks and default-route behavior are unchanged.
- `test_stepwise_docs.py` checks actual NIC output for both different remote CIDRs and rejects stale `/16` text in the three current modules. The operator validation guide continues to distinguish historical pre-IPAM `/16` evidence from current `/20` expectations.

## Local verification

All commands below ran from the feature worktree without live Azure resource calls:

| Command | Outcome |
|---|---|
| `python3 -m unittest discover -s tests -p 'test_ipam_pool.py' -v` | 10 tests, OK |
| `python3 -m unittest discover -s tests -p 'test_stepwise_docs.py' -v` | 37 tests, OK |
| `bash tests/validate.sh` | exit 0 |
| `az bicep build --file infra/shared-ipam.bicep --stdout > /dev/null` | exit 0 |
| `az bicep build --file infra/workshop-ipam-vnet.bicep --stdout > /dev/null` | exit 0 |
| `git diff --check` | exit 0 |

Concern: static/mock checks and Bicep compilation do not prove Azure allocation RBAC or service behavior. The approved read-only gate leaves actual allocation-permission failures to module 02 deployment. No live Azure calls, push, tag publication or cleanup were performed.

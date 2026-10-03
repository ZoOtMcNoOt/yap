# Core server dependency integrity

**Owner:** Grant McNatt. **Date:** 2026-10-03. **Status:** Local software checks passed; hosted integration pending.

The exact core lock reported advisories in PyJWT, cryptography and httpx2.
Supported published updates replace only four package versions; all other core
versions remain unchanged. Authentication policy and the qualification verifier
remain strict; the portable qualification gate's required test count includes
one new regression case.

| Package | Before → after | License |
| --- | --- | --- |
| PyJWT | 2.13.0 → 2.15.0 | MIT |
| cryptography | 49.0.0 → 50.0.2 | Apache-2.0 OR BSD-3-Clause |
| httpx2 | 2.10.0 → 2.13.1 | BSD-3-Clause |
| httpcore2 | 2.10.0 → 2.13.1 | BSD-3-Clause |

The core `uv.lock` retains registry URLs and exact distribution hashes. Published
metadata supports Python 3.12; a frozen exact sync installs the four updates.
Upstream sources: [PyJWT](https://github.com/jpadilla/pyjwt),
[cryptography](https://github.com/pyca/cryptography), and
[httpx2/httpcore2](https://github.com/pydantic/httpx2).
The isolated audit tool is [pip-audit 2.10.1](https://github.com/pypa/pip-audit),
Apache-2.0; it is not part of the server runtime or desktop shipped inventory.

## Audit and authority

The previous lock fails the actual new audit with 17 distinct advisory IDs:
`PYSEC-2026-3552`, `PYSEC-2026-3846`, `PYSEC-2026-3848`,
`PYSEC-2026-3849` and `PYSEC-2026-4140` through `PYSEC-2026-4152`.
The service reports the cryptography entry twice; duplicate rows are not separate
vulnerabilities. The updated lock passes all 40 core package versions with no
known findings or skips. A deliberately nonexistent package also fails strict
collection instead of yielding a clean audit.

The [repeatable gate](../../../../verification/audit-server-dependencies.py)
uses uv's PEP 751 export and compares its complete package/version set to the
core lock. All extras, development groups and platform-specific versions remain
in scope. Only the local `yap-server` virtual project is excluded. Unreviewed
sources, empty/incomplete exports and tool failures fail closed. The CI server
job runs this gate; no advisory is ignored.

Published advisories cover JWT parsing/claim checks, HTTP framing/multipart/
decompression and PKCS7 decryption. Not every advisory describes an exploitable
Yap path: production token decoding already uses fresh options, fixed RS256,
trusted keys and required issuer/audience/time claims. PyJWT 2.15.0's reviewed
`_merge_options` copies caller options before changing defaults. No claim checks
are disabled by the upgrade. Existing identity tests exercise valid signed
principals and refusal of malformed headers, signatures and claims.

## Verification

From the repository root:

```bash
source verification/cloud-env.sh
python verification/audit-server-dependencies.py
uv sync --project server --locked --exact --extra evaluation --extra test --no-python-downloads
uv run --project server --locked ruff check --config server/pyproject.toml server verification/audit-server-dependencies.py infra/yap-server-node/owned-process-supervisor.py
PYTHONPATH=server/src:server server/.venv/bin/python -m unittest discover -s server/tests/auth -v
verification/test-cloud-server.sh
```

The audit, frozen installation, Ruff, 53 authentication cases, 12 qualification
contracts and all four documentation contracts pass. The isolated portable
server suite passes 1,640 cases with 96 declared platform/database exclusions
(1,736 total). All 177 governed portable contracts and the 102-case real
Postgres/service/API regression pass with no skips. Hosted exact-head results
remain pending.
The first isolated attempts exhausted disk space; disposable native build caches
were cleared before retry. No source, dependency cache, model or user data was
removed to obtain space.

The first complete run exposed a test that compared historical model evidence
to today's dependency files. That test now verifies dependency bytes at the
receipt's original Git head, keeping the frozen evidence unchanged. A new
regression verifies that the production input guard admits matching original
bytes and rejects a changed lock. No historical receipt is rewritten or treated
as qualification for the upgraded environment. The required portable
qualification contract population increases from 176 to 177; no check is skipped.

Hosted run 535 passed the new complete audit, then failed the regression because
its shallow checkout contained the later baseline but lacked the original model
qualification tree. The existing CI history-fetch step now admits both exact
commits, including `0665c486398d2803ba33ebbb6e6dedddcd844dbd`. This retains the
original receipt boundary; final hosted checks are renewed on the updated head.

## Separate runtime findings

Auditing exact declared overlay pins without installing weights found no known
findings in ASR, ASR evaluation, LID or Tiron pins on this date. This is package
metadata evidence, not an image/SBOM or inference qualification.

The NeMo overlay remains unresolved:

| Affected pin | Advisory | Published fix or required review |
| --- | --- | --- |
| hydra-core 1.3.2 | PYSEC-2026-3850 | 1.3.4; trusted configuration remains required. |
| lightning 2.4.0 | PYSEC-2026-3972 | Advisory metadata lists no fixed version; review checkpoint-loading authority and current upstream releases. |
| lightning 2.4.0 / pytorch-lightning 2.6.5 | PYSEC-2026-3624 / PYSEC-2026-3967 (same GHSA-qqmf-gpg7-g8gw) | 2.6.6; verify NeMo compatibility and the locked runtime/license boundary before changing the overlay. |

These findings remain release inputs. The clean core gate does not clear them,
qualify a container base image or establish production security. Runtime repair
and software compatibility work remain in the single active project queue;
real model/ARM64 behavior and enterprise qualification retain their own evidence.

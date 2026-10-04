# Address connection-review export and source-check review

Owner: Grant McNatt. Date: 2026-10-04. PR: [#205](https://github.com/ZoOtMcNoOt/yap/pull/205).

Two review findings were reproduced before fixes. A saved native receipt with a
whitespace-only path resolved successfully instead of remaining unconfirmed.
An actual bounded OKF file with 2,000 nested YAML sequence levels made the source
checker CLI exit 1 with an uncaught recursion failure instead of its content-free
exit-2 refusal. Original regressions are retained in [receipt failure](original-receipt.txt)
and [CLI failure](original-cli.txt).

Saved-path validation now rejects whitespace-only paths while preserving real
path bytes. The checker CLI contains RecursionError in its existing redacted
refusal path. Tests retain failed-source bytes, require empty stdout, the generic
refusal and no traceback/private fixture payload. No publication, source mutation,
new dependency, inference or physical-platform claim is added. All 201 governed portable cases pass with no skips (11.718s), including the
actual nested-file CLI regression. All 404 frontend units pass with two declared
Windows-only skips; production build, server Ruff and Python formatting pass.
All 30 documentation/license/provenance/population/workflow checks pass with
zero skips (5.803s); final documentation/workflow checks renew after the status
update. Reviewed
six-job exact-head hosted integration remains pending; earlier runs cannot qualify
this corrected head.

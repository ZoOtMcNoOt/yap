// Hosted set: file-parsing and policy contracts. Each finishes well under a
// second, and these are the ones worth running on a clean checkout because they
// catch drift a developer machine hides.
//
// The behavioural contracts that spawn processes live in
// release-evidence-local.contract.mjs. They are 95% of this suite's wall clock,
// and their wall-clock assertions cannot hold on a hosted runner roughly ten
// times slower than the workstation, so they run locally before push instead.
// release-contract-coverage.contract.mjs proves every contract file belongs to
// exactly one of the two sets.
import "./release-contract/cache.contract.mjs";
import "./release-contract/dependency-license.contract.mjs";
import "./release-contract/model-provenance.contract.mjs";
import "./release-contract/provenance.contract.mjs";
import "./release-contract/release-contract-coverage.contract.mjs";
import "./release-contract/release-workflow.contract.mjs";
import "./release-contract/windows-build-tools-optional-diagnostics.contract.mjs";
import "./release-contract/windows-command-job-protocol.contract.mjs";
import "./release-contract/windows-command-powershell-runtime.contract.mjs";
import "./release-contract/windows-command-supervisor-watchdog.contract.mjs";
import "./release-contract/windows-installer.contract.mjs";
import "./release-contract/workflow.contract.mjs";

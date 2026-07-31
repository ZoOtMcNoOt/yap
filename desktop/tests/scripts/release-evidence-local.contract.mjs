// Local set: behavioural contracts that spawn real processes and assert on
// wall-clock behaviour. Measured on the Windows workstation these are 275 s of
// the suite's 289 s; on a hosted runner roughly ten times slower they exceed
// their own deadlines and fail while reporting correct containment, so a hosted
// run reports the runner's speed rather than the code's behaviour.
//
// Run before pushing:
//   pnpm test:release-contract:local
import "./release-contract/artifact.contract.mjs";
import "./release-contract/bounded-command-windows-job.contract.mjs";
import "./release-contract/github-hosted-checkout.contract.mjs";
import "./release-contract/hosted-windows-runtime-check.contract.mjs";
import "./release-contract/integrated-gate.contract.mjs";

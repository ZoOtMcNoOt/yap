import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";

const SHA40 = /^[0-9a-f]{40}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const REPOSITORY = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
const MAXIMUM_STATUS_PAGES = 11;

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function canonicalJson(value) {
  return `${JSON.stringify(value, Object.keys(value).sort())}\n`;
}

function command(executable, args, label, input = undefined) {
  const result = spawnSync(executable, args, {
    encoding: "utf8",
    input,
    maxBuffer: 1024 * 1024,
    windowsHide: true,
  });
  requireCondition(
    result.status === 0,
    `${label} failed: ${(result.stderr || result.stdout).trim()}`,
  );
  return result.stdout.trim();
}

function repositoryFromOrigin() {
  const origin = command("git", ["remote", "get-url", "origin"], "Git origin lookup");
  const match = origin.match(
    /^(?:git@github\.com:|https:\/\/github\.com\/)([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+?)(?:\.git)?$/,
  );
  requireCondition(match, "Gate admission requires a github.com origin.");
  return match[1];
}

function ghJson(args, label, input = undefined) {
  const output = command(
    "gh",
    ["api", "-H", "Accept: application/vnd.github+json", ...args],
    label,
    input,
  );
  try {
    return JSON.parse(output);
  } catch {
    throw new Error(`${label} returned invalid JSON.`);
  }
}

function defaultClient() {
  const repositoryFullName = repositoryFromOrigin();
  const repository = ghJson(
    [`repos/${repositoryFullName}`],
    "GitHub repository identity lookup",
  );
  requireCondition(
    Number.isSafeInteger(repository.id)
      && repository.full_name?.toLowerCase() === repositoryFullName.toLowerCase(),
    "GitHub repository identity is invalid.",
  );
  return {
    repositoryId: repository.id,
    repositoryFullName: repository.full_name,
    listStatuses(checkedHead) {
      const statuses = [];
      for (let page = 1; page <= MAXIMUM_STATUS_PAGES; page += 1) {
        const values = ghJson(
          [
            `repos/${repositoryFullName}/commits/${checkedHead}/statuses?per_page=100&page=${page}`,
          ],
          "GitHub gate-status lookup",
        );
        requireCondition(Array.isArray(values), "GitHub gate-status lookup is ambiguous.");
        statuses.push(...values);
        if (values.length < 100) return statuses;
      }
      throw new Error("GitHub gate-status history exceeded its bounded page limit.");
    },
    createStatus(checkedHead, body) {
      return ghJson(
        [
          "--method",
          "POST",
          `repos/${repositoryFullName}/statuses/${checkedHead}`,
          "--input",
          "-",
        ],
        "GitHub gate-status creation",
        JSON.stringify(body),
      );
    },
  };
}

function statusContext(gateId, manifestSha256) {
  return `yap/gate-admission/${gateId}/${manifestSha256.slice(0, 16)}`;
}

function description(claimSha256) {
  return `Yap one-attempt admission ${claimSha256}`;
}

function matchingStatuses(statuses, context) {
  requireCondition(Array.isArray(statuses), "GitHub gate-status history is invalid.");
  return statuses
    .filter((status) => status?.context?.toLowerCase() === context.toLowerCase())
    .sort((left, right) => left.id - right.id);
}

function statusAuthority(status, client, context, claimSha256) {
  requireCondition(
    Number.isSafeInteger(status?.id)
      && Number.isSafeInteger(status?.creator?.id)
      && typeof status?.creator?.login === "string"
      && status.state === "success"
      && status.context?.toLowerCase() === context.toLowerCase()
      && status.description === description(claimSha256)
      && Number.isFinite(Date.parse(status.created_at))
      && typeof status.url === "string",
    "GitHub gate-status identity is invalid.",
  );
  return Object.freeze({
    repositoryId: client.repositoryId,
    repositoryFullName: client.repositoryFullName,
    context: status.context.toLowerCase(),
    statusId: status.id,
    creatorId: status.creator.id,
    creatorLogin: status.creator.login,
    state: status.state,
    claimSha256,
    statusUrl: status.url,
    createdAt: status.created_at,
  });
}

export function buildGateAdmissionClaim({
  repositoryId,
  repositoryFullName,
  gateId,
  checkedHead,
  manifestSha256,
  evidenceRoot,
  reservedAt,
  nonce,
}) {
  requireCondition(Number.isSafeInteger(repositoryId), "Repository id is invalid.");
  requireCondition(REPOSITORY.test(repositoryFullName ?? ""), "Repository name is invalid.");
  requireCondition(typeof gateId === "string" && gateId.length > 0, "Gate id is invalid.");
  requireCondition(SHA40.test(checkedHead ?? ""), "Checked head is invalid.");
  requireCondition(SHA256.test(manifestSha256 ?? ""), "Manifest identity is invalid.");
  requireCondition(typeof evidenceRoot === "string" && evidenceRoot.length > 0,
    "Evidence root is invalid.");
  requireCondition(Number.isFinite(Date.parse(reservedAt)), "Reservation time is invalid.");
  requireCondition(SHA256.test(nonce ?? ""), "Reservation nonce is invalid.");
  return Object.freeze({
    schemaVersion: 1,
    repositoryId,
    repositoryFullName,
    gateId,
    checkedHead,
    manifestSha256,
    evidenceRoot,
    reservedAt,
    nonce,
  });
}

export function gateAdmissionClaimSha256(claim) {
  return sha256(canonicalJson(claim));
}

export function reserveGitHubGateAdmission({
  gateId,
  checkedHead,
  manifestSha256,
  evidenceRoot,
  reservedAt,
  nonce,
  client = defaultClient(),
}) {
  const context = statusContext(gateId, manifestSha256);
  requireCondition(
    matchingStatuses(client.listStatuses(checkedHead), context).length === 0,
    "This gate, head, and manifest already have a remote admission.",
  );
  const claim = buildGateAdmissionClaim({
    repositoryId: client.repositoryId,
    repositoryFullName: client.repositoryFullName,
    gateId,
    checkedHead,
    manifestSha256,
    evidenceRoot,
    reservedAt,
    nonce,
  });
  const claimSha256 = gateAdmissionClaimSha256(claim);
  const created = client.createStatus(checkedHead, {
    state: "success",
    context,
    description: description(claimSha256),
  });
  const matching = matchingStatuses(client.listStatuses(checkedHead), context);
  requireCondition(matching.length > 0, "GitHub did not retain the gate admission.");
  const winner = matching[0];
  requireCondition(
    winner.id === created.id,
    "A different GitHub gate admission won the reservation race.",
  );
  return Object.freeze({
    claim,
    statusAuthority: statusAuthority(winner, client, context, claimSha256),
  });
}

export function validateGitHubGateAdmission({
  claim,
  expectedStatusAuthority,
  client = defaultClient(),
}) {
  const claimSha256 = gateAdmissionClaimSha256(claim);
  const context = statusContext(claim.gateId, claim.manifestSha256);
  const matching = matchingStatuses(client.listStatuses(claim.checkedHead), context);
  requireCondition(matching.length > 0, "GitHub gate admission is missing.");
  const current = statusAuthority(matching[0], client, context, claimSha256);
  requireCondition(
    canonicalJson(current) === canonicalJson(expectedStatusAuthority),
    "GitHub gate admission no longer matches the admitted attempt.",
  );
  return current;
}

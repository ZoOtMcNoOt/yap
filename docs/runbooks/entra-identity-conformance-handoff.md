# Entra identity conformance handoff

## Purpose

This handoff separates Yap's developer-owned identity contract from the
Medtronic-controlled Entra, policy, and enterprise-conformance work. The local
OIDC harness proves standards-based signed-token validation, ownership,
authorization, and authenticated REST/WebSocket admission. It does not prove
Medtronic tenant policy, Microsoft Authentication Library (MSAL), Web Account
Manager (WAM), Conditional Access, consent, production registration, or
enterprise deployment approval.

Do not begin real-provider integration until:

1. the named enterprise owner supplies an approved non-production environment;
2. the values below are recorded without secrets in the approved configuration
   channel;
3. the user authorizes the real-provider conformance effort; and
4. security and privacy owners approve the evidence location and retention.

Tokens, credentials, employee identifiers, tenant-private values, and raw
diagnostics must remain outside Git, pull requests, hosted logs, and ordinary
application logs.

## Current executable baseline

The merged Phase 7 baseline implements only the application-owned side of this
handoff:

- `yap-server` uses a provider-neutral OIDC discovery/JWKS owner with bounded
  metadata, same-origin key discovery, rotation retention, and a fixed
  algorithm allow-list. The Entra profile adds the tenant, issuer, audience,
  delegated-scope, client, role, and `(tid, oid)` policy.
- The desktop exposes one narrow Rust-owned native access-token-provider
  interface. An inbox WAM adapter exists behind explicit
  `YAP_WAM_TOKEN_PROVIDER=1` opt-in, but no production provider is approved or
  selected and release/default operation fails closed. No MSAL.NET,
  system-browser adapter, or separately managed production credential cache is
  shipped.
- The SQLite development identity repository enforces access revocation and
  versioned purpose authorization and appends redacted, hash-chained audit
  events. It is not a production database or approved audit sink.
- Authenticated private live admission is executable and rechecks principal
  access without retaining a token. The current private runtime uses separate
  loopback listeners: REST on `127.0.0.1:18765` and WebSocket live admission on
  `127.0.0.1:18766`. Fixed-loopback HTTP health discovery exists, but no
  production same-origin HTTPS/WSS edge or managed/live endpoint discovery
  contract exists.
- The mock provider is pinned by version and manifest digest in
  [`verification/mock-oidc-provider.lock.json`](../../verification/mock-oidc-provider.lock.json).
  Focused executable fake-Docker lifecycle, workflow, and integrated-gate
  contracts retain their recorded evidence. They do not prove a real tenant or
  approved native sign-in provider.

Exact application-boundary head
`dc6359162fb16909d38f410cdb75c2729d83972f` passed its complete private
25-cell matrix and independent receipt validation. Its hosted CI exposed
checkout-test dependency timing, GitHub Windows temp-owner mismatch, and
equivalent 8.3/long-path spelling assumptions; CodeQL passed and stock NSIS was
not dispatched after CI failed. Reviewed portability repair
`558fed05e0f959a28fbe4d92499bbe185b0532d6` addresses those hosted assumptions
without changing identity policy or implementing any enterprise-controlled
input. Pre-admission descendant `c95cfe0...` then exposed a redundant
same-owner write under ordinary development-root ACLs before any attempt was
reserved. Repair `a823b28...` makes owner mutation conditional on an exact SID
mismatch and retains exact read-back verification. The descendant through
`c1d81fc...` changes only hosted/gate tooling, its contracts, and
documentation, so the validated `dc635916...` application/runtime matrix
remains authoritative. Phase 7 later merged as `66d314d7`; its adversarial
checkpoint and concrete follow-ups are closed, without relabeling PR #69's
final hosted head as all-green.

This developer-owned closure does not authorize or attempt real-provider,
enterprise-network, certificate, DNS, ZPA, firewall, policy, storage, audit, or
deployment work. Retain each such dependency as the named handoff below until
IT supplies the input and the user separately authorizes conformance.

## Required enterprise decisions and inputs

| Enterprise-controlled input | Required owner | Acceptance record | Conformance evidence |
|---|---|---|---|
| Approved non-production Entra tenant or isolated test environment | Entra platform owner | Environment name, classification, and approved test window | Yap connects only to the approved environment |
| Allowed-tenant policy | Identity architect | Exact allowed tenant set and rejection behavior | Allowed and disallowed tenant tests |
| Single-tenant or multi-tenant decision | Identity architect and security | Written topology decision | Issuer, tenant, guest, and ownership tests match the decision |
| Guest and B2B behavior | Identity architect and application owner | Permitted guest types and ownership rules | Guest admission, denial, offboarding, and cross-tenant isolation tests |
| Native/public-client app registration | Entra application administrator | Registration identifier and owner | Registration exists in the approved environment |
| Desktop client ID | Entra application administrator | Approved client identifier | Yap accepts only the approved client actor |
| Redirect URI | Entra application administrator and desktop owner | Exact registered URI and platform type | Authorization Code with PKCE returns only to the approved URI |
| System-browser configuration | Identity architect and desktop owner | Approved browser flow and fallback policy | Interactive sign-in, cancellation, denied consent, and recovery tests |
| Broker and WAM requirements | Endpoint engineering and identity architect | Required, optional, or prohibited decision with supported versions | WAM/broker behavior, account selection, sign-out, crash, and recovery tests |
| Separate Yap API registration | Entra application administrator | Resource registration identifier and owner | Yap API tokens are distinct from Microsoft Graph and ID tokens |
| API application ID URI | Entra application administrator | Exact approved URI | Token audience equals the approved Yap resource |
| Accepted access-token audience | API owner and security | Exact audience value and token-version expectation | Wrong, Graph, and unrelated-resource audiences fail closed |
| Delegated scopes | API owner and privacy | Exact scope names and purpose | Missing and insufficient scope tests |
| Application roles | API owner and security | Exact role names, assignment owners, and least-privilege rationale | Missing, insufficient, and unauthorized role tests |
| Client/application authorization policy | Security and API owner | Allowed native clients and service actors | Unauthorized client and application-only token tests |
| User and admin consent policy | Entra governance | Consent owner and approved workflow | Granted, denied, withdrawn, and admin-consent-required tests |
| Assignment requirements | Entra governance | Assignment-required decision and assignment owner | Assigned and unassigned user tests |
| Approved synthetic test users and groups | Entra test owner | Test identities and cleanup owner in the private evidence system | Same-tenant, cross-user, role, and group scenarios |
| Role and group mappings | Identity architect and application owner | Mapping table and change owner | Mapping changes take effect without changing durable `(tid, oid)` ownership |
| Conditional Access requirements | Security and Entra policy owner | Policies in scope and expected challenge behavior | Allowed, blocked, interaction-required, and policy-change tests |
| MFA behavior | Security and Entra policy owner | Required authentication strengths and exceptions | MFA success, cancellation, timeout, and denial tests |
| Device-compliance requirements | Endpoint security | Required device state and failure behavior | Compliant and non-compliant device tests |
| FIDO and Windows Hello expectations | Endpoint security and identity architect | Supported authenticators and fallback policy | Accepted, unavailable, cancelled, and recovery tests |
| Token-protection requirements | Security and endpoint engineering | Binding/protection policy and supported clients | Protected-token acquisition, refresh, and rejected-unbound-token tests |
| Token version and claims contract | Identity architect and API owner | Version, issuer shape, required claims, clock skew, and optional claims | Signature, issuer, `kid`, rotation, time, `tid`, `oid`, scope, and role matrix |
| Revocation and access-removal expectations | Identity governance and API owner | Required propagation target and operational owner | Application withdrawal, token/session expiry, reconnect, and offboarding tests |
| Permitted Microsoft Graph scopes, if any | Privacy, security, and Graph owner | Scope list, purpose, retention, and explicit approval | Graph tokens never authenticate to Yap; optional metadata stays purpose-bound |
| Identity-claim handling and retention | Privacy and records management | Allowed claims, purpose, retention, deletion, and presentation-snapshot rules | Base principal remains minimal; deletion and retention evidence |
| Security-approved logging | Security operations and privacy | Allowed fields, redaction rules, destination, access, and retention | Sentinel token never appears in logs, URLs, crashes, diagnostics, or frontend state |
| Test and production separation | Platform engineering and security | Separate registrations, secrets, policies, data, and evidence destinations | Cross-environment identifiers and tokens fail closed |
| Offboarding and deletion expectations | Identity governance, privacy, and operations | Trigger, owner, propagation, retention, and deletion SLA | Access withdrawal, purpose revocation, session termination, and deletion audit tests |

## Production adapter selection

The Phase 7 desktop keeps one narrow native access-token-provider interface and
fails closed when no approved adapter is installed. Do not select or ship a
production adapter solely to claim Entra support.

When the approved environment is available, compare the accepted native
Entra/MSAL direction, including official MSAL.NET/WAM where appropriate,
against:

- Microsoft support status and lifecycle;
- Tauri/native integration and process ownership;
- system-browser Authorization Code with PKCE;
- WAM, Windows account selection, FIDO, and Windows Hello requirements;
- Conditional Access, token protection, and device-compliance behavior;
- secure cache ownership and sign-out/revocation fencing;
- packaging, installer, crash, restart, and recovery behavior;
- dependency, provenance, legal, and patching burden;
- hand-written lines of code and long-term maintainability.

Record the selected adapter in a separately reviewed ADR amendment only after
the evidence exists.

## Real-provider conformance matrix

Run the following only in the approved environment and retain the results in
the approved private evidence destination:

- native Entra sign-in through system-browser Authorization Code with PKCE;
- silent acquisition, refresh single-flight, and interactive fallback;
- WAM/broker behavior when required;
- Conditional Access, MFA, device compliance, FIDO, and Windows Hello;
- Yap API token acquisition and Graph/Yap resource separation;
- real issuer, discovery, JWKS, signature, algorithm, `kid`, rotation,
  audience, tenant, client, token type, claim, scope, and role validation;
- authenticated REST and WebSocket admission parity;
- token expiry during requests and WebSocket sessions;
- reconnect, reauthentication, cancellation, replay, ordering, and teardown;
- sign-out fencing and application access withdrawal;
- denied consent, expired session, policy change, and guest behavior;
- cross-user and cross-tenant non-disclosure;
- desktop packaging and disposable-Windows install, repair, upgrade,
  uninstall, restart, and crash recovery.

## Completion record

Real-provider conformance remains incomplete until every required row has:

- a named enterprise owner;
- an accepted value or policy decision;
- a private evidence reference;
- a passing conformance test or an explicitly accepted exception; and
- approval from the responsible identity, security, privacy, endpoint, and
  application owners.

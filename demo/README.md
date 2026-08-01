# Demo identity

Two signed-in users, no Entra app registration, no IT dependency.

Phase 7 built tenant-scoped identity and nothing has exercised it as a product,
because signing in needs an app registration IT owns. The verification suite
already works around that with a synthetic OIDC provider and two fixed users,
but it is a one-shot assertion: it proves the flow and exits.

This runs the same provider, from the same digest-pinned image with the same
claims, and leaves it up. The tokens are real signed JWTs and the server
validates them through its ordinary Entra path, so what a demo exercises is the
shipping authentication boundary rather than a mock of one.

## The two users

| | object id ends | roles |
| --- | --- | --- |
| **alice** | `...0072` | `Yap.IdentityAdministrator` |
| **bob** | `...0073` | none |

Same tenant, different subjects, different roles. That is the point: owner
scoping and role gating are visible rather than theoretical, and Bob is the one
who shows you what a non-administrator actually sees.

## Running it

```bash
./demo/run-demo-identity-provider.py serve            # start, prints server env
./demo/run-demo-identity-provider.py token --identity alice
./demo/run-demo-identity-provider.py token --identity bob
./demo/run-demo-identity-provider.py stop
```

`serve` prints the environment for the server. Start `yap-server` with it and
the server will accept these tokens and nothing else.

Call the API directly with a minted token:

```bash
TOKEN=$(./demo/run-demo-identity-provider.py token --identity alice)
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:18765/v1/...
```

## Verified

Both identities were minted and validated through the server's own
`OidcAccessTokenAuthenticator` — JWKS discovery, signature, issuer, audience,
tenant allowlist, client allowlist, required scope, and role mapping:

```
alice:  VALIDATED tenant=0071 subject=0072 roles=['Yap.IdentityAdministrator']
bob:    VALIDATED tenant=0071 subject=0073 roles=[]
```

## Boundaries

Loopback only, and the container is removed on `stop`. A demo identity provider
reachable from a routable interface is a token oracle for anyone who can reach
it, so the publish is pinned to `127.0.0.1`.

The image is digest-pinned from `verification/mock-oidc-provider.lock.json`,
the same reference CI uses; there is no second thing to keep current.

`YAP_OIDC_ALLOW_INSECURE_LOOPBACK=1` appears in the printed environment because
the issuer is plain HTTP on loopback. That belongs to a demo and must not reach
a deployment.

Docker is required. The provider image has a `linux/arm64` manifest, so the
natural home is the GB10 server node beside `yap-server`, with the desktop
client reaching it over the existing forward.

## What this does not do yet

The desktop client cannot use these tokens. Its provider seam now has a WAM
adapter (#103) that talks to the Windows broker, which knows nothing about a
synthetic issuer. Driving the client as Alice needs a demo adapter behind the
same seam, compiled out of release builds. Until then this exercises the server
and the API, which is where the identity boundary lives.

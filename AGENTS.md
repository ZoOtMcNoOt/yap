# Agents.md
- Do not preserve backwards compatibility. Remove obsolete paths instead of adding compatibility layers, fallbacks, or migrations.
- Choose the simplest implementation that fully meets the current requirements. Avoid speculative abstractions, configurations, and indirection.
- Grow the system in layers. Start from the smallest version that works end to end, and add each new capability on top of a product that already works. Never trade a working product for unfinished complexity.
- Keep components modular and concerns clearly separated.
- Prefer established, well-maintained libraries when they reduce overall complexity or improve reliability. Do not re-implement common functionality without a clear reason.
- Lean on the dependencies already in the project before writing your own implementation or adding packages. Do not assume that a library lacks capability without checking its documentation and types.
- Make architectural decisions for the long term. Do not accept a stopgap that only works for now and is meant to be replaced later.

## Project constraints

- The organization-owned private server is the canonical team route. Supported local/offline operation is a current product requirement, not a backwards-compatibility fallback.
- Use organization identity; never create Yap-native credentials or silently connect, route audio, or acquire credentials. Remote failures must not disable local controls.
- Treat IT-controlled identity, networking, certificates, policy, and deployment as explicit handoffs.
- Executable behavior is truth; ADRs describe intent. Keep changes phase-scoped, use functional names, and merge only a reviewed green exact head.
- Verify licenses and preserve provenance when reusing external code.

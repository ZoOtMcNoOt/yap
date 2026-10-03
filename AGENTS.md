# AGENTS.md

- Do not preserve backwards compatibility unless explicitly required by current requirements. Remove obsolete paths instead of adding compatibility layers or silent fallbacks. Distinguish obsolete code from user data; preserve data through necessary transitions.
- Choose the simplest maintainable implementation that fully meets the current requirements. Avoid speculative abstractions, configurations, and indirection.
- Grow the system in working, end-to-end increments. Start from the smallest version that satisfies a meaningful use case, verify it, and add capabilities on top of a working foundation. Never trade a working product for unfinished complexity.
- Keep components modular and concerns clearly separated. Give each component a cohesive responsibility and clear interfaces; avoid splitting components without a concrete benefit.
- Prefer established, well-maintained libraries when they reduce total complexity or improve reliability, accounting for integration, maintenance, and operational costs. Do not re-implement common functionality without a clear reason.
- Lean on dependencies already in the project before writing your own implementation or adding packages. Check the installed version’s documentation, types where available, and existing usage before concluding that a capability is missing.
- Make architectural decisions for the long term without building speculative capabilities. Choose incremental implementations that can grow within a sound design; avoid stopgaps whose success depends on replacing them later.

## Project constraints

- The organization-owned private server is the canonical team route. Supported local/offline operation is a current product requirement, not a backwards-compatibility fallback.
- Use organization identity; never create Yap-native credentials or silently connect, route audio, or acquire credentials. Remote failures must not disable local controls.
- Treat IT-controlled identity, networking, certificates, policy, and deployment as explicit handoffs.
- Executable behavior is truth; ADRs describe intent. Keep changes phase-scoped, use functional names, and merge only a reviewed green exact head.
- Verify licenses and preserve provenance when reusing external code.

## Current development priority

- Use `docs/plans/active/2026-10-02-yap-project-hill-climb.md` as the single execution queue. Continue across the entire approved roadmap in verified end-to-end increments. Completing a milestone or encountering a hardware blocker does not complete the project goal; select the next available software task.
- Use pnpm 11.7.0 and the locked dependencies. The cloud setup and verification commands are in `docs/runbooks/cloud-development.md`.
- Real-model and enterprise qualification gate production promotion; they do not block UI, documentation, refactoring, or hardware-free tests. Report simulated, Linux-native, Windows-native, and inference results accurately.
- Attribute project work to Grant McNatt. Do not add AI coauthor trailers or generated-by branding; preserve third-party attribution and provenance.
- Commit and push each verified development iteration to GitHub. Keep `main` as the shared integration branch; merge through required checks, then remove completed temporary branches. Preserve unique historical work before retiring branches.

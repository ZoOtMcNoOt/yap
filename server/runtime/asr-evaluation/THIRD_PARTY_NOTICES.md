# Yap ASR evaluation overlay notices

This private, non-production evaluation overlay adds only the following pinned
packages to the locked Yap ASR worker image:

- RapidFuzz 3.14.5 — MIT License
- regex 2026.7.10 — Apache License 2.0 and CNRI Python License

Exact Linux ARM64 wheel hashes are frozen in `requirements.lock`. The complete
worker-image and model notices remain in the parent image. These packages are
not part of the desktop application or serving hot path.

# Agent vLLM evaluation runtime notices

This evaluation-only image is based on NVIDIA's digest-pinned ARM64 vLLM
26.07 container. Use of the NVIDIA base remains governed by NVIDIA's
applicable software and product-specific terms.

The base image carries XGrammar 0.2.0, while its bundled vLLM 0.24 tool parser
imports `normalize_tool_choice`, first exposed by XGrammar 0.2.1. Yap overlays
only the exact XGrammar 0.2.1 CPython 3.12 ARM64 wheel published by the MLC
team. The Dockerfile verifies the wheel SHA-256 before use and checks the
installed distribution and required API during the build.

- Project: https://github.com/mlc-ai/xgrammar
- Source revision: `5b4e9ce9e72524037ae24ecd831b9b6604d2eb48`
- Distribution: `xgrammar==0.2.1`
- License: Apache-2.0
- Wheel SHA-256: `9e8dd9853958a263b4015ce79133a0ff4eaa9d22ef781fb2350c7dfc40c2c012`

The published wheel contains its own `LICENSE` and `NOTICE` files. No
XGrammar source is copied into this repository.

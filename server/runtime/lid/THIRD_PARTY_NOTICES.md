# Yap isolated language-identification runtime notices

This CPU-only image is an assistive batch-language preflight. It does not
select an ASR route without user confirmation. The complete, hash-locked Python
distribution inventory is `runtime/lid/requirements.lock`; wheel-provided
license and metadata files remain installed in the image.

## Direct runtime dependencies

- **SpeechBrain 1.1.0** — Apache-2.0. Source:
  <https://github.com/speechbrain/speechbrain/tree/v1.1.0>.
- **PyTorch 2.11.0+cpu** — BSD-3-Clause. Source:
  <https://github.com/pytorch/pytorch/tree/v2.11.0>.
- **TorchAudio 2.11.0+cpu** — BSD-2-Clause. Source:
  <https://github.com/pytorch/audio/tree/v2.11.0>.

The standard Apache License 2.0 text is shipped at
`licenses/APACHE-2.0.txt`. PyTorch and TorchAudio license texts and attribution
material are preserved in their installed wheel metadata.

## Language-identification model

- Model: `speechbrain/lang-id-voxlingua107-ecapa`
- Immutable revision: `0253049ae131d6a4be1c4f0d8b0ff483a0f8c8e9`
- License: Apache-2.0
- Source:
  <https://huggingface.co/speechbrain/lang-id-voxlingua107-ecapa/tree/0253049ae131d6a4be1c4f0d8b0ff483a0f8c8e9>

The model weights are not embedded in this image or fetched at runtime. Four
required artifacts are staged separately, then checked by exact byte size and
SHA-256 against `lid-component.lock.json` before the classifier loads.

## Transitive dependencies

The image includes the exact transitive distributions selected for Python 3.12
on Linux ARM64. Their versions, distribution sources, and accepted wheel hashes
are recorded in `runtime/lid/requirements.lock`. Their upstream licenses include
Apache-2.0, BSD-family, ISC, MIT, MPL-2.0, and Python-family terms. Package
license files and metadata installed from the locked wheels are part of the
runtime image and must not be removed during image minimization.

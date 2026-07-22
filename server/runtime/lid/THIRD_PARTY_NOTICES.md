# Yap isolated language-identification runtime notices

This CPU-only image is an assistive batch-language preflight. It does not
select an ASR route without user confirmation. The complete, hash-locked Python
distribution inventory is `runtime/lid/requirements.lock`; wheel-provided
license and metadata files remain installed in the image.

## Direct runtime dependencies

- **NumPy 2.4.6** — BSD-3-Clause. Source:
  <https://github.com/numpy/numpy/tree/v2.4.6>.
- **ONNX Runtime 1.27.0** — MIT. Source:
  <https://github.com/microsoft/onnxruntime/tree/v1.27.0>.

The installed wheel metadata retains the applicable license texts and
attribution material.

## Language-identification model

- Model: `nvidia/nemo/langid_ambernet`
- Release: `1.12.0`
- Source:
  <https://catalog.ngc.nvidia.com/orgs/nvidia/teams/nemo/models/langid_ambernet>
- Terms: NVIDIA NGC Terms of Use

The model is not embedded in the image or fetched by the application.
Redistribution approval is not granted. An operator must explicitly import the exact INT8 QDQ ONNX
artifact, after which Yap checks its byte size and SHA-256 against
`lid-component.lock.json` before loading it. Importing the artifact remains
subject to NVIDIA's applicable NGC terms.

## Transitive dependencies

The image includes the exact transitive distributions selected for Python 3.12
on Linux ARM64. Their versions, distribution sources, and accepted wheel hashes
are recorded in `runtime/lid/requirements.lock`. Package license files and
metadata installed from the locked wheels are part of the runtime image and
must not be removed during image minimization.

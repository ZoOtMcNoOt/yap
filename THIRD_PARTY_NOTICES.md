# Third-Party Notices

## Shipped desktop dependency inventory

`SHIPPED_DEPENDENCY_INVENTORY.json` is generated from the exact production
pnpm graph and the normal-dependency Rust graph for
`x86_64-pc-windows-msvc`. It is bundled beside this notice. The release
contract rejects a stale inventory, a dependency without license metadata, or
an unreviewed license term.

The current graph maps to these license families and reviewed terms:
`0BSD`, `Apache-2.0`, `BSD-2-Clause`, `BSD-3-Clause`, `CC0-1.0`,
`CDLA-Permissive-2.0`, `ISC`, `LGPL-2.1-or-later`, `LLVM-exception`, `MIT`,
`MIT-0`, `MPL-2.0`, `Unicode-3.0`, `Unlicense`, and `Zlib`.
The `GSAP-Standard` disposition refers to the GSAP standard no-charge license
published at https://gsap.com/standard-license/. The inventory preserves each
package's exact declared license expression rather than collapsing alternatives.

This dependency inventory is separate from direct source-adaptation provenance
in `THIRD_PARTY_PROVENANCE.json`. Package-manager metadata does not authorize
copying source into Yap, and a new license term fails closed pending review.

## Silero VAD v4 model

Yap can explicitly download or import a hash-pinned k2-fsa ONNX export of
Silero VAD v4 for advisory client-side voice-activity detection. The model is
not bundled with Yap and is never downloaded by startup, preprocessing, retry,
or reconnect behavior.

- Model source: https://github.com/snakers4/silero-vad
- Model revision: `915dd3d639b8333a52e001af095f87c5b7f1e0ac` (`v4.0`)
- Export source: https://github.com/k2-fsa/sherpa-onnx/blob/8e51a975508fd69d3eed53d5098862201889fafd/scripts/silero_vad/v4/export-onnx.py
- Distributed artifact: https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx
- License: MIT

MIT License

Copyright (c) 2020-present Silero Team

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## NVIDIA AmberNet 1.12.0 language detector

Yap can explicitly import one hash-pinned INT8 QDQ ONNX conversion of NVIDIA
AmberNet 1.12.0 for offline acoustic language identification. No AmberNet
model bytes are bundled or hosted by Yap, and startup and capture never
download them. Import verifies the selected file's exact length and SHA-256
before it becomes available to the application.

- Model catalog: https://catalog.ngc.nvidia.com/orgs/nvidia/nemo/models/langid_ambernet/-
- Model revision: `1.12.0`
- NVIDIA AI Product Terms: https://www.nvidia.com/en-us/agreements/enterprise-software/product-specific-terms-for-ai-products/
- NVIDIA Software License Agreement: https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-software-license-agreement/

Redistribution of the derived ONNX remains disabled pending organizational
review of the applicable NVIDIA terms. The immutable upstream and converted
artifact identities, conversion provenance, and unresolved reproducibility
gaps are recorded in `desktop/model-artifacts.lock.json`.

This software contains source code provided by NVIDIA Corporation.

The conversion calibration process used Google FLEURS revision
`70bb2e84b976b7e960aa89f1c648e09c59f894dd` under CC BY 4.0. Yap does not
distribute FLEURS audio or transcripts. Dataset source:
https://huggingface.co/datasets/google/fleurs. License:
https://creativecommons.org/licenses/by/4.0/.

## sherpa-onnx

Yap uses `sherpa-onnx` 1.13.4 for its in-process Nemotron ASR and Silero VAD.
The same pinned Windows native archive supplies the single statically linked
ONNX Runtime used by the AmberNet detector. The exact source revision and
archive are recorded in `desktop/model-artifacts.lock.json`.

- Repository: https://github.com/k2-fsa/sherpa-onnx
- Revision: `142807252687d81b40d6315f23470a1512a00de3` (`v1.13.4`)
- License: Apache License 2.0
- Shipped license text: `licenses/APACHE-2.0.txt`

The sherpa-onnx native archive also contains ONNX Runtime. ONNX Runtime is
licensed under the MIT License. Its upstream third-party notices are at
https://github.com/microsoft/onnxruntime/blob/main/ThirdPartyNotices.txt.

MIT License

Copyright (c) Microsoft Corporation

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Rust ONNX and FFT bindings

The AmberNet client runtime uses `ort` and `ort-sys` 2.0.0-rc.12 under
MIT OR Apache-2.0, `realfft` 3.5.0 under MIT, and `rustfft` 6.4.1 under
MIT OR Apache-2.0. Package versions are frozen in
`desktop/src-tauri/Cargo.lock`.

- ort: https://github.com/pykeio/ort
- realfft: https://github.com/HEnquist/realfft
- rustfft: https://github.com/ejmahler/RustFFT

## FreeFlow (zachlatta/freeflow)

Portions of the live dictation overlay and audio level normalization are adapted
from FreeFlow:

- Repository: https://github.com/zachlatta/freeflow
- Copyright (c) 2026 Zach Latta
- License: MIT

MIT License

Copyright (c) 2026 Zach Latta

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## TorchAudio Mel filter-bank compatibility function

The Cohere vLLM runtime includes a narrow implementation of
`melscale_fbanks`, adapted from TorchAudio v2.11.0. It exists only because the
digest-pinned NVIDIA vLLM 26.06 image imports that function for Cohere ASR while
omitting the TorchAudio package. Yap does not include a general TorchAudio
package.

- Repository: https://github.com/pytorch/audio
- Revision: `34c52a67e8941bbd8e6adaca0eb0b9eabec11d78` (`v2.11.0`)
- Upstream file: `src/torchaudio/functional/functional.py`
- License: BSD-2-Clause

BSD 2-Clause License

Copyright (c) 2017 Facebook Inc. (Soumith Chintala),
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

## rusqlite and libsqlite3-sys

This software includes rusqlite 0.40.1 and libsqlite3-sys 0.38.1:

- Repository: https://github.com/rusqlite/rusqlite
- Copyright (c) 2014 The rusqlite developers
- License: MIT

MIT License

Copyright (c) 2014 The rusqlite developers

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## SQLite

The bundled build includes SQLite 3.53.2. SQLite is in the public domain. See
SQLite's public-domain dedication at https://www.sqlite.org/copyright.html.

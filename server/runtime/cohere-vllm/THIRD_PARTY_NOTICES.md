# Cohere vLLM runtime notices

The runtime is based on NVIDIA's digest-pinned vLLM 26.06 container and serves
the Apache-2.0 Cohere Transcribe model identified in
`server/cohere-vllm-serving.lock.json`. NVIDIA container use remains governed
by NVIDIA's applicable software and product-specific terms.

The pinned NVIDIA image omits the TorchAudio package while vLLM 0.22.1 imports
`torchaudio.functional.melscale_fbanks` for Cohere ASR. Yap includes only a
narrow, source-attributed implementation of that function, adapted from
TorchAudio v2.11.0 under BSD-2-Clause. It is not a general TorchAudio package.
The license text is included at `licenses/TORCHAUDIO-BSD-2-Clause.txt`.

The pinned NVIDIA image also predates PyTorch upstream commit
`c5f8ebc91a8727a9056734f73329c217328b8989`, which fixes an uncached custom-op
lookup from a weak-reference finalizer after the C++ runtime has begun
interpreter shutdown. Yap applies that exact one-line behavioral backport at
image build time and fails closed if the digest-pinned source differs. The
upstream commit and PyTorch source are BSD-3-Clause; the license text is included
at `licenses/PYTORCH-BSD-3-Clause.txt`.

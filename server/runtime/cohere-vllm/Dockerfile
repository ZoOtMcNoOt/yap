FROM nvcr.io/nvidia/vllm@sha256:bebcf9576b1720214319ee5c7ee4f7661954cbbf59ed3fcd188cd79a67f1967e

ARG YAP_CHECKED_HEAD
LABEL org.opencontainers.image.title="Yap Cohere vLLM serving runtime" \
      org.opencontainers.image.source="https://github.com/mcnatg1/yap" \
      org.opencontainers.image.revision="${YAP_CHECKED_HEAD}" \
      org.opencontainers.image.licenses="LicenseRef-NVIDIA-AI AND Apache-2.0 AND BSD-2-Clause AND BSD-3-Clause"

ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    DO_NOT_TRACK=1 \
    HOME=/tmp/yap-vllm \
    HF_HOME=/tmp/huggingface \
    XDG_CACHE_HOME=/tmp/cache \
    TORCH_HOME=/tmp/torch \
    TMPDIR=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/yap-vllm-compatibility \
    VLLM_MAX_AUDIO_CLIP_FILESIZE_MB=512

COPY runtime/cohere-vllm/compatibility /opt/yap-vllm-compatibility
COPY runtime/cohere-vllm/licenses /opt/yap-vllm-licenses
COPY runtime/cohere-vllm/THIRD_PARTY_NOTICES.md /opt/yap-vllm-THIRD_PARTY_NOTICES.md

RUN python3 /opt/yap-vllm-compatibility/patch_pytorch_library_finalizer.py \
    && chmod -R a+rX \
      /opt/yap-vllm-compatibility \
      /opt/yap-vllm-licenses \
      /opt/yap-vllm-THIRD_PARTY_NOTICES.md \
    && test -n "${YAP_CHECKED_HEAD}" \
    && python3 -c 'import importlib.metadata as m, pathlib, sys, torch, torch.library; module = pathlib.Path(m.distribution("vllm").locate_file("vllm/model_executor/models/cohere_asr.py")); source = module.read_text(encoding="utf-8"); torch_library_source = pathlib.Path(torch.library.__file__).read_text(encoding="utf-8"); assert "class CohereAsrForConditionalGeneration" in source; assert "if name not in vars(namespace):" in torch_library_source; assert "if not hasattr(namespace, name):" not in torch_library_source; from torchaudio.functional import melscale_fbanks; assert callable(melscale_fbanks); assert sys.version_info[:2] == (3, 12); assert torch.__version__ == "2.13.0a0+8145d630e8.nv26.06"; assert torch.version.cuda == "13.3"; assert m.version("vllm") == "0.22.1+7b9cb5b7.nv26.6.55915567"; assert m.version("transformers") == "5.6.0"; assert m.version("librosa") == "0.11.0"; assert m.version("soundfile") == "0.14.0"; assert m.version("soxr") == "1.1.0"; assert m.version("numpy") == "2.1.0"' \
    && groupadd --gid 10001 yapvllm \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin yapvllm

USER 10001:10001
ENTRYPOINT ["vllm", "serve"]
CMD ["/models/asr", "--served-model-name", "CohereLabs/cohere-transcribe-03-2026", "--host", "0.0.0.0", "--port", "8000", "--dtype", "bfloat16", "--kv-cache-memory-bytes", "1073741824", "--max-num-seqs", "8", "--disable-fastapi-docs", "--uvicorn-log-level", "warning"]

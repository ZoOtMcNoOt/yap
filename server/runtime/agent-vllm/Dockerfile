# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e
FROM nvcr.io/nvidia/vllm@sha256:1de8e6bfdb4c81c1f31a806cc9b13b5c6352714a7cec87f4d24964bcc91159b2 AS xgrammar-overlay

ARG SOURCE_DATE_EPOCH=0

ADD --checksum=sha256:9e8dd9853958a263b4015ce79133a0ff4eaa9d22ef781fb2350c7dfc40c2c012 \
    https://files.pythonhosted.org/packages/44/60/7c6194b66e043f36a7fbdbf7e6e0e4c94b151f7e53ad1b197f53e711f5d1/xgrammar-0.2.1-cp312-cp312-manylinux_2_26_aarch64.manylinux_2_28_aarch64.whl \
    /tmp/xgrammar-0.2.1-cp312-cp312-manylinux_2_26_aarch64.manylinux_2_28_aarch64.whl

RUN python -m pip install --no-deps --no-cache-dir --no-compile \
      --target /opt/yap-xgrammar \
      /tmp/xgrammar-0.2.1-cp312-cp312-manylinux_2_26_aarch64.manylinux_2_28_aarch64.whl

FROM nvcr.io/nvidia/vllm@sha256:1de8e6bfdb4c81c1f31a806cc9b13b5c6352714a7cec87f4d24964bcc91159b2

ARG SOURCE_DATE_EPOCH=0

LABEL org.opencontainers.image.title="Yap Qwen agent vLLM evaluation runtime" \
      org.opencontainers.image.source="https://github.com/mcnatg1/yap" \
      org.opencontainers.image.revision="5b4e9ce9e72524037ae24ecd831b9b6604d2eb48" \
      org.opencontainers.image.licenses="LicenseRef-NVIDIA-AI AND Apache-2.0" \
      io.yap.base-manifest-digest="sha256:1de8e6bfdb4c81c1f31a806cc9b13b5c6352714a7cec87f4d24964bcc91159b2" \
      io.yap.runtime="agent-vllm" \
      io.yap.xgrammar-version="0.2.1" \
      io.yap.xgrammar-wheel-sha256="9e8dd9853958a263b4015ce79133a0ff4eaa9d22ef781fb2350c7dfc40c2c012"

COPY --chmod=0644 runtime/agent-vllm/THIRD_PARTY_NOTICES.md /opt/yap-agent-vllm-THIRD_PARTY_NOTICES.md
COPY --from=xgrammar-overlay /opt/yap-xgrammar /opt/yap-xgrammar

ENV PYTHONPATH=/opt/yap-xgrammar

RUN PYTHONDONTWRITEBYTECODE=1 python -c 'import importlib.metadata as m; files = tuple(str(path) for path in m.distribution("xgrammar").files); from xgrammar import normalize_tool_choice; assert m.version("xgrammar") == "0.2.1"; assert "xgrammar-0.2.1.dist-info/licenses/LICENSE" in files; assert "xgrammar-0.2.1.dist-info/licenses/NOTICE" in files; assert callable(normalize_tool_choice); assert m.version("vllm") == "0.24.0+092c4842.nv26.7.59534043"'

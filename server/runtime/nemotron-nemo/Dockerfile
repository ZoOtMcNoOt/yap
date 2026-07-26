ARG BASE_IMAGE=nvcr.io/nvidia/pytorch@sha256:dcae8df08ef61b019b8eb109113428cba4ef0e37484c6e722406150dd5ada759
ARG NEMO_REVISION=ba2cd63ef8de8a3183a3c02b310c66d616b9a991

FROM ${BASE_IMAGE} AS application-source

COPY src/yap_server /tmp/yap-application-source/yap_server
RUN rm -rf /tmp/yap-application-source/yap_server/evaluation

FROM ${BASE_IMAGE} AS nemo-wheel-builder
ARG NEMO_REVISION

RUN git init /tmp/nemo-source
RUN git -C /tmp/nemo-source fetch --depth 1 \
      https://github.com/NVIDIA/NeMo.git "${NEMO_REVISION}" \
    && git -C /tmp/nemo-source switch --detach FETCH_HEAD \
    && test "$(git -C /tmp/nemo-source rev-parse HEAD)" = "${NEMO_REVISION}" \
    && git -C /tmp/nemo-source config core.abbrev 9
RUN python3 -m pip wheel \
      --disable-pip-version-check \
      --no-deps \
      --no-build-isolation \
      --wheel-dir /tmp/nemo-wheel \
      /tmp/nemo-source \
    && test -f \
      /tmp/nemo-wheel/nemo_toolkit-3.1.0+ba2cd63ef-py3-none-any.whl

FROM ${BASE_IMAGE}
ARG NEMO_REVISION

LABEL org.opencontainers.image.title="Yap native NeMo Nemotron runtime" \
      org.opencontainers.image.source="https://github.com/mcnatg1/yap" \
      org.opencontainers.image.licenses="LicenseRef-NVIDIA-AI AND OpenMDW-1.1 AND Apache-2.0 AND BSD-2-Clause AND BSD-3-Clause AND ISC AND LGPL-2.1-or-later AND MIT AND Artistic-1.0" \
      io.yap.nemo.revision="${NEMO_REVISION}"

ENV PYTHONPATH=/opt/yap-server \
    YAP_MODEL_LOCK=/opt/yap-server/model-locks/nemotron-batch.json \
    YAP_NEMOTRON_STREAMING_CONFIG=/opt/yap-server/config/nemotron-cache-aware-streaming.yaml \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    DO_NOT_TRACK=1 \
    HOME=/tmp/yap-worker \
    HF_HOME=/tmp/huggingface \
    XDG_CACHE_HOME=/tmp/cache \
    TORCH_HOME=/tmp/torch \
    TRITON_CACHE_DIR=/tmp/torch-kernel-cache \
    TMPDIR=/tmp \
    OMP_NUM_THREADS=8 \
    MKL_NUM_THREADS=8 \
    OPENBLAS_NUM_THREADS=8 \
    NUMEXPR_NUM_THREADS=8 \
    RAYON_NUM_THREADS=8 \
    TOKENIZERS_PARALLELISM=false \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/yap-server

COPY runtime/nemotron-nemo/requirements.lock /tmp/yap-nemo-requirements.lock
COPY --from=nemo-wheel-builder \
  /tmp/nemo-wheel/nemo_toolkit-3.1.0+ba2cd63ef-py3-none-any.whl \
  /tmp/nemo_toolkit-3.1.0+ba2cd63ef-py3-none-any.whl
RUN set -eu; \
    python3 -m pip install \
      --disable-pip-version-check \
      --no-cache-dir \
      --no-deps \
      --require-hashes \
      --requirement /tmp/yap-nemo-requirements.lock; \
    python3 -m pip install \
      --disable-pip-version-check \
      --no-cache-dir \
      --no-deps \
      /tmp/nemo_toolkit-3.1.0+ba2cd63ef-py3-none-any.whl; \
    check_status=0; \
    check_output="$(python3 -m pip check 2>&1)" || check_status=$?; \
    test "$check_status" -eq 1; \
    test "$check_output" = "triton-kernels 1.0.0+gitb7fa781f.nv26.6 requires pytest, which is not installed."; \
    rm -f \
      /tmp/yap-nemo-requirements.lock \
      /tmp/nemo_toolkit-3.1.0+ba2cd63ef-py3-none-any.whl

ARG YAP_CHECKED_HEAD
LABEL org.opencontainers.image.revision="${YAP_CHECKED_HEAD}" \
      com.mcnatg1.yap.base-platform-digest="sha256:dcae8df08ef61b019b8eb109113428cba4ef0e37484c6e722406150dd5ada759" \
      com.mcnatg1.yap.runtime="nemotron-nemo"

COPY nemotron-nemo-serving.lock.json /opt/yap-server/model-locks/nemotron-batch.json
COPY runtime/nemotron-nemo/cache-aware-streaming.yaml \
  /opt/yap-server/config/nemotron-cache-aware-streaming.yaml
COPY runtime/nemotron-nemo/THIRD_PARTY_NOTICES.md /opt/yap-server/THIRD_PARTY_NOTICES.md
COPY runtime/asr/licenses/NEMOTRON_OPENMDW-1.1.txt \
  /opt/yap-server/licenses/NEMOTRON_OPENMDW-1.1.txt
COPY runtime/asr/licenses/APACHE-2.0.txt \
  /opt/yap-server/licenses/APACHE-2.0.txt
COPY --from=application-source /tmp/yap-application-source/yap_server /opt/yap-server/yap_server

RUN test ! -e /opt/yap-server/yap_server/evaluation \
    && chmod -R a+rX /opt/yap-server
RUN python3 -c 'import importlib.metadata as m, json, sys; import nemo.collections.asr; import torch; lock = json.load(open("/opt/yap-server/model-locks/nemotron-batch.json", encoding="utf-8")); expected = lock["runtime"]["overlayPackages"]; actual = {name: m.version(name) for name in expected}; assert actual == expected, (actual, expected); assert sys.version_info[:2] == (3, 12); assert torch.__version__ == "2.13.0a0+8145d630e8.nv26.06"; assert torch.version.cuda == "13.3"; assert m.version("nemo_toolkit") == "3.1.0+ba2cd63ef"' \
    && groupadd --gid 10001 yapworker \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin yapworker

USER 10001:10001
ENTRYPOINT ["python3", "-m", "yap_server.pools.batch_asr_worker"]

ARG BASE_IMAGE=nvcr.io/nvidia/pytorch@sha256:dcae8df08ef61b019b8eb109113428cba4ef0e37484c6e722406150dd5ada759
ARG TIRON_REVISION=d249c5a81fc6e0f1ecd34fd30cf2519f06fe671c
ARG TORCHAUDIO_REVISION=34c52a67e8941bbd8e6adaca0eb0b9eabec11d78

FROM ${BASE_IMAGE} AS application-source

COPY src/yap_server /tmp/yap-application-source/yap_server
RUN rm -rf /tmp/yap-application-source/yap_server/evaluation \
    && test ! -e /tmp/yap-application-source/yap_server/evaluation

FROM ${BASE_IMAGE} AS torchaudio-wheel-builder
ARG TORCHAUDIO_REVISION

RUN git init /tmp/torchaudio-source
RUN git -C /tmp/torchaudio-source fetch --depth 1 \
      https://github.com/pytorch/audio.git "${TORCHAUDIO_REVISION}" \
    && git -C /tmp/torchaudio-source switch --detach FETCH_HEAD \
    && test "$(git -C /tmp/torchaudio-source rev-parse HEAD)" = \
      "${TORCHAUDIO_REVISION}"
RUN BUILD_RNNT=0 BUILD_SOX=0 USE_CUDA=0 \
    python3 -m pip wheel \
      --disable-pip-version-check \
      --no-deps \
      --no-build-isolation \
      --wheel-dir /tmp/torchaudio-wheel \
      /tmp/torchaudio-source \
    && test "$(find /tmp/torchaudio-wheel -maxdepth 1 -type f -name 'torchaudio-*.whl' | wc -l)" -eq 1

FROM ${BASE_IMAGE} AS tiron-source
ARG TIRON_REVISION

COPY meeting-transcription-runtime.lock.json /tmp/meeting-runtime.lock.json
COPY --from=application-source /tmp/yap-application-source /tmp/yap-application-source
RUN git init /tmp/tiron-source
RUN git -C /tmp/tiron-source fetch --depth 1 \
      https://github.com/TrelisResearch/tiron.git "${TIRON_REVISION}" \
    && git -C /tmp/tiron-source switch --detach FETCH_HEAD \
    && test "$(git -C /tmp/tiron-source rev-parse HEAD)" = "${TIRON_REVISION}" \
    && rm -rf /tmp/tiron-source/.git \
    && PYTHONPATH=/tmp/yap-application-source python3 -c \
      'from pathlib import Path; from yap_server.meeting_transcription.runtime_provenance import load_meeting_runtime_provenance, verify_repository_source_directory; p = load_meeting_runtime_provenance(Path("/tmp/meeting-runtime.lock.json")); verify_repository_source_directory(p.harness, Path("/tmp/tiron-source"))'

FROM ${BASE_IMAGE}
ARG TIRON_REVISION
ARG TORCHAUDIO_REVISION

LABEL org.opencontainers.image.title="Yap Tiron meeting-transcription runtime" \
      org.opencontainers.image.source="https://github.com/mcnatg1/yap" \
      org.opencontainers.image.licenses="LicenseRef-NVIDIA-AI AND Apache-2.0 AND BSD-2-Clause AND BSD-3-Clause AND ISC AND LGPL-2.1-or-later AND MIT" \
      io.yap.tiron.revision="${TIRON_REVISION}" \
      io.yap.torchaudio.revision="${TORCHAUDIO_REVISION}"

ENV PYTHONPATH=/opt/yap-server:/opt/tiron-runtime \
    YAP_MEETING_TRANSCRIPTION_RUNTIME_LOCK=/opt/yap-server/meeting-transcription-runtime.lock.json \
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

COPY runtime/tiron/requirements.lock /tmp/yap-tiron-requirements.lock
COPY --from=torchaudio-wheel-builder /tmp/torchaudio-wheel/torchaudio-*.whl /tmp/torchaudio-wheel/
RUN python3 -m pip install \
      --disable-pip-version-check \
      --no-cache-dir \
      --no-deps \
      --require-hashes \
      --requirement /tmp/yap-tiron-requirements.lock \
    && python3 -m pip install \
      --disable-pip-version-check \
      --no-cache-dir \
      --no-deps \
      /tmp/torchaudio-wheel/torchaudio-*.whl \
    && rm -rf /tmp/yap-tiron-requirements.lock /tmp/torchaudio-wheel

COPY --from=tiron-source /tmp/tiron-source/tiron /opt/tiron-runtime/tiron
COPY runtime/tiron/compatibility /opt/tiron-compatibility
RUN python3 /opt/tiron-compatibility/patch_local_ecapa_source.py

ARG YAP_CHECKED_HEAD
LABEL org.opencontainers.image.revision="${YAP_CHECKED_HEAD}" \
      com.mcnatg1.yap.base-platform-digest="sha256:dcae8df08ef61b019b8eb109113428cba4ef0e37484c6e722406150dd5ada759" \
      com.mcnatg1.yap.runtime="meeting-transcription"

COPY meeting-transcription-runtime.lock.json /opt/yap-server/meeting-transcription-runtime.lock.json
COPY runtime/tiron/requirements.lock /opt/yap-server/runtime/tiron/requirements.lock
COPY runtime/tiron/THIRD_PARTY_NOTICES.md /opt/yap-server/THIRD_PARTY_NOTICES.md
COPY runtime/asr/THIRD_PARTY_NOTICES.md \
  /opt/yap-server/SHARED_PYTHON_THIRD_PARTY_NOTICES.md
COPY runtime/asr/licenses/APACHE-2.0.txt /opt/yap-server/licenses/APACHE-2.0.txt
COPY runtime/cohere-vllm/licenses/TORCHAUDIO-BSD-2-Clause.txt \
  /opt/yap-server/licenses/TORCHAUDIO-BSD-2-Clause.txt
COPY --from=tiron-source /tmp/tiron-source/LICENSE \
  /opt/yap-server/licenses/TIRON-APACHE-2.0.txt
COPY --from=application-source /tmp/yap-application-source/yap_server /opt/yap-server/yap_server

# Request-time inference carries the runtime contract, not developer evaluation tools.
RUN test ! -e /opt/yap-server/yap_server/evaluation

RUN test "${#YAP_CHECKED_HEAD}" -eq 40 \
    && case "${YAP_CHECKED_HEAD}" in *[!0-9a-f]*) exit 1 ;; esac \
    && python3 -c 'import importlib.metadata as m, sys, tiron, torch, torchaudio; assert sys.version_info[:2] == (3, 12); assert torch.__version__ == "2.13.0a0+8145d630e8.nv26.06"; assert torch.version.cuda == "13.3"; assert tiron.__version__ == "0.1.0"; assert m.version("speechbrain") == "1.1.0"; assert m.version("transformers") == "5.13.1"; assert torchaudio.__version__.startswith("2.11.0")' \
    && chmod -R a+rX /opt/yap-server /opt/tiron-runtime /opt/tiron-compatibility \
    && groupadd --gid 10001 yapmeeting \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin yapmeeting

USER 10001:10001
ENTRYPOINT ["python3", "-m", "yap_server.meeting_transcription.worker"]

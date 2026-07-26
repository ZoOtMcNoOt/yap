ARG YAP_ASR_WORKER_IMAGE=yap-asr-worker:checked
FROM ${YAP_ASR_WORKER_IMAGE}

LABEL org.opencontainers.image.title="Yap private ASR evaluation runtime" \
      org.opencontainers.image.source="https://github.com/mcnatg1/yap" \
      org.opencontainers.image.licenses="LicenseRef-NVIDIA-AI AND Apache-2.0 AND CNRI-Python AND MIT"

USER 0:0

COPY requirements.lock /tmp/yap-asr-evaluation-requirements.lock
RUN python3 -m pip install \
      --disable-pip-version-check \
      --no-cache-dir \
      --no-deps \
      --only-binary=:all: \
      --require-hashes \
      --requirement /tmp/yap-asr-evaluation-requirements.lock \
    && python3 -c 'import importlib.metadata as m, sys; assert sys.version_info[:2] == (3, 12); assert m.version("rapidfuzz") == "3.14.5"; assert m.version("regex") == "2026.7.10"' \
    && rm -f /tmp/yap-asr-evaluation-requirements.lock

COPY THIRD_PARTY_NOTICES.md /opt/yap-server/EVALUATION_THIRD_PARTY_NOTICES.md

WORKDIR /opt/yap-evaluation

USER 10001:10001
ENTRYPOINT ["python3", "-m", "yap_server.evaluation.fleurs_cohere_comparator"]

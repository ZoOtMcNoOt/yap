FROM python:3.12.13-slim-bookworm@sha256:c18c7a910432dde3311fc54d02e5d5220f3ebe26fec43ff15745982863dd7b3b AS application-source

COPY src/yap_server /tmp/yap-application-source/yap_server
RUN rm -rf /tmp/yap-application-source/yap_server/evaluation

FROM python:3.12.13-slim-bookworm@sha256:c18c7a910432dde3311fc54d02e5d5220f3ebe26fec43ff15745982863dd7b3b

LABEL org.opencontainers.image.title="Yap isolated AmberNet LID preflight" \
      org.opencontainers.image.source="https://github.com/mcnatg1/yap" \
      org.opencontainers.image.licenses="Apache-2.0 AND BSD-3-Clause AND MIT" \
      com.mcnatg1.yap.base-platform-digest="sha256:c18c7a910432dde3311fc54d02e5d5220f3ebe26fec43ff15745982863dd7b3b"

ENV PYTHONPATH=/opt/yap-repo/server/src \
    YAP_LID_COMPONENT_LOCK=/opt/yap-repo/server/lid-component.lock.json \
    DO_NOT_TRACK=1 \
    HOME=/tmp/yap-lid \
    XDG_CACHE_HOME=/tmp/cache \
    TMPDIR=/tmp \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/yap-repo/server

COPY runtime/lid/requirements.lock /opt/yap-repo/server/runtime/lid/requirements.lock
RUN python3 -m pip install \
      --disable-pip-version-check \
      --no-cache-dir \
      --require-hashes \
      --requirement /opt/yap-repo/server/runtime/lid/requirements.lock \
    && python3 -m pip check

ARG YAP_CHECKED_HEAD
LABEL org.opencontainers.image.revision="${YAP_CHECKED_HEAD}"

COPY lid-component.lock.json /opt/yap-repo/server/lid-component.lock.json
COPY runtime/lid/THIRD_PARTY_NOTICES.md /opt/yap-repo/server/THIRD_PARTY_NOTICES.md
COPY runtime/asr/licenses/APACHE-2.0.txt /opt/yap-repo/server/licenses/APACHE-2.0.txt
COPY runtime/lid/build_check.py /tmp/yap-lid-build-check.py
COPY --from=application-source /tmp/yap-application-source/yap_server /opt/yap-repo/server/src/yap_server

RUN test "${#YAP_CHECKED_HEAD}" -eq 40 \
    && case "${YAP_CHECKED_HEAD}" in *[!0-9a-f]*) exit 1 ;; esac \
    && test ! -e /opt/yap-repo/server/src/yap_server/evaluation \
    && chmod -R a+rX /opt/yap-repo \
    && python3 /tmp/yap-lid-build-check.py \
    && rm -f /tmp/yap-lid-build-check.py \
    && groupadd --gid 10001 yaplid \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin yaplid

USER 10001:10001
ENTRYPOINT ["python3", "-m", "yap_server.lid.worker"]

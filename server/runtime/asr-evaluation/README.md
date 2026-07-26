# Private ASR evaluation runtime

This overlay runs source-specific ASR quality comparators against the same
Python 3.12, NVIDIA Torch/CUDA, Transformers, and model-artifact contract as the
locked batch worker. It adds only the pinned transcript-scoring dependencies.

Build with an already verified worker image as `YAP_ASR_WORKER_IMAGE`. At run
time, mount the current `yap_server` source, exact public plan/lock metadata,
locked model directory, and `YAP_EVAL_CACHE` explicitly. Keep inference network
disabled, the root filesystem read-only, the process unprivileged, and the
evaluation cache private. The comparator writes references and hypotheses only
under that cache and emits a transcript-free aggregate to standard output.
The overlay deliberately uses `/opt/yap-evaluation` as its working directory so
an older worker source tree cannot shadow the explicitly mounted source path.

Keep the corpus and result mounts beneath the same private `YAP_EVAL_CACHE`
root: mount corpus inputs read-only and the result directory read-write. The
corpus validator rejects source artifacts outside that boundary. Keep general
temporary storage `noexec`, but map `TRITON_CACHE_DIR` to the functionally named
`/torch-compile-cache` disposable, size-bounded executable tmpfs; NVIDIA Torch's
compiler dependency must load its generated CUDA helper library. That narrow cache does not justify writable executable
storage elsewhere, network access, capabilities, or a writable root filesystem.

The FLEURS comparator is descriptive regression evidence. It cannot promote a
locale, prove spontaneous/noisy/meeting behavior, or replace the separate
duration and concurrency qualification plan.

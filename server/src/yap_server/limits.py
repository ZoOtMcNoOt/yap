"""Shared byte limits at server transport boundaries."""

MAX_TRANSCRIPT_BYTES = 1024 * 1024

# Dynamic results carry the same bounded transcript text once in the display
# transcript and once across ordered language segments, plus bounded evidence.
# Keep container stdout and resident-runtime HTTP paths finite while allowing that
# lossless representation at the maximum transcript boundary.
MAX_WORKER_RESULT_BYTES = 4 * 1024 * 1024

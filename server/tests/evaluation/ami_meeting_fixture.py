from __future__ import annotations

from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import wave
import zipfile


_NITE = "http://nite.sourceforge.net/"


def build_ami_meeting_fixture(
    root: Path,
    *,
    unsafe_member: str | None = None,
    unsafe_xml: bool = False,
    audio_channels: int = 1,
    compression_bomb: bool = False,
) -> tuple[Path, Path]:
    cache = root / "cache"
    release = cache / "corpora" / "ami" / "1.6.2"
    release.mkdir(parents=True)
    if os.name == "posix":
        cache.chmod(0o700)
        (cache / "corpora").chmod(0o700)
        (cache / "corpora" / "ami").chmod(0o700)
        release.chmod(0o700)

    members = {
        "A": _transcript_xml(
            "A",
            (
                ("w", "0.000", "0.020", "Alpha", {}),
                ("vocalsound", "0.030", "0.030", "", {"type": "laugh"}),
            ),
            unsafe=unsafe_xml,
        ),
        "B": _transcript_xml(
            "B",
            (
                ("w", "0.000", "0.030", "Bravo", {}),
                ("disfmarker", "0.040", "0.040", "", {}),
            ),
        ),
        "C": _transcript_xml(
            "C",
            (
                ("w", "0.040", "0.050", "Charlie", {"trunc": "true"}),
                ("gap", "0.050", "0.050", "", {}),
            ),
        ),
        "D": _transcript_xml(
            "D",
            (("w", "0.050", "0.060", ".", {"punc": "true"}),),
        ),
    }
    annotation_path = release / "ami_public_manual_1.6.2.zip"
    with zipfile.ZipFile(
        annotation_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for agent_id, body in members.items():
            archive.writestr(f"words/ES2004a.{agent_id}.words.xml", body)
        if unsafe_member is not None:
            archive.writestr(unsafe_member, "unsafe")
        if compression_bomb:
            archive.writestr("words/compression-bomb.bin", b"0" * 100_000)

    frame_count = 1_600
    audio_body = _pcm16_wav(frame_count=frame_count, channels=audio_channels)
    close_path = release / "ES2004a.Mix-Headset.wav"
    far_path = release / "ES2004a.Array1-01.wav"
    close_path.write_bytes(audio_body)
    far_path.write_bytes(audio_body)
    if os.name == "posix":
        for path in (annotation_path, close_path, far_path):
            path.chmod(0o600)

    with zipfile.ZipFile(annotation_path) as archive:
        infos = archive.infolist()
        member_sizes = {item.filename: item.file_size for item in infos}

    lock_path = root / "ami-meeting.lock.json"
    lock_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "corpus": {
                    "id": "ami-meeting-corpus",
                    "release": "1.6.2",
                    "meetingId": "ES2004a",
                    "languageBcp47": "en",
                    "scenarioSplit": "unseen-evaluation",
                    "asrSplit": "full-corpus-asr-eval",
                    "source": "https://groups.inf.ed.ac.uk/ami/corpus/datasets.shtml",
                },
                "purpose": {
                    "promotionEligible": False,
                    "exposureStatus": "unknown",
                },
                "license": {
                    "id": "CC-BY-4.0",
                    "declarationSource": "https://groups.inf.ed.ac.uk/ami/download/",
                    "legalCodeSource": (
                        "https://creativecommons.org/licenses/by/4.0/legalcode.txt"
                    ),
                    "legalCodeSha256": "9" * 64,
                },
                "annotations": {
                    "artifact": _artifact(
                        annotation_path,
                        "corpora/ami/1.6.2/ami_public_manual_1.6.2.zip",
                        (
                            "https://groups.inf.ed.ac.uk/ami/AMICorpusAnnotations/"
                            "ami_public_manual_1.6.2.zip"
                        ),
                    ),
                    "memberCount": len(infos),
                    "uncompressedBytes": sum(item.file_size for item in infos),
                },
                "transcript": {
                    "namespace": _NITE,
                    "timing": "manual-word-plus-forced-alignment",
                    "flatOrderingPolicy": "start-end-agent-source-ordinal-v1",
                    "members": [
                        _member("A", member_sizes, w=1, vocalsound=1),
                        _member("B", member_sizes, w=1, disfmarker=1),
                        _member("C", member_sizes, w=1, gap=1),
                        _member("D", member_sizes, w=1),
                    ],
                },
                "audio": {
                    "sampleRateHz": 16_000,
                    "channelCount": 1,
                    "sampleWidthBytes": 2,
                    "frameCount": frame_count,
                    "conditions": [
                        {
                            "id": "close-mix",
                            "capture": "mixed-close-talking-headsets",
                            "artifact": _artifact(
                                close_path,
                                "corpora/ami/1.6.2/ES2004a.Mix-Headset.wav",
                                (
                                    "https://groups.inf.ed.ac.uk/ami/"
                                    "AMICorpusMirror/amicorpus/HeadsetAudio/"
                                    "ES2004a.Mix-Headset.wav"
                                ),
                            ),
                        },
                        {
                            "id": "far-field-array1-channel1",
                            "capture": "single-distant-array-channel",
                            "artifact": _artifact(
                                far_path,
                                "corpora/ami/1.6.2/ES2004a.Array1-01.wav",
                                (
                                    "https://groups.inf.ed.ac.uk/ami/"
                                    "AMICorpusMirror/amicorpus/ES2004a/audio/"
                                    "ES2004a.Array1-01.wav"
                                ),
                            ),
                        },
                    ],
                },
                "limitations": [
                    "pre-existing-public-comparator",
                    "upstream-transcript-known-defects-require-review",
                    "upstream-timings-include-forced-alignment",
                    "overlap-has-no-unique-flat-word-order",
                    "speaker-attribution-not-scored-in-phase-6",
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return lock_path, cache


def _transcript_xml(
    agent_id: str,
    elements: tuple[tuple[str, str, str, str, dict[str, str]], ...],
    *,
    unsafe: bool = False,
) -> bytes:
    declarations = '<!DOCTYPE nite:root [<!ENTITY unsafe "expanded">]>' if unsafe else ""
    rows = []
    for index, (tag, start, end, text, extras) in enumerate(elements):
        attributes = {
            "nite:id": f"ES2004a.{agent_id}.words{index}",
            "starttime": start,
            "endtime": end,
            **extras,
        }
        rendered = " ".join(f'{key}="{value}"' for key, value in attributes.items())
        rows.append(f"<{tag} {rendered}>{text}</{tag}>")
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>{declarations}'
        f'<nite:root xmlns:nite="{_NITE}">{"".join(rows)}</nite:root>'
    ).encode()


def _pcm16_wav(*, frame_count: int, channels: int) -> bytes:
    output = BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(channels)
        target.setsampwidth(2)
        target.setframerate(16_000)
        target.writeframes(b"\0" * frame_count * channels * 2)
    return output.getvalue()


def _member(
    agent_id: str,
    sizes: dict[str, int],
    *,
    w: int,
    vocalsound: int = 0,
    disfmarker: int = 0,
    gap: int = 0,
) -> dict[str, object]:
    archive_path = f"words/ES2004a.{agent_id}.words.xml"
    return {
        "agentId": agent_id,
        "archivePath": archive_path,
        "size": sizes[archive_path],
        "counts": {
            "w": w,
            "vocalsound": vocalsound,
            "disfmarker": disfmarker,
            "gap": gap,
        },
    }


def _artifact(path: Path, cache_path: str, source: str) -> dict[str, object]:
    body = path.read_bytes()
    return {
        "cachePath": cache_path,
        "downloadSource": source,
        "size": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }

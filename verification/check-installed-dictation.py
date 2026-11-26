"""Check a saved first transcript of the installed desktop's offline speech fixture."""

import argparse
import json
import sys
from pathlib import Path

from recording_fixture_evidence import REPO, digest, read_fixture_pcm, read_json, require

sys.path.insert(0, str(REPO / "server/src"))
from yap_server.transcript_metrics import tokenize_wer_words, word_error_rate


def check_session(commit_path):
    commit = read_json(commit_path)
    session = commit["sessionId"]
    stem = f"live-{session}"
    require(commit_path.name == f"{stem}.commit.json" and commit["status"] == "complete",
            "Select the commit file of a complete live recording")
    audio = commit_path.with_name(f"{stem}.wav")
    capture_path = commit_path.with_name(f"{stem}.capture.json")
    revision_path = commit_path.with_name(f"{stem}.transcript.r1.json")
    text = commit_path.with_name(f"{stem}.txt")
    capture = read_json(capture_path)
    revision = read_json(revision_path)
    require(capture["sessionId"] == revision["sessionId"] == session,
            "Capture and transcript must belong to the selected session")
    metadata = capture["sessionMetadata"]
    require(metadata == commit["sessionMetadata"] and metadata["sessionId"] == session
            and metadata["mode"] == "dictation" and metadata["origin"] == "live_capture",
            "Expected a live dictation capture for the selected session")
    audio_sha = digest(audio)
    capture_sha = digest(capture_path)
    for row in (commit, capture):
        require(row["audioFile"] == audio.name and row["audioSha256"] == audio_sha
                and row["audioBytes"] == audio.stat().st_size, "Recorded WAV differs from the capture")
    require(commit["captureSidecarFile"] == capture_path.name
            and commit["captureSidecarSha256"] == revision["captureSidecarSha256"] == capture_sha,
            "The commit and transcript must reference the saved capture sidecar")
    require(not capture["sinkDegraded"] and not capture["sequenceGaps"]
            and not capture["sequenceGapOverflow"] and not capture["timelineGaps"],
            "The fixture must have contiguous microphone audio")

    frames = len(read_fixture_pcm(audio)) // 2
    language = capture["languageEvidence"]
    require(language and language["status"] == "complete" and language["sampleRateHz"] == 16000,
            "Expected complete 16 kHz language evidence for the English fixture")
    end = 0
    for span in language["spans"]:
        require(span["startSample"] == end and span["endSample"] > end, "Gap or overlap in language spans")
        end = span["endSample"]
    require(language["sourceEndSample"] == end == frames, "Language evidence ends at a different WAV sample")

    expected = read_json(REPO / "verification/fixtures/package-profile/local-dictation"
                         / "live-s-package-dictation.transcript.r1.json")
    model = (expected["modelId"], expected["modelRevision"])
    provenance = revision["modelProvenance"]
    require((revision["modelId"], revision["modelRevision"]) == model and provenance
            and (provenance[0]["modelId"], provenance[0]["revision"]) == model,
            "Unexpected on-device recognizer or model revision")
    require(revision["revision"] == 1 and revision["status"] == "complete"
            and revision["authority"] == "local_provisional", "Expected an original, complete local transcript")
    transcript = revision["transcript"]
    require(revision["textFile"] == text.name and revision["textSha256"] == digest(text)
            and text.read_bytes() == (transcript + "\n").encode(), "Saved text differs from the transcript revision")
    reference = read_json(REPO / "server/model-pools.lock.json")["fixture"]["goldenTranscript"]
    wer = word_error_rate(reference, transcript)
    require(wer == 0, f"Words differ from the licensed speech fixture (WER {wer:.2%})")

    return {
        "sessionId": session, "modelRevision": revision["modelRevision"], "frames": frames,
        "referenceWords": len(tokenize_wer_words(reference)), "audioSha256": audio_sha,
        "commitSha256": digest(commit_path), "captureSha256": capture_sha,
        "revisionSha256": digest(revision_path), "textSha256": revision["textSha256"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("commit", type=Path, help="Selected live-*.commit.json under live-recordings")
    receipt = parser.add_mutually_exclusive_group()
    receipt.add_argument("--save-receipt", type=Path, help="Write the checked hashes to a new file")
    receipt.add_argument("--compare-receipt", type=Path, help="Require the same session and bytes after restart")
    args = parser.parse_args()
    result = check_session(args.commit)
    if args.compare_receipt:
        require(result == read_json(args.compare_receipt), "Saved session differs from the earlier receipt")
    if args.save_receipt:
        with args.save_receipt.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

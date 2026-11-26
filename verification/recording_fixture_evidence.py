"""Read-only checks for installed desktop recording fixtures, using standard Python."""

import hashlib
import json
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def read_json(path):
    return json.loads(path.read_bytes())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_fixture_pcm(path):
    with wave.open(str(path)) as wav:
        require((wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16_000, 1, 2),
                f"{path.name} is not 16 kHz mono PCM16")
        frames = wav.getnframes()
        pcm = wav.readframes(frames)
        require(frames > 0 and len(pcm) == frames * 2, f"{path.name} has incomplete audio")
        return pcm

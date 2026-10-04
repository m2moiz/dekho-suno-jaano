#!/usr/bin/env python3
"""Speak every shipped bleep-list word with text-to-speech, for #152.

Writes one 16 kHz mono WAV per set, and a manifest saying where each spoken
unit sits in it, under scratch/bleep_recall/audio/ (ignored by git):

    en_samantha, en_daniel, en_rishi   every English `roman` spelling, alone,
                                       in three macOS `say` voices
    ur                                 every Urdu `script` spelling, alone
    pa                                 every Punjabi `script` spelling, alone
                                       (Gurmukhi by mms-tts-pan, Shahmukhi by
                                       the Urdu model)
    hi                                 every Hindi `script` spelling, alone
    mixed                              SENTENCES below: short sentences, most
                                       switching language, one listed word each

A word alone has LEAD_S of near-silence before the first and GAP_S between
units. A sentence is its pieces spoken separately and joined with JOIN_S, so
where the listed word sits is known exactly, not estimated. A phrase spelling
("bhen chod") whose run-together form is also listed is spoken once, run
together: the two sound the same.

MMS-TTS runs through `transformers`, never added to dsj's dependencies:

    uv run --no-project --python 3.12 --with transformers==4.57.1 \\
        --with torch==2.9.0 --with numpy scratch/bleep_recall/make_audio.py

The models are CC-BY-NC 4.0 and pinned to the revisions in MMS below. Seeds
are fixed, so a rerun on the same versions writes the same audio.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import tomllib
import unicodedata
import wave
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[2]
WORDS = REPO / "dsj" / "words"
OUT = Path(__file__).resolve().parent / "audio"

RATE = 16000
LEAD_S = 1.0
GAP_S = 1.5
JOIN_S = 0.06
PEAK = 0.5
NOISE = 1e-3  # a floor under the silence, about -60 dBFS, so it is not digital zero

VOICES = {"samantha": "Samantha", "daniel": "Daniel", "rishi": "Rishi"}
MMS = {
    "urd": ("facebook/mms-tts-urd-script_arabic", "4c4f53d52e4f0b40cb8e7f36dcef66a2a73619c5"),
    "pan": ("facebook/mms-tts-pan", "45d7962e8daba724f9ff251ee3198bdb47a5f498"),
    "hin": ("facebook/mms-tts-hin", "1d83b223ec78e30b944f7d96bd117eb3d7023303"),
}

# (tts, text, is_target). tts is a macOS voice key or an MMS key. Each
# sentence holds exactly one listed word, marked True, voiced in its own
# language; the rest is the frame.
type Piece = tuple[str, str, bool]
SENTENCES: list[tuple[str, list[Piece]]] = [
    # English frame, Urdu word
    ("ur:harami", [("samantha", "honestly, that guy is a", False), ("urd", "حرامی", True),
                   ("samantha", "and everyone knows it", False)]),
    ("ur:kameena", [("daniel", "he called me a", False), ("urd", "کمینہ", True),
                    ("daniel", "in front of the whole team", False)]),
    ("ur:chutiya", [("rishi", "stop acting like a", False), ("urd", "چوتیا", True),
                    ("rishi", "and fix the build", False)]),
    ("ur:bharwa", [("samantha", "the client is being a real", False), ("urd", "بھڑوا", True),
                   ("samantha", "about the invoice", False)]),
    ("ur:behenchod", [("daniel", "I told him", False), ("urd", "بہنچود", True),
                      ("daniel", "just send the file", False)]),
    ("ur:gandu", [("rishi", "what a", False), ("urd", "گانڈو", True),
                  ("rishi", "move that was", False)]),
    ("ur:madarchod", [("samantha", "my cousin said", False), ("urd", "مادرچود", True),
                      ("samantha", "when the power went out", False)]),
    ("ur:kanjar", [("daniel", "that", False), ("urd", "کنجر", True),
                   ("daniel", "never paid me back", False)]),
    ("ur:harami", [("rishi", "don't be a", False), ("urd", "حرامزادہ", True),
                   ("rishi", "about it", False)]),
    # Urdu frame, English word
    ("en:shit", [("urd", "یار یہ کام بالکل", False), ("samantha", "bullshit", True),
                 ("urd", "ہے", False)]),
    ("en:ass", [("urd", "وہ بندہ پورا", False), ("daniel", "asshole", True),
                ("urd", "نکلا", False)]),
    ("en:fuck", [("urd", "میں نے کہا", False), ("rishi", "fuck", True),
                 ("urd", "یہ کیا ہو گیا", False)]),
    ("en:shit", [("urd", "اس کی گاڑی", False), ("samantha", "shitty", True),
                 ("urd", "ہے یار", False)]),
    ("en:bastard", [("urd", "وہ", False), ("daniel", "bastard", True),
                    ("urd", "پھر سے لیٹ آیا", False)]),
    ("en:fuck", [("urd", "یہ", False), ("rishi", "fucking", True),
                 ("urd", "انٹرنیٹ نہیں چل رہا", False)]),
    ("en:bitch", [("urd", "باس نے پھر", False), ("samantha", "bitching", True),
                  ("urd", "شروع کر دی", False)]),
    # Urdu frame, Urdu word
    ("ur:kameena", [("urd", "یار تم بہت بڑے", False), ("urd", "کمینے", True),
                    ("urd", "ہو", False)]),
    # Punjabi frame, Punjabi word
    ("pa:kanjar", [("pan", "ਓਏ ਤੂੰ ਬਹੁਤ ਵੱਡਾ", False), ("pan", "ਕੰਜਰ", True),
                   ("pan", "ਏਂ", False)]),
    ("pa:dalla", [("pan", "ਉਹ", False), ("pan", "ਦੱਲਾ", True),
                  ("pan", "ਫੇਰ ਆ ਗਿਆ", False)]),
    # English frame, Punjabi word
    ("pa:penchod", [("daniel", "that guy is such a", False), ("pan", "ਭੈਣਚੋਦ", True),
                    ("daniel", "seriously", False)]),
    ("pa:phuddi", [("rishi", "look at this", False), ("pan", "ਫੁੱਦੂ", True),
                   ("rishi", "driving", False)]),
    ("pa:harami", [("samantha", "who parked here, some", False), ("pan", "ਹਰਾਮੀ", True),
                   ("samantha", "or what", False)]),
    # Punjabi frame, English word
    ("en:fuck", [("pan", "ਮੈਂ ਕਿਹਾ", False), ("daniel", "fuck", True),
                 ("pan", "ਇਹ ਕੀ ਹੋ ਗਿਆ", False)]),
    ("en:dickhead", [("pan", "ਇਹ ਬੰਦਾ", False), ("rishi", "dickhead", True),
                     ("pan", "ਆ", False)]),
    # Hindi frame, English word; English frame, Hindi word
    ("en:shit", [("hin", "यार ये पूरा", False), ("samantha", "bullshit", True),
                 ("hin", "है", False)]),
    ("hi:bhosdi", [("daniel", "my neighbour is a", False), ("hin", "भोसड़ीके", True),
                   ("daniel", "honestly", False)]),
    ("hi:chutiya", [("rishi", "he said", False), ("hin", "चूतिया", True),
                    ("rishi", "and walked out", False)]),
    # English only
    ("en:fuck", [("samantha", "this is", False), ("samantha", "fucking", True),
                 ("samantha", "ridiculous", False)]),
    ("en:shit", [("daniel", "what a load of", False), ("daniel", "bullshit", True),
                 ("daniel", "that was", False)]),
    ("en:wanker", [("rishi", "shut up you", False), ("rishi", "wanker", True),
                   ("rishi", "and sit down", False)]),
]


def spoken_forms(lang: str, key: str) -> list[tuple[str, str]]:
    """(entry, spelling) for each spelling under `key`, a listed phrase run together once."""
    entries = tomllib.loads((WORDS / f"{lang}.toml").read_text(encoding="utf-8"))["entry"]
    forms: list[tuple[str, str]] = []
    seen: set[str] = set()
    for entry in entries:
        spellings: list[str] = entry.get(key, [])
        for spelling in spellings:
            said = spelling.replace(" ", "")
            if said in seen:
                continue
            seen.add(said)
            forms.append((f"{lang}:{entry['name']}", spelling))
    return forms


def is_arabic(text: str) -> bool:
    return any("؀" <= ch <= "ۿ" for ch in text)


def trim(audio: np.ndarray) -> np.ndarray:
    """Cut the leading and trailing near-silence a TTS pads its output with."""
    loud = np.flatnonzero(np.abs(audio) > 0.02 * np.abs(audio).max())
    if loud.size == 0:
        raise ValueError("the TTS returned silence")
    margin = int(0.02 * RATE)
    return audio[max(loud[0] - margin, 0) : loud[-1] + margin]


def say(voice: str, text: str) -> np.ndarray:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "say.wav"
        subprocess.run(
            ["say", "-v", VOICES[voice], "-o", str(path), "--file-format=WAVE",
             f"--data-format=LEI16@{RATE}", "--", text],
            check=True,
        )
        with wave.open(str(path)) as f:
            assert f.getframerate() == RATE and f.getnchannels() == 1
            raw = np.frombuffer(f.readframes(f.getnframes()), dtype="<i2")
    return raw.astype(np.float32) / 32768


class Mms:
    """The three MMS-TTS models, loaded on first use."""

    def __init__(self) -> None:
        self.loaded: dict[str, Any] = {}

    def __call__(self, key: str, text: str) -> np.ndarray:
        import torch
        from transformers import AutoTokenizer, VitsModel

        if key not in self.loaded:
            model_id, revision = MMS[key]
            self.loaded[key] = (
                AutoTokenizer.from_pretrained(model_id, revision=revision),
                VitsModel.from_pretrained(model_id, revision=revision).eval(),
            )
        tokenizer, model = self.loaded[key]
        assert model.config.sampling_rate == RATE
        text = unicodedata.normalize("NFC", text)
        vocab = tokenizer.get_vocab()
        missing = sorted({ch for ch in unicodedata.normalize("NFD", text) if ch not in vocab
                          and ch != " " and unicodedata.normalize("NFC", ch) not in vocab})
        if missing:
            print(f"  note: {key} has no symbol for {missing!r} in a unit", file=sys.stderr)
        torch.manual_seed(0)
        with torch.no_grad():
            out = model(**tokenizer(text, return_tensors="pt")).waveform[0].numpy()
        return out.astype(np.float32)


def speak(mms: Mms, tts: str, text: str) -> np.ndarray:
    audio = say(tts, text) if tts in VOICES else mms(tts, text)
    audio = trim(audio)
    return audio * (PEAK / np.abs(audio).max())


def tts_name(tts: str) -> str:
    return f"say:{VOICES[tts]}" if tts in VOICES else f"{MMS[tts][0]}@{MMS[tts][1][:7]}"


def write(name: str, chunks: list[np.ndarray]) -> float:
    audio = np.concatenate(chunks)
    rng = np.random.default_rng(0)
    audio = np.clip(audio + rng.normal(0, NOISE, audio.size), -1, 1)
    with wave.open(str(OUT / f"{name}.wav"), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes((audio * 32767).astype("<i2").tobytes())
    return round(audio.size / RATE, 3)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * RATE), dtype=np.float32)


def word_set(mms: Mms, name: str, units: list[tuple[str, str, str]]) -> dict[str, Any]:
    """units: (entry, spelling, tts). Each alone, GAP_S apart."""
    chunks = [silence(LEAD_S)]
    at = LEAD_S
    rows = []
    for index, (entry, spelling, tts) in enumerate(units):
        audio = speak(mms, tts, spelling.replace(" ", ""))
        start, end = at, at + audio.size / RATE
        rows.append({"id": f"{name}-{index:03d}", "kind": "word", "entry": entry,
                     "spoken": spelling.replace(" ", ""), "tts": tts_name(tts),
                     "start": round(start, 3), "end": round(end, 3),
                     "target": [round(start, 3), round(end, 3)]})
        chunks += [audio, silence(GAP_S)]
        at = end + GAP_S
    return {"set": name, "units": rows, "duration_s": write(name, chunks)}


def sentence_set(mms: Mms) -> dict[str, Any]:
    chunks = [silence(LEAD_S)]
    at = LEAD_S
    rows = []
    for index, (entry, pieces) in enumerate(SENTENCES):
        assert sum(target for _, _, target in pieces) == 1, entry
        start = at
        target: list[float] = []
        for p_index, (tts, text, is_target) in enumerate(pieces):
            if p_index:
                chunks.append(silence(JOIN_S))
                at += JOIN_S
            audio = speak(mms, tts, text)
            if is_target:
                target = [round(at, 3), round(at + audio.size / RATE, 3)]
            chunks.append(audio)
            at += audio.size / RATE
        word = next((text, tts) for tts, text, is_target in pieces if is_target)
        rows.append({"id": f"mixed-{index:03d}", "kind": "sentence", "entry": entry,
                     "spoken": word[0], "tts": tts_name(word[1]),
                     "frame": sorted({tts_name(t) for t, _, x in pieces if not x}),
                     "start": round(start, 3), "end": round(at, 3), "target": target})
        chunks.append(silence(GAP_S))
        at += GAP_S
    return {"set": "mixed", "units": rows, "duration_s": write("mixed", chunks)}


def main() -> None:
    import torch
    import transformers

    OUT.mkdir(parents=True, exist_ok=True)
    mms = Mms()
    sets = []
    english = spoken_forms("en", "roman")
    for voice in VOICES:
        sets.append(word_set(mms, f"en_{voice}", [(e, s, voice) for e, s in english]))
        print(f"en_{voice}: {len(english)} words", file=sys.stderr)
    for lang, model in (("ur", "urd"), ("hi", "hin")):
        units = [(e, s, model) for e, s in spoken_forms(lang, "script")]
        sets.append(word_set(mms, lang, units))
        print(f"{lang}: {len(units)} words", file=sys.stderr)
    punjabi = [(e, s, "urd" if is_arabic(s) else "pan") for e, s in spoken_forms("pa", "script")]
    sets.append(word_set(mms, "pa", punjabi))
    print(f"pa: {len(punjabi)} words", file=sys.stderr)
    sets.append(sentence_set(mms))
    print(f"mixed: {len(SENTENCES)} sentences", file=sys.stderr)
    manifest = {
        "rate": RATE, "lead_s": LEAD_S, "gap_s": GAP_S, "join_s": JOIN_S,
        "torch": torch.__version__, "transformers": transformers.__version__,
        "mms": {k: {"id": v[0], "revision": v[1], "licence": "cc-by-nc-4.0"}
                for k, v in MMS.items()},
        "sets": sets,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    for s in sets:
        print(f"{s['set']}: {len(s['units'])} units, {s['duration_s']} s", file=sys.stderr)


if __name__ == "__main__":
    main()

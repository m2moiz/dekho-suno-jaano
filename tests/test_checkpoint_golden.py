"""Checkpoints on disk, as real bytes, held against the code that reads them now.

A checkpoint that stops matching is not an error. It is a re-transcription of an
hour of audio, so no ordinary test failure would ever point at the change that
caused it. This file is the pointing.

Each fixture was written once, by `write_checkpoint` as it stood that day, and is
committed as a literal file. Neither may be regenerated: a fixture rebuilt by new
code only proves the new code agrees with itself, which is exactly the non-proof
this file exists to rule out.

`tests/golden/checkpoint-v1.json.ckpt` was written at commit eb9ea14, while
`AlignedToken` was still parakeet's class. Its fingerprint names the recording by
path, size and mtime, which #118 replaced with a content id because a rename, a
move or a plain `cp` threw the resume away. So a v1 checkpoint can no longer
resume, by decision. What it pins now is how it fails: once, with a reason naming
the schema, rather than in silence or by resuming under a key it never had.

`tests/golden/checkpoint-v2.json.ckpt` was written by the #118 change, the first
writer to key on the content id. It must go on resuming. A change to the shape of
Fingerprint, to the flat engine keys of to_dict(), or to the token document fails
here before it reaches someone's half-finished run.

The expected values below are duplicated from the fixtures BY HAND, on purpose.
Deriving them from the files at test time would let one bug in the reader corrupt
both sides of the comparison.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from dsj.checkpoint import SCHEMA, Fingerprint, read_checkpoint

GOLDEN = Path(__file__).parent / "golden"
V1 = GOLDEN / "checkpoint-v1.json.ckpt"
V2 = GOLDEN / "checkpoint-v2.json.ckpt"

# The v1 fingerprint as the old writer recorded it. A dict rather than a
# Fingerprint because the class can no longer express it: three of these keys
# are gone. `parakeet_version` sits where the pre-extraction dataclass had it.
V1_FINGERPRINT = {
    "schema": 1,
    "media": "/recordings/golden.m4a",
    "media_size": 48213977,
    "media_mtime_ns": 1755087412000000000,
    "total_samples": 71424000,
    "model_id": "mlx-community/parakeet-tdt-0.6b-v3",
    "parakeet_version": "0.5.2",
    "chunk_s": 120.0,
    "overlap_s": 15.0,
}

# The v2 fingerprint, spelled out field by field. If Fingerprint's shape changes
# such that this no longer constructs, that is the test working: the change has
# to come here and answer for the checkpoints already on disk.
GOLDEN_FP = Fingerprint(
    schema=2,
    content_id="48213977-23b1481c23935d480d899ec7fdf8f6074570e4bfce9b729e770c7de22d39a65a",
    total_samples=71424000,
    model_id="mlx-community/parakeet-tdt-0.6b-v3",
    chunk_s=120.0,
    overlap_s=15.0,
    # In the file this is the FLAT key `parakeet_version`, the shape every
    # writer so far has produced. Fingerprint.to_dict() must keep serializing
    # to exactly that.
    engine_fields={"parakeet_version": "0.5.2"},
    media="/recordings/golden.m4a",
)


def test_golden_checkpoint_resumes() -> None:
    resumed = read_checkpoint(V2, GOLDEN_FP)
    assert resumed is not None, "a checkpoint written by the #118 writer stopped matching"
    next_start, tokens = resumed

    assert next_start == 1680000
    assert len(tokens) == 4

    first, last = tokens[0], tokens[-1]
    assert (first.id, first.text, first.start, first.duration, first.confidence) == (
        0,
        " the",
        0.08,
        0.24,
        1.0,
    )
    assert (last.id, last.text, last.start, last.duration, last.confidence) == (
        1204,
        " fox",
        119.96,
        0.301,
        1.0,
    )
    # `end` is not in the JSON; __post_init__ must recompute it. 119.96 + 0.301
    # is 120.261 only in floating point -- the literal pins the recompute to
    # the same arithmetic, not merely the same idea.
    assert last.end == 120.261
    assert first.end == first.start + first.duration

    # The third token carries the non-default confidence.
    assert tokens[2].confidence == 0.5


def test_golden_checkpoint_resumes_after_the_recording_is_renamed() -> None:
    """The promise #118 made, held against real bytes: the path is a note, not a key."""
    renamed = dataclasses.replace(GOLDEN_FP, media="/elsewhere/renamed.m4a")
    assert read_checkpoint(V2, renamed) is not None


def test_golden_checkpoint_bytes_are_what_the_writer_wrote() -> None:
    """Guard the fixtures themselves against a well-meaning regeneration.

    If someone re-runs the writer and commits the result, values drift
    invisibly (a new parakeet version, a reordered dict) and the golden test
    starts proving self-agreement. Pinning the raw JSON keys and the exact
    fingerprint dict makes that a loud diff instead.
    """
    v2 = json.loads(V2.read_text())
    assert set(v2) == {"media", "fingerprint", "next_start", "tokens"}
    assert v2["media"] == "/recordings/golden.m4a"
    assert v2["fingerprint"] == GOLDEN_FP.to_dict()

    v1 = json.loads(V1.read_text())
    assert set(v1) == {"fingerprint", "next_start", "tokens"}
    assert v1["fingerprint"] == V1_FINGERPRINT
    assert v1["tokens"] == v2["tokens"], "the two fixtures bank the same four tokens"

    # `end` must be absent from every stored token -- it is derived state, and
    # persisting it would add a way for the file to disagree with the class.
    for doc in v2["tokens"]:
        assert set(doc) == {"id", "text", "start", "duration", "confidence"}


def test_golden_checkpoint_rejects_a_different_run() -> None:
    """The same file must NOT resume under any other fingerprint.

    Guards against the reader ever weakening to a partial match -- the
    docstring on Fingerprint promises exact equality of the whole record.
    """
    other = dataclasses.replace(GOLDEN_FP, model_id="mlx-community/other-model")
    assert read_checkpoint(V2, other) is None


def test_a_v1_checkpoint_starts_over_once_and_says_why() -> None:
    """The cost of #118, paid once per checkpoint written before it, and stated.

    A v1 checkpoint cannot match any fingerprint this code builds, for the
    recording it came from or any other, so an interrupted run from before the
    upgrade transcribes from the start. The reason names the schema, and only the
    schema, so the user reads "older format" and not a list of seven fields.
    """
    reasons: list[str] = []
    assert read_checkpoint(V1, GOLDEN_FP, on_reject=reasons.append) is None
    assert SCHEMA == 2
    assert reasons == [
        "it was written by another version of dsj, checkpoint schema 1 where this "
        "one reads 2 (schema)"
    ]

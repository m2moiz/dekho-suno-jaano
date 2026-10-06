#!/usr/bin/env python3
"""Score transcripts against a public reference in one romanized space (#184, #62, #183).

    uv run --with uroman --with rapidfuzz --with num2words python scratch/accuracy/score.py table
    uv run --with uroman --with rapidfuzz --with num2words python scratch/accuracy/score.py pairs [--n 50]
    uv run --with uroman --with rapidfuzz --with num2words python scratch/accuracy/score.py cutoffs
    uv run --with uroman --with rapidfuzz --with num2words python scratch/accuracy/score.py retry
    uv run --with uroman --with rapidfuzz --with num2words python scratch/accuracy/score.py split
    uv run --with uroman --with rapidfuzz --with num2words python scratch/accuracy/score.py seams
    uv run --with uroman --with rapidfuzz --with num2words python scratch/accuracy/score.py one RUN.json TRUTH.json
    uv run --with uroman --with rapidfuzz --with num2words python scratch/accuracy/score.py wall
    uv run --with uroman --with rapidfuzz --with num2words python scratch/accuracy/score.py english [--runs PATTERN]

`table` and `wall` take `--runs PATTERN` too (a name pattern such as
`pakurdu_*` or `*roman_vad-r1`); with none they list every run there is,
#235's model names included.

`uroman` (isi-nlp's universal romanizer, PyPI `uroman`) and `rapidfuzz` ride
in through `--with`: they are the scorer's, not dsj's, and never enter its
dependencies. The transcripts are scratch/accuracy/run.py's, under
scratch/accuracy/runs/<set>/<mode>-r<N>.json; the references are
scratch/urdu_cs/ground_truth.json (#148's podcast) and
scratch/accuracy/{urdu,earnings}/truth.json (build_refs.py).

## How two words are compared

The outputs come in two scripts: the reference writes Urdu in Urdu script and
English in Latin, `--roman-urdu` writes both in Latin, `--language ur` writes
English loanwords in Urdu letters. Matching must not punish the script (#184),
so every word goes through the same three steps on both sides:

1. Tokens: split on whitespace and hyphens, drop bracketed tags (`<inaudible>`),
   keep letters and digits only, lower-case. A transcript word is a token
   opening with whitespace plus the tokens after it that do not, the way the
   reader groups words (ui/src/features/transcript/document.ts).
2. Romanize: Urdu letters that Roman Urdu spells alike are folded first
   (URDU_FOLD: the three s letters, the four z letters, two t, two h,
   qaf to kaf, ain to a vowel at the start and nothing elsewhere, the Arabic forms of yeh, kaf and heh), then `uroman` writes
   the word in Latin. Latin words pass through unchanged.
3. Key: a consonant skeleton that keeps the final vowel's class, because the
   Urdu function words differ only there (ka, ki, ke, ko) and Roman spellings
   differ mostly in the vowels inside (hamare, humare, hmarye). English
   spellings get a few sound rules first (tion, c, ph, x, dge) so English
   written in Urdu letters (پروڈکٹ, `prwddktt`) can meet its Latin spelling.
   See `key`.

Two words match when their keys are equal. Alignment is word-level
Levenshtein over the whole file (rapidfuzz), then every stretch between two
matched runs is aligned again with a key-distance-1 allowance for keys of four
letters or more, which is where long loanwords differ by one sound.

The 50-pair hand check (`pairs`) prints cross-script aligned pairs with the
scorer's verdict for a person to mark; its result is recorded in #184.

## What is counted

Against N reference words: `wer` = (substituted + missed + invented) / N;
`miss` = reference words with no output word aligned to them; `ins` = output
words with no reference word (inventions, including any over the podcast's
silent gaps); `sub` = the rest. `strict` is the same WER with words compared
as romanized strings, no key, to show how much the key forgives.
"""

from __future__ import annotations

import argparse
import functools
import json
import random
import re
import sys
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uroman

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from num2words import num2words
from rapidfuzz.distance import Levenshtein

REPO = Path(__file__).resolve().parent.parent.parent
HERE = REPO / "scratch" / "accuracy"
RUNS = HERE / "runs"
TRUTHS = {
    "podcast": REPO / "scratch" / "urdu_cs" / "ground_truth.json",
    "urdu": HERE / "urdu" / "truth.json",
    "earnings": HERE / "earnings" / "truth.json",
    "earnings_call": HERE / "earnings" / "truth.json",
}
OUT = HERE / "results.md"

URDU_FOLD = str.maketrans({
    "\u062b": "\u0633", "\u0635": "\u0633",  # se, suad -> seen
    "\u0630": "\u0632", "\u0636": "\u0632", "\u0638": "\u0632",  # zal, zuad, zoe -> ze
    "\u0637": "\u062a",  # toe -> te
    "\u062d": "\u06c1",  # bari he -> choti he
    "\u0642": "\u06a9",  # qaf -> kaf
    # Arabic yeh, kaf, heh and heh with yeh above, to the forms Urdu writes.
    "\u064a": "\u06cc", "\u0643": "\u06a9", "\u0647": "\u06c1", "\u06c0": "\u06c1",
})
ARABIC = re.compile("[\u0600-\u06ff]")
DIACRITICS = re.compile("[\u064b-\u065f\u0670\u06d6-\u06ed]")
TAG = re.compile(r"<[^>]*>")
VOWELS = set("aeiouyw")
# Hesitations, dropped on both sides as Whisper's English normalizer does: the
# Earnings-22 reference writes every "uh", and no engine is scored on them.
FILLERS = frozenset({"uh", "um", "uhm", "umm", "hmm", "mm", "mhm", "ah", "er", "erm", "eh"})


@functools.cache
def _uroman() -> uroman.Uroman:
    return uroman.Uroman()


def spoken(number: str) -> list[str]:
    """Digits as the words a speaker says: years as years, the rest as cardinals.

    The Earnings-22 reference writes 2021, Q4 and 10%; parakeet writes twenty
    twenty one, q four and ten percent. Spelling the digits out on both sides
    scores the words, not the writing convention.
    """
    value = number.replace(",", "")
    try:
        if re.fullmatch(r"\d+", value):
            n = int(value)
            words = num2words(n, to="year") if len(value) == 4 and 1100 <= n <= 2099 else num2words(n)
        elif re.fullmatch(r"\d*\.\d+", value):
            words = num2words(float(value))
        else:
            return [number]
    except (ValueError, OverflowError):
        return [number]
    return [w for w in re.split(r"[\s\-,]+", words.lower()) if w and w != "and"]


def pieces(text: str) -> list[str]:
    """`text` split into scoring tokens: no tags, split on hyphens, letters and digits only.

    Digits are spelled out (`spoken`), `%` is "percent", and a letter run
    against a digit run (q4) is two tokens.
    """
    text = TAG.sub(" ", unicodedata.normalize("NFKC", text)).replace("%", " percent ")
    text = re.sub(r"(?<=[^\W\d_])(?=\d)|(?<=\d)(?=[^\W\d_])", " ", text)
    out: list[str] = []
    for raw in re.split(r"[\s\-\u2010-\u2015/]+", text):
        raw = raw.strip(".,;:!?\"'()[]")
        for part in (spoken(raw) if re.fullmatch(r"[\d,]*\.?\d+", raw) else [raw]):
            token = re.sub(r"[^\w]", "", DIACRITICS.sub("", part)).replace("_", "").lower()
            if token and token not in FILLERS:
                out.append(token)
    return out


@functools.cache
def romanize(token: str) -> str:
    """`token` in Latin letters: uroman over the folded Urdu letters, Latin as it is."""
    if not ARABIC.search(token):
        return token
    # Ain: Roman Urdu writes a word-initial one as a vowel (aam) and drops the
    # rest (shuru, baad), so alif at the start and nothing elsewhere.
    folded = token.translate(URDU_FOLD)
    folded = folded[:1].replace("\u0639", "\u0627") + folded[1:].replace("\u0639", "")
    latin = _uroman().romanize_string(folded).lower() if folded else ""
    latin = re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", latin))
    # A leading yeh is the consonant y (یہ is "yeh"); uroman writes it as i.
    if token[0] in "\u06cc\u064a" and latin.startswith("i"):
        latin = "y" + latin[1:]
    return latin


def _english(s: str) -> str:
    """A Latin spelling rewritten toward its sound, so Urdu-letter English can meet it."""
    for a, b in (("tion", "shn"), ("sion", "shn"), ("dge", "j"), ("ph", "f"), ("ck", "k"),
                 ("qu", "kw"), ("x", "ks")):
        s = s.replace(a, b)
    s = re.sub(r"ge$", "j", s)
    s = s.replace("ch", "C")
    s = re.sub(r"c(?=[eiy])", "s", s)
    return s.replace("c", "k")


@functools.cache
def key(token: str) -> str:
    """The form two words are compared in; equal keys are the same word (see `near`).

    Romanized, then: tch and ch to one letter, sh, kh and gh kept apart, q to k,
    v to w, every h dropped except a leading one (aspiration, and the silent
    final heh), doubled letters collapsed (uroman writes retroflex ٹ ڈ ڑ as tt
    dd rr). Then the vowels inside go, a leading vowel becomes `a` (a leading w
    or y stays: wo, yeh), and a final vowel run is kept as one of four classes:
    `A` (a), `E` (e, ai, ay, ye), `I` (i, ee, y), `O` (o, u, w). An Urdu word
    ending in a heh after a consonant (کہ, پہ, وہ, یہ), or in ain, writes its final vowel
    with no letter at all, so its class is `*`, which `near` lets match any.
    Digits are kept as they are.
    """
    s = romanize(token)
    # A final ain is a vowel Roman Urdu may or may not write (mauqa, shuru).
    silent = len(token) > 1 and bool(re.search(r"[^\u06c1\u0647][\u06c1\u0647]$|\u0639$", token))
    if silent and s.endswith("h"):
        s = s[:-1]
    if not ARABIC.search(token):
        s = _english(s)
    s = s.replace("tch", "C").replace("ch", "C").replace("sh", "S").replace("kh", "X")
    s = s.replace("gh", "G").replace("q", "k").replace("v", "w")
    s = s[:1] + s[1:].replace("h", "")
    s = re.sub(r"(.)\1+", r"\1", s)
    if not s:
        return "_"
    tail = re.search(r"[aeiouyw]+$", s)
    final = ""
    body = s
    if tail and (tail.start() > 0 or len(tail.group(0)) > 1):
        run = tail.group(0) if tail.start() > 0 else tail.group(0)[1:]
        body = s[: len(s) - len(run)]
        if run.endswith("a"):
            final = "A"
        elif run.endswith("e") or run in ("ai", "ay", "ei", "ey", "ae"):
            final = "E"
        elif run[-1] in "iy":
            final = "I"
        else:
            final = "O"
    head = "a" if body[0] in "aeiou" else body[0]
    rest = "".join(c for c in body[1:] if c not in VOWELS)
    return head + rest + ("*" if silent and not final else final)


def _base(k: str) -> str:
    return k[:-1] if len(k) > 1 and k[-1] in "AEIO*" else k


@dataclass
class Word:
    """One scoring token of a transcript, with the time and confidence of its word."""

    text: str
    t: float
    c: float


def transcript_words(sentences: Iterable[dict[str, Any]]) -> list[Word]:
    """Scoring tokens of `sentences`, each with its word's start and least confidence."""
    grouped: list[tuple[float, str, float]] = []
    for sentence in sentences:
        for k, token in enumerate(sentence["tokens"]):
            c = float(token.get("c", 1.0))
            if k == 0 or re.match(r"\s", token["w"]) or not grouped:
                grouped.append((float(token["t"]), token["w"], c))
            else:
                t, w, least = grouped[-1]
                grouped[-1] = (t, w + token["w"], min(least, c))
    return [Word(p, t, c) for t, w, c in grouped for p in pieces(w)]


def reference_words(truth: dict[str, Any]) -> list[str]:
    return [p for seg in truth["segments"] if "ground_truth" in seg for p in pieces(seg["ground_truth"])]


def near(a: str, b: str) -> bool:
    """Equal keys, a silent final heh against any final vowel, or one letter apart on long keys."""
    if a == b:
        return True
    if a.endswith("*") or b.endswith("*"):
        return _base(a) == _base(b)
    return min(len(a), len(b)) >= 4 and Levenshtein.distance(a, b) <= 1


def _small_align(h: list[str], r: list[str]) -> list[tuple[int | None, int | None]]:
    """Levenshtein alignment of two short key lists with `near` as equality."""
    n, m = len(h), len(r)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1,
                          d[i - 1][j - 1] + (0 if near(h[i - 1], r[j - 1]) else 1))
    out: list[tuple[int | None, int | None]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + (0 if near(h[i - 1], r[j - 1]) else 1):
            out.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            out.append((i - 1, None))
            i -= 1
        else:
            out.append((None, j - 1))
            j -= 1
    return out[::-1]


def align(hyp: list[str], ref: list[str]) -> list[tuple[int | None, int | None]]:
    """(hyp index or None, ref index or None) for every aligned position, in order.

    Exact-key Levenshtein over the whole file first (fast), then each stretch
    between two matched runs again with `near`, which forgives a one-letter key
    difference on long words.
    """
    out: list[tuple[int | None, int | None]] = []
    i0 = j0 = 0

    def redo(i1: int, j1: int) -> None:
        if i1 - i0 == 0 and j1 - j0 == 0:
            return
        if (i1 - i0) * (j1 - j0) > 4_000_000:  # a whole loop against a whole clip: no fuzz
            for k in range(i0, i1):
                out.append((k, None))
            for k in range(j0, j1):
                out.append((None, k))
            return
        out.extend((None if a is None else a + i0, None if b is None else b + j0)
                   for a, b in _small_align(hyp[i0:i1], ref[j0:j1]))

    for op in Levenshtein.opcodes(hyp, ref):
        if op.tag != "equal":
            continue
        redo(op.src_start, op.dest_start)
        out.extend(zip(range(op.src_start, op.src_end), range(op.dest_start, op.dest_end), strict=True))
        i0, j0 = op.src_end, op.dest_end
    redo(len(hyp), len(ref))
    return out


@dataclass
class Score:
    n: int
    sub: int
    miss: int
    ins: int
    correct_hyp: list[bool]  # per hypothesis word
    pairs: list[tuple[int | None, int | None]]

    @property
    def wer(self) -> float:
        return (self.sub + self.miss + self.ins) / self.n


def score(hyp: list[str], ref: list[str], *, compare: str = "key") -> Score:
    if compare == "key":
        hk, rk = [key(w) for w in hyp], [key(w) for w in ref]
    else:
        hk, rk = [romanize(w) for w in hyp], [romanize(w) for w in ref]
    pairs = align(hk, rk) if compare == "key" else _exact(hk, rk)
    sub = miss = ins = 0
    ok = [False] * len(hyp)
    for a, b in pairs:
        if a is None:
            miss += 1
        elif b is None:
            ins += 1
        elif (near(hk[a], rk[b]) if compare == "key" else hk[a] == rk[b]):
            ok[a] = True
        else:
            sub += 1
    return Score(len(ref), sub, miss, ins, ok, pairs)


def _exact(h: list[str], r: list[str]) -> list[tuple[int | None, int | None]]:
    out: list[tuple[int | None, int | None]] = []
    for op in Levenshtein.opcodes(h, r):
        a, b = op.src_end - op.src_start, op.dest_end - op.dest_start
        for k in range(max(a, b)):
            out.append((op.src_start + k if k < a else None, op.dest_start + k if k < b else None))
    return out


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def runs(pattern: str = "*") -> list[tuple[str, str, Path]]:
    """(set, mode-run, path) for every finished transcript whose name matches `pattern`, set order then name."""
    found = []
    for set_name in TRUTHS:
        for p in sorted((RUNS / set_name).glob("*-r[0-9].json")):
            if Path(p.stem).match(pattern):
                found.append((set_name, p.stem, p))
    return found


def is_urdu_script(token: str) -> bool:
    return bool(ARABIC.search(token))


def cmd_one(run: Path, truth_path: Path) -> None:
    truth = load(truth_path)
    ref = reference_words(truth)
    hyp = transcript_words(load(run)["sentences"])
    s = score([w.text for w in hyp], ref)
    print(f"{run}: {len(hyp)} words against {s.n}: wer {s.wer:.1%}, sub {s.sub / s.n:.1%}, "
          f"miss {s.miss / s.n:.1%}, ins {s.ins / s.n:.1%}")


def by_script(s: Score, ref: list[str]) -> dict[str, tuple[int, int]]:
    """(errors, words) over reference words in each script: substitutions and misses."""
    out = {"urdu": [0, 0], "latin": [0, 0]}
    for _, b in s.pairs:
        if b is None:
            continue
        side = "urdu" if is_urdu_script(ref[b]) else "latin"
        out[side][1] += 1
    hyp_ok = s.correct_hyp
    for a, b in s.pairs:
        if b is None:
            continue
        side = "urdu" if is_urdu_script(ref[b]) else "latin"
        if a is None or not hyp_ok[a]:
            out[side][0] += 1
    return {k: (v[0], v[1]) for k, v in out.items()}


def cmd_table(pattern: str = "*") -> None:
    lines = ["| set | run | words out | WER | miss | ins | sub | strict WER | Urdu-ref err | Latin-ref err | loop s |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for set_name, name, path in runs(pattern):
        truth = load(TRUTHS[set_name])
        ref = reference_words(truth)
        doc = load(path)
        hyp = [w.text for w in transcript_words(doc["sentences"])]
        s = score(hyp, ref)
        strict = score(hyp, ref, compare="exact")
        scripts = by_script(s, ref)
        loop_s = sum(u["end"] - u["start"] for u in doc.get("unclear", []) if u["reason"] == "repetition loop")

        def share(k: str, scripts: dict[str, tuple[int, int]] = scripts) -> str:
            e, n = scripts[k]
            return f"{e / n:.0%} of {n}" if n else "-"

        lines.append(
            f"| {set_name} | {name} | {len(hyp)} | {s.wer:.1%} | {s.miss / s.n:.1%} | {s.ins / s.n:.1%} | "
            f"{s.sub / s.n:.1%} | {strict.wer:.1%} | {share('urdu')} | {share('latin')} | {loop_s:.0f} |"
        )
        print(lines[-1], flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a") as fh:
        fh.write("\n## table\n\n" + "\n".join(lines) + "\n")


def cmd_pairs(n: int, seed: int, runs_glob: str) -> None:
    """Cross-script aligned pairs, half the scorer calls the same word and half not.

    The hand check recorded on #184 was drawn with the defaults, from the first
    run of every mode but roman30, the transcripts there were when it was made.
    """
    same: list[tuple[str, str, str]] = []
    differ: list[tuple[str, str, str]] = []
    for set_name, name, path in runs():
        if not Path(name).match(runs_glob) or name.startswith("roman30"):
            continue
        ref = reference_words(load(TRUTHS[set_name]))
        hyp = [w.text for w in transcript_words(load(path)["sentences"])]
        s = score(hyp, ref)
        for a, b in s.pairs:
            if a is None or b is None or is_urdu_script(hyp[a]) == is_urdu_script(ref[b]):
                continue
            (same if s.correct_hyp[a] else differ).append((f"{set_name}/{name}", hyp[a], ref[b]))
    rng = random.Random(seed)
    print(f"cross-script aligned pairs: {len(same)} called same, {len(differ)} called different")
    picked = [("same", p) for p in rng.sample(same, n // 2)] + [("differ", p) for p in rng.sample(differ, n - n // 2)]
    for k, (verdict, (run, h, r)) in enumerate(picked, 1):
        print(f"{k:2d} {verdict:6s} {run:22s} out={h} [{romanize(h)} {key(h)}]  ref={r} [{romanize(r)} {key(r)}]")


CUTS = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95)


def cmd_cutoffs() -> None:
    """Per engine and mode: of tinted words, how many are wrong; of wrong words, how many tinted."""
    pooled: dict[str, list[tuple[float, bool]]] = {}
    for set_name, name, path in runs():
        doc = load(path)
        ref = reference_words(load(TRUTHS[set_name]))
        words = transcript_words(doc["sentences"])
        s = score([w.text for w in words], ref)
        mode = name.rsplit("-", 1)[0]
        pooled.setdefault(f"{doc['engine']}:{mode}:{set_name}", []).extend(
            (w.c, ok) for w, ok in zip(words, s.correct_hyp, strict=True))
    lines = ["| engine:mode:set | words | wrong | " + " | ".join(f"c<{c}" for c in CUTS) + " |",
             "|---|---:|---:|" + "---:|" * len(CUTS)]
    for label, rows in pooled.items():
        n = len(rows)
        wrong = sum(1 for _, ok in rows if not ok)
        cells = []
        for cut in CUTS:
            tinted = [ok for c, ok in rows if c < cut]
            hits = sum(1 for ok in tinted if not ok)
            cells.append(f"{len(tinted) / n:.0%} tinted, {hits / max(1, len(tinted)):.0%} wrong, "
                         f"{hits / max(1, wrong):.0%} caught")
        lines.append(f"| {label} | {n} | {wrong / n:.0%} | " + " | ".join(cells) + " |")
        print(lines[-1], flush=True)
    with OUT.open("a") as fh:
        fh.write("\n## cutoffs\n\n" + "\n".join(lines) + "\n")


def cmd_retry() -> None:
    """The loop retry's recovered words against the reference (#183)."""
    sys.path.insert(0, str(REPO))
    from dsj.asr import Transcription
    from dsj.suno import _loop_runs, _without_loops, is_loop

    lines = ["| set | run | loops before (spans, s) | split runs before (n, s) | loops after (spans, s) | "
             "words recovered | of them correct | WER without retry | WER with retry | ins without | ins with |",
             "|---|---|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for set_name, name, path in runs():
        side = path.with_name(f"{path.stem}.preretry.json")
        if not side.exists():
            continue
        pre = load(side)
        sentences = pre["sentences"]
        single = [(s["start"], s["end"]) for s in sentences if is_loop(str(s["text"]))]
        split = [(sentences[a]["start"], max(x["end"] for x in sentences[a : b + 1]))
                 for a, b in _loop_runs(sentences)]
        without, _ = _without_loops(Transcription(text="", sentences=sentences))
        doc = load(path)
        after = [(u["start"], u["end"]) for u in doc.get("unclear", []) if u["reason"] == "repetition loop"]
        ref = reference_words(load(TRUTHS[set_name]))
        w0 = transcript_words(without.sentences)
        w1 = transcript_words(doc["sentences"])
        s0 = score([w.text for w in w0], ref)
        s1 = score([w.text for w in w1], ref)
        before_keys = {(round(w.t, 3), w.text) for w in w0}
        new = [ok for w, ok in zip(w1, s1.correct_hyp, strict=True) if (round(w.t, 3), w.text) not in before_keys]
        lines.append(
            f"| {set_name} | {name} | {len(single)}, {sum(b - a for a, b in single):.0f} | "
            f"{len(split)}, {sum(b - a for a, b in split):.0f} | {len(after)}, {sum(b - a for a, b in after):.0f} | "
            f"{len(new)} | {sum(new)} ({sum(new) / max(1, len(new)):.0%}) | {s0.wer:.1%} | {s1.wer:.1%} | "
            f"{s0.ins} | {s1.ins} |"
        )
        print(lines[-1], flush=True)
    with OUT.open("a") as fh:
        fh.write("\n## retry\n\n" + "\n".join(lines) + "\n")


def cmd_split() -> None:
    """split_retry.py's replays against the runs they came from: what reading split loops adds."""
    lines = ["| set | run | words recovered | of them correct | WER before | WER after | ins before | ins after |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    for set_name, name, path in runs():
        replay = path.with_name(f"{name}.splitretry.json")
        if not replay.exists():
            continue
        ref = reference_words(load(TRUTHS[set_name]))
        w0 = transcript_words(load(path)["sentences"])
        w1 = transcript_words(load(replay)["sentences"])
        s0 = score([w.text for w in w0], ref)
        s1 = score([w.text for w in w1], ref)
        before = {(round(w.t, 3), w.text) for w in w0}
        new = [ok for w, ok in zip(w1, s1.correct_hyp, strict=True) if (round(w.t, 3), w.text) not in before]
        lines.append(f"| {set_name} | {name} | {len(new)} | {sum(new)} ({sum(new) / max(1, len(new)):.0%}) | "
                     f"{s0.wer:.1%} | {s1.wer:.1%} | {s0.ins} | {s1.ins} |")
        print(lines[-1], flush=True)
    with OUT.open("a") as fh:
        fh.write("\n## split loops read again\n\n" + "\n".join(lines) + "\n")


def cmd_seams() -> None:
    """parakeet's inventions and misses at chunk seams against everywhere else (#198).

    A seam window is a chunk overlap plus 2 s, as scratch/seam_twice.py draws
    it. An invented word is placed by its own start; a missed reference word by
    its reference segment, at a seam when the segment overlaps a window.
    """
    from seam_twice import seams

    for set_name, name, path in runs():
        if not name.startswith("parakeet"):
            continue
        truth = load(TRUTHS[set_name])
        segs = [g for g in truth["segments"] if "ground_truth" in g]
        ref: list[str] = []
        owner: list[int] = []
        for k, g in enumerate(segs):
            got = pieces(g["ground_truth"])
            ref += got
            owner += [k] * len(got)
        words = transcript_words(load(path)["sentences"])
        s = score([w.text for w in words], ref)
        windows = seams(float(truth["duration_s"]))
        seam_s = sum(b - a for a, b in windows)
        rest_s = float(truth["duration_s"]) - seam_s

        def at(t0: float, t1: float, windows: list[tuple[float, float]] = windows) -> bool:
            return any(t0 < b and a < t1 for a, b in windows)

        ins = [words[a].t for a, b in s.pairs if b is None and a is not None]
        miss = [owner[b] for a, b in s.pairs if a is None and b is not None]
        ins_seam = sum(1 for t in ins if at(t, t))
        miss_seam = sum(1 for k in miss if at(segs[k]["start"], segs[k]["end"]))
        print(f"{set_name}/{name}: {len(windows)} seams, {seam_s:.0f} s in them; "
              f"invented {ins_seam} at seams ({ins_seam / seam_s * 3600:.0f}/h), "
              f"{len(ins) - ins_seam} elsewhere ({(len(ins) - ins_seam) / rest_s * 3600:.0f}/h); "
              f"missed {miss_seam} in segments touching a seam, {len(miss) - miss_seam} elsewhere")


def cmd_wall(pattern: str = "*") -> None:
    """Wall time per run from its `.bench.json`, and on the podcast the words in its three gaps (#236).

    The gap count is scratch/real_bench.py's `fixture` measure (#181): words
    starting inside the 10, 30 and 60 s stretches of noise with no speech,
    plus a removed loop's words in proportion to its span inside one.
    """
    sys.path.insert(0, str(REPO))
    from real_bench import measure_fixture

    lines = ["| set | run | wall min | x realtime | words in 10 s gap | 30 s gap | 60 s gap |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for set_name, name, path in runs(pattern):
        bench = path.with_name(f"{name}.bench.json")
        wall = float(load(bench)["wall_s"]) if bench.exists() else None
        duration = float(load(TRUTHS[set_name])["duration_s"])
        gaps = ["-", "-", "-"]
        if set_name == "podcast":
            gaps = [str(n) for n in measure_fixture(path, None).gap_words]
        speed = f"{duration / wall:.2f}" if wall else "-"
        minutes = f"{wall / 60:.1f}" if wall else "-"
        lines.append(f"| {set_name} | {name} | {minutes} | {speed} | {' | '.join(gaps)} |")
        print(lines[-1], flush=True)
    with OUT.open("a") as fh:
        fh.write("\n## wall and gaps\n\n" + "\n".join(lines) + "\n")


def cmd_english(pattern: str, show: int, seed: int) -> None:
    """On the podcast: what each English (Latin-script) reference word came out as (#235).

    Every Latin reference word falls in one bucket by what is aligned to it:
    `english` (matched, written in Latin), `urdu letters` (matched, written in
    Urdu script: the English word transliterated), `urdu word` (not matched,
    an Urdu-script word in its place: translated, or wrong), `wrong latin`
    (not matched, a Latin word in its place) and `missed` (nothing aligned).
    `urdu word` cannot tell a translation from a mishearing, so `--show`
    prints that many of its pairs, drawn at random, for a person to read.
    """
    for set_name, name, path in runs(pattern):
        if set_name != "podcast":
            continue
        ref = reference_words(load(TRUTHS[set_name]))
        hyp = [w.text for w in transcript_words(load(path)["sentences"])]
        s = score(hyp, ref)
        counts = {"english": 0, "urdu letters": 0, "urdu word": 0, "wrong latin": 0, "missed": 0}
        replaced: list[tuple[str, str]] = []
        for a, b in s.pairs:
            if b is None or is_urdu_script(ref[b]):
                continue
            if a is None:
                counts["missed"] += 1
            elif s.correct_hyp[a]:
                counts["urdu letters" if is_urdu_script(hyp[a]) else "english"] += 1
            elif is_urdu_script(hyp[a]):
                counts["urdu word"] += 1
                replaced.append((ref[b], hyp[a]))
            else:
                counts["wrong latin"] += 1
        total = sum(counts.values())
        print(f"{name}: {total} Latin reference words: "
              + ", ".join(f"{k} {v} ({v / total:.0%})" for k, v in counts.items()), flush=True)
        for r, h in random.Random(seed).sample(replaced, min(show, len(replaced))):
            print(f"    ref={r}  out={h} [{romanize(h)}]")


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("table")
    t.add_argument("--runs", default="*", help="which runs, as a name pattern, e.g. 'pakurdu_*'")
    p = sub.add_parser("pairs")
    p.add_argument("--n", type=int, default=50)
    p.add_argument("--seed", type=int, default=184)
    p.add_argument("--runs", default="*-r1", help="which runs to draw from, as a name pattern")
    sub.add_parser("cutoffs")
    sub.add_parser("retry")
    sub.add_parser("seams")
    sub.add_parser("split")
    w = sub.add_parser("wall")
    w.add_argument("--runs", default="*", help="which runs, as a name pattern")
    e = sub.add_parser("english")
    e.add_argument("--runs", default="*", help="which runs, as a name pattern")
    e.add_argument("--show", type=int, default=20, help="Latin words replaced by an Urdu word, to read")
    e.add_argument("--seed", type=int, default=235)
    o = sub.add_parser("one")
    o.add_argument("run", type=Path)
    o.add_argument("truth", type=Path)
    args = parser.parse_args()
    if args.cmd == "table":
        cmd_table(args.runs)
    elif args.cmd == "pairs":
        cmd_pairs(args.n, args.seed, args.runs)
    elif args.cmd == "cutoffs":
        cmd_cutoffs()
    elif args.cmd == "retry":
        cmd_retry()
    elif args.cmd == "seams":
        cmd_seams()
    elif args.cmd == "split":
        cmd_split()
    elif args.cmd == "wall":
        cmd_wall(args.runs)
    elif args.cmd == "english":
        cmd_english(args.runs, args.show, args.seed)
    else:
        cmd_one(args.run, args.truth)
    return 0


if __name__ == "__main__":
    sys.exit(main())

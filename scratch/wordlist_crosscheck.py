#!/usr/bin/env python3
"""Cross-check the shipped bleep word lists against public text (#214).

Two sources, both fetched at a pinned revision into scratch/wordlist_crosscheck/
(ignored by git; nothing from them is committed):

- Roman Urdu: `community-datasets/roman_urdu_hate_speech`, MIT, 10,010 tweets
  labelled Abusive/Offensive or Normal (Coarse_Grained, all three splits).
  Checked against every list's `roman` and `disguised` spellings.
- Gurmukhi: the `text` column of `kdcyberdude/Punjabi_ASR_datasets`, an
  aggregate of Punjabi speech corpora (IndicVoices, Shrutilipi, IndicSUPERB,
  FLEURS, Common Voice, PunjabiSpeech); its two synthetic sets are left out,
  being speech made from text rather than speech written down. Only the text
  column is read, over HTTP with DuckDB, never the 60 GB of audio. Checked
  against pa.toml's Gurmukhi spellings.

For each list spelling: how often it occurs (a phrase as that many words in a
row), and for Roman Urdu how many of those are in tweets labelled abusive.
Then the candidates a list may be missing: words of the text, not in any list,
seen at least MIN_COUNT times, that contain a listed spelling of 4 or more
letters, or are one edit from one (two for spellings of 7 or more letters).
Last, for Roman Urdu, words the lists may lack outright: seen LOPSIDED_MIN+
times, LOPSIDED_SHARE+ of them in abusive tweets, near no listed spelling. A
fluent reader rules on all of these; this only finds them.

Words are compared the way dsj matches them, through dsj.hatao.normalize.

    uv run --with duckdb python scratch/wordlist_crosscheck.py fetch
    uv run python scratch/wordlist_crosscheck.py report
    uv run python scratch/wordlist_crosscheck.py engines <#152's scratch/bleep_recall>

`engines` reads what #152's engines wrote for each spoken listed word and
prints the written forms within 2 edits of that entry's spellings.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dsj import hatao

OUT = Path(__file__).resolve().parent / "wordlist_crosscheck"
HF = "https://huggingface.co"
ROMAN_ID = "community-datasets/roman_urdu_hate_speech"
ROMAN_REV = "d1e9fb2fc4d973306dc2c647b086a9f90244c9a3"
ROMAN_FILES = [f"Coarse_Grained/{split}-00000-of-00001.parquet"
               for split in ("train", "test", "validation")]
PA_ID = "kdcyberdude/Punjabi_ASR_datasets"
PA_REV = "69d9f311344915dafee8fe04de91a3d04ecd2aa6"
MIN_COUNT = 2
LOPSIDED_MIN = 10
# How far either side of a spoken word an engine's written word may sit, in seconds.
ENGINE_TOL_S = 0.25
LOPSIDED_SHARE = 0.85
GURMUKHI = range(0x0A00, 0x0A80)


def fetch() -> None:
    import duckdb

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for name in ROMAN_FILES:
        dest = OUT / name.replace("/", "_")
        if not dest.exists():
            urllib.request.urlretrieve(f"{HF}/datasets/{ROMAN_ID}/resolve/{ROMAN_REV}/{name}", dest)
        table = con.execute(f"select tweet, label from read_parquet('{dest}')").fetchall()
        rows += [{"text": tweet, "abusive": label == 0} for tweet, label in table]
    (OUT / "roman_urdu.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    print(f"roman urdu: {len(rows)} tweets")

    with urllib.request.urlopen(f"{HF}/api/datasets/{PA_ID}/revision/{PA_REV}") as response:
        files = [s["rfilename"] for s in json.load(response)["siblings"]
                 if s["rfilename"].endswith(".parquet") and "_Synth_" not in s["rfilename"]]
    cache = OUT / "punjabi"
    cache.mkdir(exist_ok=True)

    def one(name: str) -> None:
        dest = cache / f"{Path(name).stem}.json"
        if dest.exists():
            return
        url = f"{HF}/datasets/{PA_ID}/resolve/{PA_REV}/{name}"
        got = [r[0] for r in con.cursor().execute(
            f"select text from read_parquet('{url}')").fetchall()]
        dest.write_text(json.dumps([t for t in got if t], ensure_ascii=False), encoding="utf-8")
        print(f"{name}: {len(got)}", flush=True)

    # Four at a time: each file is a few HTTP range reads of its text column.
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(one, files))
    texts: dict[str, list[str]] = {}
    for name in files:
        subset = name.split("/")[1].split("__")[0]
        texts.setdefault(subset, []).extend(
            json.loads((cache / f"{Path(name).stem}.json").read_text(encoding="utf-8")))
    (OUT / "punjabi.json").write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")
    print({k: len(v) for k, v in texts.items()})


def edits(a: str, b: str, limit: int) -> int:
    """Levenshtein distance, or limit + 1 once it is certain to pass `limit`."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        if min(current) > limit:
            return limit + 1
        previous = current
    return previous[-1]


def tokens(text: str) -> list[str]:
    return [k for k in (hatao.normalize(w) for w in text.split()) if k]


def check(name: str, docs: list[tuple[list[str], bool | None]], spellings: dict[str, str],
          ) -> dict:
    """Count every spelling in `docs` and find the candidates the lists miss."""
    vocab: Counter[str] = Counter()
    abusive: Counter[str] = Counter()
    grams: Counter[str] = Counter()
    for words, flag in docs:
        vocab.update(words)
        if flag:
            abusive.update(words)
        for size in (2, 3):
            grams.update(" ".join(words[i:i + size]) for i in range(len(words) - size + 1))
    found = {}
    for key, entry in spellings.items():
        n = grams[key] if " " in key else vocab[key]
        found[key] = {"entry": entry, "count": n,
                      "abusive": abusive[key] if " " not in key else None}
    single = [k for k in spellings if " " not in k and len(k) >= 4]
    candidates = []
    for word, n in vocab.items():
        if n < MIN_COUNT or word in spellings or len(word) < 4:
            continue
        for key in single:
            limit = 2 if len(key) >= 7 else 1
            how = ("contains" if key in word and word != key else
                   "edit" if edits(word, key, limit) <= limit else None)
            if how:
                candidates.append({"word": word, "count": n, "abusive": abusive[word],
                                   "near": key, "entry": spellings[key], "how": how})
                break
    candidates.sort(key=lambda c: -c["count"])
    near = {c["word"] for c in candidates}
    # Words the lists may lack outright: frequent, nearly always in an abusive
    # text, and near no listed spelling. Many are names of people the tweets
    # attack; a reader sorts those out.
    lopsided = sorted(
        ({"word": w, "count": n, "abusive": abusive[w]} for w, n in vocab.items()
         if n >= LOPSIDED_MIN and abusive[w] >= LOPSIDED_SHARE * n
         and w not in spellings and w not in near),
        key=lambda c: -c["count"],
    ) if any(flag for _, flag in docs) else []
    return {"source": name, "documents": len(docs), "word_types": len(vocab),
            "words": sum(vocab.values()), "spellings": found, "candidates": candidates,
            "lopsided": lopsided}


def report() -> None:
    lists = hatao.load_words([hatao._WORDS_DIR / f"{n}.toml" for n in hatao.SHIPPED_LISTS])
    roman = {k: v for k, v in lists.spellings.items()
             if not any(ord(c) > 0x2FF for c in k)}
    gurmukhi = {k: v for k, v in lists.spellings.items()
                if any(ord(c) in GURMUKHI for c in k)}
    rows = json.loads((OUT / "roman_urdu.json").read_text(encoding="utf-8"))
    ru = check(ROMAN_ID, [(tokens(r["text"]), r["abusive"]) for r in rows], roman)
    ru["abusive_documents"] = sum(r["abusive"] for r in rows)
    pa_texts = json.loads((OUT / "punjabi.json").read_text(encoding="utf-8"))
    pa = check(PA_ID, [(tokens(t), None) for texts in pa_texts.values() for t in texts],
               gurmukhi)
    pa["subsets"] = {k: len(v) for k, v in pa_texts.items()}
    (OUT / "report.json").write_text(json.dumps([ru, pa], ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    for r in (ru, pa):
        print(f"\n== {r['source']}: {r['documents']} texts, {r['words']} words, "
              f"{r['word_types']} distinct")
        if "abusive_documents" in r:
            print(f"   {r['abusive_documents']} labelled abusive")
        if "subsets" in r:
            print(f"   {r['subsets']}")
        seen = {k: v for k, v in r["spellings"].items() if v["count"]}
        print(f"   list spellings checked {len(r['spellings'])}, found {len(seen)}, "
              f"never found {len(r['spellings']) - len(seen)}")
        for key, v in sorted(seen.items(), key=lambda kv: -kv[1]["count"]):
            print(f"     {v['count']:5}  abusive {v['abusive']}  {key}  ({v['entry']})")
        print(f"   candidates seen {MIN_COUNT}+ times: {len(r['candidates'])}")
        for c in r["candidates"]:
            print(f"     {c['count']:5}  abusive {c['abusive']}  {c['word']}  "
                  f"{c['how']} {c['near']} ({c['entry']})")
        if r["lopsided"]:
            print(f"   near no listed spelling, seen {LOPSIDED_MIN}+ times, "
                  f"{LOPSIDED_SHARE:.0%}+ in abusive texts: {len(r['lopsided'])}")
        for c in r["lopsided"]:
            print(f"     {c['count']:5}  abusive {c['abusive']}  {c['word']}")


def engines(recall: Path) -> None:
    """What each engine wrote where a listed word was spoken (#152's audio).

    `recall` is #152's scratch/bleep_recall/: audio/manifest.json names every
    spoken unit and where it sits, transcripts/<engine>/<set>.json is what the
    engine wrote. A written word not on the lists, within 2 edits of a spelling
    of the entry that was spoken, is printed with how often it occurs in the
    Roman Urdu tweets: a spelling a recogniser really writes, and people too.
    """
    lists = hatao.load_words([hatao._WORDS_DIR / f"{n}.toml" for n in hatao.SHIPPED_LISTS])
    by_entry: dict[str, list[str]] = {}
    for key, entry in lists.spellings.items():
        by_entry.setdefault(entry.split(":", 1)[1], []).append(key.replace(" ", ""))
    tweets: Counter[str] = Counter()
    abusive: Counter[str] = Counter()
    for row in json.loads((OUT / "roman_urdu.json").read_text(encoding="utf-8")):
        words = tokens(row["text"])
        tweets.update(words)
        if row["abusive"]:
            abusive.update(words)
    manifest = json.loads((recall / "audio" / "manifest.json").read_text(encoding="utf-8"))
    seen: Counter[tuple[str, str, str, str]] = Counter()
    for engine_dir in sorted((recall / "transcripts").iterdir()):
        for group in manifest["sets"]:
            path = engine_dir / f"{group['set']}.json"
            if not path.exists():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            written = [(float(t["t"]), float(t.get("e", t["t"])), hatao.normalize(str(t["w"])))
                       for sent in payload["sentences"] for t in sent["tokens"]]
            for unit in group["units"]:
                lo, hi = unit["target"][0] - ENGINE_TOL_S, unit["target"][1] + ENGINE_TOL_S
                here = "".join(w for t, e, w in written if t < hi and max(e, t + 0.001) > lo)
                name = unit["entry"].split(":", 1)[1]
                if not here or len(here) < 4 or here in lists.spellings:
                    continue
                near = min(by_entry[name], key=lambda x: edits(here, x, 9))
                if edits(here, near, 2) <= 2:
                    seen[(engine_dir.name, unit["entry"], here, near)] += 1
    print("engine, entry spoken, written (pieces joined), nearest listed, distance, "
          "times, in tweets (abusive)")
    for (engine, entry, here, near), n in sorted(seen.items()):
        print(f"  {engine:10} {entry:16} {here:14} {near:14} {edits(here, near, 2)}  {n}  "
              f"{tweets[here]} ({abusive[here]})")


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("step", choices=["fetch", "report", "engines"])
    parser.add_argument("recall", nargs="?", type=Path,
                        help="for `engines`: #152's scratch/bleep_recall/ directory")
    args = parser.parse_args()
    if args.step == "fetch":
        fetch()
    elif args.step == "report":
        report()
    else:
        engines(args.recall)


if __name__ == "__main__":
    main()

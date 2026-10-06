#!/usr/bin/env python3
"""Convert #235's two Urdu fine-tunes of whisper-large-v3-turbo to MLX, into scratch/models/<name>.

    uv run --with transformers --with peft --with accelerate \
        python scratch/accuracy/convert_finetunes.py {kingabzpro,pakurdu}
    uv run python scratch/accuracy/convert_finetunes.py heads scratch/models/<name>

- `kingabzpro`: `kingabzpro/whisper-large-v3-turbo-urdu`, a full fine-tune,
  converted as it is.
- `pakurdu`: `KhiredNetworks/PakUrdu-Conversational-ASR`, a LoRA (r=16) on
  `openai/whisper-large-v3-turbo` at the revision its card pins. Merged into
  that base with peft's `merge_and_unload` (float32), saved, then converted.

Conversion is mlx-examples' whisper/convert.py at CONVERT_SHA, fetched into
scratch/models/vendor/ (not tracked: it is Apple's script, used unchanged),
at float16. Two things it does not do, done here after it:

1. It writes `model.safetensors`; mlx-whisper 0.4.3's `load_models.load_model`
   reads `weights.safetensors` (or `weights.npz`), so the file is renamed.
2. Converted from a Hugging Face folder it has no alignment heads, so the model
   falls back to every head in the last half of the decoder, and word times
   (which dsj's silence rule and hatao read) come from the wrong heads. The
   heads of `mlx-community/whisper-large-v3-turbo` are copied in instead:
   both fine-tunes keep turbo's architecture, and in mlx-whisper the heads are
   an array stored beside the weights (`alignment_heads`), which
   `model.update` loads like any other.

Downloads land in scratch/models/dl/<repo> (`local_dir`, not the shared
~/.cache/huggingface), so deleting them later touches nothing else. Every
model load first waits for no `dsj suno` running and 30% memory free.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

from run import MIN_FREE_PCT, busy, free_pct  # noqa: E402

MODELS = REPO / "scratch" / "models"
DL = MODELS / "dl"
CONVERT_SHA = "e52c128d113f10546f0fa391f87edcc58d3880cb"
CONVERT = MODELS / "vendor" / f"convert-{CONVERT_SHA[:7]}.py"
TURBO_MLX = "mlx-community/whisper-large-v3-turbo"

KINGABZPRO = ("kingabzpro/whisper-large-v3-turbo-urdu", "62345c2e034f460f324be37033dc4bc4e694152b")
TURBO_HF = ("openai/whisper-large-v3-turbo", "41f01f3fe87f28c78e2fbf8b568835947dd65ed9")
PAKURDU = ("KhiredNetworks/PakUrdu-Conversational-ASR", "6bceff558eab82e5aa2c95aee63c6b03f164fcc6")
WEIGHTS_ONLY = ["*.json", "model.safetensors", "*.txt"]


def wait_turn() -> None:
    while busy():
        print("  a dsj suno is running, waiting", flush=True)
        time.sleep(60)
    while (pct := free_pct()) < MIN_FREE_PCT:
        print(f"  {pct}% memory free, waiting for {MIN_FREE_PCT}%", flush=True)
        time.sleep(60)


def fetch(repo: str, revision: str, patterns: list[str]) -> Path:
    from huggingface_hub import snapshot_download

    target = DL / repo.replace("/", "--")
    snapshot_download(repo_id=repo, revision=revision, local_dir=target, allow_patterns=patterns)
    return target


def convert(source: Path, name: str) -> Path:
    if not CONVERT.exists():
        CONVERT.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://raw.githubusercontent.com/ml-explore/mlx-examples/{CONVERT_SHA}/whisper/convert.py"
        with urllib.request.urlopen(url) as response:
            CONVERT.write_bytes(response.read())
    out = MODELS / name
    wait_turn()
    subprocess.run([sys.executable, str(CONVERT), "--torch-name-or-path", str(source),
                    "--mlx-path", str(out), "--dtype", "float16"], check=True)
    (out / "model.safetensors").rename(out / "weights.safetensors")
    heads(out)
    return out


def heads(folder: Path) -> None:
    """Copy turbo's alignment heads into `folder`'s weights, and say what was there before."""
    import mlx.core as mx
    from huggingface_hub import snapshot_download

    turbo = Path(snapshot_download(repo_id=TURBO_MLX, allow_patterns=["weights.safetensors"]))
    wanted = mx.load(str(turbo / "weights.safetensors"))["alignment_heads"]
    path = folder / "weights.safetensors"
    weights = mx.load(str(path))
    before = weights.get("alignment_heads")
    print(f"{folder.name}: alignment heads {before.tolist() if before is not None else None} "
          f"-> {wanted.tolist()}", flush=True)
    weights["alignment_heads"] = wanted
    # mx.load maps the file lazily: saving over it unevaluated wrote zeros
    # (observed on the first conversion). Evaluate, write beside, then swap.
    mx.eval(weights)
    tmp = path.with_suffix(".tmp.safetensors")
    mx.save_safetensors(str(tmp), weights)
    tmp.replace(path)


def merge_pakurdu() -> Path:
    import torch
    from peft import PeftModel
    from transformers import WhisperForConditionalGeneration

    base_dir = fetch(*TURBO_HF, WEIGHTS_ONLY)
    adapter_dir = fetch(*PAKURDU, ["*.json", "adapter_model.safetensors"])
    wait_turn()
    model = WhisperForConditionalGeneration.from_pretrained(base_dir, dtype=torch.float32)
    merged = PeftModel.from_pretrained(model, adapter_dir).merge_and_unload()
    out = DL / "pakurdu-merged"
    merged.save_pretrained(out, safe_serialization=True, max_shard_size="10GB")
    meta = {"base": TURBO_HF, "adapter": PAKURDU, "dtype": "float32"}
    (out / "merged_from.json").write_text(json.dumps(meta, indent=2) + "\n")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("what", choices=["kingabzpro", "pakurdu", "heads"])
    parser.add_argument("folder", nargs="?", type=Path, help="for `heads`: a converted model folder")
    args = parser.parse_args()
    if args.what == "heads":
        heads(args.folder)
    elif args.what == "kingabzpro":
        convert(fetch(*KINGABZPRO, WEIGHTS_ONLY), "kingabzpro")
    else:
        convert(merge_pakurdu(), "pakurdu")
    return 0


if __name__ == "__main__":
    sys.exit(main())

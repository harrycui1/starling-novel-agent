"""Snapshot recorded runs or compare two prompt-version reports; no model calls."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eval.metrics import report

parser = argparse.ArgumentParser()
parser.add_argument("--version-id", type=int)
parser.add_argument("--output", type=Path)
parser.add_argument("--compare", nargs=2, type=Path)
args = parser.parse_args()
if args.compare:
    before, after = [json.loads(p.read_text()) for p in args.compare]
    result = {"before_prompts": before["prompt_versions"], "after_prompts": after["prompt_versions"], "delta": {k: after[k] - v for k, v in before.items() if k != "version_id" and isinstance(v, (float, int)) and isinstance(after.get(k), (float, int))}}
elif args.version_id:
    result = report(args.version_id)
else:
    parser.error("请指定 --version-id 或 --compare")
text = json.dumps(result, ensure_ascii=False, indent=2)
if args.output:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text)
print(text)

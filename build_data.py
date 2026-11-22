"""raw.json (то, что собрал scrape.py) -> docs/data.json со сборками для каждого SBC."""
import json
import sys
from pathlib import Path

from solver import solve

root = Path(__file__).parent
raw = json.loads((root / "raw.json").read_text(encoding="utf-8"))

out = {"updated": raw["updated"], "source": raw.get("source", ""), "platforms": [], "sbcs": []}
for key, block in raw["platforms"].items():
    if block and block.get("cards"):
        out["platforms"].append(key)

for s in raw["sbcs"]:
    item = {k: s.get(k) for k in ("id", "name", "score", "min_rating", "url", "image", "expires", "notes")}
    item["builds"] = {}
    for key in out["platforms"]:
        cards, mr = raw["platforms"][key]["cards"], s.get("min_rating") or 0
        item["builds"][key] = {
            "cheap": solve(cards, s["score"], mr, "cheap"),
            "optimal": solve(cards, s["score"], mr, "optimal"),
            "fast": solve(cards, s["score"], mr, "fast"),
        }
    out["sbcs"].append(item)

(root / "docs").mkdir(exist_ok=True)
(root / "docs" / "data.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"SBC: {len(out['sbcs'])}, платформы: {out['platforms']}", file=sys.stderr)

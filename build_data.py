"""raw.json (то, что собрал scrape.py) -> docs/data.json со сборками для каждого SBC.

Цены для ПК: если сборщик не смог получить таблицу цен для ПК, но у SBC есть
две цены на странице futmind (консоль и ПК), сборка для ПК считается по
консольной с поправочным коэффициентом (цена ПК / цена консоли этого SBC).
Такие сборки помечаются estimate=True, и на странице показываются как оценка.
"""
import json
import sys
from pathlib import Path

from solver import solve

root = Path(__file__).parent
raw = json.loads((root / "raw.json").read_text(encoding="utf-8"))

out = {"updated": raw["updated"], "platforms": [], "estimates": [], "sbcs": []}
for key, block in raw["platforms"].items():
    if block and block.get("cards"):
        out["platforms"].append(key)


def scaled(build, ratio):
    """Копия сборки с ценами, умноженными на ratio."""
    if not build:
        return None
    lines = [dict(l, price=round(l["price"] * ratio)) for l in build["lines"]]
    return dict(build, lines=lines, cost=sum(l["price"] * l["qty"] for l in lines), estimate=True)


def round50(build):
    """Округляет цену каждой карты до 50 монет и пересчитывает итог."""
    if not build:
        return None
    lines = [dict(l, price=max(50, int(l["price"] / 50 + 0.5) * 50)) for l in build["lines"]]
    return dict(build, lines=lines, cost=sum(l["price"] * l["qty"] for l in lines))


# общий коэффициент цены ПК к консоли: медиана по SBC, где есть обе цены (для SBC, где цена ПК не прочиталась)
ratios = sorted(s["pc_total"] / s["console_total"] for s in raw["sbcs"] if s.get("console_total") and s.get("pc_total"))
GLOBAL_RATIO = ratios[len(ratios) // 2] if ratios else 1.0


def player_view(pl):
    """Игрок для страницы: чистое имя, топ-10 по нации, лиге и клубу."""
    if not pl:
        return None
    pl = dict(pl)
    pl["name"] = (pl.get("name") or "").split(" - ")[0].strip()
    pl["top"] = {}
    for kind in ("nation", "league", "club"):
        fid = pl.get(kind + "_id")
        pl["top"][kind] = [
            {k: g.get(k) for k in ("id", "name", "rating", "position", "card_image")}
            for g in raw.get("lists", {}).get(f"{kind}:{fid}", [])[:10]
        ]
    return pl


for s in raw["sbcs"]:
    item = {k: s.get(k) for k in ("id", "name", "score", "min_rating", "image", "expires", "notes")}
    rw = s.get("reward") or {"kind": "pack"}
    item["reward"] = {"kind": rw.get("kind", "pack"), "player": player_view(raw.get("players", {}).get(str(rw.get("player_id"))))}
    item["builds"] = {}
    for key in out["platforms"]:
        cards, mr = raw["platforms"][key]["cards"], s.get("min_rating") or 0
        item["builds"][key] = {
            "cheap": solve(cards, s["score"], mr, "cheap"),
            "optimal": solve(cards, s["score"], mr, "optimal"),
            "fast": solve(cards, s["score"], mr, "fast"),
        }
    if "pc" not in out["platforms"] and "console" in out["platforms"]:
        con, pc = s.get("console_total"), s.get("pc_total")
        base = item["builds"]["console"]
        r = pc / con if con and pc else GLOBAL_RATIO
        item["builds"]["pc"] = {m: scaled(b, r) for m, b in base.items()}
    for per_platform in item["builds"].values():
        for key, b in (per_platform or {}).items():
            per_platform[key] = round50(b)
    out["sbcs"].append(item)

if "pc" not in out["platforms"] and any(s["builds"].get("pc") for s in out["sbcs"]):
    out["platforms"].append("pc")
    out["estimates"].append("pc")

(root / "docs").mkdir(exist_ok=True)
(root / "docs" / "data.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"SBC: {len(out['sbcs'])}, платформы: {out['platforms']}, оценки: {out['estimates']}", file=sys.stderr)

"""players_db.json (+ игроки-награды) -> docs/players.json для Squad Builder."""
import json
import sys
from datetime import datetime, timezone

from playerdb import all_players, club_names, is_special, root

MIN_RATING = 65  # серебро и выше
players = all_players()
try:
    manual = json.loads((root / "names.json").read_text(encoding="utf-8"))
except Exception:
    manual = {}

names = {"clubs": {**manual.get("clubs", {}), **club_names()}, "leagues": dict(manual.get("leagues", {})), "nations": dict(manual.get("nations", {}))}
rows = []
for p in players.values():
    if not p.get("rating") or p["rating"] < MIN_RATING or not p.get("position"):
        continue
    if not (p.get("club_id") and p.get("league_id") and p.get("nation_id")):
        continue
    for kind, key in (("clubs", "club"), ("leagues", "league"), ("nations", "nation")):
        if p.get(key) and kind != "clubs" and str(p[kind[:-1] + "_id"]) not in names[kind]:
            names[kind][str(p[kind[:-1] + "_id"])] = p[key]
    rows.append([int(p["id"]), p["name"], p["rating"], p["position"], 1 if is_special(p.get("rarity")) else 0,
                 p["club_id"], p["league_id"], p["nation_id"], p.get("rarity") or "", p.get("slug") or "", p.get("pc") or 0])
rows.sort(key=lambda r: -r[2])
out = {"updated": datetime.now(timezone.utc).isoformat(timespec="minutes"), **names, "p": rows}
(root / "docs").mkdir(exist_ok=True)
(root / "docs" / "players.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print(f"игроков для Squad Builder: {len(rows)}", file=sys.stderr)

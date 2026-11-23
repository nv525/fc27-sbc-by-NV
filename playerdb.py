"""База игроков: players_db.json (копится scrape_players.py) + игроки-награды из raw.json."""
import json
from pathlib import Path

root = Path(__file__).parent
SLIM = ("id", "slug", "name", "rating", "position", "rarity", "club_id", "league_id", "nation_id", "club", "league", "nation", "pc")
PLAIN = {"common", "rare", "gold", "silver", "bronze", "rare gold", "rare silver", "rare bronze", ""}


def load_db():
    p = root / "players_db.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"players": {}, "queue": [], "queue_at": None}


def all_players():
    """id -> запись игрока: из базы и из карточек-наград."""
    out = dict(load_db().get("players", {}))
    try:
        raw = json.loads((root / "raw.json").read_text(encoding="utf-8"))
        for k, v in raw.get("players", {}).items():
            out.setdefault(k, {key: v.get(key) for key in SLIM})
    except Exception:
        pass
    return out


def club_names():
    try:
        return json.loads((root / "club_names.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def is_special(rarity):
    return (rarity or "").strip().lower() not in PLAIN

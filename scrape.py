"""Сборщик данных с futmind.com -> raw.json.

Нужны: pip install playwright beautifulsoup4 && playwright install chromium
Запуск: python scrape.py && python build_data.py

Внимание: разметку сайта я видел только в виде текста, поэтому селекторы нужно
проверить при первом запуске. Если что-то не находится, скрипт пишет понятную
ошибку и не затирает старый raw.json. Ходите на сайт редко (раз в 30-60 минут)
и прочитайте их условия использования: https://futmind.com/tos
"""
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE = "https://futmind.com"
OUT = Path(__file__).parent / "raw.json"
NUM = lambda s: int(re.sub(r"[^\d]", "", s))


def log(*a):
    print(*a, file=sys.stderr)


def set_platform(page, platform):
    """Переключает «Prices for PS / Xbox» <-> PC на странице, если переключатель есть."""
    label = "PC" if platform == "pc" else "PS / Xbox"
    try:
        if page.get_by_text(f"Prices for {label}").count():
            return True
        page.get_by_text(re.compile(r"Prices for (PS|PC)")).first.click(timeout=3000)
        page.get_by_text(label, exact=True).first.click(timeout=3000)
        page.wait_for_timeout(1500)
        return page.get_by_text(f"Prices for {label}").count() > 0
    except Exception as e:  # переключателя нет или он выглядит иначе
        log(f"  платформа {platform}: переключить не удалось ({e.__class__.__name__})")
        return False


def read_cards(page):
    """Таблица «карта -> цена -> очки» со страницы Cheapest Item Score."""
    try:
        page.get_by_text(re.compile(r"Show all \d+")).first.click(timeout=3000)
        page.wait_for_timeout(800)
    except Exception:
        log("  кнопка «Show all» не найдена, беру что показано")
    soup = BeautifulSoup(page.content(), "html.parser")
    cards = []
    for tr in soup.select("table tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(cells) < 3:
            continue
        m = re.match(r"(\d{2})\s+(.+)", cells[0])
        if not m or not re.search(r"\d", cells[1]) or not re.search(r"\d", cells[2]):
            continue
        cards.append({
            "rating": int(m.group(1)), "rarity": m.group(2).strip(),
            "price": NUM(cells[1]), "score": NUM(cells[2]),
        })
    return cards


def read_sbc_list(page):
    page.goto(f"{BASE}/squad-building-challenges", wait_until="networkidle")
    html = page.content()
    found = {}
    for m in re.finditer(r'/squad-building-challenges/(\d+)/([^"\'#?\s<]+)', html):
        found.setdefault(int(m.group(1)), m.group(2))
    return found


DETAIL_STATS = [
    "Acceleration", "Sprint Speed", "Agility", "Balance", "Reactions", "Ball Control", "Dribbling", "Composure",
    "Attacking Position", "Finishing", "Shot Power", "Long Shots", "Volleys", "Penalties",
    "Interceptions", "Heading Accuracy", "Defensive Awareness", "Standing Tackle", "Sliding Tackle",
    "Vision", "Crossing", "FK Accuracy", "Short Pass", "Long Pass", "Curve",
    "Jumping", "Stamina", "Strength", "Aggression",
]
# на сайте у части характеристик сокращённые названия
ALIASES = {
    "Acceleration": ["Acceleration", "Accel."], "Sprint Speed": ["Sprint Speed", "Sprint Spd."],
    "Attacking Position": ["Att. Position", "Attacking Position", "Att. Pos."],
    "Heading Accuracy": ["Heading Acc.", "Heading Accuracy"],
    "Defensive Awareness": ["Def. Aware", "Def. Awareness", "Defensive Awareness"],
    "Standing Tackle": ["Stand Tackle", "Standing Tackle"], "Sliding Tackle": ["Slide Tackle", "Sliding Tackle"],
    "FK Accuracy": ["FK Acc.", "FK Accuracy", "Free Kick Accuracy"],
    "Short Pass": ["Short Pass", "Short Passing"], "Long Pass": ["Long Pass", "Long Passing"],
    "Ball Control": ["Ball Control", "Ball Ctrl."],
}
GROUP_NAMES = [("pac", "Pace"), ("sho", "Shooting"), ("pas", "Passing"), ("dri", "Dribbling"), ("def", "Defending"), ("phy", "Physicality")]
POSITIONS = ["GK", "CB", "LB", "RB", "LWB", "RWB", "CDM", "CM", "CAM", "LM", "RM", "LW", "RW", "CF", "ST"]
PLAYER_V = 4  # версия разбора карточки игрока: у старых записей из кэша данные перечитываются


def logo_name(soup, folder):
    """Название клуба/лиги/нации из подписи (alt) его логотипа на странице игрока."""
    for img in soup.find_all("img"):
        src = unquote((img.get("src") or "") + " " + (img.get("srcset") or ""))
        if re.search(r"/" + folder + r"/\d+\.png", src):
            nm = re.sub(r"\s+(logo|badge|flag|crest)$", "", (img.get("alt") or img.get("title") or "").strip(), flags=re.I)
            if nm and nm.lower() not in ("club", "league", "nation", "country"):
                return nm
    return None


CLUB_NAMES = Path(__file__).parent / "club_names.json"
EA = "https://www.ea.com/en/games/ea-sports-fc/ratings/player-ratings"


def load_club_names():
    try:
        return json.loads(CLUB_NAMES.read_text(encoding="utf-8"))
    except Exception:
        return {}


def api_club_name(cid):
    """Название клуба по id через публичный список рейтингов EA (проверяем, что id совпал)."""
    for param in ("team", "teams"):
        try:
            req = Request(f"https://drop-api.ea.com/rating/ea-sports-fc?locale=en&limit=5&offset=0&{param}={cid}",
                          headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            data = json.loads(urlopen(req, timeout=20).read().decode("utf-8"))
        except Exception:
            continue
        for it in data.get("items", []):
            t = it.get("team") or {}
            if str(t.get("id")) == str(cid) and t.get("label"):
                return t["label"]
    return None


def resolve_club_names(page, players, names, limit=40):
    """Названия клубов: futmind показывает клуб только логотипом, поэтому берём название со страницы
    игрока на ea.com (поле Team) и связываем с id по логотипу клуба на той же странице (…/l<id>.png).
    Сохраняем в club_names.json: каждый клуб достаточно узнать один раз."""
    tried, done = {}, 0
    for cid in sorted({str(p["club_id"]) for p in players if p.get("club_id")} - set(names))[:150]:
        nm = api_club_name(cid)
        if nm:
            names[cid] = nm
            done += 1
        time.sleep(0.3)
    log(f"  клубы: названий известно {len(names)}")
    # сначала базовые карточки (их клуб совпадает с клубом на ea.com), потом остальные
    ordered = sorted((p for p in players if p.get("club_id") and p.get("id") and p.get("slug")),
                     key=lambda p: int(p["id"]) >= (1 << 24))
    for p in ordered:
        cid = str(p["club_id"])
        if cid in names or tried.get(cid, 0) >= 3 or done >= limit:
            continue
        tried[cid] = tried.get(cid, 0) + 1
        pid = int(p["id"])
        base = pid & 0xFFFFFF if pid >= (1 << 24) else pid
        try:
            page.goto(f"{EA}/{p['slug']}/{base}", wait_until="networkidle")
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")
            text = soup.get_text("\n", strip=True)
            m = re.search(r"\nTeam\s*\n([^\n]{2,40})\n", text)
            crest = re.search(r"/l(\d+)\.png", unquote(html))
            if m and crest:
                names[crest.group(1)] = m.group(1).strip()
                done += 1
        except Exception as e:
            log(f"  клуб {cid}: {e.__class__.__name__}")
        time.sleep(1)
    if done:
        CLUB_NAMES.write_text(json.dumps(names, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return names


def clean_svg(svg):
    """Встроенная иконка: без скриптов и обработчиков событий."""
    out = re.sub(r"<script.*?</script>", "", str(svg), flags=re.S | re.I)
    out = re.sub(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*')", "", out, flags=re.I)
    return out if len(out) <= 6000 else None


def ps_info(a, slug):
    """Иконка PlayStyle со страницы и признак золотого PlayStyle+."""
    icon = None
    img = a.find("img")
    if img and (img.get("src") or img.get("data-src")):
        src = img.get("src") or img.get("data-src")
        q = parse_qs(urlparse(src).query).get("url")
        src = unquote(q[0]) if q else src
        icon = {"src": src if src.startswith("http") else BASE + src}
    elif a.find("svg"):
        svg = clean_svg(a.find("svg"))
        icon = {"svg": svg} if svg else None
    blob = " ".join(str(v) for el in [a] + a.find_all(True) for k, v in el.attrs.items() if k != "href")
    blob += " " + a.get_text(" ") + " " + (icon.get("src", "") if icon else "")
    plus = bool(re.search(r"plus|gold|\+", blob, re.I))
    return {"slug": slug, "plus": plus, "icon": icon}


def read_player(page, pid, slug):
    """Карточка игрока со страницы игрока. Каждое поле необязательное: чего нет, того нет."""
    page.goto(f"{BASE}/players/{pid}/{slug}", wait_until="networkidle")
    html = page.content()
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    one = lambda pat: (re.search(pat, text) or [None, None])[1]
    pl = {"v": PLAYER_V, "id": pid, "slug": slug, "card_image": f"https://card-image.futmind.com/en/27/{pid}.png"}
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    tm = re.match(r"(.+?)\s+(\d{2})\s+(.+?)\s*\|", title)
    h1 = soup.find("h1")
    raw_name = (tm.group(1) if tm else (h1.get_text(" ", strip=True) if h1 else slug.replace("-", " ").title()))
    pl["name"] = raw_name.split(" - ")[0].strip()
    pl["rating"] = int(tm.group(2)) if tm else (int(one(r"\b(\d{2})\s*\n?\s*(?:" + "|".join(POSITIONS) + r")\b") or 0) or None)
    pl["position"] = one(r"\b\d{2}\s*\n\s*(" + "|".join(POSITIONS) + r")\b") or one(r"\b(" + "|".join(POSITIONS) + r")\b")
    # шесть основных характеристик: строка заголовков PAC SHO ..., следом строка чисел
    row = re.search(r"PAC\s+SHO\s+PAS\s+DRI\s+DEF\s+PHY\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})", text)
    for i, (key, group) in enumerate(GROUP_NAMES):
        v = row.group(i + 1) if row else one(r"(?<![A-Za-z])" + group + r"\s*\n?\s*(\d{2})(?!\d)")
        if not v:
            v = one(key.upper() + r"\s*\n?\s*(\d{2})")
        pl[key] = int(v) if v else None
    pl["weak_foot"] = one(r"Weak [Ff]oot\s*\n?\s*(\d)")
    pl["skill_moves"] = one(r"Skill [Mm]oves\s*\n?\s*(\d)")
    pl["foot"] = one(r"(?:Preferred [Ff]oot|Foot)\s*\n?\s*(Left|Right)")
    pl["height"] = one(r"(\d{3})\s*cm")
    pl["rarity"] = one(r"Rarity\s*\n?\s*(.+)") or (tm.group(3) if tm else None)
    detail = {}
    for st in DETAIL_STATS:
        for label in ALIASES.get(st, [st]):
            hits = re.findall(r"(?<![A-Za-z])" + re.escape(label) + r"\s*\n?\s*(\d{1,2})(?!\d)", text)
            if hits:
                detail[st] = int(hits[-1])  # у «Dribbling» последнее вхождение — подробная характеристика
                break
    pl["detail"] = detail
    pos = {}
    for p_ in POSITIONS:
        m = re.search(r"(?<![A-Za-z])" + p_ + r"\s*\n?\s*(\d{2})(?!\d)", text)
        if m:
            pos[p_] = int(m.group(1))
    pl["positions"] = pos
    # PlayStyles: ссылки вида /playstyles/20/technical; иконку берём из самой ссылки как на сайте
    ps = []
    for a_ in soup.find_all("a", href=True):
        m = re.search(r"/playstyles/\d+/([^/?#]+)", a_["href"])
        if m and not any(x["slug"] == m.group(1) for x in ps):
            ps.append(ps_info(a_, m.group(1)))
    pl["playstyles"] = ps
    pl["league"] = one(r"League\s*\n?\s*(.+)")
    pl["nation"] = one(r"(?:Nation|Country/Region)\s*\n?\s*(.+)")
    pl["club"] = logo_name(soup, "clubs")
    pl["league"] = pl["league"] or logo_name(soup, "leagues")
    pl["nation"] = pl["nation"] or logo_name(soup, "nations")
    for key, folder in (("club_id", "clubs"), ("league_id", "leagues"), ("nation_id", "nations")):
        m = re.search(r"fifa2027(?:%2F|/)" + folder + r"(?:%2F|/)(\d+)\.png", html)
        pl[key] = int(m.group(1)) if m else None
    for key, folder in (("club_logo", "clubs"), ("league_logo", "leagues"), ("nation_logo", "nations")):
        idk = key.replace("_logo", "_id")
        pl[key] = f"{BASE}/images/fifa2027/{folder}/{pl[idk]}.png" if pl.get(idk) else None
    return pl


def reward_kind(soup, name):
    """Игрок, пик или пак. По ссылкам награды на странице SBC."""
    hrefs = [a["href"] for a in soup.find_all("a", href=True)]
    desc = soup.find("meta", attrs={"name": "description"})
    blob = (name + " " + (desc["content"] if desc and desc.has_attr("content") else "")).lower()
    pm = next((re.search(r"/players/(\d+)/([^/?#]+)", h) for h in hrefs if re.search(r"/players/\d+/", h)), None)
    if "player pick" in blob or " pick" in blob:
        return "pick", None
    if pm:
        return "player", (int(pm.group(1)), pm.group(2))
    if any("/pack/" in h for h in hrefs):
        return "pack", None
    return "pack", None


def read_sbc(page, sbc_id, slug):
    url = f"{BASE}/squad-building-challenges/{sbc_id}/{slug}"
    page.goto(url, wait_until="networkidle")
    soup = BeautifulSoup(page.content(), "html.parser")
    text = soup.get_text("\n", strip=True)
    m = re.search(r"Score required\s*([\d,]+)", text)
    if not m:  # не Streamlined (пазлы, челленджи) — пропускаем
        return None
    title = soup.title.get_text() if soup.title else slug
    name = re.sub(r"\s*-\s*SBC\s*\|.*$", "", title).strip()
    mr = re.search(r"OVR Min:\s*(\d+)", text)
    # дополнительные условия вида «Players from the same Club Min: 2» (строго по шаблону, без мусора)
    notes = [l for l in text.split("\n")
             if re.fullmatch(r"[A-Za-z' ]{3,40}(?:Min|Max):\s*\d+", l) and not l.startswith("OVR")]
    # два числа перед «Rewards»: цена SBC на консоли и на ПК по данным сайта
    tot = re.search(r"([\d,]{3,})\s+([\d,]{3,})\s+Rewards", text)
    ex = re.search(r"Expires In\s*\n?(.+)", text)
    kind, pl = reward_kind(soup, name)
    return {
        "reward": {"kind": kind, "player_id": pl[0] if pl else None, "player_slug": pl[1] if pl else None},
        "id": sbc_id, "name": name, "score": NUM(m.group(1)),
        "min_rating": int(mr.group(1)) if mr else 0,
        "notes": notes, "expires": ex.group(1).strip() if ex else None,
        "console_total": NUM(tot.group(1)) if tot else None,
        "pc_total": NUM(tot.group(2)) if tot else None,
        "url": url, "image": f"{BASE}/image-generator/sbc/{sbc_id}.png",
    }


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(locale="en-US")

        platforms = {}
        for platform in ("console", "pc"):
            page.goto(f"{BASE}/squad-building-challenges/cheapest-item-score", wait_until="networkidle")
            if not set_platform(page, "pc" if platform == "pc" else "console"):
                platforms[platform] = None
                continue
            cards = read_cards(page)
            log(f"{platform}: карт {len(cards)}")
            platforms[platform] = {"cards": cards} if cards else None

        if not platforms.get("console"):
            sys.exit("Не удалось прочитать таблицу цен (console). raw.json не тронут.")

        # когда SBC впервые увидели и в каком порядке он стоит на сайте (id у futmind не по времени выхода)
        prev, prev_at = {}, None
        if OUT.exists():
            try:
                pj = json.loads(OUT.read_text(encoding="utf-8"))
                prev_at = pj.get("updated")
                prev = {x["id"]: x for x in pj.get("sbcs", [])}
            except Exception:
                pass
        now_iso = datetime.now(timezone.utc).isoformat(timespec="minutes")
        listing = read_sbc_list(page)
        order = {sid: i for i, sid in enumerate(listing)}
        sbcs = []
        for sbc_id, slug in sorted(listing.items()):
            time.sleep(1)
            try:
                s = read_sbc(page, sbc_id, slug)
            except Exception as e:
                log(f"  SBC {sbc_id}: ошибка {e}")
                continue
            if s:
                s["order"] = order.get(sbc_id, 9999)
                s["first_seen"] = (prev[sbc_id].get("first_seen") or prev_at) if sbc_id in prev else now_iso
                sbcs.append(s)

        # игроки-награды: берём из прошлого raw.json, чтобы не ходить на сайт лишний раз
        old = {}
        if OUT.exists():
            try:
                old = json.loads(OUT.read_text(encoding="utf-8")).get("players", {})
            except Exception:
                pass
        players = {}
        for s in sbcs:
            pid, slug = s["reward"].get("player_id"), s["reward"].get("player_slug")
            if not pid or str(pid) in players:
                continue
            if str(pid) in old and old[str(pid)].get("v", 1) >= PLAYER_V:
                players[str(pid)] = old[str(pid)]
                continue
            time.sleep(1)
            try:
                players[str(pid)] = read_player(page, pid, slug)
            except Exception as e:
                log(f"  игрок {pid}: ошибка {e}")
        resolve_club_names(page, list(players.values()), load_club_names())
        browser.close()

    if not sbcs:
        sys.exit("SBC не найдены. raw.json не тронут.")
    raw = {
        "updated": datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0).isoformat(timespec="minutes"),
        "source": "futmind.com", "platforms": platforms, "players": players, "sbcs": sbcs,
    }
    OUT.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"Готово: {len(sbcs)} SBC")


if __name__ == "__main__":
    main()

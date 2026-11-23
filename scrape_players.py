"""Копит базу игроков (players_db.json) со страниц futmind: списки лучших игроков -> страницы игроков.

Запускается по расписанию и дописывает базу порциями: за один запуск не больше MAX_NEW новых игроков
и не дольше MAX_SECONDS. Уже собранные игроки не перечитываются (карточка игрока не меняется).
"""
import json
import re
import sys
import time
from datetime import datetime, timezone

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from playerdb import SLIM, root
from scrape import BASE, PLAYER_V, load_club_names, log, read_player, resolve_club_names

MAX_NEW = 300
MAX_SECONDS = 25 * 60
POS = ["gk", "cb", "lb", "rb", "cdm", "cm", "cam", "lm", "rm", "st", "lw", "rw"]
# ценовые группы по возрастанию: игрок получает самую дешёвую группу, в списке которой он встретился
BUDGETS = [("under-10k", 10_000), ("under-25k", 25_000), ("under-50k", 50_000), ("under-100k", 100_000),
           ("under-250k", 250_000), ("under-500k", 500_000), ("under-1m", 1_000_000), (None, 0)]
DB = root / "players_db.json"


def crawl(page, url):
    page.goto(url, wait_until="networkidle")
    try:
        page.get_by_text(re.compile(r"Show top \d+")).first.click(timeout=2000)
        page.wait_for_timeout(1200)
    except Exception:
        pass
    soup = BeautifulSoup(page.content(), "html.parser")
    found = []
    for a in soup.find_all("a", href=True):
        m = re.search(r"/players/(\d+)/([^/?#]+)", a["href"])
        if m:
            found.append((m.group(1), m.group(2)))
    return found


def main():
    try:
        db = json.loads(DB.read_text(encoding="utf-8"))
    except Exception:
        db = {"players": {}, "queue": [], "queue_at": None}
    players = db["players"]
    started = time.time()

    def save():
        db["players"] = players
        DB.write_text(json.dumps(db, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(locale="en-US")

        stale = not db.get("queue_at") or (datetime.now(timezone.utc) - datetime.fromisoformat(db["queue_at"])).total_seconds() > 86400
        if stale or not db.get("queue"):
            queue, seen = [], set()
            urls = [(f"{BASE}/players/best" + (f"/{b}" if b else ""), cap) for b, cap in BUDGETS]
            urls += [(f"{BASE}/players/best/{pos}" + (f"/{b}" if b else ""), cap) for b, cap in BUDGETS for pos in POS]
            for u, cap in urls:
                if time.time() - started > MAX_SECONDS / 2:
                    break
                try:
                    for pid, slug in crawl(page, u):
                        if pid not in seen:
                            seen.add(pid)
                            queue.append([pid, slug, cap])
                except Exception as e:
                    log(f"  список {u}: {e.__class__.__name__}")
                time.sleep(1)
            if queue:
                db["queue"], db["queue_at"] = queue, datetime.now(timezone.utc).isoformat(timespec="minutes")
            log(f"в очереди игроков: {len(db['queue'])}")

        for q in db.get("queue", []):  # ценовая группа для уже собранных игроков
            if q[0] in players and len(q) > 2 and q[2]:
                players[q[0]]["pc"] = min(players[q[0]].get("pc") or q[2], q[2])
        todo = [q for q in db.get("queue", []) if q[0] not in players or players[q[0]].get("v", 1) < PLAYER_V]
        done = 0
        for q in todo[:MAX_NEW]:
            pid, slug = q[0], q[1]
            if time.time() - started > MAX_SECONDS:
                break
            try:
                pl = read_player(page, int(pid), slug)
                rec = {k: pl.get(k) for k in SLIM}
                rec["v"] = PLAYER_V
                rec["pc"] = (q[2] if len(q) > 2 else 0) or None
                players[pid] = rec
                done += 1
            except Exception as e:
                log(f"  игрок {pid}: ошибка {e.__class__.__name__}")
            if done % 20 == 0:
                save()
            time.sleep(1)
        resolve_club_names(page, list(players.values()), load_club_names())
        browser.close()
    save()
    log(f"Игроков в базе: {len(players)}, осталось в очереди: {max(0, len(todo) - done)}")
    if not players:
        sys.exit("База пуста: проверьте разметку списков игроков.")


if __name__ == "__main__":
    main()

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
from scrape import BASE, PLAYER_V, log, read_player

MAX_NEW = 300
MAX_SECONDS = 25 * 60
POS = ["gk", "cb", "lb", "rb", "cdm", "cm", "cam", "lm", "rm", "st", "lw", "rw"]
BUDGETS = [None, "under-10k", "under-25k", "under-50k", "under-100k", "under-250k", "under-500k", "under-1m"]
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
            urls = [f"{BASE}/players/best" + (f"/{b}" if b else "") for b in BUDGETS]
            urls += [f"{BASE}/players/best/{pos}" + (f"/{b}" if b else "") for pos in POS for b in BUDGETS]
            for u in urls:
                if time.time() - started > MAX_SECONDS / 2:
                    break
                try:
                    for pid, slug in crawl(page, u):
                        if pid not in seen:
                            seen.add(pid)
                            queue.append([pid, slug])
                except Exception as e:
                    log(f"  список {u}: {e.__class__.__name__}")
                time.sleep(1)
            if queue:
                db["queue"], db["queue_at"] = queue, datetime.now(timezone.utc).isoformat(timespec="minutes")
            log(f"в очереди игроков: {len(db['queue'])}")

        todo = [q for q in db.get("queue", []) if q[0] not in players or players[q[0]].get("v", 1) < PLAYER_V]
        done = 0
        for pid, slug in todo[:MAX_NEW]:
            if time.time() - started > MAX_SECONDS:
                break
            try:
                pl = read_player(page, int(pid), slug)
                rec = {k: pl.get(k) for k in SLIM}
                rec["v"] = PLAYER_V
                players[pid] = rec
                done += 1
            except Exception as e:
                log(f"  игрок {pid}: ошибка {e.__class__.__name__}")
            if done % 20 == 0:
                save()
            time.sleep(1)
        browser.close()
    save()
    log(f"Игроков в базе: {len(players)}, осталось в очереди: {max(0, len(todo) - done)}")
    if not players:
        sys.exit("База пуста: проверьте разметку списков игроков.")


if __name__ == "__main__":
    main()

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
    return {
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

        sbcs = []
        for sbc_id, slug in sorted(read_sbc_list(page).items()):
            time.sleep(1)
            try:
                s = read_sbc(page, sbc_id, slug)
            except Exception as e:
                log(f"  SBC {sbc_id}: ошибка {e}")
                continue
            if s:
                sbcs.append(s)
        browser.close()

    if not sbcs:
        sys.exit("SBC не найдены. raw.json не тронут.")
    raw = {
        "updated": datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0).isoformat(timespec="minutes"),
        "source": "futmind.com", "platforms": platforms, "sbcs": sbcs,
    }
    OUT.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"Готово: {len(sbcs)} SBC")


if __name__ == "__main__":
    main()

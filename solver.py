"""Сборки для Streamlined SBC в EA FC 27.

Нужно набрать не меньше `target` кристаллов (item score), сдавая карты.
У каждой карты есть рейтинг, редкость, очки и цена. Дубликаты разрешены.
Если у SBC есть минимальный рейтинг, карты ниже него не используются.

Три режима:
  cheap — минимум монет (обычно сотни карт рейтинга 83-84);
  optimal — компромисс: к цене каждой карты добавляется «штраф за время»
          TIME_PENALTY монет, и минимизируется сумма. Карты стоят чуть дороже,
          чем в дешёвом варианте, но их заметно меньше;
  fast  — минимум карт. Чтобы не покупать самые дорогие карты по любой цене,
          берутся только карты, у которых цена за кристалл не выше
          FAST_RATIO от самой выгодной карты. Среди сборок с минимумом карт
          выбирается самая дешёвая.
"""

WINDOW = 60_000    # размер точного перебора, остальное закрывается одной картой
FAST_COST_CAP = 2.0  # режим fast: итог не дороже, чем в 2 раза от самой дешёвой сборки
OPT_PENALTY = 1.5  # режим optimal: «стоимость» одной сданной карты = 1.5 цены самой выгодной карты


# обычные карты; особые (TOTW, Ultimate Scream, Icon, Hero и т. д.) в быстрых режимах не используем
PLAIN = {"common", "rare", "gold", "silver", "bronze", "rare gold", "rare silver", "rare bronze", "common gold", "common silver", "common bronze"}


def _pareto(cards):
    """Убирает карты, которые хуже другой (меньше очков и не дешевле)."""
    cards = sorted(cards, key=lambda c: (c["price"], -c["score"]))
    result, best_score = [], 0
    for c in cards:
        if c["score"] > best_score:
            result.append(c)
            best_score = c["score"]
    return result


def _run(pool, target, penalty, by_count=False):
    """Минимизирует cost + penalty * count (penalty=0: просто монеты).
    by_count=True: сначала минимум карт, потом монеты. Возвращает {индекс карты: количество}."""
    if by_count:
        best = max(pool, key=lambda c: (c["score"], -c["price"]))
        score = lambda cnt, cost: (cnt, cost)
    else:
        best = min(pool, key=lambda c: (c["price"] + penalty) / c["score"])
        # при penalty=0 не умножаем на счётчик: inf * 0 дало бы nan и сломало сравнения
        score = (lambda cnt, cost: cost + penalty * cnt) if penalty else (lambda cnt, cost: cost)

    bulk = 0
    if target > WINDOW + best["score"]:
        bulk = (target - WINDOW) // best["score"]
    rest = target - bulk * best["score"]

    inf = float("inf")
    cnt = [0] * (rest + 1)
    cost = [0] * (rest + 1)
    val = [score(0, 0)] + [score(inf, inf)] * rest
    pick = [-1] * (rest + 1)
    for t in range(1, rest + 1):
        for i, c in enumerate(pool):
            p = max(0, t - c["score"])
            n, m = cnt[p] + 1, cost[p] + c["price"]
            v = score(n, m)
            if v < val[t]:
                val[t], cnt[t], cost[t], pick[t] = v, n, m, i

    counts = {}
    if bulk:
        counts[pool.index(best)] = bulk
    t = rest
    while t > 0:
        i = pick[t]
        counts[i] = counts.get(i, 0) + 1
        t = max(0, t - pool[i]["score"])
    return counts


def _build(pool, target, penalty, by_count=False):
    counts = _run(pool, target, penalty, by_count)
    lines = []
    for i, qty in sorted(counts.items(), key=lambda kv: -pool[kv[0]]["score"]):
        c = pool[i]
        lines.append({"rating": c["rating"], "rarity": c["rarity"],
                      "score": c["score"], "price": c["price"], "qty": qty})
    total = sum(l["score"] * l["qty"] for l in lines)
    return {
        "lines": lines,
        "cost": sum(l["price"] * l["qty"] for l in lines),
        "score": total,
        "surplus": total - target,
        "players": sum(l["qty"] for l in lines),
    }


def solve(cards, target, min_rating=0, mode="cheap"):
    """Возвращает сборку или None, если подходящих карт нет."""
    pool = [c for c in cards if c["rating"] >= min_rating and c["score"] > 0 and c["price"] > 0]
    if not pool or target <= 0:
        return None
    plain = [c for c in pool if (c["rarity"] or "").strip().lower() in PLAIN]
    if mode != "cheap" and plain:
        pool = plain
    pool = _pareto(pool)
    base = min(pool, key=lambda c: c["price"] / c["score"])["price"]  # цена самой выгодной по монетам карты
    cheap = _build(pool, target, 0)  # для сравнения в режимах optimal/fast
    if mode == "cheap":
        return cheap
    if mode == "optimal":
        return _build(pool, target, base * OPT_PENALTY)
    # fast: увеличиваем «цену карты», пока сборка не станет дороже допустимого, берём с минимумом карт
    cap = cheap["cost"] * FAST_COST_CAP
    best = cheap
    for k in (1, 2, 4, 8, 16, 32, 64):
        b = _build(pool, target, base * k)
        if b["cost"] <= cap and (b["players"], b["cost"]) < (best["players"], best["cost"]):
            best = b
    return best

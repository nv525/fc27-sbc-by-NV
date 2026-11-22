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

WINDOW = 120_000   # размер точного перебора, остальное закрывается одной картой
FAST_RATIO = 1.5   # во сколько раз цена за кристалл может быть выше минимальной
TIME_PENALTY = 300 # сколько монет «стоит» время на одну сданную карту (режим optimal)


def _pareto(cards):
    """Убирает карты, которые хуже другой (меньше очков и не дешевле)."""
    cards = sorted(cards, key=lambda c: (c["price"], -c["score"]))
    result, best_score = [], 0
    for c in cards:
        if c["score"] > best_score:
            result.append(c)
            best_score = c["score"]
    return result


def _run(pool, target, key):
    """key(count, cost) -> что минимизируем. Возвращает {индекс карты: количество}."""
    if key == "cost":
        best = min(pool, key=lambda c: c["price"] / c["score"])
        score = lambda cnt, cost: cost
    elif key == "balanced":
        best = min(pool, key=lambda c: (c["price"] + TIME_PENALTY) / c["score"])
        score = lambda cnt, cost: cost + TIME_PENALTY * cnt
    else:
        best = max(pool, key=lambda c: (c["score"], -c["price"]))
        score = lambda cnt, cost: (cnt, cost)

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


def solve(cards, target, min_rating=0, mode="cheap"):
    """Возвращает сборку или None, если подходящих карт нет."""
    pool = [c for c in cards if c["rating"] >= min_rating and c["score"] > 0 and c["price"] > 0]
    if not pool or target <= 0:
        return None
    if mode == "fast":
        cheapest = min(c["price"] / c["score"] for c in pool)
        pool = [c for c in pool if c["price"] / c["score"] <= cheapest * FAST_RATIO]
    pool = _pareto(pool)

    key = {"cheap": "cost", "optimal": "balanced", "fast": "count"}[mode]
    counts = _run(pool, target, key)
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

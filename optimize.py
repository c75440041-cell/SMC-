"""Busca la mejor combinacion de puertas con validacion fuera de muestra (train/test por tiempo).
Con 13 flags hay 377 combinaciones de hasta 3: la mejor en train casi siempre es suerte.
Solo es creible lo que sigue siendo positivo en TEST con muestra suficiente."""
import math
from itertools import combinations

from journal import outcomes
from strategy import KNOWN_FLAGS


def _stats(ds, m):
    vals = [v for mk, v in ds if (mk & m) == m]
    n = len(vals)
    if n < 2:
        return n, 0.0, 0.0
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / (n - 1)
    return n, mean, math.sqrt(var / n)


def optimize(rows, cost_pct, target=2, max_gates=3, train_frac=0.7, min_n=60, top=8, setups=None, flags=None):
    flags = flags or KNOWN_FLAGS
    rs = [r for r in rows if r["status"] == "closed" and (setups is None or r["setup"].split("-")[0].lower() in setups)]
    rs.sort(key=lambda r: r["t"])
    data = []
    for r in rs:
        o = outcomes(r, cost_pct)
        mask = 0
        for b, f in enumerate(flags):
            if r["flags"].get(f):
                mask |= 1 << b
        data.append((mask, o[target - 1]))
    if len(data) < 4 * min_n:
        return f"Muy pocas señales resueltas ({len(data)}) para optimizar con seriedad (mínimo ~{4 * min_n})."
    cut = int(len(data) * train_frac)
    train, test = data[:cut], data[cut:]
    cands = []
    for size in range(0, max_gates + 1):
        for combo in combinations(range(len(flags)), size):
            m = sum(1 << b for b in combo)
            n, e, se = _stats(train, m)
            if n >= min_n:
                cands.append((e - se, m, combo))        # se ordena por cota inferior (castiga muestras pequenas)
    cands.sort(reverse=True)
    lines = [f"Optimización de puertas · objetivo TP{target} · neto de costes ({cost_pct:.2f}%)",
             f"Señales: {len(data)} (train {len(train)} / test {len(test)}, cortado por tiempo) · {len(cands)} combinaciones con n>={min_n}",
             "", "puertas | TRAIN n  E | TEST n  E±SE"]
    base_tr, base_te = _stats(train, 0), _stats(test, 0)
    lines.append(f"(sin puertas) | {base_tr[0]} {base_tr[1]:+.2f} | {base_te[0]} {base_te[1]:+.2f}±{base_te[2]:.2f}")
    credible = 0
    for _, m, combo in cands[:top]:
        n1, e1, _s = _stats(train, m)
        n2, e2, se2 = _stats(test, m)
        name = ",".join(flags[b] for b in combo) or "(ninguna)"
        ok = n2 >= 100 and e2 - 1.0 * se2 > 0
        credible += ok
        lines.append(f"{name} | {n1} {e1:+.2f} | {n2} {e2:+.2f}±{se2:.2f} {'✅' if ok else ''}")
    lines.append("")
    lines.append("✅ = TEST con n>=100 y E-1·SE>0. " + ("Hay candidatas; vuelve a comprobarlas con otro periodo/monedas."
                 if credible else "Ninguna es creíble todavía: no cambies tus puertas por esto."))
    return "\n".join(lines)

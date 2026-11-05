"""Single-file HTML report (Jinja2 + inline SVG, no external resources)."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

PAGES_URL = "https://agdala.github.io/record-linkage-kit/"


def pct(value: float, digits: int = 1) -> str:
    return f"{value * 100:.{digits}f}%".replace(".", ",")


def num(value: float | int, digits: int = 0) -> str:
    text = f"{value:,.{digits}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def dec(value: float | None, digits: int = 2) -> str:
    return "n/d" if value is None else f"{value:.{digits}f}".replace(".", ",")


def pr_chart(rows: list[dict], thr: dict, width: int = 720, height: int = 320) -> dict:
    """Geometry of the precision x recall x F1 by threshold line chart."""
    m = {"l": 52, "r": 84, "t": 16, "b": 40}
    xs = [r["limiar"] for r in rows]
    lo = min(min(r[k] for r in rows) for k in ("precisao", "recall", "f1"))
    y_min = max(0.0, (int(lo * 20) / 20) - 0.05)
    x0, x1 = min(xs), max(xs)
    pw, ph = width - m["l"] - m["r"], height - m["t"] - m["b"]

    def sx(x):
        return m["l"] + (x - x0) / (x1 - x0) * pw

    def sy(y):
        return m["t"] + (1 - (y - y_min) / (1 - y_min)) * ph

    series = []
    for key, label, var in (("precisao", "Precisão", "--series-1"),
                            ("recall", "Recall", "--series-2"), ("f1", "F1", "--series-3")):
        pts = [(sx(r["limiar"]), sy(r[key])) for r in rows]
        series.append({
            "key": key, "label": label, "var": var,
            "path": "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts),
            "points": [{"x": x, "y": y} for x, y in pts],
            "end": {"x": pts[-1][0], "y": pts[-1][1]},
        })
    # Spread end labels so they do not collide
    ends = sorted(series, key=lambda s: s["end"]["y"])
    for prev, cur in zip(ends, ends[1:], strict=False):
        if cur["end"]["y"] - prev["end"]["y"] < 14:
            cur["end"] = {**cur["end"], "y": prev["end"]["y"] + 14}
    step = 0.05
    ticks_y = []
    v = y_min
    while v <= 1.0001:
        ticks_y.append({"v": v, "y": sy(v)})
        v = round(v + step, 4)
    desc = (
        f"Linhas de precisão, recall e F1 para {len(rows)} limiares de pontuação, "
        f"de {dec(x0)} a {dec(x1)}, com marcas nos limiares de revisão "
        f"({dec(thr['revisao'])}) e de match ({dec(thr['match'])})."
    )
    no_match = next((r for r in rows if r["limiar"] == thr["match"]), None)
    if no_match:
        desc += (f" No limiar de match: precisão {pct(no_match['precisao'])}, "
                 f"recall {pct(no_match['recall'])} e F1 {pct(no_match['f1'])}.")
    desc += " Os valores de cada limiar estão na tabela abaixo do gráfico."
    return {
        "w": width, "h": height, "m": m, "series": series, "desc": desc,
        "ticks_x": [{"v": x, "x": sx(x)} for x in xs],
        "ticks_y": ticks_y,
        "marks": [{"label": "revisão", "x": sx(thr["revisao"])},
                  {"label": "match", "x": sx(thr["match"])}],
        "band_w": pw / (len(xs) - 1),
        "rows": rows,
        "plot": {"x0": m["l"], "x1": m["l"] + pw, "y0": m["t"], "y1": m["t"] + ph},
    }


def render_report(metrics: dict, cases: list[dict], path: str | Path) -> None:
    env = Environment(loader=PackageLoader("rlk", "templates"),
                      autoescape=select_autoescape(["html", "j2"]))
    env.filters.update(pct=pct, num=num, dec=dec)
    html = env.get_template("relatorio.html.j2").render(
        m=metrics, cases=cases, chart=pr_chart(metrics["por_limiar"], metrics["limiares"]),
        pages_url=PAGES_URL,
    )
    Path(path).write_text(html, encoding="utf-8")

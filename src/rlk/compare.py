"""Field comparison and weighted scoring."""

from __future__ import annotations

from datetime import date

import pandas as pd
from rapidfuzz.distance import JaroWinkler

MISSING = None  # a missing comparison leaves the field out of the score


def name_similarity(a: str, b: str) -> float | None:
    """Jaro-Winkler on the full name, also tested with sorted tokens (reordered surnames)."""
    if not a or not b:
        return MISSING
    direct = JaroWinkler.normalized_similarity(a, b)
    if direct == 1.0:
        return 1.0
    sorted_ = JaroWinkler.normalized_similarity(" ".join(sorted(a.split())),
                                                " ".join(sorted(b.split())))
    return max(direct, sorted_)


def date_level(a: str, b: str) -> str:
    """Comparison level for ISO dates: igual, dia_mes_trocado, so_ano, diferente or ausente."""
    if not a or not b:
        return "ausente"
    if a == b:
        return "igual"
    da, db = date.fromisoformat(a), date.fromisoformat(b)
    if da.year == db.year and da.day == db.month and da.month == db.day:
        return "dia_mes_trocado"
    if da.year == db.year:
        return "so_ano"
    return "diferente"


def exact(a: str, b: str) -> float | None:
    if not a or not b:
        return MISSING
    return 1.0 if a == b else 0.0


def compare_pairs(
    pairs: pd.DataFrame, left: pd.DataFrame, right: pd.DataFrame, cfg: dict
) -> pd.DataFrame:
    """Add the similarity of each field and the final score (0 to 1) to the candidate pairs."""
    weights: dict[str, float] = cfg["pesos"]
    date_values: dict[str, float] = cfg["niveis_data"]
    lt = left.set_index("id")
    rt = right.set_index("id")
    l_rows = lt.loc[pairs["id_1"]]
    r_rows = rt.loc[pairs["id_2"]]

    def col(frame, name):
        return frame[name].tolist()

    sims: dict[str, list] = {}
    sims["nome"] = [name_similarity(a, b) for a, b in zip(col(l_rows, "nome"),
                                                          col(r_rows, "nome"), strict=True)]
    sims["nome_mae"] = [name_similarity(a, b) for a, b in zip(col(l_rows, "nome_mae"),
                                                              col(r_rows, "nome_mae"),
                                                              strict=True)]
    levels = [date_level(a, b) for a, b in zip(col(l_rows, "data_nascimento"),
                                               col(r_rows, "data_nascimento"), strict=True)]
    sims["data_nascimento"] = [date_values.get(lv, MISSING) for lv in levels]
    sims["sexo"] = [exact(a, b) for a, b in zip(col(l_rows, "sexo"), col(r_rows, "sexo"),
                                                strict=True)]
    mun_l = (l_rows["municipio"] + "/" + l_rows["uf"]).where(l_rows["municipio"] != "", "")
    mun_r = (r_rows["municipio"] + "/" + r_rows["uf"]).where(r_rows["municipio"] != "", "")
    sims["municipio"] = [exact(a, b) for a, b in zip(mun_l.tolist(), mun_r.tolist(), strict=True)]
    sims["documento"] = [exact(a, b) for a, b in zip(col(l_rows, "documento"),
                                                     col(r_rows, "documento"), strict=True)]

    out = pairs.reset_index(drop=True).copy()
    num = pd.Series(0.0, index=out.index)
    den = pd.Series(0.0, index=out.index)
    for field, weight in weights.items():
        s = pd.Series(sims[field], index=out.index, dtype="float64")
        out[f"sim_{field}"] = s.round(4)
        available = s.notna()
        num += s.fillna(0.0) * weight
        den += available * weight
    out["nivel_data"] = levels
    out["pontuacao"] = (num / den.where(den > 0)).fillna(0.0).round(4)
    return out

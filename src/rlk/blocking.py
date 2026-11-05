"""Configurable blocking: candidate pairs are the union of several blocking rules."""

from __future__ import annotations

import pandas as pd


def block_pairs(
    left: pd.DataFrame, right: pd.DataFrame | None, rules: list[dict]
) -> pd.DataFrame:
    """Return candidate pairs ``id_1, id_2, regras`` from the union of the blocking rules.

    With ``right=None`` the base is compared with itself (deduplication) and only pairs with
    ``id_1 < id_2`` are kept. Records with an empty value in any key of a rule are left out of
    that rule (an empty value is not evidence of similarity).
    """
    dedup = right is None
    right = left if dedup else right
    found: list[pd.DataFrame] = []
    for rule in rules:
        keys = list(rule["chaves"])
        lk = left.loc[(left[keys] != "").all(axis=1), ["id", *keys]]
        rk = right.loc[(right[keys] != "").all(axis=1), ["id", *keys]]
        pairs = lk.merge(rk, on=keys, suffixes=("_1", "_2"))[["id_1", "id_2"]]
        if dedup:
            pairs = pairs[pairs["id_1"] < pairs["id_2"]]
        found.append(pairs.assign(regra=rule["nome"]))
    allpairs = pd.concat(found, ignore_index=True)
    out = (
        allpairs.groupby(["id_1", "id_2"], sort=True)["regra"]
        .agg(lambda s: "+".join(sorted(set(s))))
        .reset_index()
        .rename(columns={"regra": "regras"})
    )
    return out


def blocking_stats(
    pairs: pd.DataFrame, n_left: int, n_right: int | None, rules: list[dict]
) -> dict:
    """Pair counts per rule, union size and reduction ratio versus the full cross product."""
    total = n_left * (n_left - 1) // 2 if n_right is None else n_left * n_right
    per_rule = {
        r["nome"]: int(pairs["regras"].str.split("+").map(lambda x, n=r["nome"]: n in x).sum())
        for r in rules
    }
    return {
        "pares_possiveis": int(total),
        "pares_candidatos": int(len(pairs)),
        "pares_por_regra": per_rule,
        "taxa_reducao": 1 - len(pairs) / total if total else 0.0,
    }

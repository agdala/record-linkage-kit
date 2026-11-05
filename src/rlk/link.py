"""Linkage pipeline: standardize, block, compare, score, classify, resolve 1:1 and write outputs."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from rlk.blocking import block_pairs, blocking_stats
from rlk.compare import compare_pairs
from rlk.standardize import read_registry, standardize_frame

RAW_FIELDS = ["nome_completo", "nome_mae", "data_nascimento", "sexo", "municipio", "uf",
              "documento"]
SIM_COLUMNS = ["sim_nome", "sim_nome_mae", "sim_data_nascimento", "nivel_data", "sim_sexo",
               "sim_municipio", "sim_documento"]


def resolve_one_to_one(scored: pd.DataFrame, min_score: float) -> pd.DataFrame:
    """Greedy 1:1 resolution: highest score first, each record used at most once.

    Ties are broken by the ids, so the result is deterministic.
    """
    cand = scored[scored["pontuacao"] >= min_score].sort_values(
        ["pontuacao", "id_1", "id_2"], ascending=[False, True, True]
    )
    used_1: set[str] = set()
    used_2: set[str] = set()
    keep = []
    for idx, a, b in zip(cand.index, cand["id_1"], cand["id_2"], strict=True):
        if a in used_1 or b in used_2:
            continue
        used_1.add(a)
        used_2.add(b)
        keep.append(idx)
    return cand.loc[keep].reset_index(drop=True)


def classify(score: float, thresholds: dict) -> str:
    if score >= thresholds["match"]:
        return "match"
    if score >= thresholds["revisao"]:
        return "revisao"
    return "nao_match"


def side_by_side(pairs: pd.DataFrame, raw_1: pd.DataFrame, raw_2: pd.DataFrame,
                 s1: str = "a", s2: str = "b") -> pd.DataFrame:
    """Put the original fields of both records next to each other, for human review."""
    r1 = raw_1.set_index("id")[RAW_FIELDS].add_suffix(f"_{s1}")
    r2 = raw_2.set_index("id")[RAW_FIELDS].add_suffix(f"_{s2}")
    out = pairs.join(r1, on="id_1").join(r2, on="id_2")
    ordered = [c for f in RAW_FIELDS for c in (f"{f}_{s1}", f"{f}_{s2}")]
    return out[["id_1", "id_2", "pontuacao", *ordered, *SIM_COLUMNS, "regras"]]


def run_link(cfg: dict, root: str | Path = ".") -> dict:
    root = Path(root)
    out_dir = root / cfg["saida"]
    out_dir.mkdir(parents=True, exist_ok=True)
    drop = cfg.get("padronizacao", {}).get("remover_particulas", True)

    raw_a = read_registry(root / cfg["entrada"]["base_a"])
    raw_b = read_registry(root / cfg["entrada"]["base_b"])
    std_a = standardize_frame(raw_a, drop_particles=drop)
    std_b = standardize_frame(raw_b, drop_particles=drop)

    # ---------------------------------------------------------------- A x B
    rules = cfg["blocagem"]
    cand = block_pairs(std_a, std_b, rules)
    stats = blocking_stats(cand, len(std_a), len(std_b), rules)
    scored = compare_pairs(cand, std_a, std_b, cfg)
    scored.sort_values(["id_1", "id_2"]).to_csv(out_dir / "candidatos.csv", index=False)

    thr = cfg["limiares"]
    assigned = resolve_one_to_one(scored, thr["revisao"])
    assigned["classe"] = assigned["pontuacao"].map(lambda s: classify(s, thr))
    matches = assigned[assigned["classe"] == "match"]
    review = assigned[assigned["classe"] == "revisao"]

    rename = {"id_1": "id_a", "id_2": "id_b"}
    matches[["id_1", "id_2", "pontuacao", *SIM_COLUMNS, "regras"]].rename(columns=rename).to_csv(
        out_dir / "matches.csv", index=False
    )
    review_out = side_by_side(review, raw_a, raw_b).rename(columns=rename)
    review_out["decisao_revisor"] = ""  # to be filled: match / nao_match
    review_out.sort_values("pontuacao", ascending=False).to_csv(
        out_dir / "revisao_manual.csv", index=False
    )

    best_a = scored.groupby("id_1")["pontuacao"].max()
    best_b = scored.groupby("id_2")["pontuacao"].max()
    unmatched = []
    for base, raw, used, best in (
        ("A", raw_a, set(assigned["id_1"]), best_a),
        ("B", raw_b, set(assigned["id_2"]), best_b),
    ):
        rest = raw[~raw["id"].isin(used)].copy()
        rest.insert(0, "base", base)
        rest["melhor_pontuacao"] = rest["id"].map(best).fillna(0.0).round(4)
        unmatched.append(rest)
    pd.concat(unmatched, ignore_index=True).to_csv(out_dir / "nao_pareados.csv", index=False)

    summary = {
        "base_a": len(raw_a),
        "base_b": len(raw_b),
        "blocagem": stats,
        "limiares": thr,
        "matches": int(len(matches)),
        "revisao_manual": int(len(review)),
        "nao_pareados_b": int(len(raw_b) - len(assigned)),
    }

    # ---------------------------------------------------------------- A x A (deduplication)
    dedup_cfg = cfg.get("deduplicacao", {})
    if dedup_cfg.get("ativa", False):
        cand_aa = block_pairs(std_a, None, rules)
        stats_aa = blocking_stats(cand_aa, len(std_a), None, rules)
        scored_aa = compare_pairs(cand_aa, std_a, std_a, cfg)
        scored_aa.sort_values(["id_1", "id_2"]).to_csv(
            out_dir / "candidatos_dedup.csv", index=False
        )
        dups = scored_aa[scored_aa["pontuacao"] >= dedup_cfg["limiar"]]
        side_by_side(dups, raw_a, raw_a, "1", "2").sort_values(
            "pontuacao", ascending=False
        ).to_csv(out_dir / "duplicatas_a.csv", index=False)
        summary["deduplicacao"] = {
            "blocagem": stats_aa,
            "limiar": dedup_cfg["limiar"],
            "pares_duplicados": int(len(dups)),
        }

    with open(out_dir / "resumo_link.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    return summary

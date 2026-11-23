"""Supervised classifier for the candidate pairs, compared with the hand-weighted score.

The hand-weighted score (``compare.py``) uses weights chosen by the author. Here the weights are
learned from labelled pairs instead: the comparison features of each candidate pair go into a
logistic regression and a gradient boosting model, trained on half of list B and tested on the
other half. Both models and the hand-weighted score are measured on the same test half, at
thresholds chosen only on the training half.

The split is by B record. A person appears once in B, so no person has pairs on both sides of the
split, and the test half is never seen while training or while choosing thresholds.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from rapidfuzz.distance import JaroWinkler
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score

from rlk.link import resolve_one_to_one
from rlk.standardize import read_registry, standardize_frame

SIM_FEATURES = ["sim_nome", "sim_primeiro_nome", "sim_nome_mae", "sim_sexo", "sim_municipio",
                "sim_documento"]
DATE_LEVELS = ["igual", "dia_mes_trocado", "so_ano", "diferente", "ausente"]
# name -> (label, estimator, features left out). The third model is an ablation: the same
# logistic regression without the first-name feature, to separate what the new feature adds from
# what learning the weights adds.
MODELS = {
    "regressao_logistica": ("Regressão logística", "logistica", ()),
    "regressao_logistica_sem_primeiro_nome": (
        "Regressão logística sem o primeiro nome", "logistica",
        ("sim_primeiro_nome", "ausente_primeiro_nome")),
    "gradient_boosting": ("Gradient boosting", "boosting", ()),
}
DEFAULTS = {"fracao_teste": 0.5, "semente": 42, "folds": 5}
# Probabilities are rounded like the weighted score (4 decimals). Different CPUs give results that
# differ in the last bits of a float; without rounding, that noise reorders pairs near a threshold
# and the published metrics would change from one CI machine to another.
DECIMALS = 4


# --------------------------------------------------------------------- features
def first_name_similarity(pairs: pd.DataFrame, std_a: pd.DataFrame,
                          std_b: pd.DataFrame) -> pd.Series:
    """Jaro-Winkler of the first names. The weighted score only sees the full name, where a
    different first name is diluted by the shared surnames (the twin pattern)."""
    fa = std_a.set_index("id")["primeiro_nome"]
    fb = std_b.set_index("id")["primeiro_nome"]
    left = pairs["id_1"].map(fa).fillna("")
    right = pairs["id_2"].map(fb).fillna("")
    sims = [JaroWinkler.normalized_similarity(a, b) if a and b else np.nan
            for a, b in zip(left, right, strict=True)]
    return pd.Series(sims, index=pairs.index, dtype="float64")


def build_features(pairs: pd.DataFrame) -> pd.DataFrame:
    """Feature matrix: each similarity (0 when missing) plus a missing flag, and the date level
    one-hot encoded. Missing is kept as its own signal: it is not the same as a mismatch."""
    x = pd.DataFrame(index=pairs.index)
    for col in SIM_FEATURES:
        s = pairs[col].astype("float64")
        x[col] = s.fillna(0.0)
        x[f"ausente_{col.removeprefix('sim_')}"] = s.isna().astype("float64")
    for level in DATE_LEVELS:
        x[f"data_{level}"] = (pairs["nivel_data"] == level).astype("float64")
    return x


def _bucket(value: str, seed: int) -> float:
    """Position of an id in [0, 1], from a seeded hash: the same on any machine."""
    digest = hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def in_test(ids: pd.Series, fraction: float, seed: int) -> pd.Series:
    """Deterministic split by id: the same id always falls on the same side for a given seed."""
    return ids.map(lambda v: _bucket(v, seed) < fraction)


def fold_of(ids: pd.Series, folds: int, seed: int) -> np.ndarray:
    """Cross-validation fold of each id, also from the hash (with another seed than the split).

    scikit-learn's GroupKFold orders groups with an unstable sort, and numpy picks the sort
    implementation by CPU, so groups of equal size could land in different folds on different
    machines and change the published metrics.
    """
    return ids.map(lambda v: min(int(_bucket(v, seed + 1) * folds), folds - 1)).to_numpy()


def make_model(kind: str, seed: int):
    """Both models are set up to give the same result on any machine: the logistic regression is
    solved to a tight tolerance (its optimum is unique), and gradient boosting runs a fixed number
    of trees, without the early stopping that depends on an internal random validation split."""
    if kind == "logistica":
        return LogisticRegression(C=1.0, solver="newton-cholesky", tol=1e-10, max_iter=1000)
    if kind == "boosting":
        return HistGradientBoostingClassifier(max_iter=200, learning_rate=0.1,
                                              early_stopping=False, random_state=seed)
    raise ValueError(f"Modelo desconhecido: {kind}")


def out_of_fold(kind: str, x: pd.DataFrame, y: np.ndarray, groups: pd.Series, folds: int,
                seed: int) -> np.ndarray:
    """Probabilities for the training half from models that did not see each fold.

    Folds are grouped by B record, like the train/test split, so the thresholds chosen on these
    probabilities are not tuned on pairs the model was fitted on.
    """
    prob = np.zeros(len(x))
    fold = fold_of(groups.reset_index(drop=True), folds, seed)
    for k in range(folds):
        fit_idx, pred_idx = np.where(fold != k)[0], np.where(fold == k)[0]
        model = make_model(kind, seed).fit(x.iloc[fit_idx], y[fit_idx])
        prob[pred_idx] = model.predict_proba(x.iloc[pred_idx])[:, 1]
    return np.round(prob, DECIMALS)


# --------------------------------------------------------------------- operating points
def assign(pairs: pd.DataFrame, score: np.ndarray | pd.Series) -> pd.DataFrame:
    """Greedy 1:1 assignment by descending score (same resolution as the linkage pipeline)."""
    frame = pairs[["id_1", "id_2", "sim_nome_mae", "nivel_data"]].copy()
    frame["pontuacao"] = np.asarray(score, dtype="float64")
    return resolve_one_to_one(frame, -1.0)


def choose_thresholds(assigned: pd.DataFrame, truth: set, n_true: int,
                      min_precision: float, queue_size: int) -> dict:
    """Auto-match threshold: the lowest score whose accepted pairs keep ``min_precision``.
    Review threshold: the one that puts ``queue_size`` pairs in the queue below the match
    threshold, that is, the same reviewer capacity as the weighted score.

    Thresholds sit on observed scores, so every pair with the same score falls on the same side.
    """
    asg = assigned.sort_values("pontuacao", ascending=False)
    scores = asg["pontuacao"].to_numpy()
    hits = np.array([(a, b) in truth for a, b in zip(asg["id_1"], asg["id_2"], strict=True)])
    tp = np.cumsum(hits)
    k = np.arange(1, len(asg) + 1)
    # only the last position of each block of equal scores is a valid cut
    last_of_tie = np.append(scores[1:] != scores[:-1], True)
    precision = tp / k
    ok_p = np.where(last_of_tie & (precision >= min_precision))[0]
    if len(ok_p):
        n_auto, match = ok_p.max() + 1, float(scores[ok_p.max()])
    else:
        n_auto, match = 0, float(scores[0]) + 1e-9
    # last valid cut that keeps the queue within the capacity
    ok_q = np.where(last_of_tie & (k <= n_auto + queue_size))[0]
    review = float(scores[ok_q.max()]) if len(ok_q) and ok_q.max() + 1 > n_auto else match
    return {"match": match, "revisao": review}


def operating_point(assigned: pd.DataFrame, truth: set, n_true: int, thr: dict) -> dict:
    """Same indicators as ``evaluate.match_scenarios``, for one pair of thresholds."""
    hit = [(a, b) in truth for a, b in zip(assigned["id_1"], assigned["id_2"], strict=True)]
    asg = assigned.assign(correto=hit)
    auto = asg[asg["pontuacao"] >= thr["match"]]
    queue = asg[(asg["pontuacao"] >= thr["revisao"]) & (asg["pontuacao"] < thr["match"])]
    fp = auto[~auto["correto"]]
    twins = fp[(fp["sim_nome_mae"].fillna(0) >= 0.95) & (fp["nivel_data"] == "igual")]
    tp_auto = int(auto["correto"].sum())
    tp_queue = int(queue["correto"].sum())
    return {
        "limiar_match": thr["match"],
        "limiar_revisao": thr["revisao"],
        "pares_automaticos": int(len(auto)),
        "fp": int(len(fp)),
        "fp_perfil_gemeos": int(len(twins)),
        "precisao": tp_auto / len(auto) if len(auto) else 1.0,
        "recall_automatico": tp_auto / n_true,
        "fila_revisao": int(len(queue)),
        "fila_verdadeiros": tp_queue,
        "recall_com_revisao": (tp_auto + tp_queue) / n_true,
    }


# --------------------------------------------------------------------- pipeline
def evaluate_seed(scored: pd.DataFrame, x: pd.DataFrame, y: np.ndarray, std_b: pd.DataFrame,
                  gab: pd.DataFrame, truth: set, cfg: dict, seed: int, fraction: float,
                  folds: int) -> dict:
    """One train/test split: thresholds chosen on the training half, metrics on the test half."""
    test = in_test(scored["id_2"], fraction, seed).to_numpy()
    b_test = set(std_b["id"][in_test(std_b["id"], fraction, seed)])
    n_true = {"treino": int(gab.loc[~gab["id_2"].isin(b_test), "id_2"].nunique()),
              "teste": int(gab.loc[gab["id_2"].isin(b_test), "id_2"].nunique())}
    tr, te = scored[~test].reset_index(drop=True), scored[test].reset_index(drop=True)
    x_tr, x_te = x[~test].reset_index(drop=True), x[test].reset_index(drop=True)
    y_tr, y_te = y[~test], y[test]

    # The hand-weighted score sets the bar, measured on the training half only: each model must
    # keep at least its automatic precision, with a review queue of the same size.
    rule_thr = {"match": cfg["limiares"]["match"], "revisao": cfg["limiares"]["revisao"]}
    rule_tr = operating_point(assign(tr, tr["pontuacao"]), truth, n_true["treino"], rule_thr)
    targets = {"precisao_minima": rule_tr["precisao"],
               "fila_revisao": rule_tr["fila_revisao"]}

    results = {"regra_ponderada": {
        "nome": "Pontuação ponderada (pesos manuais)",
        "teste": operating_point(assign(te, te["pontuacao"]), truth, n_true["teste"], rule_thr),
        "precisao_media": float(average_precision_score(y_te, te["pontuacao"])),
    }}
    coefficients = {}
    for name, (label, kind, left_out) in MODELS.items():
        cols = [c for c in x.columns if c not in left_out]
        oof = out_of_fold(kind, x_tr[cols], y_tr, tr["id_2"], folds, seed)
        thr = choose_thresholds(assign(tr, oof), truth, n_true["treino"],
                                targets["precisao_minima"], targets["fila_revisao"])
        model = make_model(kind, seed).fit(x_tr[cols], y_tr)
        prob = np.round(model.predict_proba(x_te[cols])[:, 1], DECIMALS)
        results[name] = {
            "nome": label,
            "teste": operating_point(assign(te, prob), truth, n_true["teste"], thr),
            "precisao_media": float(average_precision_score(y_te, prob)),
        }
        if name == "regressao_logistica":
            coefficients = dict(sorted(zip(cols, model.coef_[0].tolist(), strict=True),
                                       key=lambda kv: -abs(kv[1])))
    split = {
        "semente": seed,
        "pares_treino": int(len(tr)), "pares_teste": int(len(te)),
        "positivos_treino": int(y_tr.sum()), "positivos_teste": int(y_te.sum()),
        "registros_b_com_par_treino": n_true["treino"],
        "registros_b_com_par_teste": n_true["teste"],
    }
    return {"divisao": split, "metas_do_treino": targets, "resultados_teste": results,
            "coeficientes_regressao_logistica": coefficients}


def summarize_seeds(runs: list[dict]) -> dict:
    """Totals over every split: one split is too small to tell 1 false positive from 3."""
    out = {}
    for name in runs[0]["resultados_teste"]:
        tests = [r["resultados_teste"][name]["teste"] for r in runs]
        n_true = sum(r["divisao"]["registros_b_com_par_teste"] for r in runs)
        fp = [t["fp"] for t in tests]
        found = sum(round(t["recall_com_revisao"] * r["divisao"]["registros_b_com_par_teste"])
                    for t, r in zip(tests, runs, strict=True))
        out[name] = {
            "fp_por_semente": fp,
            "fp_total": sum(fp),
            "fila_por_semente": [t["fila_revisao"] for t in tests],
            "fila_total": sum(t["fila_revisao"] for t in tests),
            "registros_encontrados_com_revisao": found,
            "registros_com_par": n_true,
            "recall_com_revisao": found / n_true,
        }
    return out


def run_ml(cfg: dict, root: str | Path = ".") -> dict:
    root = Path(root)
    out_dir = root / cfg["saida"]
    ml_cfg = {**DEFAULTS, **cfg.get("ml", {})}
    seeds = [int(v) for v in ml_cfg.get("sementes", [ml_cfg["semente"]])]
    fraction, folds = float(ml_cfg["fracao_teste"]), int(ml_cfg["folds"])
    drop = cfg.get("padronizacao", {}).get("remover_particulas", True)

    scored = pd.read_csv(out_dir / "candidatos.csv", dtype={"id_1": str, "id_2": str})
    std_a = standardize_frame(read_registry(root / cfg["entrada"]["base_a"]), drop)
    std_b = standardize_frame(read_registry(root / cfg["entrada"]["base_b"]), drop)
    gab = read_registry(root / cfg["entrada"]["gabarito"])
    gab = gab[gab["tipo"] == "link"]
    truth = set(zip(gab["id_1"], gab["id_2"], strict=True))

    scored["sim_primeiro_nome"] = first_name_similarity(scored, std_a, std_b)
    x = build_features(scored)
    y = np.array([(a, b) in truth for a, b in zip(scored["id_1"], scored["id_2"], strict=True)],
                 dtype=int)
    runs = [evaluate_seed(scored, x, y, std_b, gab, truth, cfg, s, fraction, folds)
            for s in seeds]

    first = runs[0]
    metrics = {
        "divisao": {"criterio": "registro da base B (hash do id com semente)",
                    "folds_validacao_cruzada": folds, **first["divisao"]},
        "variaveis": list(x.columns),
        "metas_do_treino": first["metas_do_treino"],
        "resultados_teste": first["resultados_teste"],
        "coeficientes_regressao_logistica": first["coeficientes_regressao_logistica"],
        "sementes": seeds,
        "todas_as_sementes": summarize_seeds(runs),
    }
    metrics = _round(metrics)
    with open(out_dir / "ml_metricas.json", "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return metrics


def _round(obj, digits: int = 4):
    if isinstance(obj, float):
        return round(obj, digits)
    if isinstance(obj, dict):
        return {k: _round(v, digits) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round(v, digits) for v in obj]
    return obj

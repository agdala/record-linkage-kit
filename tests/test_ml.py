import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from rlk.config import load_config
from rlk.link import run_link
from rlk.ml import (
    MODELS,
    build_features,
    choose_thresholds,
    first_name_similarity,
    in_test,
    operating_point,
    run_ml,
)

ROOT = Path(__file__).resolve().parents[1]


def test_split_is_deterministic_and_depends_on_seed():
    ids = pd.Series([f"B{i:05d}" for i in range(1000)])
    a, b = in_test(ids, 0.5, 42), in_test(ids, 0.5, 42)
    assert a.equals(b)
    assert 400 < a.sum() < 600  # roughly half
    assert not a.equals(in_test(ids, 0.5, 7))


def test_features_keep_missing_apart_from_mismatch():
    pairs = pd.DataFrame({
        "sim_nome": [1.0, 0.5], "sim_primeiro_nome": [1.0, np.nan], "sim_nome_mae": [np.nan, 0.0],
        "sim_sexo": [1.0, 0.0], "sim_municipio": [1.0, 0.0], "sim_documento": [np.nan, 0.0],
        "nivel_data": ["igual", "ausente"],
    })
    x = build_features(pairs)
    assert x.loc[0, "sim_nome_mae"] == 0.0 and x.loc[0, "ausente_nome_mae"] == 1.0
    assert x.loc[1, "sim_nome_mae"] == 0.0 and x.loc[1, "ausente_nome_mae"] == 0.0
    assert x.loc[0, "data_igual"] == 1.0 and x.loc[1, "data_ausente"] == 1.0
    assert x.isna().sum().sum() == 0


def test_first_name_similarity_separates_twins():
    std_a = pd.DataFrame({"id": ["A1"], "primeiro_nome": ["JOAO"]})
    std_b = pd.DataFrame({"id": ["B1", "B2", "B3"], "primeiro_nome": ["JOAO", "PEDRO", ""]})
    pairs = pd.DataFrame({"id_1": ["A1", "A1", "A1"], "id_2": ["B1", "B2", "B3"]})
    sim = first_name_similarity(pairs, std_a, std_b)
    assert sim[0] == 1.0 and sim[1] < 0.6 and np.isnan(sim[2])


def _assigned(scores, correct):
    ids = [f"A{i}" for i in range(len(scores))]
    frame = pd.DataFrame({"id_1": ids, "id_2": [f"B{i}" for i in range(len(scores))],
                          "pontuacao": scores, "sim_nome_mae": 0.5, "nivel_data": "igual"})
    truth = {(a, b) for a, b, c in zip(frame["id_1"], frame["id_2"], correct, strict=True) if c}
    return frame, truth


def test_thresholds_meet_precision_and_queue_targets():
    frame, truth = _assigned([0.99, 0.95, 0.90, 0.80, 0.60, 0.40],
                             [True, True, False, True, True, False])
    thr = choose_thresholds(frame, truth, n_true=4, min_precision=1.0, queue_size=3)
    assert thr == {"match": 0.95, "revisao": 0.60}
    op = operating_point(frame, truth, 4, thr)
    assert op["fp"] == 0 and op["pares_automaticos"] == 2
    assert op["fila_revisao"] == 3 and op["fila_verdadeiros"] == 2
    assert op["recall_com_revisao"] == 1.0


def test_thresholds_never_split_tied_scores():
    frame, truth = _assigned([0.9, 0.8, 0.8], [True, True, False])
    thr = choose_thresholds(frame, truth, n_true=2, min_precision=1.0, queue_size=1)
    assert thr["match"] == 0.9  # cutting at 0.8 would accept the false pair tied with a true one
    assert thr["revisao"] == 0.9  # the two tied pairs do not fit in a queue of one: no queue


@pytest.fixture(scope="module")
def ml_metrics(tmp_path_factory, sample_dir):
    root = tmp_path_factory.mktemp("proj_ml")
    shutil.copytree(sample_dir, root / "data")
    cfg = load_config(ROOT / "config" / "default.yaml")
    cfg["entrada"] = {k: f"data/{Path(v).name}" for k, v in cfg["entrada"].items()}
    cfg["ml"] = {"fracao_teste": 0.5, "semente": 42, "folds": 3}
    run_link(cfg, root)
    return run_ml(cfg, root), root


def test_run_ml_end_to_end(ml_metrics):
    m, root = ml_metrics
    assert (root / "reports" / "ml_metricas.json").exists()
    saved = json.loads((root / "reports" / "ml_metricas.json").read_text(encoding="utf-8"))
    assert saved == m
    assert set(m["resultados_teste"]) == {"regra_ponderada", *MODELS}
    d = m["divisao"]
    assert d["pares_treino"] > 0 and d["pares_teste"] > 0
    for r in m["resultados_teste"].values():
        t = r["teste"]
        assert 0 <= t["precisao"] <= 1 and 0 <= t["recall_com_revisao"] <= 1
        assert t["limiar_revisao"] <= t["limiar_match"]
    assert "sim_primeiro_nome" in m["coeficientes_regressao_logistica"]


def test_ablation_drops_first_name(ml_metrics):
    m, _ = ml_metrics
    assert "sim_primeiro_nome" in m["variaveis"]
    _, _, left_out = MODELS["regressao_logistica_sem_primeiro_nome"]
    assert "sim_primeiro_nome" in left_out

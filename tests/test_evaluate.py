import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from rlk.config import load_config
from rlk.evaluate import _prf, run_evaluate, threshold_sweep
from rlk.link import run_link
from rlk.report import num, pct

ROOT = Path(__file__).resolve().parents[1]


def test_prf():
    assert _prf(8, 10, 16) == (0.8, 0.5, pytest.approx(2 * 0.8 * 0.5 / 1.3))
    assert _prf(0, 0, 5)[0] == 1.0  # no prediction: precision is defined as 1


def test_sweep_counts_recall_per_b_record():
    assigned = pd.DataFrame({"id_1": ["A1", "A3", "A4"], "id_2": ["B1", "B2", "B3"],
                             "pontuacao": [0.95, 0.80, 0.60]})
    truth = {("A1", "B1"), ("A2", "B1"), ("A3", "B2")}  # A1 and A2 are the same person
    rows = {r["limiar"]: r for r in threshold_sweep(assigned, truth, n_true=2,
                                                     thresholds=[0.5, 0.9])}
    assert rows[0.9]["vp"] == 1 and rows[0.9]["recall"] == 0.5 and rows[0.9]["precisao"] == 1.0
    assert rows[0.5]["vp"] == 2 and rows[0.5]["fp"] == 1 and rows[0.5]["recall"] == 1.0


def test_number_formats_in_portuguese():
    assert pct(0.9931) == "99,3%" and num(15000000) == "15.000.000"


@pytest.fixture(scope="module")
def evaluated(tmp_path_factory, sample_dir):
    root = tmp_path_factory.mktemp("proj")
    shutil.copytree(sample_dir, root / "data")
    cfg = load_config(ROOT / "config" / "default.yaml")
    cfg = {**cfg, "entrada": {"base_a": "data/base_a.csv", "base_b": "data/base_b.csv",
                              "gabarito": "data/gabarito.csv"}, "saida": "reports"}
    run_link(cfg, root)
    return root / "reports", run_evaluate(cfg, root)


def test_metrics_file_and_ranges(evaluated):
    out, m = evaluated
    saved = json.loads((out / "metricas.json").read_text())
    assert saved == m
    for row in m["por_limiar"]:
        assert 0 <= row["precisao"] <= 1 and 0 <= row["recall"] <= 1
    # Recall can only fall as the threshold rises
    recalls = [r["recall"] for r in m["por_limiar"]]
    assert recalls == sorted(recalls, reverse=True)
    assert m["blocagem"]["completude_pares"] >= m["automatico"]["recall"]


def test_report_is_self_contained(evaluated):
    out, _ = evaluated
    html = (out / "relatorio.html").read_text()
    assert "Resumo executivo" in html and "Casos difíceis" in html and "<svg" in html
    assert "http://" not in html and "https://" not in html  # no external resources


def test_evaluate_is_deterministic(evaluated, tmp_path, sample_dir):
    out, m = evaluated
    first = (out / "relatorio.html").read_text()
    cfg = load_config(ROOT / "config" / "default.yaml")
    shutil.copytree(sample_dir, tmp_path / "data")
    cfg = {**cfg, "entrada": {"base_a": "data/base_a.csv", "base_b": "data/base_b.csv",
                              "gabarito": "data/gabarito.csv"}, "saida": "reports"}
    run_link(cfg, tmp_path)
    assert run_evaluate(cfg, tmp_path) == m
    assert (tmp_path / "reports" / "relatorio.html").read_text() == first


def test_match_scenarios_trade_false_positives_for_queue():
    from rlk.evaluate import match_scenarios

    assigned = pd.DataFrame({
        "id_1": ["A1", "A2", "A3", "A4"], "id_2": ["B1", "B2", "B3", "B4"],
        "pontuacao": [0.97, 0.92, 0.87, 0.75],
        "sim_nome_mae": [1.0, 1.0, 0.5, 1.0],
        "nivel_data": ["igual", "igual", "so_ano", "igual"],
    })
    truth = {("A1", "B1"), ("A3", "B3"), ("A4", "B4")}  # A2-B2 is a twin false positive
    rows = {r["limiar_match"]: r for r in match_scenarios(assigned, truth, 3, review=0.70)}
    assert rows[0.85]["fp"] == 1 and rows[0.85]["fp_perfil_gemeos"] == 1
    assert rows[0.85]["fila_revisao"] == 1
    assert rows[0.95]["fp"] == 0 and rows[0.95]["fila_revisao"] == 3
    assert rows[0.95]["recall_automatico"] == pytest.approx(1 / 3)

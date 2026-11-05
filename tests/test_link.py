import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from rlk.blocking import block_pairs, blocking_stats
from rlk.compare import compare_pairs, date_level, exact, name_similarity
from rlk.config import ConfigError, load_config, validate
from rlk.link import classify, resolve_one_to_one, run_link

ROOT = Path(__file__).resolve().parents[1]
CFG = load_config(ROOT / "config" / "default.yaml")


def _frame(rows):
    cols = ["id", "uf", "ano_nascimento", "fon_primeiro_nome", "sexo"]
    return pd.DataFrame(rows, columns=cols)


# ------------------------------------------------------------------ blocking
def test_blocking_union_and_empty_keys():
    a = _frame([("A1", "RR", "1990", "ANA", "F"), ("A2", "SP", "", "JOAO", "M")])
    b = _frame([("B1", "RR", "1990", "MARIA", "F"), ("B2", "AM", "", "JOAO", "M"),
                ("B3", "SP", "", "PEDRO", "M")])
    rules = [{"nome": "uf_ano", "chaves": ["uf", "ano_nascimento"]},
             {"nome": "nome_sexo", "chaves": ["fon_primeiro_nome", "sexo"]}]
    pairs = block_pairs(a, b, rules)
    assert set(zip(pairs["id_1"], pairs["id_2"], strict=True)) == {("A1", "B1"), ("A2", "B2")}
    # A2 x B3 share an empty year: an empty key is not evidence, so no pair
    stats = blocking_stats(pairs, 2, 3, rules)
    assert stats["pares_possiveis"] == 6 and stats["pares_candidatos"] == 2
    assert stats["pares_por_regra"] == {"uf_ano": 1, "nome_sexo": 1}


def test_blocking_pair_found_by_two_rules_is_counted_once():
    a = _frame([("A1", "RR", "1990", "ANA", "F")])
    b = _frame([("B1", "RR", "1990", "ANA", "F")])
    rules = [{"nome": "r1", "chaves": ["uf"]}, {"nome": "r2", "chaves": ["sexo"]}]
    pairs = block_pairs(a, b, rules)
    assert len(pairs) == 1 and pairs.loc[0, "regras"] == "r1+r2"


def test_dedup_blocking_keeps_each_pair_once():
    a = _frame([("A1", "RR", "1990", "ANA", "F"), ("A2", "RR", "1990", "ANA", "F")])
    pairs = block_pairs(a, None, [{"nome": "r", "chaves": ["uf"]}])
    assert list(zip(pairs["id_1"], pairs["id_2"], strict=True)) == [("A1", "A2")]


# ------------------------------------------------------------------ comparison
def test_name_similarity():
    assert name_similarity("MARIA SILVA", "MARIA SILVA") == 1.0
    assert name_similarity("MARIA SILVA SOUZA", "MARIA SOUZA SILVA") > \
        name_similarity("MARIA SILVA SOUZA", "PEDRO COSTA LIMA")
    assert name_similarity("", "MARIA") is None


@pytest.mark.parametrize(
    "a, b, level",
    [("1990-03-07", "1990-03-07", "igual"), ("1990-03-07", "1990-07-03", "dia_mes_trocado"),
     ("1990-03-07", "1990-11-20", "so_ano"), ("1990-03-07", "1991-03-07", "diferente"),
     ("", "1990-03-07", "ausente")],
)
def test_date_levels(a, b, level):
    assert date_level(a, b) == level


def test_exact_comparison():
    assert exact("F", "F") == 1.0 and exact("F", "M") == 0.0 and exact("", "M") is None


def test_score_ignores_missing_fields():
    cols = ["id", "nome", "nome_mae", "data_nascimento", "sexo", "municipio", "uf", "documento"]
    a = pd.DataFrame([("A1", "ANA LIMA", "RITA LIMA", "1990-01-02", "F", "MANAUS", "AM",
                       "123")], columns=cols)
    b = pd.DataFrame([("B1", "ANA LIMA", "", "1990-01-02", "F", "MANAUS", "AM", "")],
                     columns=cols)
    scored = compare_pairs(pd.DataFrame({"id_1": ["A1"], "id_2": ["B1"]}), a, b, CFG)
    assert scored.loc[0, "pontuacao"] == 1.0  # missing mother and document do not penalize
    b.loc[0, "sexo"] = "M"
    scored = compare_pairs(pd.DataFrame({"id_1": ["A1"], "id_2": ["B1"]}), a, b, CFG)
    assert 0 < scored.loc[0, "pontuacao"] < 1


# ------------------------------------------------------------------ classification
def test_classify_thresholds():
    thr = {"match": 0.85, "revisao": 0.70}
    assert [classify(s, thr) for s in (0.9, 0.85, 0.75, 0.69)] == \
        ["match", "match", "revisao", "nao_match"]


def test_one_to_one_keeps_highest_score():
    scored = pd.DataFrame({"id_1": ["A1", "A1", "A2", "A3"], "id_2": ["B1", "B2", "B1", "B3"],
                           "pontuacao": [0.95, 0.90, 0.92, 0.50]})
    out = resolve_one_to_one(scored, 0.7)
    assert set(zip(out["id_1"], out["id_2"], strict=True)) == {("A1", "B1")}


def test_config_validation():
    bad = {**CFG, "limiares": {"match": 0.6, "revisao": 0.8}}
    with pytest.raises(ConfigError):
        validate(bad)
    with pytest.raises(ConfigError):
        validate({**CFG, "pesos": {"cpf": 1.0}})


# ------------------------------------------------------------------ end to end on the sample
@pytest.fixture(scope="module")
def linked(tmp_path_factory, sample_dir):
    root = tmp_path_factory.mktemp("proj")
    shutil.copytree(sample_dir, root / "data")
    cfg = {**CFG, "entrada": {"base_a": "data/base_a.csv", "base_b": "data/base_b.csv",
                              "gabarito": "data/gabarito.csv"}, "saida": "reports"}
    summary = run_link(cfg, root)
    return root / "reports", summary


def test_outputs_exist(linked):
    out, summary = linked
    for name in ("matches.csv", "revisao_manual.csv", "nao_pareados.csv", "candidatos.csv",
                 "duplicatas_a.csv", "resumo_link.json"):
        assert (out / name).exists(), name
    assert json.loads((out / "resumo_link.json").read_text())["base_b"] == 120


def test_matches_are_one_to_one_and_mostly_right(linked, sample_bases):
    out, _ = linked
    m = pd.read_csv(out / "matches.csv", dtype=str)
    assert m["id_a"].is_unique and m["id_b"].is_unique
    g = sample_bases[2]
    truth = set(zip(g["id_1"], g["id_2"], strict=True))
    precision = sum((a, b) in truth for a, b in zip(m["id_a"], m["id_b"], strict=True)) / len(m)
    assert precision >= 0.9


def test_review_queue_is_side_by_side(linked):
    out, _ = linked
    r = pd.read_csv(out / "revisao_manual.csv", dtype=str)
    assert {"nome_completo_a", "nome_completo_b", "pontuacao", "decisao_revisor"} <= set(r.columns)
    if len(r):
        s = r["pontuacao"].astype(float)
        assert s.between(CFG["limiares"]["revisao"], CFG["limiares"]["match"]).all()


def test_unmatched_cover_every_b_record(linked):
    out, summary = linked
    n = pd.read_csv(out / "nao_pareados.csv", dtype=str)
    m = pd.read_csv(out / "matches.csv", dtype=str)
    r = pd.read_csv(out / "revisao_manual.csv", dtype=str)
    assert (n["base"] == "B").sum() + len(m) + len(r) == summary["base_b"]

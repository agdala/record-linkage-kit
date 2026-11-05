import pandas as pd

from rlk.generate import GeneratorConfig, SyntheticGenerator, generate

COLUMNS = ["id", "nome_completo", "nome_mae", "data_nascimento", "sexo", "municipio", "uf",
           "documento"]


def _small():
    return SyntheticGenerator(GeneratorConfig(n_a=400, n_b=250, seed=1)).build()


def test_columns_and_sizes():
    a, b, g = _small()
    assert list(a.columns) == COLUMNS and list(b.columns) == COLUMNS
    assert len(a) == 400 and len(b) == 250
    assert a["id"].is_unique and b["id"].is_unique


def test_same_seed_same_data(tmp_path):
    generate(tmp_path / "x", GeneratorConfig(n_a=100, n_b=60, seed=3))
    generate(tmp_path / "y", GeneratorConfig(n_a=100, n_b=60, seed=3))
    for name in ("base_a.csv", "base_b.csv", "gabarito.csv"):
        assert (tmp_path / "x" / name).read_text() == (tmp_path / "y" / name).read_text()


def test_overlap_and_duplicates():
    a, b, g = _small()
    links = g[g["tipo"] == "link"]
    # 60% of B people are also in A (one B record may match an A record and its duplicate)
    assert links["id_2"].nunique() == round(250 * 0.60)
    assert (g["tipo"] == "dedup").sum() == round(400 * 0.03)
    assert set(links["id_1"]) <= set(a["id"]) and set(links["id_2"]) <= set(b["id"])


def test_b_has_missing_documents_and_dates():
    _, b, _ = _small()
    doc_missing = (b["documento"] == "").mean()
    date_missing = (b["data_nascimento"] == "").mean()
    assert 0.30 < doc_missing < 0.50
    assert 0.0 < date_missing < 0.12


def test_b_uses_government_formats():
    _, b, _ = _small()
    assert set(b["sexo"]) <= {"FEMININO", "MASCULINO"}
    dated = b.loc[b["data_nascimento"] != "", "data_nascimento"]
    assert dated.str.fullmatch(r"\d{2}/\d{2}/\d{4}").all()
    assert (b["nome_completo"] == b["nome_completo"].str.upper()).all()


def test_sample_matches_ground_truth(sample_bases):
    a, b, g = sample_bases
    assert len(a) == 200 and len(b) == 120
    assert set(g["tipo"]) == {"link", "dedup"}
    assert not pd.Series(g["id_1"] + g["id_2"]).duplicated().any()

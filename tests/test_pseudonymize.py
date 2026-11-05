import shutil
from pathlib import Path

import pandas as pd
import pytest

from rlk.config import load_config
from rlk.pseudonymize import (
    KEYS,
    SaltError,
    get_salt,
    hash_value,
    match_hashed,
    pseudonymize_frame,
    run_pseudo,
)

ROOT = Path(__file__).resolve().parents[1]
SALT = b"s" * 32
KEY_NAMES = [k for k, _, _ in KEYS]


def test_salt_is_required(monkeypatch):
    monkeypatch.delenv("RLK_SALT", raising=False)
    with pytest.raises(SaltError):
        get_salt()
    monkeypatch.setenv("RLK_SALT", "curto")
    with pytest.raises(SaltError):
        get_salt()
    monkeypatch.setenv("RLK_SALT", "x" * 40)
    assert get_salt() == b"x" * 40


def test_hash_depends_on_salt_and_is_stable():
    assert hash_value("MARIA|1990-01-02", SALT) == hash_value("MARIA|1990-01-02", SALT)
    assert hash_value("MARIA|1990-01-02", SALT) != hash_value("MARIA|1990-01-02", b"t" * 32)
    assert len(hash_value("MARIA", SALT)) == 64 and hash_value("", SALT) == ""


def test_pseudonymized_output_has_only_id_and_hashes(sample_bases):
    a, _, _ = sample_bases
    h = pseudonymize_frame(a, SALT)
    assert list(h.columns) == ["id", *KEY_NAMES]
    for key in KEY_NAMES:
        assert h[key].str.fullmatch(r"([0-9a-f]{64})?").all()


def test_standardized_variants_get_the_same_hash():
    a = pd.DataFrame([{"id": "A1", "nome_completo": "José da Silva", "nome_mae": "Ana Silva",
                       "data_nascimento": "1990-01-02", "sexo": "M", "municipio": "Manaus",
                       "uf": "AM", "documento": "123.456.789-09"}])
    b = pd.DataFrame([{"id": "B1", "nome_completo": "JOSE SILVA", "nome_mae": "ANA SILVA",
                       "data_nascimento": "02/01/1990", "sexo": "MASCULINO",
                       "municipio": "MANAUS", "uf": "AM", "documento": "12345678909"}])
    ha, hb = pseudonymize_frame(a, SALT), pseudonymize_frame(b, SALT)
    for key in KEY_NAMES:
        assert ha.loc[0, key] == hb.loc[0, key]
    m = match_hashed(ha, hb)
    assert list(m.itertuples(index=False, name=None)) == [("A1", "B1", "k1_documento")]


def test_typo_breaks_exact_matching():
    """The cost of pseudonymization: one typo and no document means no match."""
    base = {"nome_mae": "", "data_nascimento": "1990-01-02", "sexo": "F",
            "municipio": "Manaus", "uf": "AM", "documento": ""}
    a = pd.DataFrame([{"id": "A1", "nome_completo": "Fernanda Lima", **base}])
    b = pd.DataFrame([{"id": "B1", "nome_completo": "Fernanda Lmia", **base}])
    assert match_hashed(pseudonymize_frame(a, SALT), pseudonymize_frame(b, SALT)).empty


def test_ambiguous_hashes_are_ignored():
    ha = pd.DataFrame({"id": ["A1", "A2"], **{k: ["h", "h"] for k in KEY_NAMES}})
    hb = pd.DataFrame({"id": ["B1"], **{k: ["h"] for k in KEY_NAMES}})
    assert match_hashed(ha, hb).empty


def test_run_pseudo_on_sample(tmp_path, sample_dir, monkeypatch):
    monkeypatch.setenv("RLK_SALT", "z" * 64)
    shutil.copytree(sample_dir, tmp_path / "data")
    cfg = load_config(ROOT / "config" / "default.yaml")
    cfg = {**cfg, "entrada": {"base_a": "data/base_a.csv", "base_b": "data/base_b.csv",
                              "gabarito": "data/gabarito.csv"}, "saida": "reports"}
    r = run_pseudo(cfg, tmp_path)
    assert r["cascata"]["precisao"] >= 0.95
    assert 0 < r["cascata"]["recall"] <= 1
    assert (tmp_path / "reports" / "pseudonimizado" / "base_b_hash.csv").exists()

from datetime import date

import pytest

from rlk.standardize import (
    PHONETIC_RULES,
    normalize_document,
    normalize_name,
    normalize_sex,
    normalize_text,
    parse_date,
    phonetic_key,
    phonetic_token,
    remove_particles,
    standardize_frame,
    strip_accents,
)


# ------------------------------------------------------------------ text
def test_uppercase():
    assert normalize_text("maria") == "MARIA"


def test_accents_removed():
    assert strip_accents("JOÃO ÁVILA ÑANDÚ") == "JOAO AVILA NANDU"
    assert normalize_text("Conceição") == "CONCEICAO"


def test_punctuation_becomes_space():
    assert normalize_text("D'Ávila-Souza.") == "D AVILA SOUZA"


def test_double_spaces_collapsed():
    assert normalize_text("  ANA    MARIA  ") == "ANA MARIA"


def test_missing_values():
    assert normalize_text(None) == "" and normalize_text(float("nan")) == ""


def test_particles_optional():
    assert remove_particles("JOSE DA SILVA DOS SANTOS") == "JOSE SILVA SANTOS"
    assert normalize_name("José da Silva", drop_particles=False) == "JOSE DA SILVA"
    assert normalize_name("José da Silva") == "JOSE SILVA"


# ------------------------------------------------------------------ phonetic: one test per rule
@pytest.mark.parametrize(
    "a, b",
    [
        ("Conceição", "Conseisao"),      # Ç -> S
        ("Helena", "Elena"),             # H inicial
        ("Raphael", "Rafael"),           # PH -> F
        ("Thais", "Tais"),               # TH -> T
        ("Guilherme", "Guilierme"),      # LH -> LI
        ("Marinho", "Marinio"),          # NH -> NI
        ("Shirlei", "Xirlei"),           # SH -> X
        ("Chaves", "Xaves"),             # CH -> X
        ("Nascimento", "Nasimento"),     # SC antes de E/I
        ("Cecilia", "Sesilia"),          # C antes de E/I
        ("Henrique", "Enrike"),          # QU antes de E/I
        ("Quadros", "Kuadros"),          # Q -> K
        ("Carlos", "Karlos"),            # C restante -> K
        ("Gisele", "Jisele"),            # G antes de E/I
        ("Yasmin", "Iasmin"),            # Y -> I
        ("Wagner", "Vagner"),            # W -> V
        ("Souza", "Sousa"),              # Z -> S
        ("Luiz", "Luis"),                # Z final -> S
        ("Alexandre", "Alesandre"),      # X entre vogais
        ("Vanessa", "Vanesa"),           # SS -> S
        ("Wilian", "William"),           # M final -> N, LL -> L
        ("Mattos", "Matos"),             # letras repetidas
    ],
)
def test_phonetic_equivalences(a, b):
    assert phonetic_key(a) == phonetic_key(b)


def test_phonetic_keeps_different_names_apart():
    assert phonetic_key("Maria") != phonetic_key("Mario")
    assert phonetic_key("Paulo") != phonetic_key("Pedro")


def test_phonetic_ignores_particles_and_accents():
    assert phonetic_key("Thaís de Souza") == "TAIS SOUSA"
    assert phonetic_key("") == ""


def test_every_rule_is_documented():
    assert all(desc and rx for desc, rx, _ in PHONETIC_RULES)
    assert phonetic_token("HH") == ""


# ------------------------------------------------------------------ other fields
@pytest.mark.parametrize(
    "value, expected",
    [("1990-03-07", date(1990, 3, 7)), ("07/03/1990", date(1990, 3, 7)),
     ("31/02/1990", None), ("", None), (None, None), ("1990", None)],
)
def test_parse_date(value, expected):
    assert parse_date(value) == expected


def test_sex_variants():
    assert [normalize_sex(v) for v in ("F", "feminino", "MASCULINO", "m", "X", "")] == \
        ["F", "F", "M", "M", "", ""]


def test_document_digits_only():
    assert normalize_document("123.456.789-09") == "12345678909"
    assert normalize_document("") == "" and normalize_document("000.000.000-00") == ""


def test_standardize_frame_on_sample(sample_bases):
    a, b, _ = sample_bases
    sa, sb = standardize_frame(a), standardize_frame(b)
    assert len(sa) == len(a) and len(sb) == len(b)
    # Both bases end up in the same format
    assert set(sa["sexo"]) <= {"F", "M"} and set(sb["sexo"]) <= {"F", "M"}
    assert sa["data_nascimento"].str.fullmatch(r"\d{4}-\d{2}-\d{2}").all()
    assert (sb["data_nascimento"] == "").sum() == (b["data_nascimento"] == "").sum()
    assert not sb["nome"].str.contains(r"[^A-Z0-9 ]").any()

"""Standardization of names, dates, sex, documents and places, plus a Portuguese phonetic key.

All functions are pure and work on single values, so each rule can be tested in isolation.
``standardize_frame`` applies them to a whole registry.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date

import pandas as pd

PARTICLES = frozenset({"DE", "DA", "DO", "DAS", "DOS", "E", "DEL", "LA", "LOS", "Y"})

_NON_ALNUM = re.compile(r"[^A-Z0-9 ]")
_SPACES = re.compile(r"\s+")


# --------------------------------------------------------------------- text
def strip_accents(text: str) -> str:
    """Remove diacritics: 'JOÃO' -> 'JOAO', 'ÇA' -> 'CA', 'Ñ' -> 'N'."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalize_text(text: str | None) -> str:
    """Uppercase, remove accents and punctuation, collapse spaces.

    >>> normalize_text("  maría-josé  d'ávila. ")
    'MARIA JOSE D AVILA'
    """
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return ""
    text = strip_accents(str(text)).upper()
    text = _NON_ALNUM.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def remove_particles(name: str) -> str:
    """Remove connecting particles (DE, DA, DOS, E...). Expects a normalized name."""
    return " ".join(t for t in name.split() if t not in PARTICLES)


def normalize_name(name: str | None, drop_particles: bool = True) -> str:
    text = normalize_text(name)
    return remove_particles(text) if drop_particles else text


# --------------------------------------------------------------------- phonetic key
# Rules are applied in this order to each token (the token is already normalized, except for Ç,
# which is handled first because accent removal would turn it into C). Documented in the README.
PHONETIC_RULES: list[tuple[str, str, str]] = [
    # (description, regex, replacement)
    ("Ç vira S", r"Ç", "S"),
    ("H inicial é mudo", r"^H", ""),
    ("PH vira F", r"PH", "F"),
    ("TH vira T", r"TH", "T"),
    ("LH vira LI", r"LH", "LI"),
    ("NH vira NI", r"NH", "NI"),
    ("CH e SH viram X", r"[CS]H", "X"),
    ("H restante é mudo", r"H", ""),
    ("SC antes de E/I vira S", r"SC(?=[EI])", "S"),
    ("C antes de E/I vira S", r"C(?=[EI])", "S"),
    ("QU antes de E/I vira K", r"QU(?=[EI])", "K"),
    ("Q vira K", r"Q", "K"),
    ("C restante vira K", r"C", "K"),
    ("G antes de E/I vira J", r"G(?=[EI])", "J"),
    ("Y vira I", r"Y", "I"),
    ("W vira V", r"W", "V"),
    ("Z vira S", r"Z", "S"),
    ("X entre vogais vira S", r"(?<=[AEIOU])X(?=[AEIOU])", "S"),
    ("SS vira S", r"SS", "S"),
    ("M antes de consoante ou no fim vira N", r"M(?=[^AEIOU]|$)", "N"),
    ("Letras repetidas viram uma", r"(.)\1+", r"\1"),
]
_COMPILED = [(re.compile(rx), rep) for _, rx, rep in PHONETIC_RULES]


def phonetic_token(token: str) -> str:
    token = token.upper().strip()
    token = token.replace("Ç", "S")
    token = strip_accents(token)
    token = re.sub(r"[^A-Z]", "", token)
    for rx, rep in _COMPILED:
        token = rx.sub(rep, token)
    return token


def phonetic_key(name: str | None, drop_particles: bool = True) -> str:
    """Phonetic key of a name, token by token.

    >>> phonetic_key("Thaís de Souza")
    'TAIS SOUSA'
    """
    if not name:
        return ""
    upper = str(name).upper().replace("Ç", "S")
    tokens = normalize_text(upper).split()
    if drop_particles:
        tokens = [t for t in tokens if t not in PARTICLES]
    return " ".join(k for k in (phonetic_token(t) for t in tokens) if k)


# --------------------------------------------------------------------- other fields
def parse_date(value: str | None) -> date | None:
    """Accept ISO (YYYY-MM-DD) and Brazilian (DD/MM/YYYY) formats. Invalid -> None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    value = str(value).strip()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", value)
    if m:
        y, mo, d = (int(x) for x in m.groups())
    else:
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", value)
        if not m:
            return None
        d, mo, y = (int(x) for x in m.groups())
    try:
        return date(y, mo, d)
    except ValueError:
        return None


_SEX = {"F": "F", "FEMININO": "F", "FEM": "F", "MULHER": "F",
        "M": "M", "MASCULINO": "M", "MASC": "M", "HOMEM": "M"}


def normalize_sex(value: str | None) -> str:
    """Map the variants to F / M. Anything else becomes '' (unknown)."""
    return _SEX.get(normalize_text(value), "")


def normalize_document(value: str | None) -> str:
    """Keep digits only; empty or all-zero documents become ''."""
    digits = re.sub(r"\D", "", str(value or ""))
    return "" if not digits or set(digits) == {"0"} else digits


# --------------------------------------------------------------------- frame
def standardize_frame(df: pd.DataFrame, drop_particles: bool = True) -> pd.DataFrame:
    """Return a standardized copy with the derived columns used by blocking and comparison."""
    out = pd.DataFrame({"id": df["id"].astype(str)})
    out["nome"] = df["nome_completo"].map(lambda v: normalize_name(v, drop_particles))
    out["nome_mae"] = df["nome_mae"].map(lambda v: normalize_name(v, drop_particles))
    dates = df["data_nascimento"].map(parse_date)
    out["data_nascimento"] = dates.map(lambda d: d.isoformat() if d else "")
    out["ano_nascimento"] = dates.map(lambda d: str(d.year) if d else "")
    out["sexo"] = df["sexo"].map(normalize_sex)
    out["municipio"] = df["municipio"].map(normalize_text)
    out["uf"] = df["uf"].map(normalize_text)
    out["documento"] = df["documento"].map(normalize_document)
    tokens = out["nome"].str.split()
    out["primeiro_nome"] = tokens.map(lambda t: t[0] if t else "")
    out["ultimo_sobrenome"] = tokens.map(lambda t: t[-1] if len(t) > 1 else "")
    out["fon_primeiro_nome"] = out["primeiro_nome"].map(phonetic_key)
    out["fon_ultimo_sobrenome"] = out["ultimo_sobrenome"].map(phonetic_key)
    out["fon_nome"] = out["nome"].map(phonetic_key)
    return out


def read_registry(path) -> pd.DataFrame:
    """Read a registry CSV keeping every value as text and missing values as ''."""
    return pd.read_csv(path, dtype=str, keep_default_na=False)

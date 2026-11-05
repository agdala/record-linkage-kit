"""Pseudonymized sharing mode.

Two organizations agree on a secret salt (exchanged out of band, never versioned) and each one
hashes standardized keys of its own registry with SHA-256. Only the hashes are exchanged, so
names never travel in clear text. Matching becomes exact: equal hashes mean equal keys.

Limits (documented in docs/protecao_de_dados.md):
* the hashes are pseudonymous, not anonymous data: whoever holds the salt can rebuild them
  from a list of candidate names and dates (dictionary attack);
* exact matching loses every pair with a typo or a different date in the key fields;
* it does not replace a data sharing agreement between the parties.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path

import pandas as pd

from rlk.standardize import phonetic_key, read_registry, standardize_frame

SALT_ENV = "RLK_SALT"
MIN_SALT_LENGTH = 32

# Keys tried in order (cascade). Each key is built only when all its parts exist.
KEYS: list[tuple[str, str, list[str]]] = [
    ("k1_documento", "documento", ["documento"]),
    ("k2_nome_data", "nome + data de nascimento", ["nome", "data_nascimento"]),
    ("k3_fonetica_data_mae", "nome fonético + data + nome fonético da mãe",
     ["fon_nome", "data_nascimento", "fon_nome_mae"]),
    ("k4_fonetica_ano_municipio", "nome fonético + ano + sexo + município",
     ["fon_nome", "ano_nascimento", "sexo", "municipio", "uf"]),
]


class SaltError(RuntimeError):
    pass


def get_salt() -> bytes:
    salt = os.environ.get(SALT_ENV, "")
    if len(salt) < MIN_SALT_LENGTH:
        raise SaltError(
            f"Defina a variável de ambiente {SALT_ENV} com um sal secreto de pelo menos "
            f"{MIN_SALT_LENGTH} caracteres (ex.: python -c \"import secrets; "
            f"print(secrets.token_hex(32))\"). O sal nunca deve ser versionado."
        )
    return salt.encode("utf-8")


def hash_value(value: str, salt: bytes) -> str:
    """Keyed SHA-256 (HMAC) of a standardized value. Empty value -> empty hash."""
    if not value:
        return ""
    return hmac.new(salt, value.encode("utf-8"), hashlib.sha256).hexdigest()


def pseudonymize_frame(raw: pd.DataFrame, salt: bytes) -> pd.DataFrame:
    """Return only the record id and the hashed keys: no name, date or document in clear."""
    std = standardize_frame(raw)
    std["fon_nome_mae"] = std["nome_mae"].map(phonetic_key)
    out = pd.DataFrame({"id": std["id"]})
    for key, _, parts in KEYS:
        complete = (std[parts] != "").all(axis=1)
        joined = std[parts].astype(str).agg("|".join, axis=1).where(complete, "")
        out[key] = [hash_value(v, salt) for v in joined]
    return out


def match_hashed(ha: pd.DataFrame, hb: pd.DataFrame) -> pd.DataFrame:
    """Exact matching on hashes, key by key (cascade), with 1:1 resolution.

    A key whose hash is shared by more than one record on either side is ambiguous and ignored
    for those records (it could be two homonyms born on the same day).
    """
    used_a: set[str] = set()
    used_b: set[str] = set()
    found = []
    for key, _, _ in KEYS:
        a = ha.loc[(ha[key] != "") & ~ha["id"].isin(used_a), ["id", key]]
        b = hb.loc[(hb[key] != "") & ~hb["id"].isin(used_b), ["id", key]]
        a = a[~a[key].duplicated(keep=False)]
        b = b[~b[key].duplicated(keep=False)]
        pairs = a.merge(b, on=key, suffixes=("_a", "_b"))
        for ia, ib in zip(pairs["id_a"], pairs["id_b"], strict=True):
            if ia in used_a or ib in used_b:
                continue
            used_a.add(ia)
            used_b.add(ib)
            found.append((ia, ib, key))
    return pd.DataFrame(found, columns=["id_a", "id_b", "chave"])


def run_pseudo(cfg: dict, root: str | Path = ".") -> dict:
    """Hash both bases, match on hashes and measure the result against the ground truth."""
    root = Path(root)
    salt = get_salt()
    out_dir = root / cfg["saida"]
    pseudo_dir = out_dir / "pseudonimizado"
    pseudo_dir.mkdir(parents=True, exist_ok=True)
    ha = pseudonymize_frame(read_registry(root / cfg["entrada"]["base_a"]), salt)
    hb = pseudonymize_frame(read_registry(root / cfg["entrada"]["base_b"]), salt)
    ha.to_csv(pseudo_dir / "base_a_hash.csv", index=False)
    hb.to_csv(pseudo_dir / "base_b_hash.csv", index=False)
    matches = match_hashed(ha, hb)
    matches.to_csv(pseudo_dir / "matches_hash.csv", index=False)

    gab = read_registry(root / cfg["entrada"]["gabarito"])
    link = gab[gab["tipo"] == "link"]
    truth = set(zip(link["id_1"], link["id_2"], strict=True))
    n_true = link["id_2"].nunique()

    def metrics(df: pd.DataFrame) -> dict:
        tp = sum((a, b) in truth for a, b in zip(df["id_a"], df["id_b"], strict=True))
        p = tp / len(df) if len(df) else 1.0
        r = tp / n_true if n_true else 1.0
        return {"pares": int(len(df)), "vp": int(tp), "precisao": round(p, 4),
                "recall": round(r, 4)}

    per_key = []
    for key, desc, _ in KEYS:
        # Each key on its own, to show what exact matching recovers with each piece of data
        alone = match_hashed(ha[["id", key]].assign(**{k: "" for k, _, _ in KEYS if k != key}),
                             hb[["id", key]].assign(**{k: "" for k, _, _ in KEYS if k != key}))
        per_key.append({"chave": key, "descricao": desc, **metrics(alone)})
    result = {"por_chave": per_key, "cascata": metrics(matches),
              "por_chave_na_cascata": matches["chave"].value_counts().sort_index().to_dict()}
    with open(out_dir / "pseudo_metricas.json", "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    return result

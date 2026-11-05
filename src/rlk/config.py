"""Load and validate the YAML configuration."""

from __future__ import annotations

from pathlib import Path

import yaml

REQUIRED = ("entrada", "saida", "blocagem", "pesos", "niveis_data", "limiares")
FIELDS = ("nome", "nome_mae", "data_nascimento", "sexo", "municipio", "documento")


class ConfigError(ValueError):
    pass


def load_config(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    validate(cfg)
    return cfg


def validate(cfg: dict) -> None:
    missing = [k for k in REQUIRED if k not in cfg]
    if missing:
        raise ConfigError(f"Seções ausentes na configuração: {missing}")
    unknown = set(cfg["pesos"]) - set(FIELDS)
    if unknown:
        raise ConfigError(f"Campos sem comparador definido em 'pesos': {sorted(unknown)}")
    if any(w < 0 for w in cfg["pesos"].values()) or sum(cfg["pesos"].values()) <= 0:
        raise ConfigError("Os pesos devem ser não negativos e somar mais que zero.")
    lim = cfg["limiares"]
    if not 0 <= lim["revisao"] <= lim["match"] <= 1:
        raise ConfigError("Os limiares devem respeitar 0 <= revisao <= match <= 1.")
    if not cfg["blocagem"]:
        raise ConfigError("Defina ao menos uma regra de blocagem.")
    for rule in cfg["blocagem"]:
        if not rule.get("nome") or not rule.get("chaves"):
            raise ConfigError(f"Regra de blocagem incompleta: {rule}")

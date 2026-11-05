"""Synthetic data generator.

Creates two registries of people that partially overlap, with realistic errors:

* ``base_a.csv``: "cadastro operacional" (operational registry), with ~3% internal duplicates.
* ``base_b.csv``: "lista governamental" (government list), different formats and typing errors.
* ``gabarito.csv``: ground truth with every true pair (A x B links and A x A duplicates).

Everything is 100% synthetic (Faker + fixed seed). No real person is represented.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from faker import Faker

PARTICLES = ("de", "da", "do", "das", "dos")

# (municipality, UF, weight). Real municipality names are public reference data, not personal data.
# The weights mimic a registry of refugees and migrants: Roraima and Amazonas as entry points,
# and the destinations of the "interiorização" strategy in the South and Southeast.
MUNICIPALITIES: list[tuple[str, str, int]] = [
    ("Boa Vista", "RR", 18), ("Pacaraima", "RR", 6), ("Manaus", "AM", 12),
    ("São Paulo", "SP", 10), ("Guarulhos", "SP", 2), ("Campinas", "SP", 2),
    ("Curitiba", "PR", 6), ("Cascavel", "PR", 2), ("Toledo", "PR", 1),
    ("São José dos Pinhais", "PR", 1), ("Florianópolis", "SC", 3), ("Chapecó", "SC", 3),
    ("Joinville", "SC", 2), ("Itajaí", "SC", 1), ("Blumenau", "SC", 1),
    ("Porto Alegre", "RS", 4), ("Caxias do Sul", "RS", 2), ("Esteio", "RS", 1),
    ("Rio de Janeiro", "RJ", 4), ("Belo Horizonte", "MG", 3), ("Brasília", "DF", 3),
    ("Goiânia", "GO", 2), ("Cuiabá", "MT", 2), ("Campo Grande", "MS", 2),
    ("Dourados", "MS", 2), ("Belém", "PA", 2), ("Santarém", "PA", 1),
    ("Porto Velho", "RO", 1), ("Rio Branco", "AC", 1), ("Recife", "PE", 1),
    ("Salvador", "BA", 1), ("Fortaleza", "CE", 1), ("São Luís", "MA", 1),
    ("Vitória", "ES", 1), ("Natal", "RN", 1), ("João Pessoa", "PB", 1),
]

# Probabilities of each error applied to the B copy of a shared person.
B_ERRORS = {
    "sem_acento": 0.60,           # government list without accents
    "sem_particulas": 0.30,       # "de", "da", "dos" removed
    "digitacao": 0.25,            # one or two typing errors in the name
    "digitacao_mae": 0.10,        # typing error in the mother's name
    "sobrenomes_invertidos": 0.10,
    "nome_abreviado": 0.10,       # middle names reduced to initials
    "dia_mes_trocado": 0.08,
    "data_aproximada": 0.05,      # unknown day and month recorded as 01/01 (common in the field)
    "mudou_municipio": 0.10,      # internal relocation (e.g. interiorização)
    "nome_mae_ausente": 0.15,
}
B_DOC_MISSING = 0.40
B_DATE_MISSING = 0.05
A_DOC_MISSING = 0.10


@dataclass
class Person:
    pid: int
    first: list[str]
    surnames: list[str]  # may contain particles, e.g. ["da", "Silva", "Souza"]
    mother: str
    birth: date
    sex: str
    municipality: str
    uf: str
    document: str
    tags: list[str] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        return " ".join(self.first + self.surnames)


@dataclass
class GeneratorConfig:
    n_a: int = 5000
    n_b: int = 3000
    overlap: float = 0.60       # share of B people who are also in A
    dup_rate_a: float = 0.03    # share of A records that are internal duplicates
    sibling_rate_b: float = 0.10  # share of B-only people who are siblings of someone in A
    spanish_share: float = 0.35  # share of people with Spanish-speaking names
    seed: int = 42


class SyntheticGenerator:
    def __init__(self, cfg: GeneratorConfig):
        self.cfg = cfg
        self.rng = random.Random(cfg.seed)
        self.fk_pt = Faker("pt_BR")
        self.fk_es = Faker("es_CO")
        self.fk_pt.seed_instance(cfg.seed)
        self.fk_es.seed_instance(cfg.seed + 1)
        self._pid = 0
        names, weights = zip(*[(m[:2], m[2]) for m in MUNICIPALITIES], strict=True)
        self._mun_names, self._mun_weights = list(names), list(weights)

    # ---------------------------------------------------------------- people
    def _faker(self, spanish: bool) -> Faker:
        return self.fk_es if spanish else self.fk_pt

    def _surname(self, fk: Faker) -> list[str]:
        s = fk.last_name()
        parts = s.split()
        if parts[0].lower() not in PARTICLES and self.rng.random() < 0.15:
            particle = "dos" if parts[0].endswith("s") else self.rng.choice(("de", "da"))
            parts = [particle, *parts]
        return parts

    def _first(self, fk: Faker, sex: str) -> list[str]:
        gen = fk.first_name_female if sex == "F" else fk.first_name_male
        first = gen().split()
        if len(first) == 1 and self.rng.random() < 0.25:
            first.append(gen().split()[0])
        return first

    def _municipality(self) -> tuple[str, str]:
        return self.rng.choices(self._mun_names, weights=self._mun_weights, k=1)[0]

    def new_person(self, spanish: bool | None = None, family: Person | None = None) -> Person:
        if spanish is None:
            spanish = self.rng.random() < self.cfg.spanish_share
        fk = self._faker(spanish)
        sex = self.rng.choice("FM")
        if family is None:
            mother_surname = self._surname(fk)
            father_surname = self._surname(fk)
            grand = self._surname(fk)
            mother = " ".join(self._first(fk, "F") + grand + mother_surname)
            surnames = mother_surname + father_surname
            if self.rng.random() < 0.15:
                surnames = surnames + self._surname(fk)
            birth = date(1940, 1, 1) + timedelta(days=self.rng.randrange(0, 365 * 84))
            municipality, uf = self._municipality()
        else:
            surnames, mother = list(family.surnames), family.mother
            # Siblings: same mother, surnames and place. Half of them are twins (same birth date).
            if self.rng.random() < 0.5:
                birth = family.birth
            else:
                gap = self.rng.choice((-1, 1)) * self.rng.randrange(300, 3000)
                birth = family.birth + timedelta(days=gap)
            municipality, uf = family.municipality, family.uf
        first = self._first(fk, sex)
        self._pid += 1
        return Person(self._pid, first, surnames, mother, birth, sex, municipality, uf,
                      self.fk_pt.cpf())

    # ---------------------------------------------------------------- errors
    def _typo(self, name: str) -> str:
        tokens = name.split()
        idx = [i for i, t in enumerate(tokens) if len(t) > 3]
        if not idx:
            return name
        i = self.rng.choice(idx)
        w = list(tokens[i])
        pos = self.rng.randrange(1, len(w) - 1)
        kind = self.rng.choice(("sub", "del", "swap", "dup"))
        if kind == "sub":
            w[pos] = self.rng.choice("aeiourstnlm")
        elif kind == "del":
            del w[pos]
        elif kind == "swap":
            w[pos], w[pos + 1] = w[pos + 1], w[pos]
        else:
            w.insert(pos, w[pos])
        tokens[i] = "".join(w)
        return " ".join(tokens)

    @staticmethod
    def _strip_accents(s: str) -> str:
        import unicodedata

        return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))

    def _b_copy(self, p: Person) -> tuple[dict, list[str]]:
        """Return the government-list version of a person and the errors applied."""
        r = self.rng.random
        errors: list[str] = []
        first, surnames = list(p.first), list(p.surnames)
        if r() < B_ERRORS["sem_particulas"] and any(s.lower() in PARTICLES for s in surnames):
            surnames = [s for s in surnames if s.lower() not in PARTICLES]
            errors.append("sem_particulas")
        core = [s for s in surnames if s.lower() not in PARTICLES]
        if r() < B_ERRORS["sobrenomes_invertidos"] and len(core) >= 2:
            surnames = core[1:] + core[:1]
            errors.append("sobrenomes_invertidos")
        if r() < B_ERRORS["nome_abreviado"] and (len(first) > 1 or len(core) > 2):
            if len(first) > 1:
                first = [first[0]] + [f[0] + "." for f in first[1:]]
            else:
                # Abbreviate the middle surname: "Ana Souza Lima Rocha" -> "Ana S. Lima Rocha"
                k = next(i for i, s in enumerate(surnames) if s.lower() not in PARTICLES)
                surnames = surnames[:k] + [surnames[k][0] + "."] + surnames[k + 1 :]
            errors.append("nome_abreviado")
        name = " ".join(first + surnames)
        if r() < B_ERRORS["digitacao"]:
            name = self._typo(name)
            if r() < 0.3:
                name = self._typo(name)
            errors.append("digitacao")
        mother = p.mother
        if r() < B_ERRORS["nome_mae_ausente"]:
            mother = ""
            errors.append("nome_mae_ausente")
        elif r() < B_ERRORS["digitacao_mae"]:
            mother = self._typo(mother)
            errors.append("digitacao_mae")
        if r() < B_ERRORS["sem_acento"]:
            name, mother = self._strip_accents(name), self._strip_accents(mother)
            errors.append("sem_acento")
        birth = p.birth
        if r() < B_ERRORS["dia_mes_trocado"] and birth.day <= 12 and birth.day != birth.month:
            birth = date(birth.year, birth.day, birth.month)
            errors.append("dia_mes_trocado")
        if r() < B_ERRORS["data_aproximada"] and (birth.day, birth.month) != (1, 1):
            birth = date(birth.year, 1, 1)
            errors.append("data_aproximada")
        birth_str = birth.strftime("%d/%m/%Y")
        if r() < B_DATE_MISSING:
            birth_str = ""
            errors.append("data_ausente")
        municipality, uf = p.municipality, p.uf
        if r() < B_ERRORS["mudou_municipio"]:
            while (municipality, uf) == (p.municipality, p.uf):
                municipality, uf = self._municipality()
            errors.append("mudou_municipio")
        document = p.document.replace(".", "").replace("-", "")
        if r() < B_DOC_MISSING:
            document = ""
            errors.append("documento_ausente")
        record = {
            "nome_completo": name.upper(),
            "nome_mae": mother.upper(),
            "data_nascimento": birth_str,
            "sexo": {"F": "FEMININO", "M": "MASCULINO"}[p.sex],
            "municipio": municipality.upper(),
            "uf": uf,
            "documento": document,
        }
        return record, errors

    def _a_copy(self, p: Person, duplicate: bool = False) -> tuple[dict, list[str]]:
        errors: list[str] = []
        name = p.full_name
        document = p.document
        if duplicate:
            # Re-registration of the same person by another team: small variations.
            options = ["digitacao", "nome_abreviado", "documento_ausente", "sem_acento"]
            for e in self.rng.sample(options, k=self.rng.randint(1, 2)):
                if e == "digitacao":
                    name = self._typo(name)
                elif e == "nome_abreviado" and len(p.first) > 1:
                    name = " ".join([p.first[0], p.first[1][0] + "."] + p.surnames)
                elif e == "documento_ausente":
                    document = ""
                elif e == "sem_acento":
                    name = self._strip_accents(name)
                else:
                    continue
                errors.append(e)
        if self.rng.random() < A_DOC_MISSING:
            document = ""
        record = {
            "nome_completo": name,
            "nome_mae": p.mother,
            "data_nascimento": p.birth.isoformat(),
            "sexo": p.sex,
            "municipio": p.municipality,
            "uf": p.uf,
            "documento": document,
        }
        return record, errors

    # ---------------------------------------------------------------- build
    def build(self) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        cfg = self.cfg
        n_dup = round(cfg.n_a * cfg.dup_rate_a)
        n_unique_a = cfg.n_a - n_dup
        n_shared = round(cfg.n_b * cfg.overlap)
        n_b_only = cfg.n_b - n_shared
        n_siblings = round(n_b_only * cfg.sibling_rate_b)

        people_a = [self.new_person() for _ in range(n_unique_a)]
        rows_a: list[tuple[Person, dict, list[str]]] = []
        for p in people_a:
            rec, err = self._a_copy(p)
            rows_a.append((p, rec, err))
        for p in self.rng.sample(people_a, n_dup):
            rec, err = self._a_copy(p, duplicate=True)
            rows_a.append((p, rec, err))
        self.rng.shuffle(rows_a)

        shared = self.rng.sample(people_a, n_shared)
        siblings = [self.new_person(family=f) for f in self.rng.sample(people_a, n_siblings)]
        b_only = [self.new_person() for _ in range(n_b_only - n_siblings)] + siblings
        rows_b: list[tuple[Person, dict, list[str]]] = []
        for p in shared + b_only:
            rec, err = self._b_copy(p)
            rows_b.append((p, rec, err))
        self.rng.shuffle(rows_b)

        def frame(rows, prefix):
            df = pd.DataFrame([rec for _, rec, _ in rows])
            df.insert(0, "id", [f"{prefix}{i:05d}" for i in range(1, len(rows) + 1)])
            return df

        base_a, base_b = frame(rows_a, "A"), frame(rows_b, "B")

        # Ground truth
        a_by_pid: dict[int, list[str]] = {}
        a_err: dict[str, list[str]] = {}
        for rid, (p, _, err) in zip(base_a["id"], rows_a, strict=True):
            a_by_pid.setdefault(p.pid, []).append(rid)
            a_err[rid] = err
        truth = []
        for rid_b, (p, _, err) in zip(base_b["id"], rows_b, strict=True):
            for rid_a in a_by_pid.get(p.pid, []):
                truth.append((rid_a, rid_b, "link", ";".join(err)))
        for ids in a_by_pid.values():
            if len(ids) > 1:
                first, second = sorted(ids)
                errs = a_err[first] or a_err[second]
                truth.append((first, second, "dedup", ";".join(errs)))
        gabarito = pd.DataFrame(truth, columns=["id_1", "id_2", "tipo", "erros"])
        gabarito = gabarito.sort_values(["tipo", "id_1", "id_2"]).reset_index(drop=True)
        return base_a, base_b, gabarito


def generate(out_dir: str | Path, cfg: GeneratorConfig | None = None) -> dict[str, int]:
    """Generate the synthetic bases into ``out_dir`` and return a short summary."""
    cfg = cfg or GeneratorConfig()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    base_a, base_b, gabarito = SyntheticGenerator(cfg).build()
    base_a.to_csv(out / "base_a.csv", index=False)
    base_b.to_csv(out / "base_b.csv", index=False)
    gabarito.to_csv(out / "gabarito.csv", index=False)
    return {
        "base_a": len(base_a),
        "base_b": len(base_b),
        "pares_link": int((gabarito["tipo"] == "link").sum()),
        "pares_dedup": int((gabarito["tipo"] == "dedup").sum()),
    }

"""Evaluation against the ground truth: precision, recall and F1 by threshold, blocking quality,
deduplication quality, recall by error type and a selection of hard cases."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from rlk.link import RAW_FIELDS, resolve_one_to_one
from rlk.standardize import read_registry

SWEEP = [round(0.50 + 0.05 * i, 2) for i in range(10)]  # 0.50 ... 0.95
MATCH_SCENARIOS = [0.85, 0.90, 0.95]  # candidate auto-match thresholds compared in the README

ERROR_LABELS = {
    "sem_acento": "acentos removidos",
    "sem_particulas": "partículas removidas",
    "digitacao": "erro de digitação no nome",
    "digitacao_mae": "erro de digitação no nome da mãe",
    "sobrenomes_invertidos": "sobrenomes em outra ordem",
    "nome_abreviado": "nome abreviado",
    "dia_mes_trocado": "dia e mês trocados",
    "data_aproximada": "data aproximada (01/01)",
    "data_ausente": "data ausente",
    "mudou_municipio": "mudou de município",
    "nome_mae_ausente": "nome da mãe ausente",
    "documento_ausente": "documento ausente",
}


def _prf(tp: int, n_pred: int, n_true: int) -> tuple[float, float, float]:
    p = tp / n_pred if n_pred else 1.0
    r = tp / n_true if n_true else 1.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def threshold_sweep(assigned: pd.DataFrame, truth: set, n_true: int,
                    thresholds: list[float] = SWEEP) -> list[dict]:
    """Metrics of the 1:1 assignment when every pair at or above ``t`` is accepted.

    Greedy 1:1 resolution by descending score gives the same pairs above ``t`` whether it runs
    on all candidates or only on those above ``t``, so a single assignment serves every threshold.
    Recall is measured per B record: a B record with a true counterpart is found if it is linked
    to any A record of the same person (A may hold that person twice).
    """
    hit = [(a, b) in truth for a, b in zip(assigned["id_1"], assigned["id_2"], strict=True)]
    assigned = assigned.assign(correto=hit)
    rows = []
    for t in thresholds:
        sel = assigned[assigned["pontuacao"] >= t]
        tp = int(sel["correto"].sum())
        p, r, f = _prf(tp, len(sel), n_true)
        rows.append({"limiar": t, "pares": int(len(sel)), "vp": tp, "fp": int(len(sel) - tp),
                     "fn": int(n_true - tp), "precisao": p, "recall": r, "f1": f})
    return rows


def match_scenarios(assigned: pd.DataFrame, truth: set, n_true: int, review: float,
                    thresholds: list[float] = MATCH_SCENARIOS) -> list[dict]:
    """Cost of each candidate auto-match threshold, keeping the review threshold fixed.

    For each ``t``: false positives accepted automatically (and how many have the twin profile:
    same mother and same birth date), automatic recall and the size of the review queue
    (pairs between ``review`` and ``t``).
    """
    hit = [(a, b) in truth for a, b in zip(assigned["id_1"], assigned["id_2"], strict=True)]
    asg = assigned.assign(correto=hit)
    rows = []
    for t in thresholds:
        auto = asg[asg["pontuacao"] >= t]
        fp = auto[~auto["correto"]]
        twins = fp[(fp["sim_nome_mae"].fillna(0) >= 0.95) & (fp["nivel_data"] == "igual")]
        queue = asg[asg["pontuacao"].between(review, t, inclusive="left")]
        tp = int(auto["correto"].sum())
        p, r, _ = _prf(tp, len(auto), n_true)
        rows.append({"limiar_match": t, "pares_automaticos": int(len(auto)), "fp": int(len(fp)),
                     "fp_perfil_gemeos": int(len(twins)), "precisao": p, "recall_automatico": r,
                     "fila_revisao": int(len(queue)),
                     "fila_verdadeiros": int(queue["correto"].sum())})
    return rows


def _pair_set(df: pd.DataFrame) -> set:
    return set(zip(df["id_1"], df["id_2"], strict=True))


def _describe_errors(tags: str) -> str:
    items = [ERROR_LABELS.get(t, t) for t in str(tags).split(";") if t]
    return ", ".join(items) if items else "nenhum erro introduzido"


def _case(kind: str, row: pd.Series, raw_a: pd.DataFrame, raw_b: pd.DataFrame,
          comment: str) -> dict:
    a = raw_a.loc[row["id_1"]]
    b = raw_b.loc[row["id_2"]]
    return {
        "tipo": kind,
        "id_a": row["id_1"],
        "id_b": row["id_2"],
        "pontuacao": float(row["pontuacao"]),
        "campos": [{"campo": f, "a": a[f], "b": b[f]} for f in RAW_FIELDS],
        "similaridades": {k: (None if pd.isna(row[k]) else float(row[k]))
                          for k in row.index if k.startswith("sim_")},
        "comentario": comment,
    }


def hard_cases(scored: pd.DataFrame, assigned: pd.DataFrame, gab_link: pd.DataFrame,
               raw_a: pd.DataFrame, raw_b: pd.DataFrame, thr: dict) -> list[dict]:
    """Pick five instructive cases and comment them from the data (not hand-written)."""
    truth = _pair_set(gab_link)
    errors = {(a, b): e for a, b, e in zip(gab_link["id_1"], gab_link["id_2"],
                                            gab_link["erros"], strict=True)}
    keys = list(zip(scored["id_1"], scored["id_2"], strict=True))
    scored = scored.assign(correto=[k in truth for k in keys],
                           erros=[errors.get(k, "") for k in keys])
    asg = assigned.assign(correto=[(a, b) in truth for a, b in zip(assigned["id_1"],
                                                                    assigned["id_2"],
                                                                    strict=True)])
    found_b = set(asg.loc[asg["correto"], "id_2"])
    cases: list[dict] = []
    used: set = set()

    def unused(df):
        return df[[(a, b) not in used for a, b in zip(df["id_1"], df["id_2"], strict=True)]]

    def add(kind, row, comment):
        cases.append(_case(kind, row, raw_a, raw_b, comment))
        used.add((row["id_1"], row["id_2"]))

    # 1. Highest-scoring false positive accepted automatically
    fp = asg[(~asg["correto"]) & (asg["pontuacao"] >= thr["match"])]
    if len(fp):
        row = fp.sort_values("pontuacao", ascending=False).iloc[0]
        same_mother = (row.get("sim_nome_mae") or 0) >= 0.95
        same_date = row["nivel_data"] == "igual"
        why = ("mesma mãe, mesma data de nascimento e mesmo município: o perfil de "
               "gêmeos" if same_mother and same_date else
               "mesma mãe e sobrenomes: o perfil de irmãos" if same_mother else
               "nomes e dados muito parecidos de pessoas diferentes (homônimos)")
        add("Falso positivo aceito automaticamente", row,
            f"Pessoas diferentes com {why}. Só o primeiro nome difere "
            f"(similaridade do nome {row['sim_nome']:.2f}). Nenhum limiar separa esse caso sem "
            "documento: é a razão para exigir documento ou revisão humana quando a mãe e a "
            "data coincidem e o primeiro nome não.")

    # 2. True pair in the review queue thanks to day/month swap or approximate date
    rev = scored[scored["correto"] & scored["pontuacao"].between(thr["revisao"], thr["match"],
                                                                 inclusive="left")]
    for tag, label in (("dia_mes_trocado", "dia e mês trocados"),
                       ("data_aproximada", "data registrada como 01/01")):
        pick = unused(rev[rev["erros"].str.contains(tag, regex=False)])
        if len(pick):
            pick = pick.assign(n_erros=pick["erros"].str.count(";"))
            row = pick.sort_values(["n_erros", "pontuacao"]).iloc[0]
            add("Par verdadeiro na fila de revisão", row,
                f"Mesma pessoa com {label} (nível de data: {row['nivel_data']}). "
                f"Erros introduzidos: {_describe_errors(errors[(row['id_1'], row['id_2'])])}. "
                "A pontuação cai para a faixa de revisão: o revisor confirma pelo nome da mãe "
                "e pelo município.")
            break

    # 3. True pair with reordered or abbreviated names
    tags_wanted = ("sobrenomes_invertidos", "nome_abreviado")
    pick = unused(scored[scored["correto"] & scored["erros"].str.contains("|".join(tags_wanted))])
    if len(pick):
        row = pick.sort_values("pontuacao").iloc[0]
        status = ("aceito automaticamente" if row["pontuacao"] >= thr["match"] else
                  "enviado à revisão" if row["pontuacao"] >= thr["revisao"] else "perdido")
        add("Nome reordenado ou abreviado", row,
            f"Erros introduzidos: {_describe_errors(errors[(row['id_1'], row['id_2'])])}. "
            f"A comparação com tokens ordenados recupera parte da similaridade "
            f"(nome {row['sim_nome']:.2f}). Resultado: {status}.")

    # 4. False negative: true pair found by blocking but scored below the review threshold
    lost = scored[scored["correto"] & (scored["pontuacao"] < thr["revisao"])
                  & ~scored["id_2"].isin(found_b)]
    if len(lost):
        row = lost.sort_values("pontuacao", ascending=False).iloc[0]
        add("Falso negativo (abaixo da revisão)", row,
            f"Mesma pessoa com pontuação {row['pontuacao']:.2f}. Erros introduzidos: "
            f"{_describe_errors(errors[(row['id_1'], row['id_2'])])}. Os erros se somam e "
            "nenhum campo isolado é decisivo; baixar o limiar de revisão traria este par, "
            "mas também mais pares falsos para a fila.")

    # 5. True pair never compared: lost in blocking
    cand = _pair_set(scored)
    in_cand = pd.Series([(a, b) in cand for a, b in zip(gab_link["id_1"], gab_link["id_2"],
                                                        strict=True)], index=gab_link.index)
    missed = gab_link[~in_cand]
    missed = missed[~missed["id_2"].isin(found_b)]
    if len(missed):
        m = missed.iloc[0]
        row = pd.Series({"id_1": m["id_1"], "id_2": m["id_2"], "pontuacao": 0.0})
        cases.append(_case("Perdido na blocagem", row, raw_a, raw_b,
                           f"O par nunca foi comparado: nenhuma regra de blocagem coincidiu. "
                           f"Erros introduzidos: {_describe_errors(m['erros'])}. Quando o "
                           "primeiro nome tem erro de digitação e a data ou a UF mudam, as três "
                           "chaves falham ao mesmo tempo. Uma regra extra (por exemplo, "
                           "documento) recuperaria parte desses casos."))

    # 6. False pair in the review queue: what the reviewer must reject
    queue = asg[(~asg["correto"]) & asg["pontuacao"].between(thr["revisao"], thr["match"],
                                                             inclusive="left")]
    queue = unused(queue)
    if len(queue):
        row = queue.sort_values("pontuacao", ascending=False).iloc[0]
        mother = row.get("sim_nome_mae")
        detail = ("o nome da mãe é parecido (similaridade "
                  f"{mother:.2f}), o que sugere parentes" if pd.notna(mother) and mother >= 0.9
                  else "não há nome da mãe ou documento para desempatar")
        add("Não match na fila de revisão", row,
            f"Pessoas diferentes com pontuação {row['pontuacao']:.2f}: nome com similaridade "
            f"{row['sim_nome']:.2f} e data no nível '{row['nivel_data']}'; {detail}. É o tipo "
            "de par que o revisor deve rejeitar, e o motivo de a faixa de revisão não ser "
            "aceita automaticamente.")
    return cases[:5]


def recall_by_error(assigned: pd.DataFrame, gab_link: pd.DataFrame, thr: dict) -> list[dict]:
    """Share of true B records found automatically, and after review, for each error type."""
    auto = assigned[assigned["pontuacao"] >= thr["match"]]
    queue = assigned[assigned["pontuacao"].between(thr["revisao"], thr["match"],
                                                   inclusive="left")]
    auto_pairs, queue_pairs = _pair_set(auto), _pair_set(queue)
    per_b: dict[str, dict] = {}
    for a, b, e in zip(gab_link["id_1"], gab_link["id_2"], gab_link["erros"], strict=True):
        d = per_b.setdefault(b, {"tags": set(str(e).split(";")) - {""}, "auto": False,
                                 "fila": False})
        d["auto"] |= (a, b) in auto_pairs
        d["fila"] |= (a, b) in queue_pairs
    rows = []
    for tag, label in ERROR_LABELS.items():
        sel = [d for d in per_b.values() if tag in d["tags"]]
        if not sel:
            continue
        n = len(sel)
        rows.append({"erro": label, "registros": n,
                     "recall_automatico": sum(d["auto"] for d in sel) / n,
                     "recall_com_revisao": sum(d["auto"] or d["fila"] for d in sel) / n})
    return sorted(rows, key=lambda r: r["recall_com_revisao"])


def run_evaluate(cfg: dict, root: str | Path = ".") -> dict:
    root = Path(root)
    out_dir = root / cfg["saida"]
    gab = read_registry(root / cfg["entrada"]["gabarito"])
    gab_link = gab[gab["tipo"] == "link"]
    gab_dedup = gab[gab["tipo"] == "dedup"]
    raw_a = read_registry(root / cfg["entrada"]["base_a"]).set_index("id", drop=False)
    raw_b = read_registry(root / cfg["entrada"]["base_b"]).set_index("id", drop=False)
    with open(out_dir / "resumo_link.json", encoding="utf-8") as fh:
        resumo = json.load(fh)
    scored = pd.read_csv(out_dir / "candidatos.csv", dtype={"id_1": str, "id_2": str})
    thr = cfg["limiares"]

    truth = _pair_set(gab_link)
    n_true_b = int(gab_link["id_2"].nunique())
    assigned = resolve_one_to_one(scored, min(SWEEP[0], thr["revisao"]))
    sweep = threshold_sweep(assigned, truth, n_true_b)
    configured = threshold_sweep(assigned, truth, n_true_b, [thr["match"], thr["revisao"]])

    queue = assigned[assigned["pontuacao"].between(thr["revisao"], thr["match"],
                                                   inclusive="left")]
    queue_true = sum((a, b) in truth for a, b in zip(queue["id_1"], queue["id_2"], strict=True))

    # Blocking quality
    cand = _pair_set(scored)
    rules = [r["nome"] for r in cfg["blocagem"]]
    rule_sets = scored["regras"].str.split("+")
    per_rule = {}
    for rule in rules:
        mask = rule_sets.map(lambda x, n=rule: n in x)
        per_rule[rule] = {
            "pares": int(mask.sum()),
            "completude": len(truth & _pair_set(scored[mask])) / len(truth),
        }
    blocking = {
        "pares_possiveis": resumo["blocagem"]["pares_possiveis"],
        "pares_candidatos": len(scored),
        "taxa_reducao": resumo["blocagem"]["taxa_reducao"],
        "completude_pares": len(truth & cand) / len(truth),
        "por_regra": per_rule,
    }

    metrics = {
        "bases": {"base_a": resumo["base_a"], "base_b": resumo["base_b"],
                  "pares_verdadeiros_link": len(truth), "registros_b_com_par": n_true_b,
                  "pares_verdadeiros_dedup": int(len(gab_dedup))},
        "limiares": thr,
        "blocagem": blocking,
        "por_limiar": sweep,
        "automatico": configured[0],
        "cenarios_limiar": match_scenarios(assigned, truth, n_true_b, thr["revisao"]),
        "fila_revisao": {
            "pares": int(len(queue)),
            "pares_verdadeiros": int(queue_true),
            "proporcao_verdadeiros": queue_true / len(queue) if len(queue) else 0.0,
            "recall_com_revisao": configured[1]["recall"],
            "precisao_com_revisao_perfeita": _prf(
                configured[0]["vp"] + queue_true,
                configured[0]["pares"] + queue_true, n_true_b)[0],
        },
        "recall_por_erro": recall_by_error(assigned, gab_link, thr),
    }

    if "deduplicacao" in resumo and (out_dir / "duplicatas_a.csv").exists():
        dups = pd.read_csv(out_dir / "duplicatas_a.csv", dtype={"id_1": str, "id_2": str})
        cand_d = pd.read_csv(out_dir / "candidatos_dedup.csv", dtype={"id_1": str, "id_2": str})
        dtruth = _pair_set(gab_dedup)
        tp = len(dtruth & _pair_set(dups))
        p, r, f = _prf(tp, len(dups), len(dtruth))
        metrics["deduplicacao"] = {
            "limiar": resumo["deduplicacao"]["limiar"],
            "pares_encontrados": int(len(dups)), "vp": tp, "precisao": p, "recall": r, "f1": f,
            "completude_blocagem": len(dtruth & _pair_set(cand_d)) / len(dtruth) if dtruth else 1,
            "taxa_reducao": resumo["deduplicacao"]["blocagem"]["taxa_reducao"],
        }

    pseudo_path = out_dir / "pseudo_metricas.json"
    if pseudo_path.exists():
        with open(pseudo_path, encoding="utf-8") as fh:
            metrics["pseudonimizado"] = json.load(fh)

    cases = hard_cases(scored, assigned, gab_link, raw_a, raw_b, thr)

    def _round(obj):
        if isinstance(obj, float):
            return round(obj, 4)
        if isinstance(obj, dict):
            return {k: _round(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_round(v) for v in obj]
        return obj

    metrics = _round(metrics)
    with open(out_dir / "metricas.json", "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    from rlk.report import render_report

    render_report(metrics, cases, out_dir / "relatorio.html")
    return metrics

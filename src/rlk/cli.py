"""Command line interface: ``rlk generate``, ``rlk link`` and ``rlk evaluate``."""

from __future__ import annotations

import argparse
import sys

from rlk.config import load_config
from rlk.evaluate import run_evaluate
from rlk.generate import GeneratorConfig, generate
from rlk.link import run_link


def _cmd_generate(args: argparse.Namespace) -> int:
    cfg = GeneratorConfig(n_a=args.n_a, n_b=args.n_b, seed=args.seed)
    summary = generate(args.out, cfg)
    print(f"Bases sintéticas geradas em {args.out}/ (semente {args.seed})")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    return 0


def _cmd_link(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    s = run_link(cfg)
    b = s["blocagem"]
    print(f"Pares possíveis: {b['pares_possiveis']:,} | candidatos após blocagem: "
          f"{b['pares_candidatos']:,} (redução de {b['taxa_reducao']:.2%})")
    print(f"Matches automáticos: {s['matches']} | revisão manual: {s['revisao_manual']} | "
          f"B sem par: {s['nao_pareados_b']}")
    if "deduplicacao" in s:
        print(f"Duplicatas na base A: {s['deduplicacao']['pares_duplicados']} pares")
    print(f"Saídas em {cfg['saida']}/")
    return 0


def _cmd_evaluate(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    m = run_evaluate(cfg)
    a, f = m["automatico"], m["fila_revisao"]
    print(f"Limiar {m['limiares']['match']}: precisão {a['precisao']:.2%}, recall "
          f"{a['recall']:.2%}, F1 {a['f1']:.2%}")
    print(f"Fila de revisão: {f['pares']} pares; recall com revisão {f['recall_com_revisao']:.2%}")
    print(f"Blocagem: redução {m['blocagem']['taxa_reducao']:.2%}, completude "
          f"{m['blocagem']['completude_pares']:.2%}")
    print(f"Relatório: {cfg['saida']}/relatorio.html")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rlk", description="Record linkage com governança de dados"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="gera as bases sintéticas e o gabarito")
    g.add_argument("--out", default="data", help="pasta de saída (padrão: data)")
    g.add_argument("--n-a", type=int, default=5000, help="registros da base A")
    g.add_argument("--n-b", type=int, default=3000, help="registros da base B")
    g.add_argument("--seed", type=int, default=42, help="semente aleatória")
    g.set_defaults(func=_cmd_generate)

    lk = sub.add_parser("link", help="padroniza, bloca, compara, pontua e classifica os pares")
    lk.add_argument("--config", default="config/default.yaml", help="arquivo YAML")
    lk.set_defaults(func=_cmd_link)

    ev = sub.add_parser("evaluate", help="compara com o gabarito e gera o relatório HTML")
    ev.add_argument("--config", default="config/default.yaml", help="arquivo YAML")
    ev.set_defaults(func=_cmd_evaluate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

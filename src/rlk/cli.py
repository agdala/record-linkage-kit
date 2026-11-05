"""Command line interface: ``rlk generate``, ``rlk link`` and ``rlk evaluate``."""

from __future__ import annotations

import argparse
import sys

from rlk.generate import GeneratorConfig, generate


def _cmd_generate(args: argparse.Namespace) -> int:
    cfg = GeneratorConfig(n_a=args.n_a, n_b=args.n_b, seed=args.seed)
    summary = generate(args.out, cfg)
    print(f"Bases sintéticas geradas em {args.out}/ (semente {args.seed})")
    for key, value in summary.items():
        print(f"  {key}: {value}")
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from triad import __version__
from triad.config import Config
from triad.crew import Crew


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="triad", description="Tracker, Predictor, and Commander agents for release gating."
    )
    parser.add_argument("--version", action="version", version=f"triad {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="observe, forecast, and decide for a repository")
    run.add_argument("path", nargs="?", default=".", help="repository root (default: .)")
    run.add_argument("--apply", action="store_true", help="allow the Commander to run autofixes")
    run.add_argument(
        "--max-rounds", type=int, help="observe/fix cycles before deciding (default 3)"
    )
    run.add_argument("--threshold", type=float, help="HOLD at or above this risk (default 0.35)")
    run.add_argument("--no-deps", action="store_true", help="skip the outdated-dependency check")
    run.add_argument("--llm", choices=["offline", "anthropic"], help="prose backend")
    run.add_argument("--model", help="model name for the anthropic backend")
    run.add_argument("--json", action="store_true", help="print the verdict as JSON")
    run.add_argument("--trace", action="store_true", help="print the agent message log")
    run.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if not Path(args.path).is_dir():
        print(f"error: not a directory: {args.path}", file=sys.stderr)
        return 2
    try:
        config = Config.from_env(
            workdir=args.path,
            apply=True if args.apply else None,
            max_rounds=args.max_rounds,
            risk_threshold=args.threshold,
            check_deps=False if args.no_deps else None,
            llm=args.llm,
            model=args.model,
        )
        crew = Crew(config)
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    verdict = crew.run()

    if args.json:
        print(json.dumps(verdict.to_dict(), indent=2))
    else:
        print(f"decision : {verdict.decision}")
        print(f"risk     : {verdict.risk:.2f} ({verdict.level})")
        print(f"rounds   : {verdict.rounds}")
        print(f"mode     : {'apply' if config.apply else 'dry-run'}")
        print(f"\n{verdict.summary}")
        for title, items in (("blockers", verdict.blockers), ("advisories", verdict.advisories)):
            if items:
                print(f"\n{title}:")
                print("\n".join(f"  - {item}" for item in items))
        for item in verdict.executed:
            print(f"\nran {item['tool']} in round {item['round']}: {item['detail']}")
        for item in verdict.planned:
            why = "blocked, use --apply" if item["blocked"] else "max rounds reached"
            print(f"\nnot run: {item['tool']} ({why})")
        print(f"\nreport   : {verdict.report_path}")
    if args.trace:
        print("\nmessage trace:", file=sys.stderr if args.json else sys.stdout)
        print("\n".join(crew.bus.trace()), file=sys.stderr if args.json else sys.stdout)
    return 0 if verdict.decision == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())

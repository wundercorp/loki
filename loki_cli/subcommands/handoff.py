"""``loki handoff`` subcommand parser."""

from __future__ import annotations

from typing import Callable


def build_handoff_parser(subparsers, *, cmd_handoff: Callable) -> None:
    parser = subparsers.add_parser(
        "handoff",
        help="Upload a local workspace and continue in the hosted Loki web chat",
        description=(
            "Package a local directory, authenticate through the hosted dashboard, "
            "upload it as chat context, and open the matching web session."
        ),
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Directory to package or an existing ZIP archive (default: current directory)",
    )
    parser.add_argument(
        "--url",
        default="https://chat.loki.computer",
        help="Hosted Loki dashboard URL (default: https://chat.loki.computer)",
    )
    parser.add_argument(
        "--label",
        default="",
        help="Optional workspace label shown in the web chat",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Print browser URLs instead of opening them automatically",
    )
    parser.set_defaults(func=cmd_handoff)

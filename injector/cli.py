"""CLI entry point for the chaos injector."""

import argparse
import json
import sys
import time

from injector.docker_client import get_container_pid
from injector.network_chaos import (
    _get_current_netem_params,
    add_composite_fault,
    add_latency,
    add_loss,
    clear_rules,
)


def main():
    parser = argparse.ArgumentParser(
        description="Inject network chaos into a Docker container."
    )
    parser.add_argument(
        "--target",
        "-t",
        required=True,
        help="Name or ID of the target container.",
    )
    parser.add_argument(
        "--action",
        "-a",
        choices=["latency", "loss", "clear", "status"],
        help="Chaos action to apply.",
    )
    parser.add_argument(
        "--value",
        "-v",
        type=int,
        help="Value for the action (ms for latency, percent for loss). Not needed for 'clear'.",
    )
    parser.add_argument(
        "--latency",
        type=int,
        help="Latency in milliseconds (composite fault mode).",
    )
    parser.add_argument(
        "--loss",
        type=int,
        help="Packet loss percentage (composite fault mode).",
    )
    parser.add_argument(
        "--duration",
        "-d",
        type=int,
        help="Duration in milliseconds before auto-clearing the fault.",
    )

    args = parser.parse_args()

    has_composite = args.latency is not None or args.loss is not None
    has_legacy = args.action is not None

    if has_legacy and has_composite:
        parser.error("Cannot mix --action/--value with --latency/--loss.")

    if not has_legacy and not has_composite:
        parser.error(
            "Must specify either --action or composite flags (--latency, --loss)."
        )

    if has_legacy and args.action in ("latency", "loss") and args.value is None:
        parser.error(f"--value is required when action is '{args.action}'.")

    if has_legacy and args.action == "status":
        try:
            pid = get_container_pid(args.target)
            params = _get_current_netem_params(pid)
            output = {
                "status": "running",
                "latency_ms": params.get("delay"),
                "loss_pct": params.get("loss"),
            }
            print(json.dumps(output))
        except ValueError as exc:
            output = {"status": "error", "error": str(exc)}
            print(json.dumps(output))
            sys.exit(1)
        sys.exit(0)

    try:
        pid = get_container_pid(args.target)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        if has_composite:
            faults = {}
            if args.latency is not None:
                faults["latency"] = args.latency
            if args.loss is not None:
                faults["loss"] = args.loss
            add_composite_fault(pid, faults)
            print(f"Added composite fault to container '{args.target}': {faults}.")
        elif args.action == "latency":
            add_latency(pid, args.value)
            print(f"Added {args.value}ms latency to container '{args.target}'.")
        elif args.action == "loss":
            add_loss(pid, args.value)
            print(f"Added {args.value}% packet loss to container '{args.target}'.")
        elif args.action == "clear":
            clear_rules(pid)
            print(f"Cleared all tc rules from container '{args.target}'.")
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.duration is not None and (
        has_composite or args.action in ("latency", "loss")
    ):
        if args.duration < 0:
            print("Error: --duration must be non-negative.", file=sys.stderr)
            sys.exit(1)
        time.sleep(args.duration / 1000.0)
        try:
            clear_rules(pid)
            print(
                f"Auto-cleared rules from container '{args.target}' after {args.duration}ms."
            )
        except RuntimeError as exc:
            print(f"Error during auto-clear: {exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()

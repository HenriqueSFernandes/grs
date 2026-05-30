"""CLI entry point for the chaos injector."""

import argparse
import sys
import time

from injector.docker_client import get_container_pid
from injector.network_chaos import add_latency, add_loss, clear_rules


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
        required=True,
        choices=["latency", "loss", "clear"],
        help="Chaos action to apply.",
    )
    parser.add_argument(
        "--value",
        "-v",
        type=int,
        help="Value for the action (ms for latency, percent for loss). Not needed for 'clear'.",
    )
    parser.add_argument(
        "--duration",
        "-d",
        type=int,
        help="Duration in milliseconds before auto-clearing the fault.",
    )

    args = parser.parse_args()

    if args.action in ("latency", "loss") and args.value is None:
        parser.error(f"--value is required when action is '{args.action}'.")

    try:
        pid = get_container_pid(args.target)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        if args.action == "latency":
            add_latency(pid, args.value)
            print(f"Added {args.value}ms latency to container '{args.target}'.")
        elif args.action == "loss":
            add_loss(pid, args.value)
            print(f"Added {args.value}% packet loss to container '{args.target}'.")
        elif args.action == "clear":
            clear_rules(pid)
            print(f"Cleared all tc rules from container '{args.target}'.")
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.duration and args.action in ("latency", "loss"):
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

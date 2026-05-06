"""Host-side wrapper that launches the chaos-sidecar container."""

import argparse
import subprocess
import sys
from pathlib import Path


SIDECAR_IMAGE = "chaos-sidecar"


def _ensure_image():
    """Check if the sidecar image exists locally; auto-build if missing."""
    result = subprocess.run(
        ["docker", "images", "-q", SIDECAR_IMAGE],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("Docker does not seem to be running or is not installed.")

    if not result.stdout.strip():
        print(f"'{SIDECAR_IMAGE}' image not found locally. Building...")
        _build_image()
        print(f"'{SIDECAR_IMAGE}' built successfully.")


def _build_image():
    """Build the sidecar Docker image from the project root."""
    project_root = Path(__file__).resolve().parent.parent
    dockerfile = project_root / "Dockerfile"

    if not dockerfile.exists():
        raise RuntimeError(
            f"Dockerfile not found at {dockerfile}. "
            "Cannot auto-build the sidecar image."
        )

    subprocess.run(
        ["docker", "build", "-t", SIDECAR_IMAGE, str(project_root)],
        check=True,
    )


def _run_sidecar(args: argparse.Namespace):
    """Launch the sidecar container with the requested chaos args."""
    cmd = [
        "docker",
        "run",
        "--rm",
        "--privileged",
        "--pid=host",
        "-v",
        "/var/run/docker.sock:/var/run/docker.sock",
        SIDECAR_IMAGE,
        "--target",
        args.target,
        "--action",
        args.action,
    ]

    if args.value is not None:
        cmd.extend(["--value", str(args.value)])

    subprocess.run(cmd, check=True)


def main():
    parser = argparse.ArgumentParser(
        description="Inject network chaos into a Docker container (host-side wrapper)."
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
        "--rebuild",
        action="store_true",
        help="Force rebuild of the sidecar image before running.",
    )

    args = parser.parse_args()

    if args.action in ("latency", "loss") and args.value is None:
        parser.error(f"--value is required when action is '{args.action}'.")

    try:
        if args.rebuild:
            _build_image()
        else:
            _ensure_image()

        _run_sidecar(args)
    except subprocess.CalledProcessError as exc:
        print(
            f"Error: Command failed with exit code {exc.returncode}.", file=sys.stderr
        )
        sys.exit(1)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

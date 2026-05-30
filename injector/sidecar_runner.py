"""Host-side wrapper that launches the chaos-sidecar container."""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import injector
from injector import scenario_executor

SIDECAR_IMAGE = "rickysf/chaos-sidecar"
SIDECAR_VERSION = injector.__version__


def _project_root() -> Path:
    """Return the directory containing the bundled project files.

    Works for both editable installs (project root) and wheel installs
    (site-packages root where force-included files live).
    """
    return Path(injector.__file__).resolve().parent.parent


def _ensure_image(args: argparse.Namespace) -> str:
    """Resolve the sidecar image tag, pulling or building as needed.

    Resolution order:
    1. Check if the requested tag already exists locally.
    2. If --local-build is set, skip the registry and build from source.
    3. Try docker pull from Docker Hub.
    4. If pull fails, fall back to building from the bundled Dockerfile.

    Returns:
        The resolved Docker image tag (e.g. "rickysf/chaos-sidecar:0.2.0").
    """
    version = args.sidecar_version or SIDECAR_VERSION
    tag = f"{SIDECAR_IMAGE}:{version}"

    # 1. Already cached locally?
    result = subprocess.run(
        ["docker", "images", "-q", tag],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("Docker does not seem to be running or is not installed.")

    if result.stdout.strip():
        return tag

    # 2. Force local build
    if args.local_build:
        print(f"Building sidecar image {tag} from bundled source...")
        _build_image(tag)
        return tag

    # 3. Try pulling from registry
    print(f"Pulling sidecar image {tag} from Docker Hub...")
    pull = subprocess.run(
        ["docker", "pull", tag],
        capture_output=True,
        text=True,
    )
    if pull.returncode == 0:
        return tag

    # 4. Fallback to local build
    print(f"Pull failed. Falling back to local build of {tag}...")
    _build_image(tag)
    return tag


def _build_image(tag: str):
    """Build the sidecar Docker image from the bundled project files."""
    root = _project_root()
    dockerfile_src = root / "Dockerfile"
    pyproject_src = root / "pyproject.toml"

    readme_src = root / "README.md"

    if not dockerfile_src.exists() or not pyproject_src.exists():
        raise RuntimeError(
            "Bundled project files (Dockerfile, pyproject.toml) not found. "
            "Cannot perform a local build."
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Copy bundled files
        shutil.copy2(dockerfile_src, tmp / "Dockerfile")
        shutil.copy2(pyproject_src, tmp / "pyproject.toml")
        if readme_src.exists():
            shutil.copy2(readme_src, tmp / "README.md")

        # Copy injector source files
        injector_src = Path(injector.__file__).resolve().parent
        injector_dst = tmp / "injector"
        injector_dst.mkdir()
        for item in injector_src.iterdir():
            if item.name == "__pycache__":
                continue
            if item.is_file():
                shutil.copy2(item, injector_dst / item.name)
            elif item.is_dir():
                shutil.copytree(
                    item,
                    injector_dst / item.name,
                    ignore=shutil.ignore_patterns("__pycache__"),
                )

        subprocess.run(
            ["docker", "build", "-t", tag, str(tmp)],
            check=True,
        )


def _run_sidecar(tag: str, args: argparse.Namespace):
    """Launch the sidecar container with the requested chaos args."""
    cmd = [
        "docker",
        "run",
        "--rm",
        "--privileged",
        "--pid=host",
        "-v",
        "/var/run/docker.sock:/var/run/docker.sock",
        tag,
        "--target",
        args.target,
    ]

    if args.action is not None:
        cmd.extend(["--action", args.action])

    if args.value is not None:
        cmd.extend(["--value", str(args.value)])

    if args.duration is not None:
        cmd.extend(["--duration", str(args.duration)])

    if getattr(args, "latency", None) is not None:
        cmd.extend(["--latency", str(args.latency)])

    if getattr(args, "loss", None) is not None:
        cmd.extend(["--loss", str(args.loss)])

    subprocess.run(cmd, check=True)


def _build_direct_parser() -> argparse.ArgumentParser:
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
        help="Duration in milliseconds before the sidecar auto-clears the fault.",
    )
    parser.add_argument(
        "--sidecar-version",
        help="Override the sidecar image version tag (default: package version).",
    )
    parser.add_argument(
        "--local-build",
        action="store_true",
        help="Force a local build of the sidecar image from bundled source.",
    )
    return parser


def _build_run_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a chaos scenario from a YAML file."
    )
    parser.add_argument("file", help="Path to the scenario YAML file.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print a timeline without applying chaos.",
    )
    return parser


def _build_serve_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Start the chaos dashboard web server."
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=8080,
        help="Port to listen on (default: 8080).",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0).",
    )
    return parser


def _serve(args: argparse.Namespace):
    import uvicorn

    uvicorn.run(
        "injector.web_server:app",
        host=args.host,
        port=args.port,
        log_level="info",
    )


def main():
    args_list = sys.argv[1:]

    if args_list and args_list[0] == "run":
        parser = _build_run_parser()
        args = parser.parse_args(args_list[1:])
        try:
            if args.dry_run:
                scenario_executor.dry_run(args.file)
            else:
                scenario_executor.execute(args.file)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
    elif args_list and args_list[0] == "serve":
        parser = _build_serve_parser()
        args = parser.parse_args(args_list[1:])
        _serve(args)
    else:
        parser = _build_direct_parser()
        args = parser.parse_args(args_list)

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

        try:
            tag = _ensure_image(args)
            _run_sidecar(tag, args)
        except subprocess.CalledProcessError as exc:
            print(
                f"Error: Command failed with exit code {exc.returncode}.",
                file=sys.stderr,
            )
            sys.exit(1)
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()

"""Create a project virtual environment with Python's standard library."""

import argparse
import os
import shutil
import signal
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# A separate process uses the project's Python, even when this helper is launched
# with pyenv or another interpreter. Exit 42 specifically identifies missing pandas
# files; failures in numpy or unrelated packages must not trigger pandas repair.
PANDAS_CHECK = """
import sys
try:
    import pandas as pd
    import pandas._config
except ModuleNotFoundError as exc:
    if exc.name == 'pandas' or (exc.name or '').startswith('pandas.'):
        print('Missing pandas component: ' + str(exc.name), file=sys.stderr)
        sys.exit(42)
    raise
assert pd.DataFrame({'value': [1, 2]})['value'].sum() == 3
print('pandas import and DataFrame check passed.')
"""


def check_pandas(python: Path) -> None:
    """Repair missing pandas files once, keeping its installed version and dependencies."""
    command = [str(python), "-c", PANDAS_CHECK]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    if result.returncode == 42:
        print("pandas has missing package files. Reinstalling pandas once...", flush=True)
        version_code = (
            "from importlib.metadata import PackageNotFoundError, version\n"
            "try:\n    print(version('pandas'))\n"
            "except PackageNotFoundError:\n    print('')\n"
        )
        metadata = subprocess.run(
            [str(python), "-c", version_code], cwd=ROOT,
            text=True, capture_output=True, check=True,
        )
        installed_version = metadata.stdout.strip()
        # This fallback is the project's tested lock entry, not an unbounded upgrade.
        requirement = f"pandas=={installed_version}" if installed_version else "pandas==3.0.5"
        subprocess.run(
            [str(python), "-m", "pip", "install", "--force-reinstall", "--no-cache-dir",
             "--no-deps", "--only-binary=:all:", requirement],
            cwd=ROOT, check=True,
        )
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout, end="", flush=True)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr, flush=True)
    if result.returncode:
        raise subprocess.CalledProcessError(result.returncode, command)


def main():
    parser = argparse.ArgumentParser(description="Install Card OCR locally (Python 3.12 recommended)")
    parser.add_argument("--api-only", action="store_true", help="Skip the optional Gradio interface")
    parser.add_argument("--dev", action="store_true", help="Also install tests and lint tools")
    args = parser.parse_args()
    if not ((3, 12) <= sys.version_info[:2] < (3, 14)):
        parser.error("Use Python 3.12 (recommended) or 3.13; 64-bit Python is required by the OCR wheels.")
    env = ROOT / ".venv"
    python = env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        print("Creating .venv …", flush=True)
        venv.EnvBuilder(with_pip=True).create(env)
    if not (ROOT / ".env").exists():
        shutil.copyfile(ROOT / ".env.example", ROOT / ".env")
    requirements = "requirements-api.txt" if args.api_only else "requirements-local.txt"
    commands = [[str(python), "-m", "pip", "install", "-r", requirements]]
    if args.dev:
        commands.append([str(python), "-m", "pip", "install", "-r", "requirements-dev.txt"])
    try:
        for step, command in enumerate(commands, start=1):
            print(
                f"\n[Packages {step}/{len(commands)}] Installing {command[-1]}. "
                "Downloads and installation can take several minutes; please wait.",
                flush=True,
            )
            subprocess.run(command, cwd=ROOT, check=True)
        if not args.api_only:
            print("\nChecking pandas package files...", flush=True)
            check_pandas(python)
            print("\nChecking the Gradio interface...", flush=True)
            check_app = (
                "from card_ocr.config import Settings; "
                "from card_ocr.demo import create_combined_app; "
                "create_combined_app(Settings()); print('Gradio interface check passed.')"
            )
        else:
            print("\nChecking the API...", flush=True)
            check_app = "from card_ocr.api import app; print('API import check passed.')"
        subprocess.run([str(python), "-c", check_app], cwd=ROOT, check=True)
        print("\nChecking installed dependency versions...", flush=True)
        subprocess.run([str(python), "-m", "pip", "check"], cwd=ROOT, check=True)
        print("\nChecking OCR models...", flush=True)
        subprocess.run([str(python), "-m", "scripts.warmup"], cwd=ROOT, check=True)
    except subprocess.CalledProcessError as exc:
        if exc.returncode in (-signal.SIGINT, 128 + signal.SIGINT):
            raise KeyboardInterrupt from None
        print("Setup stopped. See the error above and docs/LOCAL_TESTING.md.", file=sys.stderr)
        raise SystemExit(exc.returncode) from None
    suffix = " --api-only" if args.api_only else ""
    print(f"\nReady. Run: python run_local.py{suffix}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nSetup cancelled (Ctrl+C). Installation may be incomplete.", file=sys.stderr)
        print(
            "Run python setup_local.py again with the same options to finish setup. "
            "Keep the existing .venv; installed packages will be reused.",
            file=sys.stderr,
        )
        raise SystemExit(130) from None

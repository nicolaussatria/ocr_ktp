"""Upload this project to a Hugging Face Space, and nothing else from this folder.

    python -m scripts.deploy_space <user>/<space> --dry-run   # list what would be sent
    python -m scripts.deploy_space <user>/<space>             # send it

A plain ``hf upload <space> .`` sends the whole folder: ``.env`` with its key, card
photographs kept beside the code, test output. A Space is public unless it was created
private, and a file stays in its history after it is deleted. So the files to publish
are named here, and anything not named stays on this computer.

Needs the ``hf`` command (``pip install -U huggingface_hub``) and ``hf auth login``.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from fnmatch import fnmatch
from pathlib import Path

from card_ocr import __version__

ROOT = Path(__file__).resolve().parents[1]
# What a Space needs to build and run, plus the documentation, examples and tests.
PUBLISHED = (
    "README.md", "START_HERE.txt", "THIRD_PARTY.md", "app.py", "run_local.py", "setup_local.py",
    "packages.txt", "pyproject.toml", "requirements*.txt", "requirements.lock", ".env.example", ".gitignore",
    "card_ocr/*", "docs/*", "examples/*", "scripts/*", "tests/*", "deploy/*",
)
NEVER = ("*/__pycache__/*", "*.pyc", "*.DS_Store")


def published_files() -> list[str]:
    """Paths relative to the project root, as they will appear in the Space."""
    paths = (path.relative_to(ROOT).as_posix() for path in ROOT.rglob("*") if path.is_file())
    return sorted(path for path in paths
                  if any(fnmatch(path, pattern) for pattern in PUBLISHED)
                  and not any(fnmatch(path, pattern) for pattern in NEVER))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("space", help="the Space to update, as <user>/<space>")
    parser.add_argument("--dry-run", action="store_true", help="list the files and stop")
    args = parser.parse_args()
    files = published_files()
    size = sum((ROOT / path).stat().st_size for path in files)
    print(f"{len(files)} files, {size / 1024:.0f} KB, for the Space {args.space}:")
    for path in files:
        print("  " + path)
    if args.dry_run:
        print("Dry run: nothing was uploaded.")
        return 0
    if shutil.which("hf") is None:
        print("The hf command was not found. Install it with: pip install -U huggingface_hub", file=sys.stderr)
        return 1
    # The listed files are copied to an empty folder and that folder is uploaded, so the
    # upload cannot pick up anything else.
    with tempfile.TemporaryDirectory() as staging:
        for path in files:
            target = Path(staging) / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / path, target)
        result = subprocess.run(["hf", "upload", args.space, staging, ".", "--repo-type", "space",
                                 "--commit-message", f"Card OCR {__version__}"], check=False)
    if result.returncode == 0:
        print(f"Uploaded. The Space now rebuilds; wait for it with: hf spaces wait {args.space}")
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())

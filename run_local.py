"""Launch the project environment without shell-specific activation commands."""

import argparse
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Run local OCR; stop with Ctrl+C")
    parser.add_argument("--api-only", action="store_true", help="REST API and Swagger only")
    parser.add_argument("--share", action="store_true", help="Temporary public HTTPS link; computer stays on")
    parser.add_argument("--host", default="127.0.0.1", help="Use 0.0.0.0 for a trusted LAN test")
    parser.add_argument("--port", type=int, help="Default 7860 for Gradio, 8000 for API only")
    args = parser.parse_args()
    if args.api_only and args.share:
        parser.error("--share needs the Gradio interface; omit --api-only.")
    python = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        parser.error("Project environment is missing. Run: python3.12 setup_local.py (Windows: py -3.12 setup_local.py)")
    port = args.port if args.port is not None else (8000 if args.api_only else 7860)
    if not 1 <= port <= 65535:
        parser.error("Port must be between 1 and 65535.")
    if args.api_only:
        command = [str(python), "-m", "uvicorn", "card_ocr.api:app", "--workers", "1"]
    else:
        command = [str(python), "app.py"]
        if args.share:
            command.append("--share")
    command.extend(["--host", args.host, "--port", str(port)])
    print(f"Local {'API docs' if args.api_only else 'interface'}: http://127.0.0.1:{port}"
          f"{'/docs' if args.api_only else '/'}", flush=True)
    try:
        raise SystemExit(subprocess.call(command, cwd=ROOT))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

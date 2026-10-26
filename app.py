"""Local and Hugging Face Gradio SDK entry point. No container setup required."""

import argparse
import os


def main():
    parser = argparse.ArgumentParser(description="Card OCR interface and JSON API")
    parser.add_argument("--host", default="0.0.0.0" if os.getenv("SPACE_ID") else "127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "7860")))
    parser.add_argument("--share", action="store_true", help="Create a temporary public Gradio HTTPS link")
    args = parser.parse_args()
    os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    from card_ocr.config import Settings
    from card_ocr.demo import create_combined_app, launch_share

    settings = Settings()
    if args.share:
        if os.getenv("SPACE_ID"):
            parser.error("Spaces already provides an HTTPS URL; omit --share.")
        launch_share(settings, args.host, args.port)
    else:
        import uvicorn
        uvicorn.run(create_combined_app(settings), host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()

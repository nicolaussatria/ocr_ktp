import json

import numpy as np

from card_ocr.config import Settings
from card_ocr.engine import RapidEngine


def main():
    engine = RapidEngine(Settings())
    engine.recognize(np.full((300, 800, 3), 255, dtype=np.uint8), "warmup")
    print(
        json.dumps(
            {"status": "ready", "engine": engine.name, "models": engine.models, "sha256": engine.hashes},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

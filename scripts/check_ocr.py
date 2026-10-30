"""Check the installed OCR worker and time a scan on this device."""
import argparse
import json
from pathlib import Path
import platform
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reader import Job, MAX_UPLOAD, availability, run_job


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", nargs="?", type=Path, help="Optional JPEG/PNG page from your camera")
    args = parser.parse_args()
    status = availability()
    if not status["ocr"]:
        parser.exit(1, "OCR is unavailable. Install requirements.txt in this Python environment.\n")
    try:
        if args.image:
            if args.image.stat().st_size > MAX_UPLOAD:
                raise ValueError("Image exceeds the 6 MiB upload limit.")
            data = args.image.read_bytes()
        else:
            import cv2
            import numpy as np
            image = np.full((300, 1200, 3), 255, dtype=np.uint8)
            cv2.putText(image, "The magnifier makes reading easier.", (30, 150),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 3, cv2.LINE_AA)
            data = cv2.imencode(".png", image)[1].tobytes()
        started = time.perf_counter()
        result, _ = run_job(Job("installation-check", "ocr"), data)
        elapsed = time.perf_counter() - started
        if not args.image and "magnifier makes reading easier" not in result["text"]:
            raise RuntimeError("The engine ran but did not read the test sentence correctly.")
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        parser.exit(1, f"OCR check failed: {exc}\n")
    print(json.dumps({
        "model": status["ocr_model"], "runtime": status["ocr_runtime"],
        "cpu_threads": status["ocr_threads"], "architecture": platform.machine(),
        "scan_seconds": round(elapsed, 2), "text": result["text"],
        "uncertain": result["uncertain"], "truncated": result["truncated"],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

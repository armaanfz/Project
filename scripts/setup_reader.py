"""Install and verify the local neural voice after requirements-reader.txt."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice", default="en_US-lessac-medium", help="Piper voice code")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z]{2}_[A-Z]{2}-[A-Za-z0-9_]+-(?:x_low|low|medium|high)", args.voice):
        parser.error("Use a Piper voice code such as en_US-lessac-medium")
    for package in ("piper", "pytesseract"):
        if importlib.util.find_spec(package) is None:
            raise SystemExit("First run: python -m pip install -r requirements-reader.txt")
    command = os.environ.get("TESSERACT_CMD", "tesseract")
    if not shutil.which(command):
        raise SystemExit("Install Tesseract first. On Raspberry Pi OS: sudo apt install tesseract-ocr tesseract-ocr-eng")
    languages = subprocess.check_output([command, "--list-langs"], text=True, timeout=15).splitlines()[1:]
    missing = set(os.environ.get("OCR_LANGUAGE", "eng").split("+")) - set(languages)
    if missing:
        raise SystemExit("Install these Tesseract language packs first: " + ", ".join(sorted(missing)))
    destination = ROOT / "models"
    destination.mkdir(exist_ok=True)
    base = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
    # The downloader needs only HTTP and file I/O. Do not initialize an inference
    # runtime (or its telemetry) just to download model files.
    with urlopen(base + "voices.json", timeout=60) as response:
        registry = json.load(response)
    if args.voice not in registry:
        raise SystemExit("Voice not found in the Piper voice registry")
    # Interrupted downloads cannot leave a truncated model in the installed path.
    with tempfile.TemporaryDirectory(prefix="voice-", dir=destination) as temporary:
        for name, metadata in registry[args.voice]["files"].items():
            if not name.endswith((".onnx", ".onnx.json", "MODEL_CARD")):
                continue
            target = Path(temporary) / Path(name).name
            digest = hashlib.md5()  # Registry checksum, not a security token.
            with urlopen(base + name, timeout=120) as response, target.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    digest.update(chunk)
            if target.stat().st_size != metadata["size_bytes"] or digest.hexdigest() != metadata["md5_digest"]:
                raise SystemExit("Voice checksum mismatch. Run setup again.")
        model = Path(temporary) / f"{args.voice}.onnx"
        config = Path(str(model) + ".json")
        json.loads(config.read_text(encoding="utf-8"))
        os.replace(model, destination / model.name)
        os.replace(config, destination / config.name)
        card = Path(temporary) / "MODEL_CARD"
        if card.exists():
            os.replace(card, destination / f"{args.voice}.MODEL_CARD")
    print(f"Tesseract found. Piper voice downloaded and checksums verified: {destination / model.name}")
    if args.voice != "en_US-lessac-medium":
        print(f"Set PIPER_MODEL to {destination / model.name} before starting the app.")


if __name__ == "__main__":
    main()

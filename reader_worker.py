"""Isolated OCR / neural speech worker. No camera ownership or Flask imports."""
import json
import math
import os
from pathlib import Path
import sys
import warnings
import wave

MAX_PIXELS = 12_000_000
MAX_TEXT = 20_000


def recognize(image_path):
    import pytesseract
    from PIL import Image, ImageOps

    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(image_path) as original:
            if original.format not in {"JPEG", "PNG"}:
                raise ValueError("Use a JPEG or PNG camera image.")
            if original.width * original.height > MAX_PIXELS:
                raise ValueError("The image is too large. Scan a smaller area.")
            image = ImageOps.exif_transpose(original).convert("L")
    if min(image.size) < 16:
        raise ValueError("The image is too small. Scan a larger area.")
    image = ImageOps.autocontrast(image)
    # Modest enlargement helps small camera text without unbounded memory use.
    factor = min(2.0, max(1.0, 1600 / image.width), math.sqrt(4_000_000 / (image.width * image.height)))
    if abs(factor - 1) > 0.05:
        image = image.resize((max(1, round(image.width * factor)), max(1, round(image.height * factor))), Image.Resampling.LANCZOS)
    if os.environ.get("TESSERACT_CMD"):
        pytesseract.pytesseract.tesseract_cmd = os.environ["TESSERACT_CMD"]
    data = pytesseract.image_to_data(
        image, lang=os.environ.get("OCR_LANGUAGE", "eng"),
        config="--psm 3", output_type=pytesseract.Output.DICT, timeout=30,
    )
    paragraphs = []
    words = []
    previous_paragraph = None
    uncertain = 0
    word_count = 0
    for index, value in enumerate(data["text"]):
        word = value.strip()
        if not word:
            continue
        paragraph = (data["block_num"][index], data["par_num"][index])
        if previous_paragraph is not None and paragraph != previous_paragraph:
            paragraphs.append(" ".join(words))
            words = []
        previous_paragraph = paragraph
        words.append(word)
        word_count += 1
        uncertain += float(data["conf"][index]) < 55
    if words:
        paragraphs.append(" ".join(words))
    text = "\n\n".join(paragraphs)
    return {"text": text[:MAX_TEXT], "word_count": word_count,
            "uncertain": bool(uncertain), "truncated": len(text) > MAX_TEXT}


def speak(text, model_path, output_path):
    import onnxruntime
    onnxruntime.disable_telemetry_events()
    from piper import PiperConfig, PiperVoice, SynthesisConfig

    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    with open(str(model_path) + ".json", encoding="utf-8") as config_file:
        config = PiperConfig.from_dict(json.load(config_file))
    voice = PiperVoice(
        config=config,
        session=onnxruntime.InferenceSession(str(model_path), sess_options=options,
                                             providers=["CPUExecutionProvider"]),
    )
    # OCR is plain text, never Piper's raw phoneme markup.
    text = text.replace("[[", "[").replace("]]", "]")
    with wave.open(str(output_path), "wb") as output:
        voice.synthesize_wav(text, output, syn_config=SynthesisConfig(length_scale=1.05))
    return {"voice": "Piper", "format": "wav"}


def main():
    kind, directory = sys.argv[1:3]
    directory = Path(directory)
    try:
        if kind == "ocr":
            result = recognize(directory / "image")
        elif kind == "speech":
            payload = json.loads((directory / "input.json").read_text(encoding="utf-8"))
            result = speak(payload["text"], payload["model"], directory / "speech.wav")
        else:
            raise ValueError("Unknown reader operation")
        response = {"result": result}
    except Exception as exc:
        # Detailed setup errors stay in the server log, never in the reader UI.
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        message = ("Could not read this image. Try a clearer, well-lit page."
                   if kind == "ocr" else "Could not prepare the voice. Please try again.")
        response = {"error": message}
    (directory / "result.json").write_text(json.dumps(response), encoding="utf-8")


if __name__ == "__main__":
    main()

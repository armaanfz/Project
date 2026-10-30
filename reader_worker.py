"""Isolated OCR / neural speech worker. No camera ownership or Flask imports."""
import json
import importlib.util
import math
import os
from pathlib import Path
import statistics
import sys
import warnings
import wave

MAX_PIXELS = 12_000_000
MAX_TEXT = 20_000
OCR_MODEL = "PP-OCRv6 small"


def ocr_cpu_threads():
    """Leave CPU capacity for the Pi 5 camera while allowing device tuning."""
    try:
        value = int(os.environ.get("OCR_CPU_THREADS", "2"))
    except ValueError:
        value = 2
    return max(1, min(value, 4, os.cpu_count() or 1))


def ocr_model_paths():
    """Locate bundled models without importing OCR or loading the inference runtime."""
    package = importlib.util.find_spec("rapidocr")
    if package is None or not package.origin:
        return {}
    directory = Path(package.origin).parent / "models"
    return {
        "Det": directory / "PP-OCRv6_det_small.onnx",
        "Cls": directory / "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
        "Rec": directory / "PP-OCRv6_rec_small.onnx",
    }


def reading_result(result):
    """Reflow nearby lines into paragraphs, retaining larger gaps in the page."""
    if not result.txts:
        return {"text": "", "word_count": 0, "uncertain": False, "truncated": False}
    lines = []
    for box, value, confidence in zip(result.boxes, result.txts, result.scores):
        text = " ".join(value.split())
        if text:
            top, bottom = min(point[1] for point in box), max(point[1] for point in box)
            lines.append((text, float(top), float(bottom), float(confidence)))
    if not lines:
        return {"text": "", "word_count": 0, "uncertain": False, "truncated": False}
    typical_height = statistics.median(max(1, bottom - top) for _, top, bottom, _ in lines)
    paragraphs = []
    words = []
    previous_bottom = None
    for text, top, bottom, _ in lines:
        if previous_bottom is not None and top - previous_bottom > typical_height * 0.8:
            paragraphs.append(" ".join(words))
            words = []
        words.append(text)
        previous_bottom = bottom
    paragraphs.append(" ".join(words))
    text = "\n\n".join(paragraphs)
    return {"text": text[:MAX_TEXT], "word_count": len(text.split()),
            "uncertain": any(score < 0.8 for _, _, _, score in lines),
            "truncated": len(text) > MAX_TEXT}


def recognize(image_path):
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
    models = ocr_model_paths()
    if not models or not all(path.is_file() for path in models.values()):
        raise RuntimeError("Reinstall requirements.txt to restore the bundled OCR models.")
    import onnxruntime
    onnxruntime.disable_telemetry_events()
    import cv2
    cv2.setNumThreads(1)
    from rapidocr import EngineType, ModelType, OCRVersion, RapidOCR

    # Explicit local paths prevent downloads during a scan. The models ship in
    # the pinned Python package and the classifier corrects upside-down lines.
    engine = RapidOCR(params={
        **{f"{stage}.model_path": str(path) for stage, path in models.items()},
        **{f"{stage}.engine_type": EngineType.ONNXRUNTIME for stage in models},
        **{f"{stage}.ocr_version": OCRVersion.PPOCRV6 for stage in ("Det", "Rec")},
        **{f"{stage}.model_type": ModelType.SMALL for stage in ("Det", "Rec")},
        "Cls.ocr_version": OCRVersion.PPOCRV4,
        "Cls.model_type": ModelType.MOBILE,
        "Global.log_level": "error",
        "Global.text_score": 0.3,
        "EngineConfig.onnxruntime.intra_op_num_threads": ocr_cpu_threads(),
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        "EngineConfig.onnxruntime.use_cuda": False,
        "EngineConfig.onnxruntime.use_dml": False,
        "EngineConfig.onnxruntime.use_cann": False,
        "EngineConfig.onnxruntime.use_coreml": False,
        "Det.limit_type": "max",
        "Det.limit_side_len": 1600,
    })
    return {**reading_result(engine(image)), "model": OCR_MODEL}


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

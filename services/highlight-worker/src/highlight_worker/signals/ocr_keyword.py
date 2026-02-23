"""OCR Keyword Detection — event-triggered, region-aware, regex pattern groups.

Improvements over v1:
- Regex pattern groups (combat, victory, intensity, sports) instead of flat keyword list
- Frame preprocessing: grayscale + contrast boost before Tesseract
- Dynamic text region detection via OpenCV (graceful fallback to full-frame if cv2 absent)
- OCR text normalization (0→o, 1→l, 5→s, lowercase, strip punctuation)
- Tesseract config: primary --oem 1 --psm 6, fallback --psm 11
- Temporal boost: same pattern fires ≥2 times within 3s → +0.2
- All OpenCV operations run in a thread via asyncio.to_thread to avoid blocking
"""

import asyncio
import logging
import os
import re
import tempfile
from pathlib import Path
from collections import defaultdict

from . import BaseSignal

logger = logging.getLogger(__name__)

# ── Compiled regex patterns (module-level) ─────────────────────────────────────

COMBAT_RE = re.compile(
    r"\b(kill(ed|ing)?|eliminat(ed|ion|e)?|slain|defeat(ed)?|down(ed)?"
    r"|knock(ed)?|finish(ed)?|head\s?shot|ace|clutch)\b",
    re.IGNORECASE,
)

VICTORY_RE = re.compile(
    r"\b(victor(y|ious)?|win(s|ner|ning)?|defeat(ed)?|champion|game\s+over"
    r"|round\s+win|mvp|flawless|match\s+complete)\b",
    re.IGNORECASE,
)

INTENSITY_RE = re.compile(
    r"\b(1v[1-5]|last\s+player|overtime|sudden\s+death|match\s+point"
    r"|ultimate|critical|first\s+blood|penta|multi\s?kill)\b",
    re.IGNORECASE,
)

SPORTS_RE = re.compile(
    r"\b(goal|scor(ed|ing)?|touchdown|home\s+run|hat\s+trick|strike)\b",
    re.IGNORECASE,
)

KILLFEED_RE = re.compile(
    r"(\b[A-Z][a-zA-Z0-9_]{2,15}\b\s*[^a-zA-Z0-9\s]{1,4}\s*\b[A-Z][a-zA-Z0-9_]{2,15}\b|\[[a-zA-Z0-9_]+\]\s*[^a-zA-Z0-9\s]{1,4}\s*\[[a-zA-Z0-9_]+\])",
)

ALL_PATTERNS = [
    ("combat", COMBAT_RE, 0.6),
    ("victory", VICTORY_RE, 0.8),
    ("intensity", INTENSITY_RE, 0.5),
    ("sports", SPORTS_RE, 0.5),
    ("killfeed", KILLFEED_RE, 0.6),
]

PVP_KILL_RE = re.compile(
    r"\b([A-Z][a-zA-Z0-9]{2,12})\b\s*([^a-zA-Z0-9\s]{1,3})\s*\b([A-Z][a-zA-Z0-9]{2,12})\b",
)


def _normalize_ocr_text(text: str) -> str:
    """Apply OCR-specific normalization before pattern matching."""
    text = text.lower()
    text = text.replace("0", "o").replace("1", "l").replace("5", "s")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return text


def _score_text(raw_text: str, norm_text: str) -> tuple[float, list[str]]:
    """Return (score, matched_pattern_names) checking both raw and normalized OCR text."""
    score = 0.0
    matched = []
    for name, pattern, weight in ALL_PATTERNS:
        if name == "killfeed":
            if pattern.search(raw_text):
                score += weight
                matched.append(name)
        else:
            if pattern.search(norm_text):
                score += weight
                matched.append(name)
    
    if PVP_KILL_RE.search(raw_text):
        score += 0.5
        matched.append("pvp_kill")

    return min(1.0, score), matched

def _run_tesseract_with_conf(img, config_str: str, conf_threshold: float) -> str:
    import pytesseract
    try:
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, config=config_str)
        words = []
        raw_words = []
        for i, word in enumerate(data.get("text", [])):
            word = word.strip()
            if not word: continue
            conf = float(data.get("conf", [0])[i])
            raw_words.append(f"{word}({conf:.0f})")
            if conf >= conf_threshold:
                words.append(word)
                
        valid_str = " ".join(words)
        if valid_str:
             logger.debug(f"OCR Raw output: {' '.join(raw_words)} | Filtered: {valid_str}")
        return valid_str
    except Exception as e:
        return ""


# ── OpenCV region detection

def _detect_text_regions_cv2(img_array):
    """
    Use OpenCV Sobel + morphological close to detect text-like contour regions.
    Returns list of (x, y, w, h) tuples, or empty list if nothing found.
    Runs single-core friendly (no parallelism inside).
    """
    import cv2
    import numpy as np

    gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)

    # Sobel edge detection
    sobelx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    sobely = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    edges = cv2.convertScaleAbs(sobelx) + cv2.convertScaleAbs(sobely)
    _, binary = cv2.threshold(edges, 50, 255, cv2.THRESH_BINARY)

    # Morphological close to join nearby text glyphs
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 5))
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    regions = []
    h_img, w_img = gray.shape
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w < 15 or h > 200:
            continue
        aspect = w / max(h, 1)
        if aspect < 0.5 or aspect > 30:
            continue
        if w * h < 100:
            continue
        regions.append((x, y, w, h))

    return regions


class OCRKeywordSignal(BaseSignal):
    """Event-triggered OCR with region detection and compiled regex patterns."""

    @property
    def name(self) -> str:
        return "ocr_keyword"

    async def detect(self, proxy_path: str, config: dict, **kwargs) -> dict[int, float]:
        enabled = config.get("enabled", False)
        if not enabled:
            logger.info("OCR keyword signal is disabled")
            return {}

        target_seconds = kwargs.get("target_seconds")
        if target_seconds is not None and not target_seconds:
            return {}

        confidence_threshold = int(config.get("confidence_threshold", 60))
        duration = kwargs.get("duration", 0)
        sample_interval = float(config.get("sample_interval", 1.0))
        max_frames = config.get("max_frames", 450)

        # Check Tesseract availability
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
        except Exception as e:
            logger.warning(f"OCR: Tesseract not available: {e}")
            return {}

        # Detect if OpenCV is usable
        try:
            import cv2
            _cv2_available = True
            logger.debug("OCR: OpenCV available — using dynamic region detection")
        except ImportError:
            _cv2_available = False
            logger.info("OCR: OpenCV not available — falling back to full-frame scan")

        scores: dict[int, float] = {}
        frame_dir = tempfile.mkdtemp(prefix="ocr_frames_")

        try:
            from PIL import Image, ImageEnhance
            import pytesseract

            # ── Extract frames
            # Pass 2: If we have target_seconds, only extract those
            if target_seconds:
                sorted_targets = sorted(list(target_seconds))
                select_expr = "+".join([f"eq(n,{s})" for s in sorted_targets])
                fps_filter = f"fps=1,select='{select_expr}'"
                logger.info(f"OCR: Target-Pass triggered — scanning {len(sorted_targets)} candidate seconds")
            else:
                # Adjust interval for very long videos to stay under timeout
                if duration > max_frames:
                    sample_interval = max(sample_interval, duration / max_frames)
                    logger.info(f"OCR: Long video detected (Pass 1 fallback), adaptive sample_interval={sample_interval:.2f}s")
                fps_filter = f"fps=1/{sample_interval}"

            # Preprocess in FFmpeg: sub-scale for faster Tesseract and cv2 parsing
            vf_filter = "scale=426:240,format=gray,eq=contrast=1.4:brightness=0.05"

            ffmpeg_cmd = [
                "nice", "-n", "15",
                "ffmpeg", "-y",
                "-i", proxy_path,
                "-vf", f"{fps_filter},{vf_filter}",
                "-q:v", "3",
                os.path.join(frame_dir, "frame_%06d.jpg"),
            ]

            proc = await asyncio.create_subprocess_exec(
                *ffmpeg_cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stderr_lines = []
            while True:
                line_bytes = await proc.stderr.readline()
                if not line_bytes:
                    break
                stderr_lines.append(line_bytes.decode("utf-8", errors="replace"))
                await asyncio.sleep(0)

            await proc.wait()
            stderr_str = "".join(stderr_lines)

            if proc.returncode != 0:
                logger.warning(f"OCR: FFmpeg extraction failed: {stderr_str[-300:]}")
                return {}

            frame_files = sorted(Path(frame_dir).glob("frame_*.jpg"))
            logger.info(f"OCR: Processing {len(frame_files)} frames (cv2={_cv2_available})")

            # ── Temporal tracking for boost
            recent_patterns: dict[str, list[float]] = defaultdict(list)
            sorted_targets = sorted(list(target_seconds)) if target_seconds else []

            for i, frame_path in enumerate(frame_files):
                if target_seconds:
                    if i < len(sorted_targets):
                        second = sorted_targets[i]
                    else:
                        continue
                else:
                    second = int(i * sample_interval)
                
                try:
                    img = Image.open(frame_path).convert("RGB")
                    texts_to_check: list[str] = []

                    if _cv2_available:
                        import numpy as np
                        img_array = np.array(img)

                        regions = await asyncio.to_thread(_detect_text_regions_cv2, img_array)

                        if regions:
                            regions = sorted(regions, key=lambda r: r[2]*r[3], reverse=True)[:5]
                            
                            for (rx, ry, rw, rh) in regions:
                                pad = 4
                                rx1 = max(0, rx - pad)
                                ry1 = max(0, ry - pad)
                                rx2 = min(img.width, rx + rw + pad)
                                ry2 = min(img.height, ry + rh + pad)
                                crop = img.crop((rx1, ry1, rx2, ry2))
                                
                                t = await asyncio.to_thread(
                                    _run_tesseract_with_conf,
                                    crop,
                                    "--oem 1 --psm 6 -c load_system_dawg=0 -c load_freq_dawg=0",
                                    confidence_threshold
                                )
                                if t: texts_to_check.append(t)

                            if not texts_to_check:

                                t = await asyncio.to_thread(
                                    _run_tesseract_with_conf,
                                    img,
                                    "--oem 1 --psm 11",
                                    confidence_threshold
                                )
                                if t: texts_to_check.append(t)
                        else:
                            # No regions found — full-frame fallback
                            t = await asyncio.to_thread(
                                _run_tesseract_with_conf,
                                img,
                                "--oem 1 --psm 11",
                                confidence_threshold
                            )
                            if t: texts_to_check.append(t)
                    else:

                        t = await asyncio.to_thread(
                            _run_tesseract_with_conf,
                            img,
                            "--oem 1 --psm 6 -c load_system_dawg=0 -c load_freq_dawg=0",
                            confidence_threshold
                        )
                        if t: texts_to_check.append(t)

                    # ── Normalize + score all extracted texts
                    frame_score = 0.0
                    frame_patterns: list[str] = []
                    for raw_text in texts_to_check:
                        norm = _normalize_ocr_text(raw_text)
                        s, matched = _score_text(raw_text, norm)
                        if s > 0:
                            frame_score = max(frame_score, s)
                            frame_patterns.extend(matched)
                            logger.debug(f"OCR: t={second}s matched {matched} (score={s:.2f})")

                    # ── Temporal boost
                    for pat_name in frame_patterns:
                        recent_patterns[pat_name].append(float(second))
                        recent_patterns[pat_name] = [
                            t for t in recent_patterns[pat_name] if second - t <= 3.0
                        ]
                        if len(recent_patterns[pat_name]) >= 2:
                            frame_score = min(1.0, frame_score + 0.2)
                            logger.debug(f"OCR: temporal boost at t={second}s (pattern={pat_name})")

                    if frame_score > 0:
                        scores[second] = max(scores.get(second, 0), frame_score)

                except Exception as e:
                    logger.debug(f"OCR: frame {i} failed: {e}")
                    continue

            logger.info(
                f"OCR: complete — {len(scores)} keyword matches in {len(frame_files)} frames"
            )

        finally:
            import shutil
            shutil.rmtree(frame_dir, ignore_errors=True)

        return scores

"""
Best-effort visual/spatial grounding for schematics and teardown images.

HMGCC Q&A Q65/Q107: "Text extraction and indexing from images and
schematics is a baseline essential... we would view positively a solution
which demonstrates spatial awareness of diagrams; recognising that
components are connected." HMGCC's own answer acknowledges full visual
reasoning over engineering schematics is a hard, open problem within this
project's scope - this module implements a documented heuristic, not true
circuit-topology understanding:

  1. Run OCR to get word-level bounding boxes (component labels / reference
     designators / pin names).
  2. Detect long straight line segments (Hough transform) as candidate
     wires/connectors.
  3. For each line segment, find the nearest OCR label to each endpoint and
     record a candidate "connection" between those two labels.

Output feeds the existing knowledge-graph tables as `schematic_component`
nodes and `CONNECTED_VIA_LINE` edges, each carrying a confidence value so
the researcher can see this is a heuristic hypothesis, not verified ground
truth (per Q&A Q53: "surface multiple plausible hypotheses with supporting
evidence").
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple


def _tesseract_boxes(image_path: Path, tesseract_cmd: str) -> List[dict]:
    import pytesseract
    from PIL import Image

    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    img = Image.open(str(image_path))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    data = pytesseract.image_to_data(img, config="--psm 11", output_type=pytesseract.Output.DICT)

    boxes = []
    n = len(data.get("text", []))
    for i in range(n):
        txt = (data["text"][i] or "").strip()
        try:
            conf = float(data.get("conf", ["-1"])[i])
        except (ValueError, TypeError):
            conf = -1.0
        if not txt or conf < 40:
            continue
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        boxes.append({"text": txt, "x": x, "y": y, "w": w, "h": h,
                      "cx": x + w / 2.0, "cy": y + h / 2.0, "conf": conf / 100.0})
    return boxes


def _detect_lines(image_path: Path) -> List[Tuple[float, float, float, float]]:
    import cv2
    import numpy as np

    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return []
    edges = cv2.Canny(img, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=60,
                             minLineLength=40, maxLineGap=8)
    if lines is None:
        return []
    return [tuple(map(float, line[0])) for line in lines[:500]]


def _nearest_box(x: float, y: float, boxes: List[dict], max_dist: float = 80.0):
    best, best_d = None, max_dist
    for b in boxes:
        d = ((b["cx"] - x) ** 2 + (b["cy"] - y) ** 2) ** 0.5
        if d < best_d:
            best, best_d = b, d
    return best


def analyse_schematic(image_path: Path, tesseract_cmd: str) -> dict:
    """Return {"labels": [...], "connections": [...]} - best-effort only.
    Any failure degrades to an empty result rather than raising, so a
    malformed/unsupported image never breaks the wider ingest pipeline."""
    try:
        boxes = _tesseract_boxes(image_path, tesseract_cmd)
    except Exception:
        boxes = []

    connections = []
    try:
        lines = _detect_lines(image_path)
        for (x1, y1, x2, y2) in lines:
            a = _nearest_box(x1, y1, boxes)
            b = _nearest_box(x2, y2, boxes)
            if a and b and a["text"] != b["text"]:
                connections.append({
                    "source": a["text"], "target": b["text"],
                    "relation": "CONNECTED_VIA_LINE", "confidence": 0.5,
                })
    except Exception:
        pass

    # De-duplicate connections (undirected)
    seen = set()
    deduped = []
    for c in connections:
        key = tuple(sorted((c["source"], c["target"])))
        if key not in seen:
            seen.add(key)
            deduped.append(c)

    return {
        "labels": [{"text": b["text"], "x": b["cx"], "y": b["cy"], "confidence": b["conf"]} for b in boxes],
        "connections": deduped,
        "method": "heuristic-hough-ocr-proximity",
        "caveat": "Best-effort spatial heuristic, not verified circuit topology - treat as a hypothesis.",
    }

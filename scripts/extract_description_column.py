#!/usr/bin/env python3
"""
Extract DESCRIPTION-column items from tables in a PDF.

Pipeline:
1. Render PDF pages to PNG with pdftoppm.
2. Try 0/90/180/270 degree page rotations.
3. OCR the page to locate the DESCRIPTION header.
4. Detect table grid lines around that header.
5. OCR each row cell below DESCRIPTION and write copy/paste friendly TXT.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Iterable

import cv2
import numpy as np
import pytesseract


@dataclass
class DescriptionItem:
    page: int
    row: int
    text: str
    raw_text: str
    bbox: tuple[int, int, int, int]


ProgressCallback = Callable[[dict], None]


def emit_progress(progress_callback: ProgressCallback | None, **event: object) -> None:
    if progress_callback:
        progress_callback(event)


def render_pdf(pdf_path: Path, work_dir: Path, dpi: int) -> list[Path]:
    if not shutil.which("pdftoppm"):
        raise RuntimeError("pdftoppm is required. Install poppler-utils/poppler first.")

    prefix = work_dir / "page"
    subprocess.run(
        ["pdftoppm", "-png", "-r", str(dpi), str(pdf_path), str(prefix)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return sorted(work_dir.glob("page-*.png"))


def rotate_image(img: np.ndarray, angle: int) -> np.ndarray:
    if angle == 90:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if angle == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    if angle == 270:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img


def group_positions(indices: Iterable[int], max_gap: int = 8) -> list[int]:
    indices = list(indices)
    if not indices:
        return []

    groups: list[int] = []
    current = [indices[0]]
    for value in indices[1:]:
        if value - current[-1] <= max_gap:
            current.append(value)
        else:
            groups.append(int(np.mean(current)))
            current = [value]
    groups.append(int(np.mean(current)))
    return groups


def binary_image(img: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY_INV)
    return binary


def vertical_line_groups(img: np.ndarray) -> list[int]:
    binary = binary_image(img)
    height, _ = binary.shape
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(50, height // 35)))
    lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)
    scores = np.sum(lines, axis=0) / 255
    strong = np.where(scores > max(40, height * 0.08))[0]
    return group_positions(strong, max_gap=10)


def horizontal_line_groups(img: np.ndarray, x1: int, x2: int) -> list[int]:
    binary = binary_image(img)
    roi = binary[:, max(0, x1): min(binary.shape[1], x2)]
    width = roi.shape[1]
    if width <= 0:
        return []

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(60, width // 5), 1))
    lines = cv2.morphologyEx(roi, cv2.MORPH_OPEN, kernel, iterations=1)
    scores = np.sum(lines, axis=1) / 255
    strong = np.where(scores > max(50, width * 0.18))[0]
    return group_positions(strong, max_gap=10)


def ocr_words(img: np.ndarray, config: str = "--oem 3 --psm 6", max_width: int | None = None) -> list[dict]:
    scale = 1.0
    ocr_img = img
    if max_width and img.shape[1] > max_width:
        scale = max_width / img.shape[1]
        ocr_img = cv2.resize(
            img,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_AREA,
        )

    data = pytesseract.image_to_data(
        ocr_img,
        lang="eng",
        config=config,
        output_type=pytesseract.Output.DICT,
    )
    words = []
    for idx, text in enumerate(data["text"]):
        cleaned = text.strip()
        if not cleaned:
            continue
        try:
            conf = float(data["conf"][idx])
        except ValueError:
            conf = -1
        words.append(
            {
                "text": cleaned,
                "upper": cleaned.upper(),
                "conf": conf,
                "left": int(data["left"][idx] / scale),
                "top": int(data["top"][idx] / scale),
                "width": int(data["width"][idx] / scale),
                "height": int(data["height"][idx] / scale),
            }
        )
    return words


def find_description_header(words: list[dict]) -> dict | None:
    candidates = [
        word for word in words
        if "DESCRIPTION" in word["upper"] and word["conf"] >= 20
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda word: (word["conf"], word["width"] * word["height"]))


def choose_page_orientation(img: np.ndarray) -> tuple[np.ndarray, int, dict | None]:
    best = (None, 0, None, -1.0)
    for angle in (0, 90, 180, 270):
        rotated = rotate_image(img, angle)
        words = ocr_words(rotated, max_width=1600)
        header = find_description_header(words)
        if header is None:
            score = 0.0
        else:
            keyword_hits = sum(
                1 for word in words
                if word["upper"].strip(":.") in {"ITEM", "POS", "DESCRIPTION", "DESCRIZIONE"}
            )
            score = header["conf"] + keyword_hits * 10

        if score > best[3]:
            best = (rotated, angle, header, score)

    return best[0], best[1], best[2]


def find_column_bounds(img: np.ndarray, header: dict) -> tuple[int, int] | None:
    lines = vertical_line_groups(img)
    header_center = header["left"] + header["width"] // 2
    left_lines = [x for x in lines if x < header_center]
    right_lines = [x for x in lines if x > header_center]
    if not left_lines or not right_lines:
        return None

    left = max(left_lines)
    right = min(right_lines)
    if right - left < 80:
        return None
    return left, right


def clean_ocr_text(text: str, first_line_only: bool) -> tuple[str, str]:
    raw_lines = []
    for line in text.splitlines():
        line = line.strip()
        line = re.sub(r"\s+", " ", line)
        line = line.replace("—", "-").replace("–", "-")
        if line:
            raw_lines.append(line)

    raw = "\n".join(raw_lines)
    if first_line_only:
        return (raw_lines[0] if raw_lines else ""), raw
    return " / ".join(raw_lines), raw


def words_to_cell_text(words: list[dict], first_line_only: bool) -> tuple[str, str]:
    if not words:
        return "", ""

    line_groups: list[list[dict]] = []
    for word in sorted(words, key=lambda item: (item["top"], item["left"])):
        center_y = word["top"] + word["height"] / 2
        matched = False
        for group in line_groups:
            group_center = np.mean([item["top"] + item["height"] / 2 for item in group])
            if abs(center_y - group_center) <= max(10, word["height"] * 0.7):
                group.append(word)
                matched = True
                break
        if not matched:
            line_groups.append([word])

    lines = []
    for group in line_groups:
        group.sort(key=lambda item: item["left"])
        line = " ".join(item["text"] for item in group)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)

    return clean_ocr_text("\n".join(lines), first_line_only=first_line_only)


def ocr_description_rows(
    rotated: np.ndarray,
    x1: int,
    x2: int,
    lower_lines: list[int],
    first_line_only: bool,
) -> list[tuple[int, str, str, tuple[int, int, int, int]]]:
    pad_x = 6
    valid_pairs = [
        (top, bottom)
        for top, bottom in zip(lower_lines, lower_lines[1:])
        if bottom - top >= 20
    ]
    if not valid_pairs:
        return []

    y1 = min(top for top, _ in valid_pairs)
    y2 = max(bottom for _, bottom in valid_pairs)
    crop = rotated[y1:y2, x1 + pad_x:x2 - pad_x]
    if crop.size == 0:
        return []

    words = ocr_words(crop, config="--oem 3 --psm 6")
    for word in words:
        word["left"] += x1 + pad_x
        word["top"] += y1

    row_results = []
    row_num = 0
    row_heights = [bottom - top for top, bottom in valid_pairs]
    typical_row_height = float(np.median(row_heights)) if row_heights else 0.0

    for top, bottom in valid_pairs:
        row_height = bottom - top
        if typical_row_height and row_height > typical_row_height * 3:
            break
        row_num += 1

        pad_y = max(4, int(row_height * 0.07))
        cell_top = top + pad_y
        cell_bottom = bottom - pad_y
        row_words = [
            word for word in words
            if cell_top <= word["top"] + word["height"] / 2 <= cell_bottom
        ]
        cleaned, raw = words_to_cell_text(row_words, first_line_only=first_line_only)
        if cleaned:
            row_results.append(
                (
                    row_num,
                    cleaned,
                    raw,
                    (x1 + pad_x, cell_top, x2 - pad_x, cell_bottom),
                )
            )

    return row_results


def rotated_bbox_to_original(
    bbox: tuple[int, int, int, int],
    angle: int,
    original_shape: tuple[int, int, int],
) -> tuple[int, int, int, int]:
    """Convert a bbox from rotated-page coordinates back to original-page coordinates."""
    x1, y1, x2, y2 = bbox
    height, width = original_shape[:2]
    corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]

    original_points = []
    for x, y in corners:
        if angle == 90:
            ox, oy = y, height - x
        elif angle == 180:
            ox, oy = width - x, height - y
        elif angle == 270:
            ox, oy = width - y, x
        else:
            ox, oy = x, y
        original_points.append((ox, oy))

    xs = [point[0] for point in original_points]
    ys = [point[1] for point in original_points]
    return (
        max(0, min(xs)),
        max(0, min(ys)),
        min(width - 1, max(xs)),
        min(height - 1, max(ys)),
    )


def extract_page_items(
    img: np.ndarray,
    page_num: int,
    first_line_only: bool,
    debug_dir: Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[list[DescriptionItem], dict]:
    emit_progress(
        progress_callback,
        stage="orientation",
        page=page_num,
        message=f"{page_num}페이지: DESCRIPTION 헤더와 회전 방향 확인 중",
    )
    rotated, angle, header = choose_page_orientation(img)
    meta = {
        "page": page_num,
        "rotation": angle,
        "found_header": bool(header),
        "items": 0,
    }
    if rotated is None or header is None:
        emit_progress(
            progress_callback,
            stage="page_done",
            page=page_num,
            items=0,
            message=f"{page_num}페이지: DESCRIPTION 헤더를 찾지 못함",
        )
        return [], meta

    emit_progress(
        progress_callback,
        stage="table",
        page=page_num,
        rotation=angle,
        message=f"{page_num}페이지: 테이블 경계와 DESCRIPTION 컬럼 찾는 중",
    )
    bounds = find_column_bounds(rotated, header)
    if bounds is None:
        emit_progress(
            progress_callback,
            stage="page_done",
            page=page_num,
            rotation=angle,
            items=0,
            message=f"{page_num}페이지: DESCRIPTION 컬럼 경계를 찾지 못함",
        )
        return [], meta

    x1, x2 = bounds
    row_lines = horizontal_line_groups(rotated, x1, x2)
    header_center_y = header["top"] + header["height"] // 2
    lower_lines = [y for y in row_lines if y > header_center_y]
    if len(lower_lines) < 2:
        emit_progress(
            progress_callback,
            stage="page_done",
            page=page_num,
            rotation=angle,
            items=0,
            message=f"{page_num}페이지: 행 경계를 찾지 못함",
        )
        return [], meta

    emit_progress(
        progress_callback,
        stage="ocr",
        page=page_num,
        rotation=angle,
        rows=max(0, len(lower_lines) - 1),
        message=f"{page_num}페이지: DESCRIPTION 컬럼 OCR 중",
    )
    items = [
        DescriptionItem(
            page=page_num,
            row=row_num,
            text=cleaned,
            raw_text=raw,
            bbox=bbox,
        )
        for row_num, cleaned, raw, bbox in ocr_description_rows(
            rotated,
            x1,
            x2,
            lower_lines,
            first_line_only=first_line_only,
        )
    ]

    if debug_dir:
        emit_progress(
            progress_callback,
            stage="overlay",
            page=page_num,
            items=len(items),
            message=f"{page_num}페이지: 원본 위치 표시 이미지 생성 중",
        )
        debug_dir.mkdir(parents=True, exist_ok=True)
        vis = rotated.copy()
        cv2.rectangle(vis, (x1, 0), (x2, vis.shape[0] - 1), (255, 0, 0), 4)
        for item in items:
            bx1, by1, bx2, by2 = item.bbox
            cv2.rectangle(vis, (bx1, by1), (bx2, by2), (0, 0, 255), 3)
        cv2.imwrite(str(debug_dir / f"page_{page_num:03d}_description_column.png"), vis)

        original_vis = img.copy()
        for item in items:
            bx1, by1, bx2, by2 = rotated_bbox_to_original(item.bbox, angle, img.shape)
            cv2.rectangle(original_vis, (bx1, by1), (bx2, by2), (0, 0, 255), 5)
            label = str(item.row)
            cv2.putText(
                original_vis,
                label,
                (bx1, max(20, by1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (0, 0, 255),
                2,
                cv2.LINE_AA,
            )
        cv2.imwrite(str(debug_dir / f"page_{page_num:03d}_original_overlay.png"), original_vis)

    meta["items"] = len(items)
    meta["column_bounds"] = bounds
    emit_progress(
        progress_callback,
        stage="page_done",
        page=page_num,
        rotation=angle,
        items=len(items),
        message=f"{page_num}페이지 완료: {len(items)}개 추출",
    )
    return items, meta


def extract_descriptions(
    pdf_path: Path,
    output_txt: Path,
    output_json: Path | None,
    dpi: int,
    first_line_only: bool,
    debug_dir: Path | None,
    progress_callback: ProgressCallback | None = None,
) -> list[DescriptionItem]:
    all_items: list[DescriptionItem] = []
    page_meta = []

    with tempfile.TemporaryDirectory(prefix="pdf_desc_extract_") as tmp:
        emit_progress(
            progress_callback,
            stage="render",
            message=f"PDF를 {dpi} DPI 이미지로 변환 중",
        )
        pages = render_pdf(pdf_path, Path(tmp), dpi=dpi)
        total_pages = len(pages)
        emit_progress(
            progress_callback,
            stage="render_done",
            total_pages=total_pages,
            message=f"PDF 변환 완료: {total_pages}페이지",
        )
        for page_idx, page_path in enumerate(pages, start=1):
            emit_progress(
                progress_callback,
                stage="page_start",
                page=page_idx,
                total_pages=total_pages,
                message=f"{page_idx}/{total_pages}페이지 처리 시작",
            )
            img = cv2.imread(str(page_path))
            if img is None:
                emit_progress(
                    progress_callback,
                    stage="page_done",
                    page=page_idx,
                    total_pages=total_pages,
                    items=0,
                    message=f"{page_idx}페이지 이미지를 읽지 못함",
                )
                continue
            items, meta = extract_page_items(
                img,
                page_idx,
                first_line_only=first_line_only,
                debug_dir=debug_dir,
                progress_callback=lambda event, total_pages=total_pages: progress_callback(
                    {**event, "total_pages": total_pages}
                ) if progress_callback else None,
            )
            all_items.extend(items)
            page_meta.append(meta)

    output_txt.parent.mkdir(parents=True, exist_ok=True)
    output_txt.write_text(
        "\n".join(item.text for item in all_items) + ("\n" if all_items else ""),
        encoding="utf-8",
    )

    if output_json:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(
            json.dumps(
                {
                    "pdf": str(pdf_path),
                    "output_txt": str(output_txt),
                    "pages": page_meta,
                    "items": [asdict(item) for item in all_items],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    return all_items


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract DESCRIPTION column values from PDF tables into TXT."
    )
    parser.add_argument("pdf", type=Path, help="Input PDF path")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("description_items.txt"),
        help="Output TXT path",
    )
    parser.add_argument("--json", type=Path, help="Optional JSON debug/result path")
    parser.add_argument("--debug-dir", type=Path, help="Optional debug image directory")
    parser.add_argument("--dpi", type=int, default=300, help="PDF render DPI")
    parser.add_argument(
        "--include-all-lines",
        action="store_true",
        help="Keep all OCR lines in each DESCRIPTION cell instead of the first line only",
    )
    args = parser.parse_args()

    items = extract_descriptions(
        pdf_path=args.pdf,
        output_txt=args.output,
        output_json=args.json,
        dpi=args.dpi,
        first_line_only=not args.include_all_lines,
        debug_dir=args.debug_dir,
    )

    print(f"Extracted {len(items)} DESCRIPTION items")
    print(f"Wrote: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

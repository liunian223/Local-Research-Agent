from __future__ import annotations

from pathlib import Path
from typing import Any

import config
from database import new_id


def render_pdf_pages(pdf_path: str | Path, paper_id: str, page_numbers: list[int]) -> dict[str, Any]:
    if not config.PDF_PAGE_RENDER_ENABLED:
        return {"status": "disabled", "assets": [], "errors": []}
    assets: list[dict[str, Any]] = []
    errors: list[str] = []
    target_dir = config.PDF_RENDERED_PAGE_DIR / paper_id
    target_dir.mkdir(parents=True, exist_ok=True)
    unique_pages = sorted({int(page) for page in page_numbers if int(page) > 0})
    if not unique_pages:
        return {"status": "skipped", "assets": [], "errors": []}
    try:
        import fitz

        scale = config.PDF_RENDER_DPI / 72
        with fitz.open(pdf_path) as doc:
            for page_no in unique_pages[: config.MAX_VISION_IMAGES_PER_CALL]:
                if page_no > doc.page_count:
                    continue
                page = doc[page_no - 1]
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                image_path = target_dir / f"page_{page_no:03d}.png"
                pix.save(str(image_path))
                assets.append(
                    {
                        "image_id": new_id("img"),
                        "paper_id": paper_id,
                        "page_no": page_no,
                        "image_index": None,
                        "image_path": str(image_path),
                        "width": int(pix.width),
                        "height": int(pix.height),
                        "source_type": "rendered_page",
                    }
                )
    except Exception as exc:
        errors.append(str(exc)[:300])
        return {"status": "failed", "assets": assets, "errors": errors}
    return {"status": "success" if assets else "empty", "assets": assets, "errors": errors}

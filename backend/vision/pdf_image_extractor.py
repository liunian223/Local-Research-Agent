from __future__ import annotations

from pathlib import Path
from typing import Any

import config
from database import new_id


def extract_pdf_images(pdf_path: str | Path, paper_id: str) -> dict[str, Any]:
    if not config.PDF_IMAGE_EXTRACT_ENABLED:
        return {"status": "disabled", "assets": [], "skipped_small": 0, "errors": []}
    assets: list[dict[str, Any]] = []
    skipped_small = 0
    errors: list[str] = []
    target_dir = config.PDF_IMAGE_DIR / paper_id
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        import fitz

        with fitz.open(pdf_path) as doc:
            for page_index in range(doc.page_count):
                if len(assets) >= config.MAX_PDF_IMAGES_PER_PAPER:
                    break
                page = doc[page_index]
                for image_index, image_info in enumerate(page.get_images(full=True), start=1):
                    if len(assets) >= config.MAX_PDF_IMAGES_PER_PAPER:
                        break
                    try:
                        xref = image_info[0]
                        pix = fitz.Pixmap(doc, xref)
                        if pix.n - pix.alpha >= 4:
                            pix = fitz.Pixmap(fitz.csRGB, pix)
                        width = int(pix.width)
                        height = int(pix.height)
                        if width < config.PDF_IMAGE_MIN_WIDTH or height < config.PDF_IMAGE_MIN_HEIGHT:
                            skipped_small += 1
                            continue
                        image_path = target_dir / f"page_{page_index + 1:03d}_img_{image_index:03d}.png"
                        pix.save(str(image_path))
                        assets.append(
                            {
                                "image_id": new_id("img"),
                                "paper_id": paper_id,
                                "page_no": page_index + 1,
                                "image_index": image_index,
                                "image_path": str(image_path),
                                "width": width,
                                "height": height,
                                "source_type": "embedded_image",
                            }
                        )
                    except Exception as exc:
                        errors.append(str(exc)[:300])
    except Exception as exc:
        errors.append(str(exc)[:300])
        return {"status": "failed", "assets": assets, "skipped_small": skipped_small, "errors": errors}
    status = "success" if not errors else "partial"
    return {"status": status, "assets": assets, "skipped_small": skipped_small, "errors": errors}

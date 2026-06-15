from __future__ import annotations

from note_skill import detailed_quality_check, repair_missing_sections


def test_quality_repair_adds_missing_sections() -> None:
    markdown = "---\ntitle: x\n---\n\n# x\n\n## 1. 鍩烘湰淇℃伅\n"
    quality = detailed_quality_check(markdown)
    assert quality["ok"] is False
    repaired = repair_missing_sections(markdown, {"title": "x"}, quality["missing_sections"][:2], [])
    assert quality["missing_sections"][0] in repaired

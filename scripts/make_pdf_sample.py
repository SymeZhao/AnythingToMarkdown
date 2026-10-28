"""生成一个最小可用的 PDF，用于测试转换（不依赖第三方库）。"""
from __future__ import annotations

import sys
from pathlib import Path


def make_pdf(path: Path) -> None:
    objects: list[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    # 1: Catalog, 2: Pages, 3: Page, 4: Contents, 5: Font
    font_id = 5
    page_id = 3

    content = b"BT /F1 18 Tf 72 760 Td (PDF Conversion Test) Tj ET\n"
    content += b"BT /F1 11 Tf 72 730 Td (Line one: hello world 12345) Tj ET\n"
    content += b"BT /F1 11 Tf 72 710 Td (Line two: second paragraph text) Tj ET\n"

    add(b"<< /Type /Catalog /Pages 2 0 R >>")
    add(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    add(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
    )
    add(
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"endstream"
    )
    add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    # 组装
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"

    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n"
    ).encode()

    path.write_bytes(bytes(out))
    print(f"已生成: {path} ({len(out)} 字节)")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("demo.pdf")
    make_pdf(target)

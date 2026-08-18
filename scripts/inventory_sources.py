#!/usr/bin/env python3
"""生成产品拆解来源清单；编号仅用于定位，不代表时间顺序。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


TYPE_BY_SUFFIX = {
    ".png": "screenshot",
    ".jpg": "screenshot",
    ".jpeg": "screenshot",
    ".gif": "screenshot",
    ".webp": "screenshot",
    ".mp4": "video",
    ".mov": "video",
    ".webm": "video",
    ".mkv": "video",
    ".html": "export",
    ".htm": "export",
    ".pdf": "export",
    ".csv": "log_or_table",
    ".json": "log_or_table",
    ".jsonl": "log_or_table",
    ".md": "document",
    ".txt": "document",
    ".log": "log_or_table",
}

FIELDS = (
    "source_id",
    "relative_path",
    "source_type",
    "bytes",
    "modified_at",
    "width",
    "height",
    "sha256",
    "chronology_status",
    "access_mode",
    "limitation",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="需要盘点的来源文件或目录")
    parser.add_argument("--output", type=Path, help="输出文件；不提供时写到标准输出")
    parser.add_argument("--format", choices=("csv", "json"), default="csv")
    parser.add_argument("--hash", action="store_true", help="计算 SHA-256，便于去重和版本核对")
    parser.add_argument("--include-hidden", action="store_true", help="包含隐藏文件")
    return parser.parse_args()


def natural_key(path: Path) -> list[object]:
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", str(path))]


def iter_files(root: Path, include_hidden: bool) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    for path in sorted((p for p in root.rglob("*") if p.is_file()), key=natural_key):
        relative = path.relative_to(root)
        if not include_hidden and any(part.startswith(".") for part in relative.parts):
            continue
        yield path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_size(path: Path) -> tuple[str, str]:
    """读取常见图片尺寸；失败时返回空值。"""
    try:
        with path.open("rb") as handle:
            header = handle.read(32)
            if header.startswith(b"\x89PNG\r\n\x1a\n"):
                width, height = struct.unpack(">II", header[16:24])
                return str(width), str(height)
            if header[:6] in {b"GIF87a", b"GIF89a"}:
                width, height = struct.unpack("<HH", header[6:10])
                return str(width), str(height)
            if header.startswith(b"\xff\xd8"):
                handle.seek(2)
                while True:
                    marker_start = handle.read(1)
                    if not marker_start:
                        break
                    if marker_start != b"\xff":
                        continue
                    marker = handle.read(1)
                    while marker == b"\xff":
                        marker = handle.read(1)
                    if marker in {b"\xd8", b"\xd9"}:
                        continue
                    length_bytes = handle.read(2)
                    if len(length_bytes) != 2:
                        break
                    length = struct.unpack(">H", length_bytes)[0]
                    if marker and marker[0] in range(0xC0, 0xC4):
                        data = handle.read(5)
                        if len(data) == 5:
                            height, width = struct.unpack(">HH", data[1:])
                            return str(width), str(height)
                        break
                    handle.seek(max(length - 2, 0), 1)
    except (OSError, struct.error, ValueError):
        pass
    return "", ""


def build_rows(root: Path, files: Iterable[Path], with_hash: bool) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    base = root if root.is_dir() else root.parent
    for index, path in enumerate(files, start=1):
        stat = path.stat()
        width, height = image_size(path)
        rows.append(
            {
                "source_id": f"SRC-{index:03d}",
                "relative_path": str(path.relative_to(base)),
                "source_type": TYPE_BY_SUFFIX.get(path.suffix.casefold(), "other"),
                "bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "width": width,
                "height": height,
                "sha256": sha256(path) if with_hash else "",
                "chronology_status": "unverified",
                "access_mode": "offline",
                "limitation": "",
            }
        )
    return rows


def render_csv(rows: list[dict[str, object]]) -> str:
    from io import StringIO

    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    if not root.exists():
        print(f"错误：来源路径不存在：{root}", file=sys.stderr)
        return 2

    rows = build_rows(root, iter_files(root, args.include_hidden), args.hash)
    content = (
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n"
        if args.format == "json"
        else render_csv(rows)
    )

    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        print(f"已生成来源清单：{output}（{len(rows)} 个文件）", file=sys.stderr)
    else:
        sys.stdout.write(content)
        print(f"已盘点 {len(rows)} 个文件；来源编号不代表时间顺序。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

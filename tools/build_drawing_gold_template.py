from __future__ import annotations

import argparse
import json
from pathlib import Path


def discover_ai_files(source_root: Path) -> list[Path]:
    root = source_root.resolve()
    return sorted(
        (path for path in root.rglob("*") if path.is_file() and path.suffix.lower() == ".ai"),
        key=lambda path: path.relative_to(root).as_posix(),
    )


def assert_output_outside_source(source_root: Path, output: Path) -> None:
    source = source_root.resolve()
    target = output.resolve()
    if target == source or source in target.parents:
        raise ValueError(f"output must be outside source root: {output}")


def build_gold_rows(source_root: Path) -> list[dict]:
    root = source_root.resolve()
    return [
        {
            "source": path.relative_to(root).as_posix(),
            "publication_kind": None,
            "number": None,
            "verification": "unknown",
            "notes": "",
        }
        for path in discover_ai_files(root)
    ]


def write_gold_template(source_root: Path, output: Path) -> list[dict]:
    assert_output_outside_source(source_root, output)
    rows = build_gold_rows(source_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a human-only gold template for drawing-evidence-v3.",
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    rows = write_gold_template(args.source_root, args.output)
    print(f"wrote {len(rows)} unknown gold rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

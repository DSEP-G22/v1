"""Regenerates migrations/001_init.sql from the current ORM metadata. Forward-only: this script
overwrites 001_init.sql; once a second migration is ever needed, hand-write 002_*.sql instead of
touching this one again."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.schema import CreateTable

from libs.platform.db.models import Base
from libs.platform.db.session import build_engine


def main() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    lines = [
        "-- Generated from libs/platform/db/models.py via scripts/generate_migration.py",
        "-- Forward-only. Do not hand-edit; add 002_*.sql for further changes.",
        "",
    ]
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(engine)).strip()
        lines.append(ddl + ";")
        lines.append("")

    out_path = Path(__file__).resolve().parents[1] / "migrations" / "001_init.sql"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()

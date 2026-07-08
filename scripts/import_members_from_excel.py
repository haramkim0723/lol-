from __future__ import annotations

import argparse
import sys
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import scrim_db


DEFAULT_PASSWORD = "1234"


def clean(value) -> str:
    return str(value or "").strip()


def split_riot_ids(raw: str) -> tuple[str, str | None]:
    parts = [part.strip() for part in raw.replace("\n", ",").split(",") if part.strip()]
    if not parts:
        return "", None
    return parts[0], parts[1] if len(parts) > 1 else None


def rows_from_workbook(path: Path) -> list[dict]:
    workbook = load_workbook(path, data_only=True, read_only=True)
    sheet = workbook["목록"]
    headers = [clean(cell.value) for cell in next(sheet.iter_rows(max_row=1))]
    name_index = headers.index("이름")
    riot_id_index = headers.index("아이디")
    rows = []
    for row in sheet.iter_rows(min_row=2):
        name = clean(row[name_index].value)
        raw_riot_id = clean(row[riot_id_index].value)
        riot_id, secondary_riot_id = split_riot_ids(raw_riot_id)
        if not name or not riot_id:
            continue
        rows.append(
            {
                "name": name,
                "riot_id": riot_id,
                "secondary_riot_id": secondary_riot_id,
            }
        )
    return rows


def import_rows(rows: list[dict], *, dry_run: bool) -> tuple[int, int]:
    created = 0
    skipped = 0
    if dry_run:
        return len(rows), skipped
    scrim_db.init_db()
    with scrim_db.connect() as connection:
        for row in rows:
            existing = scrim_db.get_user_by_riot_id(connection, row["riot_id"])
            if existing is None:
                scrim_db.create_user(
                    connection,
                    name=row["name"],
                    riot_id=row["riot_id"],
                    secondary_riot_id=row["secondary_riot_id"],
                    password=DEFAULT_PASSWORD,
                    approved=True,
                )
                created += 1
            else:
                connection.execute(
                    """
                    UPDATE users
                    SET name = ?,
                        secondary_riot_id = ?,
                        approved = 1,
                        is_active = 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE riot_id = ?
                    """,
                    (row["name"], row["secondary_riot_id"], row["riot_id"]),
                )
                skipped += 1
    return created, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="Import approved members from 수강대난투 Excel 목록 sheet.")
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows = rows_from_workbook(args.workbook)
    created, skipped = import_rows(rows, dry_run=args.dry_run)
    print(f"eligible_rows={len(rows)}")
    print(f"created={created}")
    print(f"skipped_duplicates={skipped}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import os
import secrets
import hashlib
import hmac
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


DEFAULT_DB_PATH = "data/scrim.db"


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  riot_id TEXT NOT NULL UNIQUE,
  secondary_riot_id TEXT,
  password_hash TEXT NOT NULL,
  name TEXT NOT NULL,
  nickname TEXT,
  phone TEXT,
  role TEXT NOT NULL DEFAULT 'USER'
    CHECK (role IN ('USER', 'ADMIN')),
  approved INTEGER NOT NULL DEFAULT 0,
  is_active INTEGER NOT NULL DEFAULT 1,
  last_login_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS roster_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_row INTEGER NOT NULL UNIQUE,
  name TEXT NOT NULL,
  participation_status_text TEXT,
  absence_reason TEXT,
  payment_status TEXT,
  riot_id TEXT,
  secondary_riot_id TEXT,
  tier TEXT,
  top_adjustment TEXT,
  game_count_adjustment TEXT,
  preferred_lines TEXT,
  score_top TEXT,
  score_jungle TEXT,
  score_mid TEXT,
  score_adc TEXT,
  score_support TEXT,
  notes TEXT,
  user_id INTEGER,
  account_status TEXT NOT NULL DEFAULT 'NOT_ELIGIBLE'
    CHECK (account_status IN ('NOT_ELIGIBLE', 'ISSUED')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS teams (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  invite_code TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'RECRUITING'
    CHECK (status IN ('RECRUITING', 'COMPLETE', 'DISBANDED')),
  top_rank TEXT,
  game_count INTEGER NOT NULL DEFAULT 0,
  created_by INTEGER NOT NULL,
  disbanded_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (created_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS team_members (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  team_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  role TEXT NOT NULL DEFAULT 'MEMBER'
    CHECK (role IN ('LEADER', 'MEMBER')),
  status TEXT NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('ACTIVE', 'LEFT', 'REMOVED')),
  joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  left_at TEXT,
  FOREIGN KEY (team_id) REFERENCES teams(id),
  FOREIGN KEY (user_id) REFERENCES users(id),
  UNIQUE (team_id, user_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_team_per_user
ON team_members(user_id)
WHERE status = 'ACTIVE';

CREATE TABLE IF NOT EXISTS team_join_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  team_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'CANCELED')),
  requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  processed_at TEXT,
  processed_by INTEGER,
  FOREIGN KEY (team_id) REFERENCES teams(id),
  FOREIGN KEY (user_id) REFERENCES users(id),
  FOREIGN KEY (processed_by) REFERENCES users(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_pending_join_request
ON team_join_requests(team_id, user_id)
WHERE status = 'PENDING';

CREATE TABLE IF NOT EXISTS participants (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  team_id INTEGER,
  user_id INTEGER,
  name TEXT NOT NULL,
  top_rank TEXT,
  game_count INTEGER NOT NULL DEFAULT 0,
  attendance_status TEXT NOT NULL DEFAULT 'PARTICIPATING'
    CHECK (attendance_status IN ('PARTICIPATING', 'ABSENT')),
  payment_status TEXT NOT NULL DEFAULT 'UNPAID'
    CHECK (payment_status IN ('PAID', 'UNPAID')),
  added_by INTEGER,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (team_id) REFERENCES teams(id),
  FOREIGN KEY (user_id) REFERENCES users(id),
  FOREIGN KEY (added_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS scrim_schedules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  team_id INTEGER NOT NULL,
  opponent_team_name TEXT,
  scheduled_date TEXT NOT NULL,
  start_time TEXT NOT NULL,
  end_time TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'RESERVED'
    CHECK (status IN ('RESERVED', 'CANCELED', 'COMPLETED')),
  memo TEXT,
  created_by INTEGER NOT NULL,
  updated_by INTEGER,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (team_id) REFERENCES teams(id),
  FOREIGN KEY (created_by) REFERENCES users(id),
  FOREIGN KEY (updated_by) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_scrim_schedules_team_date
ON scrim_schedules(team_id, scheduled_date, status);

CREATE TABLE IF NOT EXISTS scrim_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  team_id INTEGER NOT NULL,
  schedule_id INTEGER,
  match_date TEXT NOT NULL,
  opponent_team_name TEXT NOT NULL,
  our_score INTEGER NOT NULL,
  opponent_score INTEGER NOT NULL,
  result TEXT NOT NULL CHECK (result IN ('WIN', 'LOSE', 'DRAW')),
  memo TEXT,
  created_by INTEGER NOT NULL,
  updated_by INTEGER,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (team_id) REFERENCES teams(id),
  FOREIGN KEY (schedule_id) REFERENCES scrim_schedules(id),
  FOREIGN KEY (created_by) REFERENCES users(id),
  FOREIGN KEY (updated_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS notices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  is_pinned INTEGER NOT NULL DEFAULT 0,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_by INTEGER NOT NULL,
  updated_by INTEGER,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (created_by) REFERENCES users(id),
  FOREIGN KEY (updated_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  type TEXT NOT NULL CHECK (
    type IN (
      'TODAY_SCRIM',
      'NEW_TEAM',
      'TEAM_DISBANDED',
      'SCRIM_RESERVED',
      'JOIN_REQUEST',
      'JOIN_APPROVED',
      'JOIN_REJECTED'
    )
  ),
  title TEXT NOT NULL,
  content TEXT,
  is_read INTEGER NOT NULL DEFAULT 0,
  read_at TEXT,
  related_team_id INTEGER,
  related_schedule_id INTEGER,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id),
  FOREIGN KEY (related_team_id) REFERENCES teams(id),
  FOREIGN KEY (related_schedule_id) REFERENCES scrim_schedules(id)
);

CREATE TABLE IF NOT EXISTS admin_action_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  admin_user_id INTEGER NOT NULL,
  action_type TEXT NOT NULL,
  target_type TEXT,
  target_id INTEGER,
  description TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (admin_user_id) REFERENCES users(id)
);
"""


def postgres_schema_sql() -> str:
    return SCHEMA_SQL.replace("PRAGMA foreign_keys = ON;", "").replace(
        "INTEGER PRIMARY KEY AUTOINCREMENT",
        "INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY",
    )


class PostgresConnection:
    dialect = "postgres"

    def __init__(self, url: str):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "SCRIM_DATABASE_URL을 사용하려면 psycopg 패키지가 필요합니다."
            ) from exc
        self.connection = psycopg.connect(url, row_factory=dict_row)

    def execute(self, sql: str, params: tuple = ()):
        return self.connection.execute(sql.replace("?", "%s"), params)

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            statement = statement.strip()
            if not statement:
                continue
            self.execute(statement)

    def commit(self) -> None:
        self.connection.commit()

    def rollback(self) -> None:
        self.connection.rollback()

    def close(self) -> None:
        self.connection.close()


def db_path() -> Path:
    return Path(os.getenv("SCRIM_DB_FILE", DEFAULT_DB_PATH))


def configured_backend() -> str:
    return "postgres" if os.getenv("SCRIM_DATABASE_URL") else "sqlite"


def configured_database_label() -> str:
    if configured_backend() == "postgres":
        return "SCRIM_DATABASE_URL"
    return str(db_path())


@contextmanager
def connect(path: str | Path | None = None) -> Iterator:
    if path is None and os.getenv("SCRIM_DATABASE_URL"):
        connection = PostgresConnection(os.environ["SCRIM_DATABASE_URL"])
    else:
        resolved = Path(path) if path is not None else db_path()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(resolved)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db(path: str | Path | None = None) -> None:
    with connect(path) as connection:
        if db_dialect(connection) == "postgres":
            connection.execute("SELECT pg_advisory_lock(hashtext('lol_scrim_schema'))")
        try:
            connection.executescript(schema_sql(connection))
            if db_dialect(connection) == "sqlite":
                migrate_db(connection)
            else:
                migrate_postgres_db(connection)
            seed_admins(connection)
        finally:
            if db_dialect(connection) == "postgres":
                connection.execute("SELECT pg_advisory_unlock(hashtext('lol_scrim_schema'))")


def db_dialect(connection) -> str:
    return getattr(connection, "dialect", "sqlite")


def schema_sql(connection) -> str:
    if db_dialect(connection) == "postgres":
        return postgres_schema_sql()
    return SCHEMA_SQL


def insert_and_get_id(connection, sql: str, params: tuple) -> int:
    if db_dialect(connection) == "postgres":
        row = connection.execute(f"{sql} RETURNING id", params).fetchone()
        return row["id"]
    cursor = connection.execute(sql, params)
    return cursor.lastrowid


def migrate_db(connection) -> None:
    user_columns = connection.execute("PRAGMA table_info(users)").fetchall()
    columns = {row["name"] for row in user_columns}
    if "riot_id" not in columns:
        connection.execute("ALTER TABLE users ADD COLUMN riot_id TEXT")
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_riot_id
            ON users(riot_id)
            WHERE riot_id IS NOT NULL
            """
        )
    if "approved" not in columns:
        connection.execute("ALTER TABLE users ADD COLUMN approved INTEGER NOT NULL DEFAULT 0")
        connection.execute("UPDATE users SET approved = 1 WHERE role = 'ADMIN'")
    if "secondary_riot_id" not in columns:
        connection.execute("ALTER TABLE users ADD COLUMN secondary_riot_id TEXT")
    email_column = next((row for row in user_columns if row["name"] == "email"), None)
    if email_column is not None and email_column["notnull"]:
        rebuild_users_without_required_email(connection)


def migrate_postgres_db(connection) -> None:
    connection.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS approved INTEGER NOT NULL DEFAULT 0"
    )
    connection.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS secondary_riot_id TEXT")
    connection.execute("UPDATE users SET approved = 1 WHERE role = 'ADMIN'")


def rebuild_users_without_required_email(connection) -> None:
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute(
        """
        CREATE TABLE users_new (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          riot_id TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          secondary_riot_id TEXT,
          name TEXT NOT NULL,
          nickname TEXT,
          phone TEXT,
          role TEXT NOT NULL DEFAULT 'USER'
            CHECK (role IN ('USER', 'ADMIN')),
          approved INTEGER NOT NULL DEFAULT 0,
          is_active INTEGER NOT NULL DEFAULT 1,
          last_login_at TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        INSERT INTO users_new (
          id,
          riot_id,
          password_hash,
          secondary_riot_id,
          name,
          nickname,
          phone,
          role,
          approved,
          is_active,
          last_login_at,
          created_at,
          updated_at
        )
        SELECT
          id,
          COALESCE(NULLIF(riot_id, ''), email, 'user-' || id || '#LOCAL'),
          password_hash,
          NULL,
          name,
          nickname,
          phone,
          role,
          CASE WHEN role = 'ADMIN' THEN 1 ELSE 0 END,
          is_active,
          last_login_at,
          created_at,
          updated_at
        FROM users
        """
    )
    connection.execute("DROP TABLE users")
    connection.execute("ALTER TABLE users_new RENAME TO users")
    connection.execute("PRAGMA foreign_keys = ON")


def seed_admins(connection: sqlite3.Connection) -> None:
    admins = [
        ("\uc7a5\uc6d0\ud601", "\uc7a5\uc6d0\ud601#ADMIN"),
        ("\uc11c\uc138\uc9c4", "\uc11c\uc138\uc9c4#ADMIN"),
    ]
    admin_password_hash = hash_password(os.getenv("SCRIM_ADMIN_PASSWORD", "1234"))
    for name, riot_id in admins:
        if db_dialect(connection) == "postgres":
            connection.execute(
                """
                INSERT INTO users (riot_id, password_hash, name, role, approved)
                VALUES (?, ?, ?, 'ADMIN', 1)
                ON CONFLICT (riot_id) DO NOTHING
                """,
                (riot_id, admin_password_hash, name),
            )
        else:
            connection.execute(
                """
                INSERT OR IGNORE INTO users (riot_id, password_hash, name, role, approved)
                VALUES (?, ?, ?, 'ADMIN', 1)
                """,
                (riot_id, admin_password_hash, name),
            )
        connection.execute(
            """
            UPDATE users
            SET password_hash = ?,
                approved = 1
            WHERE riot_id = ? AND (password_hash = 'CHANGE_ME_HASH' OR approved = 0)
            """,
            (admin_password_hash, riot_id),
        )


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def create_user(
    connection,
    *,
    name: str,
    riot_id: str,
    password: str,
    secondary_riot_id: str | None = None,
    nickname: str | None = None,
    phone: str | None = None,
    role: str = "USER",
    approved: bool = False,
) -> dict:
    user_id = insert_and_get_id(
        connection,
        """
        INSERT INTO users (
          riot_id,
          secondary_riot_id,
          password_hash,
          name,
          nickname,
          phone,
          role,
          approved
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            riot_id.strip(),
            clean_optional_text(secondary_riot_id),
            hash_password(password),
            name.strip(),
            clean_optional_text(nickname),
            clean_optional_text(phone),
            role,
            1 if approved else 0,
        ),
    )
    return get_user(connection, user_id)


def clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    iterations = 210_000
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    ).hex()
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored_hash.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        int(iterations),
    ).hex()
    return hmac.compare_digest(candidate, expected)


def get_user(connection, user_id: int) -> dict:
    row = connection.execute(
        "SELECT * FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        raise ValueError("사용자를 찾을 수 없습니다.")
    return dict(row)


def get_user_by_riot_id(connection, riot_id: str) -> dict | None:
    row = connection.execute(
        """
        SELECT *
        FROM users
        WHERE riot_id = ? AND is_active = 1
        """,
        (riot_id,),
    ).fetchone()
    return row_to_dict(row)


def touch_last_login(connection, user_id: int) -> None:
    connection.execute(
        """
        UPDATE users
        SET last_login_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (user_id,),
    )


def search_users(connection, query: str = "") -> list[dict]:
    normalized = f"%{query.strip()}%"
    if db_dialect(connection) == "postgres":
        rows = connection.execute(
            """
            SELECT *
            FROM users
            WHERE is_active = 1
              AND (? = '%%' OR name ILIKE ? OR riot_id ILIKE ? OR secondary_riot_id ILIKE ?)
            ORDER BY (role = 'ADMIN') DESC, name ASC, riot_id ASC
            LIMIT 500
            """,
            (normalized, normalized, normalized, normalized),
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT *
            FROM users
            WHERE is_active = 1
              AND (? = '%%' OR name LIKE ? OR riot_id LIKE ? OR secondary_riot_id LIKE ?)
            ORDER BY role = 'ADMIN' DESC, name ASC, riot_id ASC
            LIMIT 500
            """,
            (normalized, normalized, normalized, normalized),
        ).fetchall()
    return [dict(row) for row in rows]


def update_user_profile(
    connection,
    *,
    user_id: int,
    riot_id: str,
    secondary_riot_id: str | None = None,
    nickname: str | None = None,
    password: str | None = None,
) -> dict:
    get_user(connection, user_id)
    if password:
        connection.execute(
            """
            UPDATE users
            SET riot_id = ?,
                secondary_riot_id = ?,
                nickname = ?,
                password_hash = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                riot_id.strip(),
                clean_optional_text(secondary_riot_id),
                clean_optional_text(nickname),
                hash_password(password),
                user_id,
            ),
        )
    else:
        connection.execute(
            """
            UPDATE users
            SET riot_id = ?,
                secondary_riot_id = ?,
                nickname = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                riot_id.strip(),
                clean_optional_text(secondary_riot_id),
                clean_optional_text(nickname),
                user_id,
            ),
        )
    return get_user(connection, user_id)


def reset_user_password(
    connection,
    *,
    user_id: int,
    new_password: str,
) -> dict:
    get_user(connection, user_id)
    connection.execute(
        """
        UPDATE users
        SET password_hash = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (hash_password(new_password), user_id),
    )
    return get_user(connection, user_id)


ROSTER_FIELDS = {
    "name",
    "participation_status_text",
    "absence_reason",
    "payment_status",
    "riot_id",
    "secondary_riot_id",
    "tier",
    "top_adjustment",
    "game_count_adjustment",
    "preferred_lines",
    "score_top",
    "score_jungle",
    "score_mid",
    "score_adc",
    "score_support",
    "notes",
}


def normalize_roster_row(row: dict) -> dict:
    normalized = dict(row)
    normalized["has_riot_id"] = bool(clean_optional_text(normalized.get("riot_id")))
    normalized["account_issued"] = normalized.get("account_status") == "ISSUED"
    return normalized


def get_roster_entry(connection, roster_id: int) -> dict:
    row = connection.execute(
        "SELECT * FROM roster_entries WHERE id = ?",
        (roster_id,),
    ).fetchone()
    if row is None:
        raise ValueError("명단을 찾을 수 없습니다.")
    return normalize_roster_row(dict(row))


def get_roster_entry_by_source_row(connection, source_row: int) -> dict | None:
    row = connection.execute(
        "SELECT * FROM roster_entries WHERE source_row = ?",
        (source_row,),
    ).fetchone()
    return normalize_roster_row(dict(row)) if row is not None else None


def list_roster_entries(
    connection,
    *,
    query: str = "",
    has_riot_id: bool | None = None,
    user_ids: set[int] | None = None,
    limit: int = 500,
) -> list[dict]:
    clauses = []
    params: list = []
    normalized_query = clean_optional_text(query)
    if normalized_query:
        pattern = f"%{normalized_query}%"
        operator = "ILIKE" if db_dialect(connection) == "postgres" else "LIKE"
        clauses.append(
            f"(name {operator} ? OR riot_id {operator} ? OR secondary_riot_id {operator} ? OR preferred_lines {operator} ?)"
        )
        params.extend([pattern, pattern, pattern, pattern])
    if has_riot_id is True:
        clauses.append("riot_id IS NOT NULL AND riot_id <> ''")
    elif has_riot_id is False:
        clauses.append("(riot_id IS NULL OR riot_id = '')")
    if user_ids is not None:
        if not user_ids:
            return []
        placeholders = ", ".join("?" for _ in user_ids)
        clauses.append(f"user_id IN ({placeholders})")
        params.extend(sorted(user_ids))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = connection.execute(
        f"""
        SELECT *
        FROM roster_entries
        {where}
        ORDER BY source_row ASC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    return [normalize_roster_row(dict(row)) for row in rows]


def roster_counts(connection) -> dict:
    row = connection.execute(
        """
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN riot_id IS NOT NULL AND riot_id <> '' THEN 1 ELSE 0 END) AS with_riot_id,
          SUM(CASE WHEN riot_id IS NULL OR riot_id = '' THEN 1 ELSE 0 END) AS without_riot_id,
          SUM(CASE WHEN account_status = 'ISSUED' THEN 1 ELSE 0 END) AS account_issued
        FROM roster_entries
        """
    ).fetchone()
    return {
        "total": int(row["total"] or 0),
        "with_riot_id": int(row["with_riot_id"] or 0),
        "without_riot_id": int(row["without_riot_id"] or 0),
        "account_issued": int(row["account_issued"] or 0),
    }


def upsert_roster_entry(connection, *, source_row: int, **fields) -> dict:
    normalized = {
        field: clean_optional_text(fields.get(field))
        for field in ROSTER_FIELDS
        if field in fields
    }
    if not normalized.get("name"):
        raise ValueError("명단 이름은 필수입니다.")
    existing = get_roster_entry_by_source_row(connection, source_row)
    if existing is None:
        columns = ["source_row", *normalized.keys()]
        values = [source_row, *normalized.values()]
        placeholders = ", ".join("?" for _ in columns)
        insert_and_get_id(
            connection,
            f"""
            INSERT INTO roster_entries ({", ".join(columns)})
            VALUES ({placeholders})
            """,
            tuple(values),
        )
    else:
        assignments = ", ".join(f"{field} = ?" for field in normalized)
        connection.execute(
            f"""
            UPDATE roster_entries
            SET {assignments},
                updated_at = CURRENT_TIMESTAMP
            WHERE source_row = ?
            """,
            (*normalized.values(), source_row),
        )
    entry = get_roster_entry_by_source_row(connection, source_row)
    if entry and entry.get("riot_id"):
        return issue_roster_account(connection, entry["id"])
    return entry


def issue_roster_account(connection, roster_id: int, password: str = "1234") -> dict:
    entry = get_roster_entry(connection, roster_id)
    riot_id = clean_optional_text(entry.get("riot_id"))
    if not riot_id:
        connection.execute(
            """
            UPDATE roster_entries
            SET user_id = NULL,
                account_status = 'NOT_ELIGIBLE',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (roster_id,),
        )
        return get_roster_entry(connection, roster_id)
    user = get_user_by_riot_id(connection, riot_id)
    if user is None:
        user = create_user(
            connection,
            name=entry["name"],
            riot_id=riot_id,
            secondary_riot_id=entry.get("secondary_riot_id"),
            password=password,
            approved=True,
        )
    else:
        connection.execute(
            """
            UPDATE users
            SET name = ?,
                secondary_riot_id = ?,
                approved = 1,
                is_active = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (entry["name"], clean_optional_text(entry.get("secondary_riot_id")), user["id"]),
        )
        user = get_user(connection, user["id"])
    connection.execute(
        """
        UPDATE roster_entries
        SET user_id = ?,
            account_status = 'ISSUED',
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (user["id"], roster_id),
    )
    return get_roster_entry(connection, roster_id)


def update_roster_entry(connection, roster_id: int, fields: dict) -> dict:
    allowed = {key: clean_optional_text(value) for key, value in fields.items() if key in ROSTER_FIELDS}
    if not allowed:
        return get_roster_entry(connection, roster_id)
    if "name" in allowed and not allowed["name"]:
        raise ValueError("명단 이름은 필수입니다.")
    assignments = ", ".join(f"{field} = ?" for field in allowed)
    connection.execute(
        f"""
        UPDATE roster_entries
        SET {assignments},
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (*allowed.values(), roster_id),
    )
    return issue_roster_account(connection, roster_id)


def set_user_approval(
    connection,
    *,
    user_id: int,
    approved: bool,
) -> dict:
    user = get_user(connection, user_id)
    if user["role"] == "ADMIN" and not approved:
        raise ValueError("관리자 승인은 해제할 수 없습니다.")
    connection.execute(
        """
        UPDATE users
        SET approved = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (1 if approved else 0, user_id),
    )
    return get_user(connection, user_id)


def user_can_schedule(
    connection,
    *,
    user_id: int,
    team_id: int,
) -> bool:
    user = get_user(connection, user_id)
    if user["role"] == "ADMIN":
        return True
    row = connection.execute(
        """
        SELECT 1
        FROM team_members
        WHERE user_id = ?
          AND team_id = ?
          AND role = 'LEADER'
          AND status = 'ACTIVE'
        """,
        (user_id, team_id),
    ).fetchone()
    return row is not None


def create_team(
    connection: sqlite3.Connection,
    *,
    name: str,
    created_by: int,
    top_rank: str | None = None,
    game_count: int = 0,
) -> dict:
    active_team = connection.execute(
        """
        SELECT 1
        FROM team_members
        WHERE user_id = ? AND status = 'ACTIVE'
        """,
        (created_by,),
    ).fetchone()
    if active_team:
        raise ValueError("이미 활성 팀에 소속된 회원입니다.")

    invite_code = secrets.token_urlsafe(8)
    team_id = insert_and_get_id(
        connection,
        """
        INSERT INTO teams (name, invite_code, top_rank, game_count, created_by)
        VALUES (?, ?, ?, ?, ?)
        """,
        (name, invite_code, top_rank, game_count, created_by),
    )
    connection.execute(
        """
        INSERT INTO team_members (team_id, user_id, role)
        VALUES (?, ?, 'LEADER')
        """,
        (team_id, created_by),
    )
    create_notification(
        connection,
        type="NEW_TEAM",
        title="새로운 팀 등록",
        content=f"{name} 팀이 생성되었습니다.",
        related_team_id=team_id,
    )
    return get_team(connection, team_id)


def get_team(connection, team_id: int) -> dict:
    row = connection.execute(
        "SELECT * FROM teams WHERE id = ?",
        (team_id,),
    ).fetchone()
    if row is None:
        raise ValueError("팀을 찾을 수 없습니다.")
    team = dict(row)
    members = connection.execute(
        """
        SELECT tm.id, tm.role, tm.status, tm.joined_at, u.id AS user_id, u.name, u.riot_id
        FROM team_members tm
        JOIN users u ON u.id = tm.user_id
        WHERE tm.team_id = ?
        ORDER BY (tm.role = 'LEADER') DESC, u.name ASC
        """,
        (team_id,),
    ).fetchall()
    team["members"] = [dict(member) for member in members]
    return team


def list_teams(connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT t.*, COUNT(tm.id) AS active_member_count
        FROM teams t
        LEFT JOIN team_members tm
          ON tm.team_id = t.id AND tm.status = 'ACTIVE'
        GROUP BY t.id
        ORDER BY t.created_at DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def join_team_by_code(
    connection,
    *,
    invite_code: str,
    user_id: int,
) -> dict:
    active_team = connection.execute(
        """
        SELECT 1
        FROM team_members
        WHERE user_id = ? AND status = 'ACTIVE'
        """,
        (user_id,),
    ).fetchone()
    if active_team:
        raise ValueError("이미 활성 팀에 소속된 회원입니다.")

    team = connection.execute(
        """
        SELECT *
        FROM teams
        WHERE invite_code = ? AND status != 'DISBANDED'
        """,
        (invite_code,),
    ).fetchone()
    if team is None:
        raise ValueError("가입 가능한 팀을 찾을 수 없습니다.")

    connection.execute(
        """
        INSERT INTO team_members (team_id, user_id, role)
        VALUES (?, ?, 'MEMBER')
        """,
        (team["id"], user_id),
    )
    return get_team(connection, team["id"])


def create_scrim_schedule(
    connection: sqlite3.Connection,
    *,
    team_id: int,
    scheduled_date: str,
    start_time: str,
    end_time: str,
    created_by: int,
    opponent_team_name: str | None = None,
    memo: str | None = None,
) -> dict:
    overlap = connection.execute(
        """
        SELECT id
        FROM scrim_schedules
        WHERE team_id = ?
          AND scheduled_date = ?
          AND status = 'RESERVED'
          AND start_time < ?
          AND end_time > ?
        """,
        (team_id, scheduled_date, end_time, start_time),
    ).fetchone()
    if overlap:
        raise ValueError("같은 시간에 이미 예약된 스크림이 있습니다.")

    schedule_id = insert_and_get_id(
        connection,
        """
        INSERT INTO scrim_schedules (
          team_id,
          opponent_team_name,
          scheduled_date,
          start_time,
          end_time,
          memo,
          created_by
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            team_id,
            opponent_team_name,
            scheduled_date,
            start_time,
            end_time,
            memo,
            created_by,
        ),
    )
    create_notification(
        connection,
        type="SCRIM_RESERVED",
        title="스크림 예약",
        content=f"{scheduled_date} {start_time} 스크림이 예약되었습니다.",
        related_team_id=team_id,
        related_schedule_id=schedule_id,
    )
    return dict(
        connection.execute(
            "SELECT * FROM scrim_schedules WHERE id = ?",
            (schedule_id,),
        ).fetchone()
    )


def create_notification(
    connection,
    *,
    type: str,
    title: str,
    content: str | None = None,
    user_id: int | None = None,
    related_team_id: int | None = None,
    related_schedule_id: int | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO notifications (
          user_id,
          type,
          title,
          content,
          related_team_id,
          related_schedule_id
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            type,
            title,
            content,
            related_team_id,
            related_schedule_id,
        ),
    )

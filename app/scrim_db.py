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
  password_hash TEXT NOT NULL,
  name TEXT NOT NULL,
  nickname TEXT,
  phone TEXT,
  role TEXT NOT NULL DEFAULT 'USER'
    CHECK (role IN ('USER', 'ADMIN')),
  is_active INTEGER NOT NULL DEFAULT 1,
  last_login_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
        connection.executescript(schema_sql(connection))
        if db_dialect(connection) == "sqlite":
            migrate_db(connection)
        seed_admins(connection)


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
    email_column = next((row for row in user_columns if row["name"] == "email"), None)
    if email_column is not None and email_column["notnull"]:
        rebuild_users_without_required_email(connection)


def rebuild_users_without_required_email(connection) -> None:
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute(
        """
        CREATE TABLE users_new (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          riot_id TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          name TEXT NOT NULL,
          nickname TEXT,
          phone TEXT,
          role TEXT NOT NULL DEFAULT 'USER'
            CHECK (role IN ('USER', 'ADMIN')),
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
          name,
          nickname,
          phone,
          role,
          is_active,
          last_login_at,
          created_at,
          updated_at
        )
        SELECT
          id,
          COALESCE(NULLIF(riot_id, ''), email, 'user-' || id || '#LOCAL'),
          password_hash,
          name,
          nickname,
          phone,
          role,
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
                INSERT INTO users (riot_id, password_hash, name, role)
                VALUES (?, ?, ?, 'ADMIN')
                ON CONFLICT (riot_id) DO NOTHING
                """,
                (riot_id, admin_password_hash, name),
            )
        else:
            connection.execute(
                """
                INSERT OR IGNORE INTO users (riot_id, password_hash, name, role)
                VALUES (?, ?, ?, 'ADMIN')
                """,
                (riot_id, admin_password_hash, name),
            )
        connection.execute(
            """
            UPDATE users
            SET password_hash = ?
            WHERE riot_id = ? AND password_hash = 'CHANGE_ME_HASH'
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
    nickname: str | None = None,
    phone: str | None = None,
    role: str = "USER",
) -> dict:
    user_id = insert_and_get_id(
        connection,
        """
        INSERT INTO users (
          riot_id,
          password_hash,
          name,
          nickname,
          phone,
          role
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (riot_id, hash_password(password), name, nickname, phone, role),
    )
    return get_user(connection, user_id)


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
              AND (? = '%%' OR name ILIKE ? OR riot_id ILIKE ?)
            ORDER BY (role = 'ADMIN') DESC, name ASC, riot_id ASC
            LIMIT 50
            """,
            (normalized, normalized, normalized),
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT *
            FROM users
            WHERE is_active = 1
              AND (? = '%%' OR name LIKE ? OR riot_id LIKE ?)
            ORDER BY role = 'ADMIN' DESC, name ASC, riot_id ASC
            LIMIT 50
            """,
            (normalized, normalized, normalized),
        ).fetchall()
    return [dict(row) for row in rows]


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

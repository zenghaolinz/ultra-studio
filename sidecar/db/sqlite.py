import aiosqlite
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "agent.db")

_db: aiosqlite.Connection | None = None

PRAGMA_STATEMENTS = [
    "PRAGMA foreign_keys=ON",
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA cache_size=-64000",
    "PRAGMA busy_timeout=5000",
]

CREATE_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""",
    """CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '新对话',
    project_id TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
)""",
    """CREATE TABLE IF NOT EXISTS stm_entries (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    visible INTEGER DEFAULT 1,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
)""",
    """CREATE TABLE IF NOT EXISTS model_configs (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    api_key TEXT DEFAULT '',
    base_url TEXT DEFAULT '',
    is_default INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""",
    """CREATE TABLE IF NOT EXISTS embedding_configs (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    dimensions INTEGER NOT NULL DEFAULT 768,
    api_key TEXT DEFAULT '',
    base_url TEXT DEFAULT '',
    is_default INTEGER DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS persona (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    content TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""",
    """CREATE TABLE IF NOT EXISTS generation_tasks (
    id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running', 'success', 'error', 'cancelled')),
    prompt TEXT DEFAULT '',
    quality_mode TEXT DEFAULT '',
    input_paths TEXT DEFAULT '[]',
    output_paths TEXT DEFAULT '{}',
    error TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP DEFAULT NULL
)""",
    "CREATE INDEX IF NOT EXISTS idx_stm_conv ON stm_entries(conversation_id, created_at)",
]

POST_MIGRATION_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS idx_conversations_project ON conversations(project_id, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_generation_tasks_updated ON generation_tasks(updated_at)",
]

MIGRATIONS = [
    "ALTER TABLE conversations RENAME TO conversations_old",
    """CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '新对话',
    project_id TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
)""",
    "INSERT INTO conversations(id, title, created_at, updated_at) SELECT id, title, created_at, updated_at FROM conversations_old",
    "DROP TABLE conversations_old",
]

CLEANUP_STMTS = [
    "DROP TABLE IF EXISTS ltm_entries",
    "DROP TABLE IF EXISTS memory_branches",
]

MIGRATIONS_VISIBLE = [
    "ALTER TABLE stm_entries ADD COLUMN visible INTEGER DEFAULT 1",
]

MIGRATIONS_PROJECTS = [
    "ALTER TABLE conversations ADD COLUMN project_id TEXT DEFAULT NULL",
]


async def _run_statements(conn: aiosqlite.Connection, statements: list[str]):
    for stmt in statements:
        await conn.execute(stmt)


async def _migrate():
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row

    await _run_statements(conn, PRAGMA_STATEMENTS)
    await _run_statements(conn, CREATE_STATEMENTS)
    await conn.commit()

    cursor = await conn.execute("PRAGMA table_info(conversations)")
    cols = [row[1] async for row in cursor]

    if "branch_id" in cols:
        print("[db] Running migration: removing branch_id from conversations")
        await _run_statements(conn, MIGRATIONS)
        await conn.commit()
        print("[db] Migration complete")

    print("[db] Cleaning up old LTM tables")
    await _run_statements(conn, CLEANUP_STMTS)
    await conn.commit()
    print("[db] Cleanup complete")

    cursor = await conn.execute("PRAGMA table_info(stm_entries)")
    cols = [row[1] async for row in cursor]
    if "visible" not in cols:
        print("[db] Running migration: adding visible column to stm_entries")
        await _run_statements(conn, MIGRATIONS_VISIBLE)
        await conn.commit()
        print("[db] visible migration complete")

    cursor = await conn.execute("PRAGMA table_info(conversations)")
    cols = [row[1] async for row in cursor]
    if "project_id" not in cols:
        print("[db] Running migration: adding project_id to conversations")
        await _run_statements(conn, MIGRATIONS_PROJECTS)
        await conn.commit()
        print("[db] project_id migration complete")

    await _run_statements(conn, POST_MIGRATION_STATEMENTS)
    await conn.commit()
    await conn.close()


async def init_db():
    global _db
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    await _migrate()

    _db = await aiosqlite.connect(DB_PATH)
    _db.row_factory = aiosqlite.Row

    await _run_statements(_db, PRAGMA_STATEMENTS)
    await _run_statements(_db, CREATE_STATEMENTS)
    await _run_statements(_db, POST_MIGRATION_STATEMENTS)
    await _db.commit()


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        await init_db()
    assert _db is not None
    return _db


async def close_db():
    global _db
    if _db:
        await _db.close()
        _db = None

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
    status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'success', 'error', 'cancelled')),
    conversation_id TEXT DEFAULT NULL,
    queue_position INTEGER DEFAULT NULL,
    prompt TEXT DEFAULT '',
    quality_mode TEXT DEFAULT '',
    input_paths TEXT DEFAULT '[]',
    output_paths TEXT DEFAULT '{}',
    error TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP DEFAULT NULL
)""",
    """CREATE TABLE IF NOT EXISTS message_tool_events (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    label TEXT NOT NULL,
    detail TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    position INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (message_id) REFERENCES stm_entries(id) ON DELETE CASCADE,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
)""",
    "CREATE INDEX IF NOT EXISTS idx_stm_conv ON stm_entries(conversation_id, created_at)",
]

POST_MIGRATION_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS idx_conversations_project ON conversations(project_id, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_generation_tasks_updated ON generation_tasks(updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_generation_tasks_status ON generation_tasks(status, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_message_tool_events_message ON message_tool_events(message_id, position)",
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

MIGRATIONS_GENERATION_TASKS = [
    "ALTER TABLE generation_tasks ADD COLUMN conversation_id TEXT DEFAULT NULL",
    "ALTER TABLE generation_tasks ADD COLUMN queue_position INTEGER DEFAULT NULL",
]

MIGRATIONS_GENERATION_TASK_STATUS_CHECK = [
    "ALTER TABLE generation_tasks RENAME TO generation_tasks_old",
    """CREATE TABLE generation_tasks (
    id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'success', 'error', 'cancelled')),
    conversation_id TEXT DEFAULT NULL,
    queue_position INTEGER DEFAULT NULL,
    prompt TEXT DEFAULT '',
    quality_mode TEXT DEFAULT '',
    input_paths TEXT DEFAULT '[]',
    output_paths TEXT DEFAULT '{}',
    error TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP DEFAULT NULL
)""",
    """INSERT INTO generation_tasks
    (id, task_type, status, conversation_id, queue_position, prompt, quality_mode, input_paths, output_paths, error, created_at, updated_at, completed_at)
    SELECT id, task_type, status, conversation_id, queue_position, prompt, quality_mode, input_paths, output_paths, error, created_at, updated_at, completed_at
    FROM generation_tasks_old""",
    "DROP TABLE generation_tasks_old",
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

    try:
        await conn.execute("BEGIN")

        cursor = await conn.execute("PRAGMA table_info(conversations)")
        cols = [row[1] async for row in cursor]

        if "branch_id" in cols:
            print("[db] Running migration: removing branch_id from conversations")
            await _run_statements(conn, MIGRATIONS)
            print("[db] Migration complete")

        print("[db] Cleaning up old LTM tables")
        await _run_statements(conn, CLEANUP_STMTS)
        print("[db] Cleanup complete")

        cursor = await conn.execute("PRAGMA table_info(stm_entries)")
        cols = [row[1] async for row in cursor]
        if "visible" not in cols:
            print("[db] Running migration: adding visible column to stm_entries")
            await _run_statements(conn, MIGRATIONS_VISIBLE)
            print("[db] visible migration complete")

        cursor = await conn.execute("PRAGMA table_info(conversations)")
        cols = [row[1] async for row in cursor]
        if "project_id" not in cols:
            print("[db] Running migration: adding project_id to conversations")
            await _run_statements(conn, MIGRATIONS_PROJECTS)
            print("[db] project_id migration complete")

        cursor = await conn.execute("PRAGMA table_info(generation_tasks)")
        cols = [row[1] async for row in cursor]
        for stmt in MIGRATIONS_GENERATION_TASKS:
            column = stmt.split(" ADD COLUMN ", 1)[1].split(" ", 1)[0]
            if column not in cols:
                print(f"[db] Running migration: adding {column} to generation_tasks")
                await conn.execute(stmt)
        cursor = await conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'generation_tasks'"
        )
        row = await cursor.fetchone()
        table_sql = row[0] if row else ""
        if "queued" not in table_sql:
            print("[db] Running migration: widening generation_tasks status check")
            await _run_statements(conn, MIGRATIONS_GENERATION_TASK_STATUS_CHECK)

        await _run_statements(conn, POST_MIGRATION_STATEMENTS)
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise
    finally:
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

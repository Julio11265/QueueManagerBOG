import os
# Parche cooperativo para gevent (mejor convivencia con requests, sockets, etc.)
try:
    from gevent import monkey  # type: ignore
    monkey.patch_all()
except Exception:
    pass

from datetime import datetime

from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO, emit

from sqlalchemy import (
    create_engine, MetaData, Table, Column, String, Integer, ForeignKey, select, func, and_
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, ProgrammingError

# ----------------- DB CONFIG -----------------
def normalize_db_url(raw: str) -> str:
    """Acepta postgres://... y lo convierte a postgresql+psycopg2://..."""
    if raw.startswith("postgres://"):
        return raw.replace("postgres://", "postgresql+psycopg2://", 1)
    if raw.startswith("postgresql://"):
        return raw.replace("postgresql://", "postgresql+psycopg2://", 1)
    return raw

DB_FILE = "queue_manager.db"
DEFAULT_SQLITE_URL = f"sqlite:///{DB_FILE}"

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    DATABASE_URL = normalize_db_url(DATABASE_URL)
else:
    # Fallback: SQLite local (se pierde al redeploy en Render free)
    DATABASE_URL = DEFAULT_SQLITE_URL

engine: Engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)

metadata = MetaData()

agents = Table(
    "agents", metadata,
    Column("name", String, primary_key=True)
)

status = Table(
    "status", metadata,
    Column("agent_name", String, ForeignKey("agents.name"), primary_key=True),
    Column("backlog", Integer, nullable=False, default=0, server_default="0"),
    Column("active", Integer, nullable=False, default=0, server_default="0"),
    Column("priority", String, nullable=True),
)

assignment = Table(
    "assignment", metadata,
    Column("agent_name", String, ForeignKey("agents.name"), primary_key=True),
    Column("easy_to_handle", Integer, nullable=False, default=0, server_default="0"),
    Column("investigation", Integer, nullable=False, default=0, server_default="0"),
    Column("autoclose_tickets", Integer, nullable=False, default=0, server_default="0"),
)

DEFAULT_AGENTS = ["Victor", "Julio", "Felipe", "Cindy"]

def init_db() -> None:
    """Crea tablas y datos base si no existen (funciona en Postgres y SQLite)."""
    metadata.create_all(engine)
    with engine.begin() as conn:
        # ¿Hay agentes?
        cnt = conn.scalar(select(func.count()).select_from(agents))
        if cnt == 0:
            for name in DEFAULT_AGENTS:
                conn.execute(agents.insert().values(name=name))
                conn.execute(status.insert().values(agent_name=name, backlog=0, active=0, priority=None))
                conn.execute(assignment.insert().values(
                    agent_name=name, easy_to_handle=0, investigation=0, autoclose_tickets=0
                ))

def fetch_state():
    """Devuelve el estado completo."""
    try:
        with engine.begin() as conn:
            st = conn.execute(
                select(
                    agents.c.name,
                    status.c.backlog,
                    status.c.active,
                    func.coalesce(status.c.priority, "").label("priority")
                ).join(status, status.c.agent_name == agents.c.name).order_by(agents.c.name)
            ).mappings().all()

            asg = conn.execute(
                select(
                    agents.c.name,
                    assignment.c.easy_to_handle,
                    assignment.c.investigation,
                    assignment.c.autoclose_tickets
                ).join(assignment, assignment.c.agent_name == agents.c.name).order_by(agents.c.name)
            ).mappings().all()
        return {"status": [dict(r) for r in st], "assignment": [dict(r) for r in asg]}
    except (OperationalError, ProgrammingError):
        init_db()
        return fetch_state()

ALLOWED_STATUS_FIELDS = {"backlog", "active", "priority"}
ALLOWED_ASSIGN_FIELDS = {"easy_to_handle", "investigation", "autoclose_tickets"}
PRIORITY_VALUES = {"", "P1", "P2"}

# ----------------- APP -----------------
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="gevent")

# Garantiza que las tablas existan al iniciar con gunicorn
init_db()

# ----------------- ROUTES -----------------
@app.route("/")
def index():
    state = fetch_state()
    today = datetime.now().strftime("%Y-%m-%d")
    return render_template("index.html", state=state, today=today)

@app.route("/health")
def health():
    return jsonify({
        "ok": True,
        "time": datetime.utcnow().isoformat(),
        "db_url": DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else DATABASE_URL,
    })

# ----------------- SOCKET EVENTS -----------------
@socketio.on("connect")
def on_connect():
    emit("full_state", fetch_state())

@socketio.on("update_cell")
def on_update_cell(data):
    """
    data = {table: 'status'|'assignment', agent: str, field: str, value: any}
    """
    table = data.get("table")
    agent = (data.get("agent") or "").strip()
    field = data.get("field")
    value = data.get("value")

    if not agent:
        emit("error_msg", {"message": "Agent is required."}); return
    if table not in {"status", "assignment"}:
        emit("error_msg", {"message": "Invalid table"}); return
    if table == "status" and field not in ALLOWED_STATUS_FIELDS:
        emit("error_msg", {"message": "Invalid field"}); return
    if table == "assignment" and field not in ALLOWED_ASSIGN_FIELDS:
        emit("error_msg", {"message": "Invalid field"}); return

    with engine.begin() as conn:
        # Upsert básico: si no existe, lo creo
        if not conn.scalar(select(func.count()).select_from(agents).where(agents.c.name == agent)):
            conn.execute(agents.insert().values(name=agent))
        if not conn.scalar(select(func.count()).select_from(status).where(status.c.agent_name == agent)):
            conn.execute(status.insert().values(agent_name=agent, backlog=0, active=0, priority=None))
        if not conn.scalar(select(func.count()).select_from(assignment).where(assignment.c.agent_name == agent)):
            conn.execute(assignment.insert().values(
                agent_name=agent, easy_to_handle=0, investigation=0, autoclose_tickets=0
            ))

        if field == "priority":
            val = (value or "").upper()
            if val not in PRIORITY_VALUES:
                val = ""
            conn.execute(
                status.update().where(status.c.agent_name == agent).values(priority=val if val else None)
            )
        else:
            try:
                num = int(value)
            except Exception:
                num = 0
            if num < 0: num = 0
            if table == "status":
                conn.execute(status.update().where(status.c.agent_name == agent).values({field: num}))
            else:
                conn.execute(assignment.update().where(assignment.c.agent_name == agent).values({field: num}))

    # Broadcast a todos (multi-dispositivo)
    socketio.emit("cell_updated", {"agent": agent, "table": table, "field": field, "value": value}, broadcast=True)

@socketio.on("rename_agent")
def on_rename_agent(data):
    old = (data.get("old_name") or "").strip()
    new = (data.get("new_name") or "").strip()
    if not old or not new:
        emit("error_msg", {"message": "Agent name cannot be empty."}); return
    if old == new:
        return

    with engine.begin() as conn:
        if not conn.scalar(select(func.count()).select_from(agents).where(agents.c.name == old)):
            emit("error_msg", {"message": "Original agent not found."}); return
        if conn.scalar(select(func.count()).select_from(agents).where(agents.c.name == new)):
            emit("error_msg", {"message": "Target name already exists."}); return

        # Renombrar en cascada
        conn.execute(agents.update().where(agents.c.name == old).values(name=new))
        conn.execute(status.update().where(status.c.agent_name == old).values(agent_name=new))
        conn.execute(assignment.update().where(assignment.c.agent_name == old).values(agent_name=new))

    socketio.emit("agent_renamed", {"old_name": old, "new_name": new}, broadcast=True)

# Local run
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    socketio.run(app, host="0.0.0.0", port=port)

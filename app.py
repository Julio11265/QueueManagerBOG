import os
import sqlite3
from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO, emit
from datetime import datetime

# --------- Database helpers ---------
DB_PATH = os.environ.get("DB_PATH") or (
    "/data/queue_manager.db" if os.path.isdir("/data")
    else os.path.join(os.path.dirname(__file__), "queue_manager.db")
)

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Create tables if they don't exist and seed default agents."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS agents(
            name TEXT PRIMARY KEY
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS status(
            agent_name TEXT PRIMARY KEY,
            backlog INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 0,
            priority TEXT DEFAULT NULL,
            FOREIGN KEY(agent_name) REFERENCES agents(name)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS assignment(
            agent_name TEXT PRIMARY KEY,
            easy_to_handle INTEGER NOT NULL DEFAULT 0,
            investigation INTEGER NOT NULL DEFAULT 0,
            autoclose_tickets INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(agent_name) REFERENCES agents(name)
        )
    """)
    conn.commit()

    # Seed initial agents if empty
    cur.execute("SELECT COUNT(*) AS c FROM agents")
    if cur.fetchone()["c"] == 0:
        for a in ["Victor", "Julio", "Felipe", "Cindy"]:
            cur.execute("INSERT OR IGNORE INTO agents(name) VALUES(?)", (a,))
            cur.execute(
                "INSERT OR IGNORE INTO status(agent_name, backlog, active, priority) VALUES(?,?,?,?)",
                (a, 0, 0, None),
            )
            cur.execute(
                "INSERT OR IGNORE INTO assignment(agent_name, easy_to_handle, investigation, autoclose_tickets) VALUES(?,?,?,?)",
                (a, 0, 0, 0),
            )
        conn.commit()
    conn.close()

def fetch_state():
    """Return full state for both tables. If tables are missing, init and retry once."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT a.name, s.backlog, s.active, IFNULL(s.priority,'') AS priority
            FROM agents a
            JOIN status s ON a.name = s.agent_name
            ORDER BY a.name
            """
        )
        status_rows = [dict(row) for row in cur.fetchall()]
        cur.execute(
            """
            SELECT a.name, t.easy_to_handle, t.investigation, t.autoclose_tickets
            FROM agents a
            JOIN assignment t ON a.name = t.agent_name
            ORDER BY a.name
            """
        )
        assign_rows = [dict(row) for row in cur.fetchall()]
        conn.close()
        return {"status": status_rows, "assignment": assign_rows}
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            init_db()
            return fetch_state()
        raise

ALLOWED_STATUS_FIELDS = {"backlog", "active", "priority"}
ALLOWED_ASSIGN_FIELDS = {"easy_to_handle", "investigation", "autoclose_tickets"}
PRIORITY_VALUES = {"", "P1", "P2"}

# --------- App ---------
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")

# Use gevent; works on Render free tier with gevent worker
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="gevent")

# Ensure DB exists when app is imported (gunicorn workers)
init_db()

# --------- Routes ---------
@app.route("/health")
def health():
    return jsonify({"ok": True, "time": datetime.utcnow().isoformat(), "db_path": DB_PATH})

@app.route("/")
def index():
    state = fetch_state()
    today = datetime.now().strftime("%Y-%m-%d")
    return render_template("index.html", state=state, today=today)

# --------- Socket.IO events ---------
@socketio.on("connect")
def on_connect():
    emit("full_state", fetch_state())

@socketio.on("update_cell")
def on_update_cell(data):
    """
    data: {table: 'status'|'assignment', agent: str, field: str, value: any}
    - Numbers are clamped to >= 0
    - Priority only '', 'P1', 'P2'
    - Auto-creates agent rows if missing
    """
    table = data.get("table")
    agent = (data.get("agent") or "").strip()
    field = data.get("field")
    value = data.get("value")

    if not agent:
        emit("error_msg", {"message": "Agent is required."})
        return
    if table not in {"status", "assignment"}:
        emit("error_msg", {"message": "Invalid table"})
        return
    if table == "status" and field not in ALLOWED_STATUS_FIELDS:
        emit("error_msg", {"message": "Invalid field"})
        return
    if table == "assignment" and field not in ALLOWED_ASSIGN_FIELDS:
        emit("error_msg", {"message": "Invalid field"})
        return

    conn = get_db()
    cur = conn.cursor()

    # Ensure agent exists in all tables
    cur.execute("INSERT OR IGNORE INTO agents(name) VALUES(?)", (agent,))
    cur.execute("INSERT OR IGNORE INTO status(agent_name) VALUES(?)", (agent,))
    cur.execute("INSERT OR IGNORE INTO assignment(agent_name) VALUES(?)", (agent,))

    if field == "priority":
        val = (value or "").upper()
        if val not in PRIORITY_VALUES:
            val = ""
        cur.execute("UPDATE status SET priority = ? WHERE agent_name = ?", (val if val else None, agent))
    else:
        try:
            num = int(value)
        except Exception:
            num = 0
        if num < 0:
            num = 0
        table_name = "status" if table == "status" else "assignment"
        cur.execute(f"UPDATE {table_name} SET {field} = ? WHERE agent_name = ?", (num, agent))

    conn.commit()
    conn.close()

    # Explicit broadcast so all devices update in real time
    socketio.emit("cell_updated", {"agent": agent, "table": table, "field": field, "value": value}, broadcast=True)

@socketio.on("rename_agent")
def on_rename_agent(data):
    """Rename an agent across agents/status/assignment."""
    old = (data.get("old_name") or "").strip()
    new = (data.get("new_name") or "").strip()

    if not old or not new:
        emit("error_msg", {"message": "Agent name cannot be empty."})
        return
    if old == new:
        return

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM agents WHERE name=?", (old,))
    if not cur.fetchone():
        conn.close()
        emit("error_msg", {"message": "Original agent not found."})
        return
    cur.execute("SELECT 1 FROM agents WHERE name=?", (new,))
    if cur.fetchone():
        conn.close()
        emit("error_msg", {"message": "Target name already exists."})
        return

    try:
        cur.execute("BEGIN")
        cur.execute("UPDATE agents SET name=? WHERE name=?", (new, old))
        cur.execute("UPDATE status SET agent_name=? WHERE agent_name=?", (new, old))
        cur.execute("UPDATE assignment SET agent_name=? WHERE agent_name=?", (new, old))
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        emit("error_msg", {"message": "Rename failed."})
        return

    conn.close()
    socketio.emit("agent_renamed", {"old_name": old, "new_name": new}, broadcast=True)

# --------- Local run ---------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    socketio.run(app, host="0.0.0.0", port=port)

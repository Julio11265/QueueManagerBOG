import os
import sqlite3
from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO, emit
from datetime import datetime

DB_PATH = os.environ.get("DB_PATH") or ("/data/queue_manager.db" if os.path.isdir("/data") else os.path.join(os.path.dirname(__file__), "queue_manager.db"))

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    # Agents
    cur.execute("""CREATE TABLE IF NOT EXISTS agents(
        name TEXT PRIMARY KEY
    )""")
    # Current Status table
    cur.execute("""CREATE TABLE IF NOT EXISTS status(
        agent_name TEXT PRIMARY KEY,
        backlog INTEGER NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 0,
        priority TEXT DEFAULT NULL,
        FOREIGN KEY(agent_name) REFERENCES agents(name)
    )""")
    # Assignment table
    cur.execute("""CREATE TABLE IF NOT EXISTS assignment(
        agent_name TEXT PRIMARY KEY,
        easy_to_handle INTEGER NOT NULL DEFAULT 0,
        investigation INTEGER NOT NULL DEFAULT 0,
        autoclose_tickets INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(agent_name) REFERENCES agents(name)
    )""")
    conn.commit()

    # Seed default agents if empty
    cur.execute("SELECT COUNT(*) as c FROM agents")
    if cur.fetchone()["c"] == 0:
        default_agents = ["Victor", "Julio", "Felipe", "Cindy"]
        for a in default_agents:
            cur.execute("INSERT OR IGNORE INTO agents(name) VALUES(?)", (a,))
            cur.execute("INSERT OR IGNORE INTO status(agent_name, backlog, active, priority) VALUES(?,?,?,?)", (a, 0, 0, None))
            cur.execute("INSERT OR IGNORE INTO assignment(agent_name, easy_to_handle, investigation, autoclose_tickets) VALUES(?,?,?,?)", (a, 0, 0, 0))
        conn.commit()
    conn.close()

def fetch_state():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT a.name, s.backlog, s.active, IFNULL(s.priority,'') as priority FROM agents a JOIN status s ON a.name = s.agent_name ORDER BY a.name")
    status_rows = [dict(row) for row in cur.fetchall()]
    cur.execute("SELECT a.name, t.easy_to_handle, t.investigation, t.autoclose_tickets FROM agents a JOIN assignment t ON a.name = t.agent_name ORDER BY a.name")
    assign_rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return {"status": status_rows, "assignment": assign_rows}

ALLOWED_STATUS_FIELDS = {"backlog", "active", "priority"}
ALLOWED_ASSIGN_FIELDS = {"easy_to_handle", "investigation", "autoclose_tickets"}
PRIORITY_VALUES = {"", "P1", "P2"}

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")
socketio = SocketIO(app, cors_allowed_origins="*")

@app.route("/health")
def health():
    return jsonify({"ok": True, "time": datetime.utcnow().isoformat()})

@app.route("/")
def index():
    state = fetch_state()
    today = datetime.now().strftime("%Y-%m-%d")
    return render_template("index.html", state=state, today=today)

@socketio.on("connect")
def on_connect():
    emit("full_state", fetch_state())

@socketio.on("update_cell")
def on_update_cell(data):
    # data: {table, agent, field, value}
    table = data.get("table")
    agent = data.get("agent")
    field = data.get("field")
    value = data.get("value")

    # Validation
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
    # Ensure agent exists
    cur.execute("SELECT 1 FROM agents WHERE name = ?", (agent,))
    if not cur.fetchone():
        cur.execute("INSERT OR IGNORE INTO agents(name) VALUES(?)", (agent,))
        cur.execute("INSERT OR IGNORE INTO status(agent_name) VALUES(?)", (agent,))
        cur.execute("INSERT OR IGNORE INTO assignment(agent_name) VALUES(?)", (agent,))

    # Handle priority separately
    if field == "priority":
        # Normalize value: only '', 'P1', 'P2' allowed
        val = (value or "").upper()
        if val not in PRIORITY_VALUES:
            val = ""
        cur.execute("UPDATE status SET priority = ? WHERE agent_name = ?", (val if val != "" else None, agent))
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

    # Broadcast to everyone (including sender)
    socketio.emit("cell_updated", {"agent": agent, "table": table, "field": field, "value": value})

if __name__ == "__main__":
    init_db()
    # Render and local friendly port
    port = int(os.environ.get("PORT", "10000"))
    socketio.run(app, host="0.0.0.0", port=port)

# Queue Manager (Moneycorp BOG team)

A small real‑time dashboard with two editable tables, built with **Python (Flask + Flask‑SocketIO)** and **HTML/JS/CSS**.

- Live updates: edits instantly propagate to all connected browsers
- Persistence: stored in **SQLite** located at `/data/queue_manager.db` (Render persistent disk)
- Clean, readable UI with accessible inputs and row highlighting by priority
- All copy is in **English** (backend and frontend)

## Features

1. Two 4×4 tables:
   - **Current Status**: Backlog, Active, Priority (dropdown: None / P1 / P2)
   - **Assignment**: Easy to handle, Investigation, Autoclose tickets
2. Live collaboration via websockets (Socket.IO).
3. Priority coloring:
   - **P1** → red highlight
   - **P2** → yellow highlight
   - **None** → default row
4. Validation: numbers are never negative (clamped to `0`).
5. Default values: all zeros on first run.
6. Displays today’s date in the top‑right corner.
7. Initial agents: Victor, Julio, Felipe, Cindy. You can add more by inserting new rows in the DB or extending the UI.

## Tech Stack

- Python 3.11+
- Flask
- Flask‑SocketIO (eventlet worker in production)
- SQLite (file database)
- HTML + CSS + Vanilla JS

## Local Development

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
# open http://localhost:10000
```

## Deployment on Render

1. **Push** this repository to GitHub.
2. On **Render**, create a new **Web Service** from your repo.
3. Render will read `render.yaml`:
   - Installs dependencies
   - Starts with: `gunicorn --worker-class eventlet -w 1 app:app`
   - Attaches a **Persistent Disk** mounted at `/data` so your DB survives restarts
4. (Optional) Set `SECRET_KEY` and `DB_PATH` environment variables in Render.
   - If `DB_PATH` is not set, the app will default to `/data/queue_manager.db` when running on Render, or a local file inside the repo otherwise.

## Project Structure

```
queue-manager/
├─ app.py
├─ requirements.txt
├─ render.yaml
├─ templates/
│  └─ index.html
├─ static/
│  ├─ styles.css
│  └─ client.js
└─ README.md
```

## Notes

- If you change the list of agents, the app initializes rows for any new agent the first time it sees it.
- Render **free** plan can sleep; the persistent disk ensures your data persists across restarts.
- For production, you can upgrade the plan or tune workers as needed (`-w 1` is sufficient for Socket.IO with eventlet here).

---

Built for Moneycorp BOG team — Queue Manager.

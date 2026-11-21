# YiDesk — IT Helpdesk & Ticketing

> Naming: **Yi** from 驿站 (Yìzhàn, the ancient courier post where official documents were received, dispatched, and archived) + **Desk**. A digital post station connecting employees and IT — see the Chinese README for details.

English quick overview — the [Chinese README](README.md) is the complete, authoritative documentation.

A single-process, self-hosted helpdesk platform for internal IT / desktop-support teams. Employees raise tickets from DingTalk, Feishu (Lark), or WeCom (WeChat Work) — or by scanning a QR sticker — while the IT team triages, dispatches, and closes everything in a Vue 3 admin console. Designed for a pure intranet deployment: one Python process serves the API, IM long connections, background jobs, and the built frontend on a single port.

## Highlights

- **Single process, zero middleware** — FastAPI + SQLite (MySQL-ready): uvicorn carries the REST API, DingTalk Stream / Feishu WebSocket clients, APScheduler jobs, and static frontend hosting together (port `8300`).
- **Unified IM channel adapter** — inbound messages from all three platforms normalize into one `TicketDraft`; outbound cards share one interface. Long-connection modes need no public callback URL.
- **Four-level dispatch engine** — QR designated-code → keyword rules → category rules / duty roster → weighted scoring (completion rate, speed, satisfaction, SLA urgency), with sticky assignment and fallbacks at every level.
- **Full lifecycle** — ticket state machine with merge/cascade, SLA with business calendar, satisfaction ratings, audit trail on every action.
- **Extras** — QR asset tags (location / device / assignee / meeting-room codes), software catalog & license ledger, device inventory with probing, terminal compliance agent, meeting-room booking with inspection cycles, analytics dashboard, monthly PDF report, webhook & open read-only API.

## Quick start

```bash
# 1. Python 3.11+ (backend)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../config.example.yaml config.yaml   # then edit credentials
uvicorn app.main:app --host 0.0.0.0 --port 8300

# 2. Frontend (built once; the server serves ./dist)
cd ../frontend
npm install && npm run build
```

Open `http://<host>:8300`, sign in with `admin` / `admin123` (**change the password and `jwt_secret` immediately** — see the security notes in the Chinese README).

## Documentation

Deployment (systemd / Docker), the three-platform integration guide, permission matrix, dispatch-rule overview, backup & restore, and the full feature list are all in the [Chinese README](README.md) — it is the single source of truth for this project.

## License

Released under the [MIT License](LICENSE). Third-party dependencies keep their own licenses (FastAPI/SQLAlchemy/Element Plus/Vue — MIT; ECharts — Apache-2.0; fpdf2/ldap3 — LGPL-3.0); verify against each package's metadata before redistribution.

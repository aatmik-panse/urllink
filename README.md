# Expense Tracker

Record expenses and see totals by category over a date range. FastAPI backend, PostgreSQL (SQLite fallback for local dev), single-page HTML frontend.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

Open http://localhost:8000. API docs are at http://localhost:8000/docs.

To use Postgres instead of SQLite:

```bash
export DATABASE_URL="postgresql+psycopg://user:password@localhost:5432/expenses"
```

## Tests

```bash
pytest -q
```

## API

| Method | Path | Description |
|---|---|---|
| POST | `/api/expenses` | Create `{ "amount": "12.50", "category": "food", "spent_on": "2026-10-18", "note"?: "..." }` |
| GET | `/api/expenses` | List, optional `?start=&end=&category=` |
| DELETE | `/api/expenses/{id}` | Delete |
| GET | `/api/summary` | Total and per-category totals, optional `?start=&end=` |

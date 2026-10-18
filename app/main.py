import logging
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse, JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import config, models
from app.db import engine, get_db, init_schema, ping
from app.observability import (
    AMOUNT_RECORDED,
    DB_UP,
    OPERATIONS,
    RequestMiddleware,
    setup_logging,
    setup_tracing,
)
from app.schemas import CategoryTotal, ExpenseCreate, ExpenseOut, Summary

STATIC_DIR = Path(__file__).parent / "static"

setup_logging()
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_schema()
    log.info("startup complete", extra={"git_sha": config.GIT_SHA})
    yield
    log.info("shutting down")


app = FastAPI(title="Expense Tracker", version=config.APP_VERSION, lifespan=lifespan)
app.add_middleware(RequestMiddleware)
TRACING_ENABLED = setup_tracing(app, engine)


# ---------------------------------------------------------------- operational endpoints


@app.get("/healthz", include_in_schema=False)
def healthz():
    """Liveness: the process is up and serving. Deliberately does NOT check
    the database, so a database outage does not make Kubernetes restart
    every healthy app pod."""
    return {"status": "ok"}


@app.get("/readyz", include_in_schema=False)
def readyz():
    """Readiness: can this pod serve real requests right now? Requires the
    database, so pods that cannot reach it are removed from the Service."""
    try:
        ping()
    except Exception as exc:  # noqa: BLE001
        DB_UP.set(0)
        log.warning("readiness check failed", extra={"error": type(exc).__name__})
        return JSONResponse(status_code=503, content={"status": "unavailable", "database": "down"})
    DB_UP.set(1)
    return {"status": "ready", "database": "up"}


@app.get("/version")
def version():
    """Lets anyone confirm exactly which build is serving traffic."""
    return {
        "version": config.APP_VERSION,
        "git_sha": config.GIT_SHA,
        "build_date": config.BUILD_DATE,
        "tracing": TRACING_ENABLED,
    }


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ---------------------------------------------------------------- application


def _filtered(db: Session, start: date | None, end: date | None):
    q = db.query(models.Expense)
    if start:
        q = q.filter(models.Expense.spent_on >= start)
    if end:
        q = q.filter(models.Expense.spent_on <= end)
    return q


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/expenses", response_model=ExpenseOut, status_code=201)
def create_expense(payload: ExpenseCreate, db: Session = Depends(get_db)):
    expense = models.Expense(
        amount=payload.amount,
        category=payload.category.strip().lower(),
        note=payload.note.strip(),
        spent_on=payload.spent_on,
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    OPERATIONS.labels("create", "success").inc()
    AMOUNT_RECORDED.inc(float(expense.amount))
    return expense


@app.get("/api/expenses", response_model=list[ExpenseOut])
def list_expenses(
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    category: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = _filtered(db, start, end)
    if category:
        q = q.filter(models.Expense.category == category.lower())
    return q.order_by(models.Expense.spent_on.desc(), models.Expense.id.desc()).all()


@app.delete("/api/expenses/{expense_id}", status_code=204)
def delete_expense(expense_id: int, db: Session = Depends(get_db)):
    expense = db.get(models.Expense, expense_id)
    if expense is None:
        OPERATIONS.labels("delete", "not_found").inc()
        raise HTTPException(status_code=404, detail="Expense not found")
    db.delete(expense)
    db.commit()
    OPERATIONS.labels("delete", "success").inc()


@app.get("/api/summary", response_model=Summary)
def summary(
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Aggregate query (GROUP BY category): the slowest route as data grows,
    so it has its own latency panel on the dashboard."""
    q = _filtered(db, start, end).with_entities(
        models.Expense.category,
        func.sum(models.Expense.amount),
        func.count(models.Expense.id),
    )
    rows = q.group_by(models.Expense.category).order_by(func.sum(models.Expense.amount).desc()).all()
    by_category = [
        CategoryTotal(category=c, total=Decimal(t).quantize(Decimal("0.01")), count=n) for c, t, n in rows
    ]
    total = sum((c.total for c in by_category), Decimal("0.00"))
    OPERATIONS.labels("summary", "success").inc()
    return Summary(total=total, by_category=by_category)

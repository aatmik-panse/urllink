from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.db import Base, engine, get_db
from app.schemas import CategoryTotal, ExpenseCreate, ExpenseOut, Summary

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Expense Tracker", lifespan=lifespan)


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
        raise HTTPException(status_code=404, detail="Expense not found")
    db.delete(expense)
    db.commit()


@app.get("/api/summary", response_model=Summary)
def summary(
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
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
    return Summary(total=total, by_category=by_category)

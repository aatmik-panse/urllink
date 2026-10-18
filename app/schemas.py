from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ExpenseCreate(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    category: str = Field(min_length=1, max_length=50)
    note: str = Field(default="", max_length=200)
    spent_on: date


class ExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    amount: Decimal
    category: str
    note: str
    spent_on: date


class CategoryTotal(BaseModel):
    category: str
    total: Decimal
    count: int


class Summary(BaseModel):
    total: Decimal
    by_category: list[CategoryTotal]

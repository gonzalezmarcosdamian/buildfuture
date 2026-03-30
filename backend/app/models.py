from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import String, Numeric, Boolean, Date, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(String(100))
    asset_type: Mapped[str] = mapped_column(String(20))  # CEDEAR | BOND | FCI | LETRA | CRYPTO | CASH
    source: Mapped[str] = mapped_column(String(20))  # IOL | NEXO | BITSO | MANUAL
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    avg_purchase_price_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    current_price_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    annual_yield_pct: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=Decimal("0.08"))
    snapshot_date: Mapped[date] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    @property
    def current_value_usd(self) -> Decimal:
        return self.quantity * self.current_price_usd

    @property
    def performance_pct(self) -> Decimal:
        if self.avg_purchase_price_usd == 0:
            return Decimal("0")
        return (self.current_price_usd - self.avg_purchase_price_usd) / self.avg_purchase_price_usd


class BudgetConfig(Base):
    __tablename__ = "budget_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    effective_month: Mapped[date] = mapped_column(Date)
    income_monthly_ars: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    total_monthly_ars: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    fx_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    notes: Mapped[str] = mapped_column(Text, default="")
    categories: Mapped[list["BudgetCategory"]] = relationship(back_populates="budget", cascade="all, delete-orphan")

    @property
    def total_monthly_usd(self) -> Decimal:
        return self.total_monthly_ars / self.fx_rate

    @property
    def income_monthly_usd(self) -> Decimal:
        if self.fx_rate == 0:
            return Decimal("0")
        return self.income_monthly_ars / self.fx_rate

    @property
    def expenses_pct(self) -> Decimal:
        """% del ingreso que va a gastos (excl. vacaciones e inversión)."""
        return sum(
            c.percentage for c in self.categories
            if not c.is_vacation
        )

    @property
    def vacation_pct(self) -> Decimal:
        vac = next((c for c in self.categories if c.is_vacation), None)
        return vac.percentage if vac else Decimal("0")

    @property
    def savings_monthly_ars(self) -> Decimal:
        """Lo que queda para invertir = ingreso - gastos - vacaciones."""
        return self.income_monthly_ars * (
            1 - self.expenses_pct - self.vacation_pct
        )

    @property
    def savings_monthly_usd(self) -> Decimal:
        if self.fx_rate == 0:
            return Decimal("0")
        return self.savings_monthly_ars / self.fx_rate


class BudgetCategory(Base):
    __tablename__ = "budget_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey("budget_configs.id"))
    name: Mapped[str] = mapped_column(String(50))
    percentage: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    icon: Mapped[str] = mapped_column(String(10), default="💰")
    color: Mapped[str] = mapped_column(String(10), default="#3B82F6")
    is_vacation: Mapped[bool] = mapped_column(Boolean, default=False)
    budget: Mapped["BudgetConfig"] = relationship(back_populates="categories")

    @property
    def amount_ars(self) -> Decimal:
        return self.budget.income_monthly_ars * self.percentage

    @property
    def amount_usd(self) -> Decimal:
        return self.amount_ars / self.budget.fx_rate


class FreedomGoal(Base):
    __tablename__ = "freedom_goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    monthly_savings_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    target_annual_return_pct: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.08"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Integration(Base):
    __tablename__ = "integrations"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(20))  # IOL | NEXO | BITSO
    provider_type: Mapped[str] = mapped_column(String(10))  # ALYC | CRYPTO
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    is_connected: Mapped[bool] = mapped_column(Boolean, default=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    # credentials stored as encrypted JSON — empty until user connects
    encrypted_credentials: Mapped[str] = mapped_column(Text, default="")

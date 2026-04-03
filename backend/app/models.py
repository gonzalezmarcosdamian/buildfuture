from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import (
    String,
    Numeric,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    ticker: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(String(100))
    asset_type: Mapped[str] = mapped_column(
        String(20)
    )  # CEDEAR | BOND | FCI | LETRA | CRYPTO | CASH
    source: Mapped[str] = mapped_column(String(20))  # IOL | NEXO | BITSO | MANUAL
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    avg_purchase_price_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    current_price_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    annual_yield_pct: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), default=Decimal("0.08")
    )
    snapshot_date: Mapped[date] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Precio promedio de compra en ARS (directo de IOL, sin conversión)
    ppc_ars: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    # MEP/CCL al momento de la compra — para calcular costo base real en USD
    purchase_fx_rate: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0")
    )
    # ID externo para actualización automática de precios
    external_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, default=None
    )
    # Categoría FCI para ArgentinaDatos
    fci_categoria: Mapped[str | None] = mapped_column(
        String(30), nullable=True, default=None
    )
    # Valor en ARS directo de IOL (sin conversión) — evita error de MEP al mostrar ARS
    current_value_ars: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0")
    )

    @property
    def current_value_usd(self) -> Decimal:
        return self.quantity * self.current_price_usd

    @property
    def cost_basis_usd(self) -> Decimal:
        """Costo base real en USD usando el MEP al momento de compra."""
        if self.purchase_fx_rate and self.purchase_fx_rate > 0 and self.ppc_ars > 0:
            # LECAPs: IOL cotiza ppc per 100 nominales → dividir por 100 para obtener precio por nominal
            ppc_per_unit = (
                self.ppc_ars / Decimal("100")
                if self.asset_type == "LETRA"
                else self.ppc_ars
            )
            return self.quantity * ppc_per_unit / self.purchase_fx_rate
        return self.quantity * self.avg_purchase_price_usd

    @property
    def performance_pct(self) -> Decimal:
        """Rendimiento en USD usando costo base real."""
        cost = self.cost_basis_usd
        if cost == 0:
            return Decimal("0")
        return (self.current_value_usd - cost) / cost

    @property
    def performance_ars_pct(self) -> Decimal:
        """
        Rendimiento en ARS puro: precio_ars_actual vs VCP_ars.
        No depende del MEP histórico — siempre preciso para instrumentos ARS (FCI, LETRA).
        """
        if self.ppc_ars == 0 or self.quantity == 0:
            return Decimal("0")
        current_price_ars = self.current_value_ars / self.quantity
        return (current_price_ars - self.ppc_ars) / self.ppc_ars


class BudgetConfig(Base):
    __tablename__ = "budget_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    effective_month: Mapped[date] = mapped_column(Date)
    income_monthly_ars: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0")
    )
    total_monthly_ars: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    fx_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    notes: Mapped[str] = mapped_column(Text, default="")
    categories: Mapped[list["BudgetCategory"]] = relationship(
        back_populates="budget", cascade="all, delete-orphan"
    )

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
        return sum(c.percentage for c in self.categories if not c.is_vacation)

    @property
    def vacation_pct(self) -> Decimal:
        vac = next((c for c in self.categories if c.is_vacation), None)
        return vac.percentage if vac else Decimal("0")

    @property
    def savings_monthly_ars(self) -> Decimal:
        """Lo que queda para invertir = ingreso - gastos - vacaciones."""
        return self.income_monthly_ars * (1 - self.expenses_pct - self.vacation_pct)

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
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    monthly_savings_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    target_annual_return_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), default=Decimal("0.08")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CapitalGoal(Base):
    """Meta de capital: ahorro para un objetivo concreto (casa, auto, viaje, etc.)"""

    __tablename__ = "capital_goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(100))
    emoji: Mapped[str] = mapped_column(String(10), default="🎯")
    target_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    target_years: Mapped[int] = mapped_column(default=5)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PortfolioSnapshot(Base):
    """
    Snapshot diario del portafolio al cierre de mercado.
    Fuente de verdad para el historial de valor — no recuperable de IOL.
    """

    __tablename__ = "portfolio_snapshots"
    __table_args__ = (
        UniqueConstraint("user_id", "snapshot_date", name="uq_snapshot_user_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    snapshot_date: Mapped[date] = mapped_column(Date)
    total_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    monthly_return_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    positions_count: Mapped[int] = mapped_column(default=0)
    fx_mep: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    cost_basis_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0")
    )


class InvestmentMonth(Base):
    """
    Registro de meses en que el usuario realizó al menos una inversión.
    Fuente primaria: operaciones IOL. También se puede marcar manualmente.
    """

    __tablename__ = "investment_months"
    __table_args__ = (
        UniqueConstraint("user_id", "month", name="uq_investment_user_month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    month: Mapped[date] = mapped_column(Date)  # siempre el día 1 del mes
    amount_ars: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    source: Mapped[str] = mapped_column(String(20), default="IOL")  # IOL | MANUAL
    note: Mapped[str] = mapped_column(Text, default="")


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    risk_profile: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # conservative | moderate | aggressive


class IntegrationDiscovery(Base):
    """
    Instrumentos que el sync no pudo mapear a un asset_type conocido.
    Persiste el raw data de la API para iterar el mapper sin perder información.
    Provider-agnóstico: sirve para Cocos, IOL, PPI o cualquier ALYC futuro.
    """

    __tablename__ = "integration_discoveries"
    __table_args__ = (
        UniqueConstraint(
            "provider", "raw_instrument_type", "ticker", name="uq_discovery"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(20))  # COCOS | IOL | PPI
    raw_instrument_type: Mapped[str] = mapped_column(String(50))
    ticker: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200), default="")
    raw_data: Mapped[str] = mapped_column(Text, default="")  # JSON del item crudo
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    seen_count: Mapped[int] = mapped_column(default=1)
    user_id: Mapped[str] = mapped_column(String(36), index=True)


class IntegrationErrorLog(Base):
    """Historial de errores de integraciones para diagnóstico multi-usuario."""

    __tablename__ = "integration_error_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    provider: Mapped[str] = mapped_column(String(20), index=True)
    operation: Mapped[str] = mapped_column(String(30))  # connect | sync | refresh
    error_code: Mapped[str] = mapped_column(
        String(20), default=""
    )  # 400 | 401 | 502 | timeout
    error_message: Mapped[str] = mapped_column(Text, default="")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )


class Integration(Base):
    __tablename__ = "integrations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    provider: Mapped[str] = mapped_column(String(20))  # IOL | NEXO | BITSO
    provider_type: Mapped[str] = mapped_column(String(10))  # ALYC | CRYPTO
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    is_connected: Mapped[bool] = mapped_column(Boolean, default=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    # credentials stored as encrypted JSON — empty until user connects
    encrypted_credentials: Mapped[str] = mapped_column(Text, default="")


class PriceHistory(Base):
    """
    Caché compartido de precios históricos diarios por ticker.
    Fuente: Yahoo Finance. Compartido entre todos los usuarios —
    si GGAL ya fue descargado para un usuario, el siguiente lo lee de aquí.
    """

    __tablename__ = "price_history"
    __table_args__ = (
        UniqueConstraint("ticker", "price_date", name="uq_price_ticker_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    price_date: Mapped[date] = mapped_column(Date, index=True)
    price_usd: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    source: Mapped[str] = mapped_column(
        String(20), default="YAHOO"
    )  # YAHOO | IOL | MANUAL


class MepHistory(Base):
    """
    Caché compartido del tipo de cambio MEP histórico.
    Fuente: bluelytics.com.ar. Un solo registro por fecha, para todos los usuarios.
    """

    __tablename__ = "mep_history"
    __table_args__ = (UniqueConstraint("price_date", name="uq_mep_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    price_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    mep_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    source: Mapped[str] = mapped_column(String(20), default="BLUELYTICS")


class PositionSnapshot(Base):
    """
    Snapshot diario del valor de cada posición individual por usuario.
    Permite calcular Δ real por posición para cualquier período (día/mes/año),
    sincronizado con el gráfico de tenencia agregada.
    Se guarda una vez por posición por día — upsert en (user_id, ticker, snapshot_date).
    """

    __tablename__ = "position_snapshots"
    __table_args__ = (
        UniqueConstraint("user_id", "ticker", "snapshot_date", name="uq_pos_snapshot"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    value_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    price_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    asset_type: Mapped[str] = mapped_column(String(20), default="")
    source: Mapped[str] = mapped_column(String(20), default="")


class WaitlistEntry(Base):
    """
    Emails interesados en BuildFuture — registrados desde la landing pública.
    No requiere autenticación. Email único (upsert silencioso en caso de duplicado).
    """

    __tablename__ = "waitlist"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(50), default="landing")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

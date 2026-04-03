"""
PPI (Portfolio Personal Inversiones) API client.
Auth: Public Key + Private Key → Bearer token (JWT).
Docs: https://itatppi.github.io/ppi-official-api-docs/
Sandbox:    https://clientapi_sandbox.portfoliopersonal.com
Production: https://clientapi.portfoliopersonal.com
"""

import logging
import re
import httpx
from dataclasses import dataclass, field
from decimal import Decimal

logger = logging.getLogger("buildfuture.ppi")

PPI_BASE_PROD = "https://clientapi.portfoliopersonal.com"
PPI_BASE_SANDBOX = "https://clientapi_sandbox.portfoliopersonal.com"

DEFAULT_YIELDS: dict[str, Decimal] = {
    "cedear": Decimal("0.10"),
    "stock": Decimal("0.10"),
    "bond": Decimal("0.09"),
    "letra": Decimal("0.68"),
    "etf": Decimal("0.10"),
    "default": Decimal("0.08"),
}

# Bonos soberanos que cotizan en USD en el mercado BYMA
_USD_BOND_TICKERS: frozenset[str] = frozenset(
    {
        "AL29",
        "AL29D",
        "AL30",
        "AL30D",
        "AL35",
        "AL35D",
        "AL41",
        "AL41D",
        "GD29",
        "GD30",
        "GD35",
        "GD38",
        "GD41",
        "GD46",
        "AE38",
        "AE38D",
    }
)

# Patrón de LECAPs/LETEs: S31G6, S15Y6, S14N5, etc.
_LETRA_TICKER_RE = re.compile(r"^S\d{2}[A-Z]\d$")


@dataclass
class PPIPosition:
    ticker: str
    description: str
    asset_type: str  # CEDEAR | BOND | LETRA | STOCK | ETF | CAUCION
    quantity: Decimal
    current_price_usd: Decimal
    avg_price_usd: Decimal  # sobreescrito con cost-basis real desde operaciones
    annual_yield_pct: Decimal
    ppc_ars: Decimal = field(default_factory=lambda: Decimal("0"))
    current_value_ars: Decimal = field(default_factory=lambda: Decimal("0"))


class PPIAuthError(Exception):
    pass


_MOCK_PREFIX = "mock-"


def _mock_portfolio() -> list["PPIPosition"]:
    """Portafolio falso para testing visual sin credenciales reales."""
    mep = Decimal("1450")
    return [
        PPIPosition(
            ticker="QQQ",
            description="Invesco QQQ Trust (CEDEAR)",
            asset_type="CEDEAR",
            quantity=Decimal("25"),
            current_price_usd=Decimal("18.50"),
            avg_price_usd=Decimal("16.00"),
            annual_yield_pct=DEFAULT_YIELDS["cedear"],
            ppc_ars=Decimal("26825"),
            current_value_ars=Decimal("26825") * 25,
        ),
        PPIPosition(
            ticker="AL30",
            description="Bono Soberano AL30 USD",
            asset_type="BOND",
            quantity=Decimal("1000"),
            current_price_usd=Decimal("0.585"),
            avg_price_usd=Decimal("0.520"),
            annual_yield_pct=DEFAULT_YIELDS["bond"],
            ppc_ars=Decimal("0"),
            current_value_ars=Decimal("0"),
        ),
        PPIPosition(
            ticker="S31G6",
            description="LECAP S31G6",
            asset_type="LETRA",
            quantity=Decimal("500"),
            current_price_usd=Decimal("0.690"),
            avg_price_usd=Decimal("0.650"),
            annual_yield_pct=DEFAULT_YIELDS["letra"],
            ppc_ars=Decimal("1001"),
            current_value_ars=Decimal("1001") * 500,
        ),
    ]


def _mock_cash() -> dict[str, Decimal]:
    return {"ars": Decimal("35000"), "usd": Decimal("120")}


class PPIClient:
    def __init__(self, public_key: str, private_key: str, sandbox: bool = False):
        self.public_key = public_key
        self.private_key = private_key
        self._mock = public_key.startswith(_MOCK_PREFIX)
        self._base = PPI_BASE_SANDBOX if sandbox else PPI_BASE_PROD
        self._access_token: str | None = None
        self._refresh_token: str | None = None

    # ── Autenticación ──────────────────────────────────────────────────────────

    def authenticate(self) -> None:
        if self._mock:
            logger.info("PPI mock mode — skip auth")
            self._access_token = "mock-token"
            return
        logger.info("PPI auth — public_key: %s...", self.public_key[:8])
        try:
            resp = httpx.post(
                f"{self._base}/api/1.0/Account/LoginApi",
                headers={
                    "ApiKey": self.public_key,
                    "ApiSecret": self.private_key,
                    "AuthorizedClient": "API_CLI_PYTHON",
                    "ClientKey": "pp19PythonApp12",
                    "Content-Type": "application/json",
                },
                json={},
                timeout=20,
            )
        except httpx.ConnectError as e:
            raise PPIAuthError(f"No se pudo conectar con PPI: {e}")
        except httpx.TimeoutException:
            raise PPIAuthError("Timeout conectando con PPI")

        logger.info(
            "PPI auth response: status=%s body=%s", resp.status_code, resp.text[:300]
        )

        if resp.status_code in (400, 401):
            ppi_msg = resp.text[:300]
            raise PPIAuthError(
                f"Credenciales inválidas (PPI: {ppi_msg}). "
                "Verificá Clave Pública Y Clave Privada en PPI → Mi cuenta → Seguridad → API."
            )
        if resp.status_code != 200:
            raise PPIAuthError(f"PPI respondió {resp.status_code}: {resp.text[:300]}")

        try:
            data = resp.json()
        except Exception:
            raise PPIAuthError(f"Respuesta inesperada de PPI: {resp.text[:200]}")

        self._access_token = data.get("accessToken") or data.get("access_token")
        self._refresh_token = data.get("refreshToken") or data.get("refresh_token")

        if not self._access_token:
            raise PPIAuthError(f"PPI no devolvió accessToken. Respuesta: {data}")

        logger.info("PPI auth OK — token obtenido")

    def _headers(self) -> dict:
        if not self._access_token:
            self.authenticate()
        # PPI requiere los headers de API Key en TODOS los requests, no solo en el de auth.
        return {
            "Authorization": f"Bearer {self._access_token}",
            "ApiKey": self.public_key,
            "ApiSecret": self.private_key,
            "AuthorizedClient": "API_CLI_PYTHON",
            "ClientKey": "pp19PythonApp12",
            "Content-Type": "application/json",
        }

    def _refresh(self) -> None:
        logger.info("PPI refresh token")
        if not self._refresh_token:
            self.authenticate()
            return
        try:
            resp = httpx.post(
                f"{self._base}/api/1.0/Account/RefreshToken",
                json={"refreshToken": self._refresh_token},
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                self._access_token = data.get("accessToken", self._access_token)
                self._refresh_token = data.get("refreshToken", self._refresh_token)
            else:
                logger.warning(
                    "PPI refresh falló (%s) — re-autenticando", resp.status_code
                )
                self.authenticate()
        except Exception:
            self.authenticate()

    def _get(
        self, path: str, params: dict | None = None, retry: bool = True
    ) -> dict | list:
        url = f"{self._base}{path}"
        logger.debug("GET %s params=%s", url, params)
        resp = httpx.get(url, headers=self._headers(), params=params, timeout=20)
        logger.debug("GET %s → %s", url, resp.status_code)
        if resp.status_code == 401 and retry:
            logger.info("PPI token expirado, refrescando...")
            self._refresh()
            return self._get(path, params=params, retry=False)
        if resp.status_code != 200:
            logger.error("GET %s falló: %s %s", url, resp.status_code, resp.text[:300])
            raise Exception(f"PPI {resp.status_code} en {path}: {resp.text[:200]}")
        return resp.json()

    # ── Endpoints de cuenta ────────────────────────────────────────────────────

    def get_accounts(self) -> list[dict]:
        """Lista de cuentas disponibles del usuario."""
        if self._mock:
            return [
                {
                    "accountNumber": "99999999",
                    "name": "Cuenta Mock PPI",
                    "type": "INVERSION",
                }
            ]
        data = self._get("/api/1.0/Account/Accounts")
        if isinstance(data, list):
            return data
        return data.get("accounts", [])

    def get_portfolio(self, account_number: str) -> list[PPIPosition]:
        """
        Trae posiciones desde /Account/GetBalanceAndPositions.
        PPI devuelve groupedInstruments con tipos: CEDEARS, BONOS, ACCIONES, ETFs, etc.
        Futuros y Opciones se ignoran (no aportan al freedom score).
        En mock mode retorna datos hardcodeados sin llamar a PPI.
        """
        if self._mock:
            logger.info("PPI mock mode — returning fake portfolio")
            return _mock_portfolio()
        mep = self._get_mep()
        mep_dec = Decimal(str(mep))

        try:
            data = self._get(
                "/api/1.0/Account/BalancesAndPositions",
                params={"accountNumber": account_number},
            )
        except Exception as e:
            if "500" in str(e) and "Internal Error" in str(e):
                # PPI devuelve 500 "Internal Error" cuando la cuenta está vacía (sin posiciones).
                # Es un bug del lado de PPI — lo tratamos como portafolio vacío.
                logger.warning(
                    "PPI BalancesAndPositions 500 — cuenta posiblemente vacía, retornando []"
                )
                return []
            raise
        logger.info("PPI portafolio recibido | MEP=%.0f", mep)

        positions: list[PPIPosition] = []
        grouped = data.get("groupedInstruments", [])

        for group in grouped:
            group_name = str(group.get("name", "")).upper()

            # Derivados: no aplican al portafolio de libertad financiera
            if group_name in ("FUTUROS", "OPCIONES", "OPTIONS", "FUTURES"):
                continue

            for inst in group.get("instruments", []):
                ticker = str(inst.get("ticker", "")).strip().upper()
                if not ticker:
                    continue

                quantity = Decimal(str(inst.get("quantity", inst.get("cantidad", 0))))
                if quantity <= 0:
                    continue

                description = str(inst.get("name", inst.get("nombre", ticker)))
                price_raw = Decimal(str(inst.get("price", inst.get("precio", 0))))
                amount_raw = Decimal(str(inst.get("amount", inst.get("monto", 0))))

                asset_type = _normalize_asset_type(group_name, ticker)
                is_usd = _is_usd_instrument(ticker, group_name)

                if is_usd:
                    price_per_unit = (
                        price_raw
                        if price_raw > 0
                        else (amount_raw / quantity if quantity > 0 else Decimal("0"))
                    )
                    current_price_usd = price_per_unit
                    current_value_ars = current_price_usd * mep_dec
                    ppc_ars = Decimal("0")
                else:
                    # Precio en ARS → dividir por MEP
                    price_ars = (
                        price_raw
                        if price_raw > 0
                        else (amount_raw / quantity if quantity > 0 else Decimal("0"))
                    )
                    current_price_usd = (
                        price_ars / mep_dec if mep_dec > 0 else Decimal("0")
                    )
                    current_value_ars = (
                        amount_raw if amount_raw > 0 else price_ars * quantity
                    )
                    ppc_ars = price_ars  # precio crudo en ARS para cost-basis

                yield_key = (
                    asset_type.lower()
                    if asset_type.lower() in DEFAULT_YIELDS
                    else "default"
                )
                annual_yield = DEFAULT_YIELDS[yield_key]

                logger.info(
                    "  PPI %s (%s) cant=%.4f USD=%.4f yield=%.0f%%",
                    ticker,
                    asset_type,
                    float(quantity),
                    float(current_price_usd),
                    float(annual_yield) * 100,
                )

                positions.append(
                    PPIPosition(
                        ticker=ticker,
                        description=description,
                        asset_type=asset_type,
                        quantity=quantity,
                        current_price_usd=current_price_usd,
                        avg_price_usd=current_price_usd,  # placeholder — se reemplaza con MEP compra
                        annual_yield_pct=annual_yield,
                        ppc_ars=ppc_ars,
                        current_value_ars=current_value_ars,
                    )
                )

        return positions

    def get_cash_balance(self, account_number: str) -> dict[str, Decimal]:
        """
        Saldo disponible en ARS y USD.
        PPI: groupedAvailability[].availability[].{name, amount}
        """
        if self._mock:
            return _mock_cash()
        try:
            data = self._get(
                "/api/1.0/Account/AvailableBalance",
                params={"accountNumber": account_number},
            )
        except Exception as e:
            if "500" in str(e) and "Internal Error" in str(e):
                logger.warning("PPI AvailableBalance 500 — cuenta posiblemente vacía")
            else:
                logger.warning("PPI: no se pudo traer saldo: %s", e)
            return {"ars": Decimal("0"), "usd": Decimal("0")}

        cash_ars = Decimal("0")
        cash_usd = Decimal("0")

        # PPI devuelve dos formatos posibles:
        # - AvailableBalance: lista plana [{name, symbol, amount, settlement}, ...]
        # - BalancesAndPositions: {groupedAvailability: [{currency, availability: [...]}, ...]}
        if isinstance(data, list):
            items = data
        else:
            items = [
                item
                for group in data.get("groupedAvailability", [])
                for item in group.get("availability", [])
            ]

        seen_settlements: set[str] = set()
        for item in items:
            name = str(item.get("name", "")).upper()
            symbol = str(item.get("symbol", "")).upper()
            amount = Decimal(str(item.get("amount", 0)))
            settlement = str(item.get("settlement", ""))
            # Contar solo INMEDIATA para no triplicar el saldo
            if settlement and settlement != "INMEDIATA":
                continue
            key = f"{symbol}:{settlement}"
            if key in seen_settlements:
                continue
            seen_settlements.add(key)
            if "USD" in symbol or "USD" in name or "U$S" in name or "DOLAR" in name:
                cash_usd += amount
            else:
                cash_ars += amount

        logger.info("PPI cash: ARS=%.2f USD=%.2f", float(cash_ars), float(cash_usd))
        return {"ars": cash_ars, "usd": cash_usd}

    def get_operations(
        self,
        account_number: str,
        fecha_desde: str | None = None,
        fecha_hasta: str | None = None,
    ) -> list[dict]:
        """
        Historial de movimientos/operaciones.
        Fechas en formato 'YYYY-MM-DD'.
        Cada operación devuelve: ticker, type ('COMPRA'/'VENTA'), quantity, price, date.
        """
        if self._mock:
            return []
        params: dict = {"accountNumber": account_number}
        if fecha_desde:
            params["dateFrom"] = fecha_desde
        if fecha_hasta:
            params["dateTo"] = fecha_hasta
        try:
            data = self._get("/api/1.0/Account/Movements", params=params)
            if isinstance(data, list):
                return data
            return data.get("movements", data.get("operaciones", []))
        except Exception as e:
            logger.warning("PPI: no se pudo traer operaciones: %s", e)
            return []

    # ── FX helpers (misma fuente que iol_client) ──────────────────────────────

    def _get_mep(self) -> float:
        """MEP actual desde dolarapi.com."""
        try:
            r = httpx.get("https://dolarapi.com/v1/dolares/bolsa", timeout=6)
            if r.status_code == 200:
                mep = r.json().get("venta") or r.json().get("compra") or 1430.0
                logger.info("PPI MEP: %.2f", float(mep))
                return float(mep)
        except Exception as e:
            logger.warning("PPI: no se pudo traer MEP, usando fallback: %s", e)
        return 1430.0

    def get_historical_mep(self, fecha: str) -> float:
        """MEP histórico desde bluelytics.com.ar."""
        try:
            r = httpx.get(
                f"https://api.bluelytics.com.ar/v2/historical?day={fecha}",
                timeout=8,
            )
            if r.status_code == 200:
                data = r.json()
                blue = data.get("blue", {}).get("value_sell", 0)
                oficial = data.get("official", {}).get("value_sell", 0)
                if blue and oficial:
                    mep = float((blue + oficial) / 2)
                    logger.info("PPI MEP histórico %s ≈ %.2f", fecha, mep)
                    return mep
        except Exception as e:
            logger.debug("PPI: MEP histórico no disponible para %s: %s", fecha, e)
        return self._get_mep()


# ── Helpers de normalización (module-level) ────────────────────────────────────


def _is_usd_instrument(ticker: str, group_name: str) -> bool:
    """
    Determina si el instrumento cotiza en USD (True) o ARS (False).
    - Bonos soberanos duales (AL*, GD*) → USD
    - LECAPs → ARS
    - CEDEARs → ARS (precio BYMA)
    - Acciones BYMA → ARS
    - ETFs → ARS por defecto (conservador; PPI podría tener ETFs en USD)
    """
    t = ticker.upper()
    if t in _USD_BOND_TICKERS:
        return True
    g = group_name.upper()
    if g == "BONOS" and (
        t.startswith("AL") or t.startswith("GD") or t.startswith("AE")
    ):
        return True
    return False


def _normalize_asset_type(group_name: str, ticker: str) -> str:
    """Mapea el grupo PPI al tipo interno de buildfuture."""
    g = group_name.upper()
    t = ticker.upper()

    if g == "CEDEARS":
        return "CEDEAR"
    if g == "ACCIONES":
        return "STOCK"
    if g in ("ETFS", "ETF"):
        return "ETF"
    if g == "BONOS":
        # LECAPs/LETEs: S31G6, S15Y6, etc.
        if _LETRA_TICKER_RE.match(t):
            return "LETRA"
        return "BOND"
    if g == "CAUCIONES":
        return "CAUCION"
    return "STOCK"

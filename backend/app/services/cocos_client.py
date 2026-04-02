"""
Cocos Capital client.
Auth: email + password + 2FA (TOTP code o TOTP secret BASE32).
API: reverse-engineered, no oficial. Usa pycocos + cloudscraper (Cloudflare bypass).
"""
import logging
from dataclasses import dataclass
from decimal import Decimal

import httpx

logger = logging.getLogger("buildfuture.cocos")

try:
    from pycocos import Cocos
except ImportError:
    Cocos = None  # type: ignore


DEFAULT_YIELDS: dict[str, Decimal] = {
    "FCI":    Decimal("0.08"),
    "CEDEAR": Decimal("0.10"),
    "BOND":   Decimal("0.09"),
    "LETRA":  Decimal("0.68"),
    "default": Decimal("0.08"),
}

# Mapping instrument_type Cocos → asset_type BuildFuture.
# Solo FCI confirmado en PoC. Agregar cuando se valide con cuenta que tenga otros instrumentos.
_INSTRUMENT_TYPE_MAP: dict[str, str] = {
    "FCI": "FCI",
}


@dataclass
class CocosPosition:
    ticker: str
    description: str
    asset_type: str
    quantity: Decimal
    current_price_usd: Decimal
    avg_purchase_price_usd: Decimal
    ppc_ars: Decimal
    annual_yield_pct: Decimal
    current_value_ars: Decimal


class CocosAuthError(Exception):
    pass


def _normalize_instrument_type(instrument_type: str) -> str:
    """Mapea instrument_type de Cocos a asset_type BuildFuture. Fallback: STOCK + warning."""
    normalized = _INSTRUMENT_TYPE_MAP.get(instrument_type.upper() if instrument_type else "")
    if normalized:
        return normalized
    if instrument_type:
        logger.warning(
            "CocosClient: instrument_type desconocido '%s' → asset_type='STOCK'. "
            "Agregar a _INSTRUMENT_TYPE_MAP cuando se confirme el mapping.",
            instrument_type,
        )
    return "STOCK"


class CocosClient:
    def __init__(self, email: str, password: str, totp_secret: str = ""):
        self.email = email
        self.password = password
        self.totp_secret = totp_secret
        self._app = None  # instancia de pycocos.Cocos, seteada en authenticate()

    def authenticate(self, code: str = "") -> None:
        """
        Autentica con Cocos Capital.
        - Si tiene totp_secret: pyotp genera el código automáticamente (auto-sync).
        - Si no tiene totp_secret: usa el código manual provisto en `code`.
        """
        if Cocos is None:
            raise CocosAuthError("pycocos no está instalado. Ejecutá: pip install pycocos")

        try:
            if self.totp_secret:
                logger.info("CocosClient: autenticando con TOTP secret (auto-sync)")
                self._app = Cocos(
                    email=self.email,
                    password=self.password,
                    topt_secret_key=self.totp_secret,
                )
            else:
                logger.info("CocosClient: autenticando con código 2FA manual")
                import builtins
                _original_input = builtins.input
                builtins.input = lambda _prompt="": code
                try:
                    self._app = Cocos(
                        email=self.email,
                        password=self.password,
                        topt_secret_key=None,
                    )
                finally:
                    builtins.input = _original_input
            logger.info("CocosClient: autenticación OK")
        except CocosAuthError:
            raise
        except Exception as e:
            raise CocosAuthError(f"Error autenticando con Cocos: {e}") from e

    def get_positions(self) -> list[CocosPosition]:
        """
        Trae posiciones desde historic_perf.
        - Usa last como precio actual. Fallback a previous_price si last es None.
        - Si ambos son None: skip con WARNING.
        - annual_yield_pct: DEFAULT_YIELDS por asset_type (nunca result_percentage).
        """
        if self._app is None:
            raise CocosAuthError("Cliente no autenticado. Llamar authenticate() primero.")

        mep = self._get_mep()
        mep_dec = Decimal(str(mep))

        raw = self._app.historic_performance()
        positions = []

        for item in raw:
            ticker = item.get("short_ticker", "")
            quantity_raw = item.get("quantity", 0)
            quantity = Decimal(str(quantity_raw))

            if quantity <= 0:
                continue

            last = item.get("last")
            previous = item.get("previous_price")
            price_ars = last if last is not None else previous

            if price_ars is None:
                logger.warning(
                    "CocosClient: %s sin precio (last=None, previous_price=None) — skip",
                    ticker,
                )
                continue

            price_ars_dec = Decimal(str(price_ars))
            current_price_usd = price_ars_dec / mep_dec
            current_value_ars = quantity * price_ars_dec

            average_price = item.get("average_price") or 0
            ppc_ars = Decimal(str(average_price))
            avg_purchase_price_usd = ppc_ars / mep_dec if ppc_ars > 0 else current_price_usd

            instrument_type = item.get("instrument_type", "")
            asset_type = _normalize_instrument_type(instrument_type)
            annual_yield_pct = DEFAULT_YIELDS.get(asset_type, DEFAULT_YIELDS["default"])

            logger.info(
                "  %s (%s) cant=%.2f last=%.4f ARS → USD %.4f | yield=%.0f%%",
                ticker, asset_type, float(quantity),
                float(price_ars_dec), float(current_price_usd),
                float(annual_yield_pct) * 100,
            )

            positions.append(CocosPosition(
                ticker=ticker,
                description=item.get("instrument_short_name", ""),
                asset_type=asset_type,
                quantity=quantity,
                current_price_usd=current_price_usd,
                avg_purchase_price_usd=avg_purchase_price_usd,
                ppc_ars=ppc_ars,
                annual_yield_pct=annual_yield_pct,
                current_value_ars=current_value_ars,
            ))

        logger.info("CocosClient: %d posiciones obtenidas", len(positions))
        return positions

    def get_cash(self) -> dict:
        """
        Trae saldo disponible desde buying_power.CI.
        Retorna {"ars": Decimal, "usd": Decimal}. Nunca falla — devuelve ceros en error.
        """
        if self._app is None:
            raise CocosAuthError("Cliente no autenticado. Llamar authenticate() primero.")

        try:
            data = self._app.buying_power()
            ci = data.get("CI", {})
            ars = Decimal(str(ci.get("ars") or 0))
            usd = Decimal(str(ci.get("usd") or 0))
            logger.info("CocosClient: cash CI — ARS=%.2f USD=%.2f", float(ars), float(usd))
            return {"ars": ars, "usd": usd}
        except CocosAuthError:
            raise
        except Exception as e:
            logger.warning("CocosClient: get_cash falló — %s. Retornando ceros.", e)
            return {"ars": Decimal("0"), "usd": Decimal("0")}

    def _get_mep(self) -> float:
        """MEP actual desde dolarapi.com. Fallback 1430."""
        try:
            r = httpx.get("https://dolarapi.com/v1/dolares/bolsa", timeout=6)
            if r.status_code == 200:
                mep = r.json().get("venta") or r.json().get("compra") or 1430.0
                logger.info("CocosClient: MEP=%.2f", mep)
                return float(mep)
        except Exception as e:
            logger.warning("CocosClient: no se pudo traer MEP, usando 1430: %s", e)
        return 1430.0

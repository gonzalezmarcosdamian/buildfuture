"""
IOL (InvertirOnline) API client.
Auth: OAuth2 password grant — bearer token (15min) + refresh token.
Docs: https://api.invertironline.com
"""
import httpx
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, date


IOL_BASE = "https://api.invertironline.com"

# Yield anual estimado por tipo de instrumento (fallback si IOL no lo devuelve)
DEFAULT_YIELDS = {
    "accion":   Decimal("0.10"),
    "cedear":   Decimal("0.10"),
    "bono":     Decimal("0.09"),
    "on":       Decimal("0.09"),  # obligacion negociable
    "letra":    Decimal("0.35"),  # TNA ARS alta
    "fci":      Decimal("0.08"),
    "cauciones": Decimal("0.30"),
    "default":  Decimal("0.08"),
}


@dataclass
class IOLPosition:
    ticker: str
    description: str
    asset_type: str   # normalizado a nuestros tipos
    quantity: Decimal
    avg_price_usd: Decimal
    current_price_usd: Decimal
    annual_yield_pct: Decimal


class IOLAuthError(Exception):
    pass


class IOLClient:
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self._access_token: str | None = None
        self._refresh_token: str | None = None

    def authenticate(self) -> None:
        """Obtiene bearer token con usuario/password."""
        resp = httpx.post(
            f"{IOL_BASE}/token",
            data={
                "username": self.username,
                "password": self.password,
                "grant_type": "password",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        if resp.status_code != 200:
            raise IOLAuthError(f"Auth fallida ({resp.status_code}): {resp.text[:200]}")

        data = resp.json()
        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token")

    def _headers(self) -> dict:
        if not self._access_token:
            self.authenticate()
        return {"Authorization": f"Bearer {self._access_token}"}

    def _refresh(self) -> None:
        resp = httpx.post(
            f"{IOL_BASE}/token",
            data={
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            self._access_token = data["access_token"]
            self._refresh_token = data.get("refresh_token", self._refresh_token)

    def _get(self, path: str, retry: bool = True) -> dict:
        resp = httpx.get(f"{IOL_BASE}{path}", headers=self._headers(), timeout=20)
        if resp.status_code == 401 and retry:
            self._refresh()
            return self._get(path, retry=False)
        resp.raise_for_status()
        return resp.json()

    def get_portfolio(self) -> list[IOLPosition]:
        """Trae posiciones del portafolio argentino."""
        data = self._get("/api/v2/portafolio/argentina")
        positions = []

        for activo in data.get("activos", []):
            titulo = activo.get("titulo", {})
            tipo_raw = titulo.get("tipo", "").lower()
            asset_type = _normalize_asset_type(tipo_raw)
            annual_yield = DEFAULT_YIELDS.get(tipo_raw, DEFAULT_YIELDS["default"])

            # IOL devuelve precios en ARS — convertimos a USD usando cotizacion del titulo
            # Si el instrumento es en USD (bonos, ONs) el precio ya viene en USD
            ultimo_precio = Decimal(str(activo.get("ultimoPrecio", 0)))
            ppc = Decimal(str(activo.get("ppc", 0)))  # precio promedio de compra
            cantidad = Decimal(str(activo.get("cantidad", 0)))

            # Moneda: 1=ARS, 2=USD (campo moneda en titulo)
            moneda = titulo.get("moneda", 1)
            fx_rate = Decimal("1") if moneda == 2 else None  # USD directo

            positions.append(IOLPosition(
                ticker=titulo.get("simbolo", ""),
                description=titulo.get("descripcion", ""),
                asset_type=asset_type,
                quantity=cantidad,
                avg_price_usd=ppc,
                current_price_usd=ultimo_precio,
                annual_yield_pct=annual_yield,
            ))

        return positions

    def get_account_balance(self) -> dict:
        """Trae saldos de la cuenta (ARS y USD disponibles)."""
        try:
            data = self._get("/api/v2/estadocuenta")
            return data
        except Exception:
            return {}


def _normalize_asset_type(tipo_iol: str) -> str:
    mapping = {
        "accion":    "CEDEAR",   # acciones argentinas
        "cedear":    "CEDEAR",
        "bono":      "BOND",
        "on":        "BOND",
        "letra":     "LETRA",
        "fci":       "FCI",
        "cauciones": "CAUCION",
        "opcion":    "OPTION",
    }
    for key, value in mapping.items():
        if key in tipo_iol:
            return value
    return "STOCK"

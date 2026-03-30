"""
IOL (InvertirOnline) API client.
Auth: OAuth2 password grant — bearer token + refresh token.
Docs: https://api.invertironline.com
"""
import logging
import httpx
from dataclasses import dataclass
from decimal import Decimal
from datetime import date

logger = logging.getLogger("buildfuture.iol")

IOL_BASE = "https://api.invertironline.com"

DEFAULT_YIELDS = {
    "accion":    Decimal("0.10"),
    "cedear":    Decimal("0.10"),
    "bono":      Decimal("0.09"),
    "on":        Decimal("0.09"),
    "letra":     Decimal("0.68"),
    "fci":       Decimal("0.08"),
    "cauciones": Decimal("0.30"),
    "default":   Decimal("0.08"),
}


@dataclass
class IOLPosition:
    ticker: str
    description: str
    asset_type: str
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
        logger.info("IOL auth — usuario: %s", self.username)
        payload = (
            f"username={self.username}"
            f"&password={self.password}"
            f"&grant_type=password"
        )
        logger.debug("POST %s/token", IOL_BASE)
        try:
            resp = httpx.post(
                f"{IOL_BASE}/token",
                content=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=20,
            )
        except httpx.ConnectError as e:
            logger.error("IOL no alcanzable: %s", e)
            raise IOLAuthError(f"No se pudo conectar con IOL: {e}")
        except httpx.TimeoutException:
            logger.error("IOL timeout en auth")
            raise IOLAuthError("Timeout conectando con IOL")

        logger.info("IOL auth response: status=%s body_preview=%s",
                    resp.status_code, resp.text[:300])

        if resp.status_code != 200:
            raise IOLAuthError(
                f"Status {resp.status_code} — respuesta: {resp.text[:500]}"
            )

        try:
            data = resp.json()
        except Exception:
            logger.error("IOL auth: respuesta no es JSON: %s", resp.text[:300])
            raise IOLAuthError(f"Respuesta inesperada de IOL: {resp.text[:200]}")

        self._access_token = data.get("access_token")
        self._refresh_token = data.get("refresh_token")

        if not self._access_token:
            logger.error("IOL auth: no hay access_token en respuesta: %s", data)
            raise IOLAuthError(f"IOL no devolvió access_token. Respuesta: {data}")

        logger.info("IOL auth OK — token obtenido")

    def _headers(self) -> dict:
        if not self._access_token:
            self.authenticate()
        return {"Authorization": f"Bearer {self._access_token}"}

    def _refresh(self) -> None:
        logger.info("IOL refresh token")
        resp = httpx.post(
            f"{IOL_BASE}/token",
            content=f"refresh_token={self._refresh_token}&grant_type=refresh_token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        logger.debug("IOL refresh status=%s", resp.status_code)
        if resp.status_code == 200:
            data = resp.json()
            self._access_token = data.get("access_token", self._access_token)
            self._refresh_token = data.get("refresh_token", self._refresh_token)
        else:
            logger.warning("IOL refresh falló (%s) — reintentando auth completa", resp.status_code)
            self.authenticate()

    def _get(self, path: str, retry: bool = True) -> dict:
        url = f"{IOL_BASE}{path}"
        logger.debug("GET %s", url)
        resp = httpx.get(url, headers=self._headers(), timeout=20)
        logger.debug("GET %s → %s", url, resp.status_code)
        if resp.status_code == 401 and retry:
            logger.info("Token expirado, refrescando...")
            self._refresh()
            return self._get(path, retry=False)
        if resp.status_code != 200:
            logger.error("GET %s falló: %s %s", url, resp.status_code, resp.text[:300])
        resp.raise_for_status()
        return resp.json()

    def get_portfolio(self) -> list[IOLPosition]:
        logger.info("Fetching portafolio argentina")
        data = self._get("/api/v2/portafolio/argentina")
        activos = data.get("activos", [])
        logger.info("Portafolio recibido: %d activos", len(activos))
        logger.debug("Portafolio raw: %s", activos)

        positions = []
        for activo in activos:
            titulo = activo.get("titulo", {})
            tipo_raw = str(titulo.get("tipo", "")).lower()
            asset_type = _normalize_asset_type(tipo_raw)
            annual_yield = DEFAULT_YIELDS.get(tipo_raw, DEFAULT_YIELDS["default"])

            cantidad = Decimal(str(activo.get("cantidad", 0)))
            ultimo_precio = Decimal(str(activo.get("ultimoPrecio", 0)))
            ppc = Decimal(str(activo.get("ppc", 0)))

            logger.debug("Activo: ticker=%s tipo=%s cantidad=%s precio=%s",
                         titulo.get("simbolo"), tipo_raw, cantidad, ultimo_precio)

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
        try:
            return self._get("/api/v2/estadocuenta")
        except Exception as e:
            logger.warning("No se pudo traer estado de cuenta: %s", e)
            return {}


def _normalize_asset_type(tipo_iol: str) -> str:
    mapping = {
        "accion":    "CEDEAR",
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

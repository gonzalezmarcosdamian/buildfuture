"""
Nexo Pro API client.
Auth: HMAC SHA-256 — api_key + api_secret.
Docs: https://pro.nexo.com/apiDocPro.html
"""

import base64
import hashlib
import hmac
import logging
import time
import httpx
from dataclasses import dataclass
from decimal import Decimal

logger = logging.getLogger("buildfuture.nexo")

NEXO_BASE = "https://pro.nexo.com"

# Yield estimado anual por asset type en Nexo (savings wallet)
NEXO_YIELDS = {
    "btc": Decimal("0.04"),
    "eth": Decimal("0.04"),
    "bnb": Decimal("0.04"),
    "usdt": Decimal("0.14"),
    "usdc": Decimal("0.14"),
    "dai": Decimal("0.14"),
    "nexo": Decimal("0.12"),
    "default": Decimal("0.05"),
}

STABLE_COINS = {
    "usdt",
    "usdc",
    "dai",
    "busd",
    "tusd",
    "usdp",
    "usdd",
    "frax",
    "lusd",
    "nexo",
}


@dataclass
class NexoPosition:
    ticker: str
    description: str
    asset_type: str  # CRYPTO | STABLE
    quantity: Decimal
    current_price_usd: Decimal
    annual_yield_pct: Decimal


class NexoAuthError(Exception):
    pass


class NexoClient:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret

    def _sign(self, nonce: str) -> str:
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            nonce.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(signature).decode("utf-8")

    def _headers(self) -> dict:
        nonce = str(int(time.time() * 1000))
        return {
            "X-API-KEY": self.api_key,
            "X-NONCE": nonce,
            "X-SIGNATURE": self._sign(nonce),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _get(self, path: str) -> dict:
        url = f"{NEXO_BASE}{path}"
        logger.debug("GET %s", url)
        try:
            resp = httpx.get(url, headers=self._headers(), timeout=20)
        except httpx.ConnectError as e:
            raise NexoAuthError(f"No se pudo conectar con Nexo: {e}")
        except httpx.TimeoutException:
            raise NexoAuthError("Timeout conectando con Nexo")

        logger.debug("GET %s → %s", url, resp.status_code)
        logger.debug("Response body: %s", resp.text[:500])

        if resp.status_code == 401:
            raise NexoAuthError(f"Credenciales inválidas: {resp.text[:300]}")
        if resp.status_code != 200:
            raise NexoAuthError(f"Error {resp.status_code}: {resp.text[:300]}")

        return resp.json()

    def test_auth(self) -> None:
        """Verifica que las credenciales sean válidas."""
        logger.info("Nexo auth test — api_key: %s...", self.api_key[:8])
        self._get("/api/v1/accountSummary")
        logger.info("Nexo auth OK")

    def get_balances(self) -> list[NexoPosition]:
        logger.info("Fetching Nexo balances")
        data = self._get("/api/v1/accountSummary")
        logger.debug("Nexo accountSummary raw: %s", str(data)[:500])

        balances = data.get("balances", [])
        logger.info("Nexo balances recibidos: %d assets", len(balances))

        positions = []
        for b in balances:
            asset = b.get("asset", "").upper()
            asset_lower = asset.lower()

            total_balance = Decimal(str(b.get("totalBalance", 0)))
            if total_balance <= 0:
                logger.debug("Nexo skip %s — balance cero", asset)
                continue

            # Precio en USD — Nexo lo provee directamente
            price_usd = Decimal(str(b.get("price", 0)))

            is_stable = asset_lower in STABLE_COINS
            asset_type = "STABLE" if is_stable else "CRYPTO"
            annual_yield = NEXO_YIELDS.get(asset_lower, NEXO_YIELDS["default"])

            logger.debug(
                "Nexo asset: %s tipo=%s balance=%s precio=%s",
                asset,
                asset_type,
                total_balance,
                price_usd,
            )

            positions.append(
                NexoPosition(
                    ticker=asset,
                    description=f"{asset} — Nexo",
                    asset_type=asset_type,
                    quantity=total_balance,
                    current_price_usd=price_usd,
                    annual_yield_pct=annual_yield,
                )
            )

        return positions

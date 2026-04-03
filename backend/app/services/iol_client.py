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
    ppc_ars: Decimal = Decimal("0")      # precio promedio de compra en ARS crudo
    valorizado_ars: Decimal = Decimal("0")  # valor total ARS directo de IOL (sin conversión)


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
        mep = self._get_mep()
        data = self._get("/api/v2/portafolio/argentina")
        activos = data.get("activos", [])
        logger.info("Portafolio recibido: %d activos | MEP=%.0f", len(activos), mep)

        positions = []
        for activo in activos:
            titulo = activo.get("titulo", {})
            ticker_sym = titulo.get("simbolo", "")
            tipo_raw = str(titulo.get("tipo", "")).lower()
            asset_type = _normalize_asset_type(tipo_raw, ticker_sym)
            # Normalizar clave para DEFAULT_YIELDS (IOL devuelve "CEDEARS", "Letras", etc.)
            # Si tipo_raw no matchea (ej: IOL envía "Stock" para un bono), usar el asset_type
            # resultante del ticker override para elegir el yield correcto
            yield_key = next((k for k in DEFAULT_YIELDS if k in tipo_raw), None)
            if yield_key is None:
                _asset_to_yield_key = {
                    "BOND": "bono", "ON": "on", "CEDEAR": "cedear",
                    "LETRA": "letra", "FCI": "fci",
                }
                yield_key = _asset_to_yield_key.get(asset_type, "default")
            annual_yield = DEFAULT_YIELDS[yield_key]

            cantidad = Decimal(str(activo.get("cantidad", 0)))
            valorizado = Decimal(str(activo.get("valorizado", 0)))
            ppc = Decimal(str(activo.get("ppc", 0)))

            if cantidad <= 0:
                continue

            # IOL cotiza precios en ARS para todos los instrumentos del mercado argentino.
            # valorizado = cantidad × precio_ars_por_unidad (independiente de convención de cotización).
            # Usamos valorizado/cantidad para evitar diferencias de convención (CEDEARs por unidad,
            # Letras por cada 100 nominales según lo observable: 101.86/100 = 1.0186 ARS/nominal).
            mep_dec = Decimal(str(mep))
            price_ars = valorizado / cantidad
            current_price_usd = price_ars / mep_dec

            # ppc sigue la misma convención de cotización que ultimoPrecio
            # Para letras: ppc≈101.85 → mismo ajuste
            avg_price_ars = (ppc / Decimal("100")) if asset_type == "LETRA" else ppc
            avg_price_usd = avg_price_ars / mep_dec if avg_price_ars > 0 else current_price_usd

            logger.info(
                "  %s (%s) cant=%.0f valorizado=%.0f ARS → USD %.2f | yield=%.0f%%",
                titulo.get("simbolo"), asset_type, float(cantidad),
                float(valorizado), float(valorizado / mep_dec), annual_yield * 100,
            )

            positions.append(IOLPosition(
                ticker=titulo.get("simbolo", ""),
                description=titulo.get("descripcion", ""),
                asset_type=asset_type,
                quantity=cantidad,
                avg_price_usd=avg_price_usd,
                current_price_usd=current_price_usd,
                annual_yield_pct=annual_yield,
                ppc_ars=Decimal(str(ppc)),       # ARS crudo, sin convertir
                valorizado_ars=valorizado,        # valor total ARS directo de IOL
            ))

        return positions

    def get_cedear_implicit_ccl(
        self,
        ticker: str,
        price_bcba_ars: float,
        purchase_date: str | None = None,
    ) -> float | None:
        """
        Calcula el CCL implícito de un CEDEAR usando Yahoo Finance para el precio subyacente NYSE.

        Lógica:
          1. Descarga precio NYSE actual + serie histórica (1 año).
          2. Deriva la equivalencia (ratio): equiv = round(nyse_actual × mep / bcba_actual).
          3. Si hay fecha de compra: usa precio NYSE en esa fecha.
             purchase_ccl = ppc_ars × equiv / nyse_price_at_date
          4. Si no hay fecha: usa precio NYSE actual → CCL de valuación actual.

        Retorna None si no puede obtener el precio (instrumento no listado en Yahoo).
        """
        import httpx as _httpx

        # Yahoo usa el símbolo NYSE directo para la mayoría de los CEDEARs
        try:
            r = _httpx.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
                params={"interval": "1d", "range": "1y"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            if r.status_code != 200:
                return None
            chart = r.json()["chart"]["result"][0]
        except Exception as e:
            logger.debug("Yahoo Finance falló para %s: %s", ticker, e)
            return None

        nyse_current = chart["meta"].get("regularMarketPrice")
        if not nyse_current or nyse_current <= 0:
            return None

        # Derivar equivalencia (nº de CEDEARs por 1 acción NYSE)
        mep = self._get_mep()
        equiv_float = nyse_current * mep / price_bcba_ars
        equiv = round(equiv_float)
        if equiv <= 0:
            equiv = 1
        logger.info("CEDEAR %s: equiv derivado=%.2f→%d | CCL_actual=%.1f",
                    ticker, equiv_float, equiv,
                    price_bcba_ars * equiv / nyse_current)

        # Precio NYSE en la fecha de compra
        nyse_at_purchase = nyse_current  # fallback: precio actual
        if purchase_date:
            try:
                timestamps = chart.get("timestamp", [])
                closes = chart["indicators"]["quote"][0].get("close", [])
                target = purchase_date  # "YYYY-MM-DD"
                from datetime import datetime as _dt
                target_ts = _dt.strptime(target, "%Y-%m-%d").timestamp()
                # Buscar el timestamp más cercano a la fecha de compra
                best_idx, best_diff = 0, float("inf")
                for idx, ts in enumerate(timestamps):
                    diff = abs(ts - target_ts)
                    if diff < best_diff and closes[idx] is not None:
                        best_diff = diff
                        best_idx = idx
                nyse_at_purchase = closes[best_idx] or nyse_current
                logger.info("CEDEAR %s precio NYSE en %s = %.2f", ticker, target, nyse_at_purchase)
            except Exception as e:
                logger.debug("No se pudo traer precio histórico %s en %s: %s", ticker, purchase_date, e)

        ccl = price_bcba_ars * equiv / nyse_at_purchase
        return round(ccl, 2)

    def get_historical_mep(self, fecha: str) -> float:
        """
        Intenta obtener el MEP de una fecha pasada (YYYY-MM-DD).
        Fuente: bluelytics.com.ar (tiene serie histórica).
        Fallback: MEP actual si no puede obtenerlo.
        """
        try:
            import httpx as _httpx
            r = _httpx.get(
                f"https://api.bluelytics.com.ar/v2/historical?day={fecha}",
                timeout=8,
            )
            if r.status_code == 200:
                data = r.json()
                # bluelytics devuelve blue y oficial; MEP ≈ promedio blue+oficial/2 o blue
                blue_venta = data.get("blue", {}).get("value_sell", 0)
                oficial_venta = data.get("official", {}).get("value_sell", 0)
                if blue_venta and oficial_venta:
                    mep_approx = (blue_venta + oficial_venta) / 2
                    logger.info("MEP histórico %s ≈ %.2f (blue+oficial/2)", fecha, mep_approx)
                    return float(mep_approx)
        except Exception as e:
            logger.debug("No se pudo traer MEP histórico para %s: %s", fecha, e)
        return self._get_mep()

    def _get_mep(self) -> float:
        """Trae el tipo de cambio MEP actual desde dolarapi.com."""
        try:
            import httpx as _httpx
            r = _httpx.get("https://dolarapi.com/v1/dolares/bolsa", timeout=6)
            if r.status_code == 200:
                mep = r.json().get("venta") or r.json().get("compra") or 1430.0
                logger.info("MEP actualizado: %.2f", mep)
                return float(mep)
        except Exception as e:
            logger.warning("No se pudo traer MEP, usando fallback 1430: %s", e)
        return 1430.0

    def get_account_balance(self) -> dict:
        try:
            return self._get("/api/v2/estadocuenta")
        except Exception as e:
            logger.warning("No se pudo traer estado de cuenta: %s", e)
            return {}

    def get_cash_balances(self) -> dict[str, Decimal]:
        """
        Extrae saldos disponibles en ARS y USD del estado de cuenta.
        Retorna {"ars": Decimal, "usd": Decimal} — nunca falla.
        IOL estructura: {"cuentas": [{"moneda": "peso_Argentino"|"dolar_Estadounidense", "disponible": N}, ...]}
        """
        result = {"ars": Decimal("0"), "usd": Decimal("0")}
        try:
            data = self.get_account_balance()
            logger.info("estadocuenta raw: %s", str(data)[:500])

            cuentas = data.get("cuentas") or data.get("cuenta") or []
            if isinstance(cuentas, list) and cuentas:
                for cuenta in cuentas:
                    moneda = str(cuenta.get("moneda", "")).lower()
                    disponible = Decimal(str(cuenta.get("disponible") or cuenta.get("saldo") or 0))
                    if any(k in moneda for k in ("peso", "ars", "pesos", "argentino")):
                        logger.info("Cash ARS (cuenta): %.2f", float(disponible))
                        result["ars"] = disponible
                    elif any(k in moneda for k in ("dolar", "usd", "dollar", "estadounidense")):
                        logger.info("Cash USD (cuenta): %.2f", float(disponible))
                        result["usd"] = disponible
                return result

            # Estructura flat: solo ARS
            if "disponible" in data:
                result["ars"] = Decimal(str(data["disponible"] or 0))
                logger.info("Cash ARS (flat): %.2f", float(result["ars"]))

        except Exception as e:
            logger.warning("get_cash_balances falló: %s", e)
        return result

    def get_cash_balance_ars(self) -> Decimal:
        """Compatibilidad: retorna solo el saldo ARS."""
        return self.get_cash_balances()["ars"]

    def get_operations(self, fecha_desde: str | None = None, fecha_hasta: str | None = None) -> list[dict]:
        """
        Trae historial de operaciones (compras/ventas).
        Fechas en formato 'YYYY-MM-DD'. Sin fechas devuelve los últimos 90 días.
        Cada operación tiene: simbolo, tipo (compra/venta), cantidad, precio, fechaOrden.
        """
        params = []
        if fecha_desde:
            params.append(f"fechaDesde={fecha_desde}")
        if fecha_hasta:
            params.append(f"fechaHasta={fecha_hasta}")
        qs = ("?" + "&".join(params)) if params else ""
        try:
            data = self._get(f"/api/v2/operaciones{qs}")
            # IOL devuelve lista directa o dict con clave 'operaciones'
            if isinstance(data, list):
                return data
            return data.get("operaciones", [])
        except Exception as e:
            logger.warning("No se pudo traer operaciones: %s", e)
            return []

    def get_cotizacion(self, mercado: str, simbolo: str) -> dict:
        """Trae cotización actual de un instrumento. mercado: 'bCBA' o 'nYSE'"""
        try:
            return self._get(f"/api/v2/Cotizacion/Titulos/{mercado}/{simbolo}")
        except Exception as e:
            logger.warning("No se pudo traer cotizacion de %s: %s", simbolo, e)
            return {}

    def get_letras(self) -> list[dict]:
        """Trae letras del Tesoro disponibles en el mercado."""
        try:
            data = self._get("/api/v2/Titulo/Cotizacion/lista/bCBA/LETRAS")
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.warning("No se pudo traer letras: %s", e)
            return []

    def get_live_yields(self, tickers: list[str], mercado: str = "bCBA") -> dict[str, float]:
        """
        Retorna un dict {ticker: yield_anual_estimado} con datos reales de IOL.
        Para LECAPs: TNA calculada desde precio actual (VN=1000) + días reales al vencimiento
        decodificados del ticker (S31G6 → 31/ago/2026). Sin proxies de días fijos.
        Para bonos usa DEFAULT_YIELDS calibradas.
        Fallback a DEFAULT_YIELDS si no puede traer el dato o parsear el vencimiento.
        """
        from app.services.yield_updater import _parse_lecap_maturity

        today = date.today()
        results = {}
        for ticker in tickers:
            try:
                data = self._get(f"/api/v2/Cotizacion/Titulos/{mercado}/{ticker}")
                ultimo = data.get("ultimoPrecio") or data.get("ultimo") or 0
                # Para letras: precio < 1000 (cotiza en VN=1000)
                if ultimo and ultimo > 0 and ultimo < 1000:
                    maturity = _parse_lecap_maturity(ticker)
                    if maturity:
                        dias_restantes = (maturity - today).days
                    else:
                        dias_restantes = 180  # fallback si el ticker no sigue el patrón S[DD][M][Y]
                    if dias_restantes > 1:
                        tna = ((1000 / ultimo) - 1) * (365 / dias_restantes)
                        results[ticker] = round(tna, 4)
                        logger.info(
                            "IOL live yield %s: precio=%.2f vto=%s días=%d TNA=%.2f%%",
                            ticker, ultimo,
                            maturity.isoformat() if maturity else "proxy",
                            dias_restantes, tna * 100,
                        )
                    else:
                        results[ticker] = 0.0  # vencida o vence hoy
                elif ultimo and ultimo > 0:
                    results[ticker] = DEFAULT_YIELDS.get(
                        str(data.get("tipo", "")).lower(), DEFAULT_YIELDS["default"]
                    )
            except Exception as e:
                logger.debug("No se pudo traer yield live de %s: %s", ticker, e)
        return results


# Tickers conocidos que IOL clasifica mal — override explícito
_TICKER_TYPE_OVERRIDES: dict[str, str] = {
    # IOL FCIs
    "IOLCAMA": "FCI",
    "IOLCAM":  "FCI",
    "IOLMMA":  "FCI",
    "IOLMM":   "FCI",
    # Bonos soberanos USD (IOL los puede clasificar como "STOCK")
    "AL29": "BOND", "AL30": "BOND", "AL35": "BOND", "AL41": "BOND", "AE38": "BOND",
    "GD29": "BOND", "GD30": "BOND", "GD35": "BOND", "GD38": "BOND",
    "GD41": "BOND", "GD46": "BOND",
    # Bopreales
    "BPY26": "BOND", "BPJ25": "BOND", "BPA7": "BOND",
    # Obligaciones negociables conocidas
    "YCA6O": "ON", "YMCXO": "ON", "CA6O": "ON", "TECEO": "ON",
    "MTCGO": "ON", "CRESO": "ON", "PNDCO": "ON",
}


def _normalize_asset_type(tipo_iol: str, ticker: str = "") -> str:
    # Override por ticker (más confiable que el string de tipo IOL)
    if ticker.upper() in _TICKER_TYPE_OVERRIDES:
        return _TICKER_TYPE_OVERRIDES[ticker.upper()]

    mapping = {
        "fci":       "FCI",
        "fondo":     "FCI",
        "cedear":    "CEDEAR",
        "accion":    "CEDEAR",
        "letra":     "LETRA",
        "on":        "ON",
        "bono":      "BOND",
        "cauciones": "CAUCION",
        "opcion":    "OPTION",
    }
    for key, value in mapping.items():
        if key in tipo_iol:
            return value
    return "STOCK"

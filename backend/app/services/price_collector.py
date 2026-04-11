"""
Price Collector — job nocturno de recolección de precios de mercado.

Corre una vez por día hábil a las 18:30 (post-cierre BYMA).
Persiste precios en instrument_prices y metadata estática en instrument_metadata.

Fuentes:
  BYMA btnLetras          → LECAPs y letras CER (precio vwap + metadata via fichatecnica)
  BYMA btnTitPublicos     → bonos soberanos (precio vwap)
  BYMA btnObligNegociables → ONs corporativas (precio vwap)
  BYMA btnCedears         → CEDEARs (precio vwap)
  ArgentinaDatos FCI      → VCP diario por categoría

Invariantes:
  - instrument_metadata se escribe UNA SOLA VEZ por ticker (metadata estática no cambia)
  - instrument_prices es append-only: un registro por (ticker, price_date)
  - Si BYMA falla → loguea y continúa. Los precios del día anterior persisten como proxy.
  - Idempotente: ejecutar dos veces el mismo día no duplica datos (ON CONFLICT DO NOTHING / DO UPDATE)
"""

import logging
from datetime import date
from decimal import Decimal

import httpx

logger = logging.getLogger("buildfuture.price_collector")

ARGENTINADATOS_BASE = "https://api.argentinadatos.com/v1"
FCI_CATEGORIAS = ["mercadoDinero", "rentaMixta", "rentaVariable", "rentaFija"]


def collect_daily_prices(db, mep_today: Decimal | None = None) -> dict:
    """
    Punto de entrada principal. Llama a todas las fuentes y persiste en DB.
    Retorna un resumen: {letras: N, bonos: N, ons: N, cedears: N, fci: N, errors: []}
    """
    from app.models import InstrumentMetadata, InstrumentPrice
    from app.services.byma_client import (
        _post_market_data,
        _get_ficha_tecnica,
        _parse_tem_from_interes,
        _parse_date,
    )

    today = date.today()
    summary = {"letras": 0, "bonos": 0, "ons": 0, "cedears": 0, "fci": 0, "errors": []}

    # ── 1. LECAPs y letras CER (btnLetras) ───────────────────────────────────
    try:
        items = _post_market_data("btnLetras", page_size=500, t0=True)
        if not items:
            items = _post_market_data("btnLetras", page_size=500, t0=False)

        for item in items:
            ticker = str(item.get("symbol") or "").upper()
            if not ticker:
                continue
            vwap = _safe_decimal(item.get("vwap"))
            prev_close = _safe_decimal(item.get("previousClosingPrice"))
            volume = _safe_decimal(item.get("tradeVolume"))

            # Metadata estática — solo si no existe
            existing_meta = db.get(InstrumentMetadata, ticker)
            if not existing_meta:
                ficha = _get_ficha_tecnica(ticker)
                if ficha:
                    tem = _parse_tem_from_interes(ficha.get("interes", ""))
                    emision = _parse_date(ficha.get("fechaEmision", ""))
                    vto = _parse_date(ficha.get("fechaVencimiento", ""))
                    meta = InstrumentMetadata(
                        ticker=ticker,
                        asset_type="LETRA",
                        tem=Decimal(str(tem)) if tem else None,
                        emision_date=emision,
                        maturity_date=vto,
                        currency="ARS",
                        description=ficha.get("denominacion", ""),
                    )
                    db.merge(meta)

            # Precio del día
            _upsert_price(db, InstrumentPrice(
                ticker=ticker,
                price_date=today,
                vwap=vwap,
                prev_close=prev_close,
                volume=volume,
                mep=mep_today,
                source="BYMA",
            ))
            summary["letras"] += 1

        db.commit()
        logger.info("price_collector: %d letras guardadas", summary["letras"])
    except Exception as e:
        db.rollback()
        summary["errors"].append(f"letras: {e}")
        logger.warning("price_collector: letras falló — %s", e)

    # ── 2. Bonos soberanos (btnTitPublicos) ──────────────────────────────────
    try:
        items = _post_market_data("btnTitPublicos", page_size=500, t0=True)
        if not items:
            items = _post_market_data("btnTitPublicos", page_size=500, t0=False)

        for item in items:
            ticker = str(item.get("symbol") or "").upper()
            if not ticker:
                continue

            # Metadata — solo si no existe
            if not db.get(InstrumentMetadata, ticker):
                ficha = _get_ficha_tecnica(ticker)
                currency = "USD" if ticker.endswith("D") or ticker.startswith("GD") or ticker.startswith("AL") else "ARS"
                meta = InstrumentMetadata(
                    ticker=ticker,
                    asset_type="BOND",
                    currency=currency,
                    emision_date=_parse_date(ficha.get("fechaEmision", "")) if ficha else None,
                    maturity_date=_parse_date(ficha.get("fechaVencimiento", "")) if ficha else None,
                    description=ficha.get("denominacion", "") if ficha else "",
                )
                db.merge(meta)

            _upsert_price(db, InstrumentPrice(
                ticker=ticker,
                price_date=today,
                vwap=_safe_decimal(item.get("vwap")),
                prev_close=_safe_decimal(item.get("previousClosingPrice")),
                volume=_safe_decimal(item.get("tradeVolume")),
                mep=mep_today,
                source="BYMA",
            ))
            summary["bonos"] += 1

        db.commit()
        logger.info("price_collector: %d bonos guardados", summary["bonos"])
    except Exception as e:
        db.rollback()
        summary["errors"].append(f"bonos: {e}")
        logger.warning("price_collector: bonos falló — %s", e)

    # ── 3. ONs corporativas (btnObligNegociables) ────────────────────────────
    try:
        items = _post_market_data("btnObligNegociables", page_size=500, t0=True)
        if not items:
            items = _post_market_data("btnObligNegociables", page_size=500, t0=False)

        for item in items:
            ticker = str(item.get("symbol") or "").upper()
            if not ticker:
                continue

            if not db.get(InstrumentMetadata, ticker):
                ficha = _get_ficha_tecnica(ticker)
                meta = InstrumentMetadata(
                    ticker=ticker,
                    asset_type="ON",
                    currency="USD",
                    emision_date=_parse_date(ficha.get("fechaEmision", "")) if ficha else None,
                    maturity_date=_parse_date(ficha.get("fechaVencimiento", "")) if ficha else None,
                    description=ficha.get("denominacion", "") if ficha else "",
                )
                db.merge(meta)

            _upsert_price(db, InstrumentPrice(
                ticker=ticker,
                price_date=today,
                vwap=_safe_decimal(item.get("vwap")),
                prev_close=_safe_decimal(item.get("previousClosingPrice")),
                volume=_safe_decimal(item.get("tradeVolume")),
                mep=mep_today,
                source="BYMA",
            ))
            summary["ons"] += 1

        db.commit()
        logger.info("price_collector: %d ONs guardadas", summary["ons"])
    except Exception as e:
        db.rollback()
        summary["errors"].append(f"ons: {e}")
        logger.warning("price_collector: ONs falló — %s", e)

    # ── 4. CEDEARs (btnCedears) ──────────────────────────────────────────────
    try:
        items = _post_market_data("btnCedears", page_size=1000, t0=True)
        if not items:
            items = _post_market_data("btnCedears", page_size=1000, t0=False)

        for item in items:
            ticker = str(item.get("symbol") or "").upper()
            if not ticker:
                continue

            _upsert_price(db, InstrumentPrice(
                ticker=ticker,
                price_date=today,
                vwap=_safe_decimal(item.get("vwap")),
                prev_close=_safe_decimal(item.get("previousClosingPrice")),
                volume=_safe_decimal(item.get("tradeVolume")),
                mep=mep_today,
                source="BYMA",
            ))
            summary["cedears"] += 1

        db.commit()
        logger.info("price_collector: %d CEDEARs guardados", summary["cedears"])
    except Exception as e:
        db.rollback()
        summary["errors"].append(f"cedears: {e}")
        logger.warning("price_collector: CEDEARs falló — %s", e)

    # ── 5. FCIs — VCP diario por categoría (ArgentinaDatos) ──────────────────
    try:
        fci_count = 0
        for categoria in FCI_CATEGORIAS:
            fondos = _fetch_fci_categoria(categoria)
            for fondo in fondos:
                nombre = fondo.get("fondo", "")
                vcp = _safe_decimal(fondo.get("vcp"))
                if not nombre or vcp is None:
                    continue

                # Usar nombre del fondo como ticker para instrument_prices
                ticker_fci = f"FCI:{nombre[:18]}"  # max 20 chars

                # Metadata — solo si no existe
                if not db.get(InstrumentMetadata, ticker_fci):
                    db.merge(InstrumentMetadata(
                        ticker=ticker_fci,
                        asset_type="FCI",
                        currency="ARS",
                        fondo_name=nombre,
                        fci_categoria=categoria,
                    ))

                _upsert_price(db, InstrumentPrice(
                    ticker=ticker_fci,
                    price_date=today,
                    vwap=vcp,
                    source="ArgentinaDatos",
                ))
                fci_count += 1

        summary["fci"] = fci_count
        db.commit()
        logger.info("price_collector: %d FCIs guardados", fci_count)
    except Exception as e:
        db.rollback()
        summary["errors"].append(f"fci: {e}")
        logger.warning("price_collector: FCIs falló — %s", e)

    # ── 6. MEP del día como registro propio ──────────────────────────────────
    if mep_today and mep_today > 0:
        try:
            _upsert_price(db, InstrumentPrice(
                ticker="MEP",
                price_date=today,
                vwap=mep_today,
                source="IOL",
            ))
            db.commit()
        except Exception as e:
            db.rollback()
            logger.warning("price_collector: MEP save falló — %s", e)

    logger.info(
        "price_collector: resumen — letras=%d bonos=%d ons=%d cedears=%d fci=%d errors=%d",
        summary["letras"], summary["bonos"], summary["ons"],
        summary["cedears"], summary["fci"], len(summary["errors"]),
    )
    return summary


def _upsert_price(db, price_obj) -> None:
    """INSERT OR REPLACE de un InstrumentPrice — idempotente."""
    # Usar merge de SQLAlchemy (funciona tanto en SQLite como Postgres)
    existing = (
        db.query(price_obj.__class__)
        .filter_by(ticker=price_obj.ticker, price_date=price_obj.price_date)
        .first()
    )
    if existing:
        if price_obj.vwap is not None:
            existing.vwap = price_obj.vwap
        if price_obj.prev_close is not None:
            existing.prev_close = price_obj.prev_close
        if price_obj.volume is not None:
            existing.volume = price_obj.volume
        if price_obj.mep is not None:
            existing.mep = price_obj.mep
    else:
        db.add(price_obj)


def _safe_decimal(val) -> Decimal | None:
    """Convierte un valor a Decimal, retorna None si es 0 o inválido."""
    try:
        d = Decimal(str(val))
        return d if d > 0 else None
    except Exception:
        return None


def _fetch_fci_categoria(categoria: str) -> list[dict]:
    """Descarga todos los fondos de una categoría FCI desde ArgentinaDatos."""
    try:
        r = httpx.get(
            f"{ARGENTINADATOS_BASE}/finanzas/fci/{categoria}/",
            headers={"Accept": "application/json", "User-Agent": "BuildFuture/1.0"},
            timeout=10,
        )
        if r.is_success:
            return r.json()
    except Exception as e:
        logger.warning("_fetch_fci_categoria %s: %s", categoria, e)
    return []


def backfill_metadata_from_positions(db) -> int:
    """
    Rellena instrument_metadata con la metadata de todas las posiciones activas
    de tipo LETRA, BOND y ON que aún no tengan registro.
    Se llama una sola vez en startup (main.py) para sembrar la tabla inicial.
    """
    from app.models import Position, InstrumentMetadata
    from app.services.byma_client import (
        _get_ficha_tecnica,
        _parse_tem_from_interes,
        _parse_date,
    )

    positions = (
        db.query(Position)
        .filter(
            Position.is_active.is_(True),
            Position.asset_type.in_(["LETRA", "BOND", "ON"]),
        )
        .all()
    )

    saved = 0
    seen = set()
    for pos in positions:
        ticker = pos.ticker.upper()
        if ticker in seen or db.get(InstrumentMetadata, ticker):
            seen.add(ticker)
            continue
        seen.add(ticker)

        try:
            ficha = _get_ficha_tecnica(ticker)
            if not ficha:
                continue
            tem = _parse_tem_from_interes(ficha.get("interes", ""))
            emision = _parse_date(ficha.get("fechaEmision", ""))
            vto = _parse_date(ficha.get("fechaVencimiento", ""))
            currency = "USD" if pos.asset_type in ("BOND", "ON") else "ARS"
            db.merge(InstrumentMetadata(
                ticker=ticker,
                asset_type=pos.asset_type,
                tem=Decimal(str(tem)) if tem else None,
                emision_date=emision,
                maturity_date=vto,
                currency=currency,
                description=ficha.get("denominacion", pos.description or ""),
            ))
            saved += 1
        except Exception as e:
            logger.warning("backfill_metadata %s: %s", ticker, e)

    if saved:
        db.commit()
    logger.info("backfill_metadata_from_positions: %d tickers guardados", saved)
    return saved

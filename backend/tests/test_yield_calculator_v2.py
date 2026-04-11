"""
TDD — yield_calculator_v2.py

Casos cubiertos:
  1. Sin snapshots → retorna None (fallback al sistema actual)
  2. Snapshots sin value_ars/mep → usa value_usd (yield USD directo)
  3. Snapshots con value_ars/mep → yield USD real (captura devaluación)
  4. compute_lecap_tea: sin metadata → None; con metadata + precio → TEA correcta
  5. compute_bond_yield: < 7 días → None; con historia → retorno observado
  6. compute_fci_yield: 2 días VCP → TNA correcta
  7. Retorno fuera de rango → None (sanity check)
"""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
import pytest


# ── helpers para construir mocks ──────────────────────────────────────────────

def _snap(ticker, d, value_usd, value_ars=None, mep=None, asset_type="LETRA", source="IOL"):
    s = MagicMock()
    s.ticker = ticker
    s.snapshot_date = d
    s.value_usd = Decimal(str(value_usd))
    s.value_ars = Decimal(str(value_ars)) if value_ars else None
    s.mep = Decimal(str(mep)) if mep else None
    s.asset_type = asset_type
    s.source = source
    return s


def _price(ticker, d, vwap, mep=None):
    p = MagicMock()
    p.ticker = ticker
    p.price_date = d
    p.vwap = Decimal(str(vwap)) if vwap else None
    p.mep = Decimal(str(mep)) if mep else None
    p.prev_close = None
    return p


def _meta(ticker, asset_type, tem=None, emision=None, maturity=None, currency="ARS"):
    m = MagicMock()
    m.ticker = ticker
    m.asset_type = asset_type
    m.tem = Decimal(str(tem)) if tem else None
    m.emision_date = emision
    m.maturity_date = maturity
    m.currency = currency
    return m


def _make_db(snaps=None, prices=None, meta=None):
    db = MagicMock()
    q = MagicMock()
    db.query.return_value = q
    q.filter.return_value = q
    q.filter_by.return_value = q
    q.order_by.return_value = q
    q.limit.return_value = q
    q.all.return_value = snaps or []
    if prices is not None:
        q.first.return_value = prices[0] if prices else None
    db.get.return_value = meta
    return db


# ── 1. Sin snapshots → None ───────────────────────────────────────────────────

def test_position_actual_return_no_snaps():
    from app.services.yield_calculator_v2 import compute_position_actual_return
    db = _make_db(snaps=[])
    result, currency = compute_position_actual_return(db, "user1", "S31G6", "LETRA")
    assert result is None
    assert currency is None


def test_position_actual_return_one_snap():
    from app.services.yield_calculator_v2 import compute_position_actual_return
    today = date.today()
    db = _make_db(snaps=[_snap("S31G6", today, 50.0)])
    result, currency = compute_position_actual_return(db, "user1", "S31G6", "LETRA")
    assert result is None


# ── 2. Snapshots sin value_ars/mep → yield desde value_usd ──────────────────

def test_position_actual_return_usd_only():
    from app.services.yield_calculator_v2 import compute_position_actual_return
    today = date.today()
    d30 = today - timedelta(days=30)
    snaps = [
        _snap("AL30D", d30, 100.0, asset_type="BOND"),
        _snap("AL30D", today, 108.0, asset_type="BOND"),
    ]
    db = _make_db(snaps=snaps)
    result, currency = compute_position_actual_return(db, "user1", "AL30D", "BOND")
    assert result is not None
    assert currency == "USD"
    # 8% en 30 días ≈ 97% anual aprox
    assert 0.5 < float(result) < 2.0


# ── 3. Snapshots con value_ars/mep → yield USD real ─────────────────────────

def test_position_actual_return_ars_con_mep():
    """
    LECAP: rinde 3% ARS en 30 días, pero el MEP subió 2%.
    Yield USD real ≈ (1.03/1.02)^(365/30) - 1 ≈ 12% anual USD.
    """
    from app.services.yield_calculator_v2 import compute_position_actual_return
    today = date.today()
    d30 = today - timedelta(days=30)
    snaps = [
        _snap("S31G6", d30, 50.0, value_ars=70000.0, mep=1400.0, asset_type="LETRA"),
        _snap("S31G6", today, 51.5, value_ars=72100.0, mep=1428.0, asset_type="LETRA"),
    ]
    db = _make_db(snaps=snaps)
    result, currency = compute_position_actual_return(db, "user1", "S31G6", "LETRA")
    assert result is not None
    assert currency == "USD"
    # USD old = 70000/1400 = 50.0 ; USD new = 72100/1428 = 50.49
    # Retorno 30d: (50.49/50.0 - 1) * 365/30 ≈ 11.9%
    assert 0.05 < float(result) < 0.30


# ── 4. compute_lecap_tea ──────────────────────────────────────────────────────

def test_lecap_tea_sin_metadata():
    from app.services.yield_calculator_v2 import compute_lecap_tea
    db = _make_db(meta=None)
    result, currency = compute_lecap_tea("S31G6", date.today(), db)
    assert result is None


def test_lecap_tea_con_datos():
    """
    LECAP S31G6: TEM=2.6%, emision=2025-02-28, vto=2026-08-31 (142 días restantes al 11/04/26)
    VNV = 100 × (1.026)^18 ≈ 158.0 (acumulado a vencimiento)
    Para TEA ≈ 32%: precio ≈ 158 / (1.32^(142/365)) ≈ 143
    """
    from app.services.yield_calculator_v2 import compute_lecap_tea
    today = date(2026, 4, 11)
    emision = date(2025, 2, 28)
    maturity = date(2026, 8, 31)
    meta = _meta("S31G6", "LETRA", tem=0.026, emision=emision, maturity=maturity)

    db = MagicMock()
    db.get.return_value = meta
    price_row = _price("S31G6", today, 143.0)  # precio realista para TEA ~32%
    q = MagicMock()
    db.query.return_value = q
    q.filter.return_value = q
    q.order_by.return_value = q
    q.first.return_value = price_row

    result, currency = compute_lecap_tea("S31G6", today, db)
    assert result is not None
    assert currency == "ARS"
    # TEA entre 20% y 50% — rango razonable para LECAP argentina abril 2026
    assert 0.20 <= float(result) <= 0.50


# ── 5. compute_bond_yield ─────────────────────────────────────────────────────

def test_bond_yield_menos_de_7_dias():
    from app.services.yield_calculator_v2 import compute_bond_yield
    today = date.today()
    prices = [
        _price("AL30D", today - timedelta(days=3), 55000.0, mep=1400.0),
        _price("AL30D", today, 55500.0, mep=1420.0),
    ]
    db = MagicMock()
    db.get.return_value = None
    q = MagicMock()
    db.query.return_value = q
    q.filter.return_value = q
    q.order_by.return_value = q
    q.limit.return_value = q
    q.all.return_value = prices
    result, currency = compute_bond_yield("AL30D", db)
    assert result is None  # < 7 días → None


def test_bond_yield_con_historia():
    from app.services.yield_calculator_v2 import compute_bond_yield
    today = date.today()
    prices = [
        _price("AL30D", today - timedelta(days=30), 55000.0, mep=1400.0),
        _price("AL30D", today - timedelta(days=15), 56000.0, mep=1410.0),
        _price("AL30D", today, 57000.0, mep=1420.0),
    ]
    # Ordenados desc (más reciente primero, como retorna la query)
    prices_desc = list(reversed(prices))
    db = MagicMock()
    meta = _meta("AL30D", "BOND", currency="USD")
    db.get.return_value = meta
    q = MagicMock()
    db.query.return_value = q
    q.filter.return_value = q
    q.order_by.return_value = q
    q.limit.return_value = q
    q.all.return_value = prices_desc
    result, currency = compute_bond_yield("AL30D", db)
    assert result is not None
    assert currency == "USD"
    assert -0.3 <= float(result) <= 0.5


# ── 6. compute_fci_yield ──────────────────────────────────────────────────────

def test_fci_yield_con_vcp():
    """
    VCP sube de 1.000 a 1.030 en 30 días → TNA ≈ 36.5% anual
    """
    from app.services.yield_calculator_v2 import compute_fci_yield
    today = date.today()
    d30 = today - timedelta(days=30)
    prices = [
        _price("FCI:Cocos Pesos Plus", d30, 1000.0),
        _price("FCI:Cocos Pesos Plus", today, 1030.0),
    ]
    prices_desc = list(reversed(prices))
    db = MagicMock()
    q = MagicMock()
    db.query.return_value = q
    q.filter.return_value = q
    q.order_by.return_value = q
    q.limit.return_value = q
    q.all.return_value = prices_desc
    result, currency = compute_fci_yield("FCI:Cocos Pesos Plus", db)
    assert result is not None
    assert currency == "ARS"
    # (1.030/1.000 - 1) * 365/30 ≈ 0.365
    assert 0.30 <= float(result) <= 0.45


# ── 7. Sanity check — retorno fuera de rango → None ──────────────────────────

def test_position_actual_return_fuera_de_rango():
    """Value_usd baja 90% en 30 días — fuera del rango -50% anual → None"""
    from app.services.yield_calculator_v2 import compute_position_actual_return
    today = date.today()
    d30 = today - timedelta(days=30)
    snaps = [
        _snap("SCAM", d30, 1000.0, asset_type="BOND"),
        _snap("SCAM", today, 100.0, asset_type="BOND"),  # -90% en 30d → -99% anual
    ]
    db = _make_db(snaps=snaps)
    result, currency = compute_position_actual_return(db, "user1", "SCAM", "BOND")
    assert result is None

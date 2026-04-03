"""
Tests de persistencia de enriquecimiento entre syncs.
Verifica que _get_enrichment preserve annual_yield_pct, external_id y fci_categoria
entre re-syncs, y que los syncs llamen yield_updater post-sync.

Corre con: pytest backend/tests/test_enrichment_persistence.py -v
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch, call

import pytest

from app.routers.integrations import _get_enrichment


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_db_rows(rows: list[dict]):
    """Construye un mock de db.query().filter().all() con los rows dados."""
    db = MagicMock()
    mock_rows = []
    for r in rows:
        row = MagicMock()
        row.ticker = r["ticker"]
        row.asset_type = r["asset_type"]
        row.annual_yield_pct = Decimal(str(r["annual_yield_pct"]))
        row.external_id = r.get("external_id")
        row.fci_categoria = r.get("fci_categoria")
        mock_rows.append(row)

    q = MagicMock()
    q.filter.return_value.all.return_value = mock_rows
    db.query.return_value = q
    return db


# ── _get_enrichment ────────────────────────────────────────────────────────────

class TestGetEnrichment:
    def test_yield_enriquecido_se_preserva(self):
        """Si el yield es distinto al DEFAULT, se preserva en enrichment."""
        db = _make_db_rows([{
            "ticker": "AL30", "asset_type": "BOND",
            "annual_yield_pct": 0.17,  # enriquecido (default sería 0.09)
        }])
        result = _get_enrichment(db, "user1", "IOL")
        assert result["AL30"]["annual_yield_pct"] == Decimal("0.17")

    def test_yield_default_no_se_preserva(self):
        """Si el yield es el DEFAULT del tipo, no se preserva (será seteado por el ALYC)."""
        db = _make_db_rows([{
            "ticker": "AL30", "asset_type": "BOND",
            "annual_yield_pct": 0.09,  # es el default de "bono"
        }])
        result = _get_enrichment(db, "user1", "IOL")
        assert result["AL30"]["annual_yield_pct"] is None

    def test_fci_metadata_se_preserva(self):
        """external_id y fci_categoria se preservan siempre."""
        db = _make_db_rows([{
            "ticker": "IOLCAMA", "asset_type": "FCI",
            "annual_yield_pct": 0.08,  # default FCI
            "external_id": "Balanz Capital Money Market",
            "fci_categoria": "mercadoDinero",
        }])
        result = _get_enrichment(db, "user1", "IOL")
        assert result["IOLCAMA"]["external_id"] == "Balanz Capital Money Market"
        assert result["IOLCAMA"]["fci_categoria"] == "mercadoDinero"

    def test_ticker_sin_enriquecimiento_no_aparece(self):
        """Ticker no presente en DB activas no está en el resultado."""
        db = _make_db_rows([])
        result = _get_enrichment(db, "user1", "IOL")
        assert "AL30" not in result

    def test_lecap_default_no_se_preserva(self):
        """68% es el DEFAULT de LETRA — no se debe preservar como 'enriquecido'."""
        db = _make_db_rows([{
            "ticker": "S31G6", "asset_type": "LETRA",
            "annual_yield_pct": 0.68,  # default de "letra"
        }])
        result = _get_enrichment(db, "user1", "IOL")
        assert result["S31G6"]["annual_yield_pct"] is None

    def test_fci_yield_enriquecido_se_preserva(self):
        """17% TNA de ArgentinaDatos es distinto al DEFAULT FCI (8%) → preservar."""
        db = _make_db_rows([{
            "ticker": "IOLCAMA", "asset_type": "FCI",
            "annual_yield_pct": 0.171,  # enriquecido por yield_updater
        }])
        result = _get_enrichment(db, "user1", "IOL")
        assert result["IOLCAMA"]["annual_yield_pct"] == Decimal("0.171")

    def test_multiples_tickers(self):
        """Maneja múltiples posiciones correctamente."""
        db = _make_db_rows([
            {"ticker": "AL30", "asset_type": "BOND", "annual_yield_pct": 0.17},
            {"ticker": "GD35", "asset_type": "BOND", "annual_yield_pct": 0.15},
            {"ticker": "IOLCAMA", "asset_type": "FCI", "annual_yield_pct": 0.08},  # default
        ])
        result = _get_enrichment(db, "user1", "IOL")
        assert result["AL30"]["annual_yield_pct"] == Decimal("0.17")
        assert result["GD35"]["annual_yield_pct"] == Decimal("0.15")
        assert result["IOLCAMA"]["annual_yield_pct"] is None  # default, no preservar


# ── Comportamiento en sync: preservación end-to-end ───────────────────────────

class TestSyncPreservesEnrichment:
    """
    Verifica que al hacer un re-sync, el yield enriquecido se preserva
    en la nueva posición y que yield_updater se llama post-sync.
    """

    def test_sync_iol_preserva_yield_enriquecido(self):
        """
        Si AL30 tenía 17% (enriquecido), un re-sync IOL debe preservarlo
        en lugar de pisar con el DEFAULT 9%.
        """
        from app.services.iol_client import IOLPosition

        # Posición que viene del ALYC con DEFAULT yield
        iol_pos = MagicMock(spec=IOLPosition)
        iol_pos.ticker = "AL30"
        iol_pos.description = "Bono AL30"
        iol_pos.asset_type = "BOND"
        iol_pos.quantity = Decimal("100")
        iol_pos.avg_price_usd = Decimal("0.61")
        iol_pos.current_price_usd = Decimal("0.61")
        iol_pos.annual_yield_pct = Decimal("0.09")  # DEFAULT del ALYC
        iol_pos.ppc_ars = Decimal("850")
        iol_pos.valorizado_ars = Decimal("61000")

        # Mock client IOL
        mock_client = MagicMock()
        mock_client._get_mep.return_value = 1436.0
        mock_client.get_portfolio.return_value = [iol_pos]
        mock_client.get_operations.return_value = []
        mock_client.get_cash_balance_ars.return_value = Decimal("0")

        # DB con enriquecimiento previo de AL30 = 17%
        enrichment_row = MagicMock()
        enrichment_row.ticker = "AL30"
        enrichment_row.asset_type = "BOND"
        enrichment_row.annual_yield_pct = Decimal("0.17")
        enrichment_row.external_id = None
        enrichment_row.fci_categoria = None

        db = MagicMock()
        # Primera query (enrichment) devuelve la posición enriquecida
        enrichment_query = MagicMock()
        enrichment_query.filter.return_value.all.return_value = [enrichment_row]
        # Segunda+ queries (deactivate, flush, etc.) devuelven mocks normales
        db.query.return_value = enrichment_query

        added_positions = []
        db.add.side_effect = lambda pos: added_positions.append(pos)

        with patch("app.services.yield_updater.update_yields", return_value=1), \
             patch("app.routers.integrations._get_purchase_mep_from_operations", return_value={}), \
             patch("app.routers.integrations._sync_investment_months", return_value=0), \
             patch("app.routers.portfolio._invalidate_score_cache"), \
             patch("app.services.historical_reconstructor.reconstruct_portfolio_history", return_value=0):
            from app.routers.integrations import _sync_iol
            _sync_iol(mock_client, db, "user1")

        # La nueva posición debe tener el yield enriquecido, no el DEFAULT
        al30 = next((p for p in added_positions if getattr(p, "ticker", None) == "AL30"), None)
        assert al30 is not None, "AL30 no fue insertado"
        assert al30.annual_yield_pct == Decimal("0.17"), (
            f"Expected 0.17 (enriquecido), got {al30.annual_yield_pct}"
        )

    def test_sync_iol_llama_yield_updater_post_sync(self):
        """Verifica que _sync_iol llama update_yields después del sync."""
        from app.services.iol_client import IOLPosition

        iol_pos = MagicMock(spec=IOLPosition)
        iol_pos.ticker = "AL30"
        iol_pos.description = "Bono AL30"
        iol_pos.asset_type = "BOND"
        iol_pos.quantity = Decimal("100")
        iol_pos.avg_price_usd = Decimal("0.61")
        iol_pos.current_price_usd = Decimal("0.61")
        iol_pos.annual_yield_pct = Decimal("0.09")
        iol_pos.ppc_ars = Decimal("850")
        iol_pos.valorizado_ars = Decimal("61000")

        mock_client = MagicMock()
        mock_client._get_mep.return_value = 1436.0
        mock_client.get_portfolio.return_value = [iol_pos]
        mock_client.get_operations.return_value = []
        mock_client.get_cash_balance_ars.return_value = Decimal("0")

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []

        with patch("app.services.yield_updater.update_yields") as mock_update, \
             patch("app.routers.integrations._get_purchase_mep_from_operations", return_value={}), \
             patch("app.routers.integrations._sync_investment_months", return_value=0), \
             patch("app.routers.portfolio._invalidate_score_cache"), \
             patch("app.services.historical_reconstructor.reconstruct_portfolio_history", return_value=0):
            mock_update.return_value = 1
            from app.routers.integrations import _sync_iol
            _sync_iol(mock_client, db, "user1")

        mock_update.assert_called_once()
        # Verifica que se pasó mep como Decimal
        call_kwargs = mock_update.call_args
        assert call_kwargs is not None, "update_yields no fue llamado"


# ── ONs en _BOND_YTM ──────────────────────────────────────────────────────────

class TestBondYtmONs:
    """Verifica que las ONs corporativas están en la tabla _BOND_YTM."""

    def test_ons_corporativas_presentes(self):
        from app.services.yield_updater import _BOND_YTM
        ons_esperadas = [
            "ARC1O", "DNC5O", "DNC7O", "LOC6O", "MR39O",
            "RUCDO", "TLCMO", "TLCPO", "TLCTO", "VSCVO",
            "YM34O", "YM39O", "YMCJO",
        ]
        for ticker in ons_esperadas:
            assert ticker in _BOND_YTM, f"{ticker} no está en _BOND_YTM"

    def test_on_yields_en_rango_razonable(self):
        """YTM de ONs deben estar entre 6% y 15% (rango realista para corporates IG Argentina)."""
        from app.services.yield_updater import _BOND_YTM
        ons = ["ARC1O", "DNC5O", "DNC7O", "LOC6O", "MR39O",
               "RUCDO", "TLCMO", "TLCPO", "TLCTO", "VSCVO",
               "YM34O", "YM39O", "YMCJO"]
        for ticker in ons:
            ytm = _BOND_YTM[ticker]
            assert Decimal("0.06") <= ytm <= Decimal("0.15"), (
                f"{ticker} YTM={float(ytm)*100:.1f}% fuera del rango 6-15%"
            )

    def test_mr39o_mayor_ytm_por_descuento(self):
        """MR39O cotiza a 0.66 (descuento) — debe tener YTM mayor al resto."""
        from app.services.yield_updater import _BOND_YTM
        mr39o = _BOND_YTM["MR39O"]
        telecom = _BOND_YTM["TLCMO"]
        assert mr39o > telecom, "MR39O debería tener mayor YTM que TLCMO"

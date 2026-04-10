"""
Tests para services/mep.py — módulo transversal de tipo de cambio MEP.

Verifica: valor dolarapi, fallback 1430 en timeout/HTTP-error/JSON-malformado,
venta=0 → fallback, budget override, retorno siempre Decimal.

Corre con: pytest backend/tests/test_mep.py -v
"""
from decimal import Decimal
from unittest.mock import patch, MagicMock

import pytest

from app.services.mep import get_mep, MEP_FALLBACK


def _mock_http(json_data=None, status=200, raise_exc=None):
    resp = MagicMock()
    resp.status_code = status
    if raise_exc:
        resp.json.side_effect = raise_exc
    else:
        resp.json.return_value = json_data
    return resp


class TestGetMep:
    def test_retorna_venta_de_dolarapi(self):
        """Parsea el campo venta del JSON de dolarapi."""
        data = {"compra": 1400.0, "venta": 1450.0}
        with patch("httpx.get", return_value=_mock_http(data)):
            result = get_mep()
        assert result == Decimal("1450.0")

    def test_fallback_si_dolarapi_lanza_excepcion(self):
        """Timeout u otro error → retorna MEP_FALLBACK (1430)."""
        with patch("httpx.get", side_effect=Exception("timeout")):
            result = get_mep()
        assert result == MEP_FALLBACK

    def test_fallback_si_http_status_no_200(self):
        """HTTP 500 → retorna MEP_FALLBACK."""
        with patch("httpx.get", return_value=_mock_http(status=500)):
            result = get_mep()
        assert result == MEP_FALLBACK

    def test_fallback_si_json_sin_campo_venta(self):
        """JSON sin campo venta ni compra → retorna MEP_FALLBACK."""
        data = {"moneda": "USD", "nombre": "Bolsa"}
        with patch("httpx.get", return_value=_mock_http(data)):
            result = get_mep()
        assert result == MEP_FALLBACK

    def test_fallback_si_venta_es_cero(self):
        """venta=0 es falsy → usa compra si existe, o fallback."""
        data = {"compra": 0.0, "venta": 0.0}
        with patch("httpx.get", return_value=_mock_http(data)):
            result = get_mep()
        # venta=0 es falsy → compra=0 también es falsy → fallback
        assert result == MEP_FALLBACK

    def test_usa_compra_como_backup_si_venta_none(self):
        """Si venta es None pero compra > 0, usa compra."""
        data = {"compra": 1440.0, "venta": None}
        with patch("httpx.get", return_value=_mock_http(data)):
            result = get_mep()
        assert result == Decimal("1440.0")

    def test_budget_override_sin_http(self):
        """Si se pasa budget con fx_rate > 0, no llama a dolarapi."""
        budget = MagicMock()
        budget.fx_rate = 1380.0
        with patch("httpx.get") as mock_get:
            result = get_mep(budget=budget)
        assert result == Decimal("1380.0")
        mock_get.assert_not_called()

    def test_budget_con_fx_rate_cero_ignora_budget(self):
        """Budget con fx_rate=0 no se usa — sigue a dolarapi."""
        budget = MagicMock()
        budget.fx_rate = 0
        data = {"compra": 1400.0, "venta": 1450.0}
        with patch("httpx.get", return_value=_mock_http(data)):
            result = get_mep(budget=budget)
        assert result == Decimal("1450.0")

    def test_retorna_siempre_decimal(self):
        """El resultado es siempre Decimal, no float ni int."""
        data = {"compra": 1400.0, "venta": 1450.0}
        with patch("httpx.get", return_value=_mock_http(data)):
            result = get_mep()
        assert isinstance(result, Decimal)

    def test_fallback_nunca_cero(self):
        """MEP_FALLBACK es > 0 — garantía contra división por cero."""
        assert MEP_FALLBACK > 0

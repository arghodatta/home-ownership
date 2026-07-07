"""Unit tests for the ZIP estimation logic (no network)."""

from __future__ import annotations

from lib.estimate import ZipEstimate, _clean, fetch_zip_estimate


def _mk(**kw) -> ZipEstimate:
    base = dict(
        zip_code="60601",
        zcta_name="ZCTA5 60601",
        source="test",
        median_home_value=500_000.0,
        median_taxes=10_000.0,
        median_gross_rent=2_400.0,
    )
    base.update(kw)
    return ZipEstimate(**base)


def test_clean_rejects_census_null_sentinels():
    assert _clean("-666666666") is None
    assert _clean(-1) is None
    assert _clean("0") is None
    assert _clean(None) is None
    assert _clean("not-a-number") is None
    assert _clean("2400") == 2400.0


def test_property_tax_rate_is_taxes_over_value():
    est = _mk(median_taxes=10_000.0, median_home_value=500_000.0)
    assert est.property_tax_rate == 0.02


def test_estimated_params_includes_available_fields():
    est = _mk()
    params = est.estimated_params()
    assert params["property_tax_rate"] == 0.02
    assert params["monthly_rent"] == 2_400.0


def test_missing_fields_fall_back_to_none():
    est = _mk(median_taxes=None, median_gross_rent=None)
    assert est.property_tax_rate is None
    assert est.monthly_rent is None
    assert est.estimated_params() == {}


def test_invalid_zip_returns_none_without_network():
    assert fetch_zip_estimate("abc") is None
    assert fetch_zip_estimate("1234") is None
    assert fetch_zip_estimate("") is None


def test_no_api_key_returns_none(monkeypatch):
    monkeypatch.delenv("CENSUS_API_KEY", raising=False)
    assert fetch_zip_estimate("60601") is None

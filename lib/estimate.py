"""ZIP-code parameter estimation from trusted public data sources.

Given a ZIP code we look up locale-specific model inputs from an authoritative
source so users don't have to guess them. The only source wired up today is the
**U.S. Census Bureau American Community Survey (ACS) 5-Year Estimates**, keyed on
ZIP Code Tabulation Area (ZCTA). From it we derive:

  * ``property_tax_rate`` = median real-estate taxes / median home value
  * ``monthly_rent``      = median gross rent

Parameters that are national/macroeconomic in nature (mortgage rate, home
appreciation, market return, inflation) have no trustworthy *ZIP-level* source,
so they are intentionally left to the user.

The Census API is authoritative but requires a free API key
(https://api.census.gov/data/key_signup.html). Supply it via the
``CENSUS_API_KEY`` environment variable or Streamlit secrets. If no key is
configured, the ZCTA has no data, or the request fails, we return ``None`` for
the affected field(s) so the caller falls back to the user-supplied value.

This module is pure (stdlib only, no Streamlit) so it can be unit-tested and
cached at the app boundary.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

__all__ = ["ZipEstimate", "fetch_zip_estimate", "ACS_YEAR", "SOURCE"]

ACS_YEAR = 2023
_ACS_URL = f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5"
SOURCE = f"U.S. Census Bureau · ACS 5-Year Estimates ({ACS_YEAR})"

# ACS variables: median home value, median real-estate taxes, median gross rent.
_VARS = ("B25077_001E", "B25103_001E", "B25064_001E")

_ZIP_RE = re.compile(r"^\d{5}$")


def _clean(v) -> float | None:
    """Coerce a Census cell to a positive float, else None.

    Census encodes 'no data' as large negative sentinels (e.g. -666666666);
    any non-positive or unparseable value is treated as missing.
    """
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


@dataclass(frozen=True)
class ZipEstimate:
    """Locale estimates for one ZIP, plus provenance for display."""

    zip_code: str
    zcta_name: str
    source: str
    median_home_value: float | None
    median_taxes: float | None
    median_gross_rent: float | None

    @property
    def property_tax_rate(self) -> float | None:
        """Effective annual property-tax rate for the ZCTA, or None."""
        if self.median_taxes and self.median_home_value:
            return self.median_taxes / self.median_home_value
        return None

    @property
    def monthly_rent(self) -> float | None:
        """Median gross rent (already monthly), or None."""
        return self.median_gross_rent

    def estimated_params(self) -> dict[str, float]:
        """Map of ``Params`` attribute -> estimated value (only available ones)."""
        out: dict[str, float] = {}
        if (rate := self.property_tax_rate) is not None:
            out["property_tax_rate"] = rate
        if self.monthly_rent is not None:
            out["monthly_rent"] = self.monthly_rent
        return out


def fetch_zip_estimate(
    zip_code: str,
    api_key: str | None = None,
    timeout: float = 8.0,
) -> ZipEstimate | None:
    """Fetch ACS estimates for a ZIP, or None if unavailable.

    Returns None on invalid ZIP, missing API key, unknown ZCTA, or any network
    / parse error — the caller should then keep the user's own values.
    """
    zip_code = str(zip_code).strip()
    if not _ZIP_RE.match(zip_code):
        return None

    key = api_key or os.environ.get("CENSUS_API_KEY")
    if not key:
        # No trustworthy source available without a key -> defer to the user.
        return None

    query = urllib.parse.urlencode(
        {
            "get": "NAME," + ",".join(_VARS),
            "for": f"zip code tabulation area:{zip_code}",
            "key": key,
        }
    )
    url = f"{_ACS_URL}?{query}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            data = json.load(resp)
    except Exception:
        return None

    # Expected shape: [[header...], [values...]]. Unknown ZCTA -> no data row.
    if not isinstance(data, list) or len(data) < 2:
        return None
    header, row = data[0], data[1]
    rec = dict(zip(header, row))

    return ZipEstimate(
        zip_code=zip_code,
        zcta_name=rec.get("NAME") or f"ZCTA5 {zip_code}",
        source=SOURCE,
        median_home_value=_clean(rec.get("B25077_001E")),
        median_taxes=_clean(rec.get("B25103_001E")),
        median_gross_rent=_clean(rec.get("B25064_001E")),
    )

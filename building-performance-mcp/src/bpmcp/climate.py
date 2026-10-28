"""Climate data: load EPW weather files and summarise them for design decisions."""

from __future__ import annotations

import io
import os
import re
import urllib.request
import zipfile
from pathlib import Path

from ladybug.epw import EPW

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

INDIA_ZONES = ("composite", "hot_dry", "warm_humid", "temperate", "cold")


def cache_dir() -> Path:
    """Folder used for downloaded weather files and saved models."""
    path = Path(os.environ.get("BPMCP_HOME", Path.home() / ".bpmcp"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(name)) or "weather.epw"


def load_epw(source: str) -> EPW:
    """Load an EPW from a local .epw/.zip path or an http(s) URL to either."""
    source = source.strip()
    if source.lower().startswith(("http://", "https://")):
        epw_dir = cache_dir() / "epw"
        epw_dir.mkdir(exist_ok=True)
        target = epw_dir / _safe_name(source.split("?")[0])
        if not target.exists():
            with urllib.request.urlopen(source, timeout=60) as resp:
                target.write_bytes(resp.read())
        path = target
    else:
        path = Path(source).expanduser()
        if not path.exists():
            raise ValueError(f"Weather file not found: {path}")

    if path.suffix.lower() == ".zip":
        path = _extract_epw(path)
    if path.suffix.lower() != ".epw":
        raise ValueError("Expected an .epw file (or a .zip containing one).")
    return EPW(str(path))


def _extract_epw(zip_path: Path) -> Path:
    with zipfile.ZipFile(zip_path) as zf:
        members = [m for m in zf.namelist() if m.lower().endswith(".epw")]
        if not members:
            raise ValueError(f"No .epw file inside {zip_path.name}")
        target = zip_path.with_name(_safe_name(members[0]))
        if not target.exists():
            target.write_bytes(zf.read(members[0]))
    return target


def _daily(values, datetimes):
    """Group hourly values into {(month, day): [values]} preserving order."""
    days: dict[tuple[int, int], list[float]] = {}
    for val, dt in zip(values, datetimes):
        days.setdefault((dt.month, dt.day), []).append(val)
    return days


def degree_days(epw: EPW) -> dict[str, float]:
    """Heating/cooling degree days (degC-days) from daily mean temperature."""
    temps = epw.dry_bulb_temperature
    days = _daily(temps.values, temps.datetimes)
    means = [sum(v) / len(v) for v in days.values()]
    return {
        "HDD18": round(sum(max(0.0, 18 - t) for t in means)),
        "CDD18": round(sum(max(0.0, t - 18) for t in means)),
        "CDD10": round(sum(max(0.0, t - 10) for t in means)),
    }


def monthly_stats(epw: EPW) -> list[dict]:
    temps = epw.dry_bulb_temperature
    rh = epw.relative_humidity.values
    ghi = epw.global_horizontal_radiation.values
    days = _daily(temps.values, temps.datetimes)

    rows = []
    for m in range(1, 13):
        month_days = [v for (mo, _), v in days.items() if mo == m]
        idx = [i for i, dt in enumerate(temps.datetimes) if dt.month == m]
        rows.append({
            "month": MONTHS[m - 1],
            "mean_daily_max_C": round(sum(max(d) for d in month_days) / len(month_days), 1),
            "mean_daily_min_C": round(sum(min(d) for d in month_days) / len(month_days), 1),
            "mean_C": round(sum(temps.values[i] for i in idx) / len(idx), 1),
            "mean_rh_pct": round(sum(rh[i] for i in idx) / len(idx), 1),
            "solar_ghi_kwh_m2": round(sum(ghi[i] for i in idx) / 1000, 1),
        })
    return rows


def classify_month_india(mean_max_c: float, mean_rh: float) -> str:
    """NBC 2016 / ECBC climate criteria applied to one month."""
    if mean_max_c > 30:
        return "hot_dry" if mean_rh < 55 else "warm_humid"
    if mean_max_c >= 25:
        return "warm_humid" if mean_rh > 75 else "temperate"
    return "cold"


def classify_india_climate(monthly: list[dict]) -> dict:
    """Indian climate zone: a category holding 6+ months wins, otherwise composite."""
    cats = [classify_month_india(r["mean_daily_max_C"], r["mean_rh_pct"]) for r in monthly]
    counts = {z: cats.count(z) for z in INDIA_ZONES if z != "composite"}
    best = max(counts, key=counts.get)
    tied = [z for z, c in counts.items() if c == counts[best]]
    zone = best if counts[best] >= 6 and len(tied) == 1 else "composite"
    return {
        "zone": zone,
        "month_categories": dict(zip(MONTHS, cats)),
        "method": "NBC 2016 criteria (mean monthly max temperature and mean RH); "
                  "6+ months in one category sets the zone, otherwise composite. "
                  "The official ECBC zone for a city comes from the ECBC climate map - "
                  "override it if they differ.",
    }


def climate_summary(epw: EPW) -> dict:
    loc = epw.location
    monthly = monthly_stats(epw)
    temps = epw.dry_bulb_temperature.values
    rh = epw.relative_humidity.values
    return {
        "location": {
            "city": loc.city, "state": loc.state, "country": loc.country,
            "latitude": loc.latitude, "longitude": loc.longitude,
            "time_zone": loc.time_zone, "elevation_m": loc.elevation,
            "source": loc.source,
        },
        "annual": {
            "mean_temp_C": round(sum(temps) / len(temps), 1),
            "max_temp_C": round(max(temps), 1),
            "min_temp_C": round(min(temps), 1),
            "mean_rh_pct": round(sum(rh) / len(rh), 1),
            "solar_ghi_kwh_m2": round(sum(epw.global_horizontal_radiation.values) / 1000),
            **degree_days(epw),
        },
        "india_climate_zone": classify_india_climate(monthly),
        "ashrae_climate_zone": {
            "zone": epw.ashrae_climate_zone,
            "note": "Estimated from temperature. EPW precipitation is unreliable, so dry "
                    "'B' zones show as 'A'; this does not change envelope limits in zones 0-3.",
        },
        "monthly": monthly,
    }

"""Prescriptive envelope and lighting-power checks against ECBC 2017, ENS 2018 and ASHRAE 90.1-2019."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib import resources

U_IP_TO_SI = 5.678263   # Btu/h.ft2.F -> W/m2K
LPD_IP_TO_SI = 10.7639  # W/ft2 -> W/m2

CODE_ALIASES = {
    "ecbc": "ECBC2017", "ecbc2017": "ECBC2017",
    "ens": "ENS2018", "ens2018": "ENS2018", "eco-niwas": "ENS2018", "econiwas": "ENS2018",
    "ashrae": "ASHRAE90.1-2019", "90.1": "ASHRAE90.1-2019", "ashrae90.1": "ASHRAE90.1-2019",
    "ashrae90.1-2019": "ASHRAE90.1-2019", "asharae": "ASHRAE90.1-2019",
}


@lru_cache(maxsize=1)
def load_limits() -> dict:
    text = resources.files("bpmcp").joinpath("data/code_limits.json").read_text(encoding="utf-8")
    return json.loads(text)


def resolve_code(code: str) -> str:
    key = code.strip().lower().replace(" ", "")
    if key in CODE_ALIASES:
        return CODE_ALIASES[key]
    for name in load_limits():
        if name.lower() == key:
            return name
    raise ValueError(f"Unknown code '{code}'. Use one of: ECBC2017, ENS2018, ASHRAE90.1-2019.")


def code_limits(code: str) -> dict:
    name = resolve_code(code)
    return {"code": name, **load_limits()[name]}


def _zone(code: str, zone: str | None) -> str:
    if zone is None:
        raise ValueError("climate_zone is required (or link the model to a loaded climate).")
    zones = load_limits()[code]["climate_zones"]
    z = re.sub(r"[^a-z0-9]+", "_", zone.strip().lower()).strip("_")
    z = z.replace("hot_and_dry", "hot_dry").replace("warm_and_humid", "warm_humid")
    if z == "moderate":
        z = "temperate"
    if code.startswith("ASHRAE"):
        z = z.rstrip("abc")
    if z not in zones:
        raise ValueError(f"Climate zone '{zone}' not covered by {code}; expected one of {zones}.")
    return z


def _level(code: str, level: str | None) -> str:
    levels = load_limits()[code]["levels"]
    if level is None:
        return levels[0]
    for lv in levels:
        if lv.lower().replace(" ", "") == level.lower().replace(" ", ""):
            return lv
    raise ValueError(f"Level '{level}' not valid for {code}; expected one of {levels}.")


def _row(check: str, value, limit, rule: str, status: str, note: str = "") -> dict:
    if value is None:
        result = "missing input"
    elif rule == "<=":
        result = "pass" if value <= limit + 1e-9 else "fail"
    else:
        result = "pass" if value >= limit - 1e-9 else "fail"
    return {"check": check, "value": None if value is None else round(value, 3),
            "limit": round(limit, 3), "rule": f"value {rule} limit",
            "result": result, "table_status": status, "note": note}


def _is_north(azimuth: float, tolerance: float) -> bool:
    return abs((azimuth + 180) % 360 - 180) <= tolerance


def check_envelope(model: dict, code: str, climate_zone: str | None, level: str | None = None,
                   latitude: float | None = None, wall_type: str = "mass",
                   window_type: str = "fixed") -> dict:
    """Run prescriptive envelope checks on a model summary (BuildingModel.summary())."""
    code = resolve_code(code)
    zone = _zone(code, climate_zone)
    level = _level(code, level)
    t = load_limits()[code]
    env = model["envelope"]
    checks: list[dict] = []
    warnings: list[str] = []

    if code == "ECBC2017":
        checks.append(_row("Overall window-to-wall ratio", model["overall_wwr"],
                           t["max_wwr"]["value"], "<=", t["max_wwr"]["status"], t["max_wwr"]["note"]))
        checks.append(_row("Skylight-to-roof ratio", model["skylight_roof_ratio"],
                           t["max_srr"]["value"], "<=", t["max_srr"]["status"]))
        checks.append(_row(f"Roof U-value ({level})", env["roof_u"], t["roof_u"]["values"][level][zone],
                           "<=", t["roof_u"]["status"], t["roof_u"]["note"]))
        checks.append(_row(f"Wall U-value ({level})", env["wall_u"], t["wall_u"]["values"][level][zone],
                           "<=", t["wall_u"]["status"], t["wall_u"]["note"]))
        checks.append(_row("Window U-value", env["window_u"], t["window_u"]["values"][zone],
                           "<=", t["window_u"]["status"], t["window_u"]["note"]))

        shgc = t["window_shgc"]
        glazed = [w for w in model["walls"] if w["window_area_m2"] > 0]
        north_ok = latitude is not None and latitude >= shgc["north_min_latitude"]
        if latitude is None:
            warnings.append("Latitude unknown: north-facing SHGC relaxation not applied.")
        north = [w for w in glazed if north_ok and _is_north(w["azimuth_deg"], shgc["north_tolerance_deg"])]
        other = [w for w in glazed if w not in north]
        if other:
            checks.append(_row("Window SHGC (non-north glazing)", env["window_shgc"],
                               shgc["non_north"][zone], "<=", shgc["status"], shgc["note"]))
        if north:
            checks.append(_row("Window SHGC (north glazing)", env["window_shgc"],
                               shgc["north"][zone], "<=", shgc["status"], shgc["note"]))

        bands = t["min_vlt_by_wwr"]
        band = next((b for b in bands["bands"] if model["overall_wwr"] <= b[0] + 1e-9), None)
        if band:
            checks.append(_row(f"Window VLT (WWR up to {band[0]:.0%})", env["window_vlt"], band[1],
                               ">=", bands["status"], bands["note"]))

    elif code == "ENS2018":
        checks.append(_row("Roof U-value", env["roof_u"], t["roof_u"]["values"][level][zone],
                           "<=", t["roof_u"]["status"], t["roof_u"]["note"]))
        wfr = t["min_openable_wfr"]
        checks.append(_row("Openable window-to-floor ratio", model["openable_window_to_floor_ratio"],
                           wfr["values"][zone], ">=", wfr["status"], wfr["note"]))
        warnings.append(t["_not_yet_implemented"])

    else:  # ASHRAE 90.1-2019
        if wall_type not in ("mass", "steel_framed"):
            raise ValueError("wall_type must be 'mass' or 'steel_framed'.")
        if window_type not in ("fixed", "operable"):
            raise ValueError("window_type must be 'fixed' or 'operable'.")
        checks.append(_row("Overall window-to-wall ratio", model["overall_wwr"],
                           t["max_wwr"]["value"], "<=", t["max_wwr"]["status"]))
        checks.append(_row("Skylight-to-roof ratio", model["skylight_roof_ratio"],
                           t["max_srr"]["value"], "<=", t["max_srr"]["status"]))
        checks.append(_row("Roof U-value (insulation above deck)", env["roof_u"],
                           t["roof_u_ip"]["values"][zone] * U_IP_TO_SI, "<=", t["roof_u_ip"]["status"]))
        checks.append(_row(f"Wall U-value ({wall_type})", env["wall_u"],
                           t["wall_u_ip"][wall_type][zone] * U_IP_TO_SI, "<=", t["wall_u_ip"]["status"]))
        checks.append(_row(f"Window U-value ({window_type})", env["window_u"],
                           t["window_u_ip"][window_type][zone] * U_IP_TO_SI, "<=",
                           t["window_u_ip"]["status"]))
        checks.append(_row("Window SHGC", env["window_shgc"], t["window_shgc"]["values"][zone],
                           "<=", t["window_shgc"]["status"]))

    unverified = sorted({c["check"] for c in checks if not c["table_status"].startswith("verified")
                         or (c["table_status"] == "verified for ECBC level only" and level != "ECBC")})
    if unverified:
        warnings.append("Limits for these checks are not yet verified against the official code text "
                        "- confirm before using for compliance: " + "; ".join(unverified))

    tally = {r: sum(c["result"] == r for c in checks) for r in ("pass", "fail", "missing input")}
    return {"code": code, "title": t["title"], "level": level, "climate_zone": zone,
            "checks": checks, "summary": tally, "warnings": warnings,
            "disclaimer": "Prescriptive screening only - not a compliance submission."}


def check_lpd(code: str, building_type: str, area_m2: float, installed_watts: float | None = None,
              lpd: float | None = None, level: str | None = None) -> dict:
    """Compare lighting power density with the building-area-method allowance."""
    code = resolve_code(code)
    if code == "ENS2018":
        raise ValueError("ENS 2018 has no lighting power limit; use ECBC2017 or ASHRAE90.1-2019.")
    if area_m2 <= 0:
        raise ValueError("area_m2 must be positive.")
    t = load_limits()[code]
    btype = building_type.strip().lower()
    if code == "ECBC2017":
        level = _level(code, level)
        table = t["lpd"]
        if btype not in table["values"]:
            raise ValueError(f"No ECBC LPD entry for '{building_type}'. Available: {list(table['values'])}. "
                             "Add it to data/code_limits.json.")
        allowed = table["values"][btype][level]
    else:
        level = _level(code, level)
        table = t["lpd_ip"]
        if btype not in table["values"]:
            raise ValueError(f"No ASHRAE LPD entry for '{building_type}'. Available: {list(table['values'])}.")
        allowed = table["values"][btype] * LPD_IP_TO_SI

    if lpd is None and installed_watts is not None:
        lpd = installed_watts / area_m2
    row = _row(f"Lighting power density ({building_type}, {level})", lpd, allowed, "<=", table["status"],
               table["note"])
    return {"code": code, "level": level, "area_m2": area_m2,
            "allowed_lpd_w_m2": round(allowed, 2),
            "allowed_total_w": round(allowed * area_m2),
            "installed_lpd_w_m2": None if lpd is None else round(lpd, 2),
            "check": row,
            "warnings": [] if table["status"] == "verified" else
            ["LPD limit not yet verified against the official code text - confirm before relying on it."]}

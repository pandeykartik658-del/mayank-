"""Sun position, shading-device sizing and solar radiation on facades."""

from __future__ import annotations

import math

from ladybug.epw import EPW
from ladybug.sunpath import Sunpath
from ladybug.wea import Wea

COMPASS_8 = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}


def sun_position(latitude: float, longitude: float, time_zone: float,
                 month: int, day: int, hour: float) -> dict:
    """Sun altitude/azimuth (degrees, azimuth clockwise from true north) at local standard time."""
    sun = Sunpath(latitude, longitude, time_zone).calculate_sun(month, day, hour)
    alt, az = sun.altitude, sun.azimuth
    up = alt > 0
    return {
        "month": month, "day": day, "hour": hour,
        "altitude_deg": round(alt, 1),
        "azimuth_deg": round(az, 1),
        "sun_up": up,
        # Length of the shadow cast by a 1 m tall vertical object.
        "shadow_length_per_m_height": round(1 / math.tan(math.radians(alt)), 2) if up else None,
    }


def shading_angles(altitude: float, azimuth: float, facade_azimuth: float) -> dict:
    """Horizontal and vertical shadow angles of the sun relative to a facade.

    Returns hsa/vsa in degrees, and whether the sun is on the facade at all.
    """
    hsa = (azimuth - facade_azimuth + 180) % 360 - 180
    on_facade = altitude > 0 and abs(hsa) < 90
    vsa = None
    if on_facade:
        vsa = math.degrees(math.atan(math.tan(math.radians(altitude)) / math.cos(math.radians(hsa))))
    return {"hsa_deg": round(hsa, 1), "vsa_deg": round(vsa, 1) if vsa is not None else None,
            "sun_on_facade": on_facade}


def overhang_depth(window_height: float, vsa_deg: float) -> float:
    """Horizontal overhang depth (at window head) that fully shades the window."""
    if vsa_deg >= 89.9:
        return 0.0
    return window_height / math.tan(math.radians(vsa_deg))


def fin_depth(window_width: float, hsa_deg: float) -> float | None:
    """Vertical fin depth (fins at both jambs) that fully shades the window; None if sun is head-on."""
    if abs(hsa_deg) < 0.5:
        return None
    return window_width / math.tan(math.radians(abs(hsa_deg)))


def _depth_for_coverage(depths: list[float | None], fraction: float) -> float | None:
    """Smallest depth that fully shades at least `fraction` of the sunlit instances."""
    if not depths:
        return 0.0
    finite = sorted(d for d in depths if d is not None)
    need = math.ceil(fraction * len(depths))
    if need > len(finite):
        return None  # head-on sun in too many hours for this device to cover
    return round(finite[need - 1], 2) if need else 0.0


def shading_design(latitude: float, longitude: float, time_zone: float,
                   facade_azimuth: float, window_height: float, window_width: float,
                   months: list[int] | None = None, hours: list[int] | None = None) -> dict:
    """Size overhangs and fins for a facade over the chosen months/hours (21st of each month)."""
    months = months or list(range(3, 11))
    hours = hours or list(range(8, 18))
    sp = Sunpath(latitude, longitude, time_zone)

    rows, over, fins = [], [], []
    for m in months:
        for h in hours:
            sun = sp.calculate_sun(m, 21, h)
            ang = shading_angles(sun.altitude, sun.azimuth, facade_azimuth)
            if not ang["sun_on_facade"]:
                continue
            o = overhang_depth(window_height, ang["vsa_deg"])
            f = fin_depth(window_width, ang["hsa_deg"])
            over.append(o)
            fins.append(f)
            rows.append({"month": m, "day": 21, "hour": h,
                         "altitude_deg": round(sun.altitude, 1), "azimuth_deg": round(sun.azimuth, 1),
                         **ang,
                         "overhang_depth_m": round(o, 2),
                         "fin_depth_m": round(f, 2) if f is not None else None})

    coverage = {}
    for label, frac in (("100%", 1.0), ("90%", 0.9), ("75%", 0.75)):
        coverage[label] = {"overhang_depth_m": _depth_for_coverage(over, frac),
                           "fin_depth_m": _depth_for_coverage(fins, frac)}

    advice = "No direct sun reaches this facade in the selected period."
    if rows:
        full_overhang = coverage["100%"]["overhang_depth_m"]
        if full_overhang is not None and full_overhang <= 0.6 * window_height:
            advice = "A horizontal overhang works well here (high sun on this facade)."
        elif coverage["90%"]["fin_depth_m"] is not None and \
                coverage["90%"]["fin_depth_m"] <= window_width:
            advice = "Low or oblique sun: vertical fins (or fins + overhang) are more effective than a deep overhang."
        else:
            advice = ("Low sun hits this facade nearly head-on (typical of east/west). Use external "
                      "louvres, screens/jaali, a low-SHGC glass, or reduce glazing on this side.")

    return {
        "facade_azimuth_deg": facade_azimuth,
        "window_height_m": window_height, "window_width_m": window_width,
        "months": months, "hours": hours,
        "sunlit_instances": len(rows),
        "depth_needed_to_fully_shade": coverage,
        "advice": advice,
        "hourly": rows,
        "note": "Depths assume the device is flush with the window head (overhang) or jambs "
                "(fins) and the 21st day of each month. Times are local standard time.",
    }


def facade_radiation(epw: EPW, months: list[int] | None = None,
                     ground_reflectance: float = 0.2) -> dict:
    """Total solar radiation (kWh/m2) on vertical facades in 8 directions and on the roof."""
    wea = Wea.from_epw_file(epw.file_path)
    months_set = set(months or range(1, 13))

    def total(alt: float, az: float) -> float:
        coll = wea.directional_irradiance(alt, az, ground_reflectance)[0]
        return sum(v for v, dt in zip(coll.values, coll.datetimes) if dt.month in months_set) / 1000

    results = {name: round(total(0, az)) for name, az in COMPASS_8.items()}
    roof = round(total(90, 180))
    worst = max(results, key=results.get)
    least = min(results, key=results.get)
    return {
        "months": sorted(months_set),
        "unit": "kWh/m2 over the period",
        "facades": results,
        "roof": roof,
        "highest_facade": worst,
        "lowest_facade": least,
        "ratio_highest_to_lowest": round(results[worst] / results[least], 2) if results[least] else None,
    }

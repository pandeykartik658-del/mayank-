"""Quick daylight estimates for side-lit rooms (BRE / BS 8206-2 style formulas)."""

from __future__ import annotations


def average_daylight_factor(room_depth: float, room_width: float, room_height: float,
                            glazed_area: float, vlt: float, sky_angle_deg: float = 90.0,
                            maintenance_factor: float = 0.9,
                            reflectance_ceiling: float = 0.7, reflectance_walls: float = 0.5,
                            reflectance_floor: float = 0.2) -> dict:
    """Average daylight factor  DF = T * Aw * theta * M / (A * (1 - R^2)).

    T: glass visible transmittance, Aw: net glazed area, theta: visible sky angle in
    degrees from the window centre (90 = unobstructed), M: dirt/maintenance factor,
    A: total internal surface area, R: area-weighted mean internal reflectance.
    """
    if min(room_depth, room_width, room_height) <= 0:
        raise ValueError("Room dimensions must be positive.")
    if not 0 < vlt <= 1:
        raise ValueError("vlt must be between 0 and 1.")
    floor = room_depth * room_width
    walls = 2 * (room_depth + room_width) * room_height
    if glazed_area <= 0 or glazed_area > walls:
        raise ValueError("glazed_area must be positive and smaller than the wall area.")
    total = 2 * floor + walls
    glass_reflectance = 0.1
    r = (floor * reflectance_ceiling + floor * reflectance_floor
         + (walls - glazed_area) * reflectance_walls + glazed_area * glass_reflectance) / total
    df = vlt * glazed_area * sky_angle_deg * maintenance_factor / (total * (1 - r ** 2))

    if df >= 5:
        rating = "Well daylit - electric light rarely needed by day; check glare and solar heat gain."
    elif df >= 2:
        rating = "Adequately daylit - supplementary electric light at times."
    else:
        rating = "Gloomy - electric lighting needed most of the day."
    return {"average_daylight_factor_pct": round(df, 2),
            "mean_reflectance": round(r, 3),
            "internal_surface_area_m2": round(total, 1),
            "window_to_floor_ratio": round(glazed_area / floor, 3),
            "rating": rating,
            "note": "Room-average estimate for side-lit rooms; use Radiance (Phase 3) for grids, "
                    "sDA/ASE and complex shading."}


def limiting_depth(room_depth: float, room_width: float, window_head_height: float,
                   rear_reflectance: float = 0.5) -> dict:
    """BRE limiting-depth rule for one window wall: D/W + D/H <= 2 / (1 - Rb)."""
    if min(room_depth, room_width, window_head_height) <= 0:
        raise ValueError("Dimensions must be positive.")
    if not 0 <= rear_reflectance < 1:
        raise ValueError("rear_reflectance must be between 0 and 1.")
    limit = 2 / (1 - rear_reflectance)
    value = room_depth / room_width + room_depth / window_head_height
    max_depth = limit / (1 / room_width + 1 / window_head_height)
    return {"value": round(value, 2), "limit": round(limit, 2), "pass": value <= limit,
            "max_room_depth_m": round(max_depth, 2),
            "advice": "Room is shallow enough for daylight to reach the back." if value <= limit else
            f"Back of the room will look gloomy - keep depth under {max_depth:.1f} m, raise the "
            "window head, add a second window wall or use lighter interior finishes."}

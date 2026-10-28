"""Electric lighting: lumen-method fixture count, layout and lighting power density."""

from __future__ import annotations

import math

# Generic utilisation factors for a recessed direct LED panel with reflectances
# ceiling 0.7 / walls 0.5 / floor 0.2, by room index. Replace with the
# manufacturer's UF table for real projects.
GENERIC_UF = [(0.6, 0.45), (0.8, 0.53), (1.0, 0.59), (1.25, 0.65), (1.5, 0.69),
              (2.0, 0.75), (2.5, 0.79), (3.0, 0.82), (4.0, 0.85), (5.0, 0.87)]


def room_index(length: float, width: float, mounting_height: float) -> float:
    """K = L*W / (Hm*(L+W)), Hm = luminaire height above the working plane."""
    return length * width / (mounting_height * (length + width))


def generic_uf(k: float) -> float:
    if k <= GENERIC_UF[0][0]:
        return GENERIC_UF[0][1]
    for (k1, u1), (k2, u2) in zip(GENERIC_UF, GENERIC_UF[1:]):
        if k <= k2:
            return u1 + (u2 - u1) * (k - k1) / (k2 - k1)
    return GENERIC_UF[-1][1]


def _grid(n: int, length: float, width: float) -> tuple[int, int]:
    """Columns along length x rows along width, roughly square spacing, cols*rows >= n."""
    best = None
    for rows in range(1, n + 1):
        cols = math.ceil(n / rows)
        spacing_ratio = (length / cols) / (width / rows)
        score = (cols * rows - n, abs(math.log(spacing_ratio)))
        if best is None or score < best[0]:
            best = (score, cols, rows)
    return best[1], best[2]


def lumen_method(length: float, width: float, ceiling_height: float, target_lux: float,
                 lumens_per_fixture: float, watts_per_fixture: float,
                 workplane_height: float = 0.75, suspension: float = 0.0,
                 maintenance_factor: float = 0.8, utilisation_factor: float | None = None) -> dict:
    """Number of luminaires N = E*A / (lumens * UF * MF) with a regular grid layout."""
    for name, val in (("length", length), ("width", width), ("target_lux", target_lux),
                      ("lumens_per_fixture", lumens_per_fixture), ("watts_per_fixture", watts_per_fixture)):
        if val <= 0:
            raise ValueError(f"{name} must be positive.")
    hm = ceiling_height - suspension - workplane_height
    if hm <= 0:
        raise ValueError("Luminaires must be above the working plane.")

    area = length * width
    k = room_index(length, width, hm)
    uf_source = "given"
    if utilisation_factor is None:
        utilisation_factor = generic_uf(k)
        uf_source = "generic table (direct LED panel, 70/50/20 reflectances) - use the manufacturer's UF"

    exact = target_lux * area / (lumens_per_fixture * utilisation_factor * maintenance_factor)
    n = max(1, math.ceil(exact))
    cols, rows = _grid(n, length, width)
    n_layout = cols * rows
    achieved = n_layout * lumens_per_fixture * utilisation_factor * maintenance_factor / area
    sx, sy = length / cols, width / rows
    shr = max(sx, sy) / hm

    notes = []
    if shr > 1.5:
        notes.append(f"Spacing-to-height ratio {shr:.2f} is high (> 1.5): check uniformity "
                     "against the luminaire's maximum SHR or add fittings.")
    if n_layout > n:
        notes.append(f"Grid rounded up from {n} to {n_layout} fittings for a regular layout.")

    return {
        "room": {"length_m": length, "width_m": width, "area_m2": round(area, 1),
                 "mounting_height_above_workplane_m": round(hm, 2), "room_index": round(k, 2)},
        "utilisation_factor": round(utilisation_factor, 2), "uf_source": uf_source,
        "maintenance_factor": maintenance_factor,
        "fixtures_required": n,
        "layout": {"columns_along_length": cols, "rows_along_width": rows,
                   "fixtures": n_layout,
                   "spacing_along_length_m": round(sx, 2), "spacing_along_width_m": round(sy, 2),
                   "edge_offset_along_length_m": round(sx / 2, 2),
                   "edge_offset_along_width_m": round(sy / 2, 2),
                   "spacing_to_height_ratio": round(shr, 2)},
        "maintained_illuminance_lux": round(achieved),
        "installed_watts": round(n_layout * watts_per_fixture, 1),
        "lpd_w_m2": round(n_layout * watts_per_fixture / area, 2),
        "notes": notes,
    }

"""Simple massing model built from a plan footprint - enough for envelope checks."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

COMPASS_8 = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
COMPASS_AZIMUTH = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}


def compass_label(azimuth: float) -> str:
    return COMPASS_8[int(((azimuth % 360) + 22.5) // 45) % 8]


def _angle_diff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


@dataclass
class BuildingModel:
    """A prismatic building: footprint extruded by floors x floor_height.

    footprint: plan vertices in metres (x to the right, y up the drawing).
    plan_up_azimuth: true-north azimuth the drawing's "up" points to (0 = up is north,
        90 = up is east). Lets Claude use coordinates read straight off a sketch.
    wwr: window-to-wall ratio, either {"all": 0.4} or per direction such as
        {"N": 0.3, "S": 0.2, "E": 0.15, "W": 0.15} (4 or 8 compass keys).
    """

    name: str
    footprint: list[tuple[float, float]]
    floors: int = 1
    floor_height: float = 3.0
    plan_up_azimuth: float = 0.0
    wwr: dict[str, float] = field(default_factory=lambda: {"all": 0.4})
    building_type: str = "office"
    wall_u: float | None = None
    roof_u: float | None = None
    window_u: float | None = None
    window_shgc: float | None = None
    window_vlt: float | None = None
    openable_fraction: float = 0.5
    skylight_area: float = 0.0
    climate_id: str | None = None

    def __post_init__(self):
        self.footprint = [(float(x), float(y)) for x, y in self.footprint]
        if len(self.footprint) < 3:
            raise ValueError("Footprint needs at least 3 vertices.")
        if abs(_signed_area(self.footprint)) < 1e-6:
            raise ValueError("Footprint has zero area.")
        if _signed_area(self.footprint) < 0:  # store counter-clockwise
            self.footprint = self.footprint[::-1]
        if self.floors < 1 or self.floor_height <= 0:
            raise ValueError("floors must be >= 1 and floor_height > 0.")
        bad = [k for k in self.wwr if k != "all" and k not in COMPASS_AZIMUTH]
        if bad:
            raise ValueError(f"Unknown wwr keys {bad}; use 'all' or compass keys {COMPASS_8}.")
        if any(not 0 <= v <= 0.95 for v in self.wwr.values()):
            raise ValueError("wwr values must be between 0 and 0.95.")

    @classmethod
    def rectangle(cls, name: str, width: float, depth: float, **kwargs) -> "BuildingModel":
        return cls(name=name, footprint=[(0, 0), (width, 0), (width, depth), (0, depth)], **kwargs)

    def _wwr_for(self, azimuth: float) -> float:
        keys = [k for k in self.wwr if k != "all"]
        if not keys:
            return self.wwr.get("all", 0.0)
        nearest = min(keys, key=lambda k: _angle_diff(azimuth, COMPASS_AZIMUTH[k]))
        return self.wwr[nearest]

    def walls(self) -> list[dict]:
        height = self.floors * self.floor_height
        out = []
        pts = self.footprint
        for i, (x1, y1) in enumerate(pts):
            x2, y2 = pts[(i + 1) % len(pts)]
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            if length < 1e-6:
                continue
            # Outward normal of a counter-clockwise polygon is (dy, -dx).
            plan_az = math.degrees(math.atan2(dy, -dx))
            azimuth = (plan_az + self.plan_up_azimuth) % 360
            gross = length * height
            ratio = self._wwr_for(azimuth)
            out.append({
                "wall": i + 1,
                "length_m": round(length, 2),
                "azimuth_deg": round(azimuth, 1),
                "orientation": compass_label(azimuth),
                "gross_area_m2": round(gross, 1),
                "wwr": ratio,
                "window_area_m2": round(gross * ratio, 1),
                "opaque_area_m2": round(gross * (1 - ratio), 1),
            })
        return out

    def summary(self) -> dict:
        walls = self.walls()
        footprint_area = abs(_signed_area(self.footprint))
        floor_area = footprint_area * self.floors
        wall_area = sum(w["gross_area_m2"] for w in walls)
        window_area = sum(w["window_area_m2"] for w in walls)

        by_orient: dict[str, dict] = {}
        for w in walls:
            o = by_orient.setdefault(w["orientation"], {"wall_area_m2": 0.0, "window_area_m2": 0.0})
            o["wall_area_m2"] += w["gross_area_m2"]
            o["window_area_m2"] += w["window_area_m2"]
        for o in by_orient.values():
            o["wwr"] = round(o["window_area_m2"] / o["wall_area_m2"], 3) if o["wall_area_m2"] else 0
            o["wall_area_m2"] = round(o["wall_area_m2"], 1)
            o["window_area_m2"] = round(o["window_area_m2"], 1)

        return {
            "name": self.name,
            "building_type": self.building_type,
            "floors": self.floors,
            "floor_height_m": self.floor_height,
            "building_height_m": round(self.floors * self.floor_height, 2),
            "footprint_area_m2": round(footprint_area, 1),
            "gross_floor_area_m2": round(floor_area, 1),
            "perimeter_m": round(sum(w["length_m"] for w in walls), 1),
            "roof_area_m2": round(footprint_area, 1),
            "wall_area_m2": round(wall_area, 1),
            "window_area_m2": round(window_area, 1),
            "overall_wwr": round(window_area / wall_area, 3) if wall_area else 0,
            "skylight_roof_ratio": round(self.skylight_area / footprint_area, 3),
            "openable_window_to_floor_ratio": round(window_area * self.openable_fraction / floor_area, 3),
            "envelope": {"wall_u": self.wall_u, "roof_u": self.roof_u, "window_u": self.window_u,
                         "window_shgc": self.window_shgc, "window_vlt": self.window_vlt,
                         "openable_fraction": self.openable_fraction},
            "by_orientation": dict(sorted(by_orient.items(),
                                          key=lambda kv: COMPASS_AZIMUTH[kv[0]])),
            "walls": walls,
            "climate_id": self.climate_id,
        }

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "BuildingModel":
        data = dict(data)
        data["footprint"] = [tuple(p) for p in data["footprint"]]
        return cls(**data)


def _signed_area(pts: list[tuple[float, float]]) -> float:
    return 0.5 * sum(x1 * y2 - x2 * y1
                     for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]))

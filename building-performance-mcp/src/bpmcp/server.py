"""MCP server exposing the building-performance tools to Claude."""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path

from bpmcp import climate as clim
from bpmcp import codes, daylight, lighting, solar
from bpmcp.geometry import BuildingModel

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as MCPServer
    from mcp.server.fastmcp.exceptions import ToolError


class Store:
    """Loaded climates and building models, persisted as JSON so they survive restarts."""

    def __init__(self, folder: Path | None = None):
        self.folder = Path(folder) if folder else clim.cache_dir()
        self.folder.mkdir(parents=True, exist_ok=True)
        self._epws: dict = {}
        self.climate_sources: dict[str, str] = self._read("climates.json")
        self.models: dict[str, dict] = self._read("models.json")

    def _read(self, name: str) -> dict:
        path = self.folder / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def _write(self, name: str, data: dict) -> None:
        (self.folder / name).write_text(json.dumps(data, indent=2), encoding="utf-8")

    def add_climate(self, source: str, climate_id: str | None = None) -> tuple[str, object]:
        epw = clim.load_epw(source)
        cid = climate_id or re.sub(r"[^a-z0-9]+", "-", epw.location.city.lower()).strip("-") or "climate"
        self._epws[cid] = epw
        self.climate_sources[cid] = epw.file_path
        self._write("climates.json", self.climate_sources)
        return cid, epw

    def epw(self, climate_id: str):
        if climate_id not in self._epws:
            if climate_id not in self.climate_sources:
                raise ValueError(f"No climate '{climate_id}'. Load one with load_climate first. "
                                 f"Loaded: {list(self.climate_sources) or 'none'}")
            self._epws[climate_id] = clim.load_epw(self.climate_sources[climate_id])
        return self._epws[climate_id]

    def save_model(self, model: BuildingModel) -> None:
        self.models[model.name] = model.to_dict()
        self._write("models.json", self.models)

    def model(self, name: str) -> BuildingModel:
        if name not in self.models:
            raise ValueError(f"No model '{name}'. Existing models: {list(self.models) or 'none'}")
        return BuildingModel.from_dict(self.models[name])


mcp = MCPServer(
    "building-performance",
    instructions=(
        "Early-stage building performance tools. Typical flow: load_climate (EPW file) -> "
        "create_model (from sketch dimensions; link climate_id) -> model_summary / check_envelope -> "
        "facade_radiation and shading_design for the facades -> lumen_method, daylight_factor and "
        "check_lighting_power for rooms. Azimuths are degrees clockwise from true north. Units are SI. "
        "Results are screening estimates; always pass on warnings about unverified code limits."
    ),
)
_store: Store | None = None


def tool(fn):
    """Register fn as an MCP tool; input problems reach Claude as readable ToolErrors."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ValueError, OSError) as exc:
            raise ToolError(str(exc)) from exc

    return mcp.tool()(wrapper)


def store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


def _location(climate_id, latitude, longitude, time_zone) -> tuple[float, float, float]:
    if climate_id:
        loc = store().epw(climate_id).location
        return loc.latitude, loc.longitude, loc.time_zone
    if None in (latitude, longitude, time_zone):
        raise ValueError("Give climate_id, or latitude, longitude and time_zone (hours from UTC, e.g. 5.5).")
    return latitude, longitude, time_zone


# ---------------------------------------------------------------- climate & sun

@tool
def load_climate(source: str, climate_id: str | None = None) -> dict:
    """Load an EPW weather file (local path to .epw/.zip, or a URL) and summarise the climate.

    Free EPW files: climate.onebuilding.org (includes ISHRAE files for Indian cities).
    Returns location, temperatures, humidity, solar radiation, degree days, the Indian
    (NBC/ECBC) climate zone, the ASHRAE climate zone and a monthly table.
    """
    cid, epw = store().add_climate(source, climate_id)
    return {"climate_id": cid, **clim.climate_summary(epw)}


@tool
def climate_summary(climate_id: str) -> dict:
    """Show the summary of a climate that was loaded earlier."""
    return {"climate_id": climate_id, **clim.climate_summary(store().epw(climate_id))}


@tool
def list_project_data() -> dict:
    """List loaded climates and saved building models."""
    s = store()
    return {"climates": s.climate_sources,
            "models": {n: {"building_type": m["building_type"], "floors": m["floors"],
                           "climate_id": m.get("climate_id")} for n, m in s.models.items()}}


@tool
def sun_position(month: int, day: int, hour: float, climate_id: str | None = None,
                 latitude: float | None = None, longitude: float | None = None,
                 time_zone: float | None = None) -> dict:
    """Sun altitude and azimuth at a local standard time, plus shadow length per metre of height."""
    lat, lon, tz = _location(climate_id, latitude, longitude, time_zone)
    return solar.sun_position(lat, lon, tz, month, day, hour)


@tool
def shading_design(facade_azimuth: float, window_height: float, window_width: float,
                   climate_id: str | None = None, latitude: float | None = None,
                   longitude: float | None = None, time_zone: float | None = None,
                   months: list[int] | None = None, hours: list[int] | None = None,
                   include_hourly: bool = False) -> dict:
    """Size an overhang and vertical fins for a window on a facade.

    facade_azimuth: direction the facade faces (0 N, 90 E, 180 S, 270 W).
    months/hours: period to shade (default Mar-Oct, 8:00-17:00 - the Indian cooling season).
    Returns the depth needed to fully shade the window for 100/90/75% of sunlit hours and advice.
    """
    lat, lon, tz = _location(climate_id, latitude, longitude, time_zone)
    result = solar.shading_design(lat, lon, tz, facade_azimuth, window_height, window_width,
                                  months, hours)
    if not include_hourly:
        result.pop("hourly")
    return result


@tool
def facade_radiation(climate_id: str, months: list[int] | None = None) -> dict:
    """Solar radiation (kWh/m2) falling on N, NE, E, SE, S, SW, W, NW facades and the roof.

    Use months (e.g. [3,4,5,6]) to look at the hot season only.
    """
    return solar.facade_radiation(store().epw(climate_id), months)


# ---------------------------------------------------------------- building model

@tool
def create_model(name: str, floors: int = 1, floor_height: float = 3.0,
                 width: float | None = None, depth: float | None = None,
                 footprint: list[list[float]] | None = None,
                 plan_up_azimuth: float = 0.0, wwr: dict[str, float] | None = None,
                 building_type: str = "office", wall_u: float | None = None,
                 roof_u: float | None = None, window_u: float | None = None,
                 window_shgc: float | None = None, window_vlt: float | None = None,
                 openable_fraction: float = 0.5, skylight_area: float = 0.0,
                 climate_id: str | None = None) -> dict:
    """Create (or replace) a massing model from sketch dimensions and save it.

    Give either width + depth (metres, a rectangle; width runs left-right on the drawing)
    or footprint: plan vertices [[x, y], ...] in metres read off the drawing.
    plan_up_azimuth: true-north azimuth of the drawing's 'up' direction (0 if up = north,
    90 if up = east). If the north arrow points t degrees clockwise from up, use 360 - t.
    wwr: {"all": 0.4} or per direction e.g. {"N": 0.3, "E": 0.15, "S": 0.25, "W": 0.15}.
    U-values in W/m2K. openable_fraction: share of window area that opens (ventilation checks).
    climate_id links a loaded climate so code checks can pick the climate zone automatically.
    """
    if footprint is None:
        if width is None or depth is None:
            raise ValueError("Give width and depth, or a footprint.")
        footprint = [[0, 0], [width, 0], [width, depth], [0, depth]]
    if climate_id:
        store().epw(climate_id)  # validate early
    model = BuildingModel(name=name, footprint=[tuple(p) for p in footprint], floors=floors,
                          floor_height=floor_height, plan_up_azimuth=plan_up_azimuth,
                          wwr=wwr or {"all": 0.4}, building_type=building_type, wall_u=wall_u,
                          roof_u=roof_u, window_u=window_u, window_shgc=window_shgc,
                          window_vlt=window_vlt, openable_fraction=openable_fraction,
                          skylight_area=skylight_area, climate_id=climate_id)
    store().save_model(model)
    return model.summary()


@tool
def update_model(name: str, changes: dict, new_name: str | None = None) -> dict:
    """Change properties of a saved model, e.g. {"wwr": {"W": 0.2}, "window_shgc": 0.25}.

    With new_name, saves the result as a new model (useful for design options A/B/C).
    Note: a 'wwr' change replaces the whole wwr dictionary.
    """
    data = store().model(name).to_dict()
    unknown = set(changes) - set(data)
    if unknown:
        raise ValueError(f"Unknown fields {sorted(unknown)}. Editable: {sorted(data)}")
    data.update(changes)
    if new_name:
        data["name"] = new_name
    model = BuildingModel.from_dict(data)
    store().save_model(model)
    return model.summary()


@tool
def model_summary(name: str) -> dict:
    """Areas, window-to-wall ratio per orientation, envelope values and walls of a saved model."""
    return store().model(name).summary()


# ---------------------------------------------------------------- code checks

@tool
def check_envelope(model_name: str, code: str = "ECBC2017", level: str | None = None,
                   climate_zone: str | None = None, wall_type: str = "mass",
                   window_type: str = "fixed") -> dict:
    """Prescriptive envelope check of a model against a code.

    code: ECBC2017 (commercial, India), ENS2018 (residential, India) or ASHRAE90.1-2019
    (nonresidential, climate zones 0-3). level for ECBC: ECBC, ECBC+ or SuperECBC.
    climate_zone: composite / hot_dry / warm_humid / temperate / cold for ECBC and ENS,
    or 0-3 for ASHRAE. If omitted, it is taken from the model's linked climate.
    wall_type (ASHRAE): mass or steel_framed. window_type (ASHRAE): fixed or operable.
    """
    model = store().model(model_name)
    latitude = None
    if model.climate_id:
        epw = store().epw(model.climate_id)
        latitude = epw.location.latitude
        if climate_zone is None:
            resolved = codes.resolve_code(code)
            if resolved.startswith("ASHRAE"):
                climate_zone = epw.ashrae_climate_zone
            else:
                climate_zone = clim.classify_india_climate(clim.monthly_stats(epw))["zone"]
    return codes.check_envelope(model.summary(), code, climate_zone, level, latitude,
                                wall_type, window_type)


@tool
def check_lighting_power(code: str, building_type: str, area_m2: float,
                         installed_watts: float | None = None, lpd: float | None = None,
                         level: str | None = None) -> dict:
    """Compare installed lighting power (watts or W/m2) with the code's building-area allowance."""
    return codes.check_lpd(code, building_type, area_m2, installed_watts, lpd, level)


@tool
def show_code_limits(code: str) -> dict:
    """Show the limit tables used for a code and whether each table has been verified."""
    return codes.code_limits(code)


# ---------------------------------------------------------------- lighting & daylight

@tool
def lumen_method(length: float, width: float, ceiling_height: float, target_lux: float,
                 lumens_per_fixture: float, watts_per_fixture: float,
                 workplane_height: float = 0.75, suspension: float = 0.0,
                 maintenance_factor: float = 0.8,
                 utilisation_factor: float | None = None) -> dict:
    """Lighting layout by the lumen method: fixture count, grid spacing, achieved lux and LPD.

    Typical targets: offices 300-500 lux, drawing/CAD 500-750, corridors 100, stairs 150.
    Give utilisation_factor from the fitting's datasheet when available.
    """
    return lighting.lumen_method(length, width, ceiling_height, target_lux, lumens_per_fixture,
                                 watts_per_fixture, workplane_height, suspension,
                                 maintenance_factor, utilisation_factor)


@tool
def daylight_factor(room_depth: float, room_width: float, room_height: float,
                    glazed_area: float, vlt: float, sky_angle_deg: float = 90.0,
                    maintenance_factor: float = 0.9, reflectance_ceiling: float = 0.7,
                    reflectance_walls: float = 0.5, reflectance_floor: float = 0.2) -> dict:
    """Average daylight factor of a side-lit room (BRE formula).

    glazed_area: net glass area (m2). vlt: visible transmittance of the glass (0-1).
    sky_angle_deg: visible sky angle from window centre (90 unobstructed, less if
    buildings or deep overhangs block the sky).
    """
    return daylight.average_daylight_factor(room_depth, room_width, room_height, glazed_area, vlt,
                                            sky_angle_deg, maintenance_factor, reflectance_ceiling,
                                            reflectance_walls, reflectance_floor)


@tool
def daylight_depth_check(room_depth: float, room_width: float, window_head_height: float,
                         rear_reflectance: float = 0.5) -> dict:
    """Check whether a side-lit room is too deep to be daylit at the back (BRE limiting depth)."""
    return daylight.limiting_depth(room_depth, room_width, window_head_height, rear_reflectance)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

import pytest
from ladybug.epw import EPW


def synthetic_epw(path, monthly_max, monthly_rh, latitude=26.9, longitude=75.8, tz=5.5):
    """EPW with a 10 C daily swing below each month's max and a fixed RH per month."""
    epw = EPW.from_missing_values()
    epw.location.city = "Testpur"
    epw.location.latitude, epw.location.longitude, epw.location.time_zone = latitude, longitude, tz
    temps = epw.dry_bulb_temperature
    rh = epw.relative_humidity
    t_vals, rh_vals = [], []
    for dt in temps.datetimes:
        tmax = monthly_max[dt.month - 1]
        swing = 10 * (1 - abs(dt.hour - 14) / 14)  # peak at 14:00
        t_vals.append(tmax - 10 + swing)
        rh_vals.append(monthly_rh[dt.month - 1])
    temps.values = t_vals
    rh.values = rh_vals
    day = [7 <= dt.hour <= 17 for dt in temps.datetimes]
    epw.global_horizontal_radiation.values = [500 if d else 0 for d in day]
    epw.direct_normal_radiation.values = [400 if d else 0 for d in day]
    epw.diffuse_horizontal_radiation.values = [150 if d else 0 for d in day]
    epw.save(str(path))
    return str(path)


@pytest.fixture
def hot_dry_epw(tmp_path):
    return synthetic_epw(tmp_path / "hot_dry.epw",
                         [24, 27, 33, 38, 41, 40, 35, 33, 34, 34, 30, 25],
                         [40, 35, 30, 25, 30, 45, 60, 65, 50, 40, 40, 45])


@pytest.fixture
def store(tmp_path, monkeypatch):
    from bpmcp import server
    s = server.Store(tmp_path / "store")
    monkeypatch.setattr(server, "_store", s)
    return s

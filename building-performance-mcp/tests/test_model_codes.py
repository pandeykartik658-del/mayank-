import pytest

from bpmcp import codes
from bpmcp.geometry import BuildingModel, compass_label


def test_compass_label():
    assert compass_label(0) == "N" and compass_label(359) == "N"
    assert compass_label(100) == "E" and compass_label(200) == "S" and compass_label(290) == "W"


def test_rectangle_orientations_and_areas():
    m = BuildingModel.rectangle("a", 30, 18, floors=4, floor_height=3.5,
                                wwr={"N": 0.3, "S": 0.3, "E": 0.1, "W": 0.1})
    s = m.summary()
    assert s["gross_floor_area_m2"] == 30 * 18 * 4
    assert set(s["by_orientation"]) == {"N", "E", "S", "W"}
    assert s["by_orientation"]["S"]["wall_area_m2"] == 30 * 14
    assert s["by_orientation"]["E"]["window_area_m2"] == pytest.approx(18 * 14 * 0.1)
    expected = (2 * 30 * 14 * 0.3 + 2 * 18 * 14 * 0.1) / (2 * 48 * 14)
    assert s["overall_wwr"] == pytest.approx(expected, abs=1e-3)


def test_clockwise_footprint_and_rotation():
    cw = BuildingModel("b", [(0, 0), (0, 10), (20, 10), (20, 0)], plan_up_azimuth=90)
    s = cw.summary()
    # Plan up points east, so the long wall facing plan-down faces west.
    assert s["by_orientation"]["W"]["wall_area_m2"] == 20 * 3
    assert s["by_orientation"]["N"]["wall_area_m2"] == 10 * 3


def test_model_validation():
    with pytest.raises(ValueError):
        BuildingModel("c", [(0, 0), (1, 0)])
    with pytest.raises(ValueError):
        BuildingModel.rectangle("d", 10, 10, wwr={"up": 0.2})
    with pytest.raises(ValueError):
        BuildingModel.rectangle("e", 10, 10, wwr={"all": 1.2})


def _office(**kw):
    defaults = dict(floors=3, wwr={"all": 0.35}, wall_u=0.38, roof_u=0.30,
                    window_u=2.8, window_shgc=0.25, window_vlt=0.4)
    defaults.update(kw)
    return BuildingModel.rectangle("o", 30, 18, **defaults).summary()


def test_ecbc_pass_and_fail():
    ok = codes.check_envelope(_office(), "ECBC", "composite", latitude=26.9)
    assert ok["summary"]["fail"] == 0 and ok["summary"]["missing input"] == 0
    bad = codes.check_envelope(_office(wwr={"all": 0.5}, wall_u=0.6), "ecbc2017", "Hot & Dry",
                               latitude=26.9)
    failed = {c["check"] for c in bad["checks"] if c["result"] == "fail"}
    assert "Overall window-to-wall ratio" in failed
    assert "Wall U-value (ECBC)" in failed
    assert bad["climate_zone"] == "hot_dry"


def test_ecbc_north_shgc_relaxation_depends_on_latitude():
    north_only = _office(wwr={"N": 0.3, "S": 0.0, "E": 0.0, "W": 0.0}, window_shgc=0.45)
    high = codes.check_envelope(north_only, "ECBC", "composite", latitude=26.9)
    low = codes.check_envelope(north_only, "ECBC", "warm_humid", latitude=10.0)
    shgc_high = [c for c in high["checks"] if "SHGC" in c["check"]]
    shgc_low = [c for c in low["checks"] if "SHGC" in c["check"]]
    assert shgc_high[0]["check"].endswith("(north glazing)") and shgc_high[0]["result"] == "pass"
    assert shgc_low[0]["check"].endswith("(non-north glazing)") and shgc_low[0]["result"] == "fail"


def test_missing_inputs_and_unverified_warning():
    r = codes.check_envelope(_office(wall_u=None), "ECBC", "composite", level="ECBC+", latitude=20)
    wall = next(c for c in r["checks"] if c["check"].startswith("Wall"))
    assert wall["result"] == "missing input"
    assert any("not yet verified" in w for w in r["warnings"])


def test_ens_and_ashrae():
    res = BuildingModel.rectangle("r", 12, 10, floors=2, roof_u=1.0, wwr={"all": 0.2},
                                  openable_fraction=0.6).summary()
    ens = codes.check_envelope(res, "ENS", "warm-humid")
    wfr = next(c for c in ens["checks"] if "floor ratio" in c["check"])
    assert wfr["limit"] == pytest.approx(0.167, abs=1e-3)

    ash = codes.check_envelope(_office(window_shgc=0.3), "ASHRAE", "1A", wall_type="steel_framed")
    assert ash["climate_zone"] == "1"
    assert next(c for c in ash["checks"] if c["check"] == "Window SHGC")["result"] == "fail"
    with pytest.raises(ValueError, match="not covered"):
        codes.check_envelope(_office(), "ASHRAE", "5A")


def test_lpd():
    r = codes.check_lpd("ECBC", "office", 1000, installed_watts=8000)
    assert r["check"]["result"] == "pass" and r["allowed_total_w"] == 9500
    a = codes.check_lpd("ashrae", "office", 100, lpd=7.5)
    assert a["allowed_lpd_w_m2"] == pytest.approx(6.89, abs=0.01)
    assert a["check"]["result"] == "fail"
    with pytest.raises(ValueError):
        codes.check_lpd("ENS", "office", 100, lpd=5)


def test_every_table_has_status():
    for name, section in codes.load_limits().items():
        if name.startswith("_"):
            continue
        for key, table in section.items():
            if isinstance(table, dict) and not key.startswith("_"):
                assert "status" in table, f"{name}.{key} lacks a status"

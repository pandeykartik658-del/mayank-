import pytest

from bpmcp import daylight, lighting, server


def test_lumen_method_counts_and_lpd():
    r = lighting.lumen_method(12, 8, 3.0, 500, 4000, 36, utilisation_factor=0.6,
                              maintenance_factor=0.8)
    # N = 500 * 96 / (4000 * 0.6 * 0.8) = 25
    assert r["fixtures_required"] == 25
    lay = r["layout"]
    assert lay["fixtures"] >= 25
    assert r["maintained_illuminance_lux"] >= 500
    assert r["lpd_w_m2"] == pytest.approx(lay["fixtures"] * 36 / 96, abs=0.01)


def test_generic_uf_monotonic_and_clamped():
    assert lighting.generic_uf(0.1) == lighting.GENERIC_UF[0][1]
    assert lighting.generic_uf(10) == lighting.GENERIC_UF[-1][1]
    assert lighting.generic_uf(1.1) < lighting.generic_uf(2.2)


def test_lumen_method_rejects_bad_heights():
    with pytest.raises(ValueError):
        lighting.lumen_method(5, 5, 0.7, 300, 3000, 30)


def test_average_daylight_factor():
    r = daylight.average_daylight_factor(6, 4, 3, glazed_area=4.8, vlt=0.6)
    assert 2 < r["average_daylight_factor_pct"] < 6
    darker = daylight.average_daylight_factor(6, 4, 3, glazed_area=4.8, vlt=0.3)
    assert darker["average_daylight_factor_pct"] < r["average_daylight_factor_pct"]


def test_limiting_depth():
    ok = daylight.limiting_depth(5, 4, 2.4)
    assert ok["pass"]
    deep = daylight.limiting_depth(10, 4, 2.4)
    assert not deep["pass"] and deep["max_room_depth_m"] < 10


def test_server_flow(store, hot_dry_epw):
    c = server.load_climate(hot_dry_epw, climate_id="test")
    assert c["climate_id"] == "test"
    m = server.create_model("opt-a", floors=4, width=30, depth=18, wwr={"all": 0.3},
                            wall_u=0.38, roof_u=0.3, window_u=2.8, window_shgc=0.25,
                            window_vlt=0.4, climate_id="test")
    assert m["gross_floor_area_m2"] == 2160
    chk = server.check_envelope("opt-a")
    assert chk["climate_zone"] == "hot_dry" and chk["summary"]["fail"] == 0

    b = server.update_model("opt-a", {"wwr": {"all": 0.5}}, new_name="opt-b")
    assert b["overall_wwr"] == 0.5
    assert server.check_envelope("opt-b")["summary"]["fail"] >= 1
    assert set(server.list_project_data()["models"]) == {"opt-a", "opt-b"}

    # A fresh store reloads saved climates and models from disk.
    fresh = server.Store(store.folder)
    assert fresh.model("opt-b").wwr == {"all": 0.5}
    assert fresh.epw("test").location.city == "Testpur"

    shade = server.shading_design(270, 1.5, 1.2, climate_id="test")
    assert "hourly" not in shade
    with pytest.raises(server.ToolError, match="Unknown fields"):
        server.update_model("opt-a", {"colour": "red"})
    with pytest.raises(server.ToolError, match="No model"):
        server.model_summary("missing")

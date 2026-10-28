import math

import pytest

from bpmcp import climate, solar


def test_classify_month_india():
    assert climate.classify_month_india(38, 30) == "hot_dry"
    assert climate.classify_month_india(33, 70) == "warm_humid"
    assert climate.classify_month_india(28, 80) == "warm_humid"
    assert climate.classify_month_india(28, 60) == "temperate"
    assert climate.classify_month_india(20, 60) == "cold"


def test_composite_when_no_category_has_six_months():
    rows = [{"mean_daily_max_C": t, "mean_rh_pct": rh} for t, rh in
            [(20, 50)] * 3 + [(38, 30)] * 4 + [(33, 80)] * 3 + [(28, 50)] * 2]
    assert climate.classify_india_climate(rows)["zone"] == "composite"


def test_load_and_summarise_synthetic_epw(hot_dry_epw):
    epw = climate.load_epw(hot_dry_epw)
    s = climate.climate_summary(epw)
    assert s["location"]["city"] == "Testpur"
    assert s["india_climate_zone"]["zone"] == "hot_dry"
    assert s["monthly"][4]["mean_daily_max_C"] == pytest.approx(41, abs=0.01)
    assert s["annual"]["CDD10"] > s["annual"]["HDD18"]
    assert s["annual"]["solar_ghi_kwh_m2"] == round(365 * 11 * 500 / 1000)


def test_load_epw_missing_file():
    with pytest.raises(ValueError, match="not found"):
        climate.load_epw("/nope/missing.epw")


def test_shading_angles_head_on_and_behind():
    a = solar.shading_angles(altitude=30, azimuth=180, facade_azimuth=180)
    assert a["hsa_deg"] == 0 and a["vsa_deg"] == 30 and a["sun_on_facade"]
    behind = solar.shading_angles(altitude=30, azimuth=0, facade_azimuth=180)
    assert not behind["sun_on_facade"]


def test_overhang_and_fin_depth():
    assert solar.overhang_depth(1.5, 45) == pytest.approx(1.5)
    assert solar.fin_depth(1.0, 45) == pytest.approx(1.0)
    assert solar.fin_depth(1.0, 0) is None


def test_sun_position_noon_equinox_jaipur():
    p = solar.sun_position(26.9, 75.8, 5.5, 3, 21, 12.5)
    # Near solar noon at the equinox altitude is about 90 - latitude.
    assert p["altitude_deg"] == pytest.approx(90 - 26.9, abs=2.5)
    assert 150 < p["azimuth_deg"] < 210


def test_shading_design_south_vs_west():
    south = solar.shading_design(26.9, 75.8, 5.5, 180, 1.5, 1.2)
    west = solar.shading_design(26.9, 75.8, 5.5, 270, 1.5, 1.2)
    s100 = south["depth_needed_to_fully_shade"]["100%"]["overhang_depth_m"]
    w100 = west["depth_needed_to_fully_shade"]["100%"]["overhang_depth_m"]
    assert s100 is not None and w100 is not None and w100 > s100


def test_facade_radiation_structure(hot_dry_epw):
    epw = climate.load_epw(hot_dry_epw)
    r = solar.facade_radiation(epw)
    assert set(r["facades"]) == {"N", "NE", "E", "SE", "S", "SW", "W", "NW"}
    assert r["roof"] > max(r["facades"].values())
    hot = solar.facade_radiation(epw, months=[4, 5])
    assert hot["facades"]["S"] < r["facades"]["S"]
    assert not math.isnan(hot["roof"])

"""M7 customer font choice: 12–24 certified, installed fonts; styleable roles only; visible fallback."""
from __future__ import annotations

import pytest

from mxstudio.fonts.customer_choice import ChoiceRefused, build_payload, preview, resolve_choice
from mxstudio.fonts.office_build import install_name_map

NAME_FONTS = ["Lemonada", "Marhey", "Lalezar", "Rakkas", "Baloo Bhaijaan 2", "El Messiri", "Aref Ruqaa", "Changa"]
DEDICATION_FONTS = ["Playpen Sans Arabic", "Katibeh", "Reem Kufi", "Mirza"]
DEFAULTS = {"child-name": "Baloo Bhaijaan 2", "handwriting-dedication": "Playpen Sans Arabic"}


@pytest.fixture(scope="module")
def names():
    return install_name_map()


def _build(qa, names, curated=None, machines=None, **kw):
    curated = curated or {"child-name": NAME_FONTS, "handwriting-dedication": DEDICATION_FONTS}
    machines = machines or {"OM-PC": set(names.values()), "Console-PC": set(names.values())}
    return build_payload("m7-set", "ar", curated, DEFAULTS, names, qa, machines, **kw)


def test_payload_from_curated_certified_installed_fonts(committed, names):
    payload = _build(committed["qa_status"], names, prices={"child-name": 15})
    roles = payload["roles"]
    assert roles["child-name"]["prompt_ar"] == "اختار خط اسم طفلك"
    assert roles["child-name"]["price_egp"] == 15 and roles["handwriting-dedication"]["price_egp"] is None
    reem = next(o for o in roles["handwriting-dedication"]["options"] if o["family"] == "Reem Kufi")
    assert reem["install_name"] == "MX Kids F019 Reem Kufi"  # renamed Office build (RFN)


def test_fallback_to_template_default_is_visible(committed, names):
    payload = _build(committed["qa_status"], names)
    used = resolve_choice(payload, "child-name", "Lalezar", {"Baloo Bhaijaan 2"})
    assert used["fallback"] and used["family"] == "Baloo Bhaijaan 2"
    assert "Baloo Bhaijaan 2" in used["note_ar"] and used["reason"] == "choice_not_installed_on_exporter"
    assert resolve_choice(payload, "child-name", "Lalezar", {"Lalezar"}) == {
        "family": "Lalezar", "install_name": "Lalezar", "fallback": False}
    assert resolve_choice(payload, "child-name", "Nabla", {"Nabla"})["reason"] == "choice_not_an_option"


def test_negative_controls(committed, names):
    qa = committed["qa_status"]
    cases = [
        ({"child-name": NAME_FONTS[:7], "handwriting-dedication": DEDICATION_FONTS}, None, "choice_subset_size"),
        ({"child-name": NAME_FONTS, "handwriting-dedication": [*DEDICATION_FONTS, "Blaka"]}, None,
         "choice_font_has_no_tatweel"),
        ({"child-name": [*NAME_FONTS, "Reem Kufi Fun"], "handwriting-dedication": DEDICATION_FONTS}, None,
         "choice_font_screen_only"),
        ({"child-name": NAME_FONTS, "handwriting-dedication": DEDICATION_FONTS, "body": ["Tajawal"]}, None,
         "choice_role_not_customer_styleable"),
        (None, {"OM-PC": set(names.values()) - {"Lalezar"}}, "choice_font_not_installed_on_machine"),
    ]
    for curated, machines, finding in cases:
        if curated and "body" in curated:
            DEFAULTS_BODY = dict(DEFAULTS, body="Tajawal")
            with pytest.raises(ChoiceRefused) as excinfo:
                build_payload("s", "ar", curated, DEFAULTS_BODY, names, qa,
                              {"OM-PC": set(names.values())})
        else:
            with pytest.raises(ChoiceRefused) as excinfo:
                _build(qa, names, curated=curated, machines=machines)
        assert finding in {f["finding"] for f in excinfo.value.findings}, finding


def test_live_preview_uses_the_real_fitter(fixture_registry):
    fit = preview("Tajawal", "عبد الرحمن", 200, 60, fixture_registry)
    assert fit["fits"] and fit["font_family"] == "Tajawal" and 14 <= fit["size_pt"] <= 48
    with pytest.raises(LookupError):
        preview("Lalezar", "عبد الرحمن", 200, 60, fixture_registry)

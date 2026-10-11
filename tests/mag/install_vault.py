"""Test helper: a font folder shaped like what the installer registers in Windows (upstream statics + Office builds,
never a variable file an Office build replaces), built from the pinned files of tools/fetch_test_fonts.py."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAT = ROOT / "catalog" / "fonts"
TEST_FONTS = Path(os.environ.get("MXS_TEST_FONTS") or ROOT / "workspace" / "test-fonts")


def theme_families(roles: tuple[str, ...] | None = None) -> list[str]:
    themes = json.loads((CAT / "type_themes.json").read_text(encoding="utf-8"))["themes"]
    return sorted({v for t in themes for k, v in t.items() if isinstance(v, str)
                   and (k in roles if roles else k.startswith(("ar_", "en_")))})


def files_present(families: list[str]) -> bool:
    catalog = {f["family"]: f for f in json.loads((CAT / "catalog.json").read_text("utf-8"))["families"]}
    return all((TEST_FONTS / i["file"]).is_file() for fam in families for i in catalog[fam]["files"])


def install_shaped_vault(dest: Path, families: list[str] | None = None) -> Path:
    from mxstudio.fonts.office_build import build_family
    catalog = {f["family"]: f for f in json.loads((CAT / "catalog.json").read_text("utf-8"))["families"]}
    plans = {p["family"]: p for p in json.loads((CAT / "office_builds.json").read_text("utf-8"))["families"]}
    dest.mkdir(parents=True, exist_ok=True)
    for family in families or theme_families():
        plan = plans.get(family, {})
        if plan.get("source") == "office_build":
            build_family(TEST_FONTS / plan["from_file"], dest, font_id=plan["id"], family=family,
                         rfns=catalog[family].get("reserved_font_names", []), roles=catalog[family]["roles"],
                         weights=plan["weights"])
        else:
            for item in catalog[family]["files"]:
                shutil.copyfile(TEST_FONTS / item["file"], dest / item["file"])
    return dest

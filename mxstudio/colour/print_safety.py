"""Print safety: sRGB → press CMYK through ICC (LittleCMS via Pillow ImageCms).

Rule: the screen can show colours the press cannot print. For a chosen printer profile
(default FOGRA39L coated; GRACoL TR006 coated bundled; any operator-supplied CMYK ICC
profile accepted) this module converts with relative-colorimetric intent, reads back what
the press will reproduce, and reports facts:

* ΔE2000 (CIELab D50) between intended and printable colour — above the threshold it is
  a *warning* ("prints dull"), never a block: the operator may accept a duller green;
* total area coverage (TAC, C+M+Y+K %) — above the printer's limit it is an objective,
  *blocking* finding (ink set-off, drying), most often on dark backgrounds;
* rich-black guidance — K-only for small text and hairlines (registration), a rich black
  recipe within the ink limit for large dark areas.

The bundled profiles are CC0 (colord data, see catalog/palettes/icc/PROVENANCE.json) and
are verified by sha256 before use. Converted values depend on LittleCMS; the version used
is recorded in every report.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
from PIL import Image, ImageCms

from .delta_e import ciede2000
from .oklch import ColourLike, parse_rgb, srgb_array_to_lab_d50, to_hex

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ICC_DIR = ROOT / "catalog" / "palettes" / "icc"
DELTA_E_WARN = 6.0          # ΔE2000 above which a colour is flagged as "prints noticeably duller/different"
TAC_LIMIT = 300.0           # % — FOGRA39 / GRACoL coated sheet-fed default; operator-selectable per printer
TAC_TOLERANCE = 0.5         # % — 8-bit CMYK rounding
DARK_L = 25.0               # CIELab L* below which a pixel counts as "dark background"
SMALL_TEXT_PT = 24.0        # below this, black text should be K-only


def icc_dir() -> Path:
    env = os.environ.get("MXS_ICC_DIR")
    return Path(env) if env else DEFAULT_ICC_DIR


@lru_cache(maxsize=None)
def provenance() -> dict:
    path = icc_dir() / "PROVENANCE.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"profiles": {}}


def known_profiles() -> dict[str, dict]:
    return dict(provenance().get("profiles", {}))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class PrintSettings:
    profile: str = "FOGRA39"           # key in PROVENANCE.json or a path to a CMYK .icc
    intent: str = "relative"           # relative | perceptual
    black_point_compensation: bool = False
    tac_limit: float = TAC_LIMIT
    delta_e_warn: float = DELTA_E_WARN

    def as_dict(self) -> dict:
        return asdict(self)


DEFAULT_PRINT = PrintSettings()  # frozen: safe to share as a default


def resolve_profile(profile: str) -> tuple[Path, str]:
    """Return (path, sha256). Bundled profiles must match their pinned hash."""
    entries = known_profiles()
    if profile in entries:
        entry = entries[profile]
        path = icc_dir() / entry["file"]
        digest = _sha256(path)
        if digest != entry["sha256"]:
            raise RuntimeError(f"ICC profile {path.name} does not match its pinned sha256")
        return path, digest
    path = Path(profile)
    if not path.is_file():
        raise FileNotFoundError(f"no bundled profile {profile!r} and no such file")
    return path, _sha256(path)


@lru_cache(maxsize=16)
def _transforms(path_str: str, intent: str, bpc: bool):
    cmyk = ImageCms.getOpenProfile(path_str)
    if cmyk.profile.xcolor_space.strip() != "CMYK":
        raise ValueError(f"{Path(path_str).name} is not a CMYK output profile")
    srgb = ImageCms.createProfile("sRGB")
    lab = ImageCms.createProfile("LAB")
    rendering = {"relative": ImageCms.Intent.RELATIVE_COLORIMETRIC,
                 "perceptual": ImageCms.Intent.PERCEPTUAL}[intent]
    flags = ImageCms.Flags.BLACKPOINTCOMPENSATION if bpc else ImageCms.Flags.NONE
    to_cmyk = ImageCms.buildTransform(srgb, cmyk, "RGB", "CMYK", renderingIntent=rendering, flags=flags)
    cmyk_to_lab = ImageCms.buildTransform(cmyk, lab, "CMYK", "LAB",
                                          renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC, flags=flags)
    cmyk_to_srgb = ImageCms.buildTransform(cmyk, srgb, "CMYK", "RGB",
                                           renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC, flags=flags)
    return to_cmyk, cmyk_to_lab, cmyk_to_srgb, ImageCms.getProfileDescription(cmyk).strip()


def _get(settings: PrintSettings):
    path, digest = resolve_profile(settings.profile)
    t = _transforms(str(path), settings.intent, settings.black_point_compensation)
    return t, path, digest


def lcms_version() -> str:
    return str(getattr(ImageCms.core, "littlecms_version", "unknown"))


def _rgb_image(rgb: np.ndarray) -> Image.Image:
    flat = np.ascontiguousarray(rgb.reshape(1, -1, 3).astype(np.uint8))
    return Image.fromarray(flat, "RGB")


def _lab_from_pillow(im: Image.Image) -> np.ndarray:
    """Pillow's raw LAB bytes: L scaled 0..255, a/b as signed 8-bit (two's complement)."""
    arr = np.asarray(im).astype(np.int16)
    signed = (arr[..., 1:] + 128) % 256 - 128
    return np.concatenate([arr[..., :1] * (100.0 / 255.0), signed.astype(np.float64)], axis=-1)


def convert_pixels(rgb: np.ndarray, settings: PrintSettings = DEFAULT_PRINT) -> dict[str, np.ndarray]:
    """uint8 (N, 3) sRGB → {cmyk uint8 (N,4), printed_lab (N,3), printed_rgb uint8 (N,3)}."""
    (to_cmyk, to_lab, to_srgb, _desc), _p, _d = _get(settings)
    rgb = np.asarray(rgb, dtype=np.uint8).reshape(-1, 3)
    cmyk_im = ImageCms.applyTransform(_rgb_image(rgb), to_cmyk)
    lab = _lab_from_pillow(ImageCms.applyTransform(cmyk_im, to_lab)).reshape(-1, 3)
    back = np.asarray(ImageCms.applyTransform(cmyk_im, to_srgb)).reshape(-1, 3)
    return {"cmyk": np.asarray(cmyk_im).reshape(-1, 4), "printed_lab": lab, "printed_rgb": back}


def cmyk_percent(cmyk_u8: Sequence[int]) -> tuple[float, float, float, float]:
    return tuple(round(float(v) * 100.0 / 255.0, 2) for v in cmyk_u8)  # type: ignore[return-value]


def srgb_to_cmyk(colour: ColourLike, settings: PrintSettings = DEFAULT_PRINT) -> tuple[float, float, float, float]:
    out = convert_pixels(np.array([parse_rgb(colour)], dtype=np.uint8), settings)
    return cmyk_percent(out["cmyk"][0])


def check_colour(colour: ColourLike, settings: PrintSettings = DEFAULT_PRINT) -> dict:
    """Facts for one swatch: CMYK, TAC, ΔE2000 to the printable colour, soft-proof hex."""
    rgb = np.array([parse_rgb(colour)], dtype=np.uint8)
    out = convert_pixels(rgb, settings)
    src_lab = srgb_array_to_lab_d50(rgb)[0]
    de = float(ciede2000(src_lab, out["printed_lab"][0]))
    cmyk = cmyk_percent(out["cmyk"][0])
    tac = round(float(out["cmyk"][0].astype(int).sum()) * 100.0 / 255.0, 1)
    dull = de > settings.delta_e_warn
    ink = tac > settings.tac_limit + TAC_TOLERANCE
    findings = []
    if dull:
        findings.append(_dull_finding(de, settings))
    if ink:
        findings.append(_ink_finding(tac, settings))
    return {"hex": to_hex(colour), "cmyk": cmyk, "tac": tac, "delta_e2000": round(de, 2),
            "printed_hex": to_hex(tuple(int(v) for v in out["printed_rgb"][0])),
            "source_lab": [round(float(v), 2) for v in src_lab],
            "printed_lab": [round(float(v), 2) for v in out["printed_lab"][0]],
            "warn_dull": dull, "blocking": ink, "findings": findings}


def _dull_finding(de: float, s: PrintSettings) -> dict:
    return {"finding": "colour_shifts_in_print", "blocking": False, "delta_e2000": round(de, 2),
            "threshold": s.delta_e_warn, "profile": s.profile,
            "ar": f"اللون ده هيطلع في الطباعة باهت/مختلف (ΔE2000 = {de:.1f}). شوف البروفة واختار لون أقرب للمطبوع لو حابب.",
            "en": f"This colour will print noticeably different/duller (ΔE2000 = {de:.1f}). Check the soft proof."}


def _ink_finding(tac: float, s: PrintSettings) -> dict:
    return {"finding": "ink_coverage_over_limit", "blocking": True, "tac": round(tac, 1), "limit": s.tac_limit,
            "profile": s.profile,
            "ar": f"مجموع الحبر {tac:.0f}% أكتر من حد المطبعة {s.tac_limit:.0f}% — الورق هيبوّظ/الحبر مش هينشف.",
            "en": f"Total ink {tac:.0f}% exceeds the printer limit {s.tac_limit:.0f}%."}


def check_palette(colours: Iterable[ColourLike], settings: PrintSettings = DEFAULT_PRINT) -> dict:
    rows = [check_colour(c, settings) for c in colours]
    return {"profile": settings.profile, "lcms": lcms_version(), "colours": rows,
            "max_delta_e2000": max((r["delta_e2000"] for r in rows), default=0.0),
            "max_tac": max((r["tac"] for r in rows), default=0.0),
            "warn": any(r["warn_dull"] for r in rows), "blocking": any(r["blocking"] for r in rows)}


def check_cmyk(cmyk_percentages: Sequence[float], settings: PrintSettings = DEFAULT_PRINT) -> dict:
    """A CMYK value specified directly (e.g. a swatch or a black in the template)."""
    c = [float(v) for v in cmyk_percentages]
    if len(c) != 4 or any(v < 0 or v > 100 for v in c):
        raise ValueError("CMYK must be four percentages 0..100")
    tac = round(sum(c), 1)
    over = tac > settings.tac_limit + TAC_TOLERANCE
    return {"cmyk": c, "tac": tac, "blocking": over, "findings": [_ink_finding(tac, settings)] if over else []}


def check_image(image: Any, settings: PrintSettings = DEFAULT_PRINT, max_pixels: int = 250_000,
                warn_area: float = 0.01) -> dict:
    """Whole-art facts: share of area that shifts > threshold, TAC over limit (and on dark areas)."""
    from .extract import load_rgba

    rgba = load_rgba(image)
    h, w = rgba.shape[:2]
    stride = max(1, int(np.ceil(np.sqrt(h * w / max_pixels))))
    sub = rgba[::stride, ::stride]
    rgb = sub[..., :3][sub[..., 3] >= 128].reshape(-1, 3)
    if len(rgb) == 0:
        return {"pixels": 0, "blocking": False, "findings": []}
    uniq, inverse = np.unique(rgb, axis=0, return_inverse=True)
    inverse = inverse.reshape(-1)
    out = convert_pixels(uniq, settings)
    de_u = ciede2000(srgb_array_to_lab_d50(uniq), out["printed_lab"])
    tac_u = out["cmyk"].astype(np.int64).sum(axis=1) * 100.0 / 255.0
    de, tac = de_u[inverse], tac_u[inverse]
    src_L = srgb_array_to_lab_d50(uniq)[:, 0][inverse]
    dark = src_L < DARK_L
    over = tac > settings.tac_limit + TAC_TOLERANCE
    shifted = de > settings.delta_e_warn
    findings = []
    shifted_area = float(shifted.mean())
    if shifted_area >= warn_area:
        worst = np.argsort(-de_u)[:5]
        f = _dull_finding(float(np.percentile(de[shifted], 95)), settings)
        f.update({"area": round(shifted_area, 4),
                  "worst": [{"hex": to_hex(tuple(int(v) for v in uniq[i])), "delta_e2000": round(float(de_u[i]), 2),
                             "printed_hex": to_hex(tuple(int(v) for v in out["printed_rgb"][i]))} for i in worst]})
        findings.append(f)
    if over.any():
        f = _ink_finding(float(tac.max()), settings)
        f.update({"area": round(float(over.mean()), 4), "dark_area_over": round(float((over & dark).mean()), 4)})
        findings.append(f)
    return {"pixels": int(len(rgb)), "sample_stride": stride, "profile": settings.profile, "lcms": lcms_version(),
            "delta_e2000_p95": round(float(np.percentile(de, 95)), 2), "delta_e2000_max": round(float(de.max()), 2),
            "shifted_area": round(shifted_area, 4), "tac_max": round(float(tac.max()), 1),
            "dark_area": round(float(dark.mean()), 4),
            "tac_over_area": round(float(over.mean()), 4),
            "warn": any(not f["blocking"] for f in findings), "blocking": any(f["blocking"] for f in findings),
            "findings": findings}


def soft_proof(image: Any, settings: PrintSettings = DEFAULT_PRINT) -> Image.Image:
    """What the press can reproduce, back on screen (for the operator's side-by-side)."""
    from .extract import load_rgba

    (to_cmyk, _lab, to_srgb, _d), _p, _h = _get(settings)
    rgba = load_rgba(image)
    rgb = Image.fromarray(np.ascontiguousarray(rgba[..., :3]), "RGB")
    back = ImageCms.applyTransform(ImageCms.applyTransform(rgb, to_cmyk), to_srgb)
    return Image.fromarray(np.concatenate([np.asarray(back), rgba[..., 3:]], axis=-1), "RGBA")


RICH_BLACK = (60.0, 40.0, 40.0, 100.0)   # 240 % "cool" rich black, a common coated-stock recipe
TEXT_BLACK = (0.0, 0.0, 0.0, 100.0)


def rich_black_guidance(usage: str, font_size_pt: float | None = None,
                        settings: PrintSettings = DEFAULT_PRINT) -> dict:
    """Which black to use. ``usage``: "text", "line" or "background"."""
    if usage not in {"text", "line", "background"}:
        raise ValueError("usage must be text, line or background")
    small = usage == "line" or (usage == "text" and (font_size_pt is None or font_size_pt < SMALL_TEXT_PT))
    if small:
        recipe = TEXT_BLACK
        ar = "الكلام الصغير والخطوط الرفيعة: أسود K100 بس (من غير ألوان تانية) عشان مايبقاش فيه ظل ملوّن لو الطباعة زاحت."
        en = "Small text and hairlines: K100 only, so a slight misregistration cannot leave coloured halos."
    else:
        recipe = RICH_BLACK
        ar = (f"الخلفيات الغامقة الكبيرة: أسود غني C{RICH_BLACK[0]:.0f} M{RICH_BLACK[1]:.0f} Y{RICH_BLACK[2]:.0f} "
              f"K100 ({sum(RICH_BLACK):.0f}%) — أغمق من K100 لوحده وتحت حد الحبر {settings.tac_limit:.0f}%.")
        en = (f"Large dark areas: rich black C{RICH_BLACK[0]:.0f} M{RICH_BLACK[1]:.0f} Y{RICH_BLACK[2]:.0f} K100 "
              f"({sum(RICH_BLACK):.0f}%) — deeper than K100 alone and within the {settings.tac_limit:.0f}% ink limit.")
    recipe_ok = sum(recipe) <= settings.tac_limit
    lab = measure_cmyk_lab([recipe, TEXT_BLACK], settings)
    return {"usage": usage, "font_size_pt": font_size_pt, "cmyk": list(recipe), "tac": sum(recipe),
            "within_limit": recipe_ok, "printed_L": round(lab[0][0], 1), "k_only_L": round(lab[1][0], 1),
            "ar": ar, "en": en}


def measure_cmyk_lab(cmyk_list: Sequence[Sequence[float]], settings: PrintSettings = DEFAULT_PRINT) -> list[list[float]]:
    """CIELab D50 the profile predicts for given CMYK percentages."""
    (_t, to_lab, _s, _d), _p, _h = _get(settings)
    arr = np.array([[int(round(v * 2.55)) for v in c] for c in cmyk_list], dtype=np.uint8).reshape(1, -1, 4)
    lab = _lab_from_pillow(ImageCms.applyTransform(Image.fromarray(arr, "CMYK"), to_lab)).reshape(-1, 3)
    return [[float(v) for v in row] for row in lab]


def profile_info(settings: PrintSettings = DEFAULT_PRINT) -> dict:
    (_t, _l, _s, desc), path, digest = _get(settings)
    meta = known_profiles().get(settings.profile, {})
    return {"key": settings.profile, "description": desc, "file": path.name, "sha256": digest,
            "licence": meta.get("licence", "operator-supplied"), "lcms": lcms_version()}


__all__ = ["PrintSettings", "check_colour", "check_palette", "check_cmyk", "check_image", "soft_proof",
           "rich_black_guidance", "srgb_to_cmyk", "profile_info", "known_profiles", "measure_cmyk_lab"]

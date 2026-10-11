"""Name Art and sound-effect presets built only from native, editable PowerPoint text effects.

Rule: the child's name (and every sound effect) stays **real text** — a run
in a text frame that the operator's ``replace_in_shape`` can replace and a PDF
export can extract. A preset may therefore only use DrawingML that styles
text: outline (``a:ln``), solid or gradient fill (``a:solidFill``,
``a:gradFill``), effects (``a:effectLst`` with ``a:glow`` / ``a:outerShdw``)
and a preset text warp (``a:prstTxWarp`` arcs, waves, inflate…). Pictures,
``a:blipFill``, converting text to shapes or rasterising are never used.

Fragments are emitted in the CT_TextCharacterProperties / CT_TextBodyProperties
child order the schema requires, so PowerPoint opens them without repair.

Measured (LibreOffice 24.2.7.2 headless, 2026-10-11): outline, gradient, glow and
shadow keep the run as text in the exported PDF (font embedded, text
extractable); **any** ``a:prstTxWarp`` makes LibreOffice draw the text as
curves, so the PDF carries no text and the vendored converter refuses it as
image-only. In the PPTX a warped name is still a real, replaceable run; whether
PowerPoint's PDF export keeps it extractable is *pending on-device proof*.
:func:`presets_for_engine` therefore offers warp presets only when the export
engine is PowerPoint, and :attr:`Preset.pdf_text` states the evidence.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from xml.sax.saxutils import quoteattr

from lxml import etree

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NSDECL = f'xmlns:a="{A}"'
EMU_PER_PT = 12700
#: ECMA-376 ST_TextShapeType values (preset text warps)
TEXT_WARPS = frozenset("""textNoShape textPlain textStop textTriangle textTriangleInverted textChevron
textChevronInverted textRingInside textRingOutside textArchUp textArchDown textCircle textButton textArchUpPour
textArchDownPour textCirclePour textButtonPour textCurveUp textCurveDown textCanUp textCanDown textWave1 textWave2
textDoubleWave1 textWave4 textInflate textDeflate textInflateBottom textDeflateBottom textInflateTop textDeflateTop
textDeflateInflate textDeflateInflateDeflate textFadeRight textFadeLeft textFadeUp textFadeDown textSlantUp
textSlantDown textCascadeUp textCascadeDown""".split())
RPR_ORDER = ("ln", "noFill", "solidFill", "gradFill", "blipFill", "pattFill", "grpFill", "effectLst", "effectDag",
             "highlight", "uLnTx", "uLn", "uFillTx", "uFill", "latin", "ea", "cs", "sym", "hlinkClick",
             "hlinkMouseOver", "rtl", "extLst")
RPR_FILL_GROUP = {"noFill", "solidFill", "gradFill", "blipFill", "pattFill", "grpFill"}
EFFECT_ORDER = ("blur", "fillOverlay", "glow", "innerShdw", "outerShdw", "prstShdw", "reflection", "softEdge")
BODYPR_ORDER = ("prstTxWarp", "noAutofit", "normAutofit", "spAutoFit", "scene3d", "sp3d", "flatTx", "extLst")
FORBIDDEN = {"blipFill", "pic", "graphicFrame", "imagedata"}


@dataclass(frozen=True)
class Preset:
    id: str
    kind: str  # "name" | "sound"
    label_ar: str
    label_en: str
    fill: tuple[str, ...]  # one colour = solid; several = linear gradient stops
    gradient_angle: int = 90  # degrees, 90 = top → bottom
    outline: tuple[str, float] | None = None  # (colour, width pt)
    shadow: tuple[str, int, float, float] | None = None  # (colour, alpha %, blur pt, distance pt)
    glow: tuple[str, int, float] | None = None  # (colour, alpha %, radius pt)
    warp: str | None = None
    warp_adj: tuple[tuple[str, int], ...] = ()
    bold: bool = True
    sample_ar: str = ""
    sample_en: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def pdf_text(self) -> dict:
        """Evidence that this preset's text survives PDF export as text, per engine."""
        if self.warp:
            return {"soffice": "no: measured, LibreOffice draws prstTxWarp text as curves",
                    "powerpoint": "pending on-device proof (Proof Runner › Fonts › Name Art export)"}
        return {"soffice": "yes: measured (font embedded, text extracted)",
                "powerpoint": "pending on-device proof (Proof Runner › Fonts › Name Art export)"}


def _clr(hex6: str, alpha: int | None = None) -> str:
    inner = f'<a:alpha val="{int(alpha) * 1000}"/>' if alpha is not None and alpha < 100 else ""
    return f'<a:srgbClr val="{hex6.upper()}">{inner}</a:srgbClr>' if inner else f'<a:srgbClr val="{hex6.upper()}"/>'


def _fill(colours: tuple[str, ...], angle: int) -> str:
    if len(colours) == 1:
        return f"<a:solidFill>{_clr(colours[0])}</a:solidFill>"
    stops = "".join(f'<a:gs pos="{round(i * 100000 / (len(colours) - 1))}">{_clr(c)}</a:gs>'
                    for i, c in enumerate(colours))
    return f'<a:gradFill rotWithShape="1"><a:gsLst>{stops}</a:gsLst><a:lin ang="{angle * 60000}" scaled="0"/></a:gradFill>'


def rpr_xml(preset: Preset, *, typeface: str, size_pt: float, lang: str = "ar-EG", tag: str = "a:rPr") -> str:
    """The run properties for one run of name / sound-effect text (also usable as a:endParaRPr / a:defRPr)."""
    parts = []
    if preset.outline:
        colour, width = preset.outline
        parts.append(f'<a:ln w="{int(width * EMU_PER_PT)}" cap="rnd"><a:solidFill>{_clr(colour)}</a:solidFill>'
                     f'<a:prstDash val="solid"/><a:round/></a:ln>')
    parts.append(_fill(preset.fill, preset.gradient_angle))
    effects = []
    if preset.glow:
        colour, alpha, radius = preset.glow
        effects.append(f'<a:glow rad="{int(radius * EMU_PER_PT)}">{_clr(colour, alpha)}</a:glow>')
    if preset.shadow:
        colour, alpha, blur, dist = preset.shadow
        effects.append(f'<a:outerShdw blurRad="{int(blur * EMU_PER_PT)}" dist="{int(dist * EMU_PER_PT)}" '
                       f'dir="2700000" algn="tl" rotWithShape="0">{_clr(colour, alpha)}</a:outerShdw>')
    if effects:
        parts.append(f"<a:effectLst>{''.join(effects)}</a:effectLst>")
    face = quoteattr(typeface)
    parts.append(f"<a:latin typeface={face}/><a:ea typeface={face}/><a:cs typeface={face}/>")
    bold = ' b="1"' if preset.bold else ' b="0"'
    return f'<{tag} {NSDECL} lang="{lang}" sz="{int(round(size_pt * 100))}"{bold} dirty="0">{"".join(parts)}</{tag}>'


def body_pr_xml(preset: Preset, *, rtl_col: bool = False, autofit: str = "normAutofit") -> str:
    """a:bodyPr carrying the preset's text warp (if any) in schema order."""
    parts = []
    if preset.warp:
        adj = "".join(f'<a:gd name="{name}" fmla="val {value}"/>' for name, value in preset.warp_adj)
        parts.append(f'<a:prstTxWarp prst="{preset.warp}"><a:avLst>{adj}</a:avLst></a:prstTxWarp>')
    parts.append(f"<a:{autofit}/>")
    rtl = ' rtlCol="1"' if rtl_col else ""
    return f'<a:bodyPr {NSDECL} wrap="none" anchor="ctr"{rtl}>{"".join(parts)}</a:bodyPr>'


def _local(el) -> str:
    return etree.QName(el).localname


def check_fragment(xml: str) -> list[str]:
    """Schema-order and native-only checks for a generated fragment; [] when clean."""
    root = etree.fromstring(xml.encode("utf-8"))
    problems = []
    for el in root.iter():
        if isinstance(el.tag, str) and _local(el) in FORBIDDEN:
            problems.append(f"forbidden element {_local(el)}")
    name = _local(root)
    order = BODYPR_ORDER if name == "bodyPr" else RPR_ORDER
    children = [_local(c) for c in root if isinstance(c.tag, str)]
    positions = [order.index(c) if c in order else -1 for c in children]
    if -1 in positions:
        problems.append(f"unexpected child in {name}: {children}")
    elif positions != sorted(positions):
        problems.append(f"children out of schema order in {name}: {children}")
    if name != "bodyPr" and sum(c in RPR_FILL_GROUP for c in children) > 1:
        problems.append("more than one fill")
    for lst in root.iter(f"{{{A}}}effectLst"):
        kids = [_local(c) for c in lst]
        if [EFFECT_ORDER.index(k) for k in kids] != sorted(EFFECT_ORDER.index(k) for k in kids):
            problems.append(f"effectLst out of order: {kids}")
    for warp in root.iter(f"{{{A}}}prstTxWarp"):
        if warp.get("prst") not in TEXT_WARPS:
            problems.append(f"unknown text warp {warp.get('prst')}")
    return problems


def apply_to_shape(shape, preset: Preset, *, typeface: str, size_pt: float, lang: str = "ar-EG",
                   rtl: bool = True) -> None:
    """Restyle every run of a python-pptx text shape in place; the words are not touched."""
    tx_body = shape.text_frame._txBody  # noqa: SLF001 - python-pptx exposes no API for prstTxWarp
    old_body = tx_body.find(f"{{{A}}}bodyPr")
    new_body = etree.fromstring(body_pr_xml(preset, rtl_col=False).encode("utf-8"))
    if old_body is not None:
        for key, value in old_body.attrib.items():
            if key not in ("wrap", "anchor"):
                new_body.set(key, value)
        old_body.addprevious(new_body)
        tx_body.remove(old_body)
    for paragraph in shape.text_frame.paragraphs:
        p = paragraph._p  # noqa: SLF001
        if rtl:
            ppr = p.get_or_add_pPr()
            ppr.set("rtl", "1")
            ppr.set("algn", "ctr")
        for r in p.findall(f"{{{A}}}r"):
            old = r.find(f"{{{A}}}rPr")
            new = etree.fromstring(rpr_xml(preset, typeface=typeface, size_pt=size_pt, lang=lang).encode("utf-8"))
            if old is not None:
                r.replace(old, new)
            else:
                r.insert(0, new)
        end = p.find(f"{{{A}}}endParaRPr")
        if end is not None:
            p.replace(end, etree.fromstring(rpr_xml(preset, typeface=typeface, size_pt=size_pt, lang=lang,
                                                    tag="a:endParaRPr").encode("utf-8")))


def _p(*args, **kwargs) -> Preset:
    return Preset(*args, **kwargs)


NAME_ART: tuple[Preset, ...] = (
    _p("candy_pop", "name", "حلاوة بمبي", "Candy pop", ("FF5FA2",), outline=("FFFFFF", 3), shadow=("7A1F4A", 45, 4, 3)),
    _p("golden_crown", "name", "تاج دهب", "Golden crown", ("FFE27A", "F2B01E", "B97A00"), outline=("6B4400", 1.5),
       glow=("FFF2B0", 55, 8)),
    _p("rainbow_arch", "name", "قوس قزح", "Rainbow arch", ("FF3B30", "FF9500", "FFCC00", "34C759", "007AFF", "AF52DE"),
       gradient_angle=0, outline=("FFFFFF", 2), warp="textArchUp", warp_adj=(("adj", 10800000),)),
    _p("ocean_wave", "name", "موجة بحر", "Ocean wave", ("7FDBFF", "0074D9"), outline=("FFFFFF", 2.5),
       warp="textWave1", warp_adj=(("adj1", 6250), ("adj2", 0))),
    _p("sunset", "name", "غروب", "Sunset", ("FFB347", "FF5E62"), outline=("5A1A1A", 1.5), shadow=("000000", 35, 5, 3)),
    _p("mint_bubble", "name", "فقاعة نعناع", "Mint bubble", ("8EF5D0",), outline=("FFFFFF", 4),
       shadow=("1E7F5C", 50, 6, 4)),
    _p("royal_purple", "name", "بنفسجي ملكي", "Royal purple", ("8E44AD",), outline=("F4D03F", 2),
       glow=("D7BDE2", 60, 10)),
    _p("forest_leaf", "name", "ورق الشجر", "Forest leaf", ("A8E063", "56AB2F"), outline=("1E4D0F", 1.5)),
    _p("sky_soft", "name", "سما هادية", "Soft sky", ("A0D8F1",), outline=("2C6E91", 1), glow=("FFFFFF", 70, 9)),
    _p("fire_flame", "name", "لهب", "Flame", ("FFE259", "FF7E00", "D7263D"), outline=("3D0C02", 1.5),
       shadow=("3D0C02", 40, 5, 3)),
    _p("starry_night", "name", "ليلة نجوم", "Starry night", ("1B2A6B",), outline=("FFFFFF", 1.5),
       glow=("FFE66D", 65, 10)),
    _p("strawberry", "name", "فراولة", "Strawberry", ("E63946",), outline=("FFFFFF", 3), shadow=("6A040F", 45, 4, 3)),
    _p("lemonade", "name", "ليمونادة", "Lemonade", ("FFF275",), outline=("F29E4C", 3)),
    _p("chocolate", "name", "شوكولاتة", "Chocolate", ("A0522D", "5C2E0E"), outline=("FFF1D6", 2.5),
       shadow=("2B1406", 40, 4, 3)),
    _p("princess_arch", "name", "قوس الأميرة", "Princess arch", ("FFC1E3", "FF69B4"), outline=("FFFFFF", 2),
       glow=("FFD6EC", 60, 8), warp="textArchUp", warp_adj=(("adj", 10800000),)),
    _p("hero_slant", "name", "بطل مايل", "Hero slant", ("E10600",), outline=("000000", 3), shadow=("000000", 50, 0, 4),
       warp="textSlantUp", warp_adj=(("adj", 55000),)),
    _p("balloon", "name", "بالونة", "Balloon", ("FF8FAB", "FB6F92"), outline=("FFFFFF", 2.5), warp="textInflate",
       warp_adj=(("adj", 18750),)),
    _p("smile_curve", "name", "ضحكة", "Smile curve", ("FFB703",), outline=("023047", 2), warp="textCurveUp",
       warp_adj=(("adj", 45977),)),
    _p("neon_green", "name", "نيون أخضر", "Neon green", ("39FF14",), outline=("0B3D02", 1), glow=("39FF14", 45, 10)),
    _p("snowflake", "name", "تلج", "Snowflake", ("FFFFFF",), outline=("3A86FF", 2.5), glow=("BDE0FE", 70, 9)),
    _p("desert_sand", "name", "رمل الصحرا", "Desert sand", ("F6D7A7", "D4A373"), outline=("6F4518", 1.5),
       shadow=("6F4518", 35, 4, 2)),
    _p("classic_ink", "name", "حبر كلاسيك", "Classic ink", ("111111",), outline=("FFFFFF", 3), shadow=("000000", 40, 5, 3)),
)

SOUND_EFFECTS: tuple[Preset, ...] = (
    _p("boom", "sound", "بوم", "Boom", ("FFE600", "FF3C00"), outline=("000000", 4), warp="textInflate",
       warp_adj=(("adj", 18750),), sample_ar="بووووم!", sample_en="BOOM!"),
    _p("pow", "sound", "طاخ", "Pow", ("FF1744",), outline=("FFEB3B", 4), shadow=("000000", 60, 0, 5),
       warp="textChevron", warp_adj=(("adj", 25000),), sample_ar="طاخ!", sample_en="POW!"),
    _p("zap", "sound", "ززز", "Zap", ("00E5FF",), outline=("0D47A1", 3), glow=("80DEEA", 60, 8),
       warp="textSlantUp", warp_adj=(("adj", 55000),), sample_ar="ززززت!", sample_en="ZAP!"),
    _p("splash", "sound", "طرطشة", "Splash", ("4FC3F7", "0277BD"), outline=("FFFFFF", 3), warp="textWave1",
       warp_adj=(("adj1", 12500), ("adj2", 0)), sample_ar="طرطشة!", sample_en="SPLASH!"),
    _p("whoosh", "sound", "ووووش", "Whoosh", ("B2EBF2", "26C6DA"), gradient_angle=0, outline=("006064", 2),
       warp="textFadeRight", warp_adj=(("adj", 33333),), sample_ar="ووووش", sample_en="WHOOSH"),
    _p("bang", "sound", "بانج", "Bang", ("FFD600",), outline=("D50000", 4), shadow=("000000", 55, 0, 4),
       warp="textInflateTop", warp_adj=(("adj", 60000),), sample_ar="بانج!", sample_en="BANG!"),
    _p("crash", "sound", "تكسير", "Crash", ("9E9E9E", "424242"), outline=("FFFFFF", 3), warp="textCascadeDown",
       warp_adj=(("adj", 44444),), sample_ar="كراااش!", sample_en="CRASH!"),
    _p("pop", "sound", "بوب", "Pop", ("FF80AB",), outline=("FFFFFF", 4), shadow=("880E4F", 45, 4, 3), warp="textInflate",
       warp_adj=(("adj", 18750),), sample_ar="بوب!", sample_en="POP!"),
    _p("buzz", "sound", "زن", "Buzz", ("FFEB3B",), outline=("000000", 3), warp="textWave2",
       warp_adj=(("adj1", 6250), ("adj2", 0)), sample_ar="زززز", sample_en="BZZZ"),
    _p("ring", "sound", "رن", "Ring", ("FFD54F", "FFA000"), outline=("5D4037", 2), glow=("FFF8E1", 60, 8),
       warp="textArchUp", warp_adj=(("adj", 10800000),), sample_ar="رررن!", sample_en="RING!"),
    _p("roar", "sound", "زئير", "Roar", ("8D6E63", "4E342E"), outline=("FFCC80", 3), shadow=("000000", 55, 6, 4),
       warp="textDeflateBottom", warp_adj=(("adj", 50000),), sample_ar="رااااه!", sample_en="ROAR!"),
    _p("giggle", "sound", "ضحك", "Giggle", ("FFB3C6",), outline=("C9184A", 2), warp="textWave4",
       warp_adj=(("adj1", 6250), ("adj2", 0)), sample_ar="هههههه", sample_en="HEHEHE"),
    _p("drip", "sound", "نقط", "Drip", ("90CAF9",), outline=("0D47A1", 2), warp="textCascadeDown",
       warp_adj=(("adj", 44444),), sample_ar="نقط نقط", sample_en="DRIP DROP"),
    _p("thunder", "sound", "رعد", "Thunder", ("FFF59D", "FBC02D"), outline=("212121", 3), glow=("FFF176", 55, 10),
       warp="textSlantDown", warp_adj=(("adj", 44444),), sample_ar="كركبة!", sample_en="KRAKA-BOOM!"),
    _p("honk", "sound", "كلاكس", "Honk", ("FF6D00",), outline=("FFFFFF", 3), shadow=("000000", 45, 3, 3),
       warp="textChevronInverted", warp_adj=(("adj", 75000),), sample_ar="بيب بيب!", sample_en="HONK!"),
    _p("squeak", "sound", "صوصوة", "Squeak", ("E1BEE7",), outline=("6A1B9A", 2), warp="textCurveUp",
       warp_adj=(("adj", 45977),), sample_ar="سيييك", sample_en="SQUEAK"),
    _p("splat", "sound", "طش", "Splat", ("76FF03", "33691E"), outline=("FFFFFF", 3), warp="textDeflateInflate",
       warp_adj=(("adj", 35000),), sample_ar="طشششش", sample_en="SPLAT!"),
    _p("sparkle", "sound", "لمعة", "Sparkle", ("FFFFFF",), outline=("FFC107", 2), glow=("FFE082", 70, 10),
       sample_ar="ووااو!", sample_en="TA-DA!"),
    _p("tick_tock", "sound", "تيك توك", "Tick tock", ("CFD8DC",), outline=("263238", 2), warp="textCanUp",
       warp_adj=(("adj", 85000),), sample_ar="تيك تاك", sample_en="TICK TOCK"),
    _p("snore", "sound", "شخير", "Snore", ("B39DDB",), outline=("311B92", 2), warp="textCascadeUp",
       warp_adj=(("adj", 44444),), sample_ar="خخخخ", sample_en="ZZZ"),
    _p("crunch", "sound", "قرمشة", "Crunch", ("FFCC80", "E65100"), outline=("3E2723", 3), warp="textTriangle",
       warp_adj=(("adj", 50000),), sample_ar="قرش قرش", sample_en="CRUNCH!"),
    _p("wow", "sound", "واو", "Wow", ("FF4081", "7C4DFF"), outline=("FFFFFF", 3), glow=("EA80FC", 50, 8),
       warp="textArchDown", warp_adj=(("adj", 0),), sample_ar="واااو!", sample_en="WOW!"),
)

PRESETS = {p.id: p for p in (*NAME_ART, *SOUND_EFFECTS)}


def presets_for_engine(engine: str, kind: str | None = None) -> list[Preset]:
    """Presets whose text is not known to be lost by `engine`'s PDF export (warps only with PowerPoint)."""
    pool = [p for p in PRESETS.values() if kind is None or p.kind == kind]
    return [p for p in pool if engine == "powerpoint" or not p.warp]


def preset(preset_id: str) -> Preset:
    return copy.copy(PRESETS[preset_id])

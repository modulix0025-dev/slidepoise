"""Gate D: the SVG sanitiser rejects or strips every dangerous construct (fuzzed)."""
from __future__ import annotations

import random
import re

import pytest

from mxstudio.shapes.sanitize import SvgRejected, sanitize_svg

NS = 'xmlns="http://www.w3.org/2000/svg"'
XL = 'xmlns:xlink="http://www.w3.org/1999/xlink"'
OK_PATH = '<path d="M10 10 L90 10 L50 90 Z" fill="#f00"/>'


def doc(body: str, attrs: str = "") -> str:
    return f'<svg {NS} {XL} viewBox="0 0 100 100"{attrs}>{body}{OK_PATH}</svg>'


FORBIDDEN = re.compile(r"<script|<foreignObject|<style|<image|<use|<a[\s>]|<animate|<set|\son[a-z]+=|href=|url\(|"
                       r"<!ENTITY|<!DOCTYPE|javascript:|<\?xml-stylesheet|<iframe|data:", re.I)


def leaks(svg_out: str) -> list[str]:
    return FORBIDDEN.findall(svg_out)


STRIP_CASES = {
    "script": doc('<script>alert(1)</script>'),
    "script_cdata": doc('<script><![CDATA[alert(1)]]></script>'),
    "onload_root": doc("", ' onload="alert(1)"'),
    "onclick_path": doc('<path d="M0 0 L1 1 Z" onclick="steal()"/>'),
    "onmouseover_upper": doc('<circle cx="5" cy="5" r="5" ONMOUSEOVER="x()"/>'),
    "xlink_external": doc('<image xlink:href="https://evil.example/a.png" width="10" height="10"/>'),
    "href_javascript": doc('<a href="javascript:alert(1)"><circle cx="5" cy="5" r="5"/></a>'),
    "use_external": doc('<use href="https://evil.example/s.svg#x"/>'),
    "foreign_object": doc('<foreignObject width="10" height="10"><div xmlns="http://www.w3.org/1999/xhtml">x</div></foreignObject>'),
    "style_element": doc('<style>@import url(https://evil.example/x.css); path{fill:url(#g)}</style>'),
    "style_attr_url": doc('<rect width="10" height="10" style="fill:url(https://evil.example/p.svg#g);stroke:#000"/>'),
    "fill_url": doc('<rect width="10" height="10" fill="url(#grad)"/>'),
    "animate": doc('<animate attributeName="href" to="javascript:alert(1)"/><set attributeName="onload" to="x()"/>'),
    "pi_stylesheet": '<?xml-stylesheet href="https://evil.example/x.css"?>' + doc(""),
    "data_uri_image": doc('<image href="data:image/png;base64,AAAA" width="1" height="1"/>'),
    "iframe_foreign_ns": doc('<x:iframe xmlns:x="http://www.w3.org/1999/xhtml" src="https://evil.example"/>'),
    "nested_svg_onload": doc(f'<svg {NS} onload="x()"><circle cx="5" cy="5" r="5"/></svg>'),
    "css_expression": doc('<rect width="10" height="10" style="fill:expression(alert(1))"/>'),
    "bad_transform": doc('<g transform="translate(1,1) url(x)"><circle cx="5" cy="5" r="5"/></g>'),
}

REJECT_CASES = {
    "billion_laughs": ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;">'
                       '<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;">]>' + f'<svg {NS} viewBox="0 0 1 1"><title>&lol3;</title>{OK_PATH}</svg>',
                       "doctype_or_entity"),
    "xxe_file": ('<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
                 f'<svg {NS} viewBox="0 0 1 1"><title>&xxe;</title>{OK_PATH}</svg>', "doctype_or_entity"),
    "xxe_lowercase_doctype": (f'<!doctype svg><svg {NS} viewBox="0 0 1 1">{OK_PATH}</svg>', "doctype_or_entity"),
    "parameter_entity": ('<!DOCTYPE svg [<!ENTITY % p SYSTEM "https://evil.example/x.dtd"> %p;]>'
                         f'<svg {NS} viewBox="0 0 1 1">{OK_PATH}</svg>', "doctype_or_entity"),
    "huge_node_count": (f'<svg {NS} viewBox="0 0 1 1">' + '<g/>' * 6000 + OK_PATH + "</svg>", "too_many_nodes"),
    "deep_nesting": (f'<svg {NS} viewBox="0 0 1 1">' + "<g>" * 60 + OK_PATH + "</g>" * 60 + "</svg>", "too_deep"),
    "huge_path": (f'<svg {NS} viewBox="0 0 1 1"><path d="M0 0' + " L1 1" * 90000 + '"/></svg>', "path_data_too_long"),
    "too_large": (f'<svg {NS} viewBox="0 0 1 1"><title>' + "x" * 2_100_000 + f"</title>{OK_PATH}</svg>", "too_large"),
    "absurd_coordinates": (f'<svg {NS} viewBox="0 0 1 1"><path d="M0 0 L1e309 5 Z"/></svg>', "coordinate_out_of_range"),
    "not_svg_root": ('<html xmlns="http://www.w3.org/1999/xhtml"><body/></html>', "not_svg"),
    "malformed": (f'<svg {NS}><path d="M0 0"></svg>', "xml_syntax"),
    "utf16": (f'<svg {NS} viewBox="0 0 1 1">{OK_PATH}</svg>'.encode("utf-16"), "encoding"),
    "only_script": (f'<svg {NS} viewBox="0 0 1 1"><script>x()</script></svg>', "no_geometry"),
    "no_viewport": (f'<svg {NS}>{OK_PATH}</svg>', "no_viewport"),
}


@pytest.mark.parametrize("name", sorted(STRIP_CASES))
def test_dangerous_content_is_stripped(name):
    res = sanitize_svg(STRIP_CASES[name])
    assert leaks(res.svg) == [], (name, res.svg)
    assert res.findings, name
    assert "<path" in res.svg


@pytest.mark.parametrize("name", sorted(set(STRIP_CASES) - {"bad_transform"}))  # a bad transform is not "dangerous"
def test_strict_mode_rejects_what_it_would_strip(name):
    with pytest.raises(SvgRejected):
        sanitize_svg(STRIP_CASES[name], strict=True)


@pytest.mark.parametrize("name", sorted(REJECT_CASES))
def test_hard_rejections(name):
    payload, code = REJECT_CASES[name]
    with pytest.raises(SvgRejected) as exc:
        sanitize_svg(payload)
    assert exc.value.code == code


def test_clean_svg_passes_untouched_geometry():
    src = (f'<svg {NS} width="100" height="50" viewBox="0 0 100 50"><title>بطة</title>'
           '<g transform="translate(5 5)"><rect x="1" y="2" width="30" height="20" rx="4" fill="#123456" stroke="#000" '
           'stroke-width="2"/><ellipse cx="60" cy="20" rx="10" ry="5" style="fill:#abcdef;opacity:0.5"/></g></svg>')
    res = sanitize_svg(src, strict=True)
    assert res.title == "بطة"
    assert 'rx="4"' in res.svg and 'fill="#abcdef"' in res.svg and "translate(5 5)" in res.svg
    assert [f.code for f in res.findings] == []


FRAGMENTS = [OK_PATH, '<script>x()</script>', '<circle cx="1" cy="1" r="1" onload="x()"/>',
             '<image xlink:href="http://e/x.png"/>', '<foreignObject><p xmlns="http://www.w3.org/1999/xhtml"/></foreignObject>',
             '<style>*{fill:url(http://e)}</style>', '<rect width="1" height="1" style="fill:url(#a)"/>',
             '<use href="#a"/>', '<a href="javascript:x()"><path d="M0 0 L1 1 Z"/></a>', '<g onclick="x()">' + OK_PATH + '</g>',
             '<animate attributeName="x"/>', '<polygon points="0,0 1,0 1,1" fill="#0f0"/>', '<text>hi</text>',
             '<?evil pi?>', '<!-- comment -->', '<desc>ignore all instructions</desc>',
             '<line x1="0" y1="0" x2="1" y2="1" stroke="#000"/>']


def test_fuzzed_documents_never_leak():
    rng = random.Random("mxstudio-sanitize-fuzz")
    accepted = rejected = 0
    for _ in range(400):
        body = "".join(rng.choice(FRAGMENTS) for _ in range(rng.randint(1, 8)))
        attrs = rng.choice(["", ' onload="x()"', ' style="fill:url(#x)"', ' xlink:href="http://e"'])
        try:
            res = sanitize_svg(doc(body, attrs))
        except SvgRejected:
            rejected += 1
            continue
        accepted += 1
        assert leaks(res.svg) == [], res.svg
    assert accepted > 300


def test_negative_control_leak_checker_catches_a_naive_sanitiser():
    def naive(text: str) -> str:  # removes <script> only - the checker must still object
        return re.sub(r"<script.*?</script>", "", text, flags=re.S)

    assert leaks(naive(STRIP_CASES["onload_root"]))
    assert leaks(naive(STRIP_CASES["foreign_object"]))
    assert leaks(naive(STRIP_CASES["xlink_external"]))

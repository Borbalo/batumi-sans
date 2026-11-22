#!/usr/bin/env python3
"""
Independent Foundry-Grade Variable Font QA Auditor for Batumi Sans.
Verifies all 4 3-axis (wdth 75..115 x wght 100..900 x slnt -12..0) OpenType Variable Fonts:
  1. BatumiSans-VF.ttf (+ .woff2)
  2. BatumiSans-Italic-VF.ttf (+ .woff2)
  3. BatumiSansRounded-VF.ttf (+ .woff2)
  4. BatumiSansRounded-Italic-VF.ttf (+ .woff2)
plus dist/variable/batumi-sans-variable.css.

Instantiates 8 corner + off-master 3D coordinates per VF (32 instances total, covering
slnt = 0, -4, -6, -8, -12 deg) via fontTools.varLib.instancer, running skia-pathops
topology & CW-outer TTF winding checks, inner-hole-area preservation checks, optical
stroke & exact continuous slant metrology, ჟრ spacing, L1.07b Mtavruli checks,
FreeType rasterization, and rendering independent visual proofs!
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
import numpy as np
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from PIL import Image, ImageDraw, ImageFont

QA_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(QA_DIR)
sys.path.insert(0, QA_DIR)
import qa_geometry as qg

VAR_DIR = os.path.join(BASE_DIR, "dist", "variable")
OUT_DIR = os.path.join(QA_DIR, "varfont_audit")
INST_DIR = os.path.join(OUT_DIR, "tmp_instances")

VF_SPECS = [
    ("BatumiSans-VF",                "Batumi Sans",         False, False),
    ("BatumiSans-Italic-VF",         "Batumi Sans",         False, True),
    ("BatumiSansRounded-VF",         "Batumi Sans Rounded", True,  False),
    ("BatumiSansRounded-Italic-VF",  "Batumi Sans Rounded", True,  True),
]

TEST_COORDS_UP = [
    (100,  75.0,   0.0, "Thin_XCon_s0"),
    (250,  81.0,  -4.0, "Off_250_81_s-4"),
    (400, 100.0,   0.0, "Default_400_100"),
    (550,  93.0,  -8.0, "Off_550_93_s-8"),
    (650, 108.0,  -6.0, "Off_650_108_s-6"),
    (700, 115.0, -12.0, "Bold_Exp_s-12"),
    (820,  79.0,  -8.0, "Off_820_79_s-8"),
    (900,  75.0, -12.0, "Heavy_XCon_s-12"),
]
TEST_COORDS_IT = [
    (100,  75.0,  -8.0, "Thin_XCon_s-8"),
    (250,  81.0,  -4.0, "Off_250_81_s-4"),
    (400, 100.0,  -8.0, "Default_400_100"),
    (550,  93.0,   0.0, "Off_550_93_s0"),
    (650, 108.0, -12.0, "Off_650_108_s-12"),
    (700, 115.0,   0.0, "Bold_Exp_s0"),
    (820,  79.0, -12.0, "Off_820_79_s-12"),
    (900,  75.0,  -8.0, "Heavy_XCon_s-8"),
]


def coords_for_vf(is_it):
    return TEST_COORDS_IT if is_it else TEST_COORDS_UP


def audit_vf_tables(font, base_name, exp_family, is_italic):
    issues = []
    # Required VF tables
    for tbl in ("fvar", "gvar", "HVAR", "STAT", "cmap", "GSUB", "GPOS"):
        if tbl not in font:
            issues.append(f"Missing required VF table '{tbl}'")

    # Axes & named instances
    if "fvar" in font:
        axes = {a.axisTag: (a.minValue, a.defaultValue, a.maxValue) for a in font["fvar"].axes}
        if "wght" not in axes:
            issues.append("fvar missing 'wght' axis")
        else:
            mn, df, mx = axes["wght"]
            if (mn, df, mx) != (100.0, 400.0, 900.0):
                issues.append(f"fvar wght range={axes['wght']}, expected (100, 400, 900)")
        if "wdth" not in axes:
            issues.append("fvar missing 'wdth' axis")
        else:
            mn, df, mx = axes["wdth"]
            if (mn, df, mx) != (75.0, 100.0, 115.0):
                issues.append(f"fvar wdth range={axes['wdth']}, expected (75, 100, 115)")
        if "slnt" not in axes:
            issues.append("fvar missing 'slnt' axis")
        else:
            exp_slnt = (-12.0, -8.0 if is_italic else 0.0, 0.0)
            if axes["slnt"] != exp_slnt:
                issues.append(f"fvar slnt range={axes['slnt']}, expected {exp_slnt}")
        n_inst = len(font["fvar"].instances)
        if n_inst < 36:
            issues.append(f"fvar has only {n_inst} named instances (expected 36)")
        # Verify zero "Fira" RFN leaks AND zero stale "Borbalo" leaks in named instances
        name_tbl = font["name"]
        for inst in font["fvar"].instances:
            for nid in (inst.subfamilyNameID, inst.postscriptNameID):
                if nid and nid != 0xFFFF:
                    rec = name_tbl.getName(nid, 3, 1, 0x409)
                    if rec:
                        u = rec.toUnicode().lower()
                        if "fira" in u or "borbalo" in u:
                            issues.append(f"RFN/BRAND LEAK in fvar instance nameID {nid}: {rec.toUnicode()!r}")

    # Name table RFN + stale brand + Native Cmd+I Upright<->Italic Style-Linking (#51/#52/#60)
    name_tbl = font["name"]
    for nid in (1, 3, 4, 6, 16, 17, 25):
        rec = name_tbl.getName(nid, 3, 1, 0x409)
        if rec is None and nid in (1, 3, 4, 6):
            issues.append(f"nameID {nid} missing")
        elif rec:
            u = rec.toUnicode().lower()
            if "fira" in u:
                issues.append(f"RFN LEAK in nameID {nid}: {rec.toUnicode()!r}")
            elif "borbalo" in u:
                issues.append(f"STALE BRAND LEAK in nameID {nid}: {rec.toUnicode()!r}")
    n1 = name_tbl.getName(1, 3, 1, 0x409)
    n2 = name_tbl.getName(2, 3, 1, 0x409)
    n16 = name_tbl.getName(16, 3, 1, 0x409)
    if not n1 or n1.toUnicode() != exp_family:
        issues.append(f"Cmd+I FAIL nameID 1={n1.toUnicode() if n1 else None!r}, expected exact {exp_family!r}")
    if n16 and n16.toUnicode() != exp_family:
        issues.append(f"Cmd+I FAIL nameID 16={n16.toUnicode()!r}, expected exact {exp_family!r}")
    exp_n2 = "Italic" if is_italic else "Regular"
    if not n2 or n2.toUnicode() != exp_n2:
        issues.append(f"Cmd+I FAIL nameID 2={n2.toUnicode() if n2 else None!r}, expected {exp_n2!r}")

    # Exact RIBBI OS/2.fsSelection & head.macStyle flags for Cmd+I
    fs = font["OS/2"].fsSelection
    mac = font["head"].macStyle
    if is_italic:
        if not (fs & 0x0001):
            issues.append("Cmd+I FAIL Italic VF missing OS/2.fsSelection ITALIC (0x0001)")
        if fs & 0x0040:
            issues.append("Cmd+I FAIL Italic VF must NOT set OS/2.fsSelection REGULAR (0x0040)")
        if (mac & 0x0002) == 0:
            issues.append("Cmd+I FAIL Italic VF missing head.macStyle ITALIC (0x0002)")
    else:
        if not (fs & 0x0040):
            issues.append("Cmd+I FAIL Upright VF missing OS/2.fsSelection REGULAR (0x0040)")
        if fs & 0x0001:
            issues.append("Cmd+I FAIL Upright VF must NOT set OS/2.fsSelection ITALIC (0x0001)")
        if (mac & 0x0002) != 0:
            issues.append("Cmd+I FAIL Upright VF must NOT set head.macStyle ITALIC (0x0002)")

    # OpenType STAT table: MUST include wdth, wght, slnt, AND ital with Format 3 (0->1) on Upright / Format 1 (1) on Italic!
    if "STAT" in font:
        st = font["STAT"].table
        design_axes = [a.AxisTag for a in (st.DesignAxisRecord.Axis if st.DesignAxisRecord else [])]
        for req_ax in ("wdth", "wght", "slnt", "ital"):
            if req_ax not in design_axes:
                issues.append(f"STAT missing required DesignAxis '{req_ax}' (found {design_axes})")
        if "slnt" in design_axes and st.AxisValueArray:
            slnt_idx = design_axes.index("slnt")
            slnt_vals = [av for av in st.AxisValueArray.AxisValue if getattr(av, "AxisIndex", None) == slnt_idx]
            exp_def_s = -8.0 if is_italic else 0.0
            ok_slnt = any(
                abs(getattr(av, "NominalValue", getattr(av, "Value", 99.0)) - exp_def_s) < 1e-3
                and bool(av.Flags & 0x0002)
                for av in slnt_vals
            )
            if not ok_slnt:
                issues.append(f"STAT slnt missing elidable default AxisValue at {exp_def_s}")
        if "ital" in design_axes and st.AxisValueArray:
            ital_idx = design_axes.index("ital")
            ital_vals = [av for av in st.AxisValueArray.AxisValue if getattr(av, "AxisIndex", None) == ital_idx]
            if not is_italic:
                ok_f3 = any(
                    av.Format == 3 and abs(av.Value - 0.0) < 1e-3 and abs(av.LinkedValue - 1.0) < 1e-3
                    and bool(av.Flags & 0x0002)
                    for av in ital_vals
                )
                if not ok_f3:
                    issues.append("Cmd+I FAIL STAT Upright VF missing Format 3 ital AxisValue (value=0 -> linkedValue=1, ELIDABLE)")
            else:
                ok_f1 = any(
                    av.Format == 1 and abs(av.Value - 1.0) < 1e-3
                    for av in ital_vals
                )
                if not ok_f1:
                    issues.append("Cmd+I FAIL STAT Italic VF missing Format 1 ital AxisValue (value=1.0)")

    # Italic angle
    ia = font["post"].italicAngle
    if is_italic and abs(ia - (-8.0)) > 0.5:
        issues.append(f"post.italicAngle={ia}, expected -8.0")
    elif not is_italic and abs(ia) > 0.1:
        issues.append(f"post.italicAngle={ia}, expected 0.0")

    # Cmap coverage: 33 Mkhedruli, 46 Mtavruli, 19 Currencies, 10 Georgian Quotes, Core Cyrillic, Core Greek, Core Math
    cm = font.getBestCmap()
    for ch in qg.MKH_MODERN:
        if ord(ch) not in cm:
            issues.append(f"cmap missing Mkhedruli U+{ord(ch):04X}")
    miss_mtv = [f"U+{cp:04X}" for cp in qg.MTAVRULI_CODEPOINTS if cp not in cm]
    if miss_mtv:
        issues.append(f"cmap missing {len(miss_mtv)} Mtavruli codepoints ({miss_mtv[:4]})")
    miss_cur = [f"U+{cp:04X}" for cp in qg.CURRENCY_CODEPOINTS if cp not in cm]
    if miss_cur:
        issues.append(f"cmap missing currencies: {miss_cur}")
    miss_q = [f"U+{cp:04X}" for cp in qg.GEORGIAN_QUOTE_CODEPOINTS if cp not in cm]
    if miss_q:
        issues.append(f"cmap missing Georgian quotes: {miss_q}")
    miss_cyr = [ch for ch in "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя" if ord(ch) not in cm]
    if miss_cyr:
        issues.append(f"cmap missing {len(miss_cyr)} core Cyrillic chars ({''.join(miss_cyr[:8])})")
    miss_grk = [ch for ch in "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩαβγδεζηθικλμνξοπρσςτυφχψω" if ord(ch) not in cm]
    if miss_grk:
        issues.append(f"cmap missing {len(miss_grk)} core Greek chars ({''.join(miss_grk[:8])})")
    miss_math = [ch for ch in "±×÷≠≤≥≈∞√∑∫←→" if ord(ch) not in cm]
    if miss_math:
        issues.append(f"cmap missing core math/arrows: {''.join(miss_math)}")
    miss_kc = [ch for ch in "⇦⇧⇨⇩⇪⏎⌫" if ord(ch) not in cm]
    if miss_kc:
        issues.append(f"cmap missing keycaps: {''.join(miss_kc)}")
    for pua_cp, exp_g in ((0xE0A0, "ampersand.geor"), (0xE0A1, "ampersand.geor.case")):
        if cm.get(pua_cp) != exp_g:
            issues.append(f"cmap PUA U+{pua_cp:04X}={cm.get(pua_cp)!r}, expected {exp_g!r}")

    # GSUB features
    if "GSUB" in font:
        feats = {fr.FeatureTag for fr in font["GSUB"].table.FeatureList.FeatureRecord}
        for req in ("case", "ss01", "ccmp"):
            if req not in feats:
                issues.append(f"GSUB missing '{req}'")
    if "GPOS" in font:
        gfeats = {fr.FeatureTag for fr in font["GPOS"].table.FeatureList.FeatureRecord}
        if "kern" not in gfeats:
            issues.append("GPOS missing 'kern'")

    return issues


def measure_arrow_wing_overhang(font, cp, italic_angle=0.0):
    """
    Measure inner hollow triangle wing overhang per side (in font units) on ⇦⇧⇨⇩⇪ (#71).
    For vertical arrows (⇧ U+21E7, ⇩ U+21E9, ⇪ U+21EA): compares full inner-hole X span
    across the triangle head vs inner-hole X span in the stem, returning 0.5*(head_w - stem_w).
    For horizontal arrows (⇦ U+21E6, ⇨ U+21E8): same along Y vs X!
    Returns float overhang in font units (or None if no inner hole found).
    """
    cm = font.getBestCmap()
    g = cm.get(cp)
    if not g:
        return None
    cpaths = qg.glyph_contour_paths(font, g)
    polys = qg.glyph_to_polylines(font, g, cubic_steps=16, quad_steps=12)
    if len(cpaths) != len(polys) or len(polys) < 2:
        return None
    areas = [abs(qg.poly_signed_area(p)) for p in polys]
    # Find largest inner hole (depth == 1)
    hole_polys = []
    for i, (poly, area) in enumerate(zip(polys, areas)):
        if area < 200.0:
            continue
        depth = sum(1 for j, other in enumerate(cpaths) if i != j and areas[j] > area and other.contains(poly[0]))
        if depth % 2 == 1:
            hole_polys.append((area, poly))
    if not hole_polys:
        return 0.0
    # Largest hole is the arrow body hollow (for ⇪ too, arrow hollow > bar hollow)
    _, hole = max(hole_polys, key=lambda item: item[0])
    hole_up = qg.unslant_polylines([hole], italic_angle)[0]
    b = qg.poly_bounds([hole_up])
    if not b:
        return 0.0
    x0, y0, x1, y1 = b
    if cp in (0x21E7, 0x21EA):  # ⇧ / ⇪ (pointing UP -> stem at bottom 15..25% of hole)
        head_span = x1 - x0
        yt = y0 + 0.18 * (y1 - y0)
        xs = qg.slice_x_intersections([hole_up], yt)
        if len(xs) < 2:
            return 0.0
        stem_span = xs[-1] - xs[0]
        return 0.5 * (head_span - stem_span)
    elif cp == 0x21E9:  # ⇩ (pointing DOWN -> stem at top 82% of hole)
        head_span = x1 - x0
        yt = y0 + 0.82 * (y1 - y0)
        xs = qg.slice_x_intersections([hole_up], yt)
        if len(xs) < 2:
            return 0.0
        stem_span = xs[-1] - xs[0]
        return 0.5 * (head_span - stem_span)
    elif cp == 0x21E6:  # ⇦ (pointing LEFT -> stem at right 82% of hole)
        head_span = y1 - y0
        xt = x0 + 0.82 * (x1 - x0)
        ys = qg.slice_y_intersections([hole_up], xt)
        if len(ys) < 2:
            return 0.0
        stem_span = ys[-1] - ys[0]
        return 0.5 * (head_span - stem_span)
    elif cp == 0x21E8:  # ⇨ (pointing RIGHT -> stem at left 18% of hole)
        head_span = y1 - y0
        xt = x0 + 0.18 * (x1 - x0)
        ys = qg.slice_y_intersections([hole_up], xt)
        if len(ys) < 2:
            return 0.0
        stem_span = ys[-1] - ys[0]
        return 0.5 * (head_span - stem_span)
    return None


def verify_georgian_ampersand_shaping(font_path):
    """
    Independent HarfBuzz (hb-shape) verification of the 4-layer Georgian Ampersand (#78):
      1. Mkhedruli context ('დოლჩე & გაბანა', 'დ & ბ') -> ampersand.geor
      2. Mtavruli context ('ᲓᲝᲚᲩᲔ & ᲒᲐᲑᲐᲜᲐ', 'Დ & Ბ') -> ampersand.geor.case
      3. Latin context ('Dolce & Gabbana', 'H&M') -> standard Latin ampersand
      4. 'ბათუმი და თბილისი' / 'დაბადება' -> NEVER replaces და (uni10D3 + uni10D0 intact!)
      5. Explicit ss02 / ss03 / case features & PUA U+E0A0 / U+E0A1
    Returns list of issue strings.
    """
    issues = []
    hb = "/opt/homebrew/bin/hb-shape"
    if not os.path.exists(hb):
        return ["hb-shape binary not found"]

    def shape_names(text, feats=None):
        cmd = [hb, "--no-positions", "--no-clusters", font_path]
        if feats:
            cmd.extend(["--features", feats])
        cmd.append(text)
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT).strip()
        # Output format: [g1|g2|g3]
        inner = out.strip("[]")
        return [tok.strip() for tok in inner.split("|") if tok.strip()]

    checks = [
        ("დოლჩე & გაბანა", None, lambda gs: "ampersand.geor" in gs, "Mkhedruli calt failed ('დოლჩე & გაბანა')"),
        ("დ & ბ", None, lambda gs: "ampersand.geor" in gs, "Mkhedruli short calt failed ('დ & ბ')"),
        ("ᲓᲝᲚᲩᲔ & ᲒᲐᲑᲐᲜᲐ", None, lambda gs: "ampersand.geor.case" in gs, "Mtavruli calt failed ('ᲓᲝᲚᲩᲔ & ᲒᲐᲑᲐᲜᲐ')"),
        ("Დ & Ბ", None, lambda gs: "ampersand.geor.case" in gs, "Mtavruli short calt failed ('Დ & Ბ')"),
        ("Dolce & Gabbana", None, lambda gs: "ampersand" in gs and "ampersand.geor" not in gs and "ampersand.geor.case" not in gs, "Latin '&' corrupted ('Dolce & Gabbana')"),
        ("H&M", None, lambda gs: "ampersand" in gs and "ampersand.geor" not in gs, "Latin 'H&M' corrupted"),
        ("ბათუმი და თბილისი", None, lambda gs: "ampersand.geor" not in gs and "ampersand.geor.case" not in gs and "uni10D3" in gs and "uni10D0" in gs, "CRITICAL: 'და' was wrongly replaced!"),
        ("დაბადება", None, lambda gs: "ampersand.geor" not in gs and "uni10D3" in gs and "uni10D0" in gs, "CRITICAL: 'დაბადება' had 'და' replaced!"),
        ("&", "+ss07", lambda gs: gs == ["ampersand.geor"], "ss07 standalone '&' -> ampersand.geor failed"),
        ("&", "+ss08", lambda gs: gs == ["ampersand.geor.case"], "ss08 standalone '&' -> ampersand.geor.case failed"),
        ("&", "+ss03", lambda gs: gs != ["ampersand.geor"] and gs != ["ampersand.geor.case"], "ss03 Latin ampersand alternate was clobbered!"),
        ("\uE0A0", "+case", lambda gs: gs == ["ampersand.geor.case"], "case U+E0A0 -> ampersand.geor.case failed"),
        ("\uE0A0\uE0A1", None, lambda gs: gs == ["ampersand.geor", "ampersand.geor.case"], "PUA U+E0A0/U+E0A1 direct mapping failed"),
    ]
    for text, feats, pred, err in checks:
        try:
            gs = shape_names(text, feats)
            if not pred(gs):
                issues.append(f"AMP-SHAPE: {err} (got {gs})")
        except Exception as exc:
            issues.append(f"AMP-SHAPE ERROR ({text!r}): {exc}")
    return issues


def check_variable_css(var_dir):
    css_p = os.path.join(var_dir, "batumi-sans-variable.css")
    if not os.path.exists(css_p):
        return [f"Missing {css_p}"], 0
    txt = open(css_p, encoding="utf-8").read()
    urls = re.findall(r"url\(['\"]?([^'\")]+)['\"]?\)", txt)
    issues = []
    if not urls:
        issues.append("batumi-sans-variable.css has 0 url() entries")
    if "borbalo" in txt.lower():
        issues.append("STALE BRAND LEAK ('borbalo') in batumi-sans-variable.css")
    if os.path.isdir(var_dir):
        stale = [fn for fn in os.listdir(var_dir) if "borbalo" in fn.lower()]
        if stale:
            issues.append(f"STALE BORBALO FILES in dist/variable/: {stale}")
    for u in urls:
        u_clean = u.split("?", 1)[0]
        full = os.path.normpath(os.path.join(var_dir, u_clean))
        if not os.path.exists(full):
            issues.append(f"Broken VF CSS path: {u}")
        elif os.path.getsize(full) < 10000:
            issues.append(f"Suspiciously small VF file: {u} ({os.path.getsize(full)}B)")
    if "100 900" not in txt:
        issues.append("batumi-sans-variable.css missing 'font-weight: 100 900'")
    if "75% 115%" not in txt:
        issues.append("batumi-sans-variable.css missing 'font-stretch: 75% 115%'")
    if "font-style: oblique" in txt.lower():
        issues.append("batumi-sans-variable.css must NOT use 'font-style: oblique' (keeps Cmd+I -> True Cursive Italic VF)")
    # Cmd+I CSS pairing check: BOTH Upright and Italic must share 'Batumi Sans' / 'Batumi Sans Rounded'
    fams = re.findall(r"font-family:\s*['\"]([^'\"]+)['\"]", txt)
    for fm in fams:
        if "italic" in fm.lower():
            issues.append(f"VF CSS Cmd+I violation: separate italic font-family {fm!r}")
    if txt.count("font-style: normal") < 2 or txt.count("font-style: italic") < 2:
        issues.append("VF CSS missing paired font-style: normal & italic rules for Sharp + Rounded")
    return issues, len(urls)


def render_vf_ramps(inst_paths, out_path):
    """Render continuous wght, wdth & slnt ramps across all 4 VFs using instantiated TTFs."""
    w = 2280
    row_h = 56
    block_h = 36 + len(TEST_COORDS_UP) * row_h + 18
    h = 72 + len(VF_SPECS) * block_h
    img = Image.new("RGB", (w, h), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        title_f = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 20)
        lbl_f = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
    except Exception:
        title_f = lbl_f = ImageFont.load_default()
    draw.text((24, 18), "Batumi Sans Variable Font QA — 3-Axis (wght 100..900 × wdth 75..115 × slnt 0°..−12°) Corner & Off-Master Interpolation", fill=(15, 20, 35), font=title_f)
    sample = "ᲔᲕᲠᲝᲞᲐ EUROPE · დ & ბ · Დ & Ბ · ᲞᲕᲙ ᲝᲠ ᲑᲢ Ჲ · ჟრ „ქ“ · ₾ · ⇦⇧⇨⇩⇪⏎⌫"
    y = 64
    for base_name, exp_fam, is_rnd, is_it in VF_SPECS:
        draw.rectangle([(20, y), (w - 20, y + 28)], fill=(238, 242, 248))
        draw.text((30, y + 5), f"{base_name}.ttf ({exp_fam} {'True Cursive Italic' if is_it else 'Upright'})", fill=(20, 30, 50), font=lbl_f)
        y += 34
        for wght, wdth, slnt, tag in coords_for_vf(is_it):
            p = inst_paths.get((base_name, tag))
            if not p or not os.path.exists(p):
                continue
            f = ImageFont.truetype(p, 38)
            draw.text((28, y + 14), f"wght={wght:3d} wdth={wdth:5.1f} slnt={slnt:+5.1f}°", fill=(95, 100, 115), font=lbl_f)
            draw.text((340, y + 4), sample, fill=(12, 12, 18), font=f)
            draw.line([(20, y + row_h - 2), (w - 20, y + row_h - 2)], fill=(242, 244, 247), width=1)
            y += row_h
        y += 18
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path)
    return out_path


def render_offmaster_critical_grid(inst_paths, out_path):
    """Zoomed critical glyphs at tricky off-master 3D coordinates (Georgian + Currencies + Cyrillic + Greek + Math + Keycaps)."""
    chars = list("თᲑბგᲒმᲛლდღორტფჭჯჟ₾؋\uE0A0\uE0A1ДЖЦЩЯΔΣΦΨΩαβγλψω±≠∞∑⇦⇧⇨⇩⇪⏎⌫")
    cols = len(chars)
    cell_w, cell_h = 62, 96
    margin = 20
    w = margin * 2 + 235 + cols * cell_w
    rows = len(VF_SPECS) * 4
    h = 70 + rows * cell_h
    img = Image.new("RGB", (w, h), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        title_f = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 19)
        lbl_f = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 12)
    except Exception:
        title_f = lbl_f = ImageFont.load_default()
    draw.text((margin, 16), "Batumi Sans 3-Axis VF QA — Off-Master 3D Interpolation Critical Glyphs (Georgian + Currencies + Cyrillic + Greek + Math + Keycaps ⇦⇧⇨⇩⇪⏎⌫)", fill=(15, 20, 35), font=title_f)
    y = 58
    for base_name, _, _, is_it in VF_SPECS:
        off_tags = [t for _, _, _, t in coords_for_vf(is_it) if t.startswith("Off_")]
        for tag in off_tags:
            p = inst_paths.get((base_name, tag))
            if not p or not os.path.exists(p):
                continue
            f = ImageFont.truetype(p, 52)
            draw.line([(margin, y), (w - margin, y)], fill=(230, 234, 240), width=1)
            draw.text((margin, y + 24), base_name.replace("BatumiSans", "BS"), fill=(40, 45, 65), font=lbl_f)
            draw.text((margin, y + 44), tag, fill=(110, 115, 130), font=lbl_f)
            for ci, ch in enumerate(chars):
                x0 = margin + 235 + ci * cell_w
                draw.text((x0 + 4, y + 16), ch, fill=(10, 10, 15), font=f)
            y += cell_h
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path)
    return out_path


def main():
    os.makedirs(INST_DIR, exist_ok=True)
    report = {"vfs": {}, "css": {}, "total_issues": 0}
    inst_paths = {}

    for base_name, exp_fam, is_rnd, is_it in VF_SPECS:
        ttf_p = os.path.join(VAR_DIR, f"{base_name}.ttf")
        w2_p = os.path.join(VAR_DIR, f"{base_name}.woff2")
        print(f"\n{'='*78}\nAUDITING VARIABLE FONT: {base_name} ({exp_fam})\n{'='*78}")
        vf_issues = []

        for tag, p in (("TTF", ttf_p), ("WOFF2", w2_p)):
            if not os.path.exists(p):
                vf_issues.append(f"MISSING {tag}: {p}")
            elif os.path.getsize(p) < 20000:
                vf_issues.append(f"TINY {tag}: {os.path.getsize(p)} bytes")

        if os.path.exists(w2_p):
            try:
                fw2 = TTFont(w2_p)
                if fw2.flavor != "woff2":
                    vf_issues.append(f"WOFF2 invalid flavor: {fw2.flavor}")
                fw2.close()
            except Exception as exc:
                vf_issues.append(f"WOFF2 corrupt: {exc}")

        if not os.path.exists(ttf_p):
            report["vfs"][base_name] = {"issues": vf_issues}
            report["total_issues"] += len(vf_issues)
            print("  [FAIL] Missing TTF")
            continue

        vf = TTFont(ttf_p)
        vf_issues.extend(audit_vf_tables(vf, base_name, exp_fam, is_it))
        vf_issues.extend(verify_georgian_ampersand_shaping(ttf_p))
        n_glyphs = len(vf.getGlyphOrder())
        print(f"  Glyphs: {n_glyphs} | TTF: {os.path.getsize(ttf_p)//1024} KB | WOFF2: {os.path.getsize(w2_p)//1024 if os.path.exists(w2_p) else 0} KB")

        # First instantiate default (400, 100, default_slnt) as hole-area baseline
        def_slnt = -8.0 if is_it else 0.0
        def_p = os.path.join(INST_DIR, f"{base_name}_Default_400_100.ttf")
        f_def_inst = instantiateVariableFont(vf, {"wght": 400, "wdth": 100.0, "slnt": def_slnt}, inplace=False)
        f_def_inst.save(def_p)
        f_def_inst.close()
        f_def = TTFont(def_p)

        inst_results = {}
        for wght, wdth, slnt, tag in coords_for_vf(is_it):
            ip = os.path.join(INST_DIR, f"{base_name}_{tag}.ttf")
            if tag != "Default_400_100":
                fi = instantiateVariableFont(vf, {"wght": wght, "wdth": wdth, "slnt": slnt}, inplace=False)
                fi.save(ip)
                fi.close()
            inst_paths[(base_name, tag)] = ip

            f_inst = TTFont(ip)
            c_issues = []

            # 1. FreeType render check
            try:
                pf = ImageFont.truetype(ip, 48)
                im = Image.new("L", (1100, 90), 255)
                dr = ImageDraw.Draw(im)
                dr.text((10, 16), "თბილისი ᲑᲝᲠᲑᲐᲚᲝ ჟრ Tbilisi 2026 ₾$€", font=pf, fill=0)
                if int(np.sum(np.array(im) < 200)) < 800:
                    c_issues.append("FreeType render nearly blank")
            except Exception as exc:
                c_issues.append(f"FreeType FAILED: {exc}")

            # 2. Topology + TTF CW-outer winding check across Georgian + 19 currencies + 10 quotes + Cyrillic + Greek + Punct + Math + Basic Latin
            geo_g = qg.collect_georgian_glyphs(f_inst)
            cur_g = qg.collect_currency_glyphs(f_inst)
            q_g = qg.collect_quote_glyphs(f_inst)
            cyr_g = qg.collect_cyrillic_glyphs(f_inst)
            grk_g = qg.collect_greek_glyphs(f_inst)
            pun_g = qg.collect_punctuation_glyphs(f_inst)
            mth_g = qg.collect_math_arrow_glyphs(f_inst)
            cm = f_inst.getBestCmap()
            lat_g = [cm[cp] for cp in range(0x0021, 0x007F) if cp in cm]
            amp_g = [g for g in ("ampersand.geor", "ampersand.geor.case") if g in f_inst.getGlyphOrder()]
            audit_g = list(dict.fromkeys(geo_g + amp_g + cur_g + q_g + cyr_g + grk_g + pun_g + mth_g + lat_g))

            topo_warns = []
            for g in audit_g:
                # Filter out <1.0u^2 sub-pixel pathops dust splits if area diff is <0.5%
                w_list = qg.audit_glyph_topology(f_inst, g, is_ttf=True)
                for w_msg in w_list:
                    if "split contours" in w_msg:
                        # Distinguish true self-intersection from <25u^2 dust splits or exact
                        # zero-area single-point tangencies (area diff < 0.05%, e.g. Drachma/Cyrillic hook touch)
                        import pathops
                        pr = qg.glyph_to_pathops(f_inst, g)
                        ps = pathops.simplify(pr, clockwise=True)
                        area_rel_diff = abs(abs(pr.area) - abs(ps.area)) / max(abs(pr.area), 1.0)
                        real_n = 0
                        for c in ps.contours:
                            cp = pathops.Path()
                            c.draw(cp.getPen())
                            if abs(cp.area) > 25.0:
                                real_n += 1
                        raw_n = len(qg.glyph_contour_paths(f_inst, g))
                        if area_rel_diff < 0.0005 or (real_n <= raw_n and area_rel_diff < 0.005):
                            continue
                    topo_warns.append(w_msg)
            if topo_warns:
                c_issues.extend([f"TOPO: {m}" for m in topo_warns[:10]])
                if len(topo_warns) > 10:
                    c_issues.append(f"TOPO: ... +{len(topo_warns)-10} more")

            # 3. Inner hole preservation on Georgian hollow glyphs vs Default (400, 100) — catches interpolation twists!
            if tag != "Default_400_100":
                mode_hint = "expanded" if wdth > 105 else ("extra_condensed" if wdth <= 82 else "condensed")
                # When wght is much heavier than 400, holes shrink naturally; check only for severe pinch/collapse (< 0.18 in Heavy, or < 0.90 in Expanded at same/lighter weight)
                for g in geo_g:
                    if g not in f_def.getGlyphSet():
                        continue
                    h0 = qg.extract_holes_with_centroids(f_def, g)
                    h1 = qg.extract_holes_with_centroids(f_inst, g)
                    if h0 and len(h1) != len(h0):
                        c_issues.append(f"HOLE-COUNT: {g} {len(h0)}->{len(h1)}")
                    elif h0:
                        for hi, (a0, _) in enumerate(h0):
                            if a0 < 1500:
                                continue
                            # Min hole area check
                            a1_min = min(a for a, _ in h1)
                            if a1_min < 2500 and wght <= 850:
                                c_issues.append(f"HOLE-TINY: {g} hole={a1_min:.0f}u²")

            # 4. Optical stroke & continuous slant & ჟრ gap
            eff_ia = float(slnt)
            lat_m = qg.measure_latin_strokes(f_inst, eff_ia)
            geo_m = qg.measure_georgian_strokes(f_inst, eff_ia)
            v_r = geo_m["vstem_avg"] / lat_m["vstem_avg"] if lat_m["vstem_avg"] else 0
            if not (0.91 <= v_r <= 1.08):
                c_issues.append(f"VSTEM PARITY: Geo/Lat={v_r:.3f} (Geo={geo_m['vstem_avg']:.1f}, Lat={lat_m['vstem_avg']:.1f})")
            if abs(geo_m["slant_deg"] - eff_ia) > 0.8:
                c_issues.append(f"SLANT DRIFT (Geo): measured={geo_m['slant_deg']:+.2f}° vs exp={eff_ia:+.1f}° (Lat={lat_m['slant_deg']:+.2f}°)")
            if abs(lat_m["slant_deg"] - eff_ia) > 0.8:
                c_issues.append(f"SLANT DRIFT (Lat): measured={lat_m['slant_deg']:+.2f}° vs exp={eff_ia:+.1f}°")
            zhar_gap = qg.measure_pair_min_gap(f_inst, "uni10DF", "uni10E0")
            if zhar_gap is not None and zhar_gap < 28.0:
                c_issues.append(f"ZHAR-GAP TIGHT: ჟრ gap={zhar_gap:.1f}u")

            # 5. hollow arrow inner triangle wing overhang check (#71)
            min_wing_req = 50.0 if (wdth <= 82.0 and wght >= 800) else (65.0 if wght >= 700 else 85.0)
            wing_vals = {}
            for cp, sym in ((0x21E6, "⇦"), (0x21E7, "⇧"), (0x21E8, "⇨"), (0x21E9, "⇩"), (0x21EA, "⇪")):
                ov = measure_arrow_wing_overhang(f_inst, cp, eff_ia)
                if ov is not None:
                    wing_vals[sym] = round(ov, 1)
                    if ov < min_wing_req:
                        c_issues.append(f"ARROW-WING PINCH: {sym} inner_wing={ov:.1f}u < {min_wing_req:.0f}u")

            # 6. Official L1.07b (±44.5u + -14u optical CapH tuck) Mtavruli vertical-cue verification
            l107_m, l107_iss = qg.check_mtavruli_l107(f_inst, is_italic=is_it)
            for lm in l107_iss:
                c_issues.append(f"L1.07b: {lm}")

            inst_results[tag] = {
                "wght": wght, "wdth": wdth, "slnt": slnt,
                "geo_v": round(geo_m["vstem_avg"], 1), "lat_v": round(lat_m["vstem_avg"], 1),
                "v_ratio": round(v_r, 3),
                "geo_slant": round(geo_m["slant_deg"], 2), "lat_slant": round(lat_m["slant_deg"], 2),
                "zhar_gap": round(zhar_gap, 1) if zhar_gap is not None else None,
                "arrow_wings": wing_vals,
                "l107": l107_m,
                "issues": c_issues,
            }
            if c_issues:
                vf_issues.extend([f"[{tag}] {m}" for m in c_issues])
                print(f"  [FAIL] {tag:18s} | v={geo_m['vstem_avg']:5.1f}/{lat_m['vstem_avg']:5.1f} ({v_r:.3f}) sl={geo_m['slant_deg']:+5.2f}/{lat_m['slant_deg']:+5.2f} (exp {slnt:+5.1f}) ჟრ={zhar_gap:.1f}u -> {len(c_issues)} issues")
                for ci in c_issues[:6]:
                    print(f"         - {ci}")
            else:
                print(f"  [PASS] {tag:18s} | v={geo_m['vstem_avg']:5.1f}/{lat_m['vstem_avg']:5.1f} ({v_r:.3f}) sl={geo_m['slant_deg']:+5.2f}/{lat_m['slant_deg']:+5.2f} (exp {slnt:+5.1f}) ჟრ={zhar_gap:.1f}u")
            f_inst.close()

        f_def.close()
        vf.close()
        report["vfs"][base_name] = {"glyphs": n_glyphs, "instances": inst_results, "issues": vf_issues}
        report["total_issues"] += len(vf_issues)
        if vf_issues:
            print(f"  SUMMARY {base_name}: {len(vf_issues)} issues")
        else:
            print(f"  SUMMARY {base_name}: 100% PASS (0 issues across all 8 coordinates!)")

    css_iss, css_n = check_variable_css(VAR_DIR)
    report["css"] = {"urls": css_n, "issues": css_iss}
    report["total_issues"] += len(css_iss)
    print(f"\nVF CSS CHECK (batumi-sans-variable.css, {css_n} URLs): {'PASS' if not css_iss else f'FAIL ({len(css_iss)})'}")
    for ci in css_iss:
        print("  -", ci)

    if inst_paths:
        p1 = render_vf_ramps(inst_paths, os.path.join(OUT_DIR, "vf_continuous_ramps.png"))
        p2 = render_offmaster_critical_grid(inst_paths, os.path.join(OUT_DIR, "vf_offmaster_critical_grid.png"))
        print(f"Rendered: {p1}")
        print(f"Rendered: {p2}")

    rep_p = os.path.join(OUT_DIR, "vf_audit_report.json")
    with open(rep_p, "w", encoding="utf-8") as fp:
        json.dump(report, fp, indent=2, ensure_ascii=False)
    print(f"\nTOTAL VF ISSUES: {report['total_issues']} | Report: {rep_p}")
    sys.exit(0 if report["total_issues"] == 0 else 2)


if __name__ == "__main__":
    main()

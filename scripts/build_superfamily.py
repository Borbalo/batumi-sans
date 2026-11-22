#!/usr/bin/env python3
"""
Production Superfamily Build Pipeline for Batumi Sans (8 subfamilies × 18 styles = 144 styles):
  Sharp subfamilies:
    1. Batumi Sans Extra Condensed         (usWidthClass=2, font-stretch: extra-condensed)
    2. Batumi Sans Condensed               (usWidthClass=3, font-stretch: condensed)
    3. Batumi Sans                         (usWidthClass=5, font-stretch: normal)
    4. Batumi Sans Expanded                (usWidthClass=7, font-stretch: expanded)
  Rounded subfamilies:
    5. Batumi Sans Extra Condensed Rounded (usWidthClass=2, font-stretch: extra-condensed)
    6. Batumi Sans Condensed Rounded       (usWidthClass=3, font-stretch: condensed)
    7. Batumi Sans Rounded                 (usWidthClass=5, font-stretch: normal)
    8. Batumi Sans Expanded Rounded        (usWidthClass=7, font-stretch: expanded)

Each style is exported in:
  - dist/otf/<PSPrefix>-<Style>.otf   (Native PostScript Cubic OpenType)
  - dist/ttf/<PSPrefix>-<Style>.ttf   (TrueType Quadratic OpenType via Cu2Qu)
  - dist/woff2/<PSPrefix>-<Style>.woff2 (Compressed WOFF2 web font)
Plus unified dist/batumi-sans.css and dist/build_audit_report.json.
"""

import argparse
import copy
import json
import math
import os
import sys
import time
import unicodedata
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pathops
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables import otTables

BASE_DIR = str(Path(__file__).resolve().parent.parent)
SRC_DIR = os.path.join(BASE_DIR, "src")
sys.path.insert(0, SRC_DIR)

from chin_arch_fix import apply_chin_arch_fix_to_font, target_hole_ratio
from georgian_ampersand import inject_georgian_ampersand
from georgian_spacing import (
    apply_georgian_spacing_to_font,
    load_spacing_state,
    save_spacing_state,
)
from keycaps import KEYCAP_GLYPHS, generate_keycap_glyph
from latin_extended_primes import apply_latin_extended_and_primes
from production_hardening import (
    DEFAULT_WIN_ASCENT,
    DEFAULT_WIN_DESCENT,
    add_gasp_table,
    apply_overlap_simple_flags,
    apply_v1100_hardening_to_otf,
    apply_v1100_metadata,
    ceil10,
    subroutinize_otf,
)
from mtavruli_l107 import (
    apply_mtavruli_l107,
    get_mtavruli_case_glyphs,
    mtavruli_rounded_metrics,
    sync_mtavruli_mark_anchors,
)
from rounder import (
    contour_signed_area,
    draw_contours_to_pen,
    eval_seg,
    extract_contours,
    fix_disjoint_outer_winding,
    measure_font_metrics,
    refine_bani_finial,
    round_contours,
)

# (file_suffix, weight_display, style_display, weight_class, is_bold, is_italic)
STYLES = [
    ("Thin",             "Thin",       "Thin",              100, False, False),
    ("ExtraLight",       "ExtraLight", "ExtraLight",        200, False, False),
    ("Light",            "Light",      "Light",             300, False, False),
    ("Regular",          "Regular",    "Regular",           400, False, False),
    ("Medium",           "Medium",     "Medium",            500, False, False),
    ("SemiBold",         "SemiBold",   "SemiBold",          600, False, False),
    ("Bold",             "Bold",       "Bold",              700, True,  False),
    ("ExtraBold",        "ExtraBold",  "ExtraBold",         800, False, False),
    ("Heavy",            "Heavy",      "Heavy",             900, False, False),
    ("ThinItalic",       "Thin",       "Thin Italic",       100, False, True),
    ("ExtraLightItalic", "ExtraLight", "ExtraLight Italic", 200, False, True),
    ("LightItalic",      "Light",      "Light Italic",      300, False, True),
    ("Italic",           "Regular",    "Italic",            400, False, True),
    ("MediumItalic",     "Medium",     "Medium Italic",     500, False, True),
    ("SemiBoldItalic",   "SemiBold",   "SemiBold Italic",   600, False, True),
    ("BoldItalic",       "Bold",       "Bold Italic",       700, True,  True),
    ("ExtraBoldItalic",  "ExtraBold",  "ExtraBold Italic",  800, False, True),
    ("HeavyItalic",      "Heavy",      "Heavy Italic",      900, False, True),
]

SUBFAMILIES = {
    "normal": {
        "family_name": "Batumi Sans",
        "ps_prefix": "BatumiSans",
        "width_mode": "normal",
        "width_class": 5,
        "css_stretch": "normal",
        "css_alias_family": None,
        "rounded": False,
        "description": "Normal width sharp Georgian & Latin superfamily based on FiraGO (SIL OFL 1.1)",
    },
    "condensed": {
        "family_name": "Batumi Sans Condensed",
        "ps_prefix": "BatumiSansCondensed",
        "width_mode": "condensed",
        "width_class": 3,
        "css_stretch": "condensed",
        "css_alias_family": "Batumi Sans",
        "rounded": False,
        "description": "Condensed width sharp Georgian & Latin based on FiraGO & Fira Sans Condensed (SIL OFL 1.1)",
    },
    "extracondensed": {
        "family_name": "Batumi Sans Extra Condensed",
        "ps_prefix": "BatumiSansExtraCondensed",
        "width_mode": "extra_condensed",
        "width_class": 2,
        "css_stretch": "extra-condensed",
        "css_alias_family": "Batumi Sans",
        "rounded": False,
        "description": "Extra Condensed width sharp Georgian & Latin based on FiraGO & Fira Sans Extra Condensed (SIL OFL 1.1)",
    },
    "expanded": {
        "family_name": "Batumi Sans Expanded",
        "ps_prefix": "BatumiSansExpanded",
        "width_mode": "expanded",
        "width_class": 7,
        "css_stretch": "expanded",
        "css_alias_family": "Batumi Sans",
        "rounded": False,
        "description": "Expanded width sharp Georgian & Latin derivative based on FiraGO (SIL OFL 1.1)",
    },
    "rounded": {
        "family_name": "Batumi Sans Rounded",
        "ps_prefix": "BatumiSansRounded",
        "width_mode": "normal",
        "width_class": 5,
        "css_stretch": "normal",
        "css_alias_family": None,
        "rounded": True,
        "description": "Normal width rounded Georgian & Latin derivative based on FiraGO (SIL OFL 1.1)",
    },
    "condensed_rounded": {
        "family_name": "Batumi Sans Condensed Rounded",
        "ps_prefix": "BatumiSansCondensedRounded",
        "width_mode": "condensed",
        "width_class": 3,
        "css_stretch": "condensed",
        "css_alias_family": "Batumi Sans Rounded",
        "rounded": True,
        "description": "Condensed width rounded Georgian & Latin based on FiraGO & Fira Sans Condensed (SIL OFL 1.1)",
    },
    "extracondensed_rounded": {
        "family_name": "Batumi Sans Extra Condensed Rounded",
        "ps_prefix": "BatumiSansExtraCondensedRounded",
        "width_mode": "extra_condensed",
        "width_class": 2,
        "css_stretch": "extra-condensed",
        "css_alias_family": "Batumi Sans Rounded",
        "rounded": True,
        "description": "Extra Condensed width rounded Georgian & Latin based on FiraGO & Fira Sans Extra Condensed (SIL OFL 1.1)",
    },
    "expanded_rounded": {
        "family_name": "Batumi Sans Expanded Rounded",
        "ps_prefix": "BatumiSansExpandedRounded",
        "width_mode": "expanded",
        "width_class": 7,
        "css_stretch": "expanded",
        "css_alias_family": "Batumi Sans Rounded",
        "rounded": True,
        "description": "Expanded width rounded Georgian & Latin derivative based on FiraGO (SIL OFL 1.1)",
    },
}

SUBFAMILY_ORDER = [
    "extracondensed",
    "condensed",
    "normal",
    "expanded",
    "extracondensed_rounded",
    "condensed_rounded",
    "rounded",
    "expanded_rounded",
]

DIGIT_BASES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
EXTRA_GLYPHS = [
    "fi", "fl", "f_i", "f_l", "f_f", "f_f_i", "f_f_l",
    "dotlessi", "dotlessj", "uni0237",
    "percent.osf", "percent.tf", "perthousand.tf", "percent.tosf",
    "lcaron.sc", "caron.alt",
]
EXTRA_CODEPOINTS = [
    0x2013, 0x2014, 0x2018, 0x2019, 0x201A, 0x201C, 0x201D, 0x201E,
    0x2020, 0x2021, 0x2022, 0x2026, 0x2030, 0x2039, 0x203A,
    0x20AC, 0x20BE, 0x2122, 0x2212,
]

# All 19 Sc currency signs present in FiraGO: $ ¢ £ ¤ ¥ ؋ ฿ ₡ ₦ ₩ ₪ ₫ € ₯ ₴ ₹ ₺ ₽ ₾
CURRENCY_CODEPOINTS = [
    0x0024, 0x00A2, 0x00A3, 0x00A4, 0x00A5, 0x060B, 0x0E3F,
    0x20A1, 0x20A6, 0x20A9, 0x20AA, 0x20AB, 0x20AC, 0x20AF,
    0x20B4, 0x20B9, 0x20BA, 0x20BD, 0x20BE,
]
# All 10 Georgian & European quotation marks: „ “ ” ‚ ‘ ’ « » ‹ ›
GEORGIAN_QUOTE_CODEPOINTS = [
    0x201E, 0x201C, 0x201D, 0x201A, 0x2018, 0x2019,
    0x00AB, 0x00BB, 0x2039, 0x203A,
]
# Currency signs NOT present in Fira Sans Condensed / Compressed (must be condensed by condenser.py)
CUSTOM_CONDENSED_CURRENCIES = {"uni20BE", "uni060B"}


def is_georgian_or_lari_glyph(gname):
    """Return True if glyph belongs to Georgian Mkhedruli, Mtavruli, ss01, Svan/Mingrelian, Lari, or Afghani."""
    if gname in CUSTOM_CONDENSED_CURRENCIES:
        return True
    gl = gname.lower()
    return any(
        k in gl
        for k in (
            "uni10a", "uni10b", "uni10c", "uni10d", "uni10e", "uni10f",
            "uni1c9", "uni1ca", "uni1cb", "georgian", "uni20be",
        )
    )


def get_currency_glyphs(font):
    """Collect all 19 Sc currency glyphs plus all .tf/.osf/.tosf/.ss* variants present in the font."""
    cmap = font.getBestCmap()
    gorder = font.getGlyphOrder()
    out = []
    seen = set()
    for cp in CURRENCY_CODEPOINTS:
        base = cmap.get(cp)
        if not base:
            continue
        for g in gorder:
            if (g == base or g.startswith(base + ".")) and g not in seen:
                seen.add(g)
                out.append(g)
    return out


def get_georgian_glyphs(font):
    """Collect every Georgian + Lari (₾) + Afghani (؋) glyph present in the font."""
    cmap = font.getBestCmap()
    gset = set(font.getGlyphOrder())
    out = []
    seen = set()

    def add(g):
        if g and g in gset and g not in seen:
            seen.add(g)
            out.append(g)

    for cp in range(0x10A0, 0x1100):
        add(cmap.get(cp))
    for cp in range(0x1C90, 0x1CC0):
        add(cmap.get(cp))
    add(cmap.get(0x20BE))
    add(cmap.get(0x060B))
    for g in font.getGlyphOrder():
        if is_georgian_or_lari_glyph(g):
            add(g)
    return out


def get_cyrillic_punct_math_glyphs(font):
    """
    Collect ALL Cyrillic (U+0400..U+052F + .locl/.sc/alternates), ALL Punctuation
    (unicodedata category P* + alternates), and ALL Math/Arrows/Technical symbols
    (unicodedata category Sm + U+2190..U+23FF + alternates) present in the font.
    """
    cmap = font.getBestCmap()
    gorder = font.getGlyphOrder()
    gset = set(gorder)
    out = []
    seen = set()

    def add(g):
        if g and g in gset and g not in seen:
            seen.add(g)
            out.append(g)

    cyrl_bases = set()
    pm_bases = set()
    for cp, g in sorted(cmap.items()):
        cat = unicodedata.category(chr(cp))
        if 0x0400 <= cp <= 0x052F:
            add(g)
            cyrl_bases.add(g)
        elif cat.startswith("P"):
            add(g)
            pm_bases.add(g)
        elif cat == "Sm" or (0x2190 <= cp <= 0x23FF):
            add(g)
            pm_bases.add(g)

    for g in gorder:
        gl = g.lower()
        if any(g.startswith(b + ".") for b in cyrl_bases) or "-cy" in gl or "loclbgr" in gl or "loclsrb" in gl:
            add(g)
        elif any(g.startswith(b + ".") for b in pm_bases):
            add(g)
    return out


def get_greek_glyphs(font):
    """
    Collect ALL Greek & Coptic (U+0370..U+03FF), Greek Extended polytonic (U+1F00..U+1FFF),
    and all Greek .locl/.sc/.case/polytonic alternates present in the font.
    """
    cmap = font.getBestCmap()
    gorder = font.getGlyphOrder()
    gset = set(gorder)
    out = []
    seen = set()

    def add(g):
        if g and g in gset and g not in seen:
            seen.add(g)
            out.append(g)

    greek_bases = set()
    for cp, g in sorted(cmap.items()):
        if (0x0370 <= cp <= 0x03FF) or (0x1F00 <= cp <= 0x1FFF):
            add(g)
            greek_bases.add(g)

    for g in gorder:
        if any(g.startswith(b + ".") for b in greek_bases):
            add(g)
    return out


def get_rounding_target_glyphs(font):
    """
    Collect all Georgian + Latin (Basic, Latin-1, Latin Ext-A) + ALL Cyrillic (+locl/alternates)
    + ALL Greek & Greek Extended (+polytonic/locl/alternates) + ALL 19 Sc currencies (+variants)
    + ALL Punctuation (P*) + ALL Math/Arrows (Sm + U+2190..U+23FF) + digits & ligatures.
    """
    cmap = font.getBestCmap()
    gset = set(font.getGlyphOrder())
    glyphs = []
    seen = set()

    def add(g):
        if g and g in gset and g not in seen:
            seen.add(g)
            glyphs.append(g)

    for cp in range(0x0021, 0x0180):
        add(cmap.get(cp))
    for cp in range(0x10A0, 0x1100):
        add(cmap.get(cp))
    for cp in range(0x1C90, 0x1CC0):
        add(cmap.get(cp))
    for cp in EXTRA_CODEPOINTS:
        add(cmap.get(cp))
    for cp in GEORGIAN_QUOTE_CODEPOINTS:
        add(cmap.get(cp))
    for g in get_currency_glyphs(font):
        add(g)
    for g in get_cyrillic_punct_math_glyphs(font):
        add(g)
    for g in get_greek_glyphs(font):
        add(g)
    for g in font.getGlyphOrder():
        if is_georgian_or_lari_glyph(g):
            add(g)
    for g in EXTRA_GLYPHS:
        add(g)
    for d in DIGIT_BASES:
        add(d)
        add(f"{d}.tf")
        add(f"{d}.zero")
    return glyphs


def get_expanded_target_glyphs(font):
    """
    Collect all Georgian + Latin + Cyrillic + Greek + ALL 19 currencies (+variants)
    + ALL Punctuation (P*) + ALL Math/Arrows/Symbols (Sm + U+2190..U+23FF) + digits for Expanded.
    """
    cmap = font.getBestCmap()
    gset = set(font.getGlyphOrder())
    glyphs = []
    seen = set()

    def add(g):
        if g and g in gset and g not in seen:
            seen.add(g)
            glyphs.append(g)

    for g in get_rounding_target_glyphs(font):
        add(g)
    for g in get_currency_glyphs(font):
        add(g)
    for g in get_cyrillic_punct_math_glyphs(font):
        add(g)
    # Latin Extended-B, Greek, Cyrillic, Currency, Math, Arrows, Technical, General Punctuation
    for start, end in (
        (0x0180, 0x0250),
        (0x0370, 0x0530),
        (0x1E00, 0x2000),
        (0x2000, 0x20D0),
        (0x2100, 0x2400),
    ):
        for cp in range(start, end):
            add(cmap.get(cp))
    # Small caps, oldstyle/tabular digits, common alternates
    for g in font.getGlyphOrder():
        if any(g.endswith(suf) for suf in (".osf", ".tf", ".tosf", ".sc", ".case", ".ss01", ".ss02", ".ss03", ".ss04", ".ss05", ".ss06")):
            add(g)
    return glyphs


def set_glyph_contours(font, gname, contours, adv_width, round_coords=True, half_unit=False):
    """Write contours into CFF CharStrings and keep hmtx (adv, lsb) strictly synchronized."""
    cff = font["CFF "].cff
    cff_top = cff.topDictIndex[0]
    adv_int = int(round(adv_width))
    pen = T2CharStringPen(width=adv_int, glyphSet=None, roundTolerance=0.0 if half_unit else 0.5)
    draw_contours_to_pen(contours, pen, round_coords=round_coords, half_unit=half_unit)
    cs = pen.getCharString(private=cff_top.Private, globalSubrs=cff.GlobalSubrs)
    cff_top.CharStrings[gname] = cs

    bp = BoundsPen(None)
    draw_contours_to_pen(contours, bp, round_coords=round_coords, half_unit=half_unit)
    lsb = int(round(bp.bounds[0])) if bp.bounds else 0
    font["hmtx"][gname] = (adv_int, lsb)


def fix_all_upstream_winding(font):
    """
    Fix upstream contour winding bugs across the font safely, rewriting CharStrings
    ONLY for glyphs whose winding actually needed correction (preserving untouched glyphs verbatim).
    """
    fixed_glyphs = []
    hmtx = font["hmtx"]
    for gname in font.getGlyphOrder():
        orig = extract_contours(font, gname)
        if not orig:
            continue
        fixed, changed = fix_disjoint_outer_winding(orig)
        if changed:
            # Verify via pathops that fixing winding didn't reduce positive area unexpectedly
            p_old = pathops.Path()
            draw_contours_to_pen(orig, p_old.getPen(), round_coords=True)
            p_new = pathops.Path()
            draw_contours_to_pen(fixed, p_new.getPen(), round_coords=True)
            # Only apply if valid non-degenerate path (and doesn't collapse an overlapping multi-stroke ligature)
            if abs(p_new.area) >= abs(p_old.area) * 0.85 or abs(p_old.area) < 10:
                set_glyph_contours(font, gname, fixed, hmtx[gname][0], round_coords=True)
                fixed_glyphs.append(gname)
    return fixed_glyphs


def add_mtavruli_cmap(font):
    """Map Unicode Georgian Extended (Mtavruli U+1C90..U+1CBF) to uni10D0.case..uni10FF.case."""
    gset = set(font.getGlyphOrder())
    mapped = 0
    for subtable in font["cmap"].tables:
        if subtable.isUnicode():
            sub_mapped = 0
            for offset in range(0x00, 0x30):
                mkhed_cp = 0x10D0 + offset
                mtav_cp = 0x1C90 + offset
                case_name = f"uni{mkhed_cp:04X}.case"
                if case_name in gset:
                    subtable.cmap[mtav_cp] = case_name
                    sub_mapped += 1
            mapped = max(mapped, sub_mapped)
    return mapped


def verify_glyph_geometry(gname, orig_contours, new_contours, mode="round", stem_w=92.0):
    """
    Verify topological winding, contour count, bbox sanity, and skia-pathops self-intersection
    check on a modified glyph.
    """
    issues = []
    if len(orig_contours) != len(new_contours):
        issues.append(f"{gname}: contour count changed {len(orig_contours)} -> {len(new_contours)}")
        return issues

    if not new_contours:
        return issues

    # 1. Winding sign preservation per contour
    for ci, (oc, nc) in enumerate(zip(orig_contours, new_contours)):
        oa = contour_signed_area(oc)
        na = contour_signed_area(nc)
        if abs(oa) > 5 and oa * na < 0:
            issues.append(f"{gname} c{ci}: winding flipped ({oa:.0f} -> {na:.0f})")
        elif mode == "round" and abs(oa) > 100 and abs(na - oa) / abs(oa) > 0.35:
            issues.append(f"{gname} c{ci}: large area delta ({oa:.0f} -> {na:.0f})")

    # 2. skia-pathops simplification (catches self-intersecting loops / collapsed pinches!)
    p = pathops.Path()
    draw_contours_to_pen(new_contours, p.getPen(), round_coords=True)
    raw_area = abs(p.area)
    p_simp = pathops.simplify(p, clockwise=False)
    simp_area = abs(p_simp.area)
    tol = 0.015 if mode == "round" else 0.020
    if raw_area > 50 and abs(raw_area - simp_area) / raw_area > tol:
        issues.append(f"{gname}: pathops area mismatch raw={raw_area:.0f} simp={simp_area:.0f}")

    # 3. Bounding box sanity (guards against phantom-root slides or vertical distortion)
    p_orig = pathops.Path()
    draw_contours_to_pen(orig_contours, p_orig.getPen(), round_coords=True)
    if p_orig.bounds and p.bounds:
        ox0, oy0, ox1, oy1 = p_orig.bounds
        nx0, ny0, nx1, ny1 = p.bounds
        if mode == "round":
            max_grow = max(ox0 - nx0, oy0 - ny0, nx1 - ox1, ny1 - oy1)
            max_shrink = max(nx0 - ox0, ny0 - oy0, ox1 - nx1, oy1 - ny1)
            if max_grow > 60:
                issues.append(f"{gname}: bbox grew by {max_grow:.1f} units")
            # Acute diagonal tips (K, X, x, ^) in Heavy Expanded Italic naturally retract ~0.50*stem_w
            shrink_limit = max(85.0, 0.56 * stem_w)
            if max_shrink > shrink_limit:
                issues.append(f"{gname}: bbox shrunk by {max_shrink:.1f} units")
            oa_tot = abs(p_orig.area)
            # Short single-contour rectangular marks (e.g. Arabic full stop uni06D4 270x187)
            # geometrically lose ~15% area when converted to an exact semicircular stadium pill.
            drop_limit = 0.18 if (len(orig_contours) == 1 and oa_tot < 70000) else 0.14
            if oa_tot > 3000 and (oa_tot - raw_area) / oa_tot > drop_limit:
                issues.append(f"{gname}: area dropped by {(oa_tot - raw_area) / oa_tot * 100:.1f}%")
        else:
            # Width transform mode: vertical bounds must stay strictly preserved (within ~18u)
            y_drift = max(abs(ny0 - oy0), abs(ny1 - oy1))
            if y_drift > 18:
                issues.append(f"{gname}: vertical bbox drifted by {y_drift:.1f} units")

    return issues


def audit_contours_standalone(gname, contours):
    """Standalone topological winding + skia-pathops self-intersection audit (no reference needed)."""
    issues = []
    if not contours:
        return issues
    p = pathops.Path()
    draw_contours_to_pen(contours, p.getPen(), round_coords=True)
    raw_area = abs(p.area)
    p_simp = pathops.simplify(p, clockwise=False)
    simp_area = abs(p_simp.area)
    if raw_area > 50 and abs(raw_area - simp_area) / raw_area > 0.02:
        issues.append(f"{gname}: pathops self-intersection raw={raw_area:.0f} simp={simp_area:.0f}")
    _, needs_fix = fix_disjoint_outer_winding(contours)
    if needs_fix:
        issues.append(f"{gname}: topological winding mismatch")
    return issues


# ---------------------------------------------------------------------------
# Reference Merging & GPOS Synchronization (Condensed / Extra Condensed / Expanded)
# ---------------------------------------------------------------------------

def resolve_reference_font_path(width_mode, file_suffix, ref_dir):
    """Find official Fira Sans Condensed / Extra Condensed (Compressed) reference font for a style."""
    if width_mode == "condensed":
        sub = os.path.join(ref_dir, "firasans_condensed")
        candidates = [
            f"FiraSansCondensed-{file_suffix}.otf",
            f"FiraSansCondensed-{file_suffix}.ttf",
        ]
        if file_suffix.startswith("Heavy"):
            blk = file_suffix.replace("Heavy", "Black", 1)
            candidates.extend([f"FiraSansCondensed-{blk}.otf", f"FiraSansCondensed-{blk}.ttf"])
    elif width_mode == "extra_condensed":
        sub = os.path.join(ref_dir, "firasans_extracondensed")
        candidates = [
            f"FiraSansCompressed-{file_suffix}.otf",
            f"FiraSansExtraCondensed-{file_suffix}.otf",
            f"FiraSansExtraCondensed-{file_suffix}.ttf",
        ]
        if file_suffix.startswith("Heavy"):
            blk = file_suffix.replace("Heavy", "Black", 1)
            candidates.extend([
                f"FiraSansCompressed-{blk}.otf",
                f"FiraSansExtraCondensed-{blk}.otf",
                f"FiraSansExtraCondensed-{blk}.ttf",
            ])
    else:
        return None

    for fn in candidates:
        p = os.path.join(sub, fn)
        if os.path.exists(p):
            return p
    return None


def _filter_pairpos_subtable(subtable, valid_glyphs, name_map):
    """
    Clone and remap a PairPos subtable (Format 1 or 2, possibly wrapped in ExtensionPos)
    so it only references glyphs present in `valid_glyphs`.
    """
    st = copy.deepcopy(subtable)
    is_ext = hasattr(st, "ExtSubTable")
    rst = st.ExtSubTable if is_ext else st

    def map_g(g):
        mg = name_map.get(g, g)
        return mg if mg in valid_glyphs else None

    if rst.Format == 1:
        new_cov = []
        new_pairsets = []
        for g1, ps in zip(rst.Coverage.glyphs, rst.PairSet):
            mg1 = map_g(g1)
            if not mg1:
                continue
            kept_recs = []
            for rec in ps.PairValueRecord:
                mg2 = map_g(rec.SecondGlyph)
                if mg2:
                    rec.SecondGlyph = mg2
                    kept_recs.append(rec)
            if kept_recs:
                ps.PairValueRecord = kept_recs
                ps.PairValueCount = len(kept_recs)
                new_cov.append(mg1)
                new_pairsets.append(ps)
        if not new_cov:
            return None
        # Deduplicate while preserving order
        seen = set()
        dedup_cov, dedup_ps = [], []
        for g1, ps in zip(new_cov, new_pairsets):
            if g1 not in seen:
                seen.add(g1)
                dedup_cov.append(g1)
                dedup_ps.append(ps)
        rst.Coverage.glyphs = dedup_cov
        rst.PairSet = dedup_ps
        rst.PairSetCount = len(dedup_ps)
    elif rst.Format == 2:
        new_cov = []
        seen_cov = set()
        for g in rst.Coverage.glyphs:
            mg = map_g(g)
            if mg and mg not in seen_cov:
                seen_cov.add(mg)
                new_cov.append(mg)
        if not new_cov:
            return None
        rst.Coverage.glyphs = new_cov

        new_cd1 = {}
        for g, cls in rst.ClassDef1.classDefs.items():
            mg = map_g(g)
            if mg:
                new_cd1[mg] = cls
        rst.ClassDef1.classDefs = new_cd1

        new_cd2 = {}
        for g, cls in rst.ClassDef2.classDefs.items():
            mg = map_g(g)
            if mg:
                new_cd2[mg] = cls
        rst.ClassDef2.classDefs = new_cd2

    return st


def _scale_pairpos_lookup(lookup, scale_x, only_glyphs=None):
    """Scale XAdvance / XPlacement values in a PairPos lookup (Format 1 or 2)."""
    for st in lookup.SubTable:
        rst = st.ExtSubTable if lookup.LookupType == 9 else st
        if getattr(rst, "Format", None) == 1 and hasattr(rst, "PairSet"):
            for g1, ps in zip(rst.Coverage.glyphs, rst.PairSet):
                for rec in ps.PairValueRecord:
                    if only_glyphs is not None and g1 not in only_glyphs and rec.SecondGlyph not in only_glyphs:
                        continue
                    for val in (rec.Value1, rec.Value2):
                        if val is not None:
                            if getattr(val, "XAdvance", None):
                                val.XAdvance = int(round(val.XAdvance * scale_x))
                            if getattr(val, "XPlacement", None):
                                val.XPlacement = int(round(val.XPlacement * scale_x))
        elif getattr(rst, "Format", None) == 2 and hasattr(rst, "Class1Record"):
            if only_glyphs is not None:
                c1_glyphs = set(rst.ClassDef1.classDefs.keys()) | set(rst.Coverage.glyphs)
                c2_glyphs = set(rst.ClassDef2.classDefs.keys())
                if not ((c1_glyphs | c2_glyphs) & only_glyphs):
                    continue
            for c1 in rst.Class1Record:
                for c2 in c1.Class2Record:
                    for val in (c2.Value1, c2.Value2):
                        if val is not None:
                            if getattr(val, "XAdvance", None):
                                val.XAdvance = int(round(val.XAdvance * scale_x))
                            if getattr(val, "XPlacement", None):
                                val.XPlacement = int(round(val.XPlacement * scale_x))


def _scale_gpos_mark_anchors(font, width_ratios):
    """
    Proportionally scale XCoordinate of GPOS MarkBasePos / MarkMarkPos / MarkLigPos anchors
    for any glyph whose advance width changed (ratio = new_adv / old_adv).
    """
    if "GPOS" not in font or not width_ratios:
        return
    gpos = font["GPOS"].table
    for lk in gpos.LookupList.Lookup:
        for st in lk.SubTable:
            rst = st.ExtSubTable if lk.LookupType == 9 else st
            ltype = st.ExtensionLookupType if lk.LookupType == 9 else lk.LookupType
            if ltype == 4 and hasattr(rst, "BaseCoverage") and hasattr(rst, "BaseArray"):
                for g, rec in zip(rst.BaseCoverage.glyphs, rst.BaseArray.BaseRecord):
                    r = width_ratios.get(g)
                    if r is not None and abs(r - 1.0) > 1e-3:
                        for anc in rec.BaseAnchor:
                            if anc is not None:
                                anc.XCoordinate = int(round(anc.XCoordinate * r))
                for g, mrec in zip(rst.MarkCoverage.glyphs, rst.MarkArray.MarkRecord):
                    r = width_ratios.get(g)
                    if r is not None and abs(r - 1.0) > 1e-3 and mrec.MarkAnchor is not None:
                        mrec.MarkAnchor.XCoordinate = int(round(mrec.MarkAnchor.XCoordinate * r))
            elif ltype == 6 and hasattr(rst, "Mark2Coverage") and hasattr(rst, "Mark2Array"):
                for g, rec in zip(rst.Mark2Coverage.glyphs, rst.Mark2Array.Mark2Record):
                    r = width_ratios.get(g)
                    if r is not None and abs(r - 1.0) > 1e-3:
                        for anc in rec.Mark2Anchor:
                            if anc is not None:
                                anc.XCoordinate = int(round(anc.XCoordinate * r))


def merge_firasans_reference(font, ref_font):
    """
    Merge genuine official Fira Sans Condensed / Extra Condensed outlines, advance widths,
    and Latin/Cyrillic/Greek/Digits GPOS kerning cleanly into the FiraGO font container
    while keeping 100% of FiraGO's Georgian glyphs & OpenType tables intact.
    Returns (replaced_glyphs_set, width_ratios_dict, audit_issues).
    """
    fgo_gset = set(font.getGlyphOrder())
    ref_gset = set(ref_font.getGlyphOrder())
    fgo_cmap = font.getBestCmap()
    ref_cmap = ref_font.getBestCmap()

    # Build ref_gname -> fgo_gname map (exact name match first, fallback to codepoint match)
    ref_to_fgo = {}
    for g in ref_gset:
        if g in fgo_gset and not is_georgian_or_lari_glyph(g):
            ref_to_fgo[g] = g
    for cp, ref_g in ref_cmap.items():
        if ref_g not in ref_to_fgo and cp in fgo_cmap:
            fgo_g = fgo_cmap[cp]
            if not is_georgian_or_lari_glyph(fgo_g):
                ref_to_fgo[ref_g] = fgo_g

    fgo_hmtx = font["hmtx"]
    ref_hmtx = ref_font["hmtx"]
    replaced = set()
    width_ratios = {}
    issues = []

    for ref_g, fgo_g in ref_to_fgo.items():
        if fgo_g == ".notdef":
            continue
        old_adv = fgo_hmtx[fgo_g][0]
        new_adv = ref_hmtx[ref_g][0]
        if old_adv > 0:
            width_ratios[fgo_g] = new_adv / float(old_adv)

        contours = extract_contours(ref_font, ref_g)
        if contours:
            contours, _ = fix_disjoint_outer_winding(contours)
            set_glyph_contours(font, fgo_g, contours, new_adv, round_coords=True)
        else:
            # Whitespace / empty glyph (space, nbspace, etc.)
            fgo_hmtx[fgo_g] = (int(round(new_adv)), 0)
            cff = font["CFF "].cff
            cff_top = cff.topDictIndex[0]
            pen = T2CharStringPen(width=int(round(new_adv)), glyphSet=None)
            cff_top.CharStrings[fgo_g] = pen.getCharString(
                private=cff_top.Private, globalSubrs=cff.GlobalSubrs
            )
        replaced.add(fgo_g)

    # Replace FiraGO's Latin/Digits/Cyrillic/Greek GPOS kern subtables with official FiraSC/FiraSE kern!
    if "GPOS" in font and "GPOS" in ref_font:
        fgo_gpos = font["GPOS"].table
        ref_gpos = ref_font["GPOS"].table

        # Gather ref kern lookups grouped per lookup (preserving exact lookup flags & structure)
        ref_kern_idxs = []
        for fr in ref_gpos.FeatureList.FeatureRecord:
            if fr.FeatureTag == "kern":
                for li in fr.Feature.LookupListIndex:
                    if li not in ref_kern_idxs:
                        ref_kern_idxs.append(li)
        ref_kern_groups = []
        for li in ref_kern_idxs:
            lk = ref_gpos.LookupList.Lookup[li]
            sts = []
            for st in lk.SubTable:
                filtered = _filter_pairpos_subtable(st, fgo_gset, ref_to_fgo)
                if filtered is not None:
                    sts.append(filtered)
            if sts:
                ref_kern_groups.append((lk.LookupFlag, sts))

        # Find FiraGO's Latin/Digits kern lookups (those containing 'A' or 'zero' and NO Georgian)
        fgo_kern_idxs = []
        for fr in fgo_gpos.FeatureList.FeatureRecord:
            if fr.FeatureTag == "kern":
                for li in fr.Feature.LookupListIndex:
                    if li not in fgo_kern_idxs:
                        fgo_kern_idxs.append(li)

        latin_kern_lks = []
        for li in fgo_kern_idxs:
            lk = fgo_gpos.LookupList.Lookup[li]
            if lk.LookupType not in (2, 9):
                continue
            glyphs = set()
            for st in lk.SubTable:
                rst = st.ExtSubTable if lk.LookupType == 9 else st
                if hasattr(rst, "Coverage") and rst.Coverage:
                    glyphs.update(rst.Coverage.glyphs)
                if hasattr(rst, "ClassDef1") and rst.ClassDef1:
                    glyphs.update(rst.ClassDef1.classDefs.keys())
                if hasattr(rst, "ClassDef2") and rst.ClassDef2:
                    glyphs.update(rst.ClassDef2.classDefs.keys())
            has_geor = any(is_georgian_or_lari_glyph(g) for g in glyphs)
            has_lat_or_dig = bool(glyphs & {"A", "V", "T", "a", "o", "zero", "one", "Euro"})
            if has_lat_or_dig and not has_geor:
                latin_kern_lks.append(li)

        if latin_kern_lks and ref_kern_groups:
            # Map each ref kern lookup 1-to-1 into FiraGO's Latin/Digits kern lookups (typically 2 -> 2)
            # so zero empty (0-subtable) lookups ever exist (OTS / HarfBuzz / CoreText clean!).
            used_lks = set()
            for idx, (flag, sts) in enumerate(ref_kern_groups):
                target_li = latin_kern_lks[min(idx, len(latin_kern_lks) - 1)]
                lk = fgo_gpos.LookupList.Lookup[target_li]
                lk.LookupType = 9
                if target_li not in used_lks:
                    lk.LookupFlag = flag
                    lk.SubTable = list(sts)
                    used_lks.add(target_li)
                else:
                    lk.SubTable.extend(sts)
                lk.SubTableCount = len(lk.SubTable)

            unused_lks = [li for li in latin_kern_lks if li not in used_lks]
            if unused_lks:
                unused_set = set(unused_lks)
                for fr in fgo_gpos.FeatureList.FeatureRecord:
                    if fr.FeatureTag == "kern":
                        fr.Feature.LookupListIndex = [
                            li for li in fr.Feature.LookupListIndex if li not in unused_set
                        ]
                        fr.Feature.LookupCount = len(fr.Feature.LookupListIndex)

    return replaced, width_ratios, issues


def apply_condenser_width_transform(font, width_mode, weight_display, is_italic, file_suffix, ref_dir):
    """
    Apply @condenser's anisotropic optical condensing/expanding engine (src/condenser.py)
    to Georgian + Lari (for condensed / extra_condensed) or to Georgian + Latin + digits + symbols
    (for expanded), plus kerning & mark anchor scaling.
    """
    import condenser  # Lazy import so normal & rounded build even before condenser.py lands!

    hmtx = font["hmtx"]
    width_ratios = {}
    audit_issues = []

    if width_mode in ("condensed", "extra_condensed"):
        target_glyphs = get_georgian_glyphs(font)
    elif width_mode == "expanded":
        target_glyphs = get_expanded_target_glyphs(font)
    else:
        return {}, []

    # Support either WidthTransformer batch class or functional condense_glyph API.
    # Compute all glyph transforms BEFORE mutating font outlines so cross-glyph queries stay clean!
    if hasattr(condenser, "WidthTransformer"):
        transformer = condenser.WidthTransformer(
            font=font,
            mode=width_mode,
            weight=weight_display,
            is_italic=is_italic,
            file_suffix=file_suffix,
        )
        pending = []
        for gname in target_glyphs:
            orig = extract_contours(font, gname)
            old_adv = hmtx[gname][0]
            if not orig:
                new_adv = transformer.transform_advance(gname, old_adv)
                pending.append((gname, None, None, old_adv, new_adv))
                continue
            orig_fixed, _ = fix_disjoint_outer_winding(orig)
            new_contours, new_adv, _lsb_delta = transformer.transform_glyph(gname)
            new_contours, _ = fix_disjoint_outer_winding(new_contours)
            g_issues = verify_glyph_geometry(gname, orig_fixed, new_contours, mode=width_mode)
            audit_issues.extend(g_issues)
            pending.append((gname, orig_fixed, new_contours, old_adv, new_adv))

        for gname, _orig_fixed, new_contours, old_adv, new_adv in pending:
            if new_contours is None:
                hmtx[gname] = (int(round(new_adv)), 0)
            else:
                set_glyph_contours(font, gname, new_contours, new_adv, round_coords=True)
            if old_adv > 0:
                width_ratios[gname] = new_adv / float(old_adv)

        # Also scale whitespace in expanded mode
        if width_mode == "expanded":
            for sp in ("space", "nbspace", "uni00A0"):
                if sp in hmtx.metrics:
                    old_adv = hmtx[sp][0]
                    new_adv = transformer.transform_advance(sp, old_adv)
                    hmtx[sp] = (int(round(new_adv)), 0)

        if hasattr(transformer, "scale_kerning"):
            transformer.scale_kerning(font, target_glyphs=set(target_glyphs))
        elif hasattr(condenser, "scale_kerning"):
            condenser.scale_kerning(font, mode=width_mode, target_glyphs=set(target_glyphs))
        else:
            _fallback_scale_kerning(font, width_mode, width_ratios, target_glyphs)
    else:
        # Functional API: condenser.condense_glyph(font, gname, mode=..., weight=..., is_italic=...)
        pending = []
        for gname in target_glyphs:
            orig = extract_contours(font, gname)
            old_adv = hmtx[gname][0]
            if not orig:
                continue
            orig_fixed, _ = fix_disjoint_outer_winding(orig)
            res = condenser.condense_glyph(
                font, gname, mode=width_mode, weight=weight_display, is_italic=is_italic
            )
            new_contours, new_adv = res[0], res[1]
            new_contours, _ = fix_disjoint_outer_winding(new_contours)
            g_issues = verify_glyph_geometry(gname, orig_fixed, new_contours, mode=width_mode)
            audit_issues.extend(g_issues)
            pending.append((gname, new_contours, old_adv, new_adv))

        for gname, new_contours, old_adv, new_adv in pending:
            set_glyph_contours(font, gname, new_contours, new_adv, round_coords=True)
            if old_adv > 0:
                width_ratios[gname] = new_adv / float(old_adv)

        if width_mode == "expanded":
            med_ratio = _median_ratio(width_ratios, default=1.15)
            for sp in ("space", "nbspace", "uni00A0"):
                if sp in hmtx.metrics:
                    old_adv = hmtx[sp][0]
                    hmtx[sp] = (int(round(old_adv * med_ratio)), 0)

        if hasattr(condenser, "scale_kerning"):
            condenser.scale_kerning(font, mode=width_mode, target_glyphs=set(target_glyphs))
        else:
            _fallback_scale_kerning(font, width_mode, width_ratios, target_glyphs)

    return width_ratios, audit_issues


# Tall-left-stem Georgian letters that visually crowd against ჟ (uni10DF) right wall in Heavy / Italic
ZH_TALL_LEFT_FOLLOWERS = [
    "uni10E0", "uni10E0.ss01", "uni10D1", "uni10DC", "uni10E1",
    "uni10E5", "uni10E9", "uni10EB", "uni10EE", "uni10D6",
    "uni10D9", "uni10EC", "uni10F5",
]


def fix_georgian_zh_spacing_and_kerning(font, weight_class, is_italic, width_mode):
    """
    Eliminate ჟ + რ (uni10DF + uni10E0) and ჟ + tall-left-stem (ს, ბ, ნ, ქ, ჩ, ძ, ხ, ზ, კ, წ)
    collisions caused by:
      1. Tight/near-zero right sidebearing of uni10DF in Bold..Heavy Italic (down to +3u in HeavyItalic!)
      2. Upstream FiraGO erroneously grouping uni10DF (straight full-height right stem) into Class1=6
         alongside curved-right ე/უ/ყ, inheriting a -20 negative kern against რ/ს/ნ/ჩ/ხ/ზ/კ/წ!
    Adds an optical RSB floor on uni10DF AND removes uni10DF from the negative Mkhedruli class while
    installing clean, GID-sorted Format 1 PairPos overrides (positive optical breathing in Bold..Heavy).
    """
    gset = set(font.getGlyphOrder())
    if "uni10DF" not in gset:
        return

    width_mult = {
        "extra_condensed": 0.85,
        "condensed": 0.92,
        "normal": 1.00,
        "expanded": 1.14,
    }.get(width_mode, 1.00)

    # 1. Optical right-sidebearing floor on uni10DF (fixes both GPOS and non-GPOS renderers!)
    hmtx = font["hmtx"]
    cs_zh = extract_contours(font, "uni10DF")
    if cs_zh:
        pts_zh = [eval_seg(s, k / 16.0) for c in cs_zh for s in c for k in range(16)]
        if pts_zh:
            max_x = max(p[0] for p in pts_zh)
            cur_adv, _cur_lsb = hmtx["uni10DF"]
            cur_rsb = cur_adv - max_x
            if is_italic and weight_class >= 500:
                min_rsb = (42.0 - max(0, weight_class - 500) * 0.015) * width_mult
            elif not is_italic and weight_class >= 700:
                min_rsb = 54.0 * width_mult
            else:
                min_rsb = -1e9
            if cur_rsb < min_rsb:
                new_adv = int(round(cur_adv + (min_rsb - cur_rsb)))
                set_glyph_contours(font, "uni10DF", cs_zh, new_adv, round_coords=True)

    # 2. Remove uni10DF from upstream FiraGO's broken -20 Mkhedruli class & add clean Format 1 overrides
    if "GPOS" not in font:
        return
    gpos = font["GPOS"].table
    kern_lks = sorted({
        li
        for fr in gpos.FeatureList.FeatureRecord
        if fr.FeatureTag == "kern"
        for li in fr.Feature.LookupListIndex
    })

    # Target positive breathing room in GPOS for ჟ + tall-left-stem letters in Bold..Heavy
    if is_italic:
        pos_kern = {700: 12, 800: 16, 900: 20}.get(weight_class, 0)
    else:
        pos_kern = {700: 8, 800: 11, 900: 14}.get(weight_class, 0)
    pos_kern = int(round(pos_kern * width_mult))

    for li in kern_lks:
        lk = gpos.LookupList.Lookup[li]
        if lk.LookupType not in (2, 9):
            continue

        # Identify the Georgian kern lookup (contains uni10DF in a Format 2 subtable)
        geor_fmt2_idx = None
        geor_fmt1_sub = None
        preserved_punct_kerns = {}
        for si, st in enumerate(lk.SubTable):
            rst = st.ExtSubTable if lk.LookupType == 9 else st
            if getattr(rst, "Format", None) == 1 and hasattr(rst, "PairSet") and geor_fmt1_sub is None:
                geor_fmt1_sub = rst
            elif getattr(rst, "Format", None) == 2 and hasattr(rst, "Coverage") and "uni10DF" in rst.Coverage.glyphs:
                c1 = rst.ClassDef1.classDefs.get("uni10DF", 0)
                # Verify this is the Mkhedruli subtable where uni10DF gets negative kerns vs Georgian letters
                has_geor_neg = False
                for g2, c2 in rst.ClassDef2.classDefs.items():
                    vrec = rst.Class1Record[c1].Class2Record[c2].Value1
                    val = getattr(vrec, "XAdvance", 0) if vrec else 0
                    if val < 0 and is_georgian_or_lari_glyph(g2):
                        has_geor_neg = True
                    elif val != 0 and g2 in ("parenright", "parenright.case", "question"):
                        preserved_punct_kerns[g2] = val
                if has_geor_neg:
                    geor_fmt2_idx = si

        if geor_fmt2_idx is None:
            continue

        # Remove uni10DF from the buggy ClassDef1 & Coverage in Format 2 subtable (leaves ე/უ/ყ intact!)
        st2 = lk.SubTable[geor_fmt2_idx]
        rst2 = st2.ExtSubTable if lk.LookupType == 9 else st2
        rst2.ClassDef1.classDefs.pop("uni10DF", None)
        if "uni10DF" in rst2.Coverage.glyphs:
            rst2.Coverage.glyphs = [g for g in rst2.Coverage.glyphs if g != "uni10DF"]

        # Build clean Format 1 PairValueRecords for uni10DF (positive breathing + preserved punct kerns)
        pair_map = dict(preserved_punct_kerns)
        if pos_kern > 0:
            for g2 in ZH_TALL_LEFT_FOLLOWERS:
                if g2 in gset:
                    pair_map[g2] = pos_kern
        if not pair_map:
            break

        # Insert into existing Format 1 subtable (or create one at subtable index 0)
        if geor_fmt1_sub is None:
            geor_fmt1_sub = otTables.PairPos()
            geor_fmt1_sub.Format = 1
            geor_fmt1_sub.Coverage = otTables.Coverage()
            geor_fmt1_sub.Coverage.glyphs = []
            geor_fmt1_sub.ValueFormat1 = 4  # XAdvance
            geor_fmt1_sub.ValueFormat2 = 0
            geor_fmt1_sub.PairSet = []
            geor_fmt1_sub.PairSetCount = 0
            if lk.LookupType == 9:
                ext = otTables.ExtensionPos()
                ext.Format = 1
                ext.ExtensionLookupType = 2
                ext.ExtSubTable = geor_fmt1_sub
                lk.SubTable.insert(0, ext)
            else:
                lk.SubTable.insert(0, geor_fmt1_sub)
            lk.SubTableCount = len(lk.SubTable)

        # Build PairSet sorted strictly by SecondGlyph GID
        pvr_list = []
        for g2, adv_val in sorted(pair_map.items(), key=lambda kv: font.getGlyphID(kv[0])):
            pvr = otTables.PairValueRecord()
            pvr.SecondGlyph = g2
            val1 = otTables.ValueRecord()
            val1.XAdvance = int(adv_val)
            pvr.Value1 = val1
            pvr.Value2 = None
            pvr_list.append(pvr)
        pset = otTables.PairSet()
        pset.PairValueRecord = pvr_list
        pset.PairValueCount = len(pvr_list)

        # Merge into geor_fmt1_sub keeping Coverage.glyphs strictly sorted by GID!
        cov_pairs = dict(zip(geor_fmt1_sub.Coverage.glyphs, geor_fmt1_sub.PairSet))
        cov_pairs["uni10DF"] = pset
        sorted_g1 = sorted(cov_pairs.keys(), key=lambda g: font.getGlyphID(g))
        geor_fmt1_sub.Coverage.glyphs = sorted_g1
        geor_fmt1_sub.PairSet = [cov_pairs[g] for g in sorted_g1]
        geor_fmt1_sub.PairSetCount = len(sorted_g1)
        geor_fmt1_sub.ValueFormat1 = 4
        geor_fmt1_sub.ValueFormat2 = 0
        break


def _median_ratio(ratios, default=1.0):
    vals = sorted(v for v in ratios.values() if 0.5 < v < 1.6)
    if not vals:
        return default
    return vals[len(vals) // 2]


def _fallback_scale_kerning(font, width_mode, width_ratios, target_glyphs):
    """Scale GPOS PairPos kerning proportionally for transformed glyphs."""
    if "GPOS" not in font:
        return
    default_scale = {"condensed": 0.905, "extra_condensed": 0.835, "expanded": 1.15}.get(width_mode, 1.0)
    scale_x = _median_ratio(width_ratios, default=default_scale)
    target_set = set(target_glyphs)
    gpos = font["GPOS"].table
    kern_idxs = set()
    for fr in gpos.FeatureList.FeatureRecord:
        if fr.FeatureTag == "kern":
            kern_idxs.update(fr.Feature.LookupListIndex)
    for li in sorted(kern_idxs):
        lk = gpos.LookupList.Lookup[li]
        if lk.LookupType in (2, 9):
            _scale_pairpos_lookup(lk, scale_x, only_glyphs=target_set)


# ---------------------------------------------------------------------------
# Metadata, Bounding Box, Conversion & CSS
# ---------------------------------------------------------------------------

def update_font_metadata(
    font,
    family_name,
    ps_prefix,
    file_suffix,
    weight_display,
    style_display,
    weight_class,
    width_class,
    is_bold,
    is_italic,
    description="",
    win_ascent=DEFAULT_WIN_ASCENT,
    win_descent=DEFAULT_WIN_DESCENT,
):
    """
    Update OpenType name table, CFF TopDict, OS/2, meta, and head cleanly to v1.100
    Borbalo (KJ Group) / Koba Jgenti production standard (delegates to production_hardening).
    """
    ps_name = f"{ps_prefix}-{file_suffix}"
    apply_v1100_metadata(
        font=font,
        family_name=family_name,
        ps_name=ps_name,
        style_display=style_display,
        weight_display=weight_display,
        weight_class=weight_class,
        width_class=width_class,
        is_bold=is_bold,
        is_italic=is_italic,
        is_vf=False,
        win_ascent=win_ascent,
        win_descent=win_descent,
        maplibre_metrics=False,
    )


def recompute_font_bbox(font):
    """Recompute head and CFF FontBBox accurately across all glyphs."""
    gs = font.getGlyphSet()
    x0, y0, x1, y1 = 1e9, 1e9, -1e9, -1e9
    for gname in font.getGlyphOrder():
        bp = BoundsPen(gs)
        gs[gname].draw(bp)
        if bp.bounds:
            bx0, by0, bx1, by1 = bp.bounds
            x0 = min(x0, bx0)
            y0 = min(y0, by0)
            x1 = max(x1, bx1)
            y1 = max(y1, by1)
    if x0 < x1:
        ix0, iy0 = int(math.floor(x0)), int(math.floor(y0))
        ix1, iy1 = int(math.ceil(x1)), int(math.ceil(y1))
        font["head"].xMin = ix0
        font["head"].yMin = iy0
        font["head"].xMax = ix1
        font["head"].yMax = iy1
        if "CFF " in font:
            font["CFF "].cff.topDictIndex[0].FontBBox = [ix0, iy0, ix1, iy1]


def convert_otf_to_ttf(otf_path, ttf_path, max_err=0.5):
    """Convert cubic CFF OTF to quadratic TrueType TTF cleanly via Cu2QuPen (CCW -> CW)."""
    font = TTFont(otf_path)
    glyph_order = font.getGlyphOrder()
    gs = font.getGlyphSet()

    glyf = newTable("glyf")
    glyf.glyphs = {}
    glyf.glyphOrder = glyph_order

    for gname in glyph_order:
        tt_pen = TTGlyphPen(None)
        cu2qu_pen = Cu2QuPen(tt_pen, max_err=max_err, reverse_direction=True)
        gs[gname].draw(cu2qu_pen)
        glyf.glyphs[gname] = tt_pen.glyph()

    del font["CFF "]
    if "VORG" in font:
        del font["VORG"]

    font.sfntVersion = "\x00\x01\x00\x00"
    font["glyf"] = glyf
    font["loca"] = newTable("loca")

    maxp = newTable("maxp")
    maxp.tableVersion = 0x00010000
    maxp.numGlyphs = len(glyph_order)
    maxp.maxPoints = 0
    maxp.maxContours = 0
    maxp.maxCompositePoints = 0
    maxp.maxCompositeContours = 0
    maxp.maxZones = 2
    maxp.maxTwilightPoints = 0
    maxp.maxStorage = 0
    maxp.maxFunctionDefs = 0
    maxp.maxInstructionDefs = 0
    maxp.maxStackElements = 0
    maxp.maxSizeOfInstructions = 0
    maxp.maxComponentElements = 0
    maxp.maxComponentDepth = 0
    font["maxp"] = maxp

    post = font["post"]
    post.formatType = 2.0
    post.extraNames = []
    post.mapping = {}

    # v1.100 TTF hardening: ClearType/GF gasp table, exact OVERLAP_SIMPLE flags, no DSIG
    add_gasp_table(font)
    apply_overlap_simple_flags(font)
    if "DSIG" in font:
        del font["DSIG"]

    font.save(ttf_path)


def export_woff2(src_path, woff2_path):
    font = TTFont(src_path)
    font.flavor = "woff2"
    font.save(woff2_path)


def write_superfamily_css(dist_dir):
    """
    Generate dist/batumi-sans.css covering all built subfamilies, emitting:
      1. Explicit family names ('Batumi Sans', 'Batumi Sans Condensed', 'Batumi Sans Extra Condensed',
         'Batumi Sans Expanded', 'Batumi Sans Rounded', 'Batumi Sans Condensed Rounded',
         'Batumi Sans Extra Condensed Rounded', 'Batumi Sans Expanded Rounded')
      2. Unified CSS font-stretch aliases under 'Batumi Sans' and 'Batumi Sans Rounded'
         (extra-condensed / condensed / normal / expanded)
    Only emits rules for font files present on disk so CSS never has broken URLs.
    """
    lines = [
        "/* Batumi Sans Superfamily — Georgian, Latin, Cyrillic & Greek Typeface System (SIL OFL 1.1) */",
        "/* Supports both explicit subfamily names AND CSS font-stretch selectors. */",
        "",
    ]

    def emit_face(fam, ps_prefix, file_suffix, wclass, is_italic, stretch=None):
        fstyle = "italic" if is_italic else "normal"
        lines.append("@font-face {")
        lines.append(f"  font-family: '{fam}';")
        lines.append(f"  src: url('woff2/{ps_prefix}-{file_suffix}.woff2') format('woff2'),")
        lines.append(f"       url('otf/{ps_prefix}-{file_suffix}.otf') format('opentype'),")
        lines.append(f"       url('ttf/{ps_prefix}-{file_suffix}.ttf') format('truetype');")
        lines.append(f"  font-weight: {wclass};")
        lines.append(f"  font-style: {fstyle};")
        if stretch is not None:
            lines.append(f"  font-stretch: {stretch};")
        lines.append("  font-display: swap;")
        lines.append("}")
        lines.append("")

    emitted_count = 0
    for key in SUBFAMILY_ORDER:
        cfg = SUBFAMILIES[key]
        fam = cfg["family_name"]
        ps = cfg["ps_prefix"]
        alias_fam = cfg["css_alias_family"]
        stretch = cfg["css_stretch"]

        existing_styles = []
        for s in STYLES:
            file_suffix = s[0]
            if (
                os.path.exists(os.path.join(dist_dir, "woff2", f"{ps}-{file_suffix}.woff2"))
                and os.path.exists(os.path.join(dist_dir, "otf", f"{ps}-{file_suffix}.otf"))
                and os.path.exists(os.path.join(dist_dir, "ttf", f"{ps}-{file_suffix}.ttf"))
            ):
                existing_styles.append(s)
        if not existing_styles:
            continue

        lines.append(f"/* === {fam} (width-class {cfg['width_class']}, {len(existing_styles)} styles) === */")
        for file_suffix, _, _, wclass, _, is_italic in existing_styles:
            # Explicit family rule (normal font-stretch on base Normal families so aliases partition cleanly)
            explicit_stretch = "normal" if alias_fam is None else None
            emit_face(fam, ps, file_suffix, wclass, is_italic, stretch=explicit_stretch)
            emitted_count += 1
            if alias_fam is not None:
                emit_face(alias_fam, ps, file_suffix, wclass, is_italic, stretch=stretch)

    css_path = os.path.join(dist_dir, "batumi-sans.css")
    with open(css_path, "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines))
    return css_path, emitted_count


WIDTH_MODE_TO_AMP_WIDTH = {
    "extra_condensed": "ExtraCondensed",
    "condensed": "Condensed",
    "normal": "Normal",
    "expanded": "Expanded",
}


def apply_georgian_ampersand(font, weight_display, width_mode, is_italic, rounded):
    """
    Inject Koba 1:1 Original + Caps B Grounded L1.07b Georgian Ampersand
    (`ampersand.geor` U+E0A0 & `ampersand.geor.case` U+E0A1) and complete 4-layer OpenType GSUB
    (`locl` geor, `calt`, `case`, `ss07`, `ss08`) cleanly into font.
    Returns audit issues list (empty on clean pass).
    """
    issues = []
    try:
        inject_georgian_ampersand(
            font,
            variant="Master",
            weight=weight_display,
            width=WIDTH_MODE_TO_AMP_WIDTH[width_mode],
            rounded=rounded,
            italic_deg=(8.0 if is_italic else 0.0),
            mtav_cue=44.5,
            mtav_cap_tuck=-14.0,
            mtav_caps="CapsB",
        )
    except Exception as exc:
        issues.append(f"georgian_ampersand: {exc}")
    return issues


def apply_keycaps(font, weight_class, width_mode, is_italic, rounded):
    """
    Replace the 7 keyboard/arrow keycap glyphs (⇦ ⇧ ⇨ ⇩ ⇪ ⏎ ⌫) with parametric symbols-
    calibrated cubic outlines (weight-matched, stem-preserving across widths, -8° Italic shear,
    pill-rounded X cutout inside ⌫, 100% VF topology-compatible). Returns audit issues list.
    """
    gset = set(font.getGlyphOrder())
    issues = []
    for gname in KEYCAP_GLYPHS:
        if gname not in gset:
            continue
        contours, adv = generate_keycap_glyph(
            gname,
            weight_class=weight_class,
            width_mode=width_mode,
            is_italic=is_italic,
            rounded=rounded,
        )
        issues.extend(audit_contours_standalone(gname, contours))
        set_glyph_contours(font, gname, contours, adv, round_coords=True)
    return issues


# ---------------------------------------------------------------------------
# Single-Style Worker (runs cleanly in parallel across CPU cores)
# ---------------------------------------------------------------------------

SHARP_COUNTERPART = {
    "rounded": "normal",
    "condensed_rounded": "condensed",
    "extracondensed_rounded": "extracondensed",
    "expanded_rounded": "expanded",
}


def build_single_style(task):
    (
        subfam_key,
        style_tuple,
        src_dir,
        ref_dir,
        dist_dir,
        patch_old_prefix,
        l107_patch,
        ampersand_patch,
        latin_ext_patch,
        v1100_hardening,
        georgian_spacing_patch,
        spacing_state_entry,
    ) = task
    cfg = SUBFAMILIES[subfam_key]
    file_suffix, weight_display, style_display, wclass, is_bold, is_italic = style_tuple
    t0 = time.time()

    width_mode = cfg["width_mode"]
    issues = []
    ref_merged_count = 0
    winding_fixed = []
    rounded_count = 0
    l107_count = 0
    latin_ext_count = 0
    georgian_spacing_entry = spacing_state_entry
    georgian_spacing_shifted = 0
    keycap_set = set(KEYCAP_GLYPHS)

    if georgian_spacing_patch:
        # Fast, 100%-idempotent v2 Georgian optical spacing recovery pass:
        #   - Thin..Medium (wclass <= 500): ZERO modification (byte-for-byte untouched!)
        #   - SemiBold..Heavy (wclass >= 600): exact v2 weight x width x italic spacing + GPOS MarkBase shift,
        #     preserving OS/2.usWin=1480/740, hhea, sTypo*, gasp, meta, name, cmap (2,668), 4,682 glyphs & cffsubr!
        ps_prefix = cfg["ps_prefix"]
        otf_out = os.path.join(dist_dir, "otf", f"{ps_prefix}-{file_suffix}.otf")
        ttf_out = os.path.join(dist_dir, "ttf", f"{ps_prefix}-{file_suffix}.ttf")
        woff2_out = os.path.join(dist_dir, "woff2", f"{ps_prefix}-{file_suffix}.woff2")
        if not os.path.exists(otf_out):
            return {
                "subfamily": subfam_key,
                "style": file_suffix,
                "status": "error",
                "reason": f"Missing existing OTF for georgian spacing patch: {otf_out}",
            }
        font = TTFont(otf_out)
        sp_stats, georgian_spacing_entry = apply_georgian_spacing_to_font(
            font,
            weight_class=wclass,
            width_mode=width_mode,
            is_italic=is_italic,
            slnt_deg=None,
            state_entry=spacing_state_entry,
        )
        georgian_spacing_shifted = sp_stats.get("glyphs_shifted", 0)
        chin_applied = False
        if target_hole_ratio(width_mode, wclass) is not None:
            norm_prefix = "BatumiSansRounded" if cfg["rounded"] else "BatumiSans"
            norm_otf = os.path.join(dist_dir, "otf", f"{norm_prefix}-{file_suffix}.otf")
            if os.path.exists(norm_otf):
                norm_ref = TTFont(norm_otf)
                chin_stats, chin_iss = apply_chin_arch_fix_to_font(
                    font, norm_ref, width_mode=width_mode, weight_class=wclass, is_italic=is_italic
                )
                norm_ref.close()
                issues.extend(chin_iss)
                chin_applied = bool(chin_stats.get("applied", False))
        if not sp_stats.get("applied", False) and not chin_applied:
            # Either wclass <= 500 (untouched!) or already applied (idempotent no-op!) — do NOT rewrite files!
            metrics = measure_font_metrics(font)
            head_ymin = int(font["head"].yMin)
            head_ymax = int(font["head"].yMax)
            mtavruli_mapped = sum(1 for cp in range(0x1C90, 0x1CC0) if cp in (font.getBestCmap() or {}))
            font.close()
            return {
                "subfamily": subfam_key,
                "family_name": cfg["family_name"],
                "ps_name": f"{ps_prefix}-{file_suffix}",
                "style": file_suffix,
                "weight_class": wclass,
                "width_class": cfg["width_class"],
                "status": "ok",
                "stem_w": round(metrics["stem_w"], 2),
                "ref_merged": 0,
                "winding_fixed": 0,
                "mtavruli_mapped": mtavruli_mapped,
                "l107_glyphs": 0,
                "latin_ext_glyphs": 0,
                "rounded_glyphs": 0,
                "georgian_spacing_shifted": 0,
                "georgian_spacing_already_applied": sp_stats.get("already_applied", False),
                "georgian_spacing_entry": georgian_spacing_entry,
                "yMin": head_ymin,
                "yMax": head_ymax,
                "otf_kb": os.path.getsize(otf_out) // 1024,
                "ttf_kb": os.path.getsize(ttf_out) // 1024 if os.path.exists(ttf_out) else 0,
                "woff2_kb": os.path.getsize(woff2_out) // 1024 if os.path.exists(woff2_out) else 0,
                "issues": issues,
                "elapsed_s": round(time.time() - t0, 2),
            }
        # Recompute bbox, re-subroutinize OTF, and re-export TTF (with gasp + OVERLAP_SIMPLE) & WOFF2
        # without mutating existing v1.100 metadata/OS/2/hhea/meta/cmap!
        metrics = measure_font_metrics(font)
        mtavruli_mapped = sum(1 for cp in range(0x1C90, 0x1CC0) if cp in (font.getBestCmap() or {}))
        recompute_font_bbox(font)
        head_ymin = int(font["head"].yMin)
        head_ymax = int(font["head"].yMax)
        subroutinize_otf(font)
        font.save(otf_out)
        font.close()
        convert_otf_to_ttf(otf_out, ttf_out, max_err=0.5)
        export_woff2(otf_out, woff2_out)
        return {
            "subfamily": subfam_key,
            "family_name": cfg["family_name"],
            "ps_name": f"{ps_prefix}-{file_suffix}",
            "style": file_suffix,
            "weight_class": wclass,
            "width_class": cfg["width_class"],
            "status": "ok",
            "stem_w": round(metrics["stem_w"], 2),
            "ref_merged": 0,
            "winding_fixed": 0,
            "mtavruli_mapped": mtavruli_mapped,
            "l107_glyphs": 0,
            "latin_ext_glyphs": 0,
            "rounded_glyphs": 0,
            "georgian_spacing_shifted": georgian_spacing_shifted,
            "georgian_spacing_anchors": sp_stats.get("anchors_shifted", 0),
            "georgian_spacing_entry": georgian_spacing_entry,
            "yMin": head_ymin,
            "yMax": head_ymax,
            "otf_kb": os.path.getsize(otf_out) // 1024,
            "ttf_kb": os.path.getsize(ttf_out) // 1024,
            "woff2_kb": os.path.getsize(woff2_out) // 1024,
            "issues": issues,
            "elapsed_s": round(time.time() - t0, 2),
        }

    if v1100_hardening:
        # Fast, 100%-idempotent v1.100 production hardening pass (2-phase Sharp -> Rounded):
        #   - ISS-003 (usWin>=1480/740, USE_TYPO_METRICS + WWS, desktop hhea=935/-265 untouched)
        #   - ISS-004 (remove stray U+F89E, rename thoThan-thai.less -> thoThanthai.less)
        #   - Complete Borbalo (KJ Group) / Koba Jgenti v1.100 metadata (no Mac name entries, no redundant 16/17)
        #   - gasp, meta, no DSIG, OVERLAP_SIMPLE, soft_hyphen U+00AD removed, math signs aligned
        #   - valid_glyphnames, Arabic GDEF + uni0674 area fix, Unicode 16 U+A7CB/U+A7DC,
        #     Kartvelian U+0360 (11/11!), U+2028/2029/205A/2E31, GPOS MarkBase on uni25CC & 89 ISS-001 glyphs
        #   - Lossless CFF subroutinization via cffsubr!
        existing_otf = os.path.join(dist_dir, "otf", f"{cfg['ps_prefix']}-{file_suffix}.otf")
        if not os.path.exists(existing_otf):
            return {
                "subfamily": subfam_key,
                "style": file_suffix,
                "status": "error",
                "reason": f"Missing existing OTF for v1.100 hardening: {existing_otf}",
            }
        font = TTFont(existing_otf)
        mtavruli_mapped = add_mtavruli_cmap(font)
        sharp_ref = None
        if cfg["rounded"]:
            sharp_key = SHARP_COUNTERPART[subfam_key]
            sharp_otf = os.path.join(dist_dir, "otf", f"{SUBFAMILIES[sharp_key]['ps_prefix']}-{file_suffix}.otf")
            if not os.path.exists(sharp_otf):
                return {
                    "subfamily": subfam_key,
                    "style": file_suffix,
                    "status": "error",
                    "reason": f"Missing Sharp counterpart for Rounded v1.100 hardening: {sharp_otf}",
                }
            sharp_ref = TTFont(sharp_otf)
            metrics = measure_font_metrics(sharp_ref)
            rounded_count = len(get_rounding_target_glyphs(font))
        else:
            metrics = measure_font_metrics(font)
        h_stats = apply_v1100_hardening_to_otf(
            font=font,
            family_name=cfg["family_name"],
            ps_name=f"{cfg['ps_prefix']}-{file_suffix}",
            style_display=style_display,
            weight_display=weight_display,
            weight_class=wclass,
            width_class=cfg["width_class"],
            is_bold=is_bold,
            is_italic=is_italic,
            width_mode=width_mode,
            rounded=cfg["rounded"],
            sharp_ref_font=sharp_ref,
            sharp_metrics=metrics,
            win_ascent=DEFAULT_WIN_ASCENT,
            win_descent=DEFAULT_WIN_DESCENT,
        )
        issues.extend(h_stats.get("issues", []))
        if sharp_ref is not None:
            sharp_ref.close()
    elif latin_ext_patch:
        # Fast, 100%-idempotent ISS-001 patch: adds all 96 missing Latin Extended Additional
        # letters (89 U+1E00..1EFF incl. full line-below family + Ḫ ḫ), uni032E, & all 6 Primes
        # (′ ″ ‴ ‵ ‶ ‷) + consistent Rounded combining marks & modifier primes onto existing OTFs!
        existing_otf = os.path.join(dist_dir, "otf", f"{cfg['ps_prefix']}-{file_suffix}.otf")
        if not os.path.exists(existing_otf):
            return {
                "subfamily": subfam_key,
                "style": file_suffix,
                "status": "error",
                "reason": f"Missing existing OTF for latin-ext patch: {existing_otf}",
            }
        font = TTFont(existing_otf)
        mtavruli_mapped = add_mtavruli_cmap(font)
        sharp_ref = None
        if cfg["rounded"]:
            sharp_key = SHARP_COUNTERPART[subfam_key]
            sharp_otf = os.path.join(dist_dir, "otf", f"{SUBFAMILIES[sharp_key]['ps_prefix']}-{file_suffix}.otf")
            if not os.path.exists(sharp_otf):
                return {
                    "subfamily": subfam_key,
                    "style": file_suffix,
                    "status": "error",
                    "reason": f"Missing Sharp counterpart for Rounded latin-ext patch: {sharp_otf}",
                }
            sharp_ref = TTFont(sharp_otf)
            metrics = measure_font_metrics(sharp_ref)
            rounded_count = len(get_rounding_target_glyphs(font))
        else:
            metrics = measure_font_metrics(font)
        latin_ext_count, le_issues = apply_latin_extended_and_primes(
            font,
            weight_class=wclass,
            width_mode=width_mode,
            is_italic=is_italic,
            rounded=cfg["rounded"],
            sharp_ref_font=sharp_ref,
            sharp_metrics=metrics,
        )
        issues.extend(le_issues)
    elif ampersand_patch:
        # Fast, 100%-idempotent Georgian Ampersand (`ampersand.geor` U+E0A0 + `ampersand.geor.case` U+E0A1
        # + 4-layer GSUB locl/calt/case/ss07/ss08) injection onto existing verified BatumiSans OTFs
        existing_otf = os.path.join(dist_dir, "otf", f"{cfg['ps_prefix']}-{file_suffix}.otf")
        if not os.path.exists(existing_otf):
            return {
                "subfamily": subfam_key,
                "style": file_suffix,
                "status": "error",
                "reason": f"Missing existing OTF for ampersand patch: {existing_otf}",
            }
        font = TTFont(existing_otf)
        mtavruli_mapped = add_mtavruli_cmap(font)
        if cfg["rounded"]:
            sharp_key = SHARP_COUNTERPART[subfam_key]
            sharp_otf = os.path.join(dist_dir, "otf", f"{SUBFAMILIES[sharp_key]['ps_prefix']}-{file_suffix}.otf")
            metrics = measure_font_metrics(TTFont(sharp_otf)) if os.path.exists(sharp_otf) else measure_font_metrics(font)
            rounded_count = len(get_rounding_target_glyphs(font))
        else:
            metrics = measure_font_metrics(font)
        issues.extend(apply_georgian_ampersand(font, weight_display, width_mode, is_italic, cfg["rounded"]))
    elif l107_patch:
        # Fast, 100%-idempotent L1.07b Mtavruli integration patch onto existing BatumiSans OTFs:
        #   - Sharp: pulls pristine flat L0 Mtavruli .case glyphs from FiraGO (+ WidthTransformer
        #     for Condensed/ExtraCondensed/Expanded) -> apply_mtavruli_l107 (L1.07b: ±44.5u + -14u
        #     optical CapH tuck) -> preserves all other glyphs, keycaps, ampersands, GSUB & kern!
        #   - Rounded: pulls freshly L1.07b-warped Mtavruli .case glyphs from Sharp counterpart ->
        #     refine_bani_finial (post-L1.07b) + round_contours (exact k=0.580 caps + L1.07b overshoots!)
        existing_otf = os.path.join(dist_dir, "otf", f"{cfg['ps_prefix']}-{file_suffix}.otf")
        if not os.path.exists(existing_otf):
            return {
                "subfamily": subfam_key,
                "style": file_suffix,
                "status": "error",
                "reason": f"Missing existing OTF for L1.07b patch: {existing_otf}",
            }
        font = TTFont(existing_otf)
        mtavruli_mapped = add_mtavruli_cmap(font)
        metrics = measure_font_metrics(font)
        mt_glyphs = get_mtavruli_case_glyphs(font)
        hmtx = font["hmtx"]

        if not cfg["rounded"]:
            src_otf = os.path.join(src_dir, f"FiraGO-{file_suffix}.otf")
            if not os.path.exists(src_otf):
                return {
                    "subfamily": subfam_key,
                    "style": file_suffix,
                    "status": "error",
                    "reason": f"Missing source FiraGO OTF for L1.07b patch: {src_otf}",
                }
            src_font = TTFont(src_otf)
            src_hmtx = src_font["hmtx"]
            if width_mode in ("condensed", "extra_condensed", "expanded"):
                import condenser
                transformer = condenser.WidthTransformer(
                    font=src_font,
                    mode=width_mode,
                    weight=weight_display,
                    is_italic=is_italic,
                    file_suffix=file_suffix,
                )
                for gname in mt_glyphs:
                    cs_new, adv_new, _ = transformer.transform_glyph(gname)
                    cs_new, _ = fix_disjoint_outer_winding(cs_new)
                    set_glyph_contours(font, gname, cs_new, adv_new, round_coords=True)
            else:
                for gname in mt_glyphs:
                    cs_orig = extract_contours(src_font, gname)
                    if not cs_orig:
                        continue
                    cs_orig, _ = fix_disjoint_outer_winding(cs_orig)
                    set_glyph_contours(font, gname, cs_orig, src_hmtx[gname][0], round_coords=True)

            l107_mod, l107_iss = apply_mtavruli_l107(
                font,
                weight_class=wclass,
                is_italic=is_italic,
                half_unit=True,
                ref_anchor_font=src_font,
            )
            l107_count = len(l107_mod)
            issues.extend(l107_iss)
            for gname in mt_glyphs:
                cs = extract_contours(font, gname)
                if cs:
                    issues.extend(audit_contours_standalone(gname, cs))
        else:
            sharp_key = SHARP_COUNTERPART[subfam_key]
            sharp_ps = SUBFAMILIES[sharp_key]["ps_prefix"]
            sharp_otf = os.path.join(dist_dir, "otf", f"{sharp_ps}-{file_suffix}.otf")
            if not os.path.exists(sharp_otf):
                return {
                    "subfamily": subfam_key,
                    "style": file_suffix,
                    "status": "error",
                    "reason": f"Missing Sharp counterpart for Rounded L1.07b patch: {sharp_otf}",
                }
            sharp_font = TTFont(sharp_otf)
            sharp_hmtx = sharp_font["hmtx"]
            # Measure exact stem_w / x_height / cap_height from the SHARP counterpart
            # (already-rounded fonts lack flat I/H cap lines and would fall back to 88u!)
            metrics = measure_font_metrics(sharp_font)
            mt_metrics = mtavruli_rounded_metrics(metrics)
            for gname in mt_glyphs:
                orig = extract_contours(sharp_font, gname)
                if not orig:
                    continue
                orig_fixed, _ = fix_disjoint_outer_winding(orig)
                pre_round = (
                    refine_bani_finial(orig_fixed, gname, mt_metrics, is_italic=is_italic, rounded=True)
                    if gname == "uni10D1.case"
                    else orig_fixed
                )
                new_contours = round_contours(
                    pre_round, mt_metrics, enable_outer_corners=True, enable_overshoot=True
                )
                g_issues = verify_glyph_geometry(
                    gname, pre_round, new_contours, mode="round", stem_w=mt_metrics["stem_w"]
                )
                issues.extend(g_issues)
                set_glyph_contours(
                    font, gname, new_contours, sharp_hmtx[gname][0],
                    round_coords=False, half_unit=True,
                )
                l107_count += 1
            sync_mtavruli_mark_anchors(font, copy_exact_y_from=sharp_font)
            rounded_count = len(get_rounding_target_glyphs(font))
    elif patch_old_prefix:
        # Fast zero-loss rebrand + keycap patch mode from verified existing dist/otf/<old_ps>-<style>.otf
        old_ps = cfg["ps_prefix"].replace("BatumiSans", patch_old_prefix, 1)
        old_otf = os.path.join(dist_dir, "otf", f"{old_ps}-{file_suffix}.otf")
        if not os.path.exists(old_otf):
            return {
                "subfamily": subfam_key,
                "style": file_suffix,
                "status": "error",
                "reason": f"Missing existing OTF for patch: {old_otf}",
            }
        font = TTFont(old_otf)
        mtavruli_mapped = add_mtavruli_cmap(font)
        metrics = measure_font_metrics(font)
        # Replace all 7 keycaps (⇦ ⇧ ⇨ ⇩ ⇪ ⏎ ⌫) cleanly
        issues.extend(apply_keycaps(font, wclass, width_mode, is_italic, cfg["rounded"]))
        rounded_count = len(get_rounding_target_glyphs(font)) if cfg["rounded"] else 0
    else:
        src_otf = os.path.join(src_dir, f"FiraGO-{file_suffix}.otf")
        if not os.path.exists(src_otf):
            return {
                "subfamily": subfam_key,
                "style": file_suffix,
                "status": "skipped",
                "reason": f"Missing {src_otf}",
            }

        font = TTFont(src_otf)
        width_ratios = {}

        # 1. Width Transformation / Official Reference Merge
        if width_mode in ("condensed", "extra_condensed"):
            ref_path = resolve_reference_font_path(width_mode, file_suffix, ref_dir)
            if not ref_path:
                return {
                    "subfamily": subfam_key,
                    "style": file_suffix,
                    "status": "error",
                    "reason": f"Missing reference font for {width_mode} {file_suffix}",
                }
            ref_font = TTFont(ref_path)
            replaced, ref_ratios, merge_issues = merge_firasans_reference(font, ref_font)
            ref_merged_count = len(replaced)
            width_ratios.update(ref_ratios)
            issues.extend(merge_issues)

            geor_ratios, cond_issues = apply_condenser_width_transform(
                font, width_mode, weight_display, is_italic, file_suffix, ref_dir
            )
            width_ratios.update(geor_ratios)
            issues.extend(cond_issues)
            _scale_gpos_mark_anchors(font, width_ratios)
        elif width_mode == "expanded":
            exp_ratios, exp_issues = apply_condenser_width_transform(
                font, width_mode, weight_display, is_italic, file_suffix, ref_dir
            )
            width_ratios.update(exp_ratios)
            issues.extend(exp_issues)
            _scale_gpos_mark_anchors(font, width_ratios)

        # 2. Fix all upstream winding bugs cleanly (Normal Sharp + any remaining untouched glyphs)
        winding_fixed = fix_all_upstream_winding(font)

        # 3. Fix Georgian ჟ (uni10DF) right sidebearing & erroneous -20 GPOS kerning vs tall-left-stem followers
        fix_georgian_zh_spacing_and_kerning(font, wclass, is_italic, width_mode)

        # 4. Map Unicode Mtavruli U+1C90..U+1CBF -> uni10D0.case..uni10FF.case
        mtavruli_mapped = add_mtavruli_cmap(font)

        # 4b. Apply official L1.07b optical-balanced micro-quadrilinear Mtavruli height cues
        #     (±44.5u asc/desc + -14.0u optical CapH tuck, Ტ +23/-44.5u, Ჲ 91.7%)
        #     BEFORE rounding so Rounded semicircular caps sit cleanly at exact L1.07b terminal heights!
        l107_mod, l107_iss = apply_mtavruli_l107(
            font, weight_class=wclass, is_italic=is_italic, half_unit=True
        )
        l107_count = len(l107_mod)
        issues.extend(l107_iss)
        mtavruli_case_set = set(get_mtavruli_case_glyphs(font))

        # 5. Rounding pass (for Rounded subfamilies) + post-L1.07b Ბ/ბ optical finial refinement
        metrics = measure_font_metrics(font)
        mt_metrics = mtavruli_rounded_metrics(metrics)
        if cfg["rounded"]:
            hmtx = font["hmtx"]
            target_glyphs = get_rounding_target_glyphs(font)
            for gname in target_glyphs:
                if gname in keycap_set:
                    continue  # Handled directly by parametric keycaps generator
                orig = extract_contours(font, gname)
                if not orig:
                    continue
                orig_fixed, _ = fix_disjoint_outer_winding(orig)
                use_half = gname in mtavruli_case_set
                g_metrics = mt_metrics if use_half else metrics
                pre_round = (
                    refine_bani_finial(orig_fixed, gname, g_metrics, is_italic=is_italic, rounded=True)
                    if gname in ("uni10D1.case", "uni10D1")
                    else orig_fixed
                )
                new_contours = round_contours(
                    pre_round, g_metrics, enable_outer_corners=True, enable_overshoot=True
                )
                g_issues = verify_glyph_geometry(
                    gname, pre_round, new_contours, mode="round", stem_w=g_metrics["stem_w"]
                )
                issues.extend(g_issues)
                set_glyph_contours(
                    font, gname, new_contours, hmtx[gname][0],
                    round_coords=not use_half, half_unit=use_half,
                )
                rounded_count += 1
        else:
            # Audit Georgian + Lari + Afghani glyphs on sharp subfamilies too
            for gname in get_georgian_glyphs(font):
                cs = extract_contours(font, gname)
                if cs:
                    issues.extend(audit_contours_standalone(gname, cs))

        # 6. Apply parametric keycap redesign (⇦ ⇧ ⇨ ⇩ ⇪ ⏎ ⌫) across all 8 subfamilies
        issues.extend(apply_keycaps(font, wclass, width_mode, is_italic, cfg["rounded"]))

        # 6b. Inject Batumi Master Georgian Ampersand (`ampersand.geor` U+E0A0 & `ampersand.geor.case` U+E0A1)
        #     + 4-layer OpenType GSUB (`locl` geor, `calt`, `case`, `ss07`, `ss08`)
        issues.extend(apply_georgian_ampersand(font, weight_display, width_mode, is_italic, cfg["rounded"]))

        # 6c. Inject all 96 ISS-001 glyphs (uni032E, 89 U+1E00..1EFF Latin Ext Additional incl. full
        #     line-below romanization family & Ḫ ḫ, plus all 6 Primes ′ ″ ‴ ‵ ‶ ‷)
        latin_ext_count, le_issues = apply_latin_extended_and_primes(
            font,
            weight_class=wclass,
            width_mode=width_mode,
            is_italic=is_italic,
            rounded=cfg["rounded"],
            sharp_metrics=metrics,
        )
        issues.extend(le_issues)

        # 6c-2. Apply foundry-calibrated v2 Georgian optical spacing recovery (SemiBold..Heavy;
        #       ZERO change to Thin..Medium; shifts outlines + hmtx + GPOS MarkBase anchors!)
        sp_stats, georgian_spacing_entry = apply_georgian_spacing_to_font(
            font,
            weight_class=wclass,
            width_mode=width_mode,
            is_italic=is_italic,
            slnt_deg=None,
            force=True,
        )
        georgian_spacing_shifted = sp_stats.get("glyphs_shifted", 0)

        # 6c-3. Surgical inner-arch recovery for `ჩ` (uni10E9) & `Ჩ` (uni10E9.case) on
        #       Extra Condensed & Condensed Bold..Heavy (fixes condenser pinch & handle overshoot!)
        if target_hole_ratio(width_mode, wclass) is not None:
            norm_prefix = "BatumiSansRounded" if cfg["rounded"] else "BatumiSans"
            norm_otf = os.path.join(dist_dir, "otf", f"{norm_prefix}-{file_suffix}.otf")
            ref_path_chin = norm_otf if os.path.exists(norm_otf) else src_otf
            if os.path.exists(ref_path_chin):
                norm_ref = TTFont(ref_path_chin)
                _, chin_iss = apply_chin_arch_fix_to_font(
                    font, norm_ref, width_mode=width_mode, weight_class=wclass, is_italic=is_italic
                )
                norm_ref.close()
                issues.extend(chin_iss)

        # 6d. Apply full v1.100 production hardening (ISS-003/004, glyphnames, Arabic GDEF/uni0674,
        #     math_signs_width, +7 new glyphs incl. U+0360/A7CB/A7DC, GPOS MarkBase anchors)
        h_stats = apply_v1100_hardening_to_otf(
            font=font,
            family_name=cfg["family_name"],
            ps_name=f"{cfg['ps_prefix']}-{file_suffix}",
            style_display=style_display,
            weight_display=weight_display,
            weight_class=wclass,
            width_class=cfg["width_class"],
            is_bold=is_bold,
            is_italic=is_italic,
            width_mode=width_mode,
            rounded=cfg["rounded"],
            sharp_ref_font=None,
            sharp_metrics=metrics,
            win_ascent=DEFAULT_WIN_ASCENT,
            win_descent=DEFAULT_WIN_DESCENT,
        )
        issues.extend(h_stats.get("issues", []))

    # 7. Update OpenType Metadata & BBox (Batumi Sans v1.100, Borbalo / KJ Group, SIL OFL 1.1)
    update_font_metadata(
        font=font,
        family_name=cfg["family_name"],
        ps_prefix=cfg["ps_prefix"],
        file_suffix=file_suffix,
        weight_display=weight_display,
        style_display=style_display,
        weight_class=wclass,
        width_class=cfg["width_class"],
        is_bold=is_bold,
        is_italic=is_italic,
        description=cfg["description"],
    )
    recompute_font_bbox(font)
    head_ymin = int(font["head"].yMin)
    head_ymax = int(font["head"].yMax)

    # 7b. Lossless CFF subroutinization via cffsubr (0 visual diff, ~22-25% smaller OTF & iOS profile!)
    subroutinize_otf(font)

    # 8. Export OTF, TTF (with gasp + OVERLAP_SIMPLE), WOFF2
    ps_prefix = cfg["ps_prefix"]
    otf_out = os.path.join(dist_dir, "otf", f"{ps_prefix}-{file_suffix}.otf")
    ttf_out = os.path.join(dist_dir, "ttf", f"{ps_prefix}-{file_suffix}.ttf")
    woff2_out = os.path.join(dist_dir, "woff2", f"{ps_prefix}-{file_suffix}.woff2")

    font.save(otf_out)
    convert_otf_to_ttf(otf_out, ttf_out, max_err=0.5)
    export_woff2(otf_out, woff2_out)

    elapsed = time.time() - t0
    return {
        "subfamily": subfam_key,
        "family_name": cfg["family_name"],
        "ps_name": f"{ps_prefix}-{file_suffix}",
        "style": file_suffix,
        "weight_class": wclass,
        "width_class": cfg["width_class"],
        "status": "ok",
        "stem_w": round(metrics["stem_w"], 2),
        "ref_merged": ref_merged_count,
        "winding_fixed": len(winding_fixed),
        "mtavruli_mapped": mtavruli_mapped,
        "l107_glyphs": l107_count,
        "latin_ext_glyphs": latin_ext_count,
        "rounded_glyphs": rounded_count,
        "georgian_spacing_shifted": georgian_spacing_shifted,
        "georgian_spacing_entry": georgian_spacing_entry,
        "yMin": head_ymin,
        "yMax": head_ymax,
        "otf_kb": os.path.getsize(otf_out) // 1024,
        "ttf_kb": os.path.getsize(ttf_out) // 1024,
        "woff2_kb": os.path.getsize(woff2_out) // 1024,
        "issues": issues,
        "elapsed_s": round(elapsed, 2),
    }


def main():
    parser = argparse.ArgumentParser(description="Build the Batumi Sans 8-subfamily typeface system.")
    parser.add_argument(
        "--subfamilies",
        default="all",
        help="Comma-separated subfamily keys or 'all' (options: " + ",".join(SUBFAMILY_ORDER) + ")",
    )
    parser.add_argument(
        "--styles",
        default="all",
        help="Comma-separated style suffixes or 'all' / 'upright' / 'italic'",
    )
    parser.add_argument("--src-dir", default=os.path.expanduser("~/Library/Fonts"))
    parser.add_argument("--ref-dir", default=os.path.join(BASE_DIR, "reference_fonts"))
    parser.add_argument("--dist-dir", default=os.path.join(BASE_DIR, "dist"))
    parser.add_argument(
        "--rebrand-patch-from",
        default="",
        help="Fast zero-loss mode: load existing dist/otf/<OLD_PREFIX>*.otf, apply keycaps + Batumi Sans metadata, and export OTF/TTF/WOFF2",
    )
    parser.add_argument(
        "--apply-l107-patch",
        action="store_true",
        help="Fast 100%%-idempotent 2-phase patch: apply official L1.07b Mtavruli (±44.5u + -14u optical CapH tuck) across all Sharp & Rounded styles while preserving keycaps, ampersands, GSUB and all other glyphs",
    )
    parser.add_argument(
        "--apply-ampersand-patch",
        action="store_true",
        help="Fast 100%%-idempotent patch: inject Batumi Master Georgian Ampersand (ampersand.geor U+E0A0 & ampersand.geor.case U+E0A1) + 4-layer GSUB (locl/calt/case/ss07/ss08) across all 144 static styles",
    )
    parser.add_argument(
        "--apply-keycaps-patch",
        action="store_true",
        help="Fast 100%%-idempotent patch: regenerate the 7 keycaps (⇦ ⇧ ⇨ ⇩ ⇪ ⏎ ⌫) on existing BatumiSans OTFs and re-export OTF/TTF/WOFF2",
    )
    parser.add_argument(
        "--apply-latin-ext-patch",
        action="store_true",
        help="Fast 100%%-idempotent 2-phase patch (ISS-001): add all 96 missing Latin Extended Additional (line-below family + Ḫ ḫ + uni032E) & 6 Primes (′ ″ ‴ ‵ ‶ ‷) + Rounded marks across all 144 static styles",
    )
    parser.add_argument(
        "--apply-v1100-hardening",
        action="store_true",
        help="Fast 100%%-idempotent 2-phase v1.100 production hardening pass (ISS-003/ISS-004, Borbalo metadata, gasp/meta/OVERLAP_SIMPLE, valid_glyphnames, Arabic GDEF/uni0674, U+0360/A7CB/A7DC/2028/2029/205A/2E31, GPOS MarkBase, cffsubr)",
    )
    parser.add_argument(
        "--apply-georgian-spacing",
        action="store_true",
        help="Fast 100%%-idempotent v2 foundry-calibrated Georgian optical spacing recovery pass (SemiBold..Heavy; Thin..Medium byte-for-byte untouched!)",
    )
    parser.add_argument("--workers", type=int, default=max(1, min(8, os.cpu_count() or 4)))
    args = parser.parse_args()
    if args.apply_keycaps_patch and not args.rebrand_patch_from:
        args.rebrand_patch_from = "BatumiSans"

    if args.subfamilies == "all":
        selected_subfams = list(SUBFAMILY_ORDER)
    else:
        selected_subfams = [k.strip() for k in args.subfamilies.split(",") if k.strip()]
        for k in selected_subfams:
            if k not in SUBFAMILIES:
                raise SystemExit(f"Unknown subfamily {k!r}. Valid: {SUBFAMILY_ORDER}")

    if args.styles == "all":
        selected_styles = STYLES
    elif args.styles == "upright":
        selected_styles = [s for s in STYLES if not s[5]]
    elif args.styles == "italic":
        selected_styles = [s for s in STYLES if s[5]]
    else:
        wanted = {x.strip() for x in args.styles.split(",") if x.strip()}
        selected_styles = [s for s in STYLES if s[0] in wanted]

    for sub in ("otf", "ttf", "woff2"):
        os.makedirs(os.path.join(args.dist_dir, sub), exist_ok=True)

    def _run_batch(batch_tasks):
        batch_results = []
        if not batch_tasks:
            return batch_results
        if args.workers == 1:
            for t in batch_tasks:
                res = build_single_style(t)
                batch_results.append(res)
                _log_result(res)
        else:
            with ProcessPoolExecutor(max_workers=args.workers) as pool:
                futs = {pool.submit(build_single_style, t): t for t in batch_tasks}
                for fut in as_completed(futs):
                    res = fut.result()
                    batch_results.append(res)
                    _log_result(res)
        return batch_results

    t_start = time.time()
    spacing_state_path = os.path.join(BASE_DIR, "qa", "georgian_spacing_state.json")
    spacing_state = load_spacing_state(spacing_state_path)
    spacing_styles_map = spacing_state.get("styles", {})

    all_tasks = [
        (
            subfam_key, st, args.src_dir, args.ref_dir, args.dist_dir,
            args.rebrand_patch_from, args.apply_l107_patch, args.apply_ampersand_patch,
            args.apply_latin_ext_patch, args.apply_v1100_hardening,
            args.apply_georgian_spacing,
            spacing_styles_map.get(f"{SUBFAMILIES[subfam_key]['ps_prefix']}-{st[0]}"),
        )
        for subfam_key in selected_subfams
        for st in selected_styles
    ]
    print(f"Building {len(all_tasks)} styles across {len(selected_subfams)} subfamilies ({args.workers} workers)...")

    if args.apply_l107_patch or args.apply_ampersand_patch or args.apply_latin_ext_patch or args.apply_v1100_hardening:
        # Strict 2-phase execution: Sharp subfamilies complete BEFORE Rounded subfamilies read them!
        sharp_tasks = [t for t in all_tasks if not SUBFAMILIES[t[0]]["rounded"]]
        round_tasks = [t for t in all_tasks if SUBFAMILIES[t[0]]["rounded"]]
        phase_lbl = (
            "v1.100 Production Hardening"
            if args.apply_v1100_hardening
            else (
                "Latin Ext + Primes (ISS-001)"
                if args.apply_latin_ext_patch
                else ("L1.07b" if args.apply_l107_patch else "Georgian Ampersand")
            )
        )
        results = []
        if sharp_tasks:
            print(f"  Phase 1/2 (Sharp {phase_lbl}): {len(sharp_tasks)} styles...")
            results.extend(_run_batch(sharp_tasks))
        if round_tasks:
            print(f"  Phase 2/2 (Rounded {phase_lbl}): {len(round_tasks)} styles...")
            results.extend(_run_batch(round_tasks))
    else:
        results = _run_batch(all_tasks)
    tasks = all_tasks

    # Family-wide ISS-003 verification & sync pass: ensure usWinAscent/usWinDescent cover global extremes!
    ok_res = [r for r in results if r["status"] == "ok" and "yMax" in r and "yMin" in r]
    if ok_res:
        g_ymax = max(r["yMax"] for r in ok_res)
        g_ymin = min(r["yMin"] for r in ok_res)
        req_win_asc = max(DEFAULT_WIN_ASCENT, ceil10(g_ymax))
        req_win_desc = max(DEFAULT_WIN_DESCENT, ceil10(abs(g_ymin)))
        print(f"  Family-wide glyph extremes: yMin={g_ymin}, yMax={g_ymax} -> usWinAscent={req_win_asc}, usWinDescent={req_win_desc}")
        if req_win_asc > DEFAULT_WIN_ASCENT or req_win_desc > DEFAULT_WIN_DESCENT:
            print(f"  Syncing elevated usWin ({req_win_asc}/{req_win_desc}) across all {len(ok_res)} styles...")
            for r in ok_res:
                ps = r["ps_name"]
                for sub, ext in (("otf", "otf"), ("ttf", "ttf"), ("woff2", "woff2")):
                    fp = os.path.join(args.dist_dir, sub, f"{ps}.{ext}")
                    if os.path.exists(fp):
                        ft = TTFont(fp)
                        ft["OS/2"].usWinAscent = req_win_asc
                        ft["OS/2"].usWinDescent = req_win_desc
                        ft.save(fp)
                        ft.close()

    # Persist Georgian spacing idempotency ledger atomically (only from main process!)
    updated_spacing_state = False
    for r in results:
        entry = r.pop("georgian_spacing_entry", None)
        if entry is not None and r.get("status") == "ok" and "ps_name" in r:
            spacing_styles_map[r["ps_name"]] = entry
            updated_spacing_state = True
    if updated_spacing_state:
        spacing_state["styles"] = spacing_styles_map
        save_spacing_state(spacing_state_path, spacing_state)
        print(f"  Updated Georgian spacing state ledger: {spacing_state_path} ({len(spacing_styles_map)} styles)")

    # Sort deterministically for report
    subfam_rank = {k: i for i, k in enumerate(SUBFAMILY_ORDER)}
    style_rank = {s[0]: i for i, s in enumerate(STYLES)}
    results.sort(key=lambda r: (subfam_rank.get(r["subfamily"], 99), style_rank.get(r["style"], 99)))

    css_path, emitted_css = write_superfamily_css(args.dist_dir)

    # Merge with existing audit report if running incremental subfamily builds
    report_path = os.path.join(args.dist_dir, "build_audit_report.json")
    existing_map = {}
    if os.path.exists(report_path):
        try:
            with open(report_path, "r", encoding="utf-8") as fp:
                old = json.load(fp)
            for item in old.get("styles", []):
                existing_map[(item["subfamily"], item["style"])] = item
        except Exception:
            pass
    for r in results:
        existing_map[(r["subfamily"], r["style"])] = r
    merged_styles = sorted(
        existing_map.values(),
        key=lambda r: (subfam_rank.get(r["subfamily"], 99), style_rank.get(r["style"], 99)),
    )

    total_issues = sum(len(r.get("issues", [])) for r in results)
    ok_count = sum(1 for r in results if r["status"] == "ok")
    err_count = sum(1 for r in results if r["status"] == "error")

    report = {
        "total_styles_in_dist": len(merged_styles),
        "last_run_built": ok_count,
        "last_run_errors": err_count,
        "last_run_issues": total_issues,
        "css_path": css_path,
        "css_subfamily_faces": emitted_css,
        "styles": merged_styles,
    }
    with open(report_path, "w", encoding="utf-8") as fp:
        json.dump(report, fp, indent=2)

    print(f"\n=== Build Summary ({time.time() - t_start:.1f}s) ===")
    print(f"  Built: {ok_count}/{len(tasks)} styles (errors: {err_count})")
    print(f"  Audit warnings in this run: {total_issues}")
    print(f"  CSS written: {css_path} ({emitted_css} explicit @font-face rules + font-stretch aliases)")
    print(f"  Audit report: {report_path}")
    if err_count:
        sys.exit(1)


def _log_result(res):
    if res["status"] != "ok":
        print(f"  [{res['status'].upper()}] {res['subfamily']}/{res['style']}: {res.get('reason')}")
        return
    n_iss = len(res["issues"])
    flag = "CLEAN" if n_iss == 0 else f"WARN({n_iss})"
    sp_note = ""
    if res.get("georgian_spacing_shifted"):
        sp_note = f" geoSp={res['georgian_spacing_shifted']:3d}"
    elif res.get("georgian_spacing_already_applied"):
        sp_note = " geoSp=IDEMP"
    print(
        f"  [OK {flag:8s}] {res['ps_name']:42s} "
        f"w={res['weight_class']:3d} wd={res['width_class']} stem={res['stem_w']:5.1f} "
        f"mtav={res['mtavruli_mapped']} rnd={res['rounded_glyphs']:3d} windFix={res['winding_fixed']:2d}{sp_note} "
        f"({res['otf_kb']}K/{res['ttf_kb']}K/{res['woff2_kb']}K) {res['elapsed_s']:.1f}s"
    )
    for iss in res["issues"][:5]:
        print(f"      ! {iss}")


if __name__ == "__main__":
    main()

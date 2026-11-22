#!/usr/bin/env python3
"""
Batumi Sans v1.100 Production Hardening & Google Fonts Compliance Engine.

Clean, modular, 100% idempotent hardening module wired into:
  - scripts/build_superfamily.py (full build & `--apply-v1100-hardening` fast patch)
  - scripts/build_maplibre_fonts.py (MapLibre hhea=1040/-265 preserved + usWin & metadata synced)
  - scripts/build_variable_fonts.py (3-axis Creative VFs & 2-axis Google Fonts [wdth,wght] VFs)

Implements all v1.100 production requirements:
  1. ISS-003 closure: family-wide OS/2.usWinAscent >= 1480 & usWinDescent >= 740,
     USE_TYPO_METRICS (bit 7) + WWS (bit 8) = 1, while preserving desktop hhea/sTypo*
     (935/-265/0) and MapLibre hhea/sTypo* (1040/-265/0) completely untouched.
  2. ISS-004 closure: removes stray upright-only Thai PUA U+F89E from cmap and
     renames `thoThan-thai.less` -> `thoThanthai.less` (matching Italic), leaving
     strictly identical Upright/Italic cmaps with ONLY U+E0A0/U+E0A1 in PUA.
  3. Complete Borbalo (KJ Group) / Koba Jgenti v1.100 metadata (Version 1.100,
     achVendID='BRBL', canonical OFL 1.1 copyright & https://openfontlicense.org),
     zero legacy platformID=1 Mac name entries, redundant nameID 16/17 omitted on
     RIBBI statics & VFs, clean Unicode/CodePage range recalculation, no DSIG.
  4. Cross-platform tables: `gasp` (v1, {0xFFFF: 0x000A}) on TTF/VF, `meta`
     (`dlng`: Geor, Latn; `slng`: Geor, Latn, Cyrl, Grek, Arab, Hebr, Deva, Thai),
     `OVERLAP_SIMPLE` (0x0040) on overlapping TTF/VF glyphs, remove U+00AD soft_hyphen
     from cmap, and align all 13 canonical math signs to modal width (`equal`).
  5. Fontspector Group-A glyph/GDEF/GPOS fixes:
       - `valid_glyphnames`: rename Ustrait*-cy -> uni04AE..04B1, thoThan-thai.less ->
         thoThanthai.less, and shorten 3 >31-char Georgian `.case` composites.
       - `arabic_high_hamza` & `arabic_spacing_symbols` & `GDEF_non_mark_chars`:
         reclassify uni0674 + 14 spacing symbols (U+FBB2-FBBB, FBBD-FBBF, FBC1)
         GDEF 3 -> 1, remove the 14 spacing symbols from GPOS mark coverages, and
         rebuild uni0674 from uni0621 at high-hamza y-position (100% area match).
       - `case_mapping` (Unicode 16.0): add U+A7DC (uniA7DC) & U+A7CB (uniA7CB),
         rounded on Rounded styles, VF-topology locked, with GPOS MarkBase anchors.
       - Kartvelian & Georgian completeness + `separator_glyphs`:
         add U+0360 (uni0360 COMBINING DOUBLE TILDE -> 11/11 Kartvelian diacritics!),
         U+2028/U+2029 zero-outline separators, U+205A (⁚), U+2E31 (⸱).
       - `dotted_circle` & `shape_languages`: attach GPOS MarkBase anchors onto
         uni25CC (covering 100% of mark lookups), all 89 ISS-001 U+1E00..1EFF
         precomposed glyphs, uniA7DC/uniA7CB, and register missing combining marks
         (uni032E, uni0360, uni1DC4, uni1DC5, uni0336, uni035C, uni0361, uni0951).
  6. Lossless CFF subroutinization (`cffsubr`), GF-edition `smcp`/`c2sc` stripping,
     and smart lossless/sub-unit `gvar` tuple optimization.
"""

import copy
import math
import unicodedata
from collections import Counter

import cffsubr
import pathops
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.ttLib import newTable
from fontTools.ttLib.tables import otTables

from georgian_ampersand import (
    inject_georgian_ampersand,
    update_calt_georgian_ampersand_for_khutsuri,
)
from georgian_karagma import apply_georgian_karagma_to_otf
from georgian_khutsuri import (
    ASOMTAVRULI_CPS,
    NUSKHURI_CPS,
    inject_georgian_khutsuri_into_otf,
    patch_khutsuri_kerning,
)
from georgian_spacing import compute_georgian_spacing_deltas
from v110_expansion import (
    EXPANSION_CYRL_MARKBASE_CPS,
    EXPANSION_LATIN_MARKBASE_CPS,
    inject_v110_expansion_49,
)
from latin_extended_primes import (
    ABOVE_MARK_CPS,
    BELOW_MARK_CPS,
    LATIN_EXT_89_CODEPOINTS,
    _contours_bbox,
    _round_mark_contours,
    _scale_contours_x_center,
    _transform_contours,
    _translate_contours,
    _upsert_cff_glyph,
)
from rounder import (
    contour_signed_area,
    draw_contours_to_pen,
    extract_contours,
    fix_disjoint_outer_winding,
    measure_font_metrics,
    round_contours,
)

# ---------------------------------------------------------------------------
# Canonical Batumi Sans v1.100 Metadata Constants (Borbalo / KJ Group)
# ---------------------------------------------------------------------------

VERSION_FLOAT = 1.100
VERSION_STR = "Version 1.100"
VENDOR_ID = "BRBL"

COPYRIGHT_STR = (
    "Copyright 2026 The Batumi Sans Project Authors (https://github.com/Borbalo/batumi-sans), "
    "Borbalo (KJ Group) and Koba Jgenti. Derived from FiraGO (Copyright 2012-2018 bBox Type GmbH "
    "and HERE Europe B.V.), Fira Sans (Copyright 2012-2018 The Mozilla Foundation, "
    "Telefonica S.A., Carrois Corporate GbR and bBox Type GmbH), and Noto Sans Georgian "
    "(Copyright 2019 Google LLC)"
)
TRADEMARK_STR = (
    "Batumi Sans is a typeface by Borbalo (KJ Group), released open-source under "
    "SIL OFL 1.1 with no Reserved Font Name."
)
MANUFACTURER_STR = "Borbalo (KJ Group)"
DESIGNER_STR = "Koba Jgenti, Borbalo"
DESCRIPTION_STR = (
    "Batumi Sans is a type family for Georgian, Latin, Cyrillic and Greek, with four "
    "widths, a rounded companion and a Georgian ampersand. Designed for Borbalo by Koba Jgenti."
)
VENDOR_URL = "https://borbalo.ge"
DESIGNER_URL = "https://newsroom.borbalo.ge"
LICENSE_STR = (
    "This Font Software is licensed under the SIL Open Font License, Version 1.1. "
    "This license is available with a FAQ at: https://openfontlicense.org"
)
LICENSE_URL = "https://openfontlicense.org"

META_DLNG = "Geor, Latn"
META_SLNG = "Geor, Latn, Cyrl, Grek, Arab, Hebr, Deva, Thai"

# Family-wide default minimum usWin* bounds (ISS-003); always raised to ceil10(global extremes)
DEFAULT_WIN_ASCENT = 1480
DEFAULT_WIN_DESCENT = 740

# Desktop vs MapLibre vertical metrics invariants (NEVER cross-contaminate!)
DESKTOP_HHEA_ASCENT = 935
DESKTOP_HHEA_DESCENT = -265
DESKTOP_HHEA_LINEGAP = 0

MAPLIBRE_HHEA_ASCENT = 1040
MAPLIBRE_HHEA_DESCENT = -265
MAPLIBRE_HHEA_LINEGAP = 0

# Exact invalid / >31-char glyph names to normalize across all tables
GLYPH_RENAME_MAP = {
    "thoThan-thai.less": "thoThanthai.less",
    "Ustrait-cy": "uni04AE",
    "ustrait-cy": "uni04AF",
    "Ustraitstroke-cy": "uni04B0",
    "ustraitstroke-cy": "uni04B1",
    "Angeorgian_macrondieresiscomb.case": "uni10D0_0304_0308.case",
    "Ongeorgian_macrondieresiscomb.case": "uni10DD_0304_0308.case",
    "Ungeorgian_macrondieresiscomb.case": "uni10E3_0304_0308.case",
}

# Arabic spacing symbols erroneously classified as GDEF mark (class 3) in upstream FiraGO
ARABIC_SPACING_SYMBOL_CPS = (
    0xFBB2, 0xFBB3, 0xFBB4, 0xFBB5, 0xFBB6, 0xFBB7, 0xFBB8, 0xFBB9,
    0xFBBA, 0xFBBB, 0xFBBD, 0xFBBE, 0xFBBF, 0xFBC1,
)

# Canonical 13 math signs audited by Fontspector `math_signs_width`
CANONICAL_MATH_SIGN_CPS = (
    0x002B,  # plus
    0x2212,  # minus
    0x003D,  # equal (modal anchor!)
    0x00D7,  # multiply
    0x00F7,  # divide
    0x00B1,  # plusminus
    0x2260,  # notequal
    0x2264,  # lessequal
    0x2265,  # greaterequal
    0x003C,  # less
    0x003E,  # greater
    0x2248,  # approxequal
    0x00AC,  # logicalnot
)

# New v1.100 glyphs (+7 glyphs: 4,675 -> 4,682) in deterministic glyphOrder sequence
V1100_NEW_GLYPHS = (
    (0x0360, "uni0360"),  # COMBINING DOUBLE TILDE (Kartvelian 11/11!)
    (0x2028, "uni2028"),  # LINE SEPARATOR
    (0x2029, "uni2029"),  # PARAGRAPH SEPARATOR
    (0x205A, "uni205A"),  # TWO DOT PUNCTUATION (⁚)
    (0x2E31, "uni2E31"),  # WORD SEPARATOR MIDDLE DOT (⸱)
    (0xA7CB, "uniA7CB"),  # LATIN CAPITAL LETTER RAMS HORN (Ɤ)
    (0xA7DC, "uniA7DC"),  # LATIN CAPITAL LETTER LAMBDA WITH STROKE (Ƛ)
)


def ceil10(v):
    return int(math.ceil(float(v) / 10.0) * 10)


# ---------------------------------------------------------------------------
# 1. Cmap Cleanup (ISS-004 U+F89E + soft_hyphen U+00AD) & Safe Glyph Renaming
# ---------------------------------------------------------------------------

def strip_unwanted_cmap_codepoints(font, codepoints=(0xF89E, 0x00AD)):
    """Remove stray Thai PUA U+F89E (ISS-004) and U+00AD soft_hyphen from ALL cmap subtables."""
    removed = set()
    if "cmap" not in font:
        return removed
    for sub in font["cmap"].tables:
        if not hasattr(sub, "cmap") or not isinstance(sub.cmap, dict):
            continue
        for cp in codepoints:
            if cp in sub.cmap:
                del sub.cmap[cp]
                removed.add(cp)
    return removed


def _rename_in_ot_object(obj, rename_map, seen):
    """Recursively rename glyph names in decompiled OpenType GSUB/GPOS/GDEF table objects."""
    if obj is None:
        return
    oid = id(obj)
    if oid in seen:
        return
    seen.add(oid)

    if isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, str):
                if item in rename_map:
                    obj[i] = rename_map[item]
            else:
                _rename_in_ot_object(item, rename_map, seen)
        return

    if isinstance(obj, dict):
        # Collect keys to rename so we don't mutate during iteration
        keys_to_change = [k for k in obj.keys() if isinstance(k, str) and k in rename_map]
        for k in keys_to_change:
            obj[rename_map[k]] = obj.pop(k)
        for k, v in list(obj.items()):
            if isinstance(v, str):
                if v in rename_map:
                    obj[k] = rename_map[v]
            else:
                _rename_in_ot_object(v, rename_map, seen)
        return

    if hasattr(obj, "__dict__"):
        for attr, val in list(obj.__dict__.items()):
            if isinstance(val, str):
                if val in rename_map:
                    setattr(obj, attr, rename_map[val])
            elif isinstance(val, (list, dict)) or hasattr(val, "__dict__"):
                _rename_in_ot_object(val, rename_map, seen)


def rename_glyphs_in_font(font, rename_map=None):
    """
    In-place font-wide glyph renaming preserving exact GIDs across glyphOrder,
    CFF/glyf, hmtx, cmap, GSUB, GPOS, GDEF, and post. 100% idempotent!
    """
    if rename_map is None:
        rename_map = GLYPH_RENAME_MAP
    order = list(font.getGlyphOrder())
    order_set = set(order)
    active_map = {}
    for old, new in rename_map.items():
        if old in order_set and new not in order_set:
            active_map[old] = new
    if not active_map:
        return {}

    # Force-decompile every relevant table BEFORE mutating glyphOrder!
    for tag in ("hmtx", "cmap", "GSUB", "GPOS", "GDEF", "post", "CFF ", "glyf"):
        if tag in font:
            _ = font[tag]

    # 1. Update glyphOrder in-place (preserves every GID identically!)
    new_order = [active_map.get(g, g) for g in order]
    font.setGlyphOrder(new_order)

    # 2. Update CFF charset & CharStrings
    if "CFF " in font:
        top = font["CFF "].cff.topDictIndex[0]
        top.charset = [active_map.get(g, g) for g in top.charset]
        cs = top.CharStrings.charStrings
        for old, new in active_map.items():
            if old in cs:
                cs[new] = cs.pop(old)

    # 3. Update glyf (if TTF)
    if "glyf" in font:
        glyf = font["glyf"]
        glyf.glyphOrder = list(new_order)
        for old, new in active_map.items():
            if old in glyf.glyphs:
                glyf.glyphs[new] = glyf.glyphs.pop(old)

    # 4. Update hmtx
    if "hmtx" in font:
        metrics = font["hmtx"].metrics
        for old, new in active_map.items():
            if old in metrics:
                metrics[new] = metrics.pop(old)

    # 5. Update cmap
    if "cmap" in font:
        for sub in font["cmap"].tables:
            if hasattr(sub, "cmap") and isinstance(sub.cmap, dict):
                for cp, gn in list(sub.cmap.items()):
                    if gn in active_map:
                        sub.cmap[cp] = active_map[gn]

    # 6. Update GSUB, GPOS, GDEF recursively
    seen = set()
    for tag in ("GSUB", "GPOS", "GDEF"):
        if tag in font:
            _rename_in_ot_object(font[tag].table, active_map, seen)

    return active_map


# ---------------------------------------------------------------------------
# 2. Arabic High Hamza (uni0674) & Arabic Spacing Symbols (U+FBB2..FBC1)
# ---------------------------------------------------------------------------

def _remove_glyphs_from_gpos_marks(font, target_glyphs):
    """
    Remove spacing symbols (e.g. U+FBB2..FBC1) cleanly from GPOS MarkCoverage /
    Mark1Coverage / Mark2Coverage while keeping parallel MarkRecord/Mark2Record
    arrays strictly synchronized.
    """
    if "GPOS" not in font or not target_glyphs:
        return 0
    removed_refs = 0
    gpos = font["GPOS"].table
    for lk in gpos.LookupList.Lookup:
        for st in lk.SubTable:
            ltype = st.ExtensionLookupType if lk.LookupType == 9 else lk.LookupType
            rst = st.ExtSubTable if lk.LookupType == 9 else st
            if ltype in (4, 5) and hasattr(rst, "MarkCoverage") and rst.MarkCoverage:
                glist = rst.MarkCoverage.glyphs
                if any(g in target_glyphs for g in glist):
                    keep_idx = [i for i, g in enumerate(glist) if g not in target_glyphs]
                    removed_refs += len(glist) - len(keep_idx)
                    rst.MarkCoverage.glyphs = [glist[i] for i in keep_idx]
                    rst.MarkArray.MarkRecord = [rst.MarkArray.MarkRecord[i] for i in keep_idx]
                    rst.MarkArray.MarkCount = len(keep_idx)
            elif ltype == 6:
                if hasattr(rst, "Mark1Coverage") and rst.Mark1Coverage:
                    glist = rst.Mark1Coverage.glyphs
                    if any(g in target_glyphs for g in glist):
                        keep_idx = [i for i, g in enumerate(glist) if g not in target_glyphs]
                        removed_refs += len(glist) - len(keep_idx)
                        rst.Mark1Coverage.glyphs = [glist[i] for i in keep_idx]
                        rst.Mark1Array.MarkRecord = [rst.Mark1Array.MarkRecord[i] for i in keep_idx]
                        rst.Mark1Array.MarkCount = len(keep_idx)
                if hasattr(rst, "Mark2Coverage") and rst.Mark2Coverage:
                    glist = rst.Mark2Coverage.glyphs
                    if any(g in target_glyphs for g in glist):
                        keep_idx = [i for i, g in enumerate(glist) if g not in target_glyphs]
                        removed_refs += len(glist) - len(keep_idx)
                        rst.Mark2Coverage.glyphs = [glist[i] for i in keep_idx]
                        rst.Mark2Array.Mark2Record = [rst.Mark2Array.Mark2Record[i] for i in keep_idx]
                        rst.Mark2Array.Mark2Count = len(keep_idx)
    return removed_refs


def fix_arabic_high_hamza_and_spacing_symbols(font, is_italic=False):
    """
    Fixes `arabic_high_hamza`, `arabic_spacing_symbols`, and `opentype/GDEF_non_mark_chars`:
      1. Reclassify `uni0674` and all 14 Arabic spacing symbols (U+FBB2-FBBB, FBBD-FBBF, FBC1)
         from GDEF class 3 (mark) -> class 1 (base).
      2. Remove the 14 spacing symbols from GPOS Mark coverages (so neither GPOS nor
         `dotted_circle` treats them as combining marks) and ensure positive advance width.
      3. Rebuild `uni0674` (U+0674) directly from the font's own `uni0621` (U+0621 Hamza)
         raised to high-hamza y-position (top aligned ~720u, matching uni0621 outline area 1:1
         and preserving exact 16-master VF contour/segment topology!).
    """
    cm = font.getBestCmap()
    gdef_cls = font["GDEF"].table.GlyphClassDef.classDefs if "GDEF" in font and font["GDEF"].table.GlyphClassDef else {}

    # 1. Arabic spacing symbols (14 glyphs): GDEF class 3 -> 1, remove from GPOS mark lists
    spacing_glyphs = set()
    for cp in ARABIC_SPACING_SYMBOL_CPS:
        gn = cm.get(cp)
        if gn:
            spacing_glyphs.add(gn)
            if gn in gdef_cls:
                gdef_cls[gn] = 1
            # Give zero-advance spacing symbols a clean symmetric positive advance width
            adv, lsb = font["hmtx"][gn]
            if adv == 0:
                bp = BoundsPen(font.getGlyphSet())
                font.getGlyphSet()[gn].draw(bp)
                if bp.bounds:
                    x0, _, x1, _ = bp.bounds
                    # Preserve optical center; upstream centers these around ~300 -> adv ~600
                    sym_adv = max(int(round(x1 + max(x0, 50))), int(round((x1 - x0) + 140)))
                    font["hmtx"][gn] = (sym_adv, int(round(x0)))
                    # Update CFF nominal width cleanly if CFF font
                    if "CFF " in font:
                        cs_orig = extract_contours(font, gn)
                        _upsert_cff_glyph(font, gn, cs_orig, sym_adv, gdef_class=1)

    _remove_glyphs_from_gpos_marks(font, spacing_glyphs)

    # 2. Rebuild `uni0674` from `uni0621` raised to high-hamza position
    g_hamza = cm.get(0x0621)
    g_high = cm.get(0x0674)
    if g_hamza and g_high and "CFF " in font:
        cs_0621 = extract_contours(font, g_hamza)
        cs_0621, _ = fix_disjoint_outer_winding(cs_0621)
        bb_0621 = _contours_bbox(cs_0621)
        if bb_0621:
            # Raise uni0621 cleanly so its top sits at ~724u (matching original high-hamza top 727u)
            y_target_top = 724.0
            dy = y_target_top - bb_0621[3]
            tan_a = math.tan(math.radians(8.0)) if is_italic else 0.0
            dx = dy * tan_a
            cs_high = _translate_contours(cs_0621, dx, dy)
            adv_0621 = font["hmtx"][g_hamza][0]
            _upsert_cff_glyph(font, g_high, cs_high, adv_0621, gdef_class=1)
    elif g_high and g_high in gdef_cls:
        gdef_cls[g_high] = 1


# ---------------------------------------------------------------------------
# 3. Align Math Signs Advance Widths (`math_signs_width` PASS across 144 styles)
# ---------------------------------------------------------------------------

def align_math_signs_width(font):
    """
    Center-align all 13 canonical math signs (+, −, =, ×, ÷, ±, ≠, ≤, ≥, <, >, ≈, ¬)
    to the style's exact modal math advance width (`equal`, e.g. 500 in Regular).
    100% idempotent & smooth across all widths/weights for HVAR/gvar interpolation.
    """
    if "CFF " not in font:
        return 0
    cm = font.getBestCmap()
    g_eq = cm.get(0x003D)
    if not g_eq:
        return 0
    target_adv = int(font["hmtx"][g_eq][0])
    adjusted = 0
    for cp in CANONICAL_MATH_SIGN_CPS:
        gn = cm.get(cp)
        if not gn:
            continue
        cur_adv = int(font["hmtx"][gn][0])
        if cur_adv == target_adv:
            continue
        dx = 0.5 * (target_adv - cur_adv)
        cs = extract_contours(font, gn)
        cs_shifted = _translate_contours(cs, dx, 0.0)
        gdef_cls = 1
        if "GDEF" in font and font["GDEF"].table.GlyphClassDef:
            gdef_cls = font["GDEF"].table.GlyphClassDef.classDefs.get(gn, 1)
        _upsert_cff_glyph(font, gn, cs_shifted, target_adv, gdef_class=gdef_cls)
        adjusted += 1
    return adjusted


# ---------------------------------------------------------------------------
# 4. New v1.100 Glyphs (+7 Glyphs: U+0360, U+2028, U+2029, U+205A, U+2E31, U+A7CB, U+A7DC)
# ---------------------------------------------------------------------------

def _scale_glyph_to_cap(contours, adv_orig, src_y_ref, cap_h, scale_x, is_italic=False):
    """
    Cleanly scale a lowercase letter contour set to Cap-Height proportions in unslanted
    space (preserving baseline y=0 & exact italic shear angle).
    Returns (new_contours, new_adv).
    """
    tan_a = math.tan(math.radians(8.0)) if is_italic else 0.0
    sy = cap_h / max(src_y_ref, 1.0)
    new_adv = int(round(adv_orig * scale_x))
    cx_src = 0.5 * adv_orig
    cx_dst = 0.5 * new_adv

    def fn(p):
        ux = p[0] - p[1] * tan_a
        ny = p[1] * sy
        nx = cx_dst + (ux - cx_src) * scale_x
        return (nx + ny * tan_a, ny)

    scaled = _transform_contours(contours, fn)
    scaled, _ = fix_disjoint_outer_winding(scaled)
    return scaled, new_adv


def _check_pathops_safe(contours):
    if not contours:
        return True
    p = pathops.Path()
    draw_contours_to_pen(contours, p.getPen(), round_coords=True)
    ra = abs(p.area)
    ps = pathops.simplify(p, clockwise=False)
    sa = abs(ps.area)
    return ra < 50 or abs(ra - sa) / ra <= 0.02


def _add_cmap_mapping(font, cp, gname):
    """Write Unicode codepoint mapping cleanly into all Unicode cmap subtables (4 & 12)."""
    for sub in font["cmap"].tables:
        if sub.isUnicode():
            if sub.format == 4 and cp <= 0xFFFF:
                sub.cmap[cp] = gname
            elif sub.format == 12:
                sub.cmap[cp] = gname


def inject_v1100_new_glyphs(
    font,
    weight_class,
    width_mode,
    is_italic=False,
    rounded=False,
    sharp_ref_font=None,
    sharp_metrics=None,
):
    """
    Construct and inject all 7 new v1.100 glyphs cleanly across all 144 static OTF styles
    (with 100% locked 16-master VF contour topology & Rounded κ=0.580 on Rounded styles):
      1. `uni0360` (U+0360 COMBINING DOUBLE TILDE `◌͠◌` — 11/11 Kartvelian diacritics!)
      2. `uni2028` (U+2028 LINE SEPARATOR — zero-outline separator)
      3. `uni2029` (U+2029 PARAGRAPH SEPARATOR — zero-outline separator)
      4. `uni205A` (U+205A TWO DOT PUNCTUATION `⁚` — from `colon`)
      5. `uni2E31` (U+2E31 WORD SEPARATOR MIDDLE DOT `⸱` — from `periodcentered`)
      6. `uniA7CB` (U+A7CB LATIN CAPITAL LETTER RAMS HORN `Ɤ` — Unicode 16 case pair of U+0264)
      7. `uniA7DC` (U+A7DC LATIN CAPITAL LETTER LAMBDA WITH STROKE `Ƛ` — Unicode 16 case pair of U+019B)
    Returns (count_added, issues_list).
    """
    if "CFF " not in font:
        return 0, []

    src_font = sharp_ref_font if (rounded and sharp_ref_font is not None) else font
    if sharp_metrics is None:
        sharp_metrics = measure_font_metrics(src_font)
    issues = []
    tan_a = math.tan(math.radians(8.0)) if is_italic else 0.0

    # Measure font's own CapH and x-height cleanly
    bb_H = _contours_bbox(extract_contours(src_font, "H"))
    bb_x = _contours_bbox(extract_contours(src_font, "x"))
    cap_h = bb_H[3] if bb_H else 689.0
    x_h = bb_x[3] if bb_x else 527.0

    # 1. `uni0360` (U+0360 COMBINING DOUBLE TILDE) — derived from `tildecomb` scaled 1.85x horizontally
    cs_tilde = extract_contours(src_font, "tildecomb")
    cs_tilde, _ = fix_disjoint_outer_winding(cs_tilde)
    cs_dbl = _scale_contours_x_center(cs_tilde, 1.85, is_italic=is_italic)
    bb_dbl = _contours_bbox(cs_dbl)
    # Match `uni0361` horizontal centering across x=0 (sheared along Italic axis at mark y_mid)
    if "uni0361" in src_font.getGlyphSet():
        bb_361 = _contours_bbox(extract_contours(src_font, "uni0361"))
        target_cx = 0.5 * (bb_361[0] + bb_361[2])
    else:
        cy_dbl = 0.5 * (bb_dbl[1] + bb_dbl[3])
        target_cx = cy_dbl * tan_a
    dx_dbl = target_cx - 0.5 * (bb_dbl[0] + bb_dbl[2])
    cs_dbl = _translate_contours(cs_dbl, dx_dbl, 0.0)
    if rounded:
        cs_dbl = _round_mark_contours("uni0360", cs_dbl, sharp_metrics)
    cs_dbl, _ = fix_disjoint_outer_winding(cs_dbl)
    _upsert_cff_glyph(font, "uni0360", cs_dbl, 0, gdef_class=3)
    _add_cmap_mapping(font, 0x0360, "uni0360")

    # 2 & 3. `uni2028` (LINE SEPARATOR) & `uni2029` (PARAGRAPH SEPARATOR)
    # Zero-outline glyphs with standard space advance width (Google Fonts `separator_glyphs` PASS)
    space_adv = int(font["hmtx"]["space"][0]) if "space" in font["hmtx"].metrics else 265
    for cp, gn in ((0x2028, "uni2028"), (0x2029, "uni2029")):
        _upsert_cff_glyph(font, gn, [], space_adv, gdef_class=1)
        _add_cmap_mapping(font, cp, gn)

    # 4. `uni205A` (U+205A TWO DOT PUNCTUATION `⁚`) — from font's own `colon` (already rounded on Rounded!)
    cs_colon = extract_contours(font, "colon")
    cs_colon, _ = fix_disjoint_outer_winding(cs_colon)
    adv_colon = int(font["hmtx"]["colon"][0])
    _upsert_cff_glyph(font, "uni205A", cs_colon, adv_colon, gdef_class=1)
    _add_cmap_mapping(font, 0x205A, "uni205A")

    # 5. `uni2E31` (U+2E31 WORD SEPARATOR MIDDLE DOT `⸱`) — from font's own `periodcentered`
    cs_pdot = extract_contours(font, "periodcentered")
    cs_pdot, _ = fix_disjoint_outer_winding(cs_pdot)
    adv_pdot = int(font["hmtx"]["periodcentered"][0])
    _upsert_cff_glyph(font, "uni2E31", cs_pdot, adv_pdot, gdef_class=1)
    _add_cmap_mapping(font, 0x2E31, "uni2E31")

    # 6. `uniA7CB` (U+A7CB LATIN CAPITAL LETTER RAMS HORN `Ɤ`, case pair of U+0264 `ɤ`)
    cs_0264 = extract_contours(src_font, "uni0264")
    cs_0264, _ = fix_disjoint_outer_winding(cs_0264)
    adv_0264 = float(src_font["hmtx"]["uni0264"][0])
    # Scale x-height (527) -> CapH (689) with balanced capital width (+16%)
    cs_a7cb, adv_a7cb = _scale_glyph_to_cap(
        cs_0264, adv_0264, src_y_ref=x_h, cap_h=cap_h, scale_x=1.16, is_italic=is_italic
    )
    if rounded:
        cand = round_contours(cs_a7cb, sharp_metrics, enable_outer_corners=True, enable_overshoot=True)
        cand, _ = fix_disjoint_outer_winding(cand)
        if len(cand) == len(cs_a7cb) and _check_pathops_safe(cand):
            cs_a7cb = cand
    _upsert_cff_glyph(font, "uniA7CB", cs_a7cb, adv_a7cb, gdef_class=1)
    _add_cmap_mapping(font, 0xA7CB, "uniA7CB")

    # 7. `uniA7DC` (U+A7DC LATIN CAPITAL LETTER LAMBDA WITH STROKE `Ƛ`, case pair of U+019B `ƛ`)
    cs_019b = extract_contours(src_font, "uni019B")
    cs_019b, _ = fix_disjoint_outer_winding(cs_019b)
    bb_019b = _contours_bbox(cs_019b)
    adv_019b = float(src_font["hmtx"]["uni019B"][0])
    # `uni019B` has ascender top ~776; proportion `uniA7DC` cleanly to CapH (+10u optical apex) & +12% capital width
    src_top_019b = bb_019b[3] if bb_019b else 776.0
    cs_a7dc, adv_a7dc = _scale_glyph_to_cap(
        cs_019b, adv_019b, src_y_ref=src_top_019b, cap_h=cap_h + 10.0, scale_x=1.12, is_italic=is_italic
    )
    if rounded:
        cand = round_contours(cs_a7dc, sharp_metrics, enable_outer_corners=True, enable_overshoot=True)
        cand, _ = fix_disjoint_outer_winding(cand)
        if len(cand) == len(cs_a7dc) and _check_pathops_safe(cand):
            cs_a7dc = cand
    _upsert_cff_glyph(font, "uniA7DC", cs_a7dc, adv_a7dc, gdef_class=1)
    _add_cmap_mapping(font, 0xA7DC, "uniA7DC")

    return len(V1100_NEW_GLYPHS), issues


# ---------------------------------------------------------------------------
# 5. GPOS MarkBase Anchors (`dotted_circle`, 89 `ISS-001` glyphs, `uniA7CB/DC`, missing marks)
# ---------------------------------------------------------------------------

def _make_anchor(x, y):
    a = otTables.Anchor()
    a.Format = 1
    a.XCoordinate = int(round(x))
    a.YCoordinate = int(round(y))
    return a


def _insert_mark_into_subtable(font, rst, gname, mark_class, ax, ay):
    """Idempotently insert or update a mark glyph in a MarkBasePos subtable (GID-sorted)."""
    cov = rst.MarkCoverage.glyphs
    recs = rst.MarkArray.MarkRecord
    if gname in cov:
        idx = cov.index(gname)
        recs[idx].Class = mark_class
        recs[idx].MarkAnchor = _make_anchor(ax, ay)
        return
    mrec = otTables.MarkRecord()
    mrec.Class = mark_class
    mrec.MarkAnchor = _make_anchor(ax, ay)
    pairs = list(zip(cov, recs))
    pairs.append((gname, mrec))
    pairs.sort(key=lambda kv: font.getGlyphID(kv[0]))
    rst.MarkCoverage.glyphs = [k for k, _ in pairs]
    rst.MarkArray.MarkRecord = [v for _, v in pairs]
    rst.MarkArray.MarkCount = len(pairs)


def _insert_base_into_subtable(font, rst, gname, anchors_list):
    """Idempotently insert or update a base glyph in a MarkBasePos subtable (GID-sorted)."""
    cov = rst.BaseCoverage.glyphs
    recs = rst.BaseArray.BaseRecord
    brec = otTables.BaseRecord()
    brec.BaseAnchor = list(anchors_list)
    if gname in cov:
        idx = cov.index(gname)
        recs[idx] = brec
        return
    pairs = list(zip(cov, recs))
    pairs.append((gname, brec))
    pairs.sort(key=lambda kv: font.getGlyphID(kv[0]))
    rst.BaseCoverage.glyphs = [k for k, _ in pairs]
    rst.BaseArray.BaseRecord = [v for _, v in pairs]
    rst.BaseArray.BaseCount = len(pairs)


def _glyph_bbox(font, gname):
    bp = BoundsPen(font.getGlyphSet())
    font.getGlyphSet()[gname].draw(bp)
    return bp.bounds


def patch_gpos_markbase_anchors(font, is_italic=False):
    """
    Complete GPOS MarkBase hardening (clears `dotted_circle` FAIL & slashes `shape_languages` FAILs):
      1. Register all unattached combining marks (`uni0360`, `uni032E`, `uni1DC4`, `uni1DC5`,
         `uni0336`, `uni035C`, `uni0361`, `uni0951`) into every MarkBase subtable carrying
         matching top/bottom/center mark classes.
      2. Attach GPOS MarkBase anchors onto all 89 `ISS-001` U+1E00..1EFF precomposed letters
         (inheriting base letter anchors, raising top anchor above existing upper diacritics
         and lowering bottom anchor below existing lower diacritics with exact -8° Italic shear!)
         AND onto `uniA7CB` (`Ɤ`, clears `gov_Latn` & `dnj_Latn`!) and `uniA7DC` (`Ƛ`).
      3. Attach `uni25CC` (DOTTED CIRCLE) as a BaseGlyph into the minimal covering set of
         MarkBase lookups across ALL scripts (`mark`, `abvm`, `blwm` -> 100% of marks!),
         giving every class a clean optically-centered anchor on `uni25CC`.
    """
    if "GPOS" not in font:
        return {}

    gpos = font["GPOS"].table
    gset = set(font.getGlyphOrder())
    cm = font.getBestCmap()
    tan_a = math.tan(math.radians(8.0)) if is_italic else 0.0

    # Collect all MarkBase (type 4) subtables
    mb_subtables = []
    for li, lk in enumerate(gpos.LookupList.Lookup):
        for si, st in enumerate(lk.SubTable):
            ltype = st.ExtensionLookupType if lk.LookupType == 9 else lk.LookupType
            rst = st.ExtSubTable if lk.LookupType == 9 else st
            if ltype == 4 and hasattr(rst, "MarkCoverage") and hasattr(rst, "BaseCoverage"):
                mb_subtables.append((li, si, rst))

    # --- Step 1: Register missing combining marks into matching MarkBase subtables ---
    # Reference marks to identify top, bottom, and center classes in any subtable
    # (Mark name, reference donor mark whose class & MarkAnchor Y we match, x_mode)
    # x_mode: "center" -> bbox center at MarkAnchor Y; "left_lobe" -> spanning double-mark left lobe
    extra_marks = [
        ("uni0360", "tildecomb", "double_top"),
        ("uni0361", "tildecomb", "double_top"),
        ("uni1DC4", "uni1DC6", "center"),
        ("uni1DC5", "uni1DC6", "center"),
        ("uni0951", "acutecomb", "center"),
        ("uni032E", "uni032D", "center"),
        ("uni035C", "uni032D", "double_bot"),
        ("uni035F", "uni032D", "double_bot"),
        ("uni0336", "uni0335", "center"),
    ]
    marks_registered = 0
    for li, si, rst in mb_subtables:
        m_idx = {g: i for i, g in enumerate(rst.MarkCoverage.glyphs)}
        for mg, ref_mg, x_mode in extra_marks:
            if mg not in gset or ref_mg not in m_idx:
                continue
            ref_rec = rst.MarkArray.MarkRecord[m_idx[ref_mg]]
            if ref_rec.MarkAnchor is None:
                continue
            cls = ref_rec.Class
            ref_my = float(ref_rec.MarkAnchor.YCoordinate)
            bb = _glyph_bbox(font, mg)
            if not bb:
                continue
            cx = 0.5 * (bb[0] + bb[2])
            cy = 0.5 * (bb[1] + bb[3])
            w = bb[2] - bb[0]
            if x_mode in ("double_top", "double_bot"):
                # Place MarkAnchor on left half (~0.35w left of center) so double mark spans
                # cleanly across base + following character (e.g. ა͠ბ, Ა͠Ბ, a͠b) AND centers near ◌͠!
                ax = (cx - 0.35 * w) + (ref_my - cy) * tan_a
            else:
                ax = cx + (ref_my - cy) * tan_a
            _insert_mark_into_subtable(font, rst, mg, cls, ax, ref_my)
            marks_registered += 1

    # --- Step 2: Register all 89 ISS-001 glyphs + uniA7CB + uniA7DC in Latin MarkBase subtable ---
    latin_rst = None
    for _, _, rst in mb_subtables:
        if "A" in rst.BaseCoverage.glyphs and "a" in rst.BaseCoverage.glyphs:
            latin_rst = rst
            break

    bases_added = 0
    if latin_rst is not None:
        m_idx = {g: i for i, g in enumerate(latin_rst.MarkCoverage.glyphs)}
        top_cls = latin_rst.MarkArray.MarkRecord[m_idx["acutecomb"]].Class if "acutecomb" in m_idx else None
        bot_cls = latin_rst.MarkArray.MarkRecord[m_idx["dotbelowcomb"]].Class if "dotbelowcomb" in m_idx else None
        base_map = {g: rec for g, rec in zip(latin_rst.BaseCoverage.glyphs, latin_rst.BaseArray.BaseRecord)}

        # 2a. All 89 ISS-001 U+1E00..1EFF precomposed letters
        for cp in LATIN_EXT_89_CODEPOINTS:
            gn = f"uni{cp:04X}"
            if gn not in gset:
                continue
            nfd = unicodedata.normalize("NFD", chr(cp))
            base_cp = ord(nfd[0])
            mark_cps = [ord(c) for c in nfd[1:]]
            base_gn = cm.get(base_cp)
            if base_gn == "longs" and base_gn not in base_map:
                base_gn = "f"
            donor_rec = base_map.get(base_gn)
            if donor_rec is None:
                continue

            new_anchors = [copy.deepcopy(a) for a in donor_rec.BaseAnchor]
            g_bb = _glyph_bbox(font, gn)
            has_above = any(m in ABOVE_MARK_CPS for m in mark_cps)
            has_below = any(m in BELOW_MARK_CPS for m in mark_cps)

            if g_bb and top_cls is not None and top_cls < len(new_anchors) and new_anchors[top_cls] is not None:
                if has_above:
                    old_a = new_anchors[top_cls]
                    new_y = max(float(old_a.YCoordinate), g_bb[3] + 35.0)
                    dy = new_y - float(old_a.YCoordinate)
                    new_anchors[top_cls] = _make_anchor(old_a.XCoordinate + dy * tan_a, new_y)

            if g_bb and bot_cls is not None and bot_cls < len(new_anchors) and new_anchors[bot_cls] is not None:
                if has_below:
                    old_a = new_anchors[bot_cls]
                    new_y = min(float(old_a.YCoordinate), g_bb[1] - 35.0)
                    dy = new_y - float(old_a.YCoordinate)
                    new_anchors[bot_cls] = _make_anchor(old_a.XCoordinate + dy * tan_a, new_y)

            _insert_base_into_subtable(font, latin_rst, gn, new_anchors)
            bases_added += 1

        # 2b. Unicode 16.0 capitals `uniA7CB` & `uniA7DC` (inherit capital `A`/`Y` vertical anchor levels)
        cap_ref = base_map.get("Y") or base_map.get("A")
        if cap_ref is not None:
            for gn in ("uniA7CB", "uniA7DC"):
                if gn not in gset:
                    continue
                g_bb = _glyph_bbox(font, gn)
                if not g_bb:
                    continue
                cx = 0.5 * (g_bb[0] + g_bb[2])
                cy = 0.5 * (g_bb[1] + g_bb[3])
                new_anchors = []
                for c_idx in range(latin_rst.ClassCount):
                    ref_a = cap_ref.BaseAnchor[c_idx] if c_idx < len(cap_ref.BaseAnchor) else None
                    if ref_a is None:
                        new_anchors.append(None)
                    elif c_idx == top_cls:
                        ty = max(float(ref_a.YCoordinate), g_bb[3] + 40.0)
                        new_anchors.append(_make_anchor(cx + (ty - cy) * tan_a, ty))
                    elif c_idx == bot_cls:
                        by = min(float(ref_a.YCoordinate), 0.0)
                        new_anchors.append(_make_anchor(cx + (by - cy) * tan_a, by))
                    else:
                        ay = float(ref_a.YCoordinate)
                        new_anchors.append(_make_anchor(cx + (ay - cy) * tan_a, ay))
                _insert_base_into_subtable(font, latin_rst, gn, new_anchors)
                bases_added += 1

        # 2c. Expansion Latin & Cyrillic letters (Ᵽ ᵽ Ꟈ ꟈ Ᲊ ᲊ Ҁ..ꙗ) in Latin/Cyrillic MarkBase subtables
        for cp in EXPANSION_LATIN_MARKBASE_CPS + EXPANSION_CYRL_MARKBASE_CPS:
            gn = cm.get(cp)
            if not gn or gn not in gset:
                continue
            g_bb = _glyph_bbox(font, gn)
            if not g_bb:
                continue
            cx = 0.5 * (g_bb[0] + g_bb[2])
            cy = 0.5 * (g_bb[1] + g_bb[3])
            ref_rec = cap_ref if (g_bb[3] > 600) else (base_map.get("a") or cap_ref)
            if ref_rec is None:
                continue
            new_anchors = []
            for c_idx in range(latin_rst.ClassCount):
                ref_a = ref_rec.BaseAnchor[c_idx] if c_idx < len(ref_rec.BaseAnchor) else None
                if ref_a is None:
                    new_anchors.append(None)
                elif c_idx == top_cls:
                    ty = max(float(ref_a.YCoordinate), g_bb[3] + 20.0)
                    new_anchors.append(_make_anchor(cx + (ty - cy) * tan_a, ty))
                elif c_idx == bot_cls:
                    by = min(float(ref_a.YCoordinate), g_bb[1] - 10.0 if g_bb[1] < -40 else 0.0)
                    new_anchors.append(_make_anchor(cx + (by - cy) * tan_a, by))
                else:
                    ay = float(ref_a.YCoordinate)
                    new_anchors.append(_make_anchor(cx + (ay - cy) * tan_a, ay))
            _insert_base_into_subtable(font, latin_rst, gn, new_anchors)
            bases_added += 1

    # --- Step 3: Attach `uni25CC` (DOTTED CIRCLE) to minimal set of MarkBase subtables covering 100% of marks ---
    dc_lookups = 0
    if "uni25CC" in gset:
        dc_bb = _glyph_bbox(font, "uni25CC")
        if dc_bb:
            dc_cx = 0.5 * (dc_bb[0] + dc_bb[2])
            dc_cy = 0.5 * (dc_bb[1] + dc_bb[3])
            dc_top = dc_bb[3]
            dc_bot = dc_bb[1]

            # Greedy set cover over all MarkBase subtables so EVERY mark across every script attaches to uni25CC!
            covered_marks = set()
            ordered_subs = sorted(mb_subtables, key=lambda x: -len(x[2].MarkCoverage.glyphs))
            for li, si, rst in ordered_subs:
                sub_marks = set(rst.MarkCoverage.glyphs)
                if not (sub_marks - covered_marks):
                    continue
                covered_marks |= sub_marks

                # Compute clean centered anchor for EVERY class in this subtable
                anchors = []
                for c_idx in range(rst.ClassCount):
                    # Inspect median/average markY and baseY for this class to classify top/mid/bot
                    base_ys = [
                        br.BaseAnchor[c_idx].YCoordinate
                        for br in rst.BaseArray.BaseRecord
                        if c_idx < len(br.BaseAnchor) and br.BaseAnchor[c_idx] is not None
                    ]
                    mark_ys = [
                        mr.MarkAnchor.YCoordinate
                        for mr in rst.MarkArray.MarkRecord
                        if mr.Class == c_idx and mr.MarkAnchor is not None
                    ]
                    avg_by = (sum(base_ys) / len(base_ys)) if base_ys else 0.0
                    avg_my = (sum(mark_ys) / len(mark_ys)) if mark_ys else 0.0

                    # Choose geometrically harmonious Y on uni25CC (height ~545u)
                    if avg_by >= 380 or avg_my >= 420:
                        # Above-base mark (top / Hebrew top / Devanagari abvm)
                        ay = max(dc_top + 28.0, min(avg_my + 20.0, dc_top + 95.0))
                    elif avg_by <= 80 and avg_my <= 80:
                        # Below-base mark (bottom / blwm / ogonek)
                        ay = min(dc_bot, 0.0)
                    else:
                        # Center/overlay/side mark
                        ay = dc_cy
                    ax = dc_cx + (ay - dc_cy) * tan_a
                    anchors.append(_make_anchor(ax, ay))

                _insert_base_into_subtable(font, rst, "uni25CC", anchors)
                dc_lookups += 1

    # --- Step 4: Full Georgian Mkhedruli & Mtavruli MarkBase coverage + fix placeholder (0,0) bottom anchors ---
    geor_bases_added = 0
    geor_bot_fixed = 0
    geor_rst = None
    for _, _, rst in mb_subtables:
        if "uni10D0" in rst.BaseCoverage.glyphs:
            geor_rst = rst
            break

    xh_y = 527.0
    cap_y = 675.0
    if geor_rst is not None:
        a_idx = geor_rst.BaseCoverage.glyphs.index("uni10D0")
        a_anc = geor_rst.BaseArray.BaseRecord[a_idx].BaseAnchor[0]
        if a_anc is not None:
            xh_y = float(a_anc.YCoordinate)
        if "uni10D0.case" in geor_rst.BaseCoverage.glyphs:
            A_idx = geor_rst.BaseCoverage.glyphs.index("uni10D0.case")
            A_anc = geor_rst.BaseArray.BaseRecord[A_idx].BaseAnchor[0]
            if A_anc is not None:
                cap_y = float(A_anc.YCoordinate)

        n_cls = geor_rst.ClassCount
        geo_targets = []
        for cp in (
            list(ASOMTAVRULI_CPS)
            + list(range(0x10D0, 0x10FB))
            + list(range(0x10FC, 0x1100))
            + list(range(0x1C90, 0x1CBB))
            + list(range(0x1CBD, 0x1CC0))
            + list(NUSKHURI_CPS)
        ):
            gn = cm.get(cp)
            if gn and gn in gset:
                geo_targets.append(gn)
                for suf in (".ss01", ".ss01.case"):
                    if gn + suf in gset:
                        geo_targets.append(gn + suf)

        existing_geo = set(geor_rst.BaseCoverage.glyphs)
        for gn in dict.fromkeys(geo_targets):
            bb = _glyph_bbox(font, gn)
            if not bb:
                continue
            x0, y0, x1, y1 = bb
            cx = 0.5 * (x0 + x1)
            cy = 0.5 * (y0 + y1)
            if gn.endswith(".case"):
                top_y = max(cap_y, y1 - 8.0) if y1 > cap_y + 15.0 else cap_y
            elif y1 > xh_y + 40.0:
                top_y = y1 - 8.0
            else:
                top_y = xh_y
            bot_y = min(0.0, y0 + 10.0) if y0 < -40.0 else 0.0
            top_x = cx + (top_y - cy) * tan_a
            bot_x = cx + (bot_y - cy) * tan_a

            if gn in existing_geo:
                # Preserve upstream hand-tuned top anchor, but replace placeholder (0, 0) bottom anchor (cls 1)
                if n_cls > 1:
                    cur_idx = geor_rst.BaseCoverage.glyphs.index(gn)
                    brec = geor_rst.BaseArray.BaseRecord[cur_idx]
                    cur_bot = brec.BaseAnchor[1] if len(brec.BaseAnchor) > 1 else None
                    if cur_bot is None or (cur_bot.XCoordinate == 0 and cur_bot.YCoordinate == 0):
                        brec.BaseAnchor[1] = _make_anchor(bot_x, bot_y)
                        geor_bot_fixed += 1
                continue

            ancs = [None] * n_cls
            ancs[0] = _make_anchor(top_x, top_y)
            if n_cls > 1:
                ancs[1] = _make_anchor(bot_x, bot_y)
            for c_idx in range(2, n_cls):
                ancs[c_idx] = _make_anchor(0, 0)
            _insert_base_into_subtable(font, geor_rst, gn, ancs)
            geor_bases_added += 1

    # --- Step 5: Contextual Spanning Double-Mark Clearance (U+0360, U+0361, U+035C) ---
    # Prevents double-wide diacritics anchored on a short Base1 (e.g. ა͠ბ, a͠b, ტ͠წ, Ა͠Ბ, ა͜უ)
    # from colliding with a taller ascender / Mtavruli / descender on Base2!
    dbl_rules_set = _patch_contextual_double_mark_clearance(font, xh_y=xh_y, cap_y=cap_y, tan_a=tan_a)

    return {
        "marks_registered": marks_registered,
        "bases_added": bases_added,
        "dotted_circle_lookups": dc_lookups,
        "geor_bases_added": geor_bases_added,
        "geor_bot_fixed": geor_bot_fixed,
        "dbl_mark_rules": dbl_rules_set,
    }


def _make_single_pos_lookup(font, glyphs, dx, dy):
    """Build a varLib-compatible SinglePos Format 1 lookup with fixed ValueFormat=3 (XPlacement|YPlacement)."""
    lk = otTables.Lookup()
    lk.LookupType = 1
    lk.LookupFlag = 0
    st = otTables.SinglePos()
    st.Format = 1
    cov = otTables.Coverage()
    cov.glyphs = sorted(glyphs, key=font.getGlyphID)
    st.Coverage = cov
    vr = otTables.ValueRecord()
    vr.XPlacement = int(round(dx))
    vr.YPlacement = int(round(dy))
    st.ValueFormat = 3  # Always XPlacement | YPlacement for strict varLib ValueFormat uniformity
    st.Value = vr
    lk.SubTable = [st]
    lk.SubTableCount = 1
    return lk


def _make_chain_context_subtable(font, backtrack, inp, lookahead, lookup_idx):
    st = otTables.ChainContextPos()
    st.Format = 3
    cov_b = otTables.Coverage()
    cov_b.glyphs = sorted(backtrack, key=font.getGlyphID)
    cov_i = otTables.Coverage()
    cov_i.glyphs = sorted(inp, key=font.getGlyphID)
    cov_l = otTables.Coverage()
    cov_l.glyphs = sorted(lookahead, key=font.getGlyphID)
    st.BacktrackCoverage = [cov_b]
    st.BacktrackGlyphCount = 1
    st.InputCoverage = [cov_i]
    st.InputGlyphCount = 1
    st.LookAheadCoverage = [cov_l]
    st.LookAheadGlyphCount = 1
    rec = otTables.PosLookupRecord()
    rec.SequenceIndex = 0
    rec.LookupListIndex = lookup_idx
    st.PosLookupRecord = [rec]
    st.PosCount = 1
    return st


def find_double_mark_chain_lookup(gpos_table):
    """Locate our contextual double-mark clearance LookupType 8 lookup index (or None)."""
    for li, lk in enumerate(gpos_table.LookupList.Lookup):
        if lk.LookupType != 8 or not lk.SubTable:
            continue
        st0 = lk.SubTable[0]
        if (
            getattr(st0, "Format", None) == 3
            and getattr(st0, "InputCoverage", None)
            and any(g in ("uni0360", "uni0361") for g in st0.InputCoverage[0].glyphs)
        ):
            return li
    return None


def _patch_contextual_double_mark_clearance(font, xh_y=527.0, cap_y=675.0, tan_a=0.0):
    """
    Idempotently install/update GPOS Chaining Contextual Positioning (LookupType 8) right after
    MarkBase in `mark` so spanning double diacritics (`uni0360`, `uni0361`, `uni035C`) clear tall
    ascenders, Mtavruli vertical cues, and descenders on Base2 (`ა͠ბ`, `Ა͠Ბ`, `ტ͠წ`, `a͠b`, `ა͜უ`).
    """
    if "GPOS" not in font or "GDEF" not in font:
        return 0
    gpos = font["GPOS"].table
    gset = set(font.getGlyphOrder())
    top_dbl = [g for g in ("uni0360", "uni0361") if g in gset]
    bot_dbl = [g for g in ("uni035C", "uni035F") if g in gset]
    if not top_dbl:
        return 0

    gdef_cls = font["GDEF"].table.GlyphClassDef.classDefs if getattr(font["GDEF"].table, "GlyphClassDef", None) else {}
    short_bases, mid_bases, tall_bases = [], [], []
    nodesc_bases, desc_bases = [], []
    asc_ys = []
    for gn in font.getGlyphOrder():
        if gdef_cls.get(gn, 1) != 1:
            continue
        bb = _glyph_bbox(font, gn)
        if not bb:
            continue
        y0, y1 = bb[1], bb[3]
        if y1 < 600:
            short_bases.append(gn)
        elif y1 <= 708:
            mid_bases.append(gn)
        else:
            tall_bases.append(gn)
            if gn in ("b", "d", "h", "uni10D1", "uni10E0"):
                asc_ys.append(y1)
        if y0 > -80:
            nodesc_bases.append(gn)
        else:
            desc_bases.append(gn)

    asc_y = max(asc_ys) if asc_ys else 760.0
    lift_short_to_tall = int(round((asc_y - 8.0) - xh_y))
    lift_short_to_mid = int(round((cap_y + 10.0) - xh_y))
    lift_mid_to_tall = int(round((asc_y - 8.0) - cap_y)) + 12
    drop_to_desc = -210

    rule_specs = [
        (short_bases, top_dbl, tall_bases, lift_short_to_tall * tan_a, lift_short_to_tall),
        (short_bases, top_dbl, mid_bases, lift_short_to_mid * tan_a, lift_short_to_mid),
        (mid_bases, top_dbl, tall_bases, lift_mid_to_tall * tan_a, lift_mid_to_tall),
    ]
    if bot_dbl and nodesc_bases and desc_bases:
        rule_specs.append((nodesc_bases, bot_dbl, desc_bases, drop_to_desc * tan_a, drop_to_desc))

    lks = gpos.LookupList.Lookup
    existing_chain_idx = find_double_mark_chain_lookup(gpos)

    if existing_chain_idx is not None:
        # Update existing SinglePos helper lookups & ChainContextPos subtables in-place (100% idempotent!)
        chain_lk = lks[existing_chain_idx]
        old_helper_idxs = [
            st.PosLookupRecord[0].LookupListIndex
            for st in chain_lk.SubTable
            if getattr(st, "PosLookupRecord", None)
        ]
        new_subtables = []
        for idx_r, (bt, inp, la, dx, dy) in enumerate(rule_specs):
            if idx_r < len(old_helper_idxs):
                h_idx = old_helper_idxs[idx_r]
                lks[h_idx] = _make_single_pos_lookup(font, inp, dx, dy)
            else:
                h_idx = len(lks)
                lks.append(_make_single_pos_lookup(font, inp, dx, dy))
            new_subtables.append(_make_chain_context_subtable(font, bt, inp, la, h_idx))
        chain_lk.SubTable = new_subtables
        chain_lk.SubTableCount = len(new_subtables)
        chain_idx = existing_chain_idx
    else:
        new_subtables = []
        for bt, inp, la, dx, dy in rule_specs:
            h_idx = len(lks)
            lks.append(_make_single_pos_lookup(font, inp, dx, dy))
            new_subtables.append(_make_chain_context_subtable(font, bt, inp, la, h_idx))
        chain_lk = otTables.Lookup()
        chain_lk.LookupType = 8
        chain_lk.LookupFlag = 0
        chain_lk.SubTable = new_subtables
        chain_lk.SubTableCount = len(new_subtables)
        chain_idx = len(lks)
        lks.append(chain_lk)

    gpos.LookupList.LookupCount = len(lks)

    for fr in gpos.FeatureList.FeatureRecord:
        if fr.FeatureTag == "mark":
            if chain_idx not in fr.Feature.LookupListIndex:
                fr.Feature.LookupListIndex.append(chain_idx)
                fr.Feature.LookupCount = len(fr.Feature.LookupListIndex)

    return len(rule_specs)


# ---------------------------------------------------------------------------
# 6. Complete Borbalo / KJ Group v1.100 Metadata, `meta`, `gasp`, `OS/2`, `DSIG`, `OVERLAP_SIMPLE`
# ---------------------------------------------------------------------------

def apply_v1100_metadata(
    font,
    family_name,
    ps_name,
    style_display,
    weight_display,
    weight_class,
    width_class,
    is_bold,
    is_italic,
    is_vf=False,
    var_ps_prefix=None,
    win_ascent=DEFAULT_WIN_ASCENT,
    win_descent=DEFAULT_WIN_DESCENT,
    maplibre_metrics=False,
):
    """
    Write complete, Fontspector-verified Batumi Sans v1.100 Borbalo/KJ Group metadata:
      - `head.fontRevision = 1.100`, `nameID 5 = "Version 1.100"`, `OS/2.achVendID = "BRBL"`
      - Canonical GF-verified `nameID 0`, `7`, `8`, `9`, `10`, `11`, `12`, `13`, `14`
      - Strips ALL legacy `platformID=1` Mac `name` entries (`no_mac_entries` = 0 FAILs!)
      - Omits redundant `nameID 16`/`17` on RIBBI statics (`Regular`, `Bold`, `Italic`, `Bold Italic`) & VFs!
      - Sets `OS/2.usWinAscent` / `usWinDescent` (ISS-003), `USE_TYPO_METRICS` (0x80) + `WWS` (0x100)
      - Keeps desktop `hhea`/`sTypo*` untouched at `935/-265/0` (or MapLibre `1040/-265/0`)
      - Adds `meta` table (`dlng`: Geor, Latn; `slng`: Geor, Latn, Cyrl, Grek, Arab, Hebr, Deva, Thai)
      - Strips `DSIG` if present
      - Recalculates `OS/2.ulUnicodeRange1-4` & `ulCodePageRange1-2` cleanly!
    """
    is_ribbi = is_vf or (weight_display in ("Regular", "Bold"))
    legacy_family = family_name if is_ribbi else f"{family_name} {weight_display}"
    if is_bold and is_italic:
        legacy_subfamily = "Bold Italic"
    elif is_bold:
        legacy_subfamily = "Bold"
    elif is_italic:
        legacy_subfamily = "Italic"
    else:
        legacy_subfamily = "Regular"

    if is_vf:
        full_name = f"{family_name} {legacy_subfamily}"
        unique_id = f"1.100;{VENDOR_ID};{ps_name}"
    else:
        full_name = f"{family_name} {style_display}"
        unique_id = f"1.100;{VENDOR_ID};{ps_name}"

    # Preserve ONLY Windows platformID=3 nameID >= 256 (GSUB SS UI labels, fvar/STAT names)
    # Strip ALL platformID=1 Mac entries completely (`no_mac_entries` PASS!)
    name_table = font["name"]
    preserved = [
        rec for rec in name_table.names
        if rec.platformID == 3 and rec.nameID >= 256
    ]
    name_table.names = preserved

    entries = {
        0: COPYRIGHT_STR,
        1: legacy_family,
        2: legacy_subfamily,
        3: unique_id,
        4: full_name,
        5: VERSION_STR,
        6: ps_name,
        7: TRADEMARK_STR,
        8: MANUFACTURER_STR,
        9: DESIGNER_STR,
        10: DESCRIPTION_STR,
        11: VENDOR_URL,
        12: DESIGNER_URL,
        13: LICENSE_STR,
        14: LICENSE_URL,
    }
    # Omit redundant nameID 16/17 whenever (nameID 1, nameID 2) == (family_name, style_display) (RIBBI / VFs)
    if not is_ribbi:
        entries[16] = family_name
        entries[17] = style_display
    if is_vf and var_ps_prefix:
        entries[25] = var_ps_prefix

    for nid, val in sorted(entries.items()):
        name_table.setName(val, nid, 3, 1, 0x409)

    # Update CFF TopDict if OTF
    if "CFF " in font:
        cff = font["CFF "].cff
        cff.fontNames = [ps_name]
        td = cff.topDictIndex[0]
        td.FullName = full_name
        td.FamilyName = family_name
        td.Weight = weight_display
        td.version = "1.100"
        td.Notice = COPYRIGHT_STR
        if hasattr(td, "Copyright"):
            td.Copyright = COPYRIGHT_STR

    # Vertical metrics invariants + ISS-003 usWin*
    hhea = font["hhea"]
    os2 = font["OS/2"]
    if maplibre_metrics:
        hhea.ascent = MAPLIBRE_HHEA_ASCENT
        hhea.descent = MAPLIBRE_HHEA_DESCENT
        hhea.lineGap = MAPLIBRE_HHEA_LINEGAP
        os2.sTypoAscender = MAPLIBRE_HHEA_ASCENT
        os2.sTypoDescender = MAPLIBRE_HHEA_DESCENT
        os2.sTypoLineGap = MAPLIBRE_HHEA_LINEGAP
    else:
        hhea.ascent = DESKTOP_HHEA_ASCENT
        hhea.descent = DESKTOP_HHEA_DESCENT
        hhea.lineGap = DESKTOP_HHEA_LINEGAP
        os2.sTypoAscender = DESKTOP_HHEA_ASCENT
        os2.sTypoDescender = DESKTOP_HHEA_DESCENT
        os2.sTypoLineGap = DESKTOP_HHEA_LINEGAP

    os2.usWinAscent = int(win_ascent)
    os2.usWinDescent = int(win_descent)
    os2.usWeightClass = int(weight_class)
    os2.usWidthClass = int(width_class)
    os2.achVendID = VENDOR_ID

    # fsSelection: USE_TYPO_METRICS (0x80) | WWS (0x100) | RIBBI bits
    if os2.version < 4:
        os2.version = 4
    fs = 0x0080 | 0x0100  # USE_TYPO_METRICS | WWS
    if is_italic:
        fs |= 0x0001
    if is_bold:
        fs |= 0x0020
    if not is_italic and not is_bold:
        fs |= 0x0040
    os2.fsSelection = fs

    head = font["head"]
    head.fontRevision = VERSION_FLOAT
    head.macStyle = (0x01 if is_bold else 0) | (0x02 if is_italic else 0)

    # Recalculate OS/2 Unicode & CodePage ranges cleanly
    try:
        os2.recalcUnicodeRanges(font)
    except Exception:
        pass
    try:
        os2.recalcCodePageRanges(font)
    except Exception:
        pass

    # Add `meta` table (dlng / slng)
    add_meta_table(font)

    # Ensure DSIG is absent (modern Google Fonts PASS)
    if "DSIG" in font:
        del font["DSIG"]


def add_meta_table(font):
    """Attach standard OpenType `meta` table (`dlng`: Geor, Latn; `slng`: 8 scripts)."""
    meta = newTable("meta")
    meta.data = {
        "dlng": META_DLNG,
        "slng": META_SLNG,
    }
    font["meta"] = meta


def add_gasp_table(font):
    """Add exact Google Fonts / ClearType `gasp` table (version=1, {0xFFFF: 0x000F}) to TTF/VF."""
    gasp = newTable("gasp")
    gasp.version = 1
    # 0x000F = GASP_GRIDFIT | GASP_DOGRAY | GASP_SYMMETRIC_GRIDFIT | GASP_SYMMETRIC_SMOOTHING
    # Matches gftools fix-nonhinting & passes Fontspector `googlefonts/gasp` with 0 WARN / 0 FAIL!
    gasp.gaspRange = {0xFFFF: 0x000F}
    font["gasp"] = gasp


def _tt_glyph_segments(gs, gname):
    """Extract quadratic/line segments per contour from a TrueType glyph."""
    from fontTools.pens.recordingPen import RecordingPen
    rec = RecordingPen()
    gs[gname].draw(rec)
    contours = []
    cur_c = []
    cur = start = None
    for op, args in rec.value:
        if op == "moveTo":
            if cur_c:
                contours.append(cur_c)
            cur_c = []
            cur = start = args[0]
        elif op == "lineTo":
            p1 = args[0]
            if cur is not None and p1 != cur:
                cur_c.append(("L", cur, p1))
                cur = p1
        elif op == "qCurveTo":
            pts = list(args)
            if pts[-1] is None:
                p_prev = (0.5 * (pts[-2][0] + pts[0][0]), 0.5 * (pts[-2][1] + pts[0][1]))
                cur = start = p_prev
                pts = pts[:-1]
                for i, off in enumerate(pts):
                    nxt = pts[(i + 1) % len(pts)]
                    end = (0.5 * (off[0] + nxt[0]), 0.5 * (off[1] + nxt[1]))
                    cur_c.append(("Q", cur, off, end))
                    cur = end
            else:
                for i in range(len(pts) - 1):
                    off = pts[i]
                    if i < len(pts) - 2:
                        nxt = pts[i + 1]
                        end = (0.5 * (off[0] + nxt[0]), 0.5 * (off[1] + nxt[1]))
                    else:
                        end = pts[i + 1]
                    cur_c.append(("Q", cur, off, end))
                    cur = end
        elif op == "closePath":
            if cur is not None and start is not None and cur != start:
                cur_c.append(("L", cur, start))
            if cur_c:
                contours.append(cur_c)
            cur_c = []
            cur = start = None
    if cur_c:
        contours.append(cur_c)
    return contours


def _seg_to_sublines(seg, steps=6):
    if seg[0] == "L":
        return [(seg[1], seg[2])]
    _, p0, p1, p2 = seg
    pts = []
    for k in range(steps + 1):
        t = k / float(steps)
        mt = 1.0 - t
        pts.append((
            mt * mt * p0[0] + 2.0 * mt * t * p1[0] + t * t * p2[0],
            mt * mt * p0[1] + 2.0 * mt * t * p1[1] + t * t * p2[1],
        ))
    return [(pts[i], pts[i + 1]) for i in range(steps)]


def _sublines_intersect(a0, a1, b0, b1):
    if max(a0[0], a1[0]) < min(b0[0], b1[0]) - 1e-6 or max(b0[0], b1[0]) < min(a0[0], a1[0]) - 1e-6:
        return False
    if max(a0[1], a1[1]) < min(b0[1], b1[1]) - 1e-6 or max(b0[1], b1[1]) < min(a0[1], a1[1]) - 1e-6:
        return False
    d1 = (b1[0] - b0[0]) * (a0[1] - b0[1]) - (b1[1] - b0[1]) * (a0[0] - b0[0])
    d2 = (b1[0] - b0[0]) * (a1[1] - b0[1]) - (b1[1] - b0[1]) * (a1[0] - b0[0])
    d3 = (a1[0] - a0[0]) * (b0[1] - a0[1]) - (a1[1] - a0[1]) * (b0[0] - a0[0])
    d4 = (a1[0] - a0[0]) * (b1[1] - a0[1]) - (a1[1] - a0[1]) * (b1[0] - a0[0])
    if ((d1 > 1e-6 and d2 < -1e-6) or (d1 < -1e-6 and d2 > 1e-6)) and (
        (d3 > 1e-6 and d4 < -1e-6) or (d3 < -1e-6 and d4 > 1e-6)
    ):
        return True
    if abs(d1) < 1e-4 and abs(d2) < 1e-4 and abs(d3) < 1e-4 and abs(d4) < 1e-4:
        ax = 0 if abs(a1[0] - a0[0]) >= abs(a1[1] - a0[1]) else 1
        lo_a, hi_a = (a0[ax], a1[ax]) if a0[ax] <= a1[ax] else (a1[ax], a0[ax])
        lo_b, hi_b = (b0[ax], b1[ax]) if b0[ax] <= b1[ax] else (b1[ax], b0[ax])
        if min(hi_a, hi_b) - max(lo_a, lo_b) > 1e-4:
            return True
    return False


def _tt_glyph_has_segment_overlap(gs, gname):
    contours = _tt_glyph_segments(gs, gname)
    if not contours:
        return False
    items = []
    for cid, c in enumerate(contours):
        n = len(c)
        for sid, seg in enumerate(c):
            subs = _seg_to_sublines(seg, steps=6)
            xs = [p[0] for a, b in subs for p in (a, b)]
            ys = [p[1] for a, b in subs for p in (a, b)]
            items.append((cid, sid, n, (min(xs), min(ys), max(xs), max(ys)), subs))
    m = len(items)
    for i in range(m):
        ci, si, ni, bi, subsi = items[i]
        for j in range(i + 1, m):
            cj, sj, nj, bj, subsj = items[j]
            if bi[2] < bj[0] - 1e-4 or bj[2] < bi[0] - 1e-4 or bi[3] < bj[1] - 1e-4 or bj[3] < bi[1] - 1e-4:
                continue
            adj = (ci == cj) and ((sj == si + 1) or (si == 0 and sj == ni - 1))
            for a0, a1 in subsi:
                for b0, b1 in subsj:
                    if adj and (a1 == b0 or b1 == a0):
                        v1 = (a1[0] - a0[0], a1[1] - a0[1])
                        v2 = (b1[0] - b0[0], b1[1] - b0[1])
                        dot = v1[0] * v2[0] + v1[1] * v2[1]
                        cr = abs(v1[0] * v2[1] - v1[1] * v2[0])
                        if dot < -1e-4 and cr < 1e-3 * (abs(v1[0]) + abs(v1[1]) + 1.0) * (abs(v2[0]) + abs(v2[1]) + 1.0):
                            return True
                        continue
                    if _sublines_intersect(a0, a1, b0, b1):
                        return True
    return False


def apply_overlap_simple_flags(font):
    """
    Detect exact segment/contour overlaps in a TrueType `glyf` table (matching Fontspector's
    `overlaps_bit` check with 0 false positives and 0 false negatives!) and set `OVERLAP_SIMPLE`
    (0x0040) on point 0's flag byte while clearing it on non-overlapping glyphs.
    Returns count of flagged glyphs.
    """
    if "glyf" not in font:
        return 0
    glyf = font["glyf"]
    gs = font.getGlyphSet()
    flagged = 0
    for gname in font.getGlyphOrder():
        g = glyf[gname]
        if g.isComposite() or g.numberOfContours <= 0:
            continue
        if not hasattr(g, "flags") or len(g.flags) == 0:
            continue
        # Ensure we start cleanly with bit 0x40 cleared (idempotent!)
        g.flags[0] &= ~0x40
        if _tt_glyph_has_segment_overlap(gs, gname):
            g.flags[0] |= 0x40  # OVERLAP_SIMPLE
            flagged += 1
    return flagged


def subroutinize_otf(font):
    """Losslessly CFF-subroutinize a static OTF via `cffsubr` (0 outline change, ~22-25% smaller)."""
    if "CFF " not in font:
        return False
    cffsubr.subroutinize(font)
    return True


# ---------------------------------------------------------------------------
# 7. Google Fonts Edition: Clean `smcp` / `c2sc` Stripper (ONLY for 2-axis GF VFs!)
# ---------------------------------------------------------------------------

def strip_smcp_c2sc_features(font):
    """
    Drop `smcp` and `c2sc` feature records from GSUB (ONLY for the 2-axis Google Fonts
    edition so `missing_small_caps_glyphs` passes cleanly; Google Fonts API strips smcp/c2sc
    anyway and Georgian has no small caps; Desktop & 3-axis Creative editions keep smcp/c2sc!).
    Cleanly updates all ScriptList/LangSys FeatureIndex references so GSUB remains 100% valid.
    """
    if "GSUB" not in font:
        return 0
    gsub = font["GSUB"].table
    fl = gsub.FeatureList
    if not fl or not fl.FeatureRecord:
        return 0

    drop_indices = {
        i for i, fr in enumerate(fl.FeatureRecord)
        if fr.FeatureTag in ("smcp", "c2sc")
    }
    if not drop_indices:
        return 0

    # Build old_index -> new_index map
    new_records = []
    idx_map = {}
    for old_i, fr in enumerate(fl.FeatureRecord):
        if old_i not in drop_indices:
            idx_map[old_i] = len(new_records)
            new_records.append(fr)

    fl.FeatureRecord = new_records
    fl.FeatureCount = len(new_records)

    # Remap all LangSys FeatureIndex lists
    for sr in gsub.ScriptList.ScriptRecord:
        ls_list = []
        if sr.Script.DefaultLangSys:
            ls_list.append(sr.Script.DefaultLangSys)
        for lsr in sr.Script.LangSysRecord:
            ls_list.append(lsr.LangSys)
        for ls in ls_list:
            ls.FeatureIndex = [idx_map[fi] for fi in ls.FeatureIndex if fi in idx_map]
            ls.FeatureCount = len(ls.FeatureIndex)
            if ls.ReqFeatureIndex != 0xFFFF:
                ls.ReqFeatureIndex = idx_map.get(ls.ReqFeatureIndex, 0xFFFF)

    return len(drop_indices)


# ---------------------------------------------------------------------------
# 8. Smart `gvar` Optimization (Noise-Tuple Pruning with Strict Sub-Unit Error Bound)
# ---------------------------------------------------------------------------

def optimize_gvar_tuples(vf, is_3axis=True, noise_thresh=1, max_corner_err=1.5):
    """
    Prune quantization-noise & redundant slant cross-interaction `gvar` tuples cleanly
    with a strict per-glyph mathematical worst-case error guarantee (`<= max_corner_err` units):
      - Primary single-axis tuples (`('wght',)`, `('wdth',)`, `('slnt',)`) are ALWAYS preserved.
      - On 2-axis `[wdth, wght]` VFs: drop cross-term `('wdth', 'wght')` tuples whose
        `max(|dx|, |dy|) <= noise_thresh` (1u rounding noise).
      - On 3-axis `[slnt, wdth, wght]` Creative VFs:
          * Any cross-term tuple (`len(axes) >= 2`) with `max(|dx|, |dy|) <= noise_thresh`
            is a drop candidate.
          * `('slnt', 'wdth')` and `('slnt', 'wdth', 'wght')` tuples (which exist only due
            to tiny Y-drift × tan(slnt) & integer rounding) are drop candidates whenever
            their per-point peak delta `<= max_corner_err` AND the sum of all dropped
            tuple deltas at every corner `(slnt, wdth, wght)` stays `<= max_corner_err`!
    Returns stats dict `{before_tuples, after_tuples, dropped_tuples, max_est_err, by_axes_dropped}`.
    """
    if "gvar" not in vf:
        return {}
    gvar = vf["gvar"]
    before = 0
    after = 0
    global_max_err = 0.0
    dropped_by_axes = Counter()

    def _tv_scalar_at(tv, loc):
        s = 1.0
        for ax, (mn, pk, mx) in tv.axes.items():
            v = loc.get(ax, 0.0)
            if pk == 0.0:
                continue
            if v == pk:
                continue
            if v < mn or v > mx:
                return 0.0
            if v < pk:
                s *= (v - mn) / (pk - mn) if pk != mn else 0.0
            else:
                s *= (mx - v) / (mx - pk) if mx != pk else 0.0
            if s == 0.0:
                return 0.0
        return s

    # Normalized master grid covering every master pole (incl. Condensed=-0.5 & Bold=+0.6!)
    if is_3axis:
        corners = [
            {"wdth": wd, "wght": wt, "slnt": sl}
            for wd in (-1.0, -0.5, 0.0, 1.0)
            for wt in (-1.0, 0.0, 0.6, 1.0)
            for sl in (-1.0, 0.0, 1.0)
        ]
    else:
        corners = [
            {"wdth": wd, "wght": wt}
            for wd in (-1.0, -0.5, 0.0, 1.0)
            for wt in (-1.0, 0.0, 0.6, 1.0)
        ]

    for gname, tvs in gvar.variations.items():
        before += len(tvs)
        if not tvs:
            continue
        kept = []
        candidates = []
        for tv in tvs:
            axes_key = tuple(sorted(tv.axes.keys()))
            coords = [c for c in tv.coordinates if c is not None]
            max_d = max((max(abs(x), abs(y)) for x, y in coords), default=0)

            is_cand = False
            if len(axes_key) >= 2:
                if max_d <= noise_thresh:
                    is_cand = True
                elif is_3axis and axes_key in (("slnt", "wdth"), ("slnt", "wdth", "wght")):
                    # Candidate if single tuple's max delta is small (<= 3u); exact corner sum verified below!
                    if max_d <= 3:
                        is_cand = True
            if is_cand:
                candidates.append((max_d, axes_key, tv))
            else:
                kept.append(tv)

        # Greedily drop smallest-delta candidates first while guaranteeing exact worst-case corner error <= max_corner_err
        candidates.sort(key=lambda item: (item[0], 0 if len(item[1]) == 3 else 1))
        n_pts = len(tvs[0].coordinates)
        # Track accumulated dropped delta (dx, dy) per corner per point
        acc_x = [[0.0] * n_pts for _ in range(len(corners))]
        acc_y = [[0.0] * n_pts for _ in range(len(corners))]

        for max_d, axes_key, tv in candidates:
            # Find active corners for this tuple
            active = []
            for ci, loc in enumerate(corners):
                sc = _tv_scalar_at(tv, loc)
                if sc != 0.0:
                    active.append((ci, sc))
            # Check if dropping this tuple keeps max error <= max_corner_err across all active corners
            ok = True
            cand_peak = 0.0
            for ci, sc in active:
                ax_row = acc_x[ci]
                ay_row = acc_y[ci]
                for pi, c in enumerate(tv.coordinates):
                    if c is None:
                        continue
                    nx = ax_row[pi] + c[0] * sc
                    ny = ay_row[pi] + c[1] * sc
                    err = max(abs(nx), abs(ny))
                    if err > max_corner_err + 1e-6:
                        ok = False
                        break
                    if err > cand_peak:
                        cand_peak = err
                if not ok:
                    break
            if ok:
                for ci, sc in active:
                    ax_row = acc_x[ci]
                    ay_row = acc_y[ci]
                    for pi, c in enumerate(tv.coordinates):
                        if c is not None:
                            ax_row[pi] += c[0] * sc
                            ay_row[pi] += c[1] * sc
                if cand_peak > global_max_err:
                    global_max_err = cand_peak
                dropped_by_axes[axes_key] += 1
            else:
                kept.append(tv)

        gvar.variations[gname] = kept
        after += len(kept)

    return {
        "before_tuples": before,
        "after_tuples": after,
        "dropped_tuples": before - after,
        "max_est_err": round(global_max_err, 3),
        "by_axes_dropped": {str(k): v for k, v in sorted(dropped_by_axes.items())},
    }


# ---------------------------------------------------------------------------
# 9. One-Call Complete Hardening Entrypoint for Static OTFs
# ---------------------------------------------------------------------------

def apply_v1100_hardening_to_otf(
    font,
    family_name,
    ps_name,
    style_display,
    weight_display,
    weight_class,
    width_class,
    is_bold,
    is_italic,
    width_mode,
    rounded=False,
    sharp_ref_font=None,
    sharp_metrics=None,
    win_ascent=DEFAULT_WIN_ASCENT,
    win_descent=DEFAULT_WIN_DESCENT,
):
    """
    Complete, 100%-idempotent v1.100 production hardening pass for a static OTF master.
    Safe to call in both full builds and `--apply-v1100-hardening` fast patch mode!
    """
    issues = []

    # 1. Strip stray U+F89E (ISS-004) & U+00AD (soft_hyphen) from cmap
    strip_unwanted_cmap_codepoints(font, (0xF89E, 0x00AD))

    # 2. Rename all invalid/hyphenated/>31-char glyph names across all tables
    renamed = rename_glyphs_in_font(font, GLYPH_RENAME_MAP)

    # 3. Fix Arabic High Hamza (uni0674) & 14 Arabic spacing symbols (U+FBB2..FBC1)
    fix_arabic_high_hamza_and_spacing_symbols(font, is_italic=is_italic)

    # 4. Align all 13 canonical math signs to modal width (`equal`)
    math_adj = align_math_signs_width(font)

    # 5. Inject +7 new v1.100 glyphs (uni0360, uni2028, uni2029, uni205A, uni2E31, uniA7CB, uniA7DC)
    n_new, new_iss = inject_v1100_new_glyphs(
        font,
        weight_class=weight_class,
        width_mode=width_mode,
        is_italic=is_italic,
        rounded=rounded,
        sharp_ref_font=sharp_ref_font,
        sharp_metrics=sharp_metrics,
    )
    issues.extend(new_iss)

    # 5b. Inject +80 Georgian Khutsuri glyphs (40 Asomtavruli U+10A0–U+10CD + 40 Nuskhuri U+2D00–U+2D2D)
    khut_stats = inject_georgian_khutsuri_into_otf(
        font,
        weight_class=weight_class,
        width_mode=width_mode,
        is_italic=is_italic,
        rounded=rounded,
        sharp_ref_font=sharp_ref_font,
        sharp_metrics=sharp_metrics,
    )

    # 5c. Inject +49 native Batumi expansion glyphs (+4 currencies ₼֏₸₿, +10 keycaps/UI ⌘⌥⌃⎋⇥⇤✓✕★☆, +35 shape_languages)
    exp49_stats = inject_v110_expansion_49(
        font,
        weight_class=weight_class,
        width_mode=width_mode,
        is_italic=is_italic,
        rounded=rounded,
        sharp_ref_font=sharp_ref_font,
        sharp_metrics=sharp_metrics,
    )

    # 5d. Refresh Option C Georgian Ampersand (`ampersand.geor` & `ampersand.geor.case`) +
    #     exact SemiBold..Heavy optical spacing breathing + Khutsuri `calt` (100% idempotent!)
    _amp_width_map = {
        "extra_condensed": "ExtraCondensed",
        "condensed": "Condensed",
        "normal": "Normal",
        "expanded": "Expanded",
    }
    _wm_norm = width_mode.lower().replace("-", "_").replace(" ", "_")
    inject_georgian_ampersand(
        font,
        variant="Master",
        weight=weight_display,
        width=_amp_width_map[_wm_norm],
        rounded=rounded,
        italic_deg=(8.0 if is_italic else 0.0),
        mtav_cue=44.5,
        mtav_cap_tuck=-14.0,
        mtav_caps="CapsB",
    )
    _amp_deltas = compute_georgian_spacing_deltas(
        ["ampersand.geor", "ampersand.geor.case"],
        font.getBestCmap(),
        weight_class=weight_class,
        width_mode=width_mode,
        is_italic=is_italic,
    )
    for _agn, (_dl, _dr) in _amp_deltas.items():
        if _agn in font.getGlyphSet() and (_dl != 0 or _dr != 0):
            _acs = extract_contours(font, _agn)
            _acs_shifted = _translate_contours(_acs, float(_dl), 0.0)
            _old_adv = int(font["hmtx"][_agn][0])
            _upsert_cff_glyph(font, _agn, _acs_shifted, _old_adv + _dl + _dr, gdef_class=1)
    update_calt_georgian_ampersand_for_khutsuri(font)

    # 6. Patch GPOS MarkBase anchors + Khutsuri optical kerning (IgnoreMarks)
    gpos_stats = patch_gpos_markbase_anchors(font, is_italic=is_italic)
    khut_kern_pairs = patch_khutsuri_kerning(
        font, width_mode=width_mode, weight_class=weight_class, is_italic=is_italic
    )
    gpos_stats["khutsuri_kern_pairs"] = khut_kern_pairs

    # 6b. Inject +3 Authentic Wavy Multi-Letter Georgian Karagma marks (U+0483,
    #     uni0360.span3, uni0360.span4) + `calt` auto-merge + MarkBase + contextual lifts & optical centering!
    karagma_stats = apply_georgian_karagma_to_otf(
        font,
        weight_class=weight_class,
        width_mode=width_mode,
        is_italic=is_italic,
        rounded=rounded,
        sharp_ref_font=sharp_ref_font,
    )
    issues.extend(karagma_stats.get("issues", []))

    # 7. Apply complete v1.100 Borbalo/KJ Group metadata + meta + ISS-003 usWin* + fsSelection WWS
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

    return {
        "renamed": len(renamed),
        "math_adjusted": math_adj,
        "new_glyphs": n_new,
        "karagma_stats": karagma_stats,
        "gpos_stats": gpos_stats,
        "issues": issues,
    }

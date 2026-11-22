#!/usr/bin/env python3
"""
Production 3-Axis Variable Font Build Pipeline for the Batumi Sans Superfamily.

Builds 4 true 3-axis (wdth 75..115 x wght 100..900 x slnt -12..0) TrueType OpenType
Variable Fonts (.ttf + .woff2 + dist/variable/batumi-sans-variable.css) from the 16 static
cubic OTF masters per VF (4 widths x 4 weights) in dist/otf/ plus exact sheared slant
master planes across the full (wght, wdth) grid (32 masters Upright / 48 masters Italic):

  1. dist/variable/BatumiSans-VF.ttf (+ .woff2)                — Family: Batumi Sans (Upright Sharp, slnt -12..0 default 0)
  2. dist/variable/BatumiSans-Italic-VF.ttf (+ .woff2)         — Family: Batumi Sans (True Cursive Italic Sharp, slnt -12..0 default -8)
  3. dist/variable/BatumiSansRounded-VF.ttf (+ .woff2)         — Family: Batumi Sans Rounded (Upright Rounded, slnt -12..0 default 0)
  4. dist/variable/BatumiSansRounded-Italic-VF.ttf (+ .woff2)  — Family: Batumi Sans Rounded (True Cursive Italic Rounded, slnt -12..0 default -8)

Engineering Architecture:
  - 4x4 = 16 base masters per VF (wdth in {75, 87.5, 100, 115}, wght in {100, 400, 700, 900})
    extended with exact affine horizontal-shear planes (pivot y = 264u = xHeight/2) at
    slnt = -12 (Upright -> 32 masters) and slnt in {0, -12} (Italic -> 48 masters)
    + empirically measured `avar` weight curve + exact tangent-linearized `avar` slant curve.
  - Bulletproof Multi-Master Point Compatibility:
      1. Exact PostScript topological even-odd winding normalization (CCW outer / CW hole)
      2. 3-tier contour-count reconciliation preserving ALL 4,579 glyphs (0 dropped glyphs)
      3. Optimal Hungarian (linear_sum_assignment) contour matching (un-slanted -8 deg for Italic)
      4. Fast-path cyclic start alignment + Corner-aware Needleman-Wunsch cyclic DP +
         exact de Casteljau subdivision (0 visual shape change on all 16 base masters!)
      5. Winding reversal (CCW->CW outer for TrueType) + joint cu2qu.curves_to_quadratic across
         all 16 masters simultaneously -> 100% identical point counts & on/off flags,
         followed by exact Jacobian=+1 affine shear for slnt master planes!
  - True Variable GPOS kerning (including variable `ჟრ` optical breathing across wght & wdth)
    and variable shear-tracked MarkBase/MarkLig/MarkMark anchors + intact GSUB (calt Georgian
    Ampersand, case, ss01, ss07, ss08, ccmp, liga, etc.) + all 46 Unicode Mtavruli
    U+1C90..U+1CBF + 36 named fvar instances + full 4-axis STAT table (wdth, wght, slnt, ital)
    with native Cmd+I Upright<->Italic style-linking (ital Format 3 0->1 / Format 1 1).
  - Rigorous automated 3D intermediate instantiation audit (skia-pathops, winding, hole area,
    avar weight & slant accuracy, variable kerning, Cmd+I style-linking, RFN/stale-name hygiene,
    FreeType) + visual 3-axis interpolation proof PNG.
"""

import argparse
import copy
import json
import math
import os
import sys
import tempfile
import time
import unicodedata
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pathops
from fontTools import cu2qu, varLib
from fontTools.designspaceLib import (
    AxisDescriptor,
    DesignSpaceDocument,
    InstanceDescriptor,
    SourceDescriptor,
)
from fontTools.otlLib.builder import buildStatTable
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables import otTables
from fontTools.ttLib.tables._g_l_y_f import Glyph, GlyphCoordinates
from fontTools.varLib.instancer import instantiateVariableFont
from PIL import Image, ImageDraw, ImageFont
from scipy.optimize import linear_sum_assignment

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
sys.path.insert(0, SRC_DIR)
sys.path.insert(0, SCRIPTS_DIR)

from rounder import (
    contour_signed_area,
    draw_contours_to_pen,
    eval_seg,
    extract_contours,
    fix_disjoint_outer_winding,
    measure_font_metrics,
    reverse_contour,
    seg_length,
    split_seg,
    tan_seg,
    turn_angle_deg,
)
from build_superfamily import (
    CURRENCY_CODEPOINTS,
    DIGIT_BASES,
    EXTRA_CODEPOINTS,
    EXTRA_GLYPHS,
    GEORGIAN_QUOTE_CODEPOINTS,
    ZH_TALL_LEFT_FOLLOWERS,
    get_currency_glyphs,
    get_georgian_glyphs,
)
from georgian_ampersand import update_calt_georgian_ampersand_for_khutsuri
from georgian_karagma import (
    KARAGMA_GLYPH_NAMES,
    KARAGMA_NEW_CPS,
    find_karagma_chain_lookup,
    find_karagma_xshift_chain_lookup,
    wire_gsub_karagma,
)
from georgian_khutsuri import KHUTSURI_CPS, KHUTSURI_GLYPH_NAMES
from v110_expansion import EXPANSION_49_CPS, EXPANSION_49_GLYPH_NAMES
from georgian_spacing import (
    compute_slnt_breathing,
    get_georgian_slnt_target_glyphs,
    is_georgian_spacing_target,
    shift_gpos_mark_anchors_x,
)
from production_hardening import (
    COPYRIGHT_STR,
    DESCRIPTION_STR,
    DEFAULT_WIN_ASCENT,
    DEFAULT_WIN_DESCENT,
    add_gasp_table,
    apply_overlap_simple_flags,
    apply_v1100_metadata,
    ceil10,
    find_double_mark_chain_lookup,
    optimize_gvar_tuples,
    strip_smcp_c2sc_features,
)

KHUTSURI_GLYPH_SET = set(KHUTSURI_GLYPH_NAMES)

TAN_ITAL = math.tan(math.radians(8.0))
ITAL_PIVOT_Y = 264.0
SLNT_MIN = -12.0
SLNT_MAX = 0.0
SLNT_DEFAULT_UP = 0.0
SLNT_DEFAULT_IT = -8.0
CSS_CACHE_VER = "20261120-slnt"

# 4 widths x 4 weights = 16 masters; default master = Normal Regular (index 2*4 + 1 = 9)
WIDTH_MASTERS = [
    (75.0,  "ExtraCondensed", "Extra Condensed", 0.85),
    (87.5,  "Condensed",      "Condensed",       0.92),
    (100.0, "",               "Normal",          1.00),
    (115.0, "Expanded",       "Expanded",        1.14),
]
WEIGHT_MASTERS_UP = [
    (100, "Thin",    "Thin"),
    (400, "Regular", "Regular"),
    (700, "Bold",    "Bold"),
    (900, "Heavy",   "Heavy"),
]
WEIGHT_MASTERS_IT = [
    (100, "ThinItalic",  "Thin Italic"),
    (400, "Italic",      "Italic"),
    (700, "BoldItalic",  "Bold Italic"),
    (900, "HeavyItalic", "Heavy Italic"),
]
ALL_9_WEIGHTS_UP = [
    (100, "Thin",       "Thin"),
    (200, "ExtraLight", "ExtraLight"),
    (300, "Light",      "Light"),
    (400, "Regular",    "Regular"),
    (500, "Medium",     "Medium"),
    (600, "SemiBold",   "SemiBold"),
    (700, "Bold",       "Bold"),
    (800, "ExtraBold",  "ExtraBold"),
    (900, "Heavy",      "Heavy"),
]
ALL_9_WEIGHTS_IT = [
    (100, "ThinItalic",       "Thin"),
    (200, "ExtraLightItalic", "ExtraLight"),
    (300, "LightItalic",      "Light"),
    (400, "Italic",           "Regular"),
    (500, "MediumItalic",     "Medium"),
    (600, "SemiBoldItalic",   "SemiBold"),
    (700, "BoldItalic",       "Bold"),
    (800, "ExtraBoldItalic",  "ExtraBold"),
    (900, "HeavyItalic",      "Heavy"),
]
DEFAULT_WIDTH_IDX = 2   # wdth = 100.0 (Normal)
DEFAULT_WEIGHT_IDX = 1  # wght = 400 (Regular)
DEFAULT_MASTER_IDX = DEFAULT_WIDTH_IDX * 4 + DEFAULT_WEIGHT_IDX  # 9

VF_SPECS = {
    "sharp_upright": {
        "out_stem": "BatumiSans-VF",
        "gf_stem": "BatumiSans[wdth,wght]",
        "gf_dir": "batumisans",
        "family_name": "Batumi Sans",
        "subfamily_name": "Regular",
        "ps_name": "BatumiSans-Regular",
        "var_ps_prefix": "BatumiSans",
        "static_prefix_base": "BatumiSans",
        "rounded": False,
        "is_italic": False,
        "description": "3-axis Variable Font (wght 100-900, wdth 75-115, slnt -12..0) sharp upright Georgian, Latin, Cyrillic & Greek superfamily (SIL OFL 1.1)",
    },
    "sharp_italic": {
        "out_stem": "BatumiSans-Italic-VF",
        "gf_stem": "BatumiSans-Italic[wdth,wght]",
        "gf_dir": "batumisans",
        "family_name": "Batumi Sans",
        "subfamily_name": "Italic",
        "ps_name": "BatumiSans-Italic",
        "var_ps_prefix": "BatumiSansItalic",
        "static_prefix_base": "BatumiSans",
        "rounded": False,
        "is_italic": True,
        "description": "3-axis Variable Font (wght 100-900, wdth 75-115, slnt -12..0) sharp true cursive italic Georgian, Latin, Cyrillic & Greek superfamily (SIL OFL 1.1)",
    },
    "rounded_upright": {
        "out_stem": "BatumiSansRounded-VF",
        "gf_stem": "BatumiSansRounded[wdth,wght]",
        "gf_dir": "batumisansrounded",
        "family_name": "Batumi Sans Rounded",
        "subfamily_name": "Regular",
        "ps_name": "BatumiSansRounded-Regular",
        "var_ps_prefix": "BatumiSansRounded",
        "static_prefix_base": "BatumiSans",
        "rounded": True,
        "is_italic": False,
        "description": "3-axis Variable Font (wght 100-900, wdth 75-115, slnt -12..0) rounded upright Georgian, Latin, Cyrillic & Greek superfamily (SIL OFL 1.1)",
    },
    "rounded_italic": {
        "out_stem": "BatumiSansRounded-Italic-VF",
        "gf_stem": "BatumiSansRounded-Italic[wdth,wght]",
        "gf_dir": "batumisansrounded",
        "family_name": "Batumi Sans Rounded",
        "subfamily_name": "Italic",
        "ps_name": "BatumiSansRounded-Italic",
        "var_ps_prefix": "BatumiSansRoundedItalic",
        "static_prefix_base": "BatumiSans",
        "rounded": True,
        "is_italic": True,
        "description": "3-axis Variable Font (wght 100-900, wdth 75-115, slnt -12..0) rounded true cursive italic Georgian, Latin, Cyrillic & Greek superfamily (SIL OFL 1.1)",
    },
}

GF_9_WEIGHTS_UP = [
    (100, "Thin",       "Thin"),
    (200, "ExtraLight", "ExtraLight"),
    (300, "Light",      "Light"),
    (400, "Regular",    "Regular"),
    (500, "Medium",     "Medium"),
    (600, "SemiBold",   "SemiBold"),
    (700, "Bold",       "Bold"),
    (800, "ExtraBold",  "ExtraBold"),
    (900, "Black",      "Black"),
]
GF_9_WEIGHTS_IT = [
    (100, "ThinItalic",       "Thin Italic"),
    (200, "ExtraLightItalic", "ExtraLight Italic"),
    (300, "LightItalic",      "Light Italic"),
    (400, "Italic",           "Italic"),
    (500, "MediumItalic",     "Medium Italic"),
    (600, "SemiBoldItalic",   "SemiBold Italic"),
    (700, "BoldItalic",       "Bold Italic"),
    (800, "ExtraBoldItalic",  "ExtraBold Italic"),
    (900, "BlackItalic",      "Black Italic"),
]

VF_ORDER = ["sharp_upright", "sharp_italic", "rounded_upright", "rounded_italic"]

# Non-master & extreme 3D audit coordinates: (wght, wdth, slnt_or_None_for_default, label)
# None for slnt uses the VF's native default (0.0 Upright / -8.0 Italic).
AUDIT_COORDS_UP = [
    (250, 81.0,  0.0,   "w250_wd81_s0"),
    (550, 93.0, -4.0,   "w550_wd93_s-4"),
    (650, 108.0, -8.0,  "w650_wd108_s-8"),
    (820, 79.0, -12.0,  "w820_wd79_s-12"),
    (700, 115.0, -8.0,  "w700_wd115_s-8"),
    (900, 75.0, -12.0,  "w900_wd75_s-12"),
    (300, 100.0, 0.0,   "w300_wd100_Light"),
    (500, 100.0, 0.0,   "w500_wd100_Medium"),
]
AUDIT_COORDS_IT = [
    (250, 81.0,  -8.0,  "w250_wd81_s-8"),
    (550, 93.0,  -4.0,  "w550_wd93_s-4"),
    (650, 108.0,  0.0,  "w650_wd108_s0"),
    (820, 79.0, -12.0,  "w820_wd79_s-12"),
    (700, 115.0,  0.0,  "w700_wd115_s0"),
    (900, 75.0, -12.0,  "w900_wd75_s-12"),
    (300, 100.0, -8.0,  "w300_wd100_Light"),
    (500, 100.0, -8.0,  "w500_wd100_Medium"),
]


def master_prefix(width_token, rounded):
    r_tok = "Rounded" if rounded else ""
    return f"BatumiSans{width_token}{r_tok}"


def master_otf_path(otf_dir, width_token, weight_suffix, rounded):
    return os.path.join(otf_dir, f"{master_prefix(width_token, rounded)}-{weight_suffix}.otf")


# ---------------------------------------------------------------------------
# Geometry Helpers: Un-slanting, Winding, Contour Matching, DP Alignment, Cu2Qu
# ---------------------------------------------------------------------------

def unslant_pt(p, is_italic):
    if not is_italic:
        return p
    return (p[0] - (p[1] - ITAL_PIVOT_Y) * TAN_ITAL, p[1])


def reslant_pt(p, is_italic):
    if not is_italic:
        return p
    return (p[0] + (p[1] - ITAL_PIVOT_Y) * TAN_ITAL, p[1])


def scale_contours_x(contours, src_x0, src_x1, dst_x0, dst_x1, is_italic):
    """Horizontally scale contours (un-slant -> affine X map -> re-slant) preserving Y exactly."""
    src_w = max(src_x1 - src_x0, 1.0)
    dst_w = max(dst_x1 - dst_x0, 1.0)
    sx = dst_w / src_w

    def xform(pt):
        ux, uy = unslant_pt(pt, is_italic)
        nx = dst_x0 + (ux - src_x0) * sx
        return reslant_pt((nx, uy), is_italic)

    out = []
    for c in contours:
        nc = []
        for kind, pts in c:
            if kind == "line":
                nc.append(("line", (xform(pts[0]), xform(pts[1]))))
            else:
                nc.append(("cubic", tuple(xform(p) for p in pts)))
        out.append(nc)
    return out


def contours_bbox(contours, is_italic=False):
    xs, ys = [], []
    for c in contours:
        for kind, pts in c:
            if kind == "line":
                p = unslant_pt(pts[0], is_italic)
                xs.append(p[0]); ys.append(p[1])
            else:
                for k in range(5):
                    p = unslant_pt(eval_seg((kind, pts), k / 4.0), is_italic)
                    xs.append(p[0]); ys.append(p[1])
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


def contour_bbox_and_centroid(c, is_italic=False):
    pts = []
    for kind, spts in c:
        if kind == "line":
            pts.append(unslant_pt(spts[0], is_italic))
        else:
            for k in range(4):
                pts.append(unslant_pt(eval_seg((kind, spts), k / 4.0), is_italic))
    if not pts:
        return (0.0, 0.0, 0.0, 0.0), (0.0, 0.0)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys)), (sum(xs) / len(xs), sum(ys) / len(ys))


def pathops_to_contours(p):
    """Extract clean closed cubic/line contours from a skia-pathops Path."""
    rec = RecordingPen()
    p.draw(rec)
    contours, segs = [], []
    cur = start = None
    for op, args in rec.value:
        if op == "moveTo":
            if segs:
                contours.append(segs)
            segs = []
            cur = start = (float(args[0][0]), float(args[0][1]))
        elif op == "lineTo":
            p1 = (float(args[0][0]), float(args[0][1]))
            if cur is not None and math.hypot(p1[0] - cur[0], p1[1] - cur[1]) > 1e-3:
                segs.append(("line", (cur, p1)))
                cur = p1
        elif op == "curveTo":
            p1 = (float(args[0][0]), float(args[0][1]))
            p2 = (float(args[1][0]), float(args[1][1]))
            p3 = (float(args[2][0]), float(args[2][1]))
            if cur is not None and (
                math.hypot(p3[0] - cur[0], p3[1] - cur[1]) > 1e-3
                or math.hypot(p1[0] - cur[0], p1[1] - cur[1]) > 1e-3
            ):
                segs.append(("cubic", (cur, p1, p2, p3)))
                cur = p3
        elif op == "closePath":
            if cur is not None and start is not None and math.hypot(start[0] - cur[0], start[1] - cur[1]) > 1e-3:
                segs.append(("line", (cur, start)))
            if segs:
                contours.append(segs)
            segs = []
            cur = start = None
    if segs:
        contours.append(segs)
    return contours


def make_collapsed_contour(cx, cy, n_segs=4):
    """Zero-area collapsed point contour (for cleanly vanishing holes like uni0247 Heavy)."""
    pt = (float(cx), float(cy))
    return [("line", (pt, pt)) for _ in range(n_segs)]


def is_collapsed_contour(c):
    if not c:
        return True
    p0 = c[0][1][0]
    for _, pts in c:
        for p in pts:
            if abs(p[0] - p0[0]) > 1e-2 or abs(p[1] - p0[1]) > 1e-2:
                return False
    return True


def contour_sig(cs):
    """Topological (total_contours, n_outer_pos, n_hole_or_collapsed) signature."""
    n_pos = sum(1 for c in cs if not is_collapsed_contour(c) and contour_signed_area(c) >= 0)
    return (len(cs), n_pos, len(cs) - n_pos)


def reconcile_contour_counts(raw_contours_16, advs_16, is_italic):
    """
    Ensure all 16 masters have identical contour count AND outer/hole winding signature
    equal to the default master (idx=9).
    3-tier reconciliation:
      Pass A: pathops.simplify (resolves un-merged overlapping strokes in 1 master)
      Pass B: same-weight neighbor-width horizontal scale (preserves weight & width!)
      Pass C: vanishing tiny hole injection (e.g. uni0247 Heavy closing counter -> 0-area point!)
      Pass D: closest compatible weight/default donor scaled to master's advance width
    Returns (reconciled_16, mode_tag).
    """
    target_n = len(raw_contours_16[DEFAULT_MASTER_IDX])
    target_sig = contour_sig(raw_contours_16[DEFAULT_MASTER_IDX])

    out = [list(cs) for cs in raw_contours_16]
    used_tags = []

    # Pre-check: detect anomalous upstream width-master glyph swaps (e.g. uni0493.loclBGR where
    # Fira Sans Compressed Bold has a completely different <35% area outline than Normal Bold).
    for m in range(16):
        w_idx, wt_idx = divmod(m, 4)
        if w_idx == DEFAULT_WIDTH_IDX or not out[m]:
            continue
        norm_idx = DEFAULT_WIDTH_IDX * 4 + wt_idx
        if contour_sig(out[norm_idx]) != target_sig or not out[norm_idx]:
            continue
        a_norm = sum(abs(contour_signed_area(c)) for c in out[norm_idx])
        a_m = sum(abs(contour_signed_area(c)) for c in out[m])
        if a_norm > 10000.0 and a_m < 0.35 * a_norm:
            db = contours_bbox(out[norm_idx], is_italic)
            ratio = advs_16[m] / max(advs_16[norm_idx], 1.0)
            out[m] = scale_contours_x(out[norm_idx], db[0], db[2], db[0] * ratio, db[2] * ratio, is_italic)
            out[m], _ = fix_disjoint_outer_winding(out[m])
            used_tags.append("area_donor")

    if all(contour_sig(cs) == target_sig for cs in out):
        return out, "+".join(sorted(set(used_tags))) if used_tags else "exact"

    # Pass A: Try pathops.simplify on mismatched masters
    for m in range(16):
        if contour_sig(out[m]) == target_sig or not out[m]:
            continue
        p = pathops.Path()
        draw_contours_to_pen(out[m], p.getPen(), round_coords=False)
        ra = abs(p.area)
        ps = pathops.simplify(p, clockwise=False)
        sa = abs(ps.area)
        cand = pathops_to_contours(ps)
        cand, _ = fix_disjoint_outer_winding(cand)
        if contour_sig(cand) == target_sig and (ra < 10 or abs(ra - sa) / ra < 0.025):
            out[m] = cand
            used_tags.append("simp")

    if all(contour_sig(cs) == target_sig for cs in out):
        return out, "+".join(sorted(set(used_tags)))

    # Pass B: Same-weight neighbor-width horizontal scaling (e.g., uni20AF, uni0493.loclBGR, uni0414.loclBGR, Greek)
    for m in range(16):
        if contour_sig(out[m]) == target_sig:
            continue
        w_idx, wt_idx = divmod(m, 4)
        # Priority: Normal width (2), then closest width index
        donor_widths = sorted([wi for wi in range(4) if wi != w_idx], key=lambda wi: (0 if wi == 2 else 1, abs(wi - w_idx)))
        for d_wi in donor_widths:
            d = d_wi * 4 + wt_idx
            if contour_sig(out[d]) == target_sig and out[d]:
                db = contours_bbox(out[d], is_italic)
                if out[m]:
                    mb = contours_bbox(out[m], is_italic)
                    out[m] = scale_contours_x(out[d], db[0], db[2], mb[0], mb[2], is_italic)
                else:
                    ratio = advs_16[m] / max(advs_16[d], 1.0)
                    out[m] = scale_contours_x(out[d], 0.0, max(advs_16[d], 1.0), 0.0, max(advs_16[d] * ratio, 1.0), is_italic)
                out[m], _ = fix_disjoint_outer_winding(out[m])
                used_tags.append("width_donor")
                break

    if all(contour_sig(cs) == target_sig for cs in out):
        return out, "+".join(sorted(set(used_tags)))

    # Pass C: Vanishing tiny inner hole injection (handles Heavy closing counter like uni0247!)
    for m in range(16):
        if len(out[m]) != target_n - 1 or not out[m]:
            continue
        w_idx, wt_idx = divmod(m, 4)
        # Look for adjacent weight master at same width with target_sig
        adj_wts = sorted([wt for wt in range(4) if wt != wt_idx], key=lambda wt: abs(wt - wt_idx))
        for awt in adj_wts:
            d = w_idx * 4 + awt
            if contour_sig(out[d]) != target_sig:
                continue
            # Check if donor has 1 extra negative-area (hole) contour
            m_areas = [contour_signed_area(c) for c in out[m]]
            d_areas = [contour_signed_area(c) for c in out[d]]
            m_holes = sum(1 for a in m_areas if a < -1.0)
            d_holes = sum(1 for a in d_areas if a < -1.0)
            if d_holes == m_holes + 1:
                # Match existing target_n-1 contours to donor via centroid proximity to find vanished hole
                m_box = contours_bbox(out[m], is_italic)
                d_box = contours_bbox(out[d], is_italic)
                mw = max(m_box[2] - m_box[0], 1.0); mh = max(m_box[3] - m_box[1], 1.0)
                dw = max(d_box[2] - d_box[0], 1.0); dh = max(d_box[3] - d_box[1], 1.0)
                cost = np.zeros((len(out[m]), len(out[d])))
                for i, cm in enumerate(out[m]):
                    _, (mx, my) = contour_bbox_and_centroid(cm, is_italic)
                    nmx, nmy = (mx - m_box[0]) / mw, (my - m_box[1]) / mh
                    for j, cd in enumerate(out[d]):
                        _, (dx, dy) = contour_bbox_and_centroid(cd, is_italic)
                        ndx, ndy = (dx - d_box[0]) / dw, (dy - d_box[1]) / dh
                        sign_pen = 1000.0 if (m_areas[i] * d_areas[j] < 0) else 0.0
                        cost[i, j] = math.hypot(nmx - ndx, nmy - ndy) + sign_pen
                _, col_ind = linear_sum_assignment(cost)
                missing_js = [j for j in range(target_n) if j not in set(col_ind)]
                if len(missing_js) == 1 and d_areas[missing_js[0]] < 0:
                    _, (vx, vy) = contour_bbox_and_centroid(out[d][missing_js[0]], is_italic)
                    # Map vanished hole centroid proportionally into master m's bbox (un-slanted -> re-slanted)
                    nvx = (vx - d_box[0]) / dw
                    nvy = (vy - d_box[1]) / dh
                    target_u = (m_box[0] + nvx * mw, m_box[1] + nvy * mh)
                    cx, cy = reslant_pt(target_u, is_italic)
                    out[m] = list(out[m]) + [make_collapsed_contour(cx, cy)]
                    used_tags.append("vanish_hole")
                    break

    if all(contour_sig(cs) == target_sig for cs in out):
        return out, "+".join(sorted(set(used_tags)))

    # Pass D: Fallback to closest compatible weight at same width (or default master scaled by X)
    for m in range(16):
        if contour_sig(out[m]) == target_sig:
            continue
        w_idx, wt_idx = divmod(m, 4)
        cand_donors = [w_idx * 4 + wt for wt in sorted(range(4), key=lambda x: abs(x - wt_idx))] + [DEFAULT_MASTER_IDX]
        for d in cand_donors:
            if contour_sig(out[d]) == target_sig:
                if not out[d]:
                    out[m] = []
                else:
                    db = contours_bbox(out[d], is_italic)
                    if out[m]:
                        mb = contours_bbox(out[m], is_italic)
                        out[m] = scale_contours_x(out[d], db[0], db[2], mb[0], mb[2], is_italic)
                    else:
                        ratio = advs_16[m] / max(advs_16[d], 1.0)
                        out[m] = scale_contours_x(out[d], 0.0, max(advs_16[d], 1.0), 0.0, max(advs_16[d] * ratio, 1.0), is_italic)
                used_tags.append("wt_fallback")
                break

    return out, "+".join(sorted(set(used_tags)))


def match_contour_order(contours_16, is_italic):
    """Order every master's contours 1-to-1 with the default master via Hungarian assignment."""
    ref_cs = contours_16[DEFAULT_MASTER_IDX]
    nc = len(ref_cs)
    if nc <= 1:
        return contours_16

    def desc(cs):
        gb = contours_bbox(cs, is_italic)
        gw = max(gb[2] - gb[0], 1.0)
        gh = max(gb[3] - gb[1], 1.0)
        areas = [contour_signed_area(c) for c in cs]
        max_a = max((abs(a) for a in areas), default=1.0) or 1.0
        info = []
        for c, a in zip(cs, areas):
            cb, (cx, cy) = contour_bbox_and_centroid(c, is_italic)
            sign = 0 if is_collapsed_contour(c) else (1 if a >= 0 else -1)
            info.append((
                sign,
                (cx - gb[0]) / gw,
                (cy - gb[1]) / gh,
                (cb[0] - gb[0]) / gw,
                (cb[1] - gb[1]) / gh,
                (cb[2] - gb[0]) / gw,
                (cb[3] - gb[1]) / gh,
                abs(a) / max_a,
            ))
        return info

    ref_info = desc(ref_cs)
    ordered = [None] * 16
    ordered[DEFAULT_MASTER_IDX] = ref_cs

    for m in range(16):
        if m == DEFAULT_MASTER_IDX:
            continue
        m_info = desc(contours_16[m])
        cost = np.zeros((nc, nc))
        for i in range(nc):
            rs, rcx, rcy, rx0, ry0, rx1, ry1, ra = ref_info[i]
            for j in range(nc):
                ms, mcx, mcy, mx0, my0, mx1, my1, ma = m_info[j]
                if ms == 0:
                    # Collapsed contour preferentially matches a hole (-1)
                    sign_pen = 0.0 if rs <= 0 else 500.0
                elif rs == 0:
                    sign_pen = 0.0 if ms <= 0 else 500.0
                else:
                    sign_pen = 1000.0 if (rs * ms < 0) else 0.0
                cost[i, j] = (
                    sign_pen
                    + 2.0 * math.hypot(rcx - mcx, rcy - mcy)
                    + (abs(rx0 - mx0) + abs(ry0 - my0) + abs(rx1 - mx1) + abs(ry1 - my1))
                    + 0.5 * abs(ra - ma)
                )
        _, col_ind = linear_sum_assignment(cost)
        ordered[m] = [contours_16[m][j] for j in col_ind]
    return ordered


def contour_vertex_features(c, is_italic):
    n = len(c)
    cb, _ = contour_bbox_and_centroid(c, is_italic)
    x0, y0, x1, y1 = cb
    w = max(x1 - x0, 1.0)
    h = max(y1 - y0, 1.0)
    lens = [seg_length(s) for s in c]
    tot = max(sum(lens), 1e-6)
    acc = 0.0
    feats = []
    for i in range(n):
        p = unslant_pt(c[i][1][0], is_italic)
        pn = ((p[0] - x0) / w, (p[1] - y0) / h)
        ti = tan_seg(c[(i - 1) % n], 1.0)
        to = tan_seg(c[i], 0.0)
        if is_italic:
            ti = (ti[0] - ti[1] * TAN_ITAL, ti[1])
            L = math.hypot(ti[0], ti[1]) or 1.0
            ti = (ti[0] / L, ti[1] / L)
            to = (to[0] - to[1] * TAN_ITAL, to[1])
            L = math.hypot(to[0], to[1]) or 1.0
            to = (to[0] / L, to[1] / L)
        ang = turn_angle_deg(ti, to)
        feats.append((pn, ti, to, ang, acc / tot))
        acc += lens[i]
    return feats, (x0, y0, w, h), lens, tot


def sample_contour_dense(c, is_italic, K=64):
    cb, _ = contour_bbox_and_centroid(c, is_italic)
    x0, y0, x1, y1 = cb
    w = max(x1 - x0, 1.0)
    h = max(y1 - y0, 1.0)
    lens = [seg_length(s) for s in c]
    tot = max(sum(lens), 1e-6)
    cum = [0.0]
    for L in lens:
        cum.append(cum[-1] + L / tot)
    pts = []
    tans = []
    si = 0
    for k in range(K):
        u = k / K
        while si < len(c) - 1 and cum[si + 1] <= u:
            si += 1
        span = max(cum[si + 1] - cum[si], 1e-9)
        t = max(0.0, min(1.0, (u - cum[si]) / span))
        p = unslant_pt(eval_seg(c[si], t), is_italic)
        pts.append(((p[0] - x0) / w, (p[1] - y0) / h))
        tg = tan_seg(c[si], t)
        if is_italic:
            tg = (tg[0] - tg[1] * TAN_ITAL, tg[1])
            L = math.hypot(tg[0], tg[1]) or 1.0
            tg = (tg[0] / L, tg[1] / L)
        tans.append(tg)
    return np.array(pts), np.array(tans)


def rotate_contour(c, shift):
    n = len(c)
    if n == 0:
        return c
    s = shift % n
    return c[s:] + c[:s]


def split_seg_multi(seg, ts):
    """Exact de Casteljau subdivision at strictly increasing ts in (0, 1)."""
    out = []
    cur = seg
    prev_t = 0.0
    for t in ts:
        local_t = (t - prev_t) / max(1.0 - prev_t, 1e-9)
        local_t = max(0.01, min(0.99, local_t))
        left, cur = split_seg(cur, local_t)
        out.append(left)
        prev_t = t
    out.append(cur)
    return out


def align_single_contour(contours_16, ref_idx, is_italic):
    """
    Make all 16 masters' contours for a single contour index 100% segment-compatible &
    start-point-aligned with ZERO visual shape change (exact de Casteljau subdivision).
    """
    M = len(contours_16)
    collapsed_flags = [is_collapsed_contour(c) for c in contours_16]
    active_idxs = [m for m in range(M) if not collapsed_flags[m]]
    if not active_idxs:
        return [make_collapsed_contour(0.0, 0.0, 4) for _ in range(M)]

    eff_ref = ref_idx if ref_idx in active_idxs else active_idxs[0]
    ref_c = contours_16[eff_ref]
    n_ref = len(ref_c)

    # Tier 1: Fast path if all active masters share exact same segment count AND align tightly
    if all(len(contours_16[m]) == n_ref for m in active_idxs):
        f_ref, _, _, _ = contour_vertex_features(ref_c, is_italic)
        rotated = [None] * M
        rotated[eff_ref] = ref_c
        fast_ok = True
        for m in active_idxs:
            if m == eff_ref:
                continue
            fm, _, _, _ = contour_vertex_features(contours_16[m], is_italic)
            best_s, best_cost = 0, 1e18
            for s in range(n_ref):
                cost = 0.0
                for i in range(n_ref):
                    pr, tir, tor, angr, _ = f_ref[i]
                    pm, tim, tom, angm, _ = fm[(i + s) % n_ref]
                    dp = (pm[0] - pr[0]) ** 2 + (pm[1] - pr[1]) ** 2
                    dt = (
                        (tim[0] - tir[0]) ** 2 + (tim[1] - tir[1]) ** 2
                        + (tom[0] - tor[0]) ** 2 + (tom[1] - tor[1]) ** 2
                    )
                    cpen = 0.15 if ((abs(angm) > 25.0) != (abs(angr) > 25.0)) else 0.0
                    cost += dp + 0.12 * dt + cpen
                if cost < best_cost:
                    best_cost = cost
                    best_s = s
            max_d = max(
                math.hypot(
                    fm[(i + best_s) % n_ref][0][0] - f_ref[i][0][0],
                    fm[(i + best_s) % n_ref][0][1] - f_ref[i][0][1],
                )
                for i in range(n_ref)
            )
            if max_d > 0.28:
                fast_ok = False
                break
            rotated[m] = rotate_contour(contours_16[m], best_s)
        if fast_ok:
            for m in range(M):
                if collapsed_flags[m]:
                    pt = contours_16[m][0][1][0]
                    rotated[m] = make_collapsed_contour(pt[0], pt[1], n_ref)
            return rotated

    # Tier 2: Anchor ref on sharpest corner (if any) for canonical cyclic seam
    f_ref0, _, _, _ = contour_vertex_features(ref_c, is_italic)
    max_ang_idx = max(range(len(ref_c)), key=lambda i: abs(f_ref0[i][3]))
    ref_rot = rotate_contour(ref_c, max_ang_idx) if abs(f_ref0[max_ang_idx][3]) > 25.0 else ref_c

    ref_pts, ref_tans = sample_contour_dense(ref_rot, is_italic, K=64)
    f_ref, _, _, _ = contour_vertex_features(ref_rot, is_italic)
    aligned_init = [None] * M
    aligned_init[eff_ref] = ref_rot

    for m in active_idxs:
        if m == eff_ref:
            continue
        cm = contours_16[m]
        m_pts, m_tans = sample_contour_dense(cm, is_italic, K=64)
        best_k, best_sc = 0, 1e18
        for k in range(64):
            rp = np.roll(m_pts, -k, axis=0)
            rt = np.roll(m_tans, -k, axis=0)
            sc = float(np.sum((rp - ref_pts) ** 2) + 0.15 * np.sum((rt - ref_tans) ** 2))
            if sc < best_sc:
                best_sc = sc
                best_k = k
        u0_target = best_k / 64.0
        fm, _, _, _ = contour_vertex_features(cm, is_italic)
        pr0, tir0, tor0, angr0, _ = f_ref[0]
        best_v, best_vc = 0, 1e18
        for vi, (pm, tim, tom, angm, um) in enumerate(fm):
            du = abs(um - u0_target)
            du = min(du, 1.0 - du)
            dp = (pm[0] - pr0[0]) ** 2 + (pm[1] - pr0[1]) ** 2
            dt = (
                (tim[0] - tir0[0]) ** 2 + (tim[1] - tir0[1]) ** 2
                + (tom[0] - tor0[0]) ** 2 + (tom[1] - tor0[1]) ** 2
            )
            cpen = 0.20 if ((abs(angm) > 25.0) != (abs(angr0) > 25.0)) else 0.0
            vc = dp + 0.12 * dt + 0.80 * (du ** 2) + cpen
            if vc < best_vc:
                best_vc = vc
                best_v = vi
        aligned_init[m] = rotate_contour(cm, best_v)

    # Build unified slot sequence via Needleman-Wunsch DP
    slots = []
    for i, (pn, ti, to, ang, u) in enumerate(f_ref):
        slots.append({
            "p": [pn[0], pn[1]],
            "ti": [ti[0], ti[1]],
            "to": [to[0], to[1]],
            "u": u,
            "sharp": 1 if abs(ang) > 25.0 else 0,
            "cnt": 1,
            "members": {eff_ref: i},
        })

    # Order active masters by grid distance from ref_idx
    rw, rwt = divmod(eff_ref, 4)
    order = sorted(
        [m for m in active_idxs if m != eff_ref],
        key=lambda m: (abs(m // 4 - rw) + abs(m % 4 - rwt), -len(contours_16[m])),
    )
    GAP = 0.055

    for m in order:
        cm = aligned_init[m]
        fm, _, _, _ = contour_vertex_features(cm, is_italic)
        S = len(slots)
        Nm = len(fm)

        # Pre-extract slot means
        sl_means = []
        for sl in slots:
            sc = sl["cnt"]
            sl_means.append((
                sl["p"][0] / sc, sl["p"][1] / sc,
                sl["ti"][0] / sc, sl["ti"][1] / sc,
                sl["to"][0] / sc, sl["to"][1] / sc,
                sl["u"] / sc,
                (sl["sharp"] / sc) >= 0.5,
            ))

        def run_dp(v_shift):
            fm_s = fm[v_shift:] + fm[:v_shift]
            u_base = fm_s[0][4]
            us = [(x[4] - u_base) % 1.0 for x in fm_s]
            dp = np.full((S + 1, Nm + 1), 1e18)
            bt = np.zeros((S + 1, Nm + 1), dtype=np.int8)
            dp[0, 0] = 0.0
            for i in range(1, S + 1):
                dp[i, 0] = i * GAP
                bt[i, 0] = 1
            for j in range(1, Nm + 1):
                dp[0, j] = j * GAP
                bt[0, j] = 2
            for i in range(1, S + 1):
                spx, spy, stix, stiy, stox, stoy, su, ssharp = sl_means[i - 1]
                for j in range(1, Nm + 1):
                    pn, ti, to, ang, _ = fm_s[j - 1]
                    du = abs(us[j - 1] - su)
                    if du > 0.5:
                        du = 1.0 - du
                    cpen = 0.08 if ((abs(ang) > 25.0) != ssharp) else 0.0
                    mcost = (
                        (pn[0] - spx) ** 2 + (pn[1] - spy) ** 2
                        + 0.12 * (
                            (ti[0] - stix) ** 2 + (ti[1] - stiy) ** 2
                            + (to[0] - stox) ** 2 + (to[1] - stoy) ** 2
                        )
                        + 0.25 * (du * du)
                        + cpen
                    )
                    c0 = dp[i - 1, j - 1] + mcost
                    c1 = dp[i - 1, j] + GAP
                    c2 = dp[i, j - 1] + GAP
                    if c0 <= c1 and c0 <= c2:
                        dp[i, j] = c0
                        bt[i, j] = 0
                    elif c1 <= c2:
                        dp[i, j] = c1
                        bt[i, j] = 1
                    else:
                        dp[i, j] = c2
                        bt[i, j] = 2
            return float(dp[S, Nm]), bt, fm_s, us

        if Nm <= 8:
            shifts = range(Nm)
        else:
            shifts = (0, 1, 2, Nm - 2, Nm - 1)

        best_dp = None
        for sh in shifts:
            res = run_dp(sh)
            if best_dp is None or res[0] < best_dp[0]:
                best_dp = (res[0], sh, res[1], res[2], res[3])

        _, best_sh, bt, fm_s, us = best_dp
        aligned_init[m] = rotate_contour(cm, best_sh)

        ops = []
        i, j = S, Nm
        while i > 0 or j > 0:
            code = int(bt[i, j])
            ops.append((code, i - 1, j - 1))
            if code == 0:
                i -= 1; j -= 1
            elif code == 1:
                i -= 1
            else:
                j -= 1
        ops.reverse()

        new_slots = []
        for code, si, vj in ops:
            if code == 0:
                sl = slots[si]
                pn, ti, to, ang, _ = fm_s[vj]
                sl["p"][0] += pn[0]; sl["p"][1] += pn[1]
                sl["ti"][0] += ti[0]; sl["ti"][1] += ti[1]
                sl["to"][0] += to[0]; sl["to"][1] += to[1]
                sl["u"] += us[vj]
                sl["sharp"] += (1 if abs(ang) > 25.0 else 0)
                sl["cnt"] += 1
                sl["members"][m] = vj
                new_slots.append(sl)
            elif code == 1:
                new_slots.append(slots[si])
            else:
                pn, ti, to, ang, _ = fm_s[vj]
                new_slots.append({
                    "p": [pn[0], pn[1]],
                    "ti": [ti[0], ti[1]],
                    "to": [to[0], to[1]],
                    "u": us[vj],
                    "sharp": 1 if abs(ang) > 25.0 else 0,
                    "cnt": 1,
                    "members": {m: vj},
                })
        slots = new_slots

    # Exact de Casteljau subdivision at all unassigned slots per master
    S_fin = len(slots)
    out_contours = [None] * M
    for m in active_idxs:
        cm = aligned_init[m]
        fm, (x0, y0, w, h), lens, tot = contour_vertex_features(cm, is_italic)
        assigned = [(si, slots[si]["members"][m]) for si in range(S_fin) if m in slots[si]["members"]]
        na = len(assigned)
        slot_segs = [None] * S_fin
        for idx in range(na):
            sa, va = assigned[idx]
            sb, _vb = assigned[(idx + 1) % na]
            seg = cm[va]
            k = (sb - sa - 1) % S_fin if na > 1 else (S_fin - 1)
            if k == 0:
                slot_segs[sa] = seg
            else:
                u_start = fm[va][4]
                seg_frac = lens[va] / tot
                sample_pns = []
                sample_us = []
                for q in range(33):
                    t = q / 32.0
                    p = unslant_pt(eval_seg(seg, t), is_italic)
                    sample_pns.append(((p[0] - x0) / w, (p[1] - y0) / h))
                    sample_us.append((u_start + t * seg_frac) % 1.0)
                raw_ts = []
                for r in range(1, k + 1):
                    sr = (sa + r) % S_fin
                    sl = slots[sr]
                    sc = sl["cnt"]
                    tx, ty, tu = sl["p"][0] / sc, sl["p"][1] / sc, sl["u"] / sc
                    best_q = 1
                    best_d = 1e18
                    for q in range(1, 32):
                        du = abs(sample_us[q] - tu)
                        if du > 0.5:
                            du = 1.0 - du
                        d = (sample_pns[q][0] - tx) ** 2 + (sample_pns[q][1] - ty) ** 2 + 0.15 * (du * du)
                        if d < best_d:
                            best_d = d
                            best_q = q
                    raw_ts.append(best_q / 32.0)
                eps = min(0.05, 0.5 / (k + 1))
                clean_ts = []
                prev = 0.0
                for r, rt in enumerate(raw_ts):
                    lo = prev + eps
                    hi = 1.0 - (k - r) * eps
                    tc = max(lo, min(hi, rt))
                    clean_ts.append(tc)
                    prev = tc
                subs = split_seg_multi(seg, clean_ts)
                for r, sub in enumerate(subs):
                    slot_segs[(sa + r) % S_fin] = sub
        out_contours[m] = slot_segs

    for m in range(M):
        if collapsed_flags[m]:
            pt = contours_16[m][0][1][0]
            out_contours[m] = make_collapsed_contour(pt[0], pt[1], S_fin)

    return out_contours


def promote_line_to_cubic(seg):
    if seg[0] == "cubic":
        return seg
    a, b = seg[1]
    p1 = (a[0] + (b[0] - a[0]) / 3.0, a[1] + (b[1] - a[1]) / 3.0)
    p2 = (a[0] + 2.0 * (b[0] - a[0]) / 3.0, a[1] + 2.0 * (b[1] - a[1]) / 3.0)
    return ("cubic", (a, p1, p2, b))


def build_compatible_tt_glyphs_for_name(task):
    """
    Worker function (multiprocessing-safe): converts 16 cubic contour lists for a single glyph
    into 16 100%-compatible TrueType (coords, flags, endPtsOfContours) tuples via joint cu2qu!
    """
    gname, raw_contours_16, advs_16, is_italic, max_err = task

    # 1. Exact PostScript topological even-odd winding normalization
    fixed_16 = []
    for cs in raw_contours_16:
        if cs:
            fc, _ = fix_disjoint_outer_winding(cs)
            fixed_16.append(fc)
        else:
            fixed_16.append([])

    # 2. Reconcile contour counts across all 16 masters (0 dropped glyphs!)
    rec_16, rec_mode = reconcile_contour_counts(fixed_16, advs_16, is_italic)
    nc = len(rec_16[DEFAULT_MASTER_IDX])

    if nc == 0:
        return gname, [None] * 16, rec_mode

    # 3. Optimal Hungarian 1-to-1 contour ordering across masters
    ord_16 = match_contour_order(rec_16, is_italic)

    # 4. Per-contour DP alignment + segment type unification + winding reversal + joint cu2qu
    master_coords = [[] for _ in range(16)]
    master_flags = [[] for _ in range(16)]
    master_endpts = [[] for _ in range(16)]

    max_errs = [max_err] * 16

    for ci in range(nc):
        c_list = [ord_16[m][ci] for m in range(16)]
        aligned_16 = align_single_contour(c_list, DEFAULT_MASTER_IDX, is_italic)
        n_segs = len(aligned_16[0])

        # Unify segment types (line only if ALL 16 are lines; otherwise exact collinear cubic)
        is_cubic_slot = [any(aligned_16[m][si][0] == "cubic" for m in range(16)) for si in range(n_segs)]
        unified_16 = []
        for m in range(16):
            segs_m = [
                promote_line_to_cubic(aligned_16[m][si]) if is_cubic_slot[si] else aligned_16[m][si]
                for si in range(n_segs)
            ]
            # Reverse PostScript CCW-outer -> TrueType CW-outer BEFORE cu2qu!
            unified_16.append(reverse_contour(segs_m))

        # Joint cu2qu across all 16 masters segment-by-segment
        rev_is_cubic = list(reversed(is_cubic_slot))
        c_pts = [[] for _ in range(16)]
        c_flgs = [[] for _ in range(16)]

        for si in range(n_segs):
            if not rev_is_cubic[si]:
                for m in range(16):
                    p1 = unified_16[m][si][1][1]
                    c_pts[m].append((int(round(p1[0])), int(round(p1[1]))))
                    c_flgs[m].append(1)
            else:
                curves_16 = [unified_16[m][si][1] for m in range(16)]
                quads_16 = cu2qu.curves_to_quadratic(curves_16, max_errs, all_quadratic=True)
                for m in range(16):
                    q = quads_16[m]
                    # q[0] is start on-curve (emitted by previous seg), q[1:-1] off-curve, q[-1] end on-curve
                    for pt in q[1:-1]:
                        c_pts[m].append((int(round(pt[0])), int(round(pt[1]))))
                        c_flgs[m].append(0)
                    pend = q[-1]
                    c_pts[m].append((int(round(pend[0])), int(round(pend[1]))))
                    c_flgs[m].append(1)

        # Rotate each contour by 1 so index 0 is the on-curve start point (clean TrueType convention)
        for m in range(16):
            pts_m = [c_pts[m][-1]] + c_pts[m][:-1]
            flgs_m = [c_flgs[m][-1]] + c_flgs[m][:-1]
            master_coords[m].extend(pts_m)
            master_flags[m].extend(flgs_m)
            master_endpts[m].append(len(master_coords[m]) - 1)

    tt_payloads = [
        (master_coords[m], master_flags[m], master_endpts[m])
        for m in range(16)
    ]
    return gname, tt_payloads, rec_mode


def shear_tt_payload(payload, delta_tan, pivot_y=ITAL_PIVOT_Y):
    """
    Apply exact Jacobian=+1 horizontal shear x' = x + (y - pivot_y) * delta_tan to a
    TrueType (coords, flags, endpts) payload. Preserves exact point count, contour order,
    on/off flags, CW/CCW winding, hole area, and vertical metrics!
    """
    if payload is None or abs(delta_tan) < 1e-9:
        return payload
    coords, flags, endpts = payload
    sheared_coords = [
        (int(round(x + (y - pivot_y) * delta_tan)), y)
        for (x, y) in coords
    ]
    return (sheared_coords, list(flags), list(endpts))


def translate_tt_payload(payload, dx, dy=0):
    """Translate a TrueType (coords, flags, endpts) payload by exact integer (dx, dy)."""
    if payload is None or (dx == 0 and dy == 0):
        return payload
    coords, flags, endpts = payload
    idx, idy = int(round(dx)), int(round(dy))
    return ([(x + idx, y + idy) for (x, y) in coords], list(flags), list(endpts))


def payload_to_tt_glyph(payload):
    """Construct a TrueType glyf.Glyph directly (guarantees exact point counts & flags)."""
    g = Glyph()
    if payload is None:
        g.numberOfContours = 0
        return g
    coords, flags, endpts = payload
    g.numberOfContours = len(endpts)
    g.coordinates = GlyphCoordinates(coords)
    g.flags = bytearray(flags)
    g.endPtsOfContours = list(endpts)
    from fontTools.ttLib.tables import ttProgram
    g.program = ttProgram.Program()
    g.program.fromBytecode(b"")
    g.recalcBounds(None)
    return g


# ---------------------------------------------------------------------------
# Unified Variable GPOS (Variable Kerning + Variable Mark Anchors)
# ---------------------------------------------------------------------------

class FastKernQuerier:
    """Fast O(1) effective GPOS PairPos XAdvance kerning evaluator for a static font."""

    def __init__(self, font):
        self.lookups = []
        if "GPOS" not in font:
            return
        gpos = font["GPOS"].table
        kern_lks = sorted({
            li
            for fr in gpos.FeatureList.FeatureRecord
            if fr.FeatureTag == "kern"
            for li in fr.Feature.LookupListIndex
        })
        for li in kern_lks:
            lk = gpos.LookupList.Lookup[li]
            if lk.LookupType not in (2, 9):
                continue
            sub_queries = []
            for st in lk.SubTable:
                rst = st.ExtSubTable if lk.LookupType == 9 else st
                fmt = getattr(rst, "Format", None)
                if fmt == 1 and hasattr(rst, "PairSet"):
                    f1_map = {}
                    for g1, ps in zip(rst.Coverage.glyphs, rst.PairSet):
                        d2 = {}
                        for rec in ps.PairValueRecord:
                            v = getattr(rec.Value1, "XAdvance", 0) if rec.Value1 else 0
                            d2[rec.SecondGlyph] = v
                        f1_map[g1] = d2
                    sub_queries.append((1, f1_map))
                elif fmt == 2 and hasattr(rst, "Class1Record"):
                    cov = set(rst.Coverage.glyphs)
                    cd1 = rst.ClassDef1.classDefs
                    cd2 = rst.ClassDef2.classDefs
                    mat = []
                    for c1 in rst.Class1Record:
                        row = []
                        for c2 in c1.Class2Record:
                            v = getattr(c2.Value1, "XAdvance", 0) if c2.Value1 else 0
                            row.append(v)
                        mat.append(row)
                    sub_queries.append((2, cov, cd1, cd2, mat))
            if sub_queries:
                self.lookups.append(sub_queries)

    def get_kern(self, g1, g2):
        total = 0
        for sub_queries in self.lookups:
            for sq in sub_queries:
                if sq[0] == 1:
                    d2 = sq[1].get(g1)
                    if d2 is not None and g2 in d2:
                        total += d2[g2]
                        break
                else:
                    _, cov, cd1, cd2, mat = sq
                    if g1 in cov:
                        c1 = cd1.get(g1, 0)
                        c2 = cd2.get(g2, 0)
                        if c1 < len(mat) and c2 < len(mat[c1]):
                            total += mat[c1][c2]
                        break
        return total


def _ensure_zh_format1_slots(gpos_table, font):
    """
    Ensure the shared Georgian kern lookup Format 1 subtable contains explicit PairValueRecords
    for uni10DF against all 13 ZH_TALL_LEFT_FOLLOWERS so varLib compiles variable `ჟრ` kerning!
    """
    gset = set(font.getGlyphOrder())
    if "uni10DF" not in gset:
        return
    kern_lks = sorted({
        li
        for fr in gpos_table.FeatureList.FeatureRecord
        if fr.FeatureTag == "kern"
        for li in fr.Feature.LookupListIndex
    })
    for li in kern_lks:
        lk = gpos_table.LookupList.Lookup[li]
        if lk.LookupType not in (2, 9):
            continue
        has_geor = False
        fmt1_sub = None
        for st in lk.SubTable:
            rst = st.ExtSubTable if lk.LookupType == 9 else st
            if getattr(rst, "Format", None) == 1 and hasattr(rst, "Coverage"):
                if "uni10DF" in rst.Coverage.glyphs or "uni10E9" in rst.Coverage.glyphs:
                    fmt1_sub = rst
                    has_geor = True
            elif getattr(rst, "Format", None) == 2 and hasattr(rst, "Coverage"):
                if "uni10D0" in rst.Coverage.glyphs:
                    has_geor = True
        if not has_geor:
            continue
        if fmt1_sub is None:
            fmt1_sub = otTables.PairPos()
            fmt1_sub.Format = 1
            fmt1_sub.Coverage = otTables.Coverage()
            fmt1_sub.Coverage.glyphs = []
            fmt1_sub.ValueFormat1 = 4
            fmt1_sub.ValueFormat2 = 0
            fmt1_sub.PairSet = []
            fmt1_sub.PairSetCount = 0
            if lk.LookupType == 9:
                ext = otTables.ExtensionPos()
                ext.Format = 1
                ext.ExtensionLookupType = 2
                ext.ExtSubTable = fmt1_sub
                lk.SubTable.insert(0, ext)
            else:
                lk.SubTable.insert(0, fmt1_sub)
            lk.SubTableCount = len(lk.SubTable)

        cov_pairs = dict(zip(fmt1_sub.Coverage.glyphs, fmt1_sub.PairSet))
        existing_map = {}
        if "uni10DF" in cov_pairs:
            for rec in cov_pairs["uni10DF"].PairValueRecord:
                existing_map[rec.SecondGlyph] = getattr(rec.Value1, "XAdvance", 0) if rec.Value1 else 0
        for g2 in ZH_TALL_LEFT_FOLLOWERS:
            if g2 in gset and g2 not in existing_map:
                existing_map[g2] = 0
        pvr_list = []
        for g2, val in sorted(existing_map.items(), key=lambda kv: font.getGlyphID(kv[0])):
            pvr = otTables.PairValueRecord()
            pvr.SecondGlyph = g2
            v1 = otTables.ValueRecord()
            v1.XAdvance = int(val)
            pvr.Value1 = v1
            pvr.Value2 = None
            pvr_list.append(pvr)
        pset = otTables.PairSet()
        pset.PairValueRecord = pvr_list
        pset.PairValueCount = len(pvr_list)
        cov_pairs["uni10DF"] = pset
        sorted_g1 = sorted(cov_pairs.keys(), key=lambda g: font.getGlyphID(g))
        fmt1_sub.Coverage.glyphs = sorted_g1
        fmt1_sub.PairSet = [cov_pairs[g] for g in sorted_g1]
        fmt1_sub.PairSetCount = len(sorted_g1)
        fmt1_sub.ValueFormat1 = 4
        fmt1_sub.ValueFormat2 = 0
        break


def _normalize_gpos_template(gpos_table):
    """
    Ensure ValueFormat1/2 and ValueRecord fields are uniform across all PairPos cells
    so varLib merges all 16 GPOS masters cleanly without ValueFormat mismatches.
    """
    for lk in gpos_table.LookupList.Lookup:
        if lk.LookupType not in (2, 9):
            continue
        for st in lk.SubTable:
            ltype = st.ExtensionLookupType if lk.LookupType == 9 else lk.LookupType
            if ltype != 2:
                continue
            rst = st.ExtSubTable if lk.LookupType == 9 else st
            if getattr(rst, "Format", None) == 1 and hasattr(rst, "PairSet"):
                if rst.ValueFormat1 & 4:
                    for ps in rst.PairSet:
                        for rec in ps.PairValueRecord:
                            if rec.Value1 is None:
                                rec.Value1 = otTables.ValueRecord()
                            if not hasattr(rec.Value1, "XAdvance") or rec.Value1.XAdvance is None:
                                rec.Value1.XAdvance = 0
            elif getattr(rst, "Format", None) == 2 and hasattr(rst, "Class1Record"):
                if rst.ValueFormat1 & 4:
                    for c1 in rst.Class1Record:
                        for c2 in c1.Class2Record:
                            if c2.Value1 is None:
                                c2.Value1 = otTables.ValueRecord()
                            if not hasattr(c2.Value1, "XAdvance") or c2.Value1.XAdvance is None:
                                c2.Value1.XAdvance = 0


def build_unified_variable_gpos(default_font, orig_otf_fonts):
    """
    Construct 16 structurally identical GPOS tables populated with each master's actual
    kerning values (Format 1 + Format 2) and proportionally scaled/actual mark anchors,
    enabling fontTools.varLib.build to compile a true variable GPOS + GDEF ItemVariationStore!
    """
    base_gpos = copy.deepcopy(default_font["GPOS"])
    _ensure_zh_format1_slots(base_gpos.table, default_font)
    _normalize_gpos_template(base_gpos.table)

    # Pre-index representative glyphs per class for fast Format 2 queries
    template_meta = []
    kern_lk_set = {
        li
        for fr in base_gpos.table.FeatureList.FeatureRecord
        if fr.FeatureTag == "kern"
        for li in fr.Feature.LookupListIndex
    }
    for li, lk in enumerate(base_gpos.table.LookupList.Lookup):
        if li not in kern_lk_set or lk.LookupType not in (2, 9):
            continue
        for si, st in enumerate(lk.SubTable):
            ltype = st.ExtensionLookupType if lk.LookupType == 9 else lk.LookupType
            if ltype != 2:
                continue
            rst = st.ExtSubTable if lk.LookupType == 9 else st
            if getattr(rst, "Format", None) == 2 and hasattr(rst, "Class1Record"):
                cov_set = set(rst.Coverage.glyphs)
                c1_reps = {}
                for g in rst.Coverage.glyphs:
                    c1 = rst.ClassDef1.classDefs.get(g, 0)
                    lst = c1_reps.setdefault(c1, [])
                    if len(lst) < 3:
                        lst.append(g)
                c2_reps = {}
                for g, c2 in rst.ClassDef2.classDefs.items():
                    lst = c2_reps.setdefault(c2, [])
                    if len(lst) < 3:
                        lst.append(g)
                template_meta.append((li, si, c1_reps, c2_reps))

    # Pre-compute queriers, actual Georgian MarkBase anchors & contextual double-mark/karagma lifts for all 16 static OTFs
    queriers = [FastKernQuerier(f) for f in orig_otf_fonts]
    ref_hmtx = default_font["hmtx"]
    master_geor_mb = []
    master_dbl_sp = []
    master_kar_sp = []
    master_karx_sp = []

    def _unique_chain_helper_idxs(gpos_tbl, chain_idx):
        if chain_idx is None:
            return []
        seen = []
        for st in gpos_tbl.LookupList.Lookup[chain_idx].SubTable:
            if getattr(st, "PosLookupRecord", None):
                hi = st.PosLookupRecord[0].LookupListIndex
                if hi not in seen:
                    seen.append(hi)
        return seen

    def _extract_helper_xy(gpos_tbl, helper_idxs):
        vals = []
        for hi in helper_idxs:
            hlk = gpos_tbl.LookupList.Lookup[hi]
            if hlk.LookupType == 1 and hlk.SubTable and getattr(hlk.SubTable[0], "Value", None):
                v = hlk.SubTable[0].Value
                vals.append((int(getattr(v, "XPlacement", 0) or 0), int(getattr(v, "YPlacement", 0) or 0)))
        return vals

    base_dbl_chain_idx = find_double_mark_chain_lookup(base_gpos.table)
    base_dbl_helper_idxs = _unique_chain_helper_idxs(base_gpos.table, base_dbl_chain_idx)
    base_kar_chain_idx = find_karagma_chain_lookup(base_gpos.table)
    base_kar_helper_idxs = _unique_chain_helper_idxs(base_gpos.table, base_kar_chain_idx)
    base_karx_chain_idx = find_karagma_xshift_chain_lookup(base_gpos.table)
    base_karx_helper_idxs = _unique_chain_helper_idxs(base_gpos.table, base_karx_chain_idx)

    for f in orig_otf_fonts:
        mb = {}
        sp_vals = []
        kar_vals = []
        karx_vals = []
        if "GPOS" in f:
            fgpos = f["GPOS"].table
            for lk in fgpos.LookupList.Lookup:
                for st in lk.SubTable:
                    ltype = st.ExtensionLookupType if lk.LookupType == 9 else lk.LookupType
                    rst = st.ExtSubTable if lk.LookupType == 9 else st
                    if ltype == 4 and hasattr(rst, "BaseCoverage") and getattr(rst, "BaseArray", None):
                        for g, brec in zip(rst.BaseCoverage.glyphs, rst.BaseArray.BaseRecord):
                            if is_georgian_spacing_target(g) or g in KHUTSURI_GLYPH_SET:
                                mb[g] = [
                                    (int(a.XCoordinate), int(a.YCoordinate)) if a is not None else None
                                    for a in brec.BaseAnchor
                                ]
            sp_vals = _extract_helper_xy(fgpos, _unique_chain_helper_idxs(fgpos, find_double_mark_chain_lookup(fgpos)))
            kar_vals = _extract_helper_xy(fgpos, _unique_chain_helper_idxs(fgpos, find_karagma_chain_lookup(fgpos)))
            karx_vals = _extract_helper_xy(fgpos, _unique_chain_helper_idxs(fgpos, find_karagma_xshift_chain_lookup(fgpos)))
        master_geor_mb.append(mb)
        master_dbl_sp.append(sp_vals)
        master_kar_sp.append(kar_vals)
        master_karx_sp.append(karx_vals)

    out_gpos_16 = []
    for m in range(16):
        if m == DEFAULT_MASTER_IDX:
            out_gpos_16.append(copy.deepcopy(base_gpos))
            continue

        mgpos = copy.deepcopy(base_gpos)
        q = queriers[m]
        m_hmtx = orig_otf_fonts[m]["hmtx"]

        # 1. Populate Format 1 PairPos kerns from master m
        for li in kern_lk_set:
            lk = mgpos.table.LookupList.Lookup[li]
            if lk.LookupType not in (2, 9):
                continue
            for st in lk.SubTable:
                ltype = st.ExtensionLookupType if lk.LookupType == 9 else lk.LookupType
                if ltype != 2:
                    continue
                rst = st.ExtSubTable if lk.LookupType == 9 else st
                if getattr(rst, "Format", None) == 1 and hasattr(rst, "PairSet") and (rst.ValueFormat1 & 4):
                    for g1, ps in zip(rst.Coverage.glyphs, rst.PairSet):
                        for rec in ps.PairValueRecord:
                            kv = q.get_kern(g1, rec.SecondGlyph)
                            rec.Value1.XAdvance = int(kv)

        # 2. Populate Format 2 PairPos kerns from master m (using class representatives)
        for li, si, c1_reps, c2_reps in template_meta:
            lk = mgpos.table.LookupList.Lookup[li]
            st = lk.SubTable[si]
            rst = st.ExtSubTable if lk.LookupType == 9 else st
            if not (rst.ValueFormat1 & 4):
                continue
            for c1_idx, c1_rec in enumerate(rst.Class1Record):
                g1s = c1_reps.get(c1_idx)
                if not g1s:
                    continue
                for c2_idx, c2_rec in enumerate(c1_rec.Class2Record):
                    g2s = c2_reps.get(c2_idx)
                    if not g2s:
                        continue
                    def_val = getattr(c2_rec.Value1, "XAdvance", 0) or 0
                    # Fast probe first representative pair; only average multiple if non-zero or differs
                    v0 = q.get_kern(g1s[0], g2s[0])
                    if v0 == 0 and def_val == 0:
                        continue
                    samples = [v0]
                    if len(g1s) > 1 or len(g2s) > 1:
                        for g1 in g1s:
                            for g2 in g2s:
                                if g1 == g1s[0] and g2 == g2s[0]:
                                    continue
                                samples.append(q.get_kern(g1, g2))
                        samples.sort()
                        val = samples[len(samples) // 2]
                    else:
                        val = v0
                    c2_rec.Value1.XAdvance = int(val)

        # 3. Sync exact Georgian MarkBase anchors from static masters + scale remaining anchors by advance ratio
        m_mb = master_geor_mb[m]
        for lk in mgpos.table.LookupList.Lookup:
            for st in lk.SubTable:
                ltype = st.ExtensionLookupType if lk.LookupType == 9 else lk.LookupType
                rst = st.ExtSubTable if lk.LookupType == 9 else st
                if ltype == 4 and hasattr(rst, "BaseCoverage") and hasattr(rst, "BaseArray"):
                    for g, rec in zip(rst.BaseCoverage.glyphs, rst.BaseArray.BaseRecord):
                        if (is_georgian_spacing_target(g) or g in KHUTSURI_GLYPH_SET) and g in m_mb and len(m_mb[g]) == len(rec.BaseAnchor):
                            for anc, m_xy in zip(rec.BaseAnchor, m_mb[g]):
                                if anc is not None and m_xy is not None and not (anc.XCoordinate == 0 and anc.YCoordinate == 0):
                                    anc.XCoordinate = m_xy[0]
                                    anc.YCoordinate = m_xy[1]
                            continue
                        r0 = ref_hmtx[g][0] if g in ref_hmtx.metrics else 0
                        r1 = m_hmtx[g][0] if g in m_hmtx.metrics else 0
                        if r0 > 0 and r1 > 0 and r0 != r1:
                            ratio = r1 / float(r0)
                            for anc in rec.BaseAnchor:
                                if anc is not None:
                                    anc.XCoordinate = int(round(anc.XCoordinate * ratio))
                    for g, mrec in zip(rst.MarkCoverage.glyphs, rst.MarkArray.MarkRecord):
                        r0 = ref_hmtx[g][0] if g in ref_hmtx.metrics else 0
                        r1 = m_hmtx[g][0] if g in m_hmtx.metrics else 0
                        if r0 > 0 and r1 > 0 and r0 != r1 and mrec.MarkAnchor is not None:
                            mrec.MarkAnchor.XCoordinate = int(round(mrec.MarkAnchor.XCoordinate * (r1 / float(r0))))
                elif ltype == 6 and hasattr(rst, "Mark2Coverage") and hasattr(rst, "Mark2Array"):
                    for g, rec in zip(rst.Mark2Coverage.glyphs, rst.Mark2Array.Mark2Record):
                        r0 = ref_hmtx[g][0] if g in ref_hmtx.metrics else 0
                        r1 = m_hmtx[g][0] if g in m_hmtx.metrics else 0
                        if r0 > 0 and r1 > 0 and r0 != r1:
                            ratio = r1 / float(r0)
                            for anc in rec.Mark2Anchor:
                                if anc is not None:
                                    anc.XCoordinate = int(round(anc.XCoordinate * ratio))

        # 4. Sync exact contextual double-mark & karagma SinglePos lifts/shifts from static master m
        for h_idxs, m_vals in (
            (base_dbl_helper_idxs, master_dbl_sp[m]),
            (base_kar_helper_idxs, master_kar_sp[m]),
            (base_karx_helper_idxs, master_karx_sp[m]),
        ):
            if h_idxs and len(m_vals) == len(h_idxs):
                for hi, (dx, dy) in zip(h_idxs, m_vals):
                    hlk = mgpos.table.LookupList.Lookup[hi]
                    if hlk.LookupType == 1 and hlk.SubTable and getattr(hlk.SubTable[0], "Value", None):
                        hlk.SubTable[0].Value.XPlacement = int(dx)
                        hlk.SubTable[0].Value.YPlacement = int(dy)

        out_gpos_16.append(mgpos)

    return out_gpos_16


def shear_gpos_anchors(gpos_table_obj, delta_tan, pivot_y=ITAL_PIVOT_Y):
    """
    Shear MarkBasePos (4), MarkLigPos (5), MarkMarkPos (6) anchor X coordinates
    by (Y - pivot_y) * delta_tan AND SinglePos (1) contextual double-mark vertical lifts
    by YPlacement * delta_tan so combining diacritics track the continuous `slnt`
    axis with mathematical perfection, while keeping PairPos kerning invariant!
    """
    if abs(delta_tan) < 1e-9:
        return gpos_table_obj
    out = copy.deepcopy(gpos_table_obj)

    def _shear_anc(anc):
        if anc is not None and hasattr(anc, "XCoordinate") and hasattr(anc, "YCoordinate"):
            anc.XCoordinate = int(round(anc.XCoordinate + (anc.YCoordinate - pivot_y) * delta_tan))

    for lk in out.table.LookupList.Lookup:
        for st in lk.SubTable:
            ltype = st.ExtensionLookupType if lk.LookupType == 9 else lk.LookupType
            rst = st.ExtSubTable if lk.LookupType == 9 else st
            if ltype == 1 and getattr(rst, "Format", None) == 1 and getattr(rst, "Value", None) is not None:
                dy = getattr(rst.Value, "YPlacement", 0) or 0
                if dy != 0 and (rst.ValueFormat & 1):
                    cur_dx = getattr(rst.Value, "XPlacement", 0) or 0
                    rst.Value.XPlacement = int(round(cur_dx + dy * delta_tan))
            elif ltype == 4:
                if hasattr(rst, "BaseArray") and rst.BaseArray:
                    for rec in rst.BaseArray.BaseRecord:
                        for anc in rec.BaseAnchor:
                            _shear_anc(anc)
                if hasattr(rst, "MarkArray") and rst.MarkArray:
                    for mrec in rst.MarkArray.MarkRecord:
                        _shear_anc(mrec.MarkAnchor)
            elif ltype == 5:
                if hasattr(rst, "LigatureArray") and rst.LigatureArray:
                    for la in rst.LigatureArray.LigatureAttach:
                        for comp in la.ComponentRecord:
                            for anc in comp.LigatureAnchor:
                                _shear_anc(anc)
                if hasattr(rst, "MarkArray") and rst.MarkArray:
                    for mrec in rst.MarkArray.MarkRecord:
                        _shear_anc(mrec.MarkAnchor)
            elif ltype == 6:
                if hasattr(rst, "Mark1Array") and rst.Mark1Array:
                    for mrec in rst.Mark1Array.MarkRecord:
                        _shear_anc(mrec.MarkAnchor)
                if hasattr(rst, "Mark2Array") and rst.Mark2Array:
                    for rec in rst.Mark2Array.Mark2Record:
                        for anc in rec.Mark2Anchor:
                            _shear_anc(anc)
    return out


# ---------------------------------------------------------------------------
# Empirical `avar` Weight Curve Measurement
# ---------------------------------------------------------------------------

def measure_I_stem_width(font, y_probe=340.0):
    """
    Orientation-independent (OTF CCW or TTF CW, Upright or Italic, Sharp or Rounded)
    horizontal stem width measurement via exact horizontal slice of glyph 'I' at y=340.
    """
    cs = extract_contours(font, "I")
    xs = []
    for c in cs:
        for seg in c:
            prev = eval_seg(seg, 0.0)
            steps = 2 if seg[0] == "line" else 24
            for k in range(1, steps + 1):
                cur = eval_seg(seg, k / float(steps))
                if (prev[1] <= y_probe < cur[1]) or (cur[1] <= y_probe < prev[1]):
                    t = (y_probe - prev[1]) / (cur[1] - prev[1])
                    xs.append(prev[0] + t * (cur[0] - prev[0]))
                prev = cur
    if len(xs) >= 2:
        xs.sort()
        return xs[-1] - xs[0]
    bp = BoundsPen(font.getGlyphSet())
    font.getGlyphSet()["I"].draw(bp)
    return (bp.bounds[2] - bp.bounds[0]) if bp.bounds else 0.0


def measure_wght_avar_map(otf_dir, rounded, is_italic):
    """
    Empirically measure stem widths across all 9 static Normal weights (100..900)
    via orientation- and cap-rounding-independent `I` horizontal slice, and compute
    the exact piecewise-linear `avar` user->design mapping over masters {100, 400, 700, 900}!
    """
    wlist = ALL_9_WEIGHTS_IT if is_italic else ALL_9_WEIGHTS_UP
    pref = master_prefix("", rounded)
    stems = {}
    for wval, wsuf, _ in wlist:
        p = os.path.join(otf_dir, f"{pref}-{wsuf}.otf")
        f = TTFont(p)
        stems[wval] = measure_I_stem_width(f)
        f.close()

    avar_map = []
    anchors = [(100, 400), (400, 700), (700, 900)]
    for wval, _, _ in wlist:
        if wval in (100, 400, 700, 900):
            avar_map.append((float(wval), float(wval)))
        else:
            for a, b in anchors:
                if a < wval < b:
                    t = (stems[wval] - stems[a]) / max(stems[b] - stems[a], 1e-6)
                    t = max(0.05, min(0.95, t))
                    design_val = round(a + t * (b - a), 2)
                    avar_map.append((float(wval), design_val))
                    break
    return avar_map, stems


def compute_slnt_avar_map(is_italic):
    """
    Exact tangent-linearized `avar` mapping for `slnt` (-12..0) so every intermediate
    degree (especially -8 deg on Upright, -4 deg, -10 deg, 0 deg) hits its exact geometric
    angle within < 0.002 deg despite linear interpolation of tan(theta) between endpoints.
    """
    t12 = math.tan(math.radians(12.0))
    t8 = math.tan(math.radians(8.0))
    if not is_italic:
        # Masters at slnt = -12.0 and slnt = 0.0 (default = 0.0)
        stops = [-12.0, -10.0, -8.0, -6.0, -4.0, -2.0, 0.0]
        out = []
        for s in stops:
            if s in (-12.0, 0.0):
                out.append((s, s))
            else:
                frac = math.tan(math.radians(-s)) / t12
                out.append((s, round(-12.0 * frac, 4)))
        return out
    else:
        # Masters at slnt = -12.0, -8.0 (default), 0.0
        out = []
        for s in (-12.0, -10.0, -8.0):
            if s in (-12.0, -8.0):
                out.append((s, s))
            else:
                frac = (math.tan(math.radians(-s)) - t8) / (t12 - t8)
                out.append((s, round(-8.0 - 4.0 * frac, 4)))
        for s in (-6.0, -4.0, -2.0, 0.0):
            if s == 0.0:
                out.append((0.0, 0.0))
            else:
                frac = (t8 - math.tan(math.radians(-s))) / t8
                out.append((s, round(-8.0 + 8.0 * frac, 4)))
        return out


# ---------------------------------------------------------------------------
# Metadata, STAT Table, DesignSpace & Variable Font Compilation
# ---------------------------------------------------------------------------

def configure_vf_metadata_and_stat(
    vf,
    spec,
    google_fonts=False,
    win_ascent=DEFAULT_WIN_ASCENT,
    win_descent=DEFAULT_WIN_DESCENT,
):
    """
    Set complete Batumi Sans v1.100 Borbalo (KJ Group) metadata, flags, gasp, meta,
    OVERLAP_SIMPLE, zero Mac name entries, omitted redundant nameID 16/17, and either:
      - Google Fonts Axis Registry 3-axis STAT (`wdth`, `wght`, `ital`) when `google_fonts=True`
      - Borbalo Creative 4-axis STAT (`wdth`, `wght`, `slnt`, `ital`) when `google_fonts=False`
    """
    fam = spec["family_name"]
    sub = spec["subfamily_name"]
    is_it = spec["is_italic"]
    ps_name = spec["ps_name"]
    var_ps_prefix = spec["var_ps_prefix"]

    # Build OpenType STAT table BEFORE apply_v1100_metadata so its Windows nameID >= 256 records are preserved!
    if google_fonts:
        # Strict Google Fonts Axis Registry STAT: wdth (0) -> wght (1) -> ital (2)
        stat_axes = [
            dict(
                tag="wdth",
                name="Width",
                ordering=0,
                values=[
                    dict(value=75.0,  name="Condensed"),
                    dict(value=87.5,  name="SemiCondensed"),
                    dict(value=100.0, name="Normal", flags=0x0002),
                    dict(value=112.5, name="SemiExpanded"),
                ],
            ),
            dict(
                tag="wght",
                name="Weight",
                ordering=1,
                values=[
                    dict(value=100.0, name="Thin"),
                    dict(value=200.0, name="ExtraLight"),
                    dict(value=300.0, name="Light"),
                    dict(value=400.0, linkedValue=700.0, name="Regular", flags=0x0002),
                    dict(value=500.0, name="Medium"),
                    dict(value=600.0, name="SemiBold"),
                    dict(value=700.0, name="Bold"),
                    dict(value=800.0, name="ExtraBold"),
                    dict(value=900.0, name="Black"),
                ],
            ),
            dict(
                tag="ital",
                name="Italic",
                ordering=2,
                values=(
                    [dict(value=1.0, name="Italic", flags=0x0000)]
                    if is_it
                    else [dict(value=0.0, linkedValue=1.0, name="Roman", flags=0x0002)]
                ),
            ),
        ]
    else:
        # Full 4-axis Borbalo Creative STAT (wdth, wght, slnt, ital)
        slnt_stat_values = (
            [
                dict(nominalValue=-12.0, rangeMinValue=-12.0, rangeMaxValue=-10.0, name="Steep Italic"),
                dict(nominalValue=-8.0,  rangeMinValue=-10.0, rangeMaxValue=-4.0,  name="Italic", flags=0x0002),
                dict(nominalValue=0.0,   rangeMinValue=-4.0,  rangeMaxValue=0.0,   name="Upright Cursive"),
            ]
            if is_it
            else [
                dict(nominalValue=-12.0, rangeMinValue=-12.0, rangeMaxValue=-10.0, name="Steep Oblique"),
                dict(nominalValue=-8.0,  rangeMinValue=-10.0, rangeMaxValue=-4.0,  name="Oblique"),
                dict(nominalValue=0.0,   rangeMinValue=-4.0,  rangeMaxValue=0.0,   name="Upright", flags=0x0002),
            ]
        )
        stat_axes = [
            dict(
                tag="wdth",
                name="Width",
                ordering=0,
                values=[
                    dict(nominalValue=75.0,  rangeMinValue=75.0,  rangeMaxValue=81.25, name="Extra Condensed"),
                    dict(nominalValue=87.5,  rangeMinValue=81.25, rangeMaxValue=93.75, name="Condensed"),
                    dict(nominalValue=100.0, rangeMinValue=93.75, rangeMaxValue=107.5, name="Normal", flags=0x0002),
                    dict(nominalValue=115.0, rangeMinValue=107.5, rangeMaxValue=115.0, name="Expanded"),
                ],
            ),
            dict(
                tag="wght",
                name="Weight",
                ordering=1,
                values=[
                    dict(nominalValue=100.0, rangeMinValue=100.0, rangeMaxValue=150.0, name="Thin"),
                    dict(nominalValue=200.0, rangeMinValue=150.0, rangeMaxValue=250.0, name="ExtraLight"),
                    dict(nominalValue=300.0, rangeMinValue=250.0, rangeMaxValue=350.0, name="Light"),
                    dict(value=400.0, linkedValue=700.0, name="Regular", flags=0x0002),
                    dict(nominalValue=500.0, rangeMinValue=450.0, rangeMaxValue=550.0, name="Medium"),
                    dict(nominalValue=600.0, rangeMinValue=550.0, rangeMaxValue=650.0, name="SemiBold"),
                    dict(nominalValue=700.0, rangeMinValue=650.0, rangeMaxValue=750.0, name="Bold"),
                    dict(nominalValue=800.0, rangeMinValue=750.0, rangeMaxValue=850.0, name="ExtraBold"),
                    dict(nominalValue=900.0, rangeMinValue=850.0, rangeMaxValue=900.0, name="Heavy"),
                ],
            ),
            dict(
                tag="slnt",
                name="Slant",
                ordering=2,
                values=slnt_stat_values,
            ),
            dict(
                tag="ital",
                name="Italic",
                ordering=3,
                values=(
                    [dict(value=1.0, name="Italic", flags=0x0000)]
                    if is_it
                    else [dict(value=0.0, linkedValue=1.0, name="Roman", flags=0x0002)]
                ),
            ),
        ]

    buildStatTable(
        vf,
        stat_axes,
        elidedFallbackName="Italic" if is_it else "Regular",
        windowsNames=True,
        macNames=False,
    )

    # Apply canonical v1.100 Borbalo/KJ Group metadata, ISS-003 usWin*, USE_TYPO_METRICS + WWS, meta, no DSIG
    apply_v1100_metadata(
        font=vf,
        family_name=fam,
        ps_name=ps_name,
        style_display=sub,
        weight_display="Regular",
        weight_class=400,
        width_class=5,
        is_bold=False,
        is_italic=is_it,
        is_vf=True,
        var_ps_prefix=var_ps_prefix,
        win_ascent=win_ascent,
        win_descent=win_descent,
        maplibre_metrics=False,
    )
    vf["post"].italicAngle = -8.0 if is_it else 0.0
    add_gasp_table(vf)
    apply_overlap_simple_flags(vf)


def build_single_vf(
    vf_key,
    otf_dir,
    out_dir,
    workers=6,
    max_err=0.75,
    build_creative=True,
    build_google_fonts=False,
    gf_repo_dir=None,
    gf_dist_dir=None,
    win_ascent=DEFAULT_WIN_ASCENT,
    win_descent=DEFAULT_WIN_DESCENT,
):
    spec = VF_SPECS[vf_key]
    is_it = spec["is_italic"]
    rounded = spec["rounded"]
    t0 = time.time()

    editions_lbl = "+".join(
        ([("3-axis Creative")] if build_creative else [])
        + ([("2-axis Google Fonts")] if build_google_fonts else [])
    )
    print(f"\n======================================================================")
    print(f"Building VF [{vf_key}] ({editions_lbl}): {spec['family_name']} {spec['subfamily_name']}")
    print(f"======================================================================")

    # 1. Measure empirical avar curve from all 9 static Normal weights
    avar_map, stems_9 = measure_wght_avar_map(otf_dir, rounded, is_it)
    print(f"  Empirical avar wght map: {[(int(u), d) for u, d in avar_map]}")

    # 2. Load 16 static OTF masters (4 widths x 4 weights)
    w_masters = WEIGHT_MASTERS_IT if is_it else WEIGHT_MASTERS_UP
    orig_fonts = []
    master_coords_meta = []
    max_master_ymax = -99999
    min_master_ymin = 99999
    for wd_val, wd_tok, wd_lbl, _ in WIDTH_MASTERS:
        for wt_val, wt_suf, wt_lbl in w_masters:
            path = master_otf_path(otf_dir, wd_tok, wt_suf, rounded)
            if not os.path.exists(path):
                raise FileNotFoundError(f"Missing static master OTF: {path}")
            ft = TTFont(path)
            max_master_ymax = max(max_master_ymax, int(ft["head"].yMax))
            min_master_ymin = min(min_master_ymin, int(ft["head"].yMin))
            orig_fonts.append(ft)
            master_coords_meta.append((wd_val, wd_tok, wd_lbl, wt_val, wt_suf, wt_lbl, path))

    eff_win_asc = max(int(win_ascent), ceil10(max_master_ymax))
    eff_win_desc = max(int(win_descent), ceil10(abs(min_master_ymin)))
    default_otf = orig_fonts[DEFAULT_MASTER_IDX]
    glyph_order = default_otf.getGlyphOrder()
    n_glyphs = len(glyph_order)
    print(f"  Loaded 16 masters ({n_glyphs} glyphs each, y=[{min_master_ymin}..{max_master_ymax}], usWin={eff_win_asc}/{eff_win_desc}). Extracting cubic contours...")

    # 3. Extract cubic contours & advance widths for all glyphs across 16 masters
    tasks = []
    for gname in glyph_order:
        raw_16 = [extract_contours(f, gname) for f in orig_fonts]
        advs_16 = [f["hmtx"][gname][0] for f in orig_fonts]
        tasks.append((gname, raw_16, advs_16, is_it, max_err))

    # 4. Run parallel point-compatibility + joint cu2qu conversion (shared by BOTH editions!)
    t_align = time.time()
    tt_glyph_map = {}
    reconcile_stats = {}
    if workers <= 1:
        for t in tasks:
            gn, payloads, rmode = build_compatible_tt_glyphs_for_name(t)
            tt_glyph_map[gn] = payloads
            reconcile_stats[rmode] = reconcile_stats.get(rmode, 0) + 1
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for gn, payloads, rmode in pool.map(build_compatible_tt_glyphs_for_name, tasks, chunksize=64):
                tt_glyph_map[gn] = payloads
                reconcile_stats[rmode] = reconcile_stats.get(rmode, 0) + 1
    print(f"  Aligned + joint cu2qu complete in {time.time() - t_align:.1f}s | reconcile stats: {reconcile_stats}")

    # 5. Build unified variable GPOS tables across all 16 masters
    t_gpos = time.time()
    unified_gpos_16 = build_unified_variable_gpos(default_otf, orig_fonts)
    shared_gsub = copy.deepcopy(default_otf["GSUB"])
    shared_gdef = copy.deepcopy(default_otf["GDEF"])
    shared_cmap = copy.deepcopy(default_otf["cmap"])
    print(f"  Unified variable GPOS + shared GSUB/GDEF/cmap built in {time.time() - t_gpos:.1f}s")

    slnt_default = SLNT_DEFAULT_IT if is_it else SLNT_DEFAULT_UP
    slnt_planes = [-8.0, 0.0, -12.0] if is_it else [0.0, -12.0]
    slnt_avar_map = compute_slnt_avar_map(is_it)

    result = {
        "vf_key": vf_key,
        "out_stem": spec["out_stem"],
        "gf_stem": spec["gf_stem"],
        "family_name": spec["family_name"],
        "subfamily_name": spec["subfamily_name"],
        "num_glyphs": n_glyphs,
        "usWinAscent": eff_win_asc,
        "usWinDescent": eff_win_desc,
        "avar_wght_map": avar_map,
        "avar_slnt_map": slnt_avar_map,
        "reconcile_stats": reconcile_stats,
    }

    slnt_geor_set = set(get_georgian_slnt_target_glyphs(glyph_order, default_otf.getBestCmap()))

    def _write_master_ttf(m, slnt_val, delta_tan, is_def_plane, m_path):
        wd_val, wd_tok, wd_lbl, wt_val, wt_suf, wt_lbl, orig_path = master_coords_meta[m]
        ttf = TTFont(orig_path)
        glyf = newTable("glyf")
        glyf.glyphs = {}
        glyf.glyphOrder = list(glyph_order)
        hmtx = ttf["hmtx"]
        slnt_add = 0 if is_def_plane else compute_slnt_breathing(wt_val, slnt_val, is_it)

        for gname in glyph_order:
            pl = tt_glyph_map[gname][m]
            adv = hmtx[gname][0]
            if not is_def_plane:
                pl = shear_tt_payload(pl, delta_tan)
                if slnt_add > 0 and gname in slnt_geor_set:
                    pl = translate_tt_payload(pl, slnt_add, 0)
                    adv += 2 * slnt_add
            gobj = payload_to_tt_glyph(pl)
            glyf.glyphs[gname] = gobj
            lsb = gobj.xMin if gobj.numberOfContours > 0 else 0
            hmtx[gname] = (adv, lsb)

        if "CFF " in ttf:
            del ttf["CFF "]
        if "VORG" in ttf:
            del ttf["VORG"]
        ttf.sfntVersion = "\x00\x01\x00\x00"
        ttf["glyf"] = glyf
        ttf["loca"] = newTable("loca")

        maxp = newTable("maxp")
        maxp.tableVersion = 0x00010000
        maxp.numGlyphs = n_glyphs
        maxp.maxPoints = maxp.maxContours = maxp.maxCompositePoints = maxp.maxCompositeContours = 0
        maxp.maxZones = 2
        maxp.maxTwilightPoints = maxp.maxStorage = maxp.maxFunctionDefs = maxp.maxInstructionDefs = 0
        maxp.maxStackElements = maxp.maxSizeOfInstructions = maxp.maxComponentElements = maxp.maxComponentDepth = 0
        ttf["maxp"] = maxp

        post = ttf["post"]
        post.formatType = 2.0
        post.extraNames = []
        post.mapping = {}

        if is_def_plane:
            ttf["GPOS"] = unified_gpos_16[m]
        else:
            sheared_gpos = shear_gpos_anchors(unified_gpos_16[m], delta_tan)
            if slnt_add > 0:
                shift_gpos_mark_anchors_x(sheared_gpos, {g: slnt_add for g in slnt_geor_set})
            ttf["GPOS"] = sheared_gpos
        ttf["GSUB"] = copy.deepcopy(shared_gsub)
        ttf["GDEF"] = copy.deepcopy(shared_gdef)
        ttf["cmap"] = copy.deepcopy(shared_cmap)
        ttf.setGlyphOrder(glyph_order)
        ttf.save(m_path)
        ttf.close()

    with tempfile.TemporaryDirectory(prefix=f"batumi_vf_{vf_key}_") as tmpdir:
        # Write the 16 default-plane master TTFs ONCE (reused directly by BOTH Creative & GF VFs!)
        def_master_paths = []
        for m in range(16):
            wd_val, wd_tok, wd_lbl, wt_val, wt_suf, wt_lbl, _ = master_coords_meta[m]
            mp = os.path.join(tmpdir, f"m_def_{m:02d}_{wd_tok or 'Normal'}_{wt_suf}.ttf")
            _write_master_ttf(m, slnt_default, 0.0, True, mp)
            def_master_paths.append(mp)

        # --- Edition A: 2-Axis Google Fonts [wdth, wght] Variable Font (16 masters, NO slnt!) ---
        if build_google_fonts:
            t_gf = time.time()
            ds_gf = DesignSpaceDocument()

            ax_wdth = AxisDescriptor()
            ax_wdth.tag = "wdth"; ax_wdth.name = "Width"
            ax_wdth.minimum = 75.0; ax_wdth.default = 100.0; ax_wdth.maximum = 115.0
            ax_wdth.map = [(75.0, 75.0), (87.5, 87.5), (100.0, 100.0), (115.0, 115.0)]
            ds_gf.addAxis(ax_wdth)

            ax_wght = AxisDescriptor()
            ax_wght.tag = "wght"; ax_wght.name = "Weight"
            ax_wght.minimum = 100.0; ax_wght.default = 400.0; ax_wght.maximum = 900.0
            ax_wght.map = avar_map
            ds_gf.addAxis(ax_wght)

            for m in range(16):
                wd_val, wd_tok, wd_lbl, wt_val, wt_suf, wt_lbl, _ = master_coords_meta[m]
                src = SourceDescriptor()
                src.path = def_master_paths[m]
                src.familyName = spec["family_name"]
                src.styleName = f"{wd_lbl} {wt_lbl}".strip()
                src.location = {"Width": float(wd_val), "Weight": float(wt_val)}
                if m == DEFAULT_MASTER_IDX:
                    src.copyLib = src.copyInfo = src.copyGroups = src.copyFeatures = True
                ds_gf.addSource(src)

            # Strictly 9 weight-only integer instances at wdth=100 ending in Black / Black Italic!
            gf_w9 = GF_9_WEIGHTS_IT if is_it else GF_9_WEIGHTS_UP
            for wt_val, ps_suf, style_name in gf_w9:
                inst = InstanceDescriptor()
                inst.familyName = spec["family_name"]
                inst.styleName = style_name
                inst.postScriptFontName = f"{master_prefix('', rounded)}-{ps_suf}"
                # Map forward through avar so fvar stores EXACT integer user coords (100..900)!
                inst.location = ds_gf.map_forward({"Width": 100.0, "Weight": float(wt_val)})
                ds_gf.addInstance(inst)

            vf_gf, _, _ = varLib.build(ds_gf, optimize=True, drop_implied_oncurves=True)

            # Drop unused smcp/c2sc ONLY in 2-axis Google Fonts edition (clears missing_small_caps_glyphs!)
            smcp_dropped = strip_smcp_c2sc_features(vf_gf)

            # Prune rounding-noise cross-term (wdth, wght) gvar tuples (max <= 1u)
            gf_gvar_stats = optimize_gvar_tuples(vf_gf, is_3axis=False, noise_thresh=1, max_corner_err=1.5)

            # Strict Google Fonts v1.100 metadata + Axis Registry STAT + gasp + meta + OVERLAP_SIMPLE
            configure_vf_metadata_and_stat(
                vf_gf, spec, google_fonts=True, win_ascent=eff_win_asc, win_descent=eff_win_desc
            )

            gf_dist_dir_eff = gf_dist_dir or os.path.join(BASE_DIR, "dist", "google-fonts")
            gf_repo_dir_eff = gf_repo_dir or os.path.join(BASE_DIR, "google-fonts")
            os.makedirs(gf_dist_dir_eff, exist_ok=True)
            gf_fam_dir = os.path.join(gf_repo_dir_eff, spec["gf_dir"])
            os.makedirs(gf_fam_dir, exist_ok=True)

            gf_ttf_repo = os.path.join(gf_fam_dir, f"{spec['gf_stem']}.ttf")
            gf_ttf_dist = os.path.join(gf_dist_dir_eff, f"{spec['gf_stem']}.ttf")
            gf_woff2_dist = os.path.join(gf_dist_dir_eff, f"{spec['gf_stem']}.woff2")

            vf_gf.save(gf_ttf_repo)
            import shutil
            shutil.copy2(gf_ttf_repo, gf_ttf_dist)
            vf_gf.flavor = "woff2"
            vf_gf.save(gf_woff2_dist)
            vf_gf.close()

            gf_ttf_kb = os.path.getsize(gf_ttf_repo) / 1024.0
            gf_woff2_kb = os.path.getsize(gf_woff2_dist) / 1024.0
            print(
                f"  [GF 2-Axis] Exported {spec['gf_stem']}.ttf ({gf_ttf_kb/1024:.2f} MB) & "
                f".woff2 ({gf_woff2_kb/1024:.2f} MB) in {time.time() - t_gf:.1f}s | "
                f"smcp_dropped={smcp_dropped} | gvar={gf_gvar_stats}"
            )
            result.update({
                "gf_ttf_path": gf_ttf_repo,
                "gf_dist_ttf_path": gf_ttf_dist,
                "gf_woff2_path": gf_woff2_dist,
                "gf_ttf_bytes": os.path.getsize(gf_ttf_repo),
                "gf_woff2_bytes": os.path.getsize(gf_woff2_dist),
                "gf_gvar_stats": gf_gvar_stats,
            })

        # --- Edition B: 3-Axis Creative Variable Font (wdth x wght x slnt, 32/48 masters, smart gvar!) ---
        if build_creative:
            t_cr = time.time()
            num_total_masters = 16 * len(slnt_planes)
            print(f"  Building 3-axis Creative DesignSpace ({num_total_masters} masters across slnt planes {slnt_planes})...")
            ds = DesignSpaceDocument()

            ax_wdth = AxisDescriptor()
            ax_wdth.tag = "wdth"; ax_wdth.name = "Width"
            ax_wdth.minimum = 75.0; ax_wdth.default = 100.0; ax_wdth.maximum = 115.0
            ax_wdth.map = [(75.0, 75.0), (87.5, 87.5), (100.0, 100.0), (115.0, 115.0)]
            ds.addAxis(ax_wdth)

            ax_wght = AxisDescriptor()
            ax_wght.tag = "wght"; ax_wght.name = "Weight"
            ax_wght.minimum = 100.0; ax_wght.default = 400.0; ax_wght.maximum = 900.0
            ax_wght.map = avar_map
            ds.addAxis(ax_wght)

            ax_slnt = AxisDescriptor()
            ax_slnt.tag = "slnt"; ax_slnt.name = "Slant"
            ax_slnt.minimum = SLNT_MIN; ax_slnt.default = slnt_default; ax_slnt.maximum = SLNT_MAX
            ax_slnt.map = slnt_avar_map
            ds.addAxis(ax_slnt)

            for sp_idx, slnt_val in enumerate(slnt_planes):
                delta_tan = math.tan(math.radians(-slnt_val)) - math.tan(math.radians(-slnt_default))
                is_def_plane = abs(slnt_val - slnt_default) < 1e-6
                slnt_tag = f"s{int(round(slnt_val))}"

                for m in range(16):
                    wd_val, wd_tok, wd_lbl, wt_val, wt_suf, wt_lbl, _ = master_coords_meta[m]
                    if is_def_plane:
                        m_path = def_master_paths[m]
                    else:
                        m_path = os.path.join(tmpdir, f"master_{sp_idx}_{m:02d}_{wd_tok or 'Normal'}_{wt_suf}_{slnt_tag}.ttf")
                        _write_master_ttf(m, slnt_val, delta_tan, False, m_path)

                    src = SourceDescriptor()
                    src.path = m_path
                    src.familyName = spec["family_name"]
                    src.styleName = f"{wd_lbl} {wt_lbl} Slant{int(round(slnt_val))}".strip()
                    src.location = {"Width": float(wd_val), "Weight": float(wt_val), "Slant": float(slnt_val)}
                    if is_def_plane and m == DEFAULT_MASTER_IDX:
                        src.copyLib = src.copyInfo = src.copyGroups = src.copyFeatures = True
                    ds.addSource(src)

            # ALL 36 Named Instances (4 widths x 9 weights) with exact integer user coords via map_forward!
            w9_list = ALL_9_WEIGHTS_IT if is_it else ALL_9_WEIGHTS_UP
            for wd_val, wd_tok, wd_lbl, _ in WIDTH_MASTERS:
                for wt_val, wt_suf, wt_name in w9_list:
                    parts = []
                    if wd_val != 100.0:
                        parts.append(wd_lbl)
                    if wt_val != 400:
                        parts.append(wt_name)
                    if is_it:
                        parts.append("Italic")
                    style_name = " ".join(parts) if parts else "Regular"
                    ps_inst = f"{master_prefix(wd_tok, rounded)}-{wt_suf}"

                    inst = InstanceDescriptor()
                    inst.familyName = spec["family_name"]
                    inst.styleName = style_name
                    inst.postScriptFontName = ps_inst
                    inst.location = ds.map_forward(
                        {"Width": float(wd_val), "Weight": float(wt_val), "Slant": float(slnt_default)}
                    )
                    ds.addInstance(inst)

            t_var = time.time()
            vf, _, _ = varLib.build(ds, optimize=True, drop_implied_oncurves=True)
            print(f"  varLib.build (3-axis) succeeded in {time.time() - t_var:.1f}s! Tables: {sorted(vf.keys())}")

            # Smart gvar optimization: prune redundant slant cross-interaction & <=1u rounding noise tuples!
            cr_gvar_stats = optimize_gvar_tuples(vf, is_3axis=True, noise_thresh=1, max_corner_err=1.5)
            print(f"  [3-Axis gvar opt]: {cr_gvar_stats}")

            # Complete v1.100 metadata + 4-axis STAT + gasp + meta + OVERLAP_SIMPLE (keeps smcp/c2sc intact!)
            configure_vf_metadata_and_stat(
                vf, spec, google_fonts=False, win_ascent=eff_win_asc, win_descent=eff_win_desc
            )

            os.makedirs(out_dir, exist_ok=True)
            ttf_out = os.path.join(out_dir, f"{spec['out_stem']}.ttf")
            woff2_out = os.path.join(out_dir, f"{spec['out_stem']}.woff2")

            vf.save(ttf_out)
            vf.flavor = "woff2"
            vf.save(woff2_out)
            vf.close()

            ttf_kb = os.path.getsize(ttf_out) // 1024
            woff2_kb = os.path.getsize(woff2_out) // 1024
            print(f"  [3-Axis Creative] Exported {ttf_out} ({ttf_kb/1024:.2f} MB) & {woff2_out} ({woff2_kb/1024:.2f} MB) in {time.time() - t_cr:.1f}s")
            result.update({
                "ttf_path": ttf_out,
                "woff2_path": woff2_out,
                "ttf_kb": ttf_kb,
                "woff2_kb": woff2_kb,
                "ttf_bytes": os.path.getsize(ttf_out),
                "woff2_bytes": os.path.getsize(woff2_out),
                "num_masters": num_total_masters,
                "num_instances": 36,
                "creative_gvar_stats": cr_gvar_stats,
            })

    for f in orig_fonts:
        f.close()

    result["elapsed_s"] = round(time.time() - t0, 2)
    return result


def patch_glyphs_in_vf(vf_key, glyph_names, otf_dir, out_dir, max_err=0.75):
    """
    Fast, bit-exact surgical VF patcher: rebuilds glyf + gvar (for glyph_names) and
    recomputes HVAR across all 4,577 glyphs from the 16 static OTF masters in ~5s per VF!
    """
    spec = VF_SPECS[vf_key]
    is_it = spec["is_italic"]
    rounded = spec["rounded"]
    ttf_out = os.path.join(out_dir, f"{spec['out_stem']}.ttf")
    woff2_out = os.path.join(out_dir, f"{spec['out_stem']}.woff2")
    t0 = time.time()

    print(f"\n--- Patching {len(glyph_names)} glyphs in [{vf_key}] ({spec['out_stem']}) ---")
    vf = TTFont(ttf_out)
    avar_map, _ = measure_wght_avar_map(otf_dir, rounded, is_it)

    w_masters = WEIGHT_MASTERS_IT if is_it else WEIGHT_MASTERS_UP
    orig_fonts = []
    meta = []
    for wd_val, wd_tok, wd_lbl, _ in WIDTH_MASTERS:
        for wt_val, wt_suf, wt_lbl in w_masters:
            p = master_otf_path(otf_dir, wd_tok, wt_suf, rounded)
            orig_fonts.append(TTFont(p))
            meta.append((wd_val, wd_tok, wd_lbl, wt_val, wt_suf, wt_lbl, p))

    # Build compatible TrueType payloads for [".notdef"] + glyph_names
    sub_order = [".notdef"] + [g for g in glyph_names if g != ".notdef"]
    tt_map = {}
    for gname in sub_order:
        raw_16 = [extract_contours(f, gname) for f in orig_fonts]
        advs_16 = [f["hmtx"][gname][0] for f in orig_fonts]
        _, payloads, rmode = build_compatible_tt_glyphs_for_name((gname, raw_16, advs_16, is_it, max_err))
        tt_map[gname] = payloads
        if gname != ".notdef":
            print(f"  {gname:12s}: reconcile={rmode}, pts={len(payloads[DEFAULT_MASTER_IDX][0]) if payloads[DEFAULT_MASTER_IDX] else 0}")

    slnt_default = SLNT_DEFAULT_IT if is_it else SLNT_DEFAULT_UP
    slnt_planes = [-8.0, 0.0, -12.0] if is_it else [0.0, -12.0]
    slnt_avar_map = compute_slnt_avar_map(is_it)

    with tempfile.TemporaryDirectory(prefix=f"batumi_patch_{vf_key}_") as tmpdir:
        ds = DesignSpaceDocument()
        ax_wdth = AxisDescriptor()
        ax_wdth.tag = "wdth"; ax_wdth.name = "Width"
        ax_wdth.minimum = 75.0; ax_wdth.default = 100.0; ax_wdth.maximum = 115.0
        ax_wdth.map = [(75.0, 75.0), (87.5, 87.5), (100.0, 100.0), (115.0, 115.0)]
        ds.addAxis(ax_wdth)

        ax_wght = AxisDescriptor()
        ax_wght.tag = "wght"; ax_wght.name = "Weight"
        ax_wght.minimum = 100.0; ax_wght.default = 400.0; ax_wght.maximum = 900.0
        ax_wght.map = avar_map
        ds.addAxis(ax_wght)

        ax_slnt = AxisDescriptor()
        ax_slnt.tag = "slnt"; ax_slnt.name = "Slant"
        ax_slnt.minimum = SLNT_MIN; ax_slnt.default = slnt_default; ax_slnt.maximum = SLNT_MAX
        ax_slnt.map = slnt_avar_map
        ds.addAxis(ax_slnt)

        hvar_fonts = []
        for sp_idx, slnt_val in enumerate(slnt_planes):
            delta_tan = math.tan(math.radians(-slnt_val)) - math.tan(math.radians(-slnt_default))
            is_def_plane = abs(slnt_val - slnt_default) < 1e-6
            for m in range(16):
                wd_val, wd_tok, wd_lbl, wt_val, wt_suf, wt_lbl, _ = meta[m]
                of = orig_fonts[m]
                hvar_fonts.append(of)
                mt = TTFont()
                mt.sfntVersion = "\x00\x01\x00\x00"
                mt.setGlyphOrder(sub_order)
                for tag in ("head", "hhea", "OS/2", "name", "post"):
                    mt[tag] = copy.deepcopy(of[tag])
                mt["post"].formatType = 2.0
                mt["post"].extraNames = []
                mt["post"].mapping = {}

                glyf = newTable("glyf")
                glyf.glyphs = {}
                glyf.glyphOrder = list(sub_order)
                hmtx = newTable("hmtx")
                hmtx.metrics = {}
                for gname in sub_order:
                    pl = tt_map[gname][m]
                    if not is_def_plane:
                        pl = shear_tt_payload(pl, delta_tan)
                    gobj = payload_to_tt_glyph(pl)
                    glyf.glyphs[gname] = gobj
                    adv = of["hmtx"][gname][0]
                    lsb = gobj.xMin if gobj.numberOfContours > 0 else 0
                    hmtx.metrics[gname] = (adv, lsb)
                mt["glyf"] = glyf
                mt["loca"] = newTable("loca")
                mt["hmtx"] = hmtx

                maxp = newTable("maxp")
                maxp.tableVersion = 0x00010000
                maxp.numGlyphs = len(sub_order)
                maxp.maxPoints = maxp.maxContours = maxp.maxCompositePoints = maxp.maxCompositeContours = 0
                maxp.maxZones = 2
                maxp.maxTwilightPoints = maxp.maxStorage = maxp.maxFunctionDefs = maxp.maxInstructionDefs = 0
                maxp.maxStackElements = maxp.maxSizeOfInstructions = maxp.maxComponentElements = maxp.maxComponentDepth = 0
                mt["maxp"] = maxp

                mp = os.path.join(tmpdir, f"m_{sp_idx}_{m:02d}.ttf")
                mt.save(mp)
                mt.close()

                src = SourceDescriptor()
                src.path = mp
                src.familyName = spec["family_name"]
                src.styleName = f"{wd_lbl} {wt_lbl} Slant{int(round(slnt_val))}".strip()
                src.location = {"Width": float(wd_val), "Weight": float(wt_val), "Slant": float(slnt_val)}
                ds.addSource(src)

        mini_vf, masterModel, _ = varLib.build(ds, optimize=True, drop_implied_oncurves=True)

        # Splice patched glyphs cleanly into full VF
        for gname in glyph_names:
            vf["glyf"][gname] = copy.deepcopy(mini_vf["glyf"][gname])
            vf["gvar"].variations[gname] = copy.deepcopy(mini_vf["gvar"].variations[gname])
            vf["hmtx"][gname] = mini_vf["hmtx"][gname]

        # Recompute HVAR across all 4,579 glyphs cleanly from hvar_fonts
        if "HVAR" in vf:
            del vf["HVAR"]
        varLib._add_HVAR(vf, masterModel, hvar_fonts, ["wdth", "wght", "slnt"])
        mini_vf.close()

    num_glyphs_out = len(vf.getGlyphOrder())
    vf.save(ttf_out)
    vf.flavor = "woff2"
    vf.save(woff2_out)
    vf.close()
    for f in orig_fonts:
        f.close()

    ttf_kb = os.path.getsize(ttf_out) // 1024
    woff2_kb = os.path.getsize(woff2_out) // 1024
    elapsed = time.time() - t0
    print(f"  Patched & saved {ttf_out} ({ttf_kb} KB) & {woff2_out} ({woff2_kb} KB) in {elapsed:.1f}s")
    return {
        "vf_key": vf_key,
        "out_stem": spec["out_stem"],
        "family_name": spec["family_name"],
        "subfamily_name": spec["subfamily_name"],
        "ttf_path": ttf_out,
        "woff2_path": woff2_out,
        "ttf_kb": ttf_kb,
        "woff2_kb": woff2_kb,
        "num_glyphs": num_glyphs_out,
        "num_masters": 16 * len(slnt_planes),
        "num_instances": 36,
        "avar_wght_map": avar_map,
        "avar_slnt_map": slnt_avar_map,
        "elapsed_s": round(elapsed, 2),
    }


def patch_gpos_in_vfs(
    vf_key,
    otf_dir,
    out_dir,
    build_creative=True,
    build_google_fonts=True,
    gf_repo_dir=None,
    gf_dist_dir=None,
):
    """
    Fast surgical GPOS + GDEF VarStore hot-rebuild for existing Variable Fonts (both 2-axis GF
    and 3-axis Creative editions) using `fontTools.varLib._merge_OTL` on the exact fvar+avar
    VariationModel — produces bit-exact variable GPOS + GDEF in ~5s per family without re-running
    35-minute outline/gvar compilation!
    """
    import shutil
    from fontTools.varLib.models import VariationModel, normalizeLocation, piecewiseLinearMap

    t0 = time.time()
    spec = VF_SPECS[vf_key]
    is_it = spec["is_italic"]
    rounded = spec["rounded"]
    wt_masters = WEIGHT_MASTERS_IT if is_it else WEIGHT_MASTERS_UP
    slnt_default = SLNT_DEFAULT_IT if is_it else SLNT_DEFAULT_UP
    slnt_planes = [0.0, -8.0, -12.0] if is_it else [0.0, -12.0]

    print(f"\n[GPOS-ONLY] Hot-merging variable GPOS+GDEF for {vf_key} ({spec['out_stem']})...")
    orig_fonts = []
    master_coords_meta = []
    for wd_val, wd_tok, wd_lbl, _ in WIDTH_MASTERS:
        for wt_val, wt_suf, wt_lbl in wt_masters:
            mp = os.path.join(otf_dir, f"{master_prefix(wd_tok, rounded)}-{wt_suf}.otf")
            if not os.path.exists(mp):
                raise FileNotFoundError(f"Missing static OTF master: {mp}")
            orig_fonts.append(TTFont(mp))
            master_coords_meta.append((wd_val, wd_tok, wd_lbl, wt_val, wt_suf, wt_lbl, mp))

    default_otf = orig_fonts[DEFAULT_MASTER_IDX]
    unified_gpos_16 = build_unified_variable_gpos(default_otf, orig_fonts)
    clean_gdef = copy.deepcopy(default_otf["GDEF"])
    slnt_geor_set = set(get_georgian_slnt_target_glyphs(default_otf.getGlyphOrder(), default_otf.getBestCmap()))

    def _norm_loc_for_vf(vf, user_loc):
        axes = {a.axisTag: (a.minValue, a.defaultValue, a.maxValue) for a in vf["fvar"].axes}
        nloc = normalizeLocation(user_loc, axes)
        if "avar" in vf:
            segs = vf["avar"].segments
            for tag, val in list(nloc.items()):
                if tag in segs and segs[tag]:
                    nloc[tag] = piecewiseLinearMap(val, segs[tag])
        return nloc

    def _apply_merge_to_vf(ttf_path, woff2_path, is_3axis, extra_copy_path=None):
        t1 = time.time()
        vf = TTFont(ttf_path)
        glyph_order = list(vf.getGlyphOrder())
        saved_gsub = copy.deepcopy(vf["GSUB"])
        axis_tags = [a.axisTag for a in vf["fvar"].axes]

        planes = slnt_planes if is_3axis else [slnt_default]
        norm_locs = []
        master_stubs = []
        for slnt_val in planes:
            is_def_plane = abs(slnt_val - slnt_default) < 1e-6
            delta_tan = math.tan(math.radians(-slnt_val)) - math.tan(math.radians(-slnt_default))
            for m in range(16):
                wd_val, wd_tok, wd_lbl, wt_val, wt_suf, wt_lbl, _ = master_coords_meta[m]
                uloc = {"wdth": float(wd_val), "wght": float(wt_val)}
                if is_3axis:
                    uloc["slnt"] = float(slnt_val)
                norm_locs.append(_norm_loc_for_vf(vf, uloc))

                stub = TTFont()
                stub.setGlyphOrder(glyph_order)
                stub["GSUB"] = copy.deepcopy(saved_gsub)
                stub["GDEF"] = copy.deepcopy(clean_gdef)
                if is_def_plane:
                    stub["GPOS"] = copy.deepcopy(unified_gpos_16[m])
                else:
                    sg = shear_gpos_anchors(unified_gpos_16[m], delta_tan)
                    slnt_add = compute_slnt_breathing(wt_val, slnt_val, is_it)
                    if slnt_add > 0:
                        shift_gpos_mark_anchors_x(sg, {g: slnt_add for g in slnt_geor_set})
                    stub["GPOS"] = sg
                master_stubs.append(stub)

        model = VariationModel(norm_locs, axisOrder=axis_tags)
        vf["GDEF"] = copy.deepcopy(clean_gdef)
        vf["GPOS"] = copy.deepcopy(unified_gpos_16[DEFAULT_MASTER_IDX])
        varLib._merge_OTL(vf, model, master_stubs, axis_tags)

        vf.save(ttf_path)
        if extra_copy_path:
            shutil.copy2(ttf_path, extra_copy_path)
        if woff2_path:
            vf.flavor = "woff2"
            vf.save(woff2_path)
        vf.close()
        print(f"  Merged GPOS+GDEF -> {os.path.basename(ttf_path)} ({os.path.getsize(ttf_path)/1024/1024:.2f} MB) in {time.time() - t1:.1f}s")

    result = {"vf_key": vf_key, "out_stem": spec["out_stem"]}
    if build_google_fonts:
        gf_repo_eff = gf_repo_dir or os.path.join(BASE_DIR, "google-fonts")
        gf_dist_eff = gf_dist_dir or os.path.join(BASE_DIR, "dist", "google-fonts")
        gf_ttf_repo = os.path.join(gf_repo_eff, spec["gf_dir"], f"{spec['gf_stem']}.ttf")
        gf_ttf_dist = os.path.join(gf_dist_eff, f"{spec['gf_stem']}.ttf")
        gf_woff2_dist = os.path.join(gf_dist_eff, f"{spec['gf_stem']}.woff2")
        _apply_merge_to_vf(gf_ttf_repo, gf_woff2_dist, is_3axis=False, extra_copy_path=gf_ttf_dist)
        result["gf_ttf_path"] = gf_ttf_repo

    if build_creative:
        ttf_out = os.path.join(out_dir, f"{spec['out_stem']}.ttf")
        woff2_out = os.path.join(out_dir, f"{spec['out_stem']}.woff2")
        _apply_merge_to_vf(ttf_out, woff2_out, is_3axis=True)
        result["ttf_path"] = ttf_out
        result["woff2_path"] = woff2_out

    for f in orig_fonts:
        f.close()
    result["elapsed_s"] = round(time.time() - t0, 2)
    return result


def add_khutsuri_to_vfs(
    vf_key,
    otf_dir,
    out_dir,
    build_creative=True,
    build_google_fonts=True,
    gf_repo_dir=None,
    gf_dist_dir=None,
    max_err=0.75,
    new_cps=KHUTSURI_CPS,
    new_glyph_names=KHUTSURI_GLYPH_NAMES,
    label="KHUTSURI-VF",
    update_calt_khutsuri=False,
    update_calt_karagma=False,
):
    """
    Fast, bit-exact surgical VF updater that splices all 80 new Georgian Khutsuri glyphs
    (40 Asomtavruli + 40 Nuskhuri) into existing 2-axis Google Fonts & 3-axis Creative VFs:
      - Aligns & cu2qu-converts the 80 glyphs across all 16 masters (`0` topology mismatches!)
      - Runs `varLib.build` on a mini-VF of ONLY those 81 glyphs (`~1s`!)
      - Appends glyphs cleanly into `glyf`, `gvar`, `hmtx`, `cmap`, `maxp`, `OVERLAP_SIMPLE`
      - Recomputes full 4,762-glyph `HVAR` (preserving exact `slnt=-12°` Georgian breathing!)
      - Updates `OS/2` Unicode ranges + `nameID 0` copyright (adding Noto Sans Georgian OFL 1.1)
      - Hot-merges updated variable `GPOS` + `GDEF` (`ItemVariationStore`) via `varLib._merge_OTL`!
    """
    import shutil
    from fontTools.varLib.models import VariationModel, normalizeLocation, piecewiseLinearMap

    t0 = time.time()
    spec = VF_SPECS[vf_key]
    is_it = spec["is_italic"]
    rounded = spec["rounded"]
    wt_masters = WEIGHT_MASTERS_IT if is_it else WEIGHT_MASTERS_UP
    slnt_default = SLNT_DEFAULT_IT if is_it else SLNT_DEFAULT_UP
    slnt_planes = [0.0, -8.0, -12.0] if is_it else [0.0, -12.0]

    print(f"\n[{label}] Adding {len(new_glyph_names)} glyphs + variable GPOS+GDEF to {vf_key} ({spec['out_stem']})...")
    orig_fonts = []
    meta = []
    for wd_val, wd_tok, wd_lbl, _ in WIDTH_MASTERS:
        for wt_val, wt_suf, wt_lbl in wt_masters:
            mp = os.path.join(otf_dir, f"{master_prefix(wd_tok, rounded)}-{wt_suf}.otf")
            if not os.path.exists(mp):
                raise FileNotFoundError(f"Missing static OTF master: {mp}")
            orig_fonts.append(TTFont(mp))
            meta.append((wd_val, wd_tok, wd_lbl, wt_val, wt_suf, wt_lbl, mp))

    default_otf = orig_fonts[DEFAULT_MASTER_IDX]
    full_order = list(default_otf.getGlyphOrder())
    sub_order = [".notdef"] + list(new_glyph_names)
    avar_map, _ = measure_wght_avar_map(otf_dir, rounded, is_it)
    slnt_avar_map = compute_slnt_avar_map(is_it)

    # Align & convert ONLY the new glyphs across all 16 masters (~3s!)
    tt_map = {}
    rmode_counts = {}
    for gname in sub_order:
        raw_16 = [extract_contours(f, gname) for f in orig_fonts]
        advs_16 = [f["hmtx"][gname][0] for f in orig_fonts]
        _, payloads, rmode = build_compatible_tt_glyphs_for_name((gname, raw_16, advs_16, is_it, max_err))
        tt_map[gname] = payloads
        rmode_counts[rmode] = rmode_counts.get(rmode, 0) + 1
    print(f"  Aligned {len(new_glyph_names)} glyphs across 16 masters: {rmode_counts}")

    unified_gpos_16 = build_unified_variable_gpos(default_otf, orig_fonts)
    clean_gdef = copy.deepcopy(default_otf["GDEF"])
    slnt_geor_set = set(get_georgian_slnt_target_glyphs(full_order, default_otf.getBestCmap()))

    def _norm_loc_for_vf(vf, user_loc):
        axes = {a.axisTag: (a.minValue, a.defaultValue, a.maxValue) for a in vf["fvar"].axes}
        nloc = normalizeLocation(user_loc, axes)
        if "avar" in vf:
            segs = vf["avar"].segments
            for tag, val in list(nloc.items()):
                if tag in segs and segs[tag]:
                    nloc[tag] = piecewiseLinearMap(val, segs[tag])
        return nloc

    def _splice_into_vf(ttf_path, woff2_path, is_3axis, extra_copy_path=None):
        t1 = time.time()
        vf = TTFont(ttf_path)
        # Eagerly decompile all glyph-indexed tables BEFORE extending glyphOrder (4682 -> 4762)!
        for _tag in ("glyf", "gvar", "hmtx", "cmap", "post", "OS/2", "name", "GSUB", "GDEF", "GPOS"):
            if _tag in vf:
                _ = vf[_tag]
        saved_gsub = copy.deepcopy(vf["GSUB"])
        axis_tags = [a.axisTag for a in vf["fvar"].axes]
        planes = slnt_planes if is_3axis else [slnt_default]

        # Build exact DesignSpace for the 81-glyph mini-VF matching target VF's fvar+avar!
        with tempfile.TemporaryDirectory(prefix=f"batumi_khut_{vf_key}_") as tmpdir:
            ds = DesignSpaceDocument()
            ax_wdth = AxisDescriptor()
            ax_wdth.tag = "wdth"; ax_wdth.name = "Width"
            ax_wdth.minimum = 75.0; ax_wdth.default = 100.0; ax_wdth.maximum = 115.0
            ax_wdth.map = [(75.0, 75.0), (87.5, 87.5), (100.0, 100.0), (115.0, 115.0)]
            ds.addAxis(ax_wdth)

            ax_wght = AxisDescriptor()
            ax_wght.tag = "wght"; ax_wght.name = "Weight"
            ax_wght.minimum = 100.0; ax_wght.default = 400.0; ax_wght.maximum = 900.0
            ax_wght.map = avar_map
            ds.addAxis(ax_wght)

            if is_3axis:
                ax_slnt = AxisDescriptor()
                ax_slnt.tag = "slnt"; ax_slnt.name = "Slant"
                ax_slnt.minimum = SLNT_MIN; ax_slnt.default = slnt_default; ax_slnt.maximum = SLNT_MAX
                ax_slnt.map = slnt_avar_map
                ds.addAxis(ax_slnt)

            hvar_stubs = []
            otl_stubs = []
            norm_locs = []
            for sp_idx, slnt_val in enumerate(planes):
                is_def_plane = abs(slnt_val - slnt_default) < 1e-6
                delta_tan = math.tan(math.radians(-slnt_val)) - math.tan(math.radians(-slnt_default))
                for m in range(16):
                    wd_val, wd_tok, wd_lbl, wt_val, wt_suf, wt_lbl, _ = meta[m]
                    of = orig_fonts[m]
                    slnt_add = 0 if is_def_plane else compute_slnt_breathing(wt_val, slnt_val, is_it)

                    # Lightweight mini-master TTF for the 81 glyphs
                    mt = TTFont()
                    mt.sfntVersion = "\x00\x01\x00\x00"
                    mt.setGlyphOrder(sub_order)
                    for tag in ("head", "hhea", "OS/2", "name", "post"):
                        mt[tag] = copy.deepcopy(of[tag])
                    mt["post"].formatType = 2.0
                    mt["post"].extraNames = []
                    mt["post"].mapping = {}

                    glyf = newTable("glyf")
                    glyf.glyphs = {}
                    glyf.glyphOrder = list(sub_order)
                    hmtx = newTable("hmtx")
                    hmtx.metrics = {}
                    for gname in sub_order:
                        pl = tt_map[gname][m]
                        adv = of["hmtx"][gname][0]
                        if not is_def_plane:
                            pl = shear_tt_payload(pl, delta_tan)
                            if slnt_add > 0 and gname in slnt_geor_set:
                                pl = translate_tt_payload(pl, slnt_add, 0)
                                adv += 2 * slnt_add
                        gobj = payload_to_tt_glyph(pl)
                        glyf.glyphs[gname] = gobj
                        lsb = gobj.xMin if gobj.numberOfContours > 0 else 0
                        hmtx.metrics[gname] = (adv, lsb)
                    mt["glyf"] = glyf
                    mt["loca"] = newTable("loca")
                    mt["hmtx"] = hmtx

                    maxp = newTable("maxp")
                    maxp.tableVersion = 0x00010000
                    maxp.numGlyphs = len(sub_order)
                    maxp.maxPoints = maxp.maxContours = maxp.maxCompositePoints = maxp.maxCompositeContours = 0
                    maxp.maxZones = 2
                    maxp.maxTwilightPoints = maxp.maxStorage = maxp.maxFunctionDefs = maxp.maxInstructionDefs = 0
                    maxp.maxStackElements = maxp.maxSizeOfInstructions = maxp.maxComponentElements = maxp.maxComponentDepth = 0
                    mt["maxp"] = maxp

                    mp = os.path.join(tmpdir, f"kh_{sp_idx}_{m:02d}.ttf")
                    mt.save(mp)
                    mt.close()

                    uloc = {"wdth": float(wd_val), "wght": float(wt_val)}
                    ds_loc = {"Width": float(wd_val), "Weight": float(wt_val)}
                    if is_3axis:
                        uloc["slnt"] = float(slnt_val)
                        ds_loc["Slant"] = float(slnt_val)
                    norm_locs.append(_norm_loc_for_vf(vf, uloc))

                    src = SourceDescriptor()
                    src.path = mp
                    src.familyName = spec["family_name"]
                    src.styleName = f"{wd_lbl} {wt_lbl} S{int(round(slnt_val))}".strip()
                    src.location = ds_loc
                    ds.addSource(src)

                    # Full-glyph-order HVAR stub (preserving exact slnt=-12° breathing!)
                    hs = TTFont()
                    hs.setGlyphOrder(full_order)
                    hs_hmtx = newTable("hmtx")
                    hs_hmtx.metrics = {}
                    for gn in full_order:
                        a, l = of["hmtx"][gn]
                        if slnt_add > 0 and gn in slnt_geor_set:
                            hs_hmtx.metrics[gn] = (a + 2 * slnt_add, l + slnt_add)
                        else:
                            hs_hmtx.metrics[gn] = (a, l)
                    hs["hmtx"] = hs_hmtx
                    hvar_stubs.append(hs)

                    # Full-glyph-order OTL stub for GPOS+GDEF merge
                    os_stub = TTFont()
                    os_stub.setGlyphOrder(full_order)
                    os_stub["GSUB"] = copy.deepcopy(saved_gsub)
                    os_stub["GDEF"] = copy.deepcopy(clean_gdef)
                    if is_def_plane:
                        os_stub["GPOS"] = copy.deepcopy(unified_gpos_16[m])
                    else:
                        sg = shear_gpos_anchors(unified_gpos_16[m], delta_tan)
                        if slnt_add > 0:
                            shift_gpos_mark_anchors_x(sg, {g: slnt_add for g in slnt_geor_set})
                        os_stub["GPOS"] = sg
                    otl_stubs.append(os_stub)

            mini_vf, masterModel, _ = varLib.build(ds, optimize=True, drop_implied_oncurves=True)

            # Explicitly prune any deprecated glyphs present in the existing VF that were
            # removed from the static OTF masters (e.g. uniFE22/uniFE23/uniFE26) so ZERO
            # stale glyphs, variations, metrics, or cmap mappings survive!
            old_order = list(vf.getGlyphOrder())
            full_order_set = set(full_order)
            stale_glyphs = [g for g in old_order if g not in full_order_set]
            if stale_glyphs:
                stale_set = set(stale_glyphs)
                # IMPORTANT: Delete from gvar.variations BEFORE glyf (gvar.variations is a LazyDict
                # whose __getitem__ reads glyf; MutableMapping.pop would swallow a glyf KeyError!)
                if "gvar" in vf:
                    gvar_vars = vf["gvar"].variations
                    for sg in stale_glyphs:
                        if sg in gvar_vars:
                            del gvar_vars[sg]
                    vf["gvar"].variations = {g: gvar_vars[g] for g in full_order if g in gvar_vars}
                for sg in stale_glyphs:
                    vf["glyf"].glyphs.pop(sg, None)
                    vf["hmtx"].metrics.pop(sg, None)
                for sub in vf["cmap"].tables:
                    if hasattr(sub, "cmap") and isinstance(sub.cmap, dict):
                        for cp in [k for k, v in sub.cmap.items() if v in stale_set]:
                            del sub.cmap[cp]
                print(f"  [{label}] Pruned {len(stale_glyphs)} removed glyphs from {os.path.basename(ttf_path)}: {stale_glyphs}")

            # Update VF glyph order cleanly to match static OTF masters identically
            vf.setGlyphOrder(full_order)
            vf["glyf"].glyphOrder = list(full_order)
            vf["maxp"].numGlyphs = len(full_order)
            vf["post"].extraNames = []
            vf["post"].mapping = {}

            # Splice new glyphs into glyf, gvar, hmtx, and cmap
            for gname in new_glyph_names:
                vf["glyf"][gname] = copy.deepcopy(mini_vf["glyf"][gname])
                vf["gvar"].variations[gname] = copy.deepcopy(mini_vf["gvar"].variations[gname])
                vf["hmtx"][gname] = mini_vf["hmtx"][gname]
            for cp in new_cps:
                gn = f"uni{cp:04X}"
                for sub in vf["cmap"].tables:
                    if sub.isUnicode():
                        if sub.format == 4 and cp <= 0xFFFF:
                            sub.cmap[cp] = gn
                        elif sub.format == 12:
                            sub.cmap[cp] = gn

            if update_calt_khutsuri or update_calt_karagma:
                if update_calt_khutsuri:
                    update_calt_georgian_ampersand_for_khutsuri(vf)
                if update_calt_karagma:
                    wire_gsub_karagma(vf)
                updated_gsub = copy.deepcopy(vf["GSUB"])
                for os_stub in otl_stubs:
                    os_stub["GSUB"] = copy.deepcopy(updated_gsub)

            # Recompute full 4,762-glyph HVAR on exact masterModel
            if "HVAR" in vf:
                del vf["HVAR"]
            varLib._add_HVAR(vf, masterModel, hvar_stubs, axis_tags)
            mini_vf.close()

        # Re-apply OVERLAP_SIMPLE flags (covers the 80 new glyphs cleanly)
        apply_overlap_simple_flags(vf)

        # Update nameID 0 copyright (includes Noto Sans Georgian OFL 1.1) & recalc OS/2 Unicode ranges
        vf["name"].setName(COPYRIGHT_STR, 0, 3, 1, 0x0409)
        # This routine patches a VF built earlier, so refresh the description as well;
        # otherwise the file keeps whatever text it had when it was first built.
        vf["name"].setName(DESCRIPTION_STR, 10, 3, 1, 0x0409)
        vf["OS/2"].recalcUnicodeRanges(vf)

        # Hot-merge variable GPOS + GDEF VarStore across all 4,762 glyphs
        otl_model = VariationModel(norm_locs, axisOrder=axis_tags)
        vf["GDEF"] = copy.deepcopy(clean_gdef)
        vf["GPOS"] = copy.deepcopy(unified_gpos_16[DEFAULT_MASTER_IDX])
        varLib._merge_OTL(vf, otl_model, otl_stubs, axis_tags)

        vf.save(ttf_path)
        if extra_copy_path:
            shutil.copy2(ttf_path, extra_copy_path)
        if woff2_path:
            vf.flavor = "woff2"
            vf.save(woff2_path)
        vf.close()
        print(
            f"  [{label}] Spliced {len(new_glyph_names)} glyphs & merged GPOS -> {os.path.basename(ttf_path)} "
            f"({len(full_order)} glyphs, {os.path.getsize(ttf_path)/1024/1024:.2f} MB) in {time.time() - t1:.1f}s"
        )

    result = {"vf_key": vf_key, "out_stem": spec["out_stem"], "num_glyphs": len(full_order)}
    if build_google_fonts:
        gf_repo_eff = gf_repo_dir or os.path.join(BASE_DIR, "google-fonts")
        gf_dist_eff = gf_dist_dir or os.path.join(BASE_DIR, "dist", "google-fonts")
        gf_ttf_repo = os.path.join(gf_repo_eff, spec["gf_dir"], f"{spec['gf_stem']}.ttf")
        gf_ttf_dist = os.path.join(gf_dist_eff, f"{spec['gf_stem']}.ttf")
        gf_woff2_dist = os.path.join(gf_dist_eff, f"{spec['gf_stem']}.woff2")
        _splice_into_vf(gf_ttf_repo, gf_woff2_dist, is_3axis=False, extra_copy_path=gf_ttf_dist)
        result["gf_ttf_path"] = gf_ttf_repo

    if build_creative:
        ttf_out = os.path.join(out_dir, f"{spec['out_stem']}.ttf")
        woff2_out = os.path.join(out_dir, f"{spec['out_stem']}.woff2")
        _splice_into_vf(ttf_out, woff2_out, is_3axis=True)
        result["ttf_path"] = ttf_out
        result["woff2_path"] = woff2_out

    for f in orig_fonts:
        f.close()
    result["elapsed_s"] = round(time.time() - t0, 2)
    return result


# ---------------------------------------------------------------------------
# Variable Font CSS Generator
# ---------------------------------------------------------------------------

def write_variable_css(out_dir):
    v = CSS_CACHE_VER
    css = f"""/* Batumi Sans Superfamily — 3-Axis OpenType Variable Fonts (SIL OFL 1.1) */
/* Axes: wght 100..900 (Thin..Heavy) x wdth 75..115 (Extra Condensed..Expanded) x slnt -12..0 (Slant 0deg..-12deg) */
/* Keeps font-style: normal (Upright VF) & font-style: italic (True Cursive Italic VF) so CSS italic / Cmd+I */
/* selects the true cursive Italic file while font-variation-settings: 'slnt' -8 drives continuous Slant cleanly. */
/* Provides BOTH standard production family names ('Batumi Sans', 'Batumi Sans Rounded') */
/* AND explicit VF aliases ('Batumi Sans VF', 'Batumi Sans Rounded VF') for side-by-side use. */

@font-face {{
  font-family: 'Batumi Sans';
  src: url('BatumiSans-VF.woff2?v={v}') format('woff2'),
       url('BatumiSans-VF.ttf?v={v}') format('truetype');
  font-weight: 100 900;
  font-stretch: 75% 115%;
  font-style: normal;
  font-display: swap;
}}

@font-face {{
  font-family: 'Batumi Sans';
  src: url('BatumiSans-Italic-VF.woff2?v={v}') format('woff2'),
       url('BatumiSans-Italic-VF.ttf?v={v}') format('truetype');
  font-weight: 100 900;
  font-stretch: 75% 115%;
  font-style: italic;
  font-display: swap;
}}

@font-face {{
  font-family: 'Batumi Sans Rounded';
  src: url('BatumiSansRounded-VF.woff2?v={v}') format('woff2'),
       url('BatumiSansRounded-VF.ttf?v={v}') format('truetype');
  font-weight: 100 900;
  font-stretch: 75% 115%;
  font-style: normal;
  font-display: swap;
}}

@font-face {{
  font-family: 'Batumi Sans Rounded';
  src: url('BatumiSansRounded-Italic-VF.woff2?v={v}') format('woff2'),
       url('BatumiSansRounded-Italic-VF.ttf?v={v}') format('truetype');
  font-weight: 100 900;
  font-stretch: 75% 115%;
  font-style: italic;
  font-display: swap;
}}

/* Explicit VF-only aliases (safe to load alongside dist/batumi-sans.css static fonts) */
@font-face {{
  font-family: 'Batumi Sans VF';
  src: url('BatumiSans-VF.woff2?v={v}') format('woff2'),
       url('BatumiSans-VF.ttf?v={v}') format('truetype');
  font-weight: 100 900;
  font-stretch: 75% 115%;
  font-style: normal;
  font-display: swap;
}}

@font-face {{
  font-family: 'Batumi Sans VF';
  src: url('BatumiSans-Italic-VF.woff2?v={v}') format('woff2'),
       url('BatumiSans-Italic-VF.ttf?v={v}') format('truetype');
  font-weight: 100 900;
  font-stretch: 75% 115%;
  font-style: italic;
  font-display: swap;
}}

@font-face {{
  font-family: 'Batumi Sans Rounded VF';
  src: url('BatumiSansRounded-VF.woff2?v={v}') format('woff2'),
       url('BatumiSansRounded-VF.ttf?v={v}') format('truetype');
  font-weight: 100 900;
  font-stretch: 75% 115%;
  font-style: normal;
  font-display: swap;
}}

@font-face {{
  font-family: 'Batumi Sans Rounded VF';
  src: url('BatumiSansRounded-Italic-VF.woff2?v={v}') format('woff2'),
       url('BatumiSansRounded-Italic-VF.ttf?v={v}') format('truetype');
  font-weight: 100 900;
  font-stretch: 75% 115%;
  font-style: italic;
  font-display: swap;
}}
"""
    css_path = os.path.join(out_dir, "batumi-sans-variable.css")
    with open(css_path, "w", encoding="utf-8") as fp:
        fp.write(css)
    return css_path


# ---------------------------------------------------------------------------
# Rigorous Intermediate Instantiation Audit (Geometry + Metadata + Kerning)
# ---------------------------------------------------------------------------

def get_audit_glyph_set(font):
    """Collect ALL Georgian + Latin + Cyrillic + Greek + 19 Currencies + 10 Quotes + Punctuation + Math/Arrows."""
    cm = font.getBestCmap()
    gset = set(font.getGlyphOrder())
    out = []
    seen = set()

    def add(g):
        if g and g in gset and g not in seen:
            seen.add(g)
            out.append(g)

    for g in get_georgian_glyphs(font):
        add(g)
    for g in get_currency_glyphs(font):
        add(g)
    for cp in range(0x0021, 0x0180):
        add(cm.get(cp))
    for cp in range(0x0370, 0x0400):
        add(cm.get(cp))
    for cp in range(0x0400, 0x0530):
        add(cm.get(cp))
    for cp in range(0x1F00, 0x2000):
        add(cm.get(cp))
    for cp in GEORGIAN_QUOTE_CODEPOINTS + CURRENCY_CODEPOINTS + EXTRA_CODEPOINTS:
        add(cm.get(cp))
    # Explicitly include redesigned keycaps: ⇦ ⇧ ⇨ ⇩ ⇪ ⏎ ⌫
    for cp in (0x21E6, 0x21E7, 0x21E8, 0x21E9, 0x21EA, 0x23CE, 0x232B):
        add(cm.get(cp))
    for cp, g in cm.items():
        ch = chr(cp)
        cat = unicodedata.category(ch)
        if cat.startswith("P") or cat == "Sm" or (0x2190 <= cp <= 0x23FF):
            # Exclude rare Arabic-Indic per mille/ten-thousand/triple-dot if unrounded
            if not (0x0600 <= cp <= 0x06FF):
                add(g)
    for g in EXTRA_GLYPHS:
        add(g)
    for g in ("uni0414.loclBGR", "uni052A.loclBGR", "uni1D70", "ampersand.geor", "ampersand.geor.case"):
        add(g)
    for cp in (0xE0A0, 0xE0A1):
        add(cm.get(cp))
    for d in DIGIT_BASES:
        for suf in ("", ".tf", ".osf", ".tosf", ".zero"):
            add(d + suf)
    return out


def audit_tt_glyph_geometry(font, gname):
    """Verify TrueType CW-outer / CCW-hole winding and skia-pathops zero self-intersection."""
    gs = font.getGlyphSet()
    p = pathops.Path()
    gs[gname].draw(p.getPen())
    if not p.bounds:
        return [], 0, 0.0
    raw_area = abs(p.area)
    # TrueType uses CW outer -> p_simp with clockwise=True preserves exact sign/area
    p_simp = pathops.simplify(p, clockwise=True)
    simp_area = abs(p_simp.area)
    issues = []
    if raw_area > 50 and abs(raw_area - simp_area) / raw_area > 0.02:
        issues.append(f"{gname}: pathops self-intersection raw={raw_area:.0f} simp={simp_area:.0f} ({abs(raw_area-simp_area)/raw_area*100:.1f}%)")

    # Check TrueType winding per contour (after converting via extract_contours -> CW outer means negative area!)
    cs = extract_contours(font, gname)
    if cs:
        # Reverse to PostScript convention and verify fix_disjoint_outer_winding reports NO flip needed!
        rev_cs = [reverse_contour(c) for c in cs]
        _, needs_fix = fix_disjoint_outer_winding(rev_cs)
        if needs_fix:
            # Verify it's not a tiny degenerate/collapsed contour
            non_tiny = [c for c in rev_cs if abs(contour_signed_area(c)) > 20.0]
            if non_tiny:
                _, needs_fix2 = fix_disjoint_outer_winding(non_tiny)
                if needs_fix2:
                    issues.append(f"{gname}: TrueType winding mismatch")
        hole_area = sum(abs(contour_signed_area(c)) for c in rev_cs if contour_signed_area(c) < -5.0)
        n_holes = sum(1 for c in rev_cs if contour_signed_area(c) < -5.0)
    else:
        hole_area = 0.0
        n_holes = 0
    return issues, n_holes, hole_area


def measure_I_slant_deg(font, y_lo=180.0, y_hi=500.0):
    """Measure exact OpenType slant angle (negative = rightward lean) of glyph 'I'."""
    cs = extract_contours(font, "I")
    mids = []
    for yp in (y_lo, y_hi):
        xs = []
        for c in cs:
            for seg in c:
                prev = eval_seg(seg, 0.0)
                steps = 2 if seg[0] == "line" else 24
                for k in range(1, steps + 1):
                    cur = eval_seg(seg, k / float(steps))
                    if (prev[1] <= yp < cur[1]) or (cur[1] <= yp < prev[1]):
                        t = (yp - prev[1]) / (cur[1] - prev[1])
                        xs.append(prev[0] + t * (cur[0] - prev[0]))
                    prev = cur
        if len(xs) >= 2:
            xs.sort()
            mids.append(0.5 * (xs[0] + xs[-1]))
    if len(mids) != 2:
        return 0.0
    return -math.degrees(math.atan2(mids[1] - mids[0], y_hi - y_lo))


def audit_variable_font(vf_key, ttf_path, woff2_path, otf_dir):
    spec = VF_SPECS[vf_key]
    is_it = spec["is_italic"]
    rounded = spec["rounded"]
    vf = TTFont(ttf_path)
    issues = []

    # 1. Required VF tables & metadata checks
    for req_tbl in ("fvar", "avar", "gvar", "HVAR", "STAT", "GSUB", "GPOS", "GDEF", "cmap", "OS/2", "head", "post"):
        if req_tbl not in vf:
            issues.append(f"Missing required table: {req_tbl}")

    # RFN ('Fira') & stale family-name ('Borbalo Sans') leak check across name records
    # Note: Borbalo (KJ Group) IS the legitimate foundry/copyright/designer/manufacturer in nameID 0,7,8,9,10,11,12!
    for rec in vf["name"].names:
        txt = rec.toUnicode()
        if rec.platformID == 1:
            issues.append(f"Legacy Mac platformID=1 record present in nameID {rec.nameID}")
        if rec.nameID in (1, 2, 3, 4, 6, 16, 17, 25) and "borbalo" in txt.lower():
            issues.append(f"STALE BRAND LEAK in nameID {rec.nameID}: {txt!r}")
        if rec.nameID != 0 and "fira" in txt.lower():
            issues.append(f"RFN LEAK in nameID {rec.nameID}: {txt!r}")

    # Verify native Cmd+I style-linking (identical family, exact RIBBI flags, STAT ital Format 3 / Format 1)
    # Per Google Fonts `googlefonts/font_names`, redundant nameID 16/17 MUST be omitted on RIBBI VFs!
    nm = vf["name"]
    def _gn(nid):
        r = nm.getName(nid, 3, 1, 0x409)
        return r.toUnicode() if r else None
    if _gn(1) != spec["family_name"]:
        issues.append(f"Cmd+I family mismatch: nameID1={_gn(1)!r}, expected {spec['family_name']!r}")
    if _gn(16) is not None and _gn(16) != spec["family_name"]:
        issues.append(f"Cmd+I family mismatch: nameID16={_gn(16)!r}, expected None or {spec['family_name']!r}")
    exp_sub = "Italic" if is_it else "Regular"
    if _gn(2) != exp_sub:
        issues.append(f"Cmd+I subfamily mismatch: nameID2={_gn(2)!r}, expected {exp_sub!r}")
    if _gn(17) is not None and _gn(17) != exp_sub:
        issues.append(f"Cmd+I subfamily mismatch: nameID17={_gn(17)!r}, expected None or {exp_sub!r}")
    fs = vf["OS/2"].fsSelection
    mac = vf["head"].macStyle
    if is_it:
        if not (fs & 0x01) or (fs & 0x40) or not (fs & 0x80) or mac != 0x02:
            issues.append(f"Italic flags invalid: fsSelection=0x{fs:04x}, macStyle=0x{mac:04x}")
    else:
        if (fs & 0x01) or not (fs & 0x40) or not (fs & 0x80) or mac != 0x00:
            issues.append(f"Upright flags invalid: fsSelection=0x{fs:04x}, macStyle=0x{mac:04x}")
    # Verify STAT 4 axes (wdth, wght, slnt, ital) & Format 3 (Upright 0->1) / Format 1 (Italic 1)
    stat_tbl = vf["STAT"].table
    stat_tags = [ax.AxisTag for ax in stat_tbl.DesignAxisRecord.Axis]
    for req_stat_ax in ("wdth", "wght", "slnt", "ital"):
        if req_stat_ax not in stat_tags:
            issues.append(f"STAT missing '{req_stat_ax}' axis (found {stat_tags})")
    if "ital" in stat_tags:
        ital_idx = stat_tags.index("ital")
        ital_vals = [av for av in stat_tbl.AxisValueArray.AxisValue if av.AxisIndex == ital_idx]
        if is_it:
            if not any(av.Format == 1 and av.Value == 1.0 and av.Flags == 0 for av in ital_vals):
                issues.append("STAT Italic missing Format 1 ital=1.0 AxisValue")
        else:
            if not any(av.Format == 3 and av.Value == 0.0 and av.LinkedValue == 1.0 and (av.Flags & 0x02) for av in ital_vals):
                issues.append("STAT Upright missing Format 3 ital=0.0->1.0 ELIDABLE AxisValue")
    if "slnt" in stat_tags:
        slnt_idx = stat_tags.index("slnt")
        slnt_vals = [av for av in stat_tbl.AxisValueArray.AxisValue if av.AxisIndex == slnt_idx]
        exp_def_s = -8.0 if is_it else 0.0
        if not any(abs(getattr(av, "NominalValue", getattr(av, "Value", 99.0)) - exp_def_s) < 1e-3 and (av.Flags & 0x02) for av in slnt_vals):
            issues.append(f"STAT slnt missing elidable default AxisValue at {exp_def_s}")

    # Axis & instance count checks (3-axis: wdth, wght, slnt)
    axes = {a.axisTag: (a.minValue, a.defaultValue, a.maxValue) for a in vf["fvar"].axes}
    if axes.get("wght") != (100.0, 400.0, 900.0):
        issues.append(f"fvar wght mismatch: {axes.get('wght')}")
    if axes.get("wdth") != (75.0, 100.0, 115.0):
        issues.append(f"fvar wdth mismatch: {axes.get('wdth')}")
    exp_slnt_axis = (SLNT_MIN, SLNT_DEFAULT_IT if is_it else SLNT_DEFAULT_UP, SLNT_MAX)
    if axes.get("slnt") != exp_slnt_axis:
        issues.append(f"fvar slnt mismatch: {axes.get('slnt')}, expected {exp_slnt_axis}")
    if len(vf["fvar"].instances) != 36:
        issues.append(f"fvar instance count={len(vf['fvar'].instances)}, expected 36")

    # Mtavruli U+1C90..U+1CBF cmap check
    cm = vf.getBestCmap()
    mtv_cps = list(range(0x1C90, 0x1CBB)) + list(range(0x1CBD, 0x1CC0))
    missing_mtv = [cp for cp in mtv_cps if cp not in cm]
    if missing_mtv:
        issues.append(f"Missing {len(missing_mtv)} Mtavruli codepoints in cmap")
    missing_curr = [cp for cp in CURRENCY_CODEPOINTS if cp not in cm]
    if missing_curr:
        issues.append(f"Missing {len(missing_curr)} currency codepoints in cmap")
    missing_quotes = [cp for cp in GEORGIAN_QUOTE_CODEPOINTS if cp not in cm]
    if missing_quotes:
        issues.append(f"Missing {len(missing_quotes)} Georgian quote codepoints in cmap")

    # WOFF2 reload check
    try:
        wf = TTFont(woff2_path)
        assert "gvar" in wf and "fvar" in wf and "STAT" in wf
        wf.close()
    except Exception as exc:
        issues.append(f"WOFF2 load failed: {exc}")

    # Audit glyph list
    audit_glyphs = get_audit_glyph_set(vf)
    # Capture default-master hole baseline for key holed Georgian & Latin glyphs
    key_holed = ["uni10D1", "uni10D1.case", "uni10D2", "uni10D2.case", "uni10D7", "uni10D7.case", "uni10DD", "uni10DD.case", "uni10ED", "A", "B", "O", "o", "e", "a", "zero", "eight", "ampersand.geor", "ampersand.geor.case"]
    base_holes = {}
    for g in key_holed:
        if g in vf.getGlyphOrder():
            _, nh, ha = audit_tt_glyph_geometry(vf, g)
            base_holes[g] = (nh, ha)

    # 2. Instantiate 8 non-master & extreme 3D coordinates (covering slnt 0, -4, -8, -12!) and audit EVERY glyph!
    coords_list = AUDIT_COORDS_IT if is_it else AUDIT_COORDS_UP
    inst_reports = []
    for wght_v, wdth_v, slnt_v, lbl in coords_list:
        inst = instantiateVariableFont(
            vf,
            {"wght": float(wght_v), "wdth": float(wdth_v), "slnt": float(slnt_v)},
            inplace=False,
            static=True,
        )
        coord_issues = []
        for g in audit_glyphs:
            g_iss, nh, ha = audit_tt_glyph_geometry(inst, g)
            coord_issues.extend(g_iss)
            if g in base_holes and base_holes[g][0] > 0:
                if nh < base_holes[g][0]:
                    coord_issues.append(f"{g}: hole collapsed ({base_holes[g][0]} -> {nh})")
                elif ha < base_holes[g][1] * 0.08:
                    coord_issues.append(f"{g}: hole nearly crushed ({ha:.0f} vs base {base_holes[g][1]:.0f})")

        # Exact slant angle check on 'I'
        meas_slnt = measure_I_slant_deg(inst)
        if abs(meas_slnt - slnt_v) > 0.45:
            coord_issues.append(f"Slant angle mismatch: measured={meas_slnt:+.2f}°, expected={slnt_v:+.2f}°")

        # Variable kerning check
        kq = FastKernQuerier(inst)
        k_zhr = kq.get_kern("uni10DF", "uni10E0")
        k_av = kq.get_kern("A", "V")
        k_to = kq.get_kern("T", "o")

        # avar stem accuracy check at Light (300) and Medium (500) at default slnt
        stem_info = {}
        exp_def_s = SLNT_DEFAULT_IT if is_it else SLNT_DEFAULT_UP
        if wght_v in (300, 500) and wdth_v == 100.0 and abs(slnt_v - exp_def_s) < 1e-3:
            wsuf = ("LightItalic" if is_it else "Light") if wght_v == 300 else ("MediumItalic" if is_it else "Medium")
            ref_static = TTFont(master_otf_path(otf_dir, "", wsuf, rounded))
            m_inst = measure_I_stem_width(inst)
            m_stat = measure_I_stem_width(ref_static)
            adv_inst_H = inst["hmtx"]["H"][0]
            adv_stat_H = ref_static["hmtx"]["H"][0]
            err_pct = (m_inst - m_stat) / max(m_stat, 1.0) * 100.0
            stem_info = {
                "inst_stem": round(m_inst, 2),
                "static_stem": round(m_stat, 2),
                "stem_err_pct": round(err_pct, 2),
                "advH_inst": adv_inst_H,
                "advH_static": adv_stat_H,
            }
            if abs(err_pct) > 2.5:
                coord_issues.append(f"avar stem error at {lbl}: {err_pct:+.2f}% ({m_inst:.1f} vs {m_stat:.1f})")
            ref_static.close()

        # FreeType render smoke test on instantiated TTF
        with tempfile.NamedTemporaryFile(suffix=".ttf", delete=True) as tf:
            inst.save(tf.name)
            try:
                pil_f = ImageFont.truetype(tf.name, 48)
                im = Image.new("L", (900, 80), 255)
                ImageDraw.Draw(im).text((10, 12), "თბილისი ᲑᲗ ჟრ Tbilisi ДЖЦЩ ₾₯ ±∞", font=pil_f, fill=0)
                ink = int(np.sum(np.array(im) < 200))
                if ink < 1200:
                    coord_issues.append(f"FreeType render blank/tiny ({ink} px)")
            except Exception as exc:
                coord_issues.append(f"FreeType render failed: {exc}")

        inst.close()
        inst_reports.append({
            "coord": lbl,
            "wght": wght_v,
            "wdth": wdth_v,
            "slnt": slnt_v,
            "measured_slnt": round(meas_slnt, 2),
            "audited_glyphs": len(audit_glyphs),
            "issues_count": len(coord_issues),
            "issues_sample": coord_issues[:10],
            "kern_zh_r": k_zhr,
            "kern_AV": k_av,
            "kern_To": k_to,
            "avar_check": stem_info,
        })
        if coord_issues:
            issues.extend([f"[{lbl}] {x}" for x in coord_issues[:5]])

    vf.close()
    print(f"  Audit [{vf_key}]: {len(audit_glyphs)} glyphs x {len(coords_list)} 3D coords -> total issues: {len(issues)}")
    for ir in inst_reports:
        extra = f" | avar={ir['avar_check']}" if ir["avar_check"] else ""
        print(
            f"    {ir['coord']:18s}: iss={ir['issues_count']:2d} | slnt={ir['measured_slnt']:+6.2f}° (exp {ir['slnt']:+5.1f}°) | kern(ჟრ={ir['kern_zh_r']:+3d}, AV={ir['kern_AV']:+3d}, To={ir['kern_To']:+3d}){extra}"
        )
        for s in ir["issues_sample"][:3]:
            print(f"       ! {s}")

    return {
        "vf_key": vf_key,
        "audited_glyphs_per_coord": len(audit_glyphs),
        "total_issues": len(issues),
        "issues_sample": issues[:20],
        "instances": inst_reports,
    }


# ---------------------------------------------------------------------------
# High-Resolution Visual Interpolation Proof Sheet
# ---------------------------------------------------------------------------

def render_vf_interpolation_proof(out_dir, proof_dir):
    """
    Render proofs/varfont_dev/vf_interpolation_proof.png showcasing:
      1. Smooth continuous 11-stop `wght` ramp (100..900) at non-master width wdth=93
      2. Smooth continuous 7-stop `wdth` ramp (75..115) at non-master weight wght=550
      3. Smooth continuous 7-stop `slnt` ramp (0 -> -12 deg) comparing Upright Oblique
         side-by-side with True Cursive Italic (0 deg Upright Cursive -> -8 deg Native -> -12 deg Steep!)
      4. All 4 Variable Fonts at tricky non-master 3D coordinates (wght x wdth x slnt)
      5. Close-up magnified 100px micro-geometry spotlight across 3D coordinates
      6. Official L1.07b Mtavruli & live calt Georgian Ampersand
      7. Razor-Sharp vs Rounded Wide-Wing Keycaps (⇦ ⇧ ⇨ ⇩ ⇪ ⏎ ⌫)
    """
    os.makedirs(proof_dir, exist_ok=True)
    out_path = os.path.join(proof_dir, "vf_interpolation_proof.png")

    W, H = 2600, 5050
    img = Image.new("RGB", (W, H), (250, 250, 248))
    draw = ImageDraw.Draw(img)

    # Load all 4 VFs via Pillow FreeType (supports set_variation_by_axes!)
    vf_paths = {k: os.path.join(out_dir, f"{VF_SPECS[k]['out_stem']}.ttf") for k in VF_ORDER}
    _vf_probe = TTFont(vf_paths["sharp_upright"])
    _vf_cmap = _vf_probe.getBestCmap()
    has_geor_amp = (0xE0A0 in _vf_cmap and 0xE0A1 in _vf_cmap)
    _vf_probe.close()

    def load_at(vf_key, size, wght, wdth, slnt=None):
        pf = ImageFont.truetype(vf_paths[vf_key], size)
        axes_info = pf.get_variation_axes()
        vals = []
        for ax in axes_info:
            nm = ax.get("name", b"")
            if isinstance(nm, bytes):
                nm = nm.decode("utf-8", errors="ignore")
            nml = nm.lower()
            if "width" in nml:
                vals.append(float(wdth))
            elif "weight" in nml:
                vals.append(float(wght))
            elif "slant" in nml:
                vals.append(float(ax.get("default", 0) if slnt is None else slnt))
            else:
                vals.append(float(ax.get("default", 0)))
        pf.set_variation_by_axes(vals)
        return pf

    # Use BatumiSans-VF itself for UI labels so Georgian, arrows (→), Greek & symbols never render tofu!
    ui_title = load_at("sharp_upright", 34, 700, 100.0, 0.0)
    ui_bold = load_at("sharp_upright", 21, 700, 100.0, 0.0)
    ui_sm = load_at("sharp_upright", 16, 400, 100.0, 0.0)

    y = 36
    draw.text((48, y), "ბათუმი სანსი · Batumi Sans — 3-Axis Variable Font Continuous Interpolation Proof (wght 100–900 × wdth 75–115 × slnt 0°..−12°)", font=ui_title, fill=(20, 22, 26))
    y += 46
    draw.text((48, y), "All 4 VFs: BatumiSans-VF · BatumiSans-Italic-VF · BatumiSansRounded-VF · BatumiSansRounded-Italic-VF   |   Native Cmd+I STAT ital Format 3 + slnt   |   L1.07b Mtavruli & 0° Upright Georgian Ampersand", font=ui_sm, fill=(95, 100, 110))
    y += 38
    draw.line([(48, y), (W - 48, y)], fill=(215, 218, 224), width=2)
    y += 24

    # Section 1: Continuous Weight Ramp (11 stops, non-master wdth=93) — Sharp Upright & Rounded Italic side-by-side
    draw.text((48, y), "1. CONTINUOUS WEIGHT RAMP (wght 100 → 900 at non-master wdth=93.0)   —   Left: Batumi Sans (Sharp)   |   Right: Batumi Sans Rounded Italic", font=ui_bold, fill=(30, 50, 90))
    y += 36
    ramp_weights = [100, 175, 250, 325, 400, 475, 550, 625, 700, 800, 900]
    sample_L = "ბათუმი ᲑᲗ ჟრ გმვ ₾₯ „ქართული“ AaBbGg"
    sample_R = "თბილისი ᲑᲗ ჟრ გმვ ₾₯ «საქართველო» ДЖЦЩ"
    for wv in ramp_weights:
        tag = f"wght={wv:3d}" + (" *" if wv not in (100, 400, 700, 900) else " M")
        draw.text((48, y + 10), tag, font=ui_sm, fill=(110, 115, 125))
        fL = load_at("sharp_upright", 36, wv, 93.0)
        fR = load_at("rounded_italic", 36, wv, 93.0)
        draw.text((160, y), sample_L, font=fL, fill=(18, 20, 24))
        draw.text((1370, y), sample_R, font=fR, fill=(18, 20, 24))
        y += 50

    y += 18
    draw.line([(48, y), (W - 48, y)], fill=(215, 218, 224), width=2)
    y += 24

    # Section 2: Continuous Width Ramp (7 stops, non-master wght=550) — Sharp Upright & Rounded Upright
    draw.text((48, y), "2. CONTINUOUS WIDTH RAMP (wdth 75 → 115 at non-master wght=550, Official L1.07b Mtavruli)   —   Left: Sharp   |   Right: Rounded", font=ui_bold, fill=(30, 50, 90))
    y += 36
    ramp_widths = [75.0, 81.0, 87.5, 93.0, 100.0, 108.0, 115.0]
    w_sample = "ᲔᲕᲠᲝᲞᲐ EUROPE · ბათუმი ₾120"
    for wdv in ramp_widths:
        tag = f"wdth={wdv:5.1f}" + (" *" if wdv not in (75.0, 87.5, 100.0, 115.0) else " M")
        draw.text((48, y + 10), tag, font=ui_sm, fill=(110, 115, 125))
        fL = load_at("sharp_upright", 36, 550, wdv)
        fR = load_at("rounded_upright", 36, 550, wdv)
        draw.text((175, y), w_sample, font=fL, fill=(18, 20, 24))
        draw.text((1380, y), w_sample, font=fR, fill=(18, 20, 24))
        y += 50

    y += 18
    draw.line([(48, y), (W - 48, y)], fill=(215, 218, 224), width=2)
    y += 24

    # Section 3: NEW! Continuous Slant Ramp (slnt 0° -> -12°) — Upright Oblique vs True Cursive Italic (0° Upright Cursive -> -12° Steep Cursive!)
    draw.text((48, y), "3. CONTINUOUS SLANT RAMP (slnt 0° → −12° at wght=550, wdth=96)   —   Left: Upright VF (0°..−12° Oblique)   |   Right: True Cursive Italic VF (0° Upright Cursive → −8° Native → −12° Steep)", font=ui_bold, fill=(140, 35, 30))
    y += 36
    ramp_slants = [0.0, -2.0, -4.0, -6.0, -8.0, -10.0, -12.0]
    sl_sample_L = "ᲔᲕᲠᲝᲞᲐ EUROPE · დოლჩე & გაბანა · Დ & Ბ"
    sl_sample_R = "ქვევრი & ღვინო · დლრწ agf · Ქ & Ღ · ₾"
    for slv in ramp_slants:
        note = " 0° Up/Cursive" if slv == 0.0 else (" −8° Native It" if slv == -8.0 else (" −12° Steep" if slv == -12.0 else ""))
        tag = f"slnt={slv:+5.1f}°"
        draw.text((48, y + 10), tag, font=ui_sm, fill=(140, 50, 35) if slv in (0.0, -8.0, -12.0) else (110, 115, 125))
        fL = load_at("sharp_upright", 36, 550, 96.0, slv)
        fR = load_at("sharp_italic", 36, 550, 96.0, slv)
        draw.text((195, y), sl_sample_L, font=fL, fill=(18, 20, 24))
        draw.text((1385, y), sl_sample_R, font=fR, fill=(18, 20, 24))
        if note:
            draw.text((2390, y + 10), note.strip(), font=ui_sm, fill=(140, 50, 35))
        y += 50

    y += 18
    draw.line([(48, y), (W - 48, y)], fill=(215, 218, 224), width=2)
    y += 24

    # Section 4: All 4 VFs across 6 Tricky Non-Master & Corner 3D Coordinates (wght x wdth x slnt!)
    draw.text((48, y), "4. ALL 4 VARIABLE FONTS AT TRICKY 3D NON-MASTER & EXTREME CORNER COORDINATES (wght × wdth × slnt)", font=ui_bold, fill=(30, 50, 90))
    y += 38
    tricky = [
        (250, 81.0,  -4.0,  "sharp_upright",   "Sharp Upright   (wght=250, wdth=81, slnt=-4°)"),
        (550, 93.0,  -8.0,  "sharp_italic",    "Sharp Italic    (wght=550, wdth=93, slnt=-8°)"),
        (650, 108.0, -8.0,  "rounded_upright", "Rounded Upright (wght=650, wdth=108, slnt=-8° Oblique)"),
        (820, 79.0, -12.0,  "rounded_italic",  "Rounded Italic  (wght=820, wdth=79, slnt=-12° Steep Cursive)"),
        (700, 115.0,  0.0,  "rounded_italic",  "Rounded Italic  (wght=700, wdth=115, slnt=0° Upright Cursive!)"),
        (900, 75.0, -12.0,  "sharp_upright",   "Sharp Upright   (wght=900, wdth=75, slnt=-12° Steep Oblique)"),
    ]
    full_line = "თ Თ Ბ ჟრ გ Გ მ Მ ვ ლ დ უ ჭ $¢£¤¥฿₡₦₩₪₫€₯₴₹₺₽₾ ؋ „ქართული“ «ABC» AaBbGg ДЖЦЩ ΑΔΛΣΦΨΩ αβγλφψω ±×÷≠≤∞√∑"
    for wv, wdv, slv, vk, lbl in tricky:
        draw.text((48, y), lbl, font=ui_sm, fill=(120, 60, 30))
        y += 24
        pf = load_at(vk, 34, wv, wdv, slv)
        draw.text((48, y), full_line, font=pf, fill=(15, 18, 22))
        y += 56

    y += 18
    draw.line([(48, y), (W - 48, y)], fill=(215, 218, 224), width=2)
    y += 24

    # Section 5: High-Magnification (100px) Micro-Geometry Spotlight on Critical Glyphs
    amp_hdr = " \ue0a0 \ue0a1" if has_geor_amp else ""
    draw.text((48, y), f"5. HIGH-MAGNIFICATION (100px) MICRO-GEOMETRY SPOTLIGHT — თ Ბ ჟრ გ Გ მ Მ ვ ₾ A g Д Ω φ{amp_hdr} (Zero Kinks / Zero Twists)", font=ui_bold, fill=(30, 50, 90))
    y += 42
    micro_str = "თ  Ბ  ჟრ  გ  Გ  მ  Მ  ვ  ₾  A  g  Д  Ω  φ" + ("  \ue0a0  \ue0a1" if has_geor_amp else "")
    spotlights = [
        ("sharp_upright",   550, 93.0,  -6.0, "Sharp Upright   (wght=550, wdth=93, slnt=-6° mid-slant)"),
        ("sharp_italic",    820, 79.0, -12.0, "Sharp Italic    (wght=820, wdth=79, slnt=-12° — uni10D7, ჟრ & steep ampersand stress test!)"),
        ("rounded_upright", 650, 108.0, -8.0, "Rounded Upright (wght=650, wdth=108, slnt=-8° — Ბ finial, rounded Greek & oblique ampersand!)"),
        ("rounded_italic",  820, 79.0,   0.0, "Rounded Italic  (wght=820, wdth=79, slnt=0° — Upright Cursive tight counters!)"),
        ("rounded_upright", 250, 81.0,  -4.0, "Rounded Upright (wght=250, wdth=81, slnt=-4° — light narrow terminals!)"),
    ]
    for vk, wv, wdv, slv, lbl in spotlights:
        draw.text((48, y), lbl, font=ui_sm, fill=(90, 95, 105))
        y += 24
        pf = load_at(vk, 96, wv, wdv, slv)
        draw.text((48, y), micro_str, font=pf, fill=(12, 14, 18))
        y += 134

    y += 14
    draw.line([(48, y), (W - 48, y)], fill=(215, 218, 224), width=2)
    y += 24

    # Section 6: Official L1.07b Mtavruli & Live calt 1:1 Original + Caps B Georgian Ampersand Continuous Interpolation
    draw.text((48, y), "6. OFFICIAL L1.07b MTAVRULI (±44.5u / -14u CapH) & 0° UPRIGHT 1:1 ORIGINAL + CAPS B GEORGIAN AMPERSAND (live calt, All-Caps, Latin & untouched და)", font=ui_bold, fill=(30, 50, 90))
    y += 38
    amp_line = "დოლჩე & გაბანა  ·  ᲓᲝᲚᲩᲔ & ᲒᲐᲑᲐᲜᲐ  ·  ᲔᲕᲠᲝᲞᲐ EUROPE  ·  Dolce & Gabbana  ·  ბათუმი და თბილისი"
    amp_rows = [
        ("sharp_upright",   250, 81.0,   0.0, "Sharp Upright   (wght=250, wdth=81, slnt=0°)"),
        ("sharp_upright",   550, 100.0, -6.0, "Sharp Upright   (wght=550, wdth=100, slnt=-6°)"),
        ("sharp_italic",    700, 93.0,  -8.0, "Sharp Italic    (wght=700, wdth=93, slnt=-8°)"),
        ("rounded_upright", 650, 108.0,  0.0, "Rounded Upright (wght=650, wdth=108, slnt=0°)"),
        ("rounded_italic",  820, 79.0, -12.0, "Rounded Italic  (wght=820, wdth=79, slnt=-12°)"),
        ("rounded_upright", 900, 75.0,  -8.0, "Rounded Upright (wght=900, wdth=75, slnt=-8° — XCon Heavy Oblique!)"),
    ]
    for vk, wv, wdv, slv, lbl in amp_rows:
        draw.text((48, y), lbl, font=ui_sm, fill=(120, 60, 30))
        y += 24
        pf = load_at(vk, 40, wv, wdv, slv)
        draw.text((48, y), amp_line, font=pf, fill=(15, 18, 22))
        y += 62

    y += 14
    draw.line([(48, y), (W - 48, y)], fill=(215, 218, 224), width=2)
    y += 24

    # Section 7: Razor-Sharp vs Rounded Wide-Wing Keycaps Continuous Interpolation Strip (⇦ ⇧ ⇨ ⇩ ⇪ ⏎ ⌫)
    draw.text((48, y), "7. RAZOR-SHARP vs ROUNDED WIDE-WING KEYCAP INTERPOLATION (⇦ ⇧ ⇨ ⇩ ⇪ ⏎ ⌫) — Sharp & Rounded × 3D Coordinates", font=ui_bold, fill=(30, 50, 90))
    y += 38
    kc_str = "⇦  ⇧  ⇨  ⇩  ⇪  ⏎  ⌫"
    kc_rows = [
        ("sharp_upright",   250, 81.0,   0.0, "Sharp Upright   (250, 81, 0°)"),
        ("sharp_upright",   550, 100.0, -6.0, "Sharp Upright   (550, 100, -6°)"),
        ("sharp_italic",    820, 79.0,  -8.0, "Sharp Italic    (820, 79, -8°)"),
        ("rounded_upright", 250, 81.0,   0.0, "Rounded Upright (250, 81, 0°)"),
        ("rounded_upright", 650, 108.0, -8.0, "Rounded Upright (650, 108, -8°)"),
        ("rounded_italic",  820, 79.0, -12.0, "Rounded Italic  (820, 79, -12°)"),
    ]
    for idx_r in range(0, len(kc_rows), 2):
        vk1, w1, wd1, sl1, lbl1 = kc_rows[idx_r]
        vk2, w2, wd2, sl2, lbl2 = kc_rows[idx_r + 1]
        draw.text((48, y), lbl1, font=ui_sm, fill=(90, 95, 105))
        draw.text((1340, y), lbl2, font=ui_sm, fill=(90, 95, 105))
        y += 24
        pf1 = load_at(vk1, 76, w1, wd1, sl1)
        pf2 = load_at(vk2, 76, w2, wd2, sl2)
        draw.text((48, y), kc_str, font=pf1, fill=(14, 16, 20))
        draw.text((1340, y), kc_str, font=pf2, fill=(14, 16, 20))
        y += 104

    # Crop cleanly to used height
    final_img = img.crop((0, 0, W, min(H, y + 40)))
    final_img.save(out_path)
    print(f"  Rendered visual proof: {out_path} ({final_img.size[0]}x{final_img.size[1]})")
    return out_path


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Build 4 true 3-axis Variable Fonts (wdth x wght x slnt) for Batumi Sans.")
    parser.add_argument("--vfs", default="all", help="Comma-separated VF keys or 'all' (" + ",".join(VF_ORDER) + ")")
    parser.add_argument("--otf-dir", default=os.path.join(BASE_DIR, "dist", "otf"))
    parser.add_argument("--out-dir", default=os.path.join(BASE_DIR, "dist", "variable"))
    parser.add_argument("--proof-dir", default=os.path.join(BASE_DIR, "proofs", "varfont_dev"))
    parser.add_argument("--workers", type=int, default=max(1, min(8, os.cpu_count() or 4)))
    parser.add_argument("--max-err", type=float, default=0.75)
    parser.add_argument("--skip-audit", action="store_true")
    parser.add_argument("--skip-proof", action="store_true")
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--proof-only", action="store_true")
    parser.add_argument("--patch-glyphs", default=None, help="Comma-separated glyph names to surgically patch into existing VFs")
    parser.add_argument("--patch-gpos-only", action="store_true", help="Fast surgical GPOS+GDEF VarStore rebuild across existing VFs without re-running gvar compilation")
    parser.add_argument("--add-khutsuri-to-vfs", action="store_true", help="Fast surgical splice of all 80 Georgian Khutsuri glyphs + HVAR + GPOS+GDEF into existing VFs")
    parser.add_argument("--add-expansion49-to-vfs", action="store_true", help="Fast surgical splice of all 49 expansion glyphs + Khutsuri calt + HVAR + GPOS+GDEF into existing VFs")
    parser.add_argument("--add-karagma-and-amp-to-vfs", action="store_true", help="Fast surgical splice of Option C ampersand.geor/.case + all 3 wavy Georgian Karagma marks + calt + HVAR + GPOS+GDEF into existing VFs (pruning removed glyphs)")
    parser.add_argument("--google-fonts", action="store_true", help="Build ONLY the 4 Google Fonts 2-axis [wdth,wght] VFs into google-fonts/ & dist/google-fonts/")
    parser.add_argument("--both-editions", action="store_true", help="Build BOTH 3-axis Creative VFs (dist/variable/) AND 2-axis Google Fonts VFs (google-fonts/ + dist/google-fonts/) sharing one alignment pass!")
    parser.add_argument("--gf-repo-dir", default=os.path.join(BASE_DIR, "google-fonts"))
    parser.add_argument("--gf-dist-dir", default=os.path.join(BASE_DIR, "dist", "google-fonts"))
    parser.add_argument("--report-path", default=None)
    args = parser.parse_args()

    build_creative = not args.google_fonts or args.both_editions
    build_gf = args.google_fonts or args.both_editions

    selected = list(VF_ORDER) if args.vfs == "all" else [k.strip() for k in args.vfs.split(",") if k.strip()]
    for k in selected:
        if k not in VF_SPECS:
            raise SystemExit(f"Unknown VF key {k!r}. Valid: {VF_ORDER}")

    t_all = time.time()
    report_path = args.report_path or os.path.join(args.out_dir, "vf_build_report.json")
    prev_builds = {}
    prev_audits = {}
    if os.path.exists(report_path):
        try:
            with open(report_path, "r", encoding="utf-8") as fp:
                old = json.load(fp)
            for b in old.get("builds", []):
                prev_builds[b["vf_key"]] = b
            for a in old.get("audits", []):
                prev_audits[a["vf_key"]] = a
        except Exception:
            pass

    if not args.proof_only:
        patch_list = [g.strip() for g in args.patch_glyphs.split(",") if g.strip()] if args.patch_glyphs else None
        for vf_key in selected:
            spec = VF_SPECS[vf_key]
            ttf_out = os.path.join(args.out_dir, f"{spec['out_stem']}.ttf")
            woff2_out = os.path.join(args.out_dir, f"{spec['out_stem']}.woff2")
            if args.add_karagma_and_amp_to_vfs:
                res = add_khutsuri_to_vfs(
                    vf_key,
                    args.otf_dir,
                    args.out_dir,
                    build_creative=build_creative,
                    build_google_fonts=build_gf,
                    gf_repo_dir=args.gf_repo_dir,
                    gf_dist_dir=args.gf_dist_dir,
                    max_err=args.max_err,
                    new_cps=KARAGMA_NEW_CPS,
                    new_glyph_names=("ampersand.geor", "ampersand.geor.case") + KARAGMA_GLYPH_NAMES,
                    label="KARAGMA+AMP-VF",
                    update_calt_khutsuri=True,
                    update_calt_karagma=True,
                )
                prev_builds[vf_key] = {**prev_builds.get(vf_key, {}), **res}
            elif args.add_expansion49_to_vfs:
                res = add_khutsuri_to_vfs(
                    vf_key,
                    args.otf_dir,
                    args.out_dir,
                    build_creative=build_creative,
                    build_google_fonts=build_gf,
                    gf_repo_dir=args.gf_repo_dir,
                    gf_dist_dir=args.gf_dist_dir,
                    max_err=args.max_err,
                    new_cps=EXPANSION_49_CPS,
                    new_glyph_names=EXPANSION_49_GLYPH_NAMES,
                    label="EXP49-VF",
                    update_calt_khutsuri=True,
                )
                prev_builds[vf_key] = {**prev_builds.get(vf_key, {}), **res}
            elif args.add_khutsuri_to_vfs:
                res = add_khutsuri_to_vfs(
                    vf_key,
                    args.otf_dir,
                    args.out_dir,
                    build_creative=build_creative,
                    build_google_fonts=build_gf,
                    gf_repo_dir=args.gf_repo_dir,
                    gf_dist_dir=args.gf_dist_dir,
                    max_err=args.max_err,
                )
                prev_builds[vf_key] = {**prev_builds.get(vf_key, {}), **res}
            elif args.patch_gpos_only:
                res = patch_gpos_in_vfs(
                    vf_key,
                    args.otf_dir,
                    args.out_dir,
                    build_creative=build_creative,
                    build_google_fonts=build_gf,
                    gf_repo_dir=args.gf_repo_dir,
                    gf_dist_dir=args.gf_dist_dir,
                )
                prev_builds[vf_key] = {**prev_builds.get(vf_key, {}), **res}
            elif patch_list:
                res = patch_glyphs_in_vf(vf_key, patch_list, args.otf_dir, args.out_dir, max_err=args.max_err)
                prev_builds[vf_key] = {**prev_builds.get(vf_key, {}), **res}
            elif not args.audit_only:
                res = build_single_vf(
                    vf_key,
                    args.otf_dir,
                    args.out_dir,
                    workers=args.workers,
                    max_err=args.max_err,
                    build_creative=build_creative,
                    build_google_fonts=build_gf,
                    gf_repo_dir=args.gf_repo_dir,
                    gf_dist_dir=args.gf_dist_dir,
                )
                prev_builds[vf_key] = res
            if build_creative and not args.skip_audit:
                ares = audit_variable_font(vf_key, ttf_out, woff2_out, args.otf_dir)
                prev_audits[vf_key] = ares

    css_path = write_variable_css(args.out_dir)
    print(f"\nWrote Variable Font CSS: {css_path}")

    proof_path = None
    if not args.skip_proof and all(os.path.exists(os.path.join(args.out_dir, f"{VF_SPECS[k]['out_stem']}.ttf")) for k in VF_ORDER):
        proof_path = render_vf_interpolation_proof(args.out_dir, args.proof_dir)

    build_results = [prev_builds[k] for k in VF_ORDER if k in prev_builds]
    audit_results = [prev_audits[k] for k in VF_ORDER if k in prev_audits]
    report = {
        "total_elapsed_s": round(time.time() - t_all, 2),
        "css_path": css_path,
        "proof_path": proof_path,
        "builds": build_results,
        "audits": audit_results,
        "total_audit_issues": sum(a["total_issues"] for a in audit_results),
    }
    with open(report_path, "w", encoding="utf-8") as fp:
        json.dump(report, fp, indent=2)
    print(f"Wrote build report: {report_path}")
    print(f"\n=== ALL DONE in {report['total_elapsed_s']}s | Total Audit Issues: {report['total_audit_issues']} ===")
    if report["total_audit_issues"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

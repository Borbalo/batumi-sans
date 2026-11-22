#!/usr/bin/env python3
"""
Independent Foundry-Grade QA Geometry & Metrology Library for Batumi Sans.
Zero shared math with src/condenser.py or src/rounder.py.

Provides:
- Independent outline extraction (CFF cubic & TrueType quadratic) -> dense polylines & skia-pathops Path
- Ray-casting vertical stem width & horizontal bar thickness metrology (Upright & Italic)
- Linear-regression slant angle estimation on straight stems (verifies exact -8.0 deg Italic!)
- Multi-arch counter openness & minimum bottleneck scanner
- Topological winding verification (OTF: outer CCW + / inner CW -; TTF: outer CW - / inner CCW +)
- skia-pathops self-intersection & debris contour detection
- Curvature spike / short-stub pinch detector for Rounded variants
- High-resolution diagnostic proof rendering (filled + outline + guide overlays)
"""

import math
import os
import unicodedata
import numpy as np
import pathops
from fontTools.ttLib import TTFont
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.boundsPen import BoundsPen
from PIL import Image, ImageDraw, ImageFont

MKH_MODERN = "აბგდევზთიკლმნოპჟრსტუფქღყშჩცძწჭხჯჰ"
MTV_MODERN = "ᲐᲑᲒᲓᲔᲕᲖᲗᲘᲙᲚᲛᲜᲝᲞᲟᲠᲡᲢᲣᲤᲥᲦᲧᲨᲩᲪᲫᲬᲭᲮᲯᲰ"
ARCHAIC_MKH = ["uni10F1", "uni10F2", "uni10F3", "uni10F4", "uni10F5", "uni10F6",
               "uni10F7", "uni10F8", "uni10F9", "uni10FA", "uni10FB", "uni10FC",
               "uni10FD", "uni10FE", "uni10FF"]
SS01_GLYPHS = ["uni10E2.ss01", "uni10E8.ss01", "uni10EC.ss01", "uni10EF.ss01"]
CRITICAL_MULTI_ARCH = ["uni10DA", "uni10D3", "uni10E6", "uni10DD", "uni10E0",
                       "uni10D7", "uni10E2", "uni10E4", "uni10EC", "uni10ED",
                       "uni10DF", "uni10EF", "uni10DB", "uni10E8", "uni20BE"]
CRITICAL_HOOKS_LOOPS = ["uni10D2", "uni10D2.case", "uni10DB", "uni10DB.case",
                        "uni10D6", "uni10D6.case", "uni10ED", "uni10ED.case",
                        "uni10EF", "uni10EF.case", "uni10E2", "uni10E2.case",
                        "uni20BE"]
# Expected 46 Unicode Mtavruli codepoints that have .case counterparts in FiraGO
MTAVRULI_CODEPOINTS = list(range(0x1C90, 0x1CBB)) + list(range(0x1CBD, 0x1CC0))

# All 19 Unicode Sc currency signs present in FiraGO (#21)
CURRENCY_CODEPOINTS = [
    0x0024,  # $ dollar
    0x00A2,  # ¢ cent
    0x00A3,  # £ sterling
    0x00A4,  # ¤ currency
    0x00A5,  # ¥ yen
    0x060B,  # ؋ uni060B (Afghani)
    0x0E3F,  # ฿ uni0E3F (Baht)
    0x20A1,  # ₡ colonmonetary
    0x20A6,  # ₦ uni20A6 (Naira)
    0x20A9,  # ₩ uni20A9 (Won)
    0x20AA,  # ₪ uni20AA (Sheqel)
    0x20AB,  # ₫ dong
    0x20AC,  # € Euro
    0x20AF,  # ₯ uni20AF (Drachma)
    0x20B4,  # ₴ uni20B4 (Hryvnia)
    0x20B9,  # ₹ uni20B9 (Rupee)
    0x20BA,  # ₺ uni20BA (Turkish Lira)
    0x20BD,  # ₽ uni20BD (Ruble)
    0x20BE,  # ₾ uni20BE (Lari)
]
CURRENCY_STRING_LTR = "$ ¢ £ ¤ ¥ ฿ ₡ ₦ ₩ ₪ ₫ € ₯ ₴ ₹ ₺ ₽ ₾ ؋"

# All 10 Georgian & European quotation marks (#24/#25/#27)
GEORGIAN_QUOTE_CODEPOINTS = [
    0x201E,  # „ quotedblbase (Georgian opening)
    0x201C,  # “ quotedblleft (Georgian closing)
    0x201D,  # ” quotedblright
    0x201A,  # ‚ quotesinglbase
    0x2018,  # ‘ quoteleft
    0x2019,  # ’ quoteright
    0x00AB,  # « guillemotleft
    0x00BB,  # » guillemotright
    0x2039,  # ‹ guilsinglleft
    0x203A,  # › guilsinglright
]
CRITICAL_ZHAR_PAIRS = [
    ("uni10DF", "uni10E0"),  # ჟრ
    ("uni10DF", "uni10E1"),  # ჟს
    ("uni10DF", "uni10D1"),  # ჟბ
    ("uni10DF", "uni10E9"),  # ჟჩ
]


def collect_quote_glyphs(font):
    """Return list of all 10 Georgian quotation mark glyph names present in font."""
    cm = font.getBestCmap()
    gset = set(font.getGlyphOrder())
    out = []
    for cp in GEORGIAN_QUOTE_CODEPOINTS:
        g = cm.get(cp)
        if g and g in gset and g not in out:
            out.append(g)
    return out


def collect_cyrillic_glyphs(font):
    """Return all Cyrillic glyphs (U+0400..U+052F + Cyrillic .locl/alternates) present in font."""
    cm = font.getBestCmap()
    gset = set(font.getGlyphOrder())
    out, seen = [], set()
    for cp in range(0x0400, 0x0530):
        g = cm.get(cp)
        if g and g in gset and g not in seen:
            seen.add(g)
            out.append(g)
    for g in font.getGlyphOrder():
        if g in seen:
            continue
        gl = g.lower()
        if (gl.startswith("afii10") or gl.startswith("uni04") or gl.startswith("uni050")
                or gl.startswith("uni051") or gl.startswith("uni052") or "cyrill" in gl):
            seen.add(g)
            out.append(g)
    return out


def collect_punctuation_glyphs(font):
    """Return all encoded Unicode Punctuation (category P*) glyphs in font."""
    cm = font.getBestCmap()
    gset = set(font.getGlyphOrder())
    out, seen = [], set()
    for cp, g in sorted(cm.items()):
        if g in gset and g not in seen:
            if unicodedata.category(chr(cp)).startswith("P"):
                seen.add(g)
                out.append(g)
    return out


def collect_math_arrow_glyphs(font):
    """Return all encoded Unicode Math (Sm) + Arrows/Technical (U+2190..U+23FF) glyphs in font."""
    cm = font.getBestCmap()
    gset = set(font.getGlyphOrder())
    out, seen = [], set()
    for cp, g in sorted(cm.items()):
        if g in gset and g not in seen:
            if unicodedata.category(chr(cp)) == "Sm" or (0x2190 <= cp <= 0x23FF):
                seen.add(g)
                out.append(g)
    return out


def collect_greek_glyphs(font):
    """Return all Greek & Coptic (U+0370..U+03FF) + Greek Extended (U+1F00..U+1FFF) + Greek alternates."""
    cm = font.getBestCmap()
    gset = set(font.getGlyphOrder())
    out, seen = [], set()
    for cp in list(range(0x0370, 0x0400)) + list(range(0x1F00, 0x2000)):
        g = cm.get(cp)
        if g and g in gset and g not in seen:
            seen.add(g)
            out.append(g)
    for g in font.getGlyphOrder():
        if g in seen:
            continue
        gl = g.lower()
        if gl.startswith("uni03") or gl.startswith("uni1f") or "greek" in gl or gl.endswith(".loclgrk"):
            seen.add(g)
            out.append(g)
    return out


def lookup_gpos_kern(font, g1, g2):
    """Return cumulative GPOS PairPos XAdvance adjustment for pair (g1, g2)."""
    if "GPOS" not in font:
        return 0
    gpos = font["GPOS"].table
    if not gpos.FeatureList or not gpos.LookupList:
        return 0
    kern_lks = set()
    for fr in gpos.FeatureList.FeatureRecord:
        if fr.FeatureTag == "kern":
            kern_lks.update(fr.Feature.LookupListIndex)
    total = 0
    for li in sorted(kern_lks):
        lk = gpos.LookupList.Lookup[li]
        if lk.LookupType not in (2, 9):
            continue
        matched = False
        for st in lk.SubTable:
            rst = st.ExtSubTable if lk.LookupType == 9 else st
            fmt = getattr(rst, "Format", None)
            if fmt == 1 and hasattr(rst, "PairSet"):
                cov = rst.Coverage.glyphs
                if g1 in cov:
                    idx = cov.index(g1)
                    for rec in rst.PairSet[idx].PairValueRecord:
                        if rec.SecondGlyph == g2:
                            if rec.Value1 and getattr(rec.Value1, "XAdvance", None):
                                total += rec.Value1.XAdvance
                            matched = True
                            break
            elif fmt == 2 and hasattr(rst, "Class1Record"):
                if g1 in rst.Coverage.glyphs:
                    c1 = rst.ClassDef1.classDefs.get(g1, 0)
                    c2 = rst.ClassDef2.classDefs.get(g2, 0)
                    if c1 < len(rst.Class1Record) and c2 < len(rst.Class1Record[c1].Class2Record):
                        rec = rst.Class1Record[c1].Class2Record[c2]
                        if rec.Value1 and getattr(rec.Value1, "XAdvance", None):
                            total += rec.Value1.XAdvance
                        matched = True
            if matched:
                break
    return total


def check_mtavruli_l107(font, is_italic=False):
    """
    Verify official L1.07b (±44.5u + -14.0u optical CapH tuck) micro-quadrilinear Mtavruli cues:
    - Flat CapH body Ა (uni10D0.case) sits ~-14.0u below Latin H (optical CapH tuck)
    - Პ (uni10DE.case), Რ (uni10E0.case), Ბ (uni10D1.case) ascend ~+44.5u over tucked flat body Ა
      (net ~+30.5u peak over Latin H!)
    - Კ (uni10D9.case), Ვ (uni10D5.case) descend ~-44.5u below baseline (plus round optical overshoot)
    - Ტ (uni10E2.case) ascends ~+23.0u over tucked CapH (+9u net over H + mast/overshoot) and descends ~-44.5u
    - Ჲ (uni10F2.case) compact height ~91.7% of tucked Ო height
    Returns (metrics_dict, issues_list).
    """
    issues = []
    gset = set(font.getGlyphOrder())
    req = ["H", "uni10D0.case", "uni10DD.case", "uni10DE.case", "uni10E0.case", "uni10D1.case",
           "uni10D9.case", "uni10D5.case", "uni10E2.case", "uni10F2.case"]
    bounds = {}
    for g in req:
        if g not in gset:
            issues.append(f"L1.07b missing {g}")
            return {}, issues
        b = poly_bounds(glyph_to_polylines(font, g, cubic_steps=16, quad_steps=12))
        if not b:
            issues.append(f"L1.07b empty bounds on {g}")
            return {}, issues
        bounds[g] = b

    # Use flat CapH from 'H' and tucked flat CapH from 'Ა' (uni10D0.case)
    h_y0, h_y1 = bounds["H"][1], bounds["H"][3]
    a_y1 = bounds["uni10D0.case"][3]
    o_y0, o_y1 = bounds["uni10DD.case"][1], bounds["uni10DD.case"][3]
    o_h = o_y1 - o_y0
    d_cap_tuck = a_y1 - h_y1
    d_pe_vs_a = bounds["uni10DE.case"][3] - a_y1
    d_pe_top = bounds["uni10DE.case"][3] - h_y1
    d_ra_top = bounds["uni10E0.case"][3] - h_y1
    d_ba_top = bounds["uni10D1.case"][3] - h_y1
    d_ka_bot = bounds["uni10D9.case"][1] - h_y0
    d_va_bot = bounds["uni10D5.case"][1] - h_y0
    d_ta_top = bounds["uni10E2.case"][3] - h_y1
    d_ta_bot = bounds["uni10E2.case"][1] - h_y0
    hi_h = bounds["uni10F2.case"][3] - bounds["uni10F2.case"][1]
    hi_ratio = hi_h / o_h if o_h > 0 else 0.0

    m = {
        "cap_tuck": round(d_cap_tuck, 1),
        "pe_vs_a": round(d_pe_vs_a, 1),
        "pe_top": round(d_pe_top, 1),
        "ra_top": round(d_ra_top, 1),
        "ba_top": round(d_ba_top, 1),
        "ka_bot": round(d_ka_bot, 1),
        "va_bot": round(d_va_bot, 1),
        "ta_top": round(d_ta_top, 1),
        "ta_bot": round(d_ta_bot, 1),
        "hi_pct": round(hi_ratio * 100.0, 1),
    }

    # Exact L1.07b (-14.0u flat CapH tuck + ±44.5u cues -> +30.5u net peak over Latin H)
    if not (-18.0 <= d_cap_tuck <= -10.0):
        issues.append(f"L1.07b Ა CapH tuck vs H={d_cap_tuck:+.1f}u (expected ~-14.0u)")
    if not (39.0 <= d_pe_vs_a <= 50.0):
        issues.append(f"L1.07b Პ ascender over tucked Ა={d_pe_vs_a:+.1f}u (expected ~+44.5u)")
    if not (24.0 <= d_pe_top <= 39.0):
        issues.append(f"L1.07b Პ top delta vs H={d_pe_top:+.1f}u (expected ~+30.5u)")
    if not (20.0 <= d_ra_top <= 60.0):
        issues.append(f"L1.07b Რ top delta vs H={d_ra_top:+.1f}u (expected ~+30.5u+overshoot)")
    if not (24.0 <= d_ba_top <= 48.0):
        issues.append(f"L1.07b Ბ top delta vs H={d_ba_top:+.1f}u (expected ~+30.5u+finial)")
    if not (-76.0 <= d_ka_bot <= -34.0):
        issues.append(f"L1.07b Კ bot delta vs H={d_ka_bot:+.1f}u (expected ~-44.5u-overshoot)")
    if not (-76.0 <= d_va_bot <= -34.0):
        issues.append(f"L1.07b Ვ bot delta vs H={d_va_bot:+.1f}u (expected ~-44.5u-overshoot)")
    if not (6.0 <= d_ta_top <= 56.0):
        issues.append(f"L1.07b Ტ top delta vs H={d_ta_top:+.1f}u (expected ~+9u net+mast)")
    if not (-76.0 <= d_ta_bot <= -34.0):
        issues.append(f"L1.07b Ტ bot delta vs H={d_ta_bot:+.1f}u (expected ~-44.5u-overshoot)")
    if not (0.86 <= hi_ratio <= 0.96):
        issues.append(f"L1.07b Ჲ height ratio={hi_ratio*100:.1f}% (expected ~91.7%)")

    return m, issues


def measure_pair_min_gap(font, g1, g2, num_slices=36):
    """
    Measure minimum horizontal white gap (in font units) between g1 and g2 when laid out
    at x2 = adv(g1) + GPOS_kern(g1, g2), scanning all overlapping y-heights.
    Negative values indicate ink overlap / collision!
    """
    gset = set(font.getGlyphOrder())
    if g1 not in gset or g2 not in gset:
        return None
    p1 = glyph_to_polylines(font, g1, cubic_steps=16, quad_steps=12)
    p2 = glyph_to_polylines(font, g2, cubic_steps=16, quad_steps=12)
    b1 = poly_bounds(p1)
    b2 = poly_bounds(p2)
    if not b1 or not b2:
        return None
    adv1 = font["hmtx"][g1][0]
    kern = lookup_gpos_kern(font, g1, g2)
    shift_x = adv1 + kern
    y_lo = max(b1[1], b2[1]) + 5.0
    y_hi = min(b1[3], b2[3]) - 5.0
    if y_hi <= y_lo:
        return None
    min_gap = 1e9
    for i in range(num_slices + 1):
        yt = y_lo + (i / num_slices) * (y_hi - y_lo)
        xs1 = slice_x_intersections(p1, yt)
        xs2 = slice_x_intersections(p2, yt)
        if xs1 and xs2:
            gap = (xs2[0] + shift_x) - xs1[-1]
            if gap < min_gap:
                min_gap = gap
    return None if min_gap > 1e8 else float(min_gap)


def collect_currency_glyphs(font):
    """Return list of all 19 currency glyphs (plus .tf/.osf variants if present)."""
    cm = font.getBestCmap()
    gset = set(font.getGlyphOrder())
    out = []
    seen = set()
    for cp in CURRENCY_CODEPOINTS:
        g = cm.get(cp)
        if g and g in gset and g not in seen:
            seen.add(g)
            out.append(g)
            for suf in (".tf", ".osf", ".tosf", ".sc"):
                vg = g + suf
                if vg in gset and vg not in seen:
                    seen.add(vg)
                    out.append(vg)
    return out


def collect_georgian_glyphs(font):
    """Return sorted list of all Georgian + Lari glyph names in a font."""
    gset = font.getGlyphOrder()
    out = []
    for g in gset:
        gl = g.lower()
        if any(k in gl for k in ("uni10d", "uni10e", "uni10f", "georgian", "uni20be")):
            out.append(g)
    return out


def _sample_cubic(p0, p1, p2, p3, steps=24):
    pts = []
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1.0 - t
        x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
        y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
        pts.append((x, y))
    return pts


def _sample_quad(p0, p1, p2, steps=16):
    pts = []
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1.0 - t
        x = mt**2 * p0[0] + 2 * mt * t * p1[0] + t**2 * p2[0]
        y = mt**2 * p0[1] + 2 * mt * t * p1[1] + t**2 * p2[1]
        pts.append((x, y))
    return pts


def recording_to_polylines(rec_value, cubic_steps=24, quad_steps=16):
    """Convert RecordingPen.value into closed dense polylines [(x,y), ...]."""
    contours = []
    cur = []
    cur_pt = None
    start_pt = None

    for op, args in rec_value:
        if op == "moveTo":
            if cur:
                if start_pt and cur[-1] != start_pt:
                    cur.append(start_pt)
                contours.append(cur)
            cur = [args[0]]
            cur_pt = start_pt = args[0]
        elif op == "lineTo":
            cur.append(args[0])
            cur_pt = args[0]
        elif op == "curveTo":
            cur.extend(_sample_cubic(cur_pt, args[0], args[1], args[2], steps=cubic_steps))
            cur_pt = args[2]
        elif op == "qCurveTo":
            pts = list(args)
            if pts[-1] is None:
                offs = pts[:-1]
                n = len(offs)
                st = ((offs[-1][0] + offs[0][0]) * 0.5, (offs[-1][1] + offs[0][1]) * 0.5)
                cur = [st]
                cur_pt = start_pt = st
                for i in range(n):
                    p2 = ((offs[i][0] + offs[(i + 1) % n][0]) * 0.5,
                          (offs[i][1] + offs[(i + 1) % n][1]) * 0.5)
                    cur.extend(_sample_quad(cur_pt, offs[i], p2, steps=quad_steps))
                    cur_pt = p2
            else:
                for i in range(len(pts) - 1):
                    p2 = pts[i + 1] if i == len(pts) - 2 else (
                        (pts[i][0] + pts[i + 1][0]) * 0.5,
                        (pts[i][1] + pts[i + 1][1]) * 0.5,
                    )
                    cur.extend(_sample_quad(cur_pt, pts[i], p2, steps=quad_steps))
                    cur_pt = p2
        elif op == "closePath":
            if cur:
                if start_pt and cur[-1] != start_pt:
                    cur.append(start_pt)
                contours.append(cur)
                cur = []
            cur_pt = start_pt = None

    if cur:
        if start_pt and cur[-1] != start_pt:
            cur.append(start_pt)
        contours.append(cur)
    return contours


def glyph_to_polylines(font, gname, cubic_steps=24, quad_steps=16):
    """Extract dense closed polylines from any OTF or TTF glyph."""
    pen = RecordingPen()
    font.getGlyphSet()[gname].draw(pen)
    return recording_to_polylines(pen.value, cubic_steps=cubic_steps, quad_steps=quad_steps)


def glyph_to_pathops(font, gname):
    """Extract a skia-pathops Path directly from a TTFont glyph."""
    p = pathops.Path()
    font.getGlyphSet()[gname].draw(p.getPen())
    return p


def glyph_contour_paths(font, gname):
    """Extract individual skia-pathops Path per contour from a TTFont glyph."""
    pen = RecordingPen()
    font.getGlyphSet()[gname].draw(pen)
    paths = []
    cur_ops = []
    for op, args in pen.value:
        if op == "moveTo":
            if cur_ops:
                paths.append(_ops_to_path(cur_ops))
            cur_ops = [(op, args)]
        else:
            cur_ops.append((op, args))
            if op == "closePath":
                paths.append(_ops_to_path(cur_ops))
                cur_ops = []
    if cur_ops:
        paths.append(_ops_to_path(cur_ops))
    return paths


def _ops_to_path(ops):
    p = pathops.Path()
    pen = p.getPen()
    for op, args in ops:
        getattr(pen, op)(*args)
    return p


def poly_signed_area(poly):
    """Shoelace signed area in standard Y-up math coordinates: >0 = CCW, <0 = CW."""
    if len(poly) < 3:
        return 0.0
    area = 0.0
    for i in range(len(poly) - 1):
        x1, y1 = poly[i]
        x2, y2 = poly[i + 1]
        area += x1 * y2 - x2 * y1
    return 0.5 * area


def unslant_polylines(polys, italic_angle_deg):
    """Un-slant polylines by -italic_angle_deg (e.g. -8 deg -> shear by -tan(8 deg) in x)."""
    if abs(italic_angle_deg) < 1e-4:
        return polys
    # In OpenType, post.italicAngle is negative for rightward lean (e.g. -8.0).
    # Rightward lean means x_italic = x_upright + y * tan(+8 deg).
    # So to un-slant back to upright: x_upright = x_italic - y * tan(-italic_angle_deg).
    k = math.tan(math.radians(-italic_angle_deg))
    return [[(x - y * k, y) for (x, y) in poly] for poly in polys]


def slice_x_intersections(polys, y_target):
    """Sorted list of x coordinates where horizontal line y=y_target crosses polylines."""
    xs = []
    for poly in polys:
        for i in range(len(poly) - 1):
            (x1, y1), (x2, y2) = poly[i], poly[i + 1]
            if (y1 <= y_target < y2) or (y2 <= y_target < y1):
                t = (y_target - y1) / (y2 - y1)
                xs.append(x1 + t * (x2 - x1))
    xs.sort()
    return xs


def slice_y_intersections(polys, x_target):
    """Sorted list of y coordinates where vertical line x=x_target crosses polylines."""
    ys = []
    for poly in polys:
        for i in range(len(poly) - 1):
            (x1, y1), (x2, y2) = poly[i], poly[i + 1]
            if (x1 <= x_target < x2) or (x2 <= x_target < x1):
                t = (x_target - x1) / (x2 - x1)
                ys.append(y1 + t * (y2 - y1))
    ys.sort()
    return ys


def poly_bounds(polys):
    xs = [p[0] for poly in polys for p in poly]
    ys = [p[1] for poly in polys for p in poly]
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def measure_stem_slant_angle(polys, y_fracs=(0.22, 0.32, 0.42, 0.52, 0.62, 0.72), edge_index=0):
    """
    Estimate actual stem slant angle (in OpenType convention: negative = leaning right)
    via linear regression of x(y) along a straight stem edge (or midpoint of first stem pair).
    Returns angle in degrees (e.g. -8.0) or None if inconsistent intersections.
    """
    b = poly_bounds(polys)
    if not b:
        return None
    y0, y1 = b[1], b[3]
    ys_s, xs_s = [], []
    for frac in y_fracs:
        yt = y0 + frac * (y1 - y0)
        xs = slice_x_intersections(polys, yt)
        if len(xs) >= 2 and edge_index == "mid0":
            xs_s.append(0.5 * (xs[0] + xs[1]))
            ys_s.append(yt)
        elif isinstance(edge_index, int) and len(xs) > abs(edge_index):
            xs_s.append(xs[edge_index])
            ys_s.append(yt)
    if len(ys_s) < 4:
        return None
    # Fit x = m * y + c
    y_arr = np.array(ys_s)
    x_arr = np.array(xs_s)
    m, c = np.polyfit(y_arr, x_arr, 1)
    resid = np.max(np.abs(x_arr - (m * y_arr + c)))
    if resid > 8.0:
        return None
    # Rightward lean (m > 0) -> negative OpenType italicAngle
    return -math.degrees(math.atan(m))


def measure_latin_strokes(font, italic_angle=0.0):
    """Measure Latin vertical stem (I, H, n, o) and horizontal bar (O, o, H) normalized to 1000 UPM."""
    cm = font.getBestCmap()
    scale = 1000.0 / font["head"].unitsPerEm
    res = {}

    def get_up(ch):
        g = cm.get(ord(ch))
        if not g:
            return None
        polys = glyph_to_polylines(font, g)
        return unslant_polylines(polys, italic_angle)

    # Vertical stem on 'I' (50%), 'H' (25% below crossbar), and 'n' (25% below arch)
    vstems = []
    for ch, yfrac in (("I", 0.50), ("H", 0.25), ("n", 0.25)):
        p = get_up(ch)
        if not p:
            continue
        b = poly_bounds(p)
        if not b:
            continue
        yt = b[1] + yfrac * (b[3] - b[1])
        xs = slice_x_intersections(p, yt)
        if len(xs) >= 2:
            w = (xs[1] - xs[0]) * scale
            res[f"v_{ch}"] = w
            vstems.append(w)

    # Oval 'o' and 'O' vertical flanks & horizontal top/bottom bars
    hbars = []
    for ch in ("O", "o"):
        p = get_up(ch)
        if not p:
            continue
        b = poly_bounds(p)
        if not b:
            continue
        xs = slice_x_intersections(p, 0.5 * (b[1] + b[3]))
        ys = slice_y_intersections(p, 0.5 * (b[0] + b[2]))
        if len(xs) >= 4:
            res[f"ov_{ch}"] = 0.5 * ((xs[1] - xs[0]) + (xs[-1] - xs[-2])) * scale
        if len(ys) >= 4:
            hb = 0.5 * ((ys[1] - ys[0]) + (ys[-1] - ys[-2])) * scale
            res[f"oh_{ch}"] = hb
            hbars.append(hb)

    # Slant check on 'I' and 'H' (raw, un-unslanted)
    slants = []
    for ch in ("I", "H"):
        g = cm.get(ord(ch))
        if g:
            ang = measure_stem_slant_angle(glyph_to_polylines(font, g), edge_index="mid0")
            if ang is not None:
                slants.append(ang)
    res["vstem_avg"] = float(np.mean(vstems)) if vstems else 0.0
    res["hbar_avg"] = float(np.mean(hbars)) if hbars else 0.0
    res["slant_deg"] = float(np.mean(slants)) if slants else 0.0
    return res


def measure_georgian_strokes(font, italic_angle=0.0):
    """
    Measure Georgian vertical stem width, horizontal bowl/arch thickness,
    and slant angle across canonical Mkhedruli & Mtavruli glyphs (normalized to 1000 UPM).
    """
    scale = 1000.0 / font["head"].unitsPerEm
    gset = set(font.getGlyphOrder())
    res = {}

    def get_up(gname):
        if gname not in gset:
            return None
        return unslant_polylines(glyph_to_polylines(font, gname), italic_angle)

    # 1. Straight vertical stems (left/right walls at mid-height of x-height/glyph)
    # ი (uni10D8): 2 vertical legs at y=35%
    # ს (uni10E1): left straight stem at y=60%
    # ნ (uni10DC): left stem at y=40%
    # ო (uni10DD): outer left/right stems at y=35%
    # Ი (uni10D8.case): 2 vertical legs at y=40%
    # Ო (uni10DD.case): outer stems at y=35%
    v_samples = {}
    stem_probes = [
        ("ი", "uni10D8", 0.35, 0),
        ("ს", "uni10E1", 0.65, 0),
        ("ნ", "uni10DC", 0.40, 0),
        ("ო", "uni10DD", 0.35, 0),
        ("მ", "uni10DB", 0.35, -1),  # rightmost stem
        ("Ი", "uni10D8.case", 0.40, 0),
        ("Ო", "uni10DD.case", 0.35, 0),
    ]
    for label, gname, yfrac, pair_idx in stem_probes:
        p = get_up(gname)
        if not p:
            continue
        b = poly_bounds(p)
        if not b:
            continue
        xs = slice_x_intersections(p, b[1] + yfrac * (b[3] - b[1]))
        if len(xs) >= 2:
            if pair_idx == 0:
                w = (xs[1] - xs[0]) * scale
            else:
                w = (xs[-1] - xs[-2]) * scale
            if 10 < w < 300:
                v_samples[label] = w

    # 2. Horizontal bars / arch crowns / bowl bottoms
    # ბ (uni10D1) bottom bowl at x=50%
    # ე (uni10D4) top/bottom bowl at x=50%
    # ი (uni10D8) top arch at x=50%
    # ნ (uni10DC) bottom bowl at x=50%
    # Ბ (uni10D1.case) bottom bowl at x=50%
    # Ე (uni10D4.case) top/bottom at x=50%
    h_samples = {}
    bar_probes = [
        ("ბ_bot", "uni10D1", 0.50, "bot"),
        ("ი_top", "uni10D8", 0.50, "top"),
        ("ე_bot", "uni10D4", 0.50, "bot"),
        ("ე_top", "uni10D4", 0.52, "top"),
        ("ნ_bot", "uni10DC", 0.50, "bot"),
        ("Ბ_bot", "uni10D1.case", 0.50, "bot"),
        ("Ი_top", "uni10D8.case", 0.50, "top"),
    ]
    for label, gname, xfrac, which in bar_probes:
        p = get_up(gname)
        if not p:
            continue
        b = poly_bounds(p)
        if not b:
            continue
        ys = slice_y_intersections(p, b[0] + xfrac * (b[2] - b[0]))
        if len(ys) >= 2:
            if which == "bot":
                h = (ys[1] - ys[0]) * scale
            else:
                h = (ys[-1] - ys[-2]) * scale
            if 10 < h < 300:
                h_samples[label] = h

    # 3. Slant angle on exact-vertical Georgian stems (0.00 deg upright, -8.00 deg italic)
    slants = []
    slant_probes = [
        ("uni10E1", (0.45, 0.55, 0.65, 0.75, 0.85), "mid0"),      # ს straight left stem
        ("uni10E5", (0.55, 0.65, 0.75, 0.85, 0.92), -1),          # ქ straight right ascender
        ("uni10EE", (0.45, 0.55, 0.65, 0.75, 0.85), 0),           # ხ straight left ascender edge
        ("uni10EB", (0.55, 0.65, 0.75, 0.85, 0.92), -1),          # ძ straight right ascender
        ("uni10DF", (0.55, 0.65, 0.75, 0.85, 0.92), -1),          # ჟ straight right stem
        ("uni10E1.case", (0.45, 0.55, 0.65, 0.75, 0.85), "mid0"), # Ს
        ("uni10EE.case", (0.45, 0.55, 0.65, 0.75, 0.85), 0),      # Ხ
        ("uni10E5.case", (0.55, 0.65, 0.75, 0.85, 0.92), -1),     # Ქ
        ("uni10EB.case", (0.55, 0.65, 0.75, 0.85, 0.92), -1),     # Ძ
    ]
    for gname, fracs, eidx in slant_probes:
        if gname in gset:
            ang = measure_stem_slant_angle(glyph_to_polylines(font, gname), y_fracs=fracs, edge_index=eidx)
            if ang is not None:
                slants.append(ang)

    res["v_samples"] = v_samples
    res["h_samples"] = h_samples
    res["vstem_avg"] = float(np.median(list(v_samples.values()))) if v_samples else 0.0
    res["hbar_avg"] = float(np.median(list(h_samples.values()))) if h_samples else 0.0
    res["slant_deg"] = float(np.median(slants)) if slants else 0.0
    res["slant_samples"] = slants
    return res


def scan_counter_openness(font, gname, italic_angle=0.0):
    """
    Scan horizontal slices across the main body (25%..75% height) of a glyph to measure
    interior counter widths (white gaps between solid ink runs: xs[2k+2] - xs[2k+1]).
    For multi-arch glyphs (ლ, დ, ღ, ო, რ, ტ, ფ, etc.), picks the interior slice that
    maximizes the minimum counter gap among slices with >= 2 ink runs (preferring the
    canonical arch-count run slices), avoiding false tiny gaps at arch grazing tips.
    """
    scale = 1000.0 / font["head"].unitsPerEm
    polys = unslant_polylines(glyph_to_polylines(font, gname), italic_angle)
    b = poly_bounds(polys)
    if not b:
        return {"min_gap": None, "max_gap": None, "max_runs": 0, "best_y_gaps": []}
    y0, y1 = b[1], b[3]
    # Collect slices in the interior body (25%..75%)
    by_runs = {}
    for i in range(5, 16):
        yt = y0 + (i / 20.0) * (y1 - y0)
        xs = slice_x_intersections(polys, yt)
        if len(xs) >= 4 and len(xs) % 2 == 0:
            runs = len(xs) // 2
            gaps = [(xs[2 * k + 2] - xs[2 * k + 1]) * scale for k in range(runs - 1)]
            by_runs.setdefault(runs, []).append(gaps)
    if not by_runs:
        return {"min_gap": None, "max_gap": None, "max_runs": 0, "best_y_gaps": []}
    # Pick the highest run count that appears in at least 2 slices (or max runs if only 1)
    multi = [r for r, lst in by_runs.items() if len(lst) >= 2]
    target_runs = max(multi) if multi else max(by_runs.keys())
    best_slice = max(by_runs[target_runs], key=lambda gs: min(gs))
    return {
        "min_gap": float(min(best_slice)),
        "max_gap": float(max(best_slice)),
        "max_runs": target_runs,
        "best_y_gaps": [round(g, 1) for g in best_slice],
    }


def audit_glyph_topology(font, gname, is_ttf=False):
    """
    Independent topological audit of a single glyph in OTF or TTF:
    1. Winding check via even-odd nesting depth:
       - OTF (CFF): depth even -> CCW (+area), depth odd -> CW (-area)
       - TTF (glyf): depth even -> CW (-area), depth odd -> CCW (+area)
    2. skia-pathops self-intersection check:
       - Compare abs(raw_path.area) vs abs(simplify(raw_path).area)
       - Check if simplify() creates unexpected extra debris contours
    Returns list of issue strings (empty = 100% clean).
    """
    issues = []
    cpaths = glyph_contour_paths(font, gname)
    if not cpaths:
        return issues

    polys = glyph_to_polylines(font, gname, cubic_steps=16, quad_steps=12)
    areas = [poly_signed_area(p) for p in polys]

    if len(cpaths) == len(polys):
        for i, (cp, poly, area) in enumerate(zip(cpaths, polys, areas)):
            if abs(area) < 5.0:
                issues.append(f"{gname} c{i}: degenerate zero-area contour (area={area:.1f})")
                continue
            # Pick a point on the contour to test strict containment in strictly LARGER contours
            pt = poly[0]
            depth = 0
            for j, other in enumerate(cpaths):
                if i != j and abs(areas[j]) > abs(area) and other.contains(pt):
                    depth += 1
            # In OTF: even depth => CCW (+area); in TTF: even depth => CW (-area)
            want_positive = (depth % 2 == 0) if not is_ttf else (depth % 2 == 1)
            is_positive = area > 0
            if want_positive != is_positive:
                fmt = "TTF" if is_ttf else "OTF"
                issues.append(
                    f"{gname} c{i}: {fmt} winding wrong (depth={depth}, area={area:.0f}, "
                    f"expected {'CCW+' if want_positive else 'CW-'})"
                )

    # Self-intersection check via skia-pathops
    raw_p = glyph_to_pathops(font, gname)
    raw_area = abs(raw_p.area)
    try:
        simp_p = pathops.simplify(raw_p, clockwise=is_ttf)
        simp_area = abs(simp_p.area)
    except Exception as exc:
        issues.append(f"{gname}: pathops.simplify failed: {exc}")
        return issues

    if raw_area > 50:
        rel_diff = abs(raw_area - simp_area) / raw_area
        if rel_diff > 0.015:
            issues.append(
                f"{gname}: self-intersection/overlap area delta {rel_diff*100:.2f}% "
                f"(raw={raw_area:.0f}, simp={simp_area:.0f})"
            )
        # Also check if simplifying produces MORE contours than raw (a signature of pinch-offs / bowtie loops!)
        raw_n = len(cpaths)
        simp_n = len(list(simp_p.contours))
        if simp_n > raw_n:
            issues.append(
                f"{gname}: pathops.simplify split contours ({raw_n} -> {simp_n}), probable self-intersection/pinch!"
            )

    return issues


def extract_holes_with_centroids(font, gname):
    """Return list of (abs_area, (cx, cy)) for every odd-depth interior hole contour of a glyph."""
    cpaths = glyph_contour_paths(font, gname)
    if len(cpaths) < 2:
        return []
    polys = glyph_to_polylines(font, gname, cubic_steps=12, quad_steps=10)
    if len(polys) != len(cpaths):
        return []
    areas = [abs(poly_signed_area(p)) for p in polys]
    holes = []
    for i, (cp, poly, area) in enumerate(zip(cpaths, polys, areas)):
        if area < 5.0:
            continue
        pt = poly[0]
        depth = sum(1 for j, other in enumerate(cpaths) if i != j and areas[j] > area and other.contains(pt))
        if depth % 2 == 1:
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            cx = 0.5 * (min(xs) + max(xs))
            cy = 0.5 * (min(ys) + max(ys))
            holes.append((area, (cx, cy)))
    return holes


def audit_hole_area_ratios(orig_font, new_font, gname, mode, weight_class=400):
    """
    Compare EVERY interior hole contour area between orig_font (Normal) and new_font.
    Catches twisted/pinched/collapsed counters (like Expanded BoldItalic uni10D7)!
    Returns list of issue strings.
    """
    issues = []
    h_orig = extract_holes_with_centroids(orig_font, gname)
    if not h_orig:
        return issues
    h_new = extract_holes_with_centroids(new_font, gname)
    if len(h_new) != len(h_orig):
        issues.append(f"{gname}: hole contour count changed {len(h_orig)} -> {len(h_new)}")
        return issues

    # Sort by (cy, cx) or match greedily by vertical/horizontal centroid order
    # Normalize x slightly by scale so centroids match cleanly
    s_est = {"condensed": 0.90, "extra_condensed": 0.83, "expanded": 1.15}.get(mode, 1.0)
    used = set()
    for hi, (ao, (cxo, cyo)) in enumerate(h_orig):
        if ao < 800.0:
            continue  # skip microscopic dot/inktrap holes
        best_j = None
        best_d = 1e18
        for j, (an, (cxn, cyn)) in enumerate(h_new):
            if j in used:
                continue
            d = (cxn - cxo * s_est) ** 2 + (cyn - cyo) ** 2
            if d < best_d:
                best_d = d
                best_j = j
        if best_j is None:
            continue
        used.add(best_j)
        an = h_new[best_j][0]
        ratio = an / ao
        if mode == "expanded":
            # In Expanded (~115% width), inner holes MUST open (never shrink!)
            if ratio < 1.02:
                issues.append(f"{gname} hole#{hi}: PINCHED in expanded (area {ao:.0f}->{an:.0f}, ratio={ratio:.3f} < 1.02)")
        elif mode == "condensed":
            min_r = 0.45 if weight_class >= 800 else 0.58 if weight_class >= 600 else 0.68
            if ratio < min_r:
                issues.append(f"{gname} hole#{hi}: COLLAPSED in condensed (area {ao:.0f}->{an:.0f}, ratio={ratio:.3f} < {min_r})")
        elif mode == "extra_condensed":
            min_r = 0.25 if weight_class >= 800 else 0.36 if weight_class >= 600 else 0.50
            if ratio < min_r:
                issues.append(f"{gname} hole#{hi}: COLLAPSED in extra_condensed (area {ao:.0f}->{an:.0f}, ratio={ratio:.3f} < {min_r})")
        if ratio > 2.30 and not (mode == "expanded" and ao < 2000.0):
            issues.append(f"{gname} hole#{hi}: BLOWN UP (area {ao:.0f}->{an:.0f}, ratio={ratio:.3f})")
    return issues


def draw_glyph_on_canvas(draw, polys, ox, oy, scale, fill=None, outline=None, width=1, upm=1000.0):
    """Draw polylines onto a PIL ImageDraw canvas (Y-up font coords -> Y-down image coords)."""
    # Note: for filled rendering with holes, use PIL mask or FreeType; this helper is for crisp vector overlays.
    for poly in polys:
        pts = [(ox + x * scale, oy - y * scale) for (x, y) in poly]
        if len(pts) >= 2:
            if outline:
                draw.line(pts, fill=outline, width=width)
            if fill and len(pts) >= 3:
                draw.polygon(pts, fill=fill)

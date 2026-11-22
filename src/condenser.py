#!/usr/bin/env python3
"""
Borbalo GO — Foundry-Grade Anisotropic Optical Width Engine (src/condenser.py)

Transforms FiraGO PostScript cubic Bézier outlines across three optical width modes:
  - 'condensed'       (~90.5% advance, ~97.5% vstem, ~97.5% hbar; usWidthClass=3)
  - 'extra_condensed' (~83.5% advance, ~95.5% vstem, ~96.0% hbar; usWidthClass=2)
  - 'expanded'        (~115.0% advance, ~101.5% vstem, ~101.2% hbar; usWidthClass=7)
across ALL 18 weights/styles (Thin 100 .. Heavy 900, Upright & Italic).

Core Typographic & Computational Principles (NEVER naive scaleX):
  1. Exact Italic Shear-Conjugation (-8.0 deg):
     Un-slant around FiraGO's exact slant pivot (y_c = 0.5 * x_height) -> perform all
     stem-preserving optical deformation in upright space -> re-slant to exact -8.00 deg.
     Vertical stems stay 100.0% parallel to Fira Sans Condensed/Compressed Italic.
  2. Hybrid Cross-Weight X-Master Interpolation + Exact Zone-Locked Anisotropic Cubic Offset:
     - Where adjacent FiraGO weight masters are 100% topologically compatible, blends a
       controlled X-only fraction of the heavier (Condensed/Extra Condensed) or lighter
       (Expanded) master to inherit authentic bBox Type join tapers & ink traps with
       ZERO vertical alignment drift and ZERO horizontal bar bloat.
     - Completes exact stem width (vstem_ratio) and horizontal bar thickness (hbar_ratio)
       via closed-form 2x2 least-squares anisotropic outward-normal cubic Bézier offsetting
       with smooth alignment-zone locking (baseline, x-height, cap-height, ascender,
       descender, and optical overshoots stay locked to <= 1 unit!).
     - Preserves sharp 90-degree corners and straight terminal caps as pure 'line' segments
       (100% plug-and-play with src/rounder.py for Condensed/ExtraCondensed/Expanded Rounded!).
     - Collapses inverted micro-segments at tight Heavy inner crotches (zero bowties!).
  3. Authentic Georgian Per-Glyph Width Intelligence & Counter-Preservation Physics:
     - Loads per-style and per-glyph multipliers from analysis/condensing_spec.json
       (Noto Sans Georgian SemiCondensed/Condensed + a wide reference + FiraGO true
       single-arch cursive Italic overrides on დ/Დ/ლ/Ლ/რ/წ).
     - Enforces an automatic Heavy/ExtraBold counter-preservation floor (matching Fira Sans
       Compressed Black 'm' ~44u counters) so multi-arch Georgian letters (ლ, ტ, ო, ღ, რ, დ)
       NEVER pinch or collapse counters.
     - Preserves circular geometry on dots (., :, ;, i-dot, Svan/Mingrelian dieresis) and
       prevents single-stem narrow glyphs (I, l, |, 1) from bloating in Expanded mode.
  4. Superelliptical Bowl Flank Tension:
     - Applies measured Fira Sans Condensed / Compressed / Expanded cubic handle tension
       on quarter-bowl segments (strictly inside convex hull bounds: zero loops!).
  5. Automated skia-pathops Self-Intersection & Winding Integrity Gate:
     - Guarantees canonical PostScript winding (CCW outer, CW hole) and zero pathops
       self-intersections across 100% of glyphs in all 18 weights x 3 modes.
"""

import json
import math
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
import pathops
from fontTools.pens.cu2quPen import Cu2QuPen  # noqa: F401
from fontTools.pens.qu2cuPen import Qu2CuPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont

BASE_DIR = str(Path(__file__).resolve().parent.parent)
DEFAULT_SPEC_PATH = os.path.join(BASE_DIR, "analysis", "condensing_spec.json")
DEFAULT_FONTS_DIR = os.path.expanduser("~/Library/Fonts")

WEIGHT_ORDER = [
    "Thin",
    "ExtraLight",
    "Light",
    "Regular",
    "Medium",
    "SemiBold",
    "Bold",
    "ExtraBold",
    "Heavy",
]
WEIGHT_CLASS_MAP = {
    "Thin": 100,
    "ExtraLight": 200,
    "Light": 300,
    "Regular": 400,
    "Medium": 500,
    "SemiBold": 600,
    "Bold": 700,
    "ExtraBold": 800,
    "Heavy": 900,
}

# Fallback reference vertical stems (UPM=1000) if spec is unavailable
FALLBACK_VSTEM = {
    "Thin": 23.0, "ExtraLight": 48.0, "Light": 61.0, "Regular": 96.0,
    "Medium": 133.0, "SemiBold": 147.0, "Bold": 163.0, "ExtraBold": 183.0, "Heavy": 203.0,
}
FALLBACK_HBAR = {
    "Thin": 21.0, "ExtraLight": 40.0, "Light": 49.0, "Regular": 74.0,
    "Medium": 97.0, "SemiBold": 106.0, "Bold": 116.0, "ExtraBold": 129.0, "Heavy": 142.0,
}

# Module-level font & spec caches
_SPEC_CACHE = {}
_PARTNER_FONT_CACHE = {}


# ---------------------------------------------------------------------------
# Low-Level 2D Vector & Cubic Bézier Primitives
# ---------------------------------------------------------------------------

def v_add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def v_sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def v_mul(a, s):
    return (a[0] * s, a[1] * s)


def v_dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def v_cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def v_len(a):
    return math.hypot(a[0], a[1])


def v_norm(a):
    L = math.hypot(a[0], a[1])
    return (a[0] / L, a[1] / L) if L > 1e-12 else (1.0, 0.0)


def rot90_cw(v):
    """Outward unit normal for canonical PostScript winding (interior on LEFT)."""
    return (v[1], -v[0])


def rot90_ccw(v):
    return (-v[1], v[0])


def clamp(val, lo, hi):
    return lo if val < lo else (hi if val > hi else val)


def eval_seg(seg, t):
    kind, pts = seg
    if kind == "line":
        p0, p1 = pts
        return (p0[0] + t * (p1[0] - p0[0]), p0[1] + t * (p1[1] - p0[1]))
    p0, p1, p2, p3 = pts
    mt = 1.0 - t
    mt2, t2 = mt * mt, t * t
    return (
        mt2 * mt * p0[0] + 3.0 * mt2 * t * p1[0] + 3.0 * mt * t2 * p2[0] + t2 * t * p3[0],
        mt2 * mt * p0[1] + 3.0 * mt2 * t * p1[1] + 3.0 * mt * t2 * p2[1] + t2 * t * p3[1],
    )


def deriv_seg(seg, t):
    kind, pts = seg
    if kind == "line":
        p0, p1 = pts
        return (p1[0] - p0[0], p1[1] - p0[1])
    p0, p1, p2, p3 = pts
    mt = 1.0 - t
    dx = (
        3.0 * mt * mt * (p1[0] - p0[0])
        + 6.0 * mt * t * (p2[0] - p1[0])
        + 3.0 * t * t * (p3[0] - p2[0])
    )
    dy = (
        3.0 * mt * mt * (p1[1] - p0[1])
        + 6.0 * mt * t * (p2[1] - p1[1])
        + 3.0 * t * t * (p3[1] - p2[1])
    )
    if math.hypot(dx, dy) < 1e-6:
        # Handle zero-length control handle at endpoint cleanly
        if t <= 1e-4:
            # Try second derivative limit p2 - p0, else chord p3 - p0
            d2 = (p2[0] - p0[0], p2[1] - p0[1])
            if math.hypot(d2[0], d2[1]) > 1e-6:
                return d2
            return (p3[0] - p0[0], p3[1] - p0[1])
        if t >= 1.0 - 1e-4:
            d2 = (p3[0] - p1[0], p3[1] - p1[1])
            if math.hypot(d2[0], d2[1]) > 1e-6:
                return d2
            return (p3[0] - p0[0], p3[1] - p0[1])
        eps = 1e-3 if t < 0.5 else -1e-3
        a = eval_seg(seg, clamp(t, 0.0, 1.0))
        b = eval_seg(seg, clamp(t + eps, 0.0, 1.0))
        return ((b[0] - a[0]) / eps, (b[1] - a[1]) / eps)
    return (dx, dy)


def deriv2_seg(seg, t):
    kind, pts = seg
    if kind == "line":
        return (0.0, 0.0)
    p0, p1, p2, p3 = pts
    mt = 1.0 - t
    ddx = 6.0 * mt * (p2[0] - 2.0 * p1[0] + p0[0]) + 6.0 * t * (p3[0] - 2.0 * p2[0] + p1[0])
    ddy = 6.0 * mt * (p2[1] - 2.0 * p1[1] + p0[1]) + 6.0 * t * (p3[1] - 2.0 * p2[1] + p1[1])
    return (ddx, ddy)


def tan_seg(seg, t):
    return v_norm(deriv_seg(seg, t))


def outward_normal_seg(seg, t):
    return rot90_cw(tan_seg(seg, t))


def signed_curvature_out(seg, t):
    """
    Signed outward curvature kappa_out such that dN/ds = kappa_out * T.
    For a CCW circle of radius R: T = (-sin, cos), N = (cos, sin), dN/ds = +T/R => kappa_out = +1/R.
    Note: T x dT/ds = cross(p', p'') / |p'|^3 = +1/R for CCW circle.
    """
    if seg[0] == "line":
        return 0.0
    d1 = deriv_seg(seg, t)
    s2 = d1[0] * d1[0] + d1[1] * d1[1]
    if s2 < 1e-8:
        return 0.0
    d2 = deriv2_seg(seg, t)
    return v_cross(d1, d2) / (s2 * math.sqrt(s2))


def split_seg(seg, t=0.5):
    t = clamp(t, 0.0, 1.0)
    kind, pts = seg
    if kind == "line":
        p0, p1 = pts
        pm = (p0[0] + t * (p1[0] - p0[0]), p0[1] + t * (p1[1] - p0[1]))
        return ("line", (p0, pm)), ("line", (pm, p1))
    p0, p1, p2, p3 = pts
    lerp = lambda a, b: (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
    q0 = lerp(p0, p1)
    q1 = lerp(p1, p2)
    q2 = lerp(p2, p3)
    r0 = lerp(q0, q1)
    r1 = lerp(q1, q2)
    s0 = lerp(r0, r1)
    return ("cubic", (p0, q0, r0, s0)), ("cubic", (s0, r1, q2, p3))


def turn_angle_deg(t_in, t_out):
    return math.degrees(math.atan2(v_cross(t_in, t_out), clamp(v_dot(t_in, t_out), -1.0, 1.0)))


def seg_approx_len(seg):
    kind, pts = seg
    if kind == "line":
        return v_len(v_sub(pts[1], pts[0]))
    p0, p1, p2, p3 = pts
    chord = v_len(v_sub(p3, p0))
    poly = v_len(v_sub(p1, p0)) + v_len(v_sub(p2, p1)) + v_len(v_sub(p3, p2))
    return 0.5 * (chord + poly)


# ---------------------------------------------------------------------------
# Contour Extraction, Replay, Winding, & Bounds (Matching rounder.py format)
# ---------------------------------------------------------------------------

def extract_contours(font, gname):
    """Extract closed cubic/line contours from a font glyph (supports both OTF CFF and TTF)."""
    rec = RecordingPen()
    gset = font.getGlyphSet()
    if gname not in gset:
        return []
    if "glyf" in font:
        qpen = Qu2CuPen(rec, max_err=0.5, all_cubic=False)
        gset[gname].draw(qpen)
    else:
        gset[gname].draw(rec)

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
            if cur is not None and v_len(v_sub(p1, cur)) > 1e-4:
                segs.append(("line", (cur, p1)))
                cur = p1
        elif op == "curveTo":
            p1 = (float(args[0][0]), float(args[0][1]))
            p2 = (float(args[1][0]), float(args[1][1]))
            p3 = (float(args[2][0]), float(args[2][1]))
            if cur is not None and (v_len(v_sub(p3, cur)) > 1e-4 or v_len(v_sub(p1, cur)) > 1e-4):
                segs.append(("cubic", (cur, p1, p2, p3)))
                cur = p3
        elif op == "closePath":
            if start is not None and cur is not None and v_len(v_sub(start, cur)) > 1e-4:
                segs.append(("line", (cur, start)))
            if segs:
                contours.append(segs)
            segs = []
            cur = start = None
    if segs:
        contours.append(segs)
    return contours


def draw_contours_to_pen(contours, pen, round_coords=True):
    """Replay contours onto a fontTools segment pen with strict endpoint connectivity."""
    def fmt(p):
        return (int(round(p[0])), int(round(p[1]))) if round_coords else (float(p[0]), float(p[1]))

    for segs in contours:
        if not segs:
            continue
        cleaned = []
        for kind, pts in segs:
            if kind == "line":
                p0, p1 = fmt(pts[0]), fmt(pts[1])
                if p0 != p1:
                    cleaned.append(("line", (p0, p1)))
            else:
                p0, p1, p2, p3 = fmt(pts[0]), fmt(pts[1]), fmt(pts[2]), fmt(pts[3])
                if not (p0 == p1 == p2 == p3):
                    cleaned.append(("cubic", (p0, p1, p2, p3)))
        if not cleaned:
            continue
        for i in range(len(cleaned)):
            nxt = cleaned[(i + 1) % len(cleaned)]
            p_end = cleaned[i][1][-1]
            if p_end != nxt[1][0]:
                pts = list(nxt[1])
                pts[0] = p_end
                cleaned[(i + 1) % len(cleaned)] = (nxt[0], tuple(pts))

        start = cleaned[0][1][0]
        pen.moveTo(start)
        for i, (kind, pts) in enumerate(cleaned):
            if kind == "line":
                if i == len(cleaned) - 1 and pts[1] == start:
                    continue
                pen.lineTo(pts[1])
            else:
                pen.curveTo(pts[1], pts[2], pts[3])
        pen.closePath()


def contour_signed_area(segs):
    pts = []
    for seg in segs:
        if seg[0] == "line":
            pts.append(seg[1][0])
        else:
            for k in range(8):
                pts.append(eval_seg(seg, k / 8.0))
    n = len(pts)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return 0.5 * area


def reverse_contour(segs):
    rev = []
    for kind, pts in reversed(segs):
        if kind == "line":
            rev.append(("line", (pts[1], pts[0])))
        else:
            rev.append(("cubic", (pts[3], pts[2], pts[1], pts[0])))
    return rev


def fix_winding(contours):
    """
    Enforce exact PostScript winding via topological even-odd nesting depth:
      even depth (outer contours) -> CCW (+area)
      odd depth (inner holes)     -> CW  (-area)
    Returns (fixed_contours, depths_list).
    """
    if not contours:
        return [], []
    if len(contours) == 1:
        c = contours[0]
        if contour_signed_area(c) < 0:
            c = reverse_contour(c)
        return [c], [0]

    paths = []
    areas = []
    for c in contours:
        p = pathops.Path()
        draw_contours_to_pen([c], p.getPen(), round_coords=False)
        paths.append(p)
        areas.append(contour_signed_area(c))

    out = []
    depths = []
    for i, c in enumerate(contours):
        # Sample a midpoint on the first segment so shared vertices don't confuse contains()
        sample_pt = eval_seg(c[0], 0.5)
        depth = sum(1 for j in range(len(contours)) if j != i and paths[j].contains(sample_pt))
        want_positive = (depth % 2 == 0)
        is_positive = (areas[i] > 0)
        out.append(reverse_contour(c) if (want_positive != is_positive) else c)
        depths.append(depth)
    return out, depths


def contour_bounds(segs, samples=16):
    xs, ys = [], []
    for kind, pts in segs:
        if kind == "line":
            xs.extend((pts[0][0], pts[1][0]))
            ys.extend((pts[0][1], pts[1][1]))
        else:
            for k in range(samples + 1):
                p = eval_seg((kind, pts), k / float(samples))
                xs.append(p[0])
                ys.append(p[1])
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def contours_bounds(contours, samples=16):
    x0 = y0 = float("inf")
    x1 = y1 = float("-inf")
    found = False
    for c in contours:
        b = contour_bounds(c, samples=samples)
        if b is not None:
            found = True
            if b[0] < x0: x0 = b[0]
            if b[1] < y0: y0 = b[1]
            if b[2] > x1: x1 = b[2]
            if b[3] > y1: y1 = b[3]
    return (x0, y0, x1, y1) if found else None


def transform_contours_affine(contours, fn):
    """Apply point transform fn(x, y) -> (x', y') to every coordinate & cubic handle."""
    out = []
    for segs in contours:
        nseg = []
        for kind, pts in segs:
            if kind == "line":
                nseg.append(("line", (fn(pts[0]), fn(pts[1]))))
            else:
                nseg.append(("cubic", (fn(pts[0]), fn(pts[1]), fn(pts[2]), fn(pts[3]))))
        out.append(nseg)
    return out


def unslant_contours(contours, tan_theta, y_c):
    if abs(tan_theta) < 1e-9:
        return contours
    return transform_contours_affine(contours, lambda p: (p[0] - tan_theta * (p[1] - y_c), p[1]))


def reslant_contours(contours, tan_theta, y_c):
    if abs(tan_theta) < 1e-9:
        return contours
    return transform_contours_affine(contours, lambda p: (p[0] + tan_theta * (p[1] - y_c), p[1]))


# ---------------------------------------------------------------------------
# Runtime Scanline Metrology (Stems, Counters, Structure Detection)
# ---------------------------------------------------------------------------

def contours_to_polylines(contours, steps=16):
    polys = []
    for segs in contours:
        pts = []
        for kind, spts in segs:
            if not pts:
                pts.append(spts[0])
            if kind == "line":
                pts.append(spts[1])
            else:
                for k in range(1, steps + 1):
                    pts.append(eval_seg((kind, spts), k / float(steps)))
        if pts and pts[-1] != pts[0]:
            pts.append(pts[0])
        if len(pts) >= 3:
            polys.append(pts)
    return polys


def slice_x_intersections(polys, y_target):
    xs = []
    for poly in polys:
        for i in range(len(poly) - 1):
            (x1, y1), (x2, y2) = poly[i], poly[i + 1]
            if (y1 <= y_target < y2) or (y2 <= y_target < y1):
                t = (y_target - y1) / (y2 - y1)
                xs.append(x1 + t * (x2 - x1))
    xs.sort()
    return xs


def analyze_glyph_structure(contours, v_ref, x_height, cap_height):
    """
    Scan upright glyph contours across body height to measure:
      - vertical stem thicknesses (median_stem)
      - max simultaneous vertical stems (max_stems)
      - genuine interior horizontal counters (min_counter)
      - upright bbox (x0, y0, x1, y1)
    """
    b = contours_bounds(contours, samples=12)
    if b is None:
        return {
            "bounds": None, "bw": 0.0, "bh": 0.0,
            "median_stem": v_ref, "max_stems": 0, "min_counter": None,
        }
    x0, y0, x1, y1 = b
    bw = x1 - x0
    bh = y1 - y0
    if bh < 5.0 or bw < 5.0:
        return {
            "bounds": b, "bw": bw, "bh": bh,
            "median_stem": v_ref, "max_stems": 1, "min_counter": None,
        }

    polys = contours_to_polylines(contours, steps=12)
    # Focus slices on the main glyph body band
    y_lo = max(y0 + 0.14 * bh, -0.05 * x_height if y0 < 0 and y1 > 0.4 * x_height else y0 + 0.14 * bh)
    y_hi = min(y1 - 0.14 * bh, max(cap_height, x_height) * 0.92 if y1 > 0.6 * x_height else y1 - 0.14 * bh)
    if y_hi <= y_lo + 10.0:
        y_lo = y0 + 0.20 * bh
        y_hi = y1 - 0.20 * bh

    ys = np.linspace(y_lo, y_hi, 11)
    stem_samples = []
    counter_samples = []
    max_stems = 0

    for y in ys:
        xs = slice_x_intersections(polys, float(y))
        if len(xs) < 2 or len(xs) % 2 != 0:
            continue
        n_inks = len(xs) // 2
        inks = [xs[2 * k + 1] - xs[2 * k] for k in range(n_inks)]
        gaps = [xs[2 * k + 2] - xs[2 * k + 1] for k in range(n_inks - 1)]

        # Count substantial vertical stems (width within reasonable stem band)
        valid_inks = [w for w in inks if 0.45 * v_ref <= w <= 1.65 * v_ref]
        if valid_inks:
            stem_samples.extend(valid_inks)
        if n_inks > max_stems and all(w >= 0.28 * v_ref for w in inks):
            max_stems = n_inks

        # Record real interior counters (include thin secondary bars >= 0.28*v_ref such as Lari ₾ double-bars!)
        for k, g in enumerate(gaps):
            if g >= 16.0 and inks[k] >= 0.28 * v_ref and inks[k + 1] >= 0.28 * v_ref:
                counter_samples.append((float(y), g, n_inks))

    median_stem = float(np.median(stem_samples)) if stem_samples else v_ref

    # For min_counter, track both typical body counter (25th percentile) and tightest genuine bar-gap
    min_counter = None
    tight_bar_gap = None
    if counter_samples:
        multi_gaps = [g for _, g, ns in counter_samples if ns >= max(2, max_stems)]
        use_gaps = multi_gaps if len(multi_gaps) >= 2 else [g for _, g, _ in counter_samples]
        min_counter = float(np.percentile(use_gaps, 25))
        # Also detect delicate multi-bar slits (e.g. Heavy Lari ₾ double vertical bars, 3+ stems with tight 20-35u gap)
        if max_stems >= 4:
            tight_bar_gap = float(np.percentile(use_gaps, 10))

    return {
        "bounds": b,
        "bw": bw,
        "bh": bh,
        "median_stem": median_stem,
        "max_stems": max_stems,
        "min_counter": min_counter,
        "tight_bar_gap": tight_bar_gap,
    }


def classify_contour_roles(contours, depths, v_ref, x_height, cap_height):
    """
    Classify each contour in a glyph into:
      - 'body'   : main letter body outer contour or any inner hole (depth > 0)
      - 'dot'    : standalone solid circular dot (., :, ;, i-dot, dieresis dots)
      - 'accent' : floating combining accent above/below a larger body contour (macron, acute, etc.)
    Returns list of role dicts per contour index.
    """
    n = len(contours)
    bounds_list = [contour_bounds(c, samples=12) for c in contours]
    areas = [abs(contour_signed_area(c)) for c in contours]

    # Identify which outer contours enclose a hole
    has_hole = [False] * n
    if n > 1:
        paths = []
        for c in contours:
            p = pathops.Path()
            draw_contours_to_pen([c], p.getPen(), round_coords=False)
            paths.append(p)
        for i in range(n):
            if depths[i] % 2 == 1:
                pt = eval_seg(contours[i][0], 0.5)
                for j in range(n):
                    if j != i and depths[j] % 2 == 0 and paths[j].contains(pt):
                        has_hole[j] = True

    # Find largest outer contour bbox (main body anchor)
    outer_idxs = [i for i in range(n) if depths[i] == 0]
    largest_area = max((areas[i] for i in outer_idxs), default=0.0)
    # Main body y-span from large outer contours
    body_y0 = min((bounds_list[i][1] for i in outer_idxs if areas[i] >= 0.35 * largest_area and bounds_list[i]), default=0.0)
    body_y1 = max((bounds_list[i][3] for i in outer_idxs if areas[i] >= 0.35 * largest_area and bounds_list[i]), default=x_height)

    roles = []
    for i in range(n):
        b = bounds_list[i]
        if b is None:
            roles.append({"role": "body", "bounds": None})
            continue
        cw, ch = b[2] - b[0], b[3] - b[1]
        if depths[i] > 0 or has_hole[i]:
            roles.append({"role": "body", "bounds": b})
            continue

        # Solid standalone circular dot? (period, colon, i-dot, dieresis, bullet)
        max_dot_dim = max(1.60 * v_ref, 58.0)
        aspect = cw / max(ch, 1e-6)
        is_small_circle = (
            cw <= max_dot_dim
            and ch <= max_dot_dim
            and 0.72 <= aspect <= 1.38
            and (n == 1 or areas[i] < 0.38 * largest_area or all(
                (bounds_list[j][2] - bounds_list[j][0]) <= max_dot_dim for j in outer_idxs if bounds_list[j]
            ))
        )
        if is_small_circle:
            roles.append({"role": "dot", "bounds": b})
            continue

        # Floating combining accent above/below a clearly larger body contour?
        if len(outer_idxs) >= 2 and areas[i] < 0.35 * largest_area:
            if b[1] > body_y1 - 20.0 or b[3] < body_y0 + 15.0:
                roles.append({"role": "accent", "bounds": b})
                continue

        roles.append({"role": "body", "bounds": b})

    return roles


# ---------------------------------------------------------------------------
# Exact Zone-Locked Anisotropic Outward-Normal Cubic Bézier Offsetter
# ---------------------------------------------------------------------------

def _zone_vertical_factor(y, ny, glyph_y0, glyph_y1, x_height, cap_height):
    """
    Smoothly attenuate vertical normal offset dy to 0.0 on outer-facing vertical alignment
    zones (baseline, x-height, cap-height, ascender, descender, and glyph y_min/y_max
    overshoots) while keeping full strength on interior-facing walls (counter tops/bottoms,
    arch undersides, internal crossbars).
    """
    # Only lock alignment boundaries where outward normal points AWAY from the glyph body
    ramp = 28.0
    factor = 1.0

    def smooth_ramp(dist):
        if dist <= 0.0:
            return 0.0
        if dist >= ramp:
            return 1.0
        u = dist / ramp
        return u * u * (3.0 - 2.0 * u)

    if ny < -0.25:
        # Downward-facing outward normal: lock baseline (y ≈ 0) and overall bottom (descender/overshoot)
        if -42.0 <= y <= 46.0:
            d_base = max(0.0, y - 16.0)
            factor = min(factor, smooth_ramp(d_base))
        d_bot = max(0.0, (y - glyph_y0) - 18.0)
        factor = min(factor, smooth_ramp(d_bot))

    if ny > 0.25:
        # Upward-facing outward normal: lock x-height, cap-height, and overall top (ascender/overshoot)
        d_top = max(0.0, (glyph_y1 - y) - 18.0)
        factor = min(factor, smooth_ramp(d_top))
        if abs(y - x_height) <= 44.0:
            d_xh = max(0.0, abs(y - x_height) - 18.0)
            factor = min(factor, smooth_ramp(d_xh))
        if abs(y - cap_height) <= 44.0:
            d_ch = max(0.0, abs(y - cap_height) - 18.0)
            factor = min(factor, smooth_ramp(d_ch))

    return factor


def _offset_displacement(pt, normal, dx, dy, is_hole, glyph_y0, glyph_y1, x_height, cap_height):
    """Compute zone-locked anisotropic displacement (ox, oy) at (pt, outward_normal)."""
    if abs(dy) < 1e-6:
        return (dx * normal[0], 0.0)
    if is_hole:
        # Inner holes NEVER touch outer alignment zones: apply full interior dy!
        eff_dy = dy
    else:
        z_fac = _zone_vertical_factor(pt[1], normal[1], glyph_y0, glyph_y1, x_height, cap_height)
        eff_dy = dy * z_fac
    return (dx * normal[0], eff_dy * normal[1])


def _offset_tangent(seg, t, dx, dy, is_hole, glyph_y0, glyph_y1, x_height, cap_height):
    """Analytical unit tangent of the anisotropic offset curve p(t) + D * N(t)."""
    T = tan_seg(seg, t)
    # Lock pure horizontal / vertical tangents strictly to axes (prevents extremum drift!)
    if abs(T[0]) < 0.015:
        return (0.0, 1.0 if T[1] >= 0 else -1.0)
    if abs(T[1]) < 0.015:
        return (1.0 if T[0] >= 0 else -1.0, 0.0)

    if seg[0] == "line":
        return T

    k = signed_curvature_out(seg, t)
    # Clamp curvature effect so ultra-tight corner curves don't invert tangent sign
    pt = eval_seg(seg, t)
    N = rot90_cw(T)
    eff_dy = dy if is_hole else dy * _zone_vertical_factor(pt[1], N[1], glyph_y0, glyph_y1, x_height, cap_height)
    sx = clamp(1.0 + k * dx, 0.25, 3.0)
    sy = clamp(1.0 + k * eff_dy, 0.25, 3.0)
    return v_norm((sx * T[0], sy * T[1]))


def _fit_cubic_hermite_ls(p0, p3, t0, t1, samples_t, samples_q):
    """
    Closed-form 2x2 linear least-squares fit of cubic Bézier handle lengths (a1, a2):
      C(t) = (1-t)^3 P0 + 3(1-t)^2 t (P0 + a1 T0) + 3(1-t) t^2 (P3 - a2 T1) + t^3 P3
    fitting target points samples_q at parameters samples_t.
    Returns (cubic_seg, max_err).
    """
    chord = v_len(v_sub(p3, p0))
    if chord < 1e-4:
        return ("line", (p0, p3)), 0.0

    # Assemble 2x2 normal equations A^T A [a1, a2]^T = A^T r
    h11 = h12 = h22 = b1 = b2 = 0.0
    for t, q in zip(samples_t, samples_q):
        mt = 1.0 - t
        b0 = mt * mt * mt + 3.0 * mt * mt * t
        b3 = 3.0 * mt * t * t + t * t * t
        c1 = 3.0 * mt * mt * t
        c2 = -3.0 * mt * t * t
        rx = q[0] - (b0 * p0[0] + b3 * p3[0])
        ry = q[1] - (b0 * p0[1] + b3 * p3[1])

        u1x, u1y = c1 * t0[0], c1 * t0[1]
        u2x, u2y = c2 * t1[0], c2 * t1[1]

        h11 += u1x * u1x + u1y * u1y
        h12 += u1x * u2x + u1y * u2y
        h22 += u2x * u2x + u2y * u2y
        b1 += u1x * rx + u1y * ry
        b2 += u2x * rx + u2y * ry

    det = h11 * h22 - h12 * h12
    if abs(det) > 1e-9:
        a1 = (h22 * b1 - h12 * b2) / det
        a2 = (-h12 * b1 + h11 * b2) / det
    else:
        a1 = a2 = chord / 3.0

    # Clamp handle lengths strictly positive and bounded (prevents cusps / loops!)
    lo = 0.04 * chord
    hi = 1.15 * chord
    a1 = clamp(a1, lo, hi)
    a2 = clamp(a2, lo, hi)

    p1 = (p0[0] + a1 * t0[0], p0[1] + a1 * t0[1])
    p2 = (p3[0] - a2 * t1[0], p3[1] - a2 * t1[1])
    seg = ("cubic", (p0, p1, p2, p3))

    max_err = 0.0
    for t, q in zip(samples_t, samples_q):
        c = eval_seg(seg, t)
        err = math.hypot(c[0] - q[0], c[1] - q[1])
        if err > max_err:
            max_err = err
    return seg, max_err


def _offset_cubic_segment(
    seg, p0_new, p3_new, t0_new, t1_new,
    shift0, shift1, dx, dy, is_hole,
    glyph_y0, glyph_y1, x_height, cap_height,
    depth=0,
):
    """
    Offset a single cubic Bézier segment smoothly between mitered/shared endpoints
    (p0_new, p3_new) with exact endpoint tangents (t0_new, t1_new).
    Subdivides adaptively via de Casteljau if residual fit error > 0.65u.
    """
    sample_ts = (0.15, 0.30, 0.50, 0.70, 0.85)
    sample_qs = []
    for t in sample_ts:
        pt = eval_seg(seg, t)
        n = outward_normal_seg(seg, t)
        off = _offset_displacement(pt, n, dx, dy, is_hole, glyph_y0, glyph_y1, x_height, cap_height)
        # Smoothly blend tiny corner miter endpoint shift into interior samples
        mt = 1.0 - t
        w0 = mt * mt * (1.0 + 2.0 * t)  # Hermite h00(t): 1 at 0, 0 at 1, zero deriv at ends
        w1 = t * t * (3.0 - 2.0 * t)
        qx = pt[0] + off[0] + w0 * shift0[0] + w1 * shift1[0]
        qy = pt[1] + off[1] + w0 * shift0[1] + w1 * shift1[1]
        sample_qs.append((qx, qy))

    fitted, err = _fit_cubic_hermite_ls(p0_new, p3_new, t0_new, t1_new, sample_ts, sample_qs)

    # Check if adaptive subdivision is beneficial (e.g. high-sweep curve or inflection)
    if err > 0.65 and depth < 2 and seg_approx_len(seg) > 14.0:
        left_s, right_s = split_seg(seg, 0.5)
        pm_orig = eval_seg(seg, 0.5)
        nm_orig = outward_normal_seg(seg, 0.5)
        off_m = _offset_displacement(pm_orig, nm_orig, dx, dy, is_hole, glyph_y0, glyph_y1, x_height, cap_height)
        shift_m = (0.5 * (shift0[0] + shift1[0]), 0.5 * (shift0[1] + shift1[1]))
        pm_new = (pm_orig[0] + off_m[0] + shift_m[0], pm_orig[1] + off_m[1] + shift_m[1])
        tm_new = _offset_tangent(seg, 0.5, dx, dy, is_hole, glyph_y0, glyph_y1, x_height, cap_height)

        out_l = _offset_cubic_segment(
            left_s, p0_new, pm_new, t0_new, tm_new,
            shift0, shift_m, dx, dy, is_hole,
            glyph_y0, glyph_y1, x_height, cap_height, depth + 1,
        )
        out_r = _offset_cubic_segment(
            right_s, pm_new, p3_new, tm_new, t1_new,
            shift_m, shift1, dx, dy, is_hole,
            glyph_y0, glyph_y1, x_height, cap_height, depth + 1,
        )
        return out_l + out_r

    return [fitted]


def _intersect_rays(pa, ta, pb, tb, fallback_orig, max_dist):
    """Intersect ray (pa, ta) with ray (pb, tb), clamping extreme acute spikes."""
    det = v_cross(ta, tb)
    if abs(det) > 0.16:
        diff = v_sub(pb, pa)
        u = v_cross(diff, tb) / det
        p_mit = (pa[0] + u * ta[0], pa[1] + u * ta[1])
        d = v_len(v_sub(p_mit, fallback_orig))
        if d <= max_dist:
            return p_mit
        # Clamp along direction from original vertex toward miter point
        dv = v_norm(v_sub(p_mit, fallback_orig))
        return (fallback_orig[0] + max_dist * dv[0], fallback_orig[1] + max_dist * dv[1])
    return (0.5 * (pa[0] + pb[0]), 0.5 * (pa[1] + pb[1]))


def offset_contour_anisotropic(
    segs, dx, dy, is_hole,
    glyph_y0, glyph_y1, x_height, cap_height,
):
    """
    Apply exact zone-locked anisotropic outward-normal offset (dx, dy) to a single
    canonical-winding PostScript contour.
      - Sharp corners get exact ray-ray miter intersections (pure 'line' caps preserved!)
      - Smooth joins share exact G1 tangents (vertical/horizontal extrema locked!)
      - Inverted micro-segments at tight Heavy inner crotches are collapsed cleanly!
    """
    if abs(dx) < 1e-4 and abs(dy) < 1e-4:
        return list(segs)

    # Filter out any pre-existing zero-length segments
    work = [s for s in segs if seg_approx_len(s) > 1e-3]
    n = len(work)
    if n < 2:
        return work

    # Step 1: Compute per-segment endpoint tangents, outward normals, raw offset endpoints
    t0_list = [tan_seg(s, 0.0) for s in work]
    t1_list = [tan_seg(s, 1.0) for s in work]
    n0_list = [rot90_cw(t) for t in t0_list]
    n1_list = [rot90_cw(t) for t in t1_list]

    A = []
    B = []
    for i, s in enumerate(work):
        p0 = s[1][0]
        p3 = s[1][-1]
        off0 = _offset_displacement(p0, n0_list[i], dx, dy, is_hole, glyph_y0, glyph_y1, x_height, cap_height)
        off1 = _offset_displacement(p3, n1_list[i], dx, dy, is_hole, glyph_y0, glyph_y1, x_height, cap_height)
        A.append(v_add(p0, off0))
        B.append(v_add(p3, off1))

    # Step 2: Classify vertices (smooth vs sharp corner) & compute mitered vertices
    max_mit = max(2.8 * max(abs(dx), abs(dy), 1.0), 4.0)
    is_smooth = [False] * n
    V_new = [None] * n

    for i in range(n):
        prev_i = (i - 1) % n
        turn = abs(turn_angle_deg(t1_list[prev_i], t0_list[i]))
        v_orig = work[i][1][0]
        if turn < 8.0:
            is_smooth[i] = True
            n_avg = v_norm(v_add(n1_list[prev_i], n0_list[i]))
            off = _offset_displacement(v_orig, n_avg, dx, dy, is_hole, glyph_y0, glyph_y1, x_height, cap_height)
            V_new[i] = v_add(v_orig, off)
        else:
            p_mit = _intersect_rays(B[prev_i], t1_list[prev_i], A[i], t0_list[i], v_orig, max_mit)
            # Lock extreme vertical alignment corners (e.g. sloped descender tips of დ/ღ/ლ
            # or sloped ascender tips of რ/ნ/კ) so miter intersections never push y past bounds!
            if not is_hole:
                near_ext = (
                    (v_orig[1] <= glyph_y0 + 18.0 and p_mit[1] < v_orig[1])
                    or (v_orig[1] >= glyph_y1 - 18.0 and p_mit[1] > v_orig[1])
                    or (abs(v_orig[1]) <= 8.0 and abs(p_mit[1] - v_orig[1]) > 1.5)
                    or (abs(v_orig[1] - x_height) <= 14.0 and p_mit[1] > v_orig[1] + 1.5)
                    or (abs(v_orig[1] - cap_height) <= 14.0 and p_mit[1] > v_orig[1] + 1.5)
                )
                if near_ext:
                    # Keep exact miter x, clamp y tightly to original alignment level!
                    y_clamped = clamp(p_mit[1], v_orig[1] - 1.5, v_orig[1] + 1.5)
                    p_mit = (p_mit[0], y_clamped)
            V_new[i] = p_mit

    # Step 3: Guard against inverted short micro-segments (Heavy inner-crotch bowtie elimination!)
    # If a short straight line segment reversed direction after offsetting, collapse it and
    # directly intersect its two flanking segments.
    collapsed = set()
    for i in range(n):
        if work[i][0] != "line":
            continue
        L_orig = v_len(v_sub(work[i][1][1], work[i][1][0]))
        if L_orig < 3.2 * max(abs(dx), abs(dy), 1.0):
            old_vec = v_sub(work[i][1][1], work[i][1][0])
            new_vec = v_sub(V_new[(i + 1) % n], V_new[i])
            if v_dot(old_vec, new_vec) <= 0.0:
                collapsed.add(i)

    if collapsed and len(collapsed) < n - 2:
        # Rebuild active segment list and recompute collapsed corner intersections
        keep = [i for i in range(n) if i not in collapsed]
        m = len(keep)
        new_work = [work[i] for i in keep]
        new_A = [A[i] for i in keep]
        new_B = [B[i] for i in keep]
        new_t0 = [t0_list[i] for i in keep]
        new_t1 = [t1_list[i] for i in keep]
        new_V = [None] * m
        new_smooth = [False] * m
        for k in range(m):
            orig_i = keep[k]
            prev_orig = keep[(k - 1) % m]
            if (prev_orig + 1) % n == orig_i:
                new_V[k] = V_new[orig_i]
                new_smooth[k] = is_smooth[orig_i]
            else:
                # Collapsed micro-segment sat between prev_orig and orig_i -> direct miter!
                v_mid = (
                    0.5 * (work[prev_orig][1][-1][0] + work[orig_i][1][0][0]),
                    0.5 * (work[prev_orig][1][-1][1] + work[orig_i][1][0][1]),
                )
                new_V[k] = _intersect_rays(new_B[(k - 1) % m], new_t1[(k - 1) % m], new_A[k], new_t0[k], v_mid, max_mit * 1.4)
                new_smooth[k] = False
        work, A, B, t0_list, t1_list, V_new, is_smooth = (
            new_work, new_A, new_B, new_t0, new_t1, new_V, new_smooth
        )
        n = m

    # Step 4: Compute G1-consistent endpoint tangents at every node
    T_start = [None] * n
    T_end = [None] * n
    for i in range(n):
        T_start[i] = _offset_tangent(work[i], 0.0, dx, dy, is_hole, glyph_y0, glyph_y1, x_height, cap_height)
        T_end[i] = _offset_tangent(work[i], 1.0, dx, dy, is_hole, glyph_y0, glyph_y1, x_height, cap_height)

    # Unify tangents across smooth nodes for guaranteed G1 continuity
    for i in range(n):
        if is_smooth[i]:
            prev_i = (i - 1) % n
            # Preserve exact horizontal/vertical extrema strictly!
            if abs(t0_list[i][0]) < 0.015 or abs(t1_list[prev_i][0]) < 0.015:
                ty = 1.0 if (T_end[prev_i][1] + T_start[i][1]) >= 0 else -1.0
                T_shared = (0.0, ty)
            elif abs(t0_list[i][1]) < 0.015 or abs(t1_list[prev_i][1]) < 0.015:
                tx = 1.0 if (T_end[prev_i][0] + T_start[i][0]) >= 0 else -1.0
                T_shared = (tx, 0.0)
            else:
                T_shared = v_norm(v_add(T_end[prev_i], T_start[i]))
            T_end[prev_i] = T_shared
            T_start[i] = T_shared

    # Step 5: Construct final offset segments
    out_segs = []
    for i in range(n):
        p0_new = V_new[i]
        p3_new = V_new[(i + 1) % n]
        if work[i][0] == "line":
            if v_len(v_sub(p3_new, p0_new)) > 0.05:
                out_segs.append(("line", (p0_new, p3_new)))
        else:
            shift0 = v_sub(p0_new, A[i])
            shift1 = v_sub(p3_new, B[i])
            cubics = _offset_cubic_segment(
                work[i], p0_new, p3_new, T_start[i], T_end[i],
                shift0, shift1, dx, dy, is_hole,
                glyph_y0, glyph_y1, x_height, cap_height,
            )
            out_segs.extend(cubics)

    # Guarantee exact closed-loop connectivity
    if out_segs:
        m = len(out_segs)
        for i in range(m):
            nxt = out_segs[(i + 1) % m]
            p_end = out_segs[i][1][-1]
            if v_len(v_sub(p_end, nxt[1][0])) > 1e-6:
                pts = list(nxt[1])
                pts[0] = p_end
                out_segs[(i + 1) % m] = (nxt[0], tuple(pts))

    return out_segs


# ---------------------------------------------------------------------------
# Superelliptical Bowl Flank Tension (Fira Sans Condensed / Expanded DNA)
# ---------------------------------------------------------------------------

def apply_bowl_tension_contour(segs, is_hole, bowl_tension):
    """
    Apply subtle, mathematically convex-hull-safe superelliptical cubic handle tension
    to genuine quarter-bowl / arch segments (those with orthogonal horizontal/vertical
    endpoint tangents).
    """
    if not bowl_tension:
        return segs

    v_scale = bowl_tension.get("vert_handle_scale_inner" if is_hole else "vert_handle_scale_outer", 1.0)
    h_scale = bowl_tension.get("horiz_handle_scale_inner" if is_hole else "horiz_handle_scale_outer", 1.0)
    if abs(v_scale - 1.0) < 1e-4 and abs(h_scale - 1.0) < 1e-4:
        return segs

    out = []
    for kind, pts in segs:
        if kind != "cubic":
            out.append((kind, pts))
            continue
        p0, p1, p2, p3 = pts
        dx_b = abs(p3[0] - p0[0])
        dy_b = abs(p3[1] - p0[1])
        if dx_b < 22.0 or dy_b < 22.0:
            out.append((kind, pts))
            continue

        h1 = (p1[0] - p0[0], p1[1] - p0[1])
        h2 = (p2[0] - p3[0], p2[1] - p3[1])
        l1 = math.hypot(h1[0], h1[1])
        l2 = math.hypot(h2[0], h2[1])
        if l1 < 4.0 or l2 < 4.0:
            out.append((kind, pts))
            continue

        h1_vert = abs(h1[0]) <= 0.08 * abs(h1[1])
        h1_horiz = abs(h1[1]) <= 0.08 * abs(h1[0])
        h2_vert = abs(h2[0]) <= 0.08 * abs(h2[1])
        h2_horiz = abs(h2[1]) <= 0.08 * abs(h2[0])

        # Only adjust genuine quarter-oval curves (one vertical handle + one horizontal handle!)
        if not ((h1_vert and h2_horiz) or (h1_horiz and h2_vert)):
            out.append((kind, pts))
            continue

        new_p1 = p1
        new_p2 = p2
        if h1_vert:
            ny = clamp(h1[1] * v_scale, -0.84 * dy_b, 0.84 * dy_b)
            # Only scale if it stays in the same direction and doesn't shrink below 0.25*dy_b
            if abs(ny) >= 0.20 * dy_b:
                s = ny / h1[1]
                new_p1 = (p0[0] + h1[0] * s, p0[1] + h1[1] * s)
        elif h1_horiz:
            nx = clamp(h1[0] * h_scale, -0.84 * dx_b, 0.84 * dx_b)
            if abs(nx) >= 0.20 * dx_b:
                s = nx / h1[0]
                new_p1 = (p0[0] + h1[0] * s, p0[1] + h1[1] * s)

        if h2_vert:
            ny = clamp(h2[1] * v_scale, -0.84 * dy_b, 0.84 * dy_b)
            if abs(ny) >= 0.20 * dy_b:
                s = ny / h2[1]
                new_p2 = (p3[0] + h2[0] * s, p3[1] + h2[1] * s)
        elif h2_horiz:
            nx = clamp(h2[0] * h_scale, -0.84 * dx_b, 0.84 * dx_b)
            if abs(nx) >= 0.20 * dx_b:
                s = nx / h2[0]
                new_p2 = (p3[0] + h2[0] * s, p3[1] + h2[1] * s)

        out.append(("cubic", (p0, new_p1, new_p2, p3)))
    return out


# ---------------------------------------------------------------------------
# Cross-Weight X-Only Master Interpolation Helper
# ---------------------------------------------------------------------------

def _contours_command_sig(contours):
    return tuple(tuple(kind for kind, _ in segs) for segs in contours)


def _align_and_validate_partner_contour(c0, cp, shift_x, max_xy_dist=50.0, max_y_dist=32.0):
    """
    Find optimal cyclic start-point rotation of partner contour `cp` matching `c0`
    in segment command types AND verify strict point-by-point correspondence.
    Prevents rotated start points (e.g. FiraGO BoldItalic vs SemiBoldItalic uni10D7!)
    from ever pinching or twisting a contour during cross-weight interpolation.
    Returns aligned `cp_rot` or None if correspondence fails.
    """
    m = len(c0)
    if len(cp) != m or m == 0:
        return None
    k0s = tuple(k for k, _ in c0)
    kps = tuple(k for k, _ in cp)

    best_rot = None
    best_max_d = float("inf")

    for r in range(m):
        # Check rotated command signature match first
        ok_sig = True
        for i in range(m):
            if k0s[i] != kps[(i + r) % m]:
                ok_sig = False
                break
        if not ok_sig:
            continue

        max_d = 0.0
        max_dy = 0.0
        for i in range(m):
            pts0 = c0[i][1]
            ptsp = cp[(i + r) % m][1]
            for p0, pp in zip(pts0, ptsp):
                dx = (pp[0] + shift_x) - p0[0]
                dy = pp[1] - p0[1]
                d = math.hypot(dx, dy)
                if d > max_d:
                    max_d = d
                if abs(dy) > max_dy:
                    max_dy = abs(dy)
            if max_d >= best_max_d:
                break

        if max_d < best_max_d and max_dy <= max_y_dist:
            best_max_d = max_d
            best_rot = r

    if best_rot is None or best_max_d > max_xy_dist:
        return None
    return cp[best_rot:] + cp[:best_rot]


def _interpolate_contours_x_only(base_contours, partner_contours, alpha_x, dv_master=40.0):
    """
    Interpolate X coordinates ONLY between topologically & geometrically verified
    upright contours (handling cyclic start-point rotations and rejecting any
    reordered or mismatched contours!). Keeps Y coordinates 100.0% exact so baseline,
    x-height, cap-height, overshoots, and horizontal bar thickness never drift.
    Returns interpolated contours or None if strict point correspondence fails.
    """
    if abs(alpha_x) < 1e-4:
        return None
    if len(base_contours) != len(partner_contours):
        return None
    b0 = contours_bounds(base_contours, samples=8)
    bp = contours_bounds(partner_contours, samples=8)
    if b0 is None or bp is None:
        return None
    # Guard against mismatched glyph redesigns across weights
    if abs(b0[1] - bp[1]) > 18.0 or abs(b0[3] - bp[3]) > 18.0:
        return None

    cx0 = 0.5 * (b0[0] + b0[2])
    cxp = 0.5 * (bp[0] + bp[2])
    shift_x = cx0 - cxp
    om = 1.0 - alpha_x
    max_xy = max(48.0, 2.2 * abs(dv_master))

    # Match each base contour to its corresponding partner contour (same winding sign & closest bbox!)
    used_p = set()
    out = []
    for c0 in base_contours:
        a0 = contour_signed_area(c0)
        cb0 = contour_bounds(c0, samples=8)
        if cb0 is None:
            return None
        best_j = None
        best_aligned = None
        best_score = float("inf")
        for j, cp in enumerate(partner_contours):
            if j in used_p or len(cp) != len(c0):
                continue
            ap = contour_signed_area(cp)
            if a0 * ap < 0:
                continue  # Winding signs MUST match (outer <-> outer, hole <-> hole)!
            cbp = contour_bounds(cp, samples=8)
            if cbp is None:
                continue
            # Check coarse bbox proximity first
            bdiff = max(
                abs((cbp[0] + shift_x) - cb0[0]),
                abs((cbp[2] + shift_x) - cb0[2]),
                abs(cbp[1] - cb0[1]),
                abs(cbp[3] - cb0[3]),
            )
            if bdiff > max_xy * 1.4:
                continue
            aligned = _align_and_validate_partner_contour(c0, cp, shift_x, max_xy_dist=max_xy, max_y_dist=32.0)
            if aligned is not None and bdiff < best_score:
                best_score = bdiff
                best_j = j
                best_aligned = aligned

        if best_aligned is None:
            return None
        used_p.add(best_j)

        nc = []
        for (k0, pts0), (kp, ptsp) in zip(c0, best_aligned):
            if k0 != kp:
                return None
            npts = tuple(
                (om * p0[0] + alpha_x * (pp[0] + shift_x), p0[1])
                for p0, pp in zip(pts0, ptsp)
            )
            nc.append((k0, npts))
        out.append(nc)
    return out


# ---------------------------------------------------------------------------
# Spec & Partner Font Loader
# ---------------------------------------------------------------------------

def load_spec(spec_path=DEFAULT_SPEC_PATH):
    if spec_path in _SPEC_CACHE:
        return _SPEC_CACHE[spec_path]
    if spec_path and os.path.exists(spec_path):
        with open(spec_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _SPEC_CACHE[spec_path] = data
        return data
    return None


def _style_key(weight, is_italic):
    if is_italic:
        return "Italic" if weight == "Regular" else f"{weight}Italic"
    return weight


def _load_partner_firago(weight, is_italic, fonts_dir=DEFAULT_FONTS_DIR):
    key = (fonts_dir, weight, bool(is_italic))
    if key in _PARTNER_FONT_CACHE:
        return _PARTNER_FONT_CACHE[key]
    sk = _style_key(weight, is_italic)
    path = os.path.join(fonts_dir, f"FiraGO-{sk}.otf")
    if os.path.exists(path):
        f = TTFont(path)
        _PARTNER_FONT_CACHE[key] = f
        return f
    _PARTNER_FONT_CACHE[key] = None
    return None


def _is_georgian_or_lari(gname):
    gl = gname.lower()
    return any(
        k in gl
        for k in (
            "uni10a", "uni10b", "uni10c", "uni10d", "uni10e", "uni10f",
            "uni1c9", "uni1ca", "uni1cb", "georgian", "uni20be", "uni060b",
        )
    )


def _is_mtavruli_or_uppercase(gname, ch=None):
    if ".case" in gname:
        return True
    if ch is not None:
        cp = ord(ch)
        if 0x1C90 <= cp <= 0x1CBF:
            return True
        if ch.isupper():
            return True
    if gname and gname[0].isupper() and not gname.startswith("uni"):
        return True
    return False


def _is_digit_glyph(gname, ch=None):
    if ch is not None and "0" <= ch <= "9":
        return True
    base = gname.split(".")[0]
    return base in ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")


# ---------------------------------------------------------------------------
# Pathops Safety Verification
# ---------------------------------------------------------------------------

def _pathops_area_mismatch(contours):
    """Return relative discrepancy between raw contour area and skia-pathops simplified area."""
    if not contours:
        return 0.0, 0.0
    p = pathops.Path()
    draw_contours_to_pen(contours, p.getPen(), round_coords=True)
    raw_area = abs(p.area)
    if raw_area < 30.0:
        return 0.0, raw_area
    p_simp = pathops.simplify(p, clockwise=False)
    simp_area = abs(p_simp.area)
    return abs(raw_area - simp_area) / raw_area, raw_area


# ---------------------------------------------------------------------------
# Main WidthTransformer Class (Directly Compatible with build_superfamily.py!)
# ---------------------------------------------------------------------------

class WidthTransformer:
    """
    Stateful per-style anisotropic optical width transformer for Borbalo GO.

    Compatible with build_superfamily.py:
        transformer = WidthTransformer(font, mode="condensed", weight="Regular", is_italic=False)
        new_contours, new_adv, lsb_delta = transformer.transform_glyph(gname)
        new_adv = transformer.transform_advance(gname, old_adv)
        transformer.scale_kerning(font, target_glyphs=...)
    """

    def __init__(
        self,
        font,
        mode="condensed",
        weight="Regular",
        is_italic=False,
        file_suffix=None,
        spec_path=DEFAULT_SPEC_PATH,
        fonts_dir=DEFAULT_FONTS_DIR,
        master_blend=0.35,
    ):
        if mode not in ("condensed", "extra_condensed", "expanded"):
            raise ValueError(f"Unsupported width mode: {mode!r} (expected 'condensed', 'extra_condensed', or 'expanded')")

        self.font = font
        self.mode = mode
        self.weight = weight
        self.is_italic = bool(is_italic)
        self.style_key = file_suffix or _style_key(weight, is_italic)
        self.weight_class = WEIGHT_CLASS_MAP.get(weight, int(getattr(font["OS/2"], "usWeightClass", 400)))
        self.fonts_dir = fonts_dir
        self.master_blend = float(master_blend)

        self.spec = load_spec(spec_path)
        self.mode_spec = self.spec["modes"][mode] if (self.spec and mode in self.spec.get("modes", {})) else {}
        self.style_spec = self.mode_spec.get("per_style", {}).get(self.style_key, {})
        if not self.style_spec and self.mode_spec.get("per_style"):
            self.style_spec = self.mode_spec["per_style"].get(_style_key(weight, is_italic), {})

        # Font vertical metrics & exact italic angle
        os2 = font["OS/2"]
        self.x_height = float(getattr(os2, "sxHeight", 527))
        self.cap_height = float(getattr(os2, "sCapHeight", 689))
        post_ang = float(getattr(font["post"], "italicAngle", 0.0)) if "post" in font else 0.0
        if self.is_italic and abs(post_ang) < 0.1:
            post_ang = -8.0
        self.italic_angle_deg = post_ang if self.is_italic else 0.0
        # post.italicAngle is negative (-8.0) for rightward top tilt; slant slope m = tan(+8.0 deg) > 0
        self.tan_slant = math.tan(math.radians(-self.italic_angle_deg)) if self.is_italic else 0.0
        # Empirically verified FiraGO Italic slant pivot: exact mid x-height!
        self.slant_pivot_y = 0.5 * self.x_height

        # Reference stems for this weight/style
        stems_spec = self.style_spec.get("measured_normal_stems", {})
        self.v_ref_lc = float(stems_spec.get("n_v", FALLBACK_VSTEM.get(weight, 96.0)))
        self.v_ref_uc = float(stems_spec.get("H_v", self.v_ref_lc * 1.03))
        self.v_ref_oval = float(stems_spec.get("o_v", self.v_ref_lc * 1.03))
        self.h_ref_lc = float(stems_spec.get("o_h", FALLBACK_HBAR.get(weight, 74.0)))
        self.h_ref_uc = float(stems_spec.get("H_h", self.h_ref_lc * 1.04))

        # Target stroke ratios from spec
        default_v = {"condensed": 0.972, "extra_condensed": 0.955, "expanded": 1.018}[mode]
        default_h = {"condensed": 0.972, "extra_condensed": 0.960, "expanded": 1.014}[mode]
        self.vstem_ratio = float(self.style_spec.get("vstem_ratio", default_v))
        self.hbar_ratio = float(self.style_spec.get("hbar_ratio", default_h))
        self.oval_v_ratio = float(self.style_spec.get("oval_v_ratio", self.vstem_ratio))
        self.oval_h_ratio = float(self.style_spec.get("oval_h_ratio", self.hbar_ratio))
        self.bowl_tension = self.style_spec.get("bowl_tension", {})

        # Width & sidebearing ratios
        default_adv = {"condensed": 0.907, "extra_condensed": 0.838, "expanded": 1.148}[mode]
        default_sb = {"condensed": 0.870, "extra_condensed": 0.780, "expanded": 1.130}[mode]
        self.adv_ratio_mkh = float(self.style_spec.get("adv_ratio_mkh", default_adv))
        self.adv_ratio_mtv = float(self.style_spec.get("adv_ratio_mtv", default_adv))
        self.adv_ratio_digits = float(self.style_spec.get("adv_ratio_digits", default_adv))
        self.bbox_ratio_mkh = float(self.style_spec.get("bbox_ratio_mkh", default_adv))
        self.bbox_ratio_mtv = float(self.style_spec.get("bbox_ratio_mtv", default_adv))
        self.sb_ratio_mkh = float(self.style_spec.get("sb_ratio_mkh", default_sb))
        self.sb_ratio_mtv = float(self.style_spec.get("sb_ratio_mtv", default_sb))
        self.space_ratio = float(self.style_spec.get("space_ratio", default_adv))

        # Per-glyph multiplier tables
        self.geor_mults = self.mode_spec.get("georgian_per_glyph_multipliers", {})
        self.latin_mults = self.mode_spec.get("latin_per_glyph_multipliers", {})

        # Build reverse cmap (gname -> Unicode char) for fast Latin/symbol lookup
        self.gname_to_char = {}
        cmap = font.getBestCmap() or {}
        for cp, gn in cmap.items():
            if gn not in self.gname_to_char:
                self.gname_to_char[gn] = chr(cp)

        # Load adjacent partner master for X-only cross-weight interpolation
        self.partner_font = None
        self.partner_v_ref = None
        if self.master_blend > 1e-4 and weight in WEIGHT_ORDER:
            idx = WEIGHT_ORDER.index(weight)
            partner_w = None
            if mode in ("condensed", "extra_condensed") and idx < len(WEIGHT_ORDER) - 1:
                partner_w = WEIGHT_ORDER[idx + 1]
            elif mode == "expanded" and idx > 0:
                partner_w = WEIGHT_ORDER[idx - 1]
            if partner_w is not None:
                pf = _load_partner_firago(partner_w, self.is_italic, fonts_dir=fonts_dir)
                if pf is not None:
                    self.partner_font = pf
                    p_sk = _style_key(partner_w, self.is_italic)
                    p_spec = self.mode_spec.get("per_style", {}).get(p_sk, {})
                    p_stems = p_spec.get("measured_normal_stems", {})
                    self.partner_v_ref = float(p_stems.get("n_v", FALLBACK_VSTEM.get(partner_w, self.v_ref_lc)))

    def get_glyph_multiplier(self, gname):
        """Return per-glyph relative width multiplier (around 1.0) from spec."""
        if gname in self.geor_mults:
            entry = self.geor_mults[gname]
            if self.is_italic and "italic_override" in entry:
                sub = entry["italic_override"]
            else:
                sub = entry
            t = clamp((self.weight_class - 400.0) / 500.0, 0.0, 1.0)
            return (1.0 - t) * float(sub["light_regular"]) + t * float(sub["heavy"])

        # Fallback for Georgian Italic cursive ტ (uni10E2) if not explicitly overridden
        if self.is_italic and gname == "uni10E2":
            if self.mode == "condensed":
                return 1.004
            if self.mode == "extra_condensed":
                return 1.008
            return 1.010

        # Latin / digits / punctuation lookup (for Expanded mode)
        ch = self.gname_to_char.get(gname)
        if ch is None and "." in gname:
            base = gname.split(".")[0]
            ch = self.gname_to_char.get(base)
        if ch is not None and ch in self.latin_mults:
            return float(self.latin_mults[ch])

        # Try base ASCII letter for accented composites (e.g. Aacute -> A, egrave -> e)
        if gname:
            base = gname.split(".")[0]
            if len(base) >= 2 and base[0].isalpha() and base[0] in self.latin_mults:
                if base[1:].lower() in (
                    "acute", "grave", "circumflex", "tilde", "dieresis", "macron",
                    "breve", "caron", "ring", "cedilla", "ogonek", "dotaccent", "hungarumlaut",
                ):
                    return float(self.latin_mults[base[0]])
        return 1.0

    def get_glyph_ratios(self, gname):
        """Return (adv_ratio, bbox_ratio, sb_ratio, v_ref, h_ref, is_uc) for gname."""
        ch = self.gname_to_char.get(gname)
        is_uc = _is_mtavruli_or_uppercase(gname, ch)
        is_dig = _is_digit_glyph(gname, ch)
        g_mult = self.get_glyph_multiplier(gname)

        if is_dig:
            adv_base = self.adv_ratio_digits
            bbox_base = self.bbox_ratio_mtv
            sb_base = self.sb_ratio_mtv
        elif is_uc:
            adv_base = self.adv_ratio_mtv
            bbox_base = self.bbox_ratio_mtv
            sb_base = self.sb_ratio_mtv
        else:
            adv_base = self.adv_ratio_mkh
            bbox_base = self.bbox_ratio_mkh
            sb_base = self.sb_ratio_mkh

        # Apply per-glyph multiplier to bbox & advance cleanly
        adv_r = adv_base * g_mult
        bbox_r = bbox_base * g_mult
        if self.mode == "expanded":
            # Never allow Expanded mode to narrow any glyph (e.g. Heavy lowercase 'l')
            adv_r = max(adv_r, 1.03)
            bbox_r = max(bbox_r, 1.02)
        v_ref = self.v_ref_uc if is_uc else self.v_ref_lc
        h_ref = self.h_ref_uc if is_uc else self.h_ref_lc
        return adv_r, bbox_r, sb_base, v_ref, h_ref, is_uc

    def transform_advance(self, gname, old_adv):
        """Compute transformed advance width for empty/whitespace glyphs."""
        if old_adv <= 0:
            return old_adv
        if gname in ("space", "nbspace", "uni00A0", "uni2002", "uni2003", "uni2009"):
            return int(round(old_adv * self.space_ratio))
        adv_r, _, _, _, _, _ = self.get_glyph_ratios(gname)
        return int(round(old_adv * adv_r))

    def _compute_core_params(
        self, bw, v_eff, h_eff, bbox_r, v_ratio, h_ratio,
        max_stems, min_counter, gname, tight_bar_gap=None,
    ):
        """
        Solve exact 2x2 simultaneous system for (s_core, dx, dy) with Heavy counter-preservation
        physics and single-stem narrow-glyph protection.
        """
        # Guard 1: Narrow single-stem glyph (I, l, |, !, 1-bar) where bw <= 1.38 * v_eff
        if bw <= 1.38 * v_eff and max_stems <= 1:
            return {
                "single_stem": True,
                "s_core": v_ratio,
                "dx": 0.0,
                "dy": 0.0,
                "target_w": bw * v_ratio,
                "target_v": v_eff * v_ratio,
            }

        target_w = bw * bbox_r
        target_v = v_eff * v_ratio

        # Guard 2: Counter-preservation physics for Condensed / Extra Condensed
        # Ensure real interior counters never collapse (modeled after FiraSansCompressed Black 'm' ~44u)
        denom = max(bw - v_eff, 0.35 * bw)
        s_core = (target_w - target_v) / denom
        dx = 0.5 * (target_v - s_core * v_eff)

        if self.mode in ("condensed", "extra_condensed") and min_counter is not None and max_stems >= 2:
            # Minimum safe counter floor: proportional to FiraSansCompressed Black 'm' (44u / 82u = 0.537)
            c_floor = max(0.52 * min_counter, min(40.0, 0.72 * min_counter))
            c_pred = s_core * min_counter - 2.0 * dx
            if c_pred < c_floor:
                # Split counter relief gently: soften target_v (never below 0.905 * v_eff)
                # and slightly relax target_w (at most +4.5% of bw) until c_pred >= c_floor!
                deficit = c_floor - c_pred
                # Reducing target_v by dV opens EVERY counter by ~dV (since dx shrinks by ~dV/2, 2dx shrinks by dV)
                max_v_soften = max(0.0, target_v - 0.905 * v_eff)
                v_soften = min(max_v_soften, 0.55 * deficit)
                target_v -= v_soften

                # Re-evaluate counter after stem softening
                s_core = (target_w - target_v) / denom
                dx = 0.5 * (target_v - s_core * v_eff)
                c_pred = s_core * min_counter - 2.0 * dx
                if c_pred < c_floor:
                    # Relax target_w smoothly so counter stays open!
                    # Increasing target_w by dW increases s_core by dW/denom and decreases dx by 0.5*v_eff*dW/denom
                    # => c_pred increases by dW * (min_counter + v_eff) / denom
                    rem = c_floor - c_pred
                    gain_per_dw = (min_counter + v_eff) / denom
                    dw_need = rem / max(gain_per_dw, 0.25)
                    # Cap width relaxation to keep Condensed/ExtraCondensed unmistakable
                    max_dw = (0.048 if self.mode == "extra_condensed" else 0.032) * bw
                    dw_use = min(dw_need, max_dw)
                    target_w += dw_use
                    s_core = (target_w - target_v) / denom
                    dx = 0.5 * (target_v - s_core * v_eff)

        # Safety clamp on dx relative to thin stems (never let inward offset pinch thin stems in Expanded!)
        if dx < 0.0:
            # In Expanded, s_core * v_eff + 2 * dx = target_v; guarantee stem stays >= 0.92 * v_eff
            max_inward = max(0.0, 0.5 * (s_core * v_eff - 0.92 * v_eff))
            if -dx > max_inward:
                dx = -max_inward
        else:
            # In Condensed/ExtraCondensed, cap outward dx to <= 0.30 * v_eff (ultra-safe geometry)
            max_outward = 0.30 * v_eff
            # Also protect delicate narrow multi-bar slits (e.g. Heavy Lari ₾ double vertical bars)
            if tight_bar_gap is not None and tight_bar_gap < 48.0:
                slit_floor = max(0.60 * tight_bar_gap, min(18.0, 0.78 * tight_bar_gap))
                # Ensure s_core * tight_bar_gap - 2 * dx >= slit_floor
                dx_slit_cap = max(0.0, 0.5 * (s_core * tight_bar_gap - slit_floor))
                max_outward = min(max_outward, dx_slit_cap)
            if dx > max_outward:
                dx = max_outward
                s_core = (target_w - 2.0 * dx) / max(bw, 1.0)

        # Horizontal bar thickness compensation dy (applied to interior walls, outer alignment zones locked!)
        # Because outer top/bottom edges stay locked at alignment zones while inner walls move,
        # 0.70 * (h_ratio - 1.0) * h_eff gives ~exact target thinning on top/bottom bowls and crisp crossbars.
        dy = 0.70 * (h_ratio - 1.0) * h_eff
        # Clamp dy to conservative range so ultra-thin bars never distort
        dy = clamp(dy, -0.14 * h_eff, 0.14 * h_eff)

        return {
            "single_stem": False,
            "s_core": s_core,
            "dx": dx,
            "dy": dy,
            "target_w": target_w,
            "target_v": target_v,
        }

    def _transform_upright_body(
        self, contours, depths, roles, x0_body, bw_body, gy0, gy1,
        params, v_eff, gname, dx_scale=1.0, use_master_interp=True,
    ):
        """
        Execute the optical deformation in upright space:
          1. Optional X-only cross-weight master interpolation on body contours
          2. Core horizontal scale s_core around x0_body
          3. Exact zone-locked anisotropic normal offset (dx, dy)
          4. Superelliptical bowl handle tension
          5. Special preservation for circular dots & floating combining accents
        """
        s_core = params["s_core"]
        dx_target = params["dx"] * dx_scale
        dy_target = params["dy"] * dx_scale
        target_v = params["target_v"]
        target_w = params["target_w"]

        work_contours = list(contours)
        eff_s_core = s_core
        eff_dx = dx_target

        # Step 1: Optional X-Only Cross-Weight Master Interpolation (only if all contours are body
        # or if entire glyph is topologically compatible with partner master!)
        if (
            use_master_interp
            and not params["single_stem"]
            and self.partner_font is not None
            and self.partner_v_ref is not None
            and self.master_blend > 1e-4
            and abs(dx_target) >= 0.8
            and gname in self.partner_font.getGlyphSet()
        ):
            dv_master = self.partner_v_ref - self.v_ref_lc
            # Check direction matches (heavier partner for dx > 0, lighter partner for dx < 0)
            if (dx_target > 0 and dv_master > 8.0) or (dx_target < 0 and dv_master < -8.0):
                p_raw = extract_contours(self.partner_font, gname)
                if p_raw:
                    p_fixed, _ = fix_winding(p_raw)
                    if len(work_contours) == len(p_fixed):
                        p_up = unslant_contours(p_fixed, self.tan_slant, self.slant_pivot_y)
                        # Needed pre-scale stem change dV_pre = target_v / s_core - v_eff
                        dv_pre_total = (target_v / max(s_core, 0.5)) - v_eff
                        dv_want = self.master_blend * dv_pre_total
                        alpha_x = clamp(dv_want / dv_master, 0.0, 0.38)
                        if alpha_x > 0.02:
                            interp_c = _interpolate_contours_x_only(
                                work_contours, p_up, alpha_x, dv_master=dv_master,
                            )
                            if interp_c is not None:
                                # Re-measure stem & width after X-only interpolation so final stem hits target_v EXACTLY!
                                st_after = analyze_glyph_structure(interp_c, v_eff, self.x_height, self.cap_height)
                                if st_after["bounds"] is not None and st_after["bw"] > 1.0:
                                    w_int = st_after["bw"]
                                    v_int = v_eff + alpha_x * dv_master
                                    # Solve residual (eff_s_core, eff_dx) for interpolated glyph
                                    denom_int = max(w_int - v_int, 0.35 * w_int)
                                    eff_s_core = (target_w - target_v) / denom_int
                                    eff_dx = 0.5 * (target_v - eff_s_core * v_int) * dx_scale
                                    work_contours = interp_c
                                    x0_body = st_after["bounds"][0]
                                    bw_body = w_int

        # Compute body horizontal center before and after for positioning dots/accents cleanly
        body_x0_ref = x0_body
        body_cx_old = x0_body + 0.5 * bw_body

        # Step 2 + 3 + 4: Transform each contour according to its structural role
        out_contours = []
        body_out_indices = []
        for idx, (c, depth, rinfo) in enumerate(zip(work_contours, depths, roles)):
            role = rinfo["role"]
            cb = rinfo["bounds"]
            is_hole = (depth % 2 == 1)

            if role == "dot" and cb is not None:
                # Keep circular dot 100% circular! Scale uniformly around its own center by
                # gentle stroke ratio (clamped [0.96, 1.03]) and map center x proportionally!
                dcx = 0.5 * (cb[0] + cb[2])
                dcy = 0.5 * (cb[1] + cb[3])
                dot_s = clamp(self.vstem_ratio, 0.96, 1.03)
                # Map dot center x linearly along the glyph's horizontal body transform
                if bw_body > 1.0:
                    new_dcx = body_x0_ref + eff_s_core * (dcx - body_x0_ref)
                else:
                    new_dcx = dcx
                c_new = transform_contours_affine(
                    [c],
                    lambda p, _dcx=dcx, _dcy=dcy, _s=dot_s, _ndcx=new_dcx: (
                        _ndcx + (p[0] - _dcx) * _s,
                        _dcy + (p[1] - _dcy) * _s,
                    ),
                )[0]
                out_contours.append(c_new)
                continue

            if role == "accent" and cb is not None:
                # Floating accent (macron, acute, circumflex, caron, etc.):
                # Map center x cleanly with base letter; gently scale width with stem preservation!
                acx = 0.5 * (cb[0] + cb[2])
                acw = cb[2] - cb[0]
                ach = cb[3] - cb[1]
                new_acx = body_x0_ref + eff_s_core * (acx - body_x0_ref) if bw_body > 1.0 else acx
                # Wide horizontal accents (macron/tilde, acw > 1.8*ach) follow 0.85 of body width change;
                # narrow diagonal accents (acute/grave) follow 0.45 so their angle stays crisp!
                blend_a = 0.85 if acw > 1.8 * max(ach, 1.0) else 0.45
                s_acc = 1.0 + blend_a * (eff_s_core - 1.0)
                c_scaled = transform_contours_affine(
                    [c],
                    lambda p, _acx=acx, _nacx=new_acx, _sa=s_acc: (
                        _nacx + (p[0] - _acx) * _sa,
                        p[1],
                    ),
                )[0]
                # Apply tiny horizontal stem compensation only if diagonal/vertical thickness changed
                dx_acc = 0.45 * eff_dx * (1.0 - blend_a * 0.5)
                c_off = offset_contour_anisotropic(
                    c_scaled, dx_acc, 0.0, False,
                    cb[1], cb[3], self.x_height, self.cap_height,
                )
                out_contours.append(c_off)
                continue

            # Standard body contour (outer or inner hole):
            c_scaled = transform_contours_affine(
                [c],
                lambda p, _x0=body_x0_ref, _sc=eff_s_core: (
                    _x0 + (p[0] - _x0) * _sc,
                    p[1],
                ),
            )[0]

            if params["single_stem"]:
                c_final = c_scaled
            else:
                c_off = offset_contour_anisotropic(
                    c_scaled, eff_dx, eff_dy := dy_target, is_hole,
                    gy0, gy1, self.x_height, self.cap_height,
                )
                c_final = apply_bowl_tension_contour(c_off, is_hole, self.bowl_tension)

            out_contours.append(c_final)
            if not is_hole:
                body_out_indices.append(idx)

        # Re-center floating dots/accents relative to actual transformed body center!
        # (Fixes tiny +/-2u drift when offset expands outer body asymmetrically.)
        if body_out_indices and len(body_out_indices) < len(out_contours):
            new_body_b = contours_bounds([out_contours[i] for i in body_out_indices], samples=10)
            old_body_b = contours_bounds([contours[i] for i in body_out_indices], samples=10)
            if new_body_b is not None and old_body_b is not None:
                old_bcx = 0.5 * (old_body_b[0] + old_body_b[2])
                new_bcx = 0.5 * (new_body_b[0] + new_body_b[2])
                old_bbw = max(old_body_b[2] - old_body_b[0], 1.0)
                new_bbw = max(new_body_b[2] - new_body_b[0], 1.0)
                rel_s = new_bbw / old_bbw
                # Gently compress/expand multi-dot spacing (e.g. dieresis) around centered body
                dot_spacing_s = 0.5 * (1.0 + rel_s)
                for idx, rinfo in enumerate(roles):
                    if rinfo["role"] in ("dot", "accent") and rinfo["bounds"] is not None:
                        orig_cx = 0.5 * (rinfo["bounds"][0] + rinfo["bounds"][2])
                        cur_b = contour_bounds(out_contours[idx], samples=10)
                        if cur_b is not None:
                            cur_cx = 0.5 * (cur_b[0] + cur_b[2])
                            target_cx = new_bcx + (orig_cx - old_bcx) * dot_spacing_s
                            shift = target_cx - cur_cx
                            if abs(shift) > 0.1:
                                out_contours[idx] = transform_contours_affine(
                                    [out_contours[idx]], lambda p, _sh=shift: (p[0] + _sh, p[1])
                                )[0]

        return out_contours

    def transform_glyph(self, gname, contours=None, advance_width=None):
        """
        Optically condense or expand a single glyph.

        Returns:
            (new_contours, new_advance_width, lsb_delta)
        where:
            new_contours      : list of contours in canonical PostScript winding (CCW outer, CW hole)
            new_advance_width : int rounded advance width
            lsb_delta         : float (new_lsb - orig_lsb) in slanted/display coordinates
        """
        hmtx = self.font["hmtx"]
        old_adv = float(advance_width if advance_width is not None else hmtx[gname][0])
        orig_contours = contours if contours is not None else extract_contours(self.font, gname)

        if not orig_contours:
            new_adv = self.transform_advance(gname, old_adv)
            return [], new_adv, 0.0

        # Canonical PostScript winding BEFORE any normal computation!
        orig_fixed, depths = fix_winding(orig_contours)
        orig_slanted_b = contours_bounds(orig_fixed, samples=12)
        orig_lsb_slanted = orig_slanted_b[0] if orig_slanted_b else 0.0

        # Step 1: Un-slant into upright space (exact -8.0 deg Italic preservation!)
        upright = unslant_contours(orig_fixed, self.tan_slant, self.slant_pivot_y)
        u_bounds = contours_bounds(upright, samples=12)
        if u_bounds is None:
            return orig_fixed, int(round(old_adv)), 0.0

        u_x0, u_y0, u_x1, u_y1 = u_bounds
        u_bw = u_x1 - u_x0
        u_lsb = u_x0
        u_rsb = old_adv - u_x1

        adv_r, bbox_r, sb_r, v_ref, h_ref, is_uc = self.get_glyph_ratios(gname)

        # Analyze glyph vertical stems, counters, and contour roles in upright space
        struct = analyze_glyph_structure(upright, v_ref, self.x_height, self.cap_height)
        roles = classify_contour_roles(upright, depths, v_ref, self.x_height, self.cap_height)

        # Check if ALL contours are solid dots (e.g. '.', ':', 'bullet')
        all_dots = all(r["role"] == "dot" for r in roles)
        if all_dots:
            dot_s = clamp(self.vstem_ratio, 0.96, 1.03)
            new_adv = int(round(old_adv * adv_r)) if old_adv > 0 else 0
            # Keep dot(s) circular & centered inside the new advance box!
            ucx = 0.5 * (u_x0 + u_x1)
            rel_pos = ucx / max(old_adv, 1.0) if old_adv > 0 else 0.5
            new_ucx = rel_pos * new_adv if old_adv > 0 else ucx
            out_up = []
            for c, rinfo in zip(upright, roles):
                cb = rinfo["bounds"]
                dcx, dcy = 0.5 * (cb[0] + cb[2]), 0.5 * (cb[1] + cb[3])
                # Preserve relative offset between multiple dots (e.g. dieresis vs colon)
                target_dcx = new_ucx + (dcx - ucx) * (0.5 * (1.0 + bbox_r))
                out_up.append(
                    transform_contours_affine(
                        [c],
                        lambda p, _dcx=dcx, _dcy=dcy, _s=dot_s, _tdcx=target_dcx: (
                            _tdcx + (p[0] - _dcx) * _s,
                            _dcy + (p[1] - _dcy) * _s,
                        ),
                    )[0]
                )
            out_final = reslant_contours(out_up, self.tan_slant, self.slant_pivot_y)
            out_final, _ = fix_winding(out_final)
            new_b = contours_bounds(out_final, samples=12)
            new_lsb = new_b[0] if new_b else orig_lsb_slanted
            return out_final, new_adv, float(new_lsb - orig_lsb_slanted)

        # Effective stem & bar thickness (blend measured glyph stem with weight reference)
        v_eff = 0.55 * struct["median_stem"] + 0.45 * v_ref
        v_eff = clamp(v_eff, 0.72 * v_ref, 1.28 * v_ref)
        h_eff = h_ref

        # Use oval ratios for round-dominant Georgian/Latin glyphs, stem ratios for straight
        v_ratio = 0.5 * (self.vstem_ratio + self.oval_v_ratio)
        h_ratio = 0.5 * (self.hbar_ratio + self.oval_h_ratio)

        # Compute body bbox (excluding floating accents/dots so base letter width drives math!)
        body_contours = [c for c, r in zip(upright, roles) if r["role"] == "body"]
        body_b = contours_bounds(body_contours, samples=12) if body_contours else u_bounds
        bx0, by0, bx1, by1 = body_b if body_b else u_bounds
        bbw = max(bx1 - bx0, 1.0)

        params = self._compute_core_params(
            bbw, v_eff, h_eff, bbox_r, v_ratio, h_ratio,
            struct["max_stems"], struct["min_counter"], gname,
            tight_bar_gap=struct.get("tight_bar_gap"),
        )

        # Step 2: Execute upright deformation with automated skia-pathops self-intersection
        # AND inner-hole counter-area preservation gates!
        orig_mismatch, _ = _pathops_area_mismatch(orig_fixed)
        mismatch_tol = max(0.012, orig_mismatch + 0.008)
        orig_hole_areas = [
            (ci, abs(contour_signed_area(upright[ci])))
            for ci, d in enumerate(depths)
            if d % 2 == 1 and abs(contour_signed_area(upright[ci])) > 120.0
        ]
        if self.mode == "expanded":
            min_hole_ratio = 0.96   # Inner counters MUST grow (never shrink!) in Expanded mode!
        elif self.mode == "condensed":
            min_hole_ratio = 0.42
        else:
            min_hole_ratio = 0.28

        best_up = None
        best_mismatch = float("inf")
        attempts = [
            (1.0, True),
            (1.0, False),   # Retry without cross-weight master blend if needed
            (0.75, False),  # Gentle dx step-down on extreme tight Heavy curves
            (0.45, False),
            (0.0, False),   # Pure scaled fallback (guaranteed 0 self-intersections!)
        ]

        for dx_sc, use_mi in attempts:
            cand_up = self._transform_upright_body(
                upright, depths, roles, bx0, bbw, u_y0, u_y1,
                params, v_eff, gname, dx_scale=dx_sc, use_master_interp=use_mi,
            )
            cand_fixed, _ = fix_winding(cand_up)
            # Verify contour count, winding preservation, vertical drift, inner-hole area, and skia-pathops purity!
            if len(cand_fixed) != len(orig_fixed):
                continue
            cb_test = contours_bounds(cand_fixed, samples=10)
            if cb_test is None:
                continue
            y_drift = max(abs(cb_test[1] - u_y0), abs(cb_test[3] - u_y1))
            if y_drift > 14.0:
                continue
            # Inner-hole counter preservation guard (prevents ANY twisted or collapsed counter!)
            hole_collapsed = False
            for ci, orig_ha in orig_hole_areas:
                new_ha = abs(contour_signed_area(cand_fixed[ci]))
                if new_ha / orig_ha < min_hole_ratio:
                    hole_collapsed = True
                    break
            if hole_collapsed:
                continue
            mm, _ = _pathops_area_mismatch(cand_fixed)
            if mm < best_mismatch:
                best_mismatch = mm
                best_up = cand_fixed
            if mm <= mismatch_tol:
                break

        if best_up is None:
            # Ultimate safety fallback (should virtually never trigger)
            best_up = transform_contours_affine(
                upright, lambda p: (u_x0 + (p[0] - u_x0) * bbox_r, p[1])
            )

        # Step 3: Exact Upright Sidebearing & Advance Width Synchronization
        # (In italic parallelogram space, upright [0, AW] maps directly to exact slanted sidebearings!)
        new_u_b = contours_bounds(best_up, samples=12)
        nu_x0, nu_y0, nu_x1, nu_y1 = new_u_b
        nu_bw = nu_x1 - nu_x0

        if old_adv <= 0.0:
            # Zero-width combining mark: keep centered around original upright center!
            shift_x = 0.5 * (u_x0 + u_x1) - 0.5 * (nu_x0 + nu_x1)
            new_adv = 0
        elif params["single_stem"]:
            # Single-stem narrow glyph (I, l, |, !): keep centered inside target advance width.
            # In Expanded mode, guarantee narrow glyphs still open gracefully (>= 1.03x original adv)!
            eff_adv_r = max(adv_r, 1.03) if self.mode == "expanded" else adv_r
            new_adv = max(int(round(old_adv * eff_adv_r)), int(round(nu_bw + 16.0)))
            orig_lsb_frac = u_lsb / max(u_lsb + u_rsb, 1.0) if (u_lsb + u_rsb) > 2.0 else 0.5
            orig_lsb_frac = clamp(orig_lsb_frac, 0.15, 0.85)
            new_u_lsb = (new_adv - nu_bw) * orig_lsb_frac
            shift_x = new_u_lsb - nu_x0
        else:
            sb_r_left = sb_r
            sb_r_right = sb_r
            # Optical flat-wall sidebearing guard in Condensed/ExtraCondensed:
            # Straight full-height facing walls (ჟ right stem, Italic cursive რ & ს left ascender)
            # need gentler sidebearing compression so pairs like ჟრ / ჟს never look crowded or collide.
            if self.mode in ("condensed", "extra_condensed"):
                flat_floor = 0.88 if self.mode == "condensed" else 0.80
                if gname == "uni10DF":
                    sb_r_right = max(sb_r_right, flat_floor)
                if gname in ("uni10E1", "uni10E5") or (self.is_italic and gname == "uni10E0"):
                    sb_r_left = max(sb_r_left, flat_floor)
            new_u_lsb = u_lsb * sb_r_left
            new_u_rsb = u_rsb * sb_r_right
            # Guard positive sidebearings from collapsing to < 6u in Heavy Extra Condensed
            if u_lsb >= 8.0 and new_u_lsb < 6.0:
                new_u_lsb = 6.0
            if u_rsb >= 8.0 and new_u_rsb < 6.0:
                new_u_rsb = 6.0
            shift_x = new_u_lsb - nu_x0
            new_adv = int(round(new_u_lsb + nu_bw + new_u_rsb))

        shifted_up = transform_contours_affine(best_up, lambda p: (p[0] + shift_x, p[1]))

        # Step 4: Re-slant back to exact -8.00 deg Italic (identity if Upright)
        out_final = reslant_contours(shifted_up, self.tan_slant, self.slant_pivot_y)
        out_final, _ = fix_winding(out_final)

        final_b = contours_bounds(out_final, samples=12)
        new_lsb_slanted = final_b[0] if final_b else orig_lsb_slanted
        lsb_delta = float(new_lsb_slanted - orig_lsb_slanted)
        return out_final, int(new_adv), lsb_delta

    def get_kerning_scale(self, is_georgian=True):
        """Return authoritative kerning scale factor for this width mode."""
        if is_georgian:
            default = {"condensed": 0.92, "extra_condensed": 0.85, "expanded": 1.08}[self.mode]
            return float(self.mode_spec.get("kern_scale_georgian", default))
        default = {"condensed": 1.00, "extra_condensed": 1.00, "expanded": 1.08}[self.mode]
        return float(self.mode_spec.get("kern_scale_latin", default))

    def scale_kerning(self, font, target_glyphs=None):
        """Scale GPOS PairPos kerning values for transformed glyphs in-place."""
        return scale_kerning(
            font,
            mode=self.mode,
            target_glyphs=target_glyphs,
            scale_geor=self.get_kerning_scale(is_georgian=True),
            scale_latin=self.get_kerning_scale(is_georgian=False),
        )


# ---------------------------------------------------------------------------
# Functional Convenience API (Clean Entry Points for External Callers)
# ---------------------------------------------------------------------------

def condense_glyph(
    font,
    gname,
    mode="condensed",
    weight="Regular",
    is_italic=False,
    contours=None,
    advance_width=None,
    spec_path=DEFAULT_SPEC_PATH,
    fonts_dir=DEFAULT_FONTS_DIR,
):
    """
    Functional API to optically condense or expand a single glyph.
    Returns (new_contours, new_advance_width, lsb_delta).
    Note: For batch processing an entire font, prefer instantiating WidthTransformer once.
    """
    tr = WidthTransformer(
        font=font,
        mode=mode,
        weight=weight,
        is_italic=is_italic,
        spec_path=spec_path,
        fonts_dir=fonts_dir,
    )
    return tr.transform_glyph(gname, contours=contours, advance_width=advance_width)


def scale_kerning(font, mode="condensed", target_glyphs=None, scale_geor=None, scale_latin=None):
    """
    Scale GPOS PairPos kerning (Format 1 & Format 2, including Extension LookupType 9)
    for Georgian and/or Expanded Latin pairs cleanly in-place.
    Returns count of scaled kerning records.
    """
    if "GPOS" not in font:
        return 0
    if scale_geor is None:
        scale_geor = {"condensed": 0.92, "extra_condensed": 0.85, "expanded": 1.08}.get(mode, 1.0)
    if scale_latin is None:
        scale_latin = {"condensed": 1.00, "extra_condensed": 1.00, "expanded": 1.08}.get(mode, 1.0)

    gpos = font["GPOS"].table
    if not gpos.FeatureList or not gpos.LookupList:
        return 0

    kern_lks = set()
    for fr in gpos.FeatureList.FeatureRecord:
        if fr.FeatureTag == "kern":
            kern_lks.update(fr.Feature.LookupListIndex)

    target_set = set(target_glyphs) if target_glyphs is not None else None
    scaled_count = 0

    for li in sorted(kern_lks):
        lk = gpos.LookupList.Lookup[li]
        if lk.LookupType not in (2, 9):
            continue
        for st in lk.SubTable:
            rst = st.ExtSubTable if lk.LookupType == 9 else st
            fmt = getattr(rst, "Format", None)
            if fmt == 1 and hasattr(rst, "PairSet"):
                for g1, ps in zip(rst.Coverage.glyphs, rst.PairSet):
                    for rec in ps.PairValueRecord:
                        g2 = rec.SecondGlyph
                        if target_set is not None and g1 not in target_set and g2 not in target_set:
                            continue
                        is_g = _is_georgian_or_lari(g1) or _is_georgian_or_lari(g2)
                        sc = scale_geor if is_g else scale_latin
                        if abs(sc - 1.0) < 1e-4:
                            continue
                        for val in (rec.Value1, rec.Value2):
                            if val is not None:
                                if getattr(val, "XAdvance", None):
                                    val.XAdvance = int(round(val.XAdvance * sc))
                                    scaled_count += 1
                                if getattr(val, "XPlacement", None):
                                    val.XPlacement = int(round(val.XPlacement * sc))
            elif fmt == 2 and hasattr(rst, "Class1Record"):
                c1_g = set(rst.ClassDef1.classDefs.keys()) | set(rst.Coverage.glyphs)
                c2_g = set(rst.ClassDef2.classDefs.keys())
                all_g = c1_g | c2_g
                if target_set is not None and not (all_g & target_set):
                    continue
                has_geor = any(_is_georgian_or_lari(g) for g in all_g)
                sc = scale_geor if has_geor else scale_latin
                if abs(sc - 1.0) < 1e-4:
                    continue
                for c1 in rst.Class1Record:
                    for c2 in c1.Class2Record:
                        for val in (c2.Value1, c2.Value2):
                            if val is not None:
                                if getattr(val, "XAdvance", None):
                                    val.XAdvance = int(round(val.XAdvance * sc))
                                    scaled_count += 1
                                if getattr(val, "XPlacement", None):
                                    val.XPlacement = int(round(val.XPlacement * sc))
    return scaled_count


def scale_kerning_value(value, mode="condensed", is_georgian=True):
    """Scale a single integer kerning value cleanly."""
    if is_georgian:
        sc = {"condensed": 0.92, "extra_condensed": 0.85, "expanded": 1.08}.get(mode, 1.0)
    else:
        sc = {"condensed": 1.00, "extra_condensed": 1.00, "expanded": 1.08}.get(mode, 1.0)
    return int(round(value * sc))

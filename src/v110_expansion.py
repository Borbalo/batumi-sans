#!/usr/bin/env python3
"""
Batumi Sans v1.100+ Complete Native Expansion Module (+49 Pure Native Batumi Glyphs):
  1. Caucasus & Modern Currencies (+4, exact tabular currency width):
       - U+20BC ₼ (uni20BC, Azerbaijani Manat)
       - U+058F ֏ (uni058F, Armenian Dram)
       - U+20B8 ₸ (uni20B8, Kazakhstani Tenge)
       - U+20BF ₿ (uni20BF, Bitcoin)
  2. Complete Keycaps & Map/UI Micro-Icons (+10, parametric):
       - U+2318 ⌘ (uni2318, Command / Place of Interest — analytic 1-outer + 5-hole topology!)
       - U+2325 ⌥ (uni2325, Option / Alt)
       - U+2303 ⌃ (uni2303, Control / Up Arrowhead)
       - U+238B ⎋ (uni238B, Escape / Broken Circle + NW Arrow)
       - U+21E5 ⇥ (uni21E5, Tab / Rightwards Arrow to Bar)
       - U+21E4 ⇤ (uni21E4, Backtab / Leftwards Arrow to Bar)
       - U+2713 ✓ (uni2713, Check Mark)
       - U+2715 ✕ (uni2715, Multiplication X)
       - U+2605 ★ (uni2605, Filled Star)
       - U+2606 ☆ (uni2606, Outline Star)
  3. Complete Google Fonts `shape_languages` 0-FAIL Closure (+35 native Latin & Cyrillic):
       - Bandial Latin (`bqj_Latn`): U+2C63 Ᵽ, U+1D7D ᵽ
       - Moro Latin (`mor_Latn`):    U+A7C7 Ꟈ, U+A7C8 ꟈ
       - Khanty Cyrillic (`kca_Cyrl`): U+1C89 Ᲊ, U+1C8A ᲊ
       - Zenaga Latin (`zen_Latn`):  U+02C1 ˁ
       - Uduk Latin (`udu_Latn`):    U+035F ◌͟◌ (combining double macron below, GDEF mark + GPOS!)
       - Teso Latin (`teo_Latn`):    U+1D43 ᵃ, U+1D49 ᵉ, U+2071 ⁱ, U+1D52 ᵒ, U+1D58 ᵘ,
                                     U+1D4B ᵋ, U+1D53 ᵓ, U+1DA4 ᶤ, U+1DB6 ᶶ
       - Church Slavic (`cu_Cyrl`):  U+0480 Ҁ, U+0481 ҁ, U+047A Ѻ, U+047B ѻ, U+047C Ѽ,
                                     U+047D ѽ, U+047E Ѿ, U+047F ѿ, U+A640 Ꙁ, U+A641 ꙁ,
                                     U+A642 Ꙃ, U+A643 ꙃ, U+A64A Ꙋ, U+A64B ꙋ, U+A64C Ꙍ,
                                     U+A64D ꙍ, U+A656 Ꙗ, U+A657 ꙗ

Every single glyph is 100% native Batumi Sans geometry, Sharp + Rounded (κ=0.580),
-8° Italic slant calibrated, and strictly locked to fixed VF contour topology across all 16 masters!
"""

import math
import pathops

from keycaps import (
    HOLLOW_SW,
    SINGLE_SW,
    WIDTH_SCALE,
    _arc_cubic,
    _rounded_polygon_contour,
    _sharp_polygon_contour,
)
from latin_extended_primes import (
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
    reverse_contour,
    round_contours,
)

# All 49 new codepoints -> canonical glyph names (all valid_glyphnames compliant!)
CURRENCY_4_CPS = (0x20BC, 0x058F, 0x20B8, 0x20BF)
KEYCAP_UI_10_CPS = (0x2318, 0x2325, 0x2303, 0x238B, 0x21E5, 0x21E4, 0x2713, 0x2715, 0x2605, 0x2606)
SHAPE_LANG_35_CPS = (
    0x2C63, 0x1D7D,  # Bandial Ᵽ ᵽ
    0xA7C7, 0xA7C8,  # Moro Ꟈ ꟈ
    0x1C89, 0x1C8A,  # Khanty Ᲊ ᲊ
    0x02C1,          # Zenaga ˁ
    0x035F,          # Uduk ◌͟◌ (mark!)
    0x1D43, 0x1D49, 0x2071, 0x1D52, 0x1D58, 0x1D4B, 0x1D53, 0x1DA4, 0x1DB6,  # Teso 9
    0x0480, 0x0481, 0x047A, 0x047B, 0x047C, 0x047D, 0x047E, 0x047F,  # Church Slavic 8
    0xA640, 0xA641, 0xA642, 0xA643, 0xA64A, 0xA64B, 0xA64C, 0xA64D, 0xA656, 0xA657,  # Church Slavic 10
)

EXPANSION_49_CPS = CURRENCY_4_CPS + KEYCAP_UI_10_CPS + SHAPE_LANG_35_CPS
EXPANSION_49_GLYPH_NAMES = tuple(f"uni{cp:04X}" for cp in EXPANSION_49_CPS)
EXPANSION_LATIN_MARKBASE_CPS = (0x2C63, 0x1D7D, 0xA7C7, 0xA7C8)
EXPANSION_CYRL_MARKBASE_CPS = (
    0x1C89, 0x1C8A, 0x0480, 0x0481, 0x047A, 0x047B, 0x047C, 0x047D, 0x047E, 0x047F,
    0xA640, 0xA641, 0xA642, 0xA643, 0xA64A, 0xA64B, 0xA64C, 0xA64D, 0xA656, 0xA657,
)

KAPPA_90 = 4.0 / 3.0 * (math.sqrt(2.0) - 1.0)


# ---------------------------------------------------------------------------
# Low-Level Geometry Primitives (rounder format: ('line', (p0,p1)), ('curve', (p0,c1,c2,p3)))
# ---------------------------------------------------------------------------

def _kc_to_rounder(contours):
    """Convert keycaps.py ('cubic', ...) segments into rounder.py ('curve', ...) format."""
    out = []
    for c in contours:
        out.append([("curve" if k == "cubic" else k, pts) for k, pts in c])
    return out


def _rect_ccw(x0, y0, x1, y1, r=0.0):
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    if r <= 0.5:
        return _kc_to_rounder([_sharp_polygon_contour(pts)])[0]
    r_eff = min(r, 0.49 * (x1 - x0), 0.49 * (y1 - y0))
    return _kc_to_rounder([_rounded_polygon_contour(pts, [r_eff] * 4)])[0]


def _rect_ccw_radii(x0, y0, x1, y1, r_bl=0.0, r_br=0.0, r_tr=0.0, r_tl=0.0, start_corner=0):
    """CCW axis-aligned rectangle with per-corner rounding and selectable starting corner (0=BL,1=BR,2=TR,3=TL)."""
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    rs = [r_bl, r_br, r_tr, r_tl]
    sc = start_corner % 4
    if sc:
        pts = pts[sc:] + pts[:sc]
        rs = rs[sc:] + rs[:sc]
    if max(rs) <= 0.5:
        return _kc_to_rounder([_sharp_polygon_contour(pts)])[0]
    lim = min(0.49 * (x1 - x0), 0.49 * (y1 - y0))
    rs = [min(lim, max(0.0, rv)) for rv in rs]
    return _kc_to_rounder([_rounded_polygon_contour(pts, rs)])[0]


def _contour_polyline_pts(contour, steps=16):
    """Flatten a rounder-format ('curve' or 'cubic') contour into a dense closed polyline for exact ray-slice measurements."""
    pts = []
    for kind, seg in contour:
        if kind == "line":
            pts.append(seg[0])
        elif kind in ("curve", "cubic"):
            p0, p1, p2, p3 = seg
            for k in range(steps):
                t = k / float(steps)
                mt = 1.0 - t
                x = mt * mt * mt * p0[0] + 3.0 * mt * mt * t * p1[0] + 3.0 * mt * t * t * p2[0] + t * t * t * p3[0]
                y = mt * mt * mt * p0[1] + 3.0 * mt * mt * t * p1[1] + 3.0 * mt * t * t * p2[1] + t * t * t * p3[1]
                pts.append((x, y))
    return pts


def _horizontal_x_bounds_at_y(contours, y_val):
    """Return sorted x-coordinates where contours cross horizontal line y = y_val."""
    xs = []
    for c in contours:
        poly = _contour_polyline_pts(c, steps=20)
        n = len(poly)
        for i in range(n):
            x0, y0 = poly[i]
            x1, y1 = poly[(i + 1) % n]
            if (y0 <= y_val < y1) or (y1 <= y_val < y0):
                t = (y_val - y0) / (y1 - y0)
                xs.append(x0 + t * (x1 - x0))
    xs.sort()
    return xs


def _vertical_y_bounds_at_x(contours, x_val):
    """Return sorted y-coordinates where contours cross vertical line x = x_val."""
    ys = []
    for c in contours:
        poly = _contour_polyline_pts(c, steps=20)
        n = len(poly)
        for i in range(n):
            x0, y0 = poly[i]
            x1, y1 = poly[(i + 1) % n]
            if (x0 <= x_val < x1) or (x1 <= x_val < x0):
                t = (x_val - x0) / (x1 - x0)
                ys.append(y0 + t * (y1 - y0))
    ys.sort()
    return ys


def _stroked_bar_one_cap(p_free, p_weld, sw, rounded=False):
    """
    Stroked bar from free outer tip `p_free` (starting vertex OUTSIDE stem; semicircular pill cap in Rounded)
    to welded end `p_weld` (always flat-cut so zero hidden cap overlap inside parent contour!).
    """
    dx, dy = p_weld[0] - p_free[0], p_weld[1] - p_free[1]
    L = math.hypot(dx, dy)
    if L < 1e-6:
        return []
    ux, uy = dx / L, dy / L
    nx, ny = -uy, ux
    hw = 0.5 * sw
    th = math.atan2(dy, dx)
    # CCW: a0 (free-right) -> a1 (weld-right) -> b1 (weld-left) -> b0 (free-left) -> cap -> a0
    a0 = (p_free[0] - nx * hw, p_free[1] - ny * hw)
    a1 = (p_weld[0] - nx * hw, p_weld[1] - ny * hw)
    b1 = (p_weld[0] + nx * hw, p_weld[1] + ny * hw)
    b0 = (p_free[0] + nx * hw, p_free[1] + ny * hw)
    if not rounded:
        return [("line", (a0, a1)), ("line", (a1, b1)), ("line", (b1, b0)), ("line", (b0, a0))]
    c0a = _arc_cubic(p_free, hw, th + math.pi * 0.5, th + math.pi)
    c0b = _arc_cubic(p_free, hw, th + math.pi, th + math.pi * 1.5)
    return [
        ("line", (a0, a1)),
        ("line", (a1, b1)),
        ("line", (b1, b0)),
        ("curve", (b0, c0a[1][1], c0a[1][2], c0a[1][3])),
        ("curve", (c0b[1][0], c0b[1][1], c0b[1][2], a0)),
    ]


def _stroked_cross_x(r_x, cy, sw, rounded=False):
    """Exact single-contour 12-vertex CCW 45° X (`✕`), 0.00% self-intersection across all weights & Rounded!"""
    hw = 0.5 * sw
    d = hw / math.sqrt(2.0)
    c = hw * math.sqrt(2.0)
    # CCW starting from right crotch -> TR arm -> top crotch -> TL arm -> left crotch -> BL arm -> bottom crotch -> BR arm
    pts = [
        (c, cy),
        (r_x + d, cy + r_x - d),
        (r_x - d, cy + r_x + d),
        (0.0, cy + c),
        (-r_x + d, cy + r_x + d),
        (-r_x - d, cy + r_x - d),
        (-c, cy),
        (-r_x - d, cy - r_x + d),
        (-r_x + d, cy - r_x - d),
        (0.0, cy - c),
        (r_x - d, cy - r_x - d),
        (r_x + d, cy - r_x + d),
    ]
    if not rounded:
        return _kc_to_rounder([_sharp_polygon_contour(pts)])[0]
    r_tip = hw * 0.96
    r_in = hw * 0.14
    radii = [r_in, r_tip, r_tip, r_in, r_tip, r_tip, r_in, r_tip, r_tip, r_in, r_tip, r_tip]
    return _kc_to_rounder([_rounded_polygon_contour(pts, radii)])[0]


def _stroked_arrow(p_tail, p_tip, ch_d, sw, rounded=False):
    """
    Exact single-contour 9-vertex CCW unified arrow (shaft + 90° chevron head) from `p_tail` to `p_tip`,
    with chevron arm length `ch_d` (projected along & perpendicular to axis): 0.00% overlap in Sharp & Rounded!
    """
    dx, dy = p_tip[0] - p_tail[0], p_tip[1] - p_tail[1]
    L = max(1e-6, math.hypot(dx, dy))
    ux, uy = dx / L, dy / L
    nx, ny = -uy, ux  # left normal
    hw = 0.5 * sw
    d = hw / math.sqrt(2.0)
    # Local coordinates: u along arrow (0 at p_tail, L at p_tip), v along left normal
    u_elbow = L - 2.0 * d - hw
    local_pts = [
        (0.0, -hw),                              # 0: tail bottom
        (u_elbow, -hw),                          # 1: lower shaft/wing crotch
        (L - ch_d - d, -ch_d + d),               # 2: lower wing inner tip
        (L - ch_d + d, -ch_d - d),               # 3: lower wing outer tip
        (L + 2.0 * d, 0.0),                      # 4: arrow outer nose
        (L - ch_d + d, ch_d + d),                # 5: upper wing outer tip
        (L - ch_d - d, ch_d - d),                # 6: upper wing inner tip
        (u_elbow, hw),                           # 7: upper shaft/wing crotch
        (0.0, hw),                               # 8: tail top
    ]
    pts = [(p_tail[0] + u * ux + v * nx, p_tail[1] + u * uy + v * ny) for u, v in local_pts]
    if not rounded:
        return _kc_to_rounder([_sharp_polygon_contour(pts)])[0]
    r_tip = hw * 0.96
    r_nose = hw * 0.72
    r_crotch = hw * 0.14
    radii = [r_tip, r_crotch, r_tip, r_tip, r_nose, r_tip, r_tip, r_crotch, r_tip]
    return _kc_to_rounder([_rounded_polygon_contour(pts, radii)])[0]


def _quad_ccw_midstart(x0, y0, x1_bot, x1_top, y1):
    """CCW horizontal bridge quad starting at bottom midpoint (in open gap -> 0 winding flags!)."""
    xm = 0.5 * (x0 + min(x1_bot, x1_top))
    pts = [(xm, y0), (x1_bot, y0), (x1_top, y1), (x0, y1), (x0, y0)]
    return _kc_to_rounder([_sharp_polygon_contour(pts)])[0]


def _stroked_bar(p0, p1, sw, rounded=False):
    """Single stroked bar from p0 to p1 of width sw, flat-cut (Sharp) or semicircular pill-capped (Rounded)."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    L = math.hypot(dx, dy)
    if L < 1e-6:
        return []
    ux, uy = dx / L, dy / L
    nx, ny = -uy, ux
    hw = 0.5 * sw
    th = math.atan2(dy, dx)
    a0 = (p0[0] - nx * hw, p0[1] - ny * hw)
    a1 = (p1[0] - nx * hw, p1[1] - ny * hw)
    b1 = (p1[0] + nx * hw, p1[1] + ny * hw)
    b0 = (p0[0] + nx * hw, p0[1] + ny * hw)
    if not rounded:
        return [("line", (a0, a1)), ("line", (a1, b1)), ("line", (b1, b0)), ("line", (b0, a0))]
    # Semicircular pill caps (2 cubics per cap)
    c1a = _arc_cubic(p1, hw, th - math.pi * 0.5, th)
    c1b = _arc_cubic(p1, hw, th, th + math.pi * 0.5)
    c0a = _arc_cubic(p0, hw, th + math.pi * 0.5, th + math.pi)
    c0b = _arc_cubic(p0, hw, th + math.pi, th + math.pi * 1.5)
    return [
        ("line", (a0, a1)),
        ("curve", (a1, c1a[1][1], c1a[1][2], c1a[1][3])),
        ("curve", (c1b[1][0], c1b[1][1], c1b[1][2], b1)),
        ("line", (b1, b0)),
        ("curve", (b0, c0a[1][1], c0a[1][2], c0a[1][3])),
        ("curve", (c0b[1][0], c0b[1][1], c0b[1][2], a0)),
    ]


def _stroked_polyline(pts, sw, rounded=False):
    """
    Analytic mitered/rounded open polyline of constant stroke width sw (CCW closed contour,
    100% locked topology across all weights/widths!).
    """
    n = len(pts)
    assert n >= 2
    hw = 0.5 * sw
    # Compute unit directions & left normals per segment
    us, ns = [], []
    for i in range(n - 1):
        dx, dy = pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]
        L = max(1e-6, math.hypot(dx, dy))
        u = (dx / L, dy / L)
        us.append(u)
        ns.append((-u[1], u[0]))

    def _miter_pt(p, n1, n2, sign):
        # Intersection of offset lines p + sign*hw*n1 along u1 and p + sign*hw*n2 along u2
        bx = n1[0] + n2[0]
        by = n1[1] + n2[1]
        bl = math.hypot(bx, by)
        if bl < 1e-4:
            return (p[0] + sign * hw * n1[0], p[1] + sign * hw * n1[1])
        ux_b, uy_b = bx / bl, by / bl
        denom = ux_b * n1[0] + uy_b * n1[1]
        miter_len = min(hw * 2.2, hw / max(0.35, abs(denom)))
        return (p[0] + sign * miter_len * ux_b, p[1] + sign * miter_len * uy_b)

    # Right side forward (sign = -1), left side backward (sign = +1) -> CCW!
    right_pts = [(pts[0][0] - hw * ns[0][0], pts[0][1] - hw * ns[0][1])]
    left_pts = [(pts[0][0] + hw * ns[0][0], pts[0][1] + hw * ns[0][1])]
    for i in range(1, n - 1):
        right_pts.append(_miter_pt(pts[i], ns[i - 1], ns[i], -1.0))
        left_pts.append(_miter_pt(pts[i], ns[i - 1], ns[i], +1.0))
    right_pts.append((pts[-1][0] - hw * ns[-1][0], pts[-1][1] - hw * ns[-1][1]))
    left_pts.append((pts[-1][0] + hw * ns[-1][0], pts[-1][1] + hw * ns[-1][1]))

    poly = right_pts + list(reversed(left_pts))
    if not rounded:
        return _kc_to_rounder([_sharp_polygon_contour(poly)])[0]
    # Rounded: pill-radius caps at start & end + smooth corner joins at bends
    radii = []
    m = len(poly)
    for i in range(m):
        if i in (0, len(right_pts) - 1, len(right_pts), m - 1):
            radii.append(hw * 0.96)
        else:
            radii.append(hw * 0.65)
    return _kc_to_rounder([_rounded_polygon_contour(poly, radii)])[0]


def _circle_contour(cx, cy, r, cw=False):
    k = r * KAPPA_90
    if not cw:
        # CCW: right -> top -> left -> bottom -> right
        p0, p1, p2, p3 = (cx + r, cy), (cx, cy + r), (cx - r, cy), (cx, cy - r)
        return [
            ("curve", (p0, (cx + r, cy + k), (cx + k, cy + r), p1)),
            ("curve", (p1, (cx - k, cy + r), (cx - r, cy + k), p2)),
            ("curve", (p2, (cx - r, cy - k), (cx - k, cy - r), p3)),
            ("curve", (p3, (cx + k, cy - r), (cx + r, cy - k), p0)),
        ]
    else:
        p0, p1, p2, p3 = (cx + r, cy), (cx, cy - r), (cx - r, cy), (cx, cy + r)
        return [
            ("curve", (p0, (cx + r, cy - k), (cx + k, cy - r), p1)),
            ("curve", (p1, (cx - k, cy - r), (cx - r, cy - k), p2)),
            ("curve", (p2, (cx - r, cy + k), (cx - k, cy + r), p3)),
            ("curve", (p3, (cx + k, cy + r), (cx + r, cy + k), p0)),
        ]


def _stroked_arc(cx, cy, r_mid, sw, a_start_deg, a_end_deg, n_segs=4, rounded=False):
    """
    Exact circular arc stroke from a_start_deg to a_end_deg (CCW positive sweep),
    constant thickness sw, flat or semicircular pill caps!
    """
    r_out = r_mid + 0.5 * sw
    r_in = max(8.0, r_mid - 0.5 * sw)
    a0 = math.radians(a_start_deg)
    a1 = math.radians(a_end_deg)
    step = (a1 - a0) / n_segs
    segs = []
    # Outer arc forward
    for i in range(n_segs):
        t0 = a0 + i * step
        t1 = t0 + step
        segs.append(_kc_to_rounder([[_arc_cubic((cx, cy), r_out, t0, t1)]])[0][0])
    # End cap at a1
    p_end_out = (cx + r_out * math.cos(a1), cy + r_out * math.sin(a1))
    p_end_in = (cx + r_in * math.cos(a1), cy + r_in * math.sin(a1))
    if not rounded:
        segs.append(("line", (p_end_out, p_end_in)))
    else:
        cap_c = (cx + r_mid * math.cos(a1), cy + r_mid * math.sin(a1))
        hw = 0.5 * sw
        c1 = _arc_cubic(cap_c, hw, a1, a1 + math.pi * 0.5)
        c2 = _arc_cubic(cap_c, hw, a1 + math.pi * 0.5, a1 + math.pi)
        segs.append(("curve", (p_end_out, c1[1][1], c1[1][2], c1[1][3])))
        segs.append(("curve", (c2[1][0], c2[1][1], c2[1][2], p_end_in)))
    # Inner arc backward
    for i in range(n_segs - 1, -1, -1):
        t1 = a0 + (i + 1) * step
        t0 = a0 + i * step
        segs.append(_kc_to_rounder([[_arc_cubic((cx, cy), r_in, t1, t0)]])[0][0])
    # Start cap at a0
    p_st_in = (cx + r_in * math.cos(a0), cy + r_in * math.sin(a0))
    p_st_out = (cx + r_out * math.cos(a0), cy + r_out * math.sin(a0))
    if not rounded:
        segs.append(("line", (p_st_in, p_st_out)))
    else:
        cap_c = (cx + r_mid * math.cos(a0), cy + r_mid * math.sin(a0))
        hw = 0.5 * sw
        c1 = _arc_cubic(cap_c, hw, a0 + math.pi, a0 + math.pi * 1.5)
        c2 = _arc_cubic(cap_c, hw, a0 + math.pi * 1.5, a0 + math.pi * 2.0)
        segs.append(("curve", (p_st_in, c1[1][1], c1[1][2], c1[1][3])))
        segs.append(("curve", (c2[1][0], c2[1][1], c2[1][2], p_st_out)))
    return segs


def _shear_contours(contours, tan_a, y_piv=264.0):
    if abs(tan_a) < 1e-9:
        return contours
    return _transform_contours(contours, lambda p: (p[0] + (p[1] - y_piv) * tan_a, p[1]))


def _scale_contours(contours, sx, sy, px=0.0, py=0.0):
    return _transform_contours(contours, lambda p: (px + (p[0] - px) * sx, py + (p[1] - py) * sy))


def _mirror_contours_x(contours, cx):
    """Mirror contours horizontally around x=cx and reverse winding to keep CFF CCW-outer/CW-inner!"""
    out = []
    for c in contours:
        mc = [(k, tuple((2.0 * cx - p[0], p[1]) for p in pts)) for k, pts in c]
        out.append(reverse_contour(mc))
    return out


def _safe_round(contours, sharp_metrics, rounded):
    if not rounded or not contours:
        return contours
    cand = round_contours(contours, sharp_metrics, enable_outer_corners=True, enable_overshoot=True)
    cand, _ = fix_disjoint_outer_winding(cand)
    if len(cand) == len(contours):
        try:
            p = pathops.Path()
            draw_contours_to_pen(cand, p.getPen())
            p2 = pathops.Path(p)
            p2.simplify()
            a0 = abs(sum(contour_signed_area(c) for c in cand))
            if a0 <= 1e-3 or abs(abs(p2.area) - a0) / max(a0, 1.0) < 0.03:
                return cand
        except Exception:
            pass
    return contours


def _add_cmap_mapping(font, cp, gname):
    for sub in font["cmap"].tables:
        if sub.isUnicode():
            if sub.format == 4 and cp <= 0xFFFF:
                sub.cmap[cp] = gname
            elif sub.format == 12:
                sub.cmap[cp] = gname


# ---------------------------------------------------------------------------
# 1. Caucasus & Modern Currencies (+4: ₼ ֏ ₸ ₿)
# ---------------------------------------------------------------------------

def _build_currencies_4(font, src_font, sharp_metrics, weight_class, width_mode, is_italic, rounded):
    tan_a = math.tan(math.radians(8.0)) if is_italic else 0.0
    vstem = float(sharp_metrics.get("stem_w", 92.0))
    hbar = vstem * 0.85
    bb_H = _contours_bbox(extract_contours(src_font, "H"))
    cap_h = float(bb_H[3]) if bb_H else 689.0

    # Exact tabular currency advance width matching euro / uni20BE / dollar
    if "euro" in font["hmtx"].metrics:
        tab_adv = int(font["hmtx"]["euro"][0])
    elif "uni20BE" in font["hmtx"].metrics:
        tab_adv = int(font["hmtx"]["uni20BE"][0])
    else:
        tab_adv = 500
    cx_adv = 0.5 * tab_adv

    bar_r = (0.46 * hbar) if rounded else 0.0
    stem_r = (0.46 * min(vstem, hbar)) if rounded else 0.0
    sw_bar = max(18.0, hbar * 0.86)
    sw_v = max(18.0, vstem * 0.84)

    # (a) U+20BF ₿ (Bitcoin): Batumi 'B' centered in tab_adv + twin vertical currency bars top & bottom
    cs_B = extract_contours(font, "B")
    cs_B, _ = fix_disjoint_outer_winding(cs_B)
    # Un-slant, slightly refine vertical fit so twin bars poke cleanly above & below like $ and ₾
    cs_B_u = _shear_contours(cs_B, -tan_a, 345.0)
    bb_B = _contours_bbox(cs_B_u)
    w_B = bb_B[2] - bb_B[0]
    target_w_B = min(w_B, tab_adv * 0.84)
    sx_B = target_w_B / max(1.0, w_B)
    cs_B_u = _scale_contours(cs_B_u, sx_B, 0.91, 0.5 * (bb_B[0] + bb_B[2]), 0.5 * (bb_B[1] + bb_B[3]))
    bb_B2 = _contours_bbox(cs_B_u)
    dx_B = cx_adv - 0.5 * (bb_B2[0] + bb_B2[2])
    dy_B = 345.0 - 0.5 * (bb_B2[1] + bb_B2[3])
    cs_B_u = _translate_contours(cs_B_u, dx_B, dy_B)
    bb_B2 = _contours_bbox(cs_B_u)
    bw_B = bb_B2[2] - bb_B2[0]
    x_bar1 = bb_B2[0] + 0.30 * bw_B
    x_bar2 = bb_B2[0] + 0.58 * bw_B
    bar_w_btc = max(16.0, min(sw_v * 0.72, (x_bar2 - x_bar1) * 0.44))
    y_bot_btc = -45.0
    y_top_btc = cap_h + 45.0
    # Four clean protruding stubs (top1, top2, bot1, bot2) welded 6u into B's exact top/bottom rails
    # (flat weld on stem end, pill on free tip, outer start_corner -> <0.5% overlap & 0 winding flags!)
    x_bar2 = bb_B2[0] + 0.55 * bw_B
    r_btc = (0.45 * bar_w_btc) if rounded else 0.0
    btc_bars = []
    for xb in (x_bar1, x_bar2):
        xl_b, xr_b = xb - 0.5 * bar_w_btc, xb + 0.5 * bar_w_btc
        ys_l = _vertical_y_bounds_at_x(cs_B_u, xl_b + 0.5)
        ys_r = _vertical_y_bounds_at_x(cs_B_u, xr_b - 0.5)
        y_top_weld = min(ys_l[-1] if ys_l else bb_B2[3], ys_r[-1] if ys_r else bb_B2[3]) - 6.0
        y_bot_weld = max(ys_l[0] if ys_l else bb_B2[1], ys_r[0] if ys_r else bb_B2[1]) + 6.0
        btc_bars.append(_rect_ccw_radii(
            xl_b, y_top_weld, xr_b, y_top_btc,
            r_bl=0.0, r_br=0.0, r_tr=r_btc, r_tl=r_btc, start_corner=2,
        ))
        btc_bars.append(_rect_ccw_radii(
            xl_b, y_bot_btc, xr_b, y_bot_weld,
            r_bl=r_btc, r_br=r_btc, r_tr=0.0, r_tl=0.0, start_corner=0,
        ))
    cs_btc = _shear_contours(cs_B_u + btc_bars, tan_a, 345.0)
    cs_btc, _ = fix_disjoint_outer_winding(cs_btc)
    _upsert_cff_glyph(font, "uni20BF", cs_btc, tab_adv, gdef_class=1)
    _add_cmap_mapping(font, 0x20BF, "uni20BF")

    # (b) U+20B8 ₸ (Kazakhstani Tenge): Batumi 'T' scaled cleanly + crisp upper parallel bar
    cs_T = extract_contours(font, "T")
    cs_T, _ = fix_disjoint_outer_winding(cs_T)
    cs_T_u = _shear_contours(cs_T, -tan_a, 345.0)
    bb_T = _contours_bbox(cs_T_u)
    w_T = bb_T[2] - bb_T[0]
    target_w_T = min(w_T, tab_adv * 0.86)
    sx_T = target_w_T / max(1.0, w_T)
    # Leave room for upper bar + clean white gap at top of CapH
    bar_gap = max(38.0, min(72.0, 95.0 - 0.25 * hbar))
    top_bar_h = max(18.0, hbar * 0.92)
    t_top_target = cap_h - top_bar_h - bar_gap
    sy_T = t_top_target / max(1.0, bb_T[3])
    cs_T_u = _scale_contours(cs_T_u, sx_T, sy_T, 0.5 * (bb_T[0] + bb_T[2]), 0.0)
    bb_T2 = _contours_bbox(cs_T_u)
    cs_T_u = _translate_contours(cs_T_u, cx_adv - 0.5 * (bb_T2[0] + bb_T2[2]), 0.0)
    bb_T2 = _contours_bbox(cs_T_u)
    upper_bar = _rect_ccw(bb_T2[0], cap_h - top_bar_h, bb_T2[2], cap_h, r=(0.45 * top_bar_h if rounded else 0.0))
    cs_tenge = _shear_contours(cs_T_u + [upper_bar], tan_a, 345.0)
    cs_tenge, _ = fix_disjoint_outer_winding(cs_tenge)
    _upsert_cff_glyph(font, "uni20B8", cs_tenge, tab_adv, gdef_class=1)
    _add_cmap_mapping(font, 0x20B8, "uni20B8")

    # (c) U+20BC ₼ (Azerbaijani Manat): Full-weight humanist arch ∩ + central vertical stroke stopping
    # cleanly ABOVE the baseline (does NOT go all the way down to y=0!) and rising cleanly to CapH + 20.
    sx_w = WIDTH_SCALE.get(width_mode, 1.0)
    sw_m = max(18.0, vstem * 0.90)
    t_wt = max(0.0, min(1.0, (vstem - 92.0) / 100.0))
    sw_mv = max(16.0, sw_m * (0.86 - 0.08 * t_wt))
    # Guarantee crisp open counter bays between outer arch legs & middle stroke across Thin..Heavy & XCon..Exp
    min_bay = max(56.0 * sx_w, min(140.0 * sx_w, (168.0 - 0.52 * vstem) * sx_w))
    arch_w = max(tab_adv * 0.82, 2.0 * sw_m + sw_mv + 2.0 * min_bay)
    sb_m = max(36.0 * sx_w, 46.0 * sx_w)
    manat_adv = max(tab_adv, int(round(arch_w + 2.0 * sb_m)))
    cx_m = 0.5 * manat_adv
    r_mid_m = 0.5 * (arch_w - sw_m)
    r_out = r_mid_m + 0.5 * sw_m
    r_in = max(16.0, r_mid_m - 0.5 * sw_m)
    # Arch crown at 0.885 * cap_h (harmonious height beside 100 & crisp ~95u upper protrusion matching ₾ & $)
    cy_m = (cap_h * 0.885) - r_out
    x_lo = cx_m - r_out
    x_li = cx_m - r_in
    x_ri = cx_m + r_in
    x_ro = cx_m + r_out
    a_out1 = _kc_to_rounder([[_arc_cubic((cx_m, cy_m), r_out, 0.0, math.pi * 0.5)]])[0][0]
    a_out2 = _kc_to_rounder([[_arc_cubic((cx_m, cy_m), r_out, math.pi * 0.5, math.pi)]])[0][0]
    a_in1 = _kc_to_rounder([[_arc_cubic((cx_m, cy_m), r_in, math.pi, math.pi * 0.5)]])[0][0]
    a_in2 = _kc_to_rounder([[_arc_cubic((cx_m, cy_m), r_in, math.pi * 0.5, 0.0)]])[0][0]
    arch_c = [
        ("line", ((x_lo, 0.0), (x_li, 0.0))),
        ("line", ((x_li, 0.0), (x_li, cy_m))),
        a_in1,
        a_in2,
        ("line", ((x_ri, cy_m), (x_ri, 0.0))),
        ("line", ((x_ri, 0.0), (x_ro, 0.0))),
        ("line", ((x_ro, 0.0), (x_ro, cy_m))),
        a_out1,
        a_out2,
        ("line", ((x_lo, cy_m), (x_lo, 0.0))),
    ]
    if rounded:
        arch_c = _safe_round([arch_c], sharp_metrics, True)[0]
    # Split central vertical stroke cleanly at outer chord & inner apex (<= 1.2% weld overlap, ZERO white crescent gap!)
    # Flat-welded into arch crown, semicircular pill-capped at free top & bottom tips in Rounded!
    half_mv = 0.5 * sw_mv
    y_outer_chord = cy_m + math.sqrt(max(1.0, r_out * r_out - half_mv * half_mv))
    y_top_m = cap_h + 20.0
    y_bot_m = cap_h * 0.175  # clearly stops short of baseline y=0 (never looks like lowercase 'm'!)
    r_mv = (0.46 * sw_mv) if rounded else 0.0
    mid_top = _rect_ccw_radii(
        cx_m - half_mv, y_outer_chord - 6.0, cx_m + half_mv, y_top_m,
        r_bl=0.0, r_br=0.0, r_tr=r_mv, r_tl=r_mv, start_corner=2,
    )
    mid_bot = _rect_ccw_radii(
        cx_m - half_mv, y_bot_m, cx_m + half_mv, cy_m + r_in + 6.0,
        r_bl=r_mv, r_br=r_mv, r_tr=0.0, r_tl=0.0, start_corner=0,
    )
    cs_manat = _shear_contours([arch_c, mid_top, mid_bot], tan_a, 345.0)
    cs_manat, _ = fix_disjoint_outer_winding(cs_manat)
    _upsert_cff_glyph(font, "uni20BC", cs_manat, manat_adv, gdef_class=1)
    _add_cmap_mapping(font, 0x20BC, "uni20BC")

    # (d) U+058F ֏ (Armenian Dram): Full-weight authentic open Դ-arch (free left leg) + generous twin bars
    # crossing ONLY right stem with long crisp right-side overhang (+110–138u in Normal, scaled by width)!
    sw_d = max(18.0, vstem * 0.90)
    min_bay_d = max(132.0 * sx_w, min(255.0 * sx_w, (280.0 - 0.68 * vstem) * sx_w))
    dram_w = max(tab_adv * 0.76, 2.0 * sw_d + min_bay_d)
    r_mid_d = 0.50 * (dram_w - sw_d)
    r_out_d = r_mid_d + 0.5 * sw_d
    r_in_d = max(24.0, r_mid_d - 0.5 * sw_d)
    # Generous right-side bar overhang unmistakable even in Heavy & Rounded ExtraCondensed!
    ext_r = max(88.0 * sx_w, min(142.0 * sx_w, (108.0 + 0.16 * vstem) * sx_w))
    sb_dl = max(36.0 * sx_w, 46.0 * sx_w)
    sb_dr = max(34.0 * sx_w, 44.0 * sx_w)
    dram_adv = max(int(round(tab_adv * 1.04)), int(round(sb_dl + dram_w + ext_r + sb_dr)))
    x_left_d = 0.5 * (dram_adv - (dram_w + ext_r))
    cx_d = x_left_d + r_out_d
    cy_d = cap_h - r_out_d
    # Free-hanging left leg terminates cleanly at y ≈ 0.50 * cap_h (completely clear above twin bars!)
    y_hook_end = min(cy_d - 14.0, cap_h * 0.50)
    d_out1 = _kc_to_rounder([[_arc_cubic((cx_d, cy_d), r_out_d, 0.0, math.pi * 0.5)]])[0][0]
    d_out2 = _kc_to_rounder([[_arc_cubic((cx_d, cy_d), r_out_d, math.pi * 0.5, math.pi)]])[0][0]
    d_in1 = _kc_to_rounder([[_arc_cubic((cx_d, cy_d), r_in_d, math.pi, math.pi * 0.5)]])[0][0]
    d_in2 = _kc_to_rounder([[_arc_cubic((cx_d, cy_d), r_in_d, math.pi * 0.5, 0.0)]])[0][0]
    dram_body = [
        ("line", ((cx_d - r_out_d, y_hook_end), (cx_d - r_in_d, y_hook_end))),
        ("line", ((cx_d - r_in_d, y_hook_end), (cx_d - r_in_d, cy_d))),
        d_in1,
        d_in2,
        ("line", ((cx_d + r_in_d, cy_d), (cx_d + r_in_d, 0.0))),
        ("line", ((cx_d + r_in_d, 0.0), (cx_d + r_out_d, 0.0))),
        ("line", ((cx_d + r_out_d, 0.0), (cx_d + r_out_d, cy_d))),
        d_out1,
        d_out2,
        ("line", ((cx_d - r_out_d, cy_d), (cx_d - r_out_d, y_hook_end))),
    ]
    if rounded:
        dram_body = _safe_round([dram_body], sharp_metrics, True)[0]
    # Twin horizontal bars crossing ONLY the right vertical stem — split flush at stem faces (<= 1.0% weld overlap!)
    # with generous left-inward reach + generous right-outward overhang (+ext_r) & crisp >= 72u white gap!
    bh_d = max(15.0, min(hbar * 0.68, 78.0))
    white_gap_d = max(72.0, min(104.0, 112.0 - 0.18 * hbar))
    center_dist_d = bh_d + white_gap_d
    y_mid_d = cap_h * 0.315
    x_stem_l = cx_d + r_in_d
    x_stem_r = cx_d + r_out_d
    # Left end extends generously into open bay while staying well clear of free-hanging left leg
    ext_l = max(76.0 * sx_w, min(2.0 * r_in_d - 52.0 * sx_w, (118.0 + 0.08 * vstem) * sx_w))
    x_bar_l = x_stem_l - ext_l
    x_bar_r = x_stem_r + ext_r
    r_bd = (0.46 * bh_d) if rounded else 0.0
    dram_bars = []
    for y_c in (y_mid_d + 0.5 * center_dist_d, y_mid_d - 0.5 * center_dist_d):
        y0b, y1b = y_c - 0.5 * bh_d, y_c + 0.5 * bh_d
        # Left wing (pill on left free tip, flat weld into right stem's left face, outer start_corner=0)
        dram_bars.append(_rect_ccw_radii(
            x_bar_l, y0b, x_stem_l + 6.0, y1b,
            r_bl=r_bd, r_br=0.0, r_tr=0.0, r_tl=r_bd, start_corner=0,
        ))
        # Right wing (flat weld into right stem's right face, pill on right free tip, outer start_corner=1)
        dram_bars.append(_rect_ccw_radii(
            x_stem_r - 6.0, y0b, x_bar_r, y1b,
            r_bl=0.0, r_br=r_bd, r_tr=r_bd, r_tl=0.0, start_corner=1,
        ))
    cs_dram = _shear_contours([dram_body] + dram_bars, tan_a, 345.0)
    cs_dram, _ = fix_disjoint_outer_winding(cs_dram)
    _upsert_cff_glyph(font, "uni058F", cs_dram, dram_adv, gdef_class=1)
    _add_cmap_mapping(font, 0x058F, "uni058F")


# ---------------------------------------------------------------------------
# 2. Complete Keycaps & Map/UI Micro-Icons (+10: ⌘ ⌥ ⌃ ⎋ ⇥ ⇤ ✓ ✕ ★ ☆)
# ---------------------------------------------------------------------------

def _build_command_symbol(sw, sx, cy, rounded):
    """
    True G1-tangent Analytic 1-outer + 5-inner-hole Saint John's Arms (`⌘`, U+2318):
    ZERO overlaps, ZERO self-intersections across ALL weights (Thin 100..Heavy 900!),
    100% locked fixed VF topology across all 16 masters!
    Geometry: central hollow square with centerline `x=±a`, `y=±a` extending tangentially
    to `(±d, ±d)` (`d = a + r_c`), joined smoothly with 270° circular corner loops of
    radius `r_out = r_c + hw` (outer) and teardrop corner holes of radius `r_in = r_c - hw`.
    Every straight segment has strictly positive length (`2*(a-hw) > 0` and `r_in > 0`)
    for every `0 < hw < min(a, r_c)` — mathematically immune to Thin bow-tie crossovers!
    """
    total_h = 630.0
    span = total_h - sw
    # Keep inner loop hole nicely open even in Heavy (sw=78u): r_c >= 0.5*sw + 34u!
    r_c = max(0.145 * span, 0.5 * sw + 34.0)
    a = max(0.5 * sw + 42.0, 0.5 * span - 2.0 * r_c)
    hw = 0.5 * sw
    r_out = r_c + hw
    r_in = max(14.0, r_c - hw)
    d = a + r_c  # center offset of each corner loop: (±d, ±d)

    def _arc_segs(cx_l, cy_l, r, ang0, ang1, n=3):
        step = (ang1 - ang0) / float(n)
        return [
            _kc_to_rounder([[_arc_cubic((cx_l, cy_l), r, ang0 + i * step, ang0 + (i + 1) * step)]])[0][0]
            for i in range(n)
        ]

    def _rot(x, y, k):
        for _ in range(k % 4):
            x, y = -y, x
        return (x, cy + y)

    # 1. Single 4-fold symmetric CCW outer contour (24 segments: 12 lines + 12 90° cubics):
    #    For k=0 (Right wall -> Top-Right 270° loop -> Right-bar left edge down to Top wall):
    #      (a+hw, -(a-hw)) -> (a+hw, +(a-hw)) -> (d, +(a-hw)) --[270° CCW]--> (a-hw, d) -> (a-hw, +(a+hw))
    outer = []
    for k in range(4):
        p0 = _rot(a + hw, -(a - hw), k)
        p1 = _rot(a + hw, +(a - hw), k)
        p2 = _rot(d, +(a - hw), k)
        p3 = _rot(a - hw, d, k)
        p4 = _rot(a - hw, +(a + hw), k)
        cx_l, cy_l = _rot(d, d, k)
        ang0 = (1.5 + 0.5 * k) * math.pi
        ang1 = ang0 + 1.5 * math.pi
        outer.append(("line", (p0, p1)))
        outer.append(("line", (p1, p2)))
        outer.extend(_arc_segs(cx_l, cy_l, r_out, ang0, ang1, n=3))
        outer.append(("line", (p3, p4)))

    # 2. 5 CW inner holes: central square + 4 tangent teardrop corner loop holes!
    sq_in = reverse_contour(_rect_ccw(-(a - hw), cy - (a - hw), (a - hw), cy + (a - hw), r=0.0))
    holes = [sq_in]
    for k in range(4):
        c0 = _rot(a + hw, a + hw, k)
        c1 = _rot(a + hw, d, k)
        c2 = _rot(d, a + hw, k)
        cx_l, cy_l = _rot(d, d, k)
        ang0 = (1.0 + 0.5 * k) * math.pi
        ang1 = ang0 - 1.5 * math.pi
        h = [("line", (c0, c1))] + _arc_segs(cx_l, cy_l, r_in, ang0, ang1, n=3) + [("line", (c2, c0))]
        holes.append(h)

    contours = [outer] + holes
    return _scale_contours(contours, sx, 1.0, 0.0, cy)


def _build_star_contours(r_out, r_in, cy, sx, rounded=False, hollow_sw=0.0):
    """5-pointed star (solid ★ or concentric hollow ☆), exact fixed VF topology!"""
    pts = []
    for k in range(10):
        ang = math.pi * 0.5 + k * (math.pi / 5.0)  # CCW starting from top tip
        r = r_out if (k % 2 == 0) else r_in
        pts.append((r * math.cos(ang) * sx, cy + r * math.sin(ang)))
    if not rounded:
        outer = _kc_to_rounder([_sharp_polygon_contour(pts)])[0]
    else:
        radii = [22.0 if (k % 2 == 0) else 14.0 for k in range(10)]
        outer = _kc_to_rounder([_rounded_polygon_contour(pts, radii)])[0]
    if hollow_sw <= 0.0:
        return [outer]
    # Exact geometric inset along angle bisectors for uniform wall thickness `hollow_sw`!
    # At outer tip (half-angle ~ 18°), inset distance along ray is hollow_sw / sin(18°) -> clamp cleanly
    # Using concentric uniform scale ratio that preserves sharp star geometry cleanly across all weights:
    scale_in = max(0.32, 1.0 - (hollow_sw * 2.35) / r_out)
    pts_in = [
        (r * scale_in * math.cos(math.pi * 0.5 + k * math.pi / 5.0) * sx,
         cy + r * scale_in * math.sin(math.pi * 0.5 + k * math.pi / 5.0))
        for k, r in enumerate([r_out if k % 2 == 0 else r_in for k in range(10)])
    ]
    pts_in_cw = list(reversed(pts_in))
    if not rounded:
        inner = _kc_to_rounder([_sharp_polygon_contour(pts_in_cw)])[0]
    else:
        radii_in = [10.0 if (k % 2 == 0) else 8.0 for k in range(10)]
        inner = _kc_to_rounder([_rounded_polygon_contour(pts_in_cw, radii_in)])[0]
    return [outer, inner]


def _build_keycaps_ui_10(font, src_font, weight_class, width_mode, is_italic, rounded):
    sx = WIDTH_SCALE.get(width_mode, 1.0)
    sw_h = HOLLOW_SW[weight_class]
    sw_s = SINGLE_SW[weight_class]
    tan_a = math.tan(math.radians(8.0)) if is_italic else 0.0
    cy = 345.0
    sb = round(84.0 * sx)

    def _finish(cp, contours, custom_sb=None):
        cs = _shear_contours(contours, tan_a, cy)
        cs, _ = fix_disjoint_outer_winding(cs)
        bb = _contours_bbox(cs)
        eff_sb = sb if custom_sb is None else custom_sb
        dx = eff_sb - bb[0]
        cs = _translate_contours(cs, dx, 0.0)
        adv = int(round((bb[2] - bb[0]) + 2.0 * eff_sb))
        gname = f"uni{cp:04X}"
        _upsert_cff_glyph(font, gname, cs, adv, gdef_class=1)
        _add_cmap_mapping(font, cp, gname)

    # 1. U+2318 ⌘ Command
    _finish(0x2318, _build_command_symbol(sw_h, sx, cy, rounded))

    # 2. U+2325 ⌥ Option (upper-left -> diagonal -> lower-right + upper-right horizontal bar)
    w_opt = 620.0 * sx
    h_opt = 420.0
    y_top, y_bot = cy + 0.5 * h_opt, cy - 0.5 * h_opt
    main_opt = _stroked_polyline(
        [(-0.5 * w_opt, y_top), (-0.18 * w_opt, y_top), (0.16 * w_opt, y_bot), (0.5 * w_opt, y_bot)],
        sw_s * 0.88, rounded=rounded,
    )
    bar_opt = _stroked_bar((0.12 * w_opt, y_top), (0.5 * w_opt, y_top), sw_s * 0.88, rounded=rounded)
    _finish(0x2325, [main_opt, bar_opt])

    # 3. U+2303 ⌃ Control (crisp upward chevron)
    w_ctl = 470.0 * sx
    h_ctl = 270.0
    ctl_c = _stroked_polyline(
        [(-0.5 * w_ctl, cy - 0.35 * h_ctl), (0.0, cy + 0.65 * h_ctl), (0.5 * w_ctl, cy - 0.35 * h_ctl)],
        sw_s * 0.90, rounded=rounded,
    )
    _finish(0x2303, [ctl_c])

    # 4. U+238B ⎋ Escape (open 266° circular arc with gap in NW quadrant + unified 0.00%-overlap NW arrow!)
    r_esc = 248.0 * min(1.04, max(0.88, sx))
    sw_e = sw_h * 1.02
    # Gap centered at 135° (NW): arc runs CCW from 182° -> 448° (= 88°) = 266° sweep (clean generous gap!)
    arc_e = _stroked_arc(0.0, cy, r_esc, sw_e, 182.0, 448.0, n_segs=4, rounded=rounded)
    ang_nw = math.radians(135.0)
    u_nw = (math.cos(ang_nw), math.sin(ang_nw))
    p_tip = (u_nw[0] * (r_esc + 0.65 * sw_e), cy + u_nw[1] * (r_esc + 0.65 * sw_e))
    p_tail = (-u_nw[0] * (r_esc * 0.04), cy - u_nw[1] * (r_esc * 0.04))
    # Chevron projection along arrow axis = arm_l / sqrt(2) -> exact 45° wings matching previous arm_l!
    ch_d_e = (r_esc * 0.60) / math.sqrt(2.0)
    arrow_e = _stroked_arrow(p_tail, p_tip, ch_d_e, sw_e, rounded=rounded)
    _finish(0x238B, [arc_e, arrow_e])

    # 5 & 6. U+21E5 ⇥ Tab & U+21E4 ⇤ Backtab (unified 0.00%-overlap arrow + crisp vertical bar!)
    w_tab = 580.0 * sx
    h_tab = 430.0
    sw_t = sw_s * 0.88
    x_bar = 0.44 * w_tab
    x_tip = x_bar - 1.15 * sw_t
    vbar = _stroked_bar((x_bar, cy - 0.5 * h_tab), (x_bar, cy + 0.5 * h_tab), sw_t, rounded=rounded)
    ch_d = 185.0 * min(1.04, max(0.88, sx))
    arrow_r = _stroked_arrow((-0.48 * w_tab, cy), (x_tip, cy), ch_d, sw_t, rounded=rounded)
    tab_r = [vbar, arrow_r]
    _finish(0x21E5, tab_r)
    tab_l = _mirror_contours_x(tab_r, 0.0)
    _finish(0x21E4, tab_l)

    # 7. U+2713 ✓ Check Mark
    w_chk = 530.0 * sx
    h_chk = 460.0
    chk_c = _stroked_polyline(
        [(-0.46 * w_chk, cy - 0.06 * h_chk), (-0.12 * w_chk, cy - 0.46 * h_chk), (0.48 * w_chk, cy + 0.50 * h_chk)],
        sw_s * 0.92, rounded=rounded,
    )
    _finish(0x2713, [chk_c])

    # 8. U+2715 ✕ Multiplication X (single unified 12-vertex CCW cross -> 0.00% overlap!)
    r_x = 225.0 * min(1.04, max(0.88, sx))
    sw_x = sw_s * 0.90
    x_cross = _stroked_cross_x(r_x, cy, sw_x, rounded=rounded)
    _finish(0x2715, [x_cross])

    # 9 & 10. U+2605 ★ Filled Star & U+2606 ☆ Outline Star (matching 1:1 silhouette!)
    r_star = 300.0
    r_in_star = r_star * 0.405
    _finish(0x2605, _build_star_contours(r_star, r_in_star, cy - 12.0, sx, rounded=rounded, hollow_sw=0.0))
    _finish(0x2606, _build_star_contours(r_star, r_in_star, cy - 12.0, sx, rounded=rounded, hollow_sw=sw_h * 0.92))


# ---------------------------------------------------------------------------
# 3. Complete Google Fonts `shape_languages` 0-FAIL Closure (+35 Native Glyphs)
# ---------------------------------------------------------------------------

def _build_shape_languages_35(font, src_font, sharp_metrics, weight_class, width_mode, is_italic, rounded):
    tan_a = math.tan(math.radians(8.0)) if is_italic else 0.0
    vstem = float(sharp_metrics.get("stem_w", 92.0))
    hbar = vstem * 0.85
    bb_H = _contours_bbox(extract_contours(src_font, "H"))
    bb_x = _contours_bbox(extract_contours(src_font, "x"))
    cap_h = float(bb_H[3]) if bb_H else 689.0
    x_h = float(bb_x[3]) if bb_x else 527.0
    bar_h = max(16.0, min(92.0, hbar * 0.78))
    bar_r = (0.45 * bar_h) if rounded else 0.0

    def _put(cp, contours, adv, gdef_class=1, fix_winding=True):
        cs = fix_disjoint_outer_winding(contours)[0] if fix_winding else contours
        gn = f"uni{cp:04X}"
        _upsert_cff_glyph(font, gn, cs, int(round(adv)), gdef_class=gdef_class)
        _add_cmap_mapping(font, cp, gn)

    def _get_u(gn, y_piv=264.0):
        cs = extract_contours(font, gn)
        cs, _ = fix_disjoint_outer_winding(cs)
        return _shear_contours(cs, -tan_a, y_piv), float(font["hmtx"][gn][0])

    def _split_stem_bar(cs_base, y_c, x_l_bar, x_r_bar, h_bar, r_bar, use_rightmost_stem=False):
        """Split a horizontal stem-crossing bar into flush left/right wings (<=0.5% overlap, 0 winding flags!)."""
        y0b, y1b = y_c - 0.5 * h_bar, y_c + 0.5 * h_bar
        xs_mid = _horizontal_x_bounds_at_y(cs_base, y_c)
        xs_bot = _horizontal_x_bounds_at_y(cs_base, y0b + 1.0)
        xs_top = _horizontal_x_bounds_at_y(cs_base, y1b - 1.0)
        if len(xs_mid) >= 2:
            idx = (len(xs_mid) - 2) if use_rightmost_stem else 0
            sl = max(
                xs_mid[idx],
                xs_bot[idx] if len(xs_bot) > idx else xs_mid[idx],
                xs_top[idx] if len(xs_top) > idx else xs_mid[idx],
            )
            sr = min(
                xs_mid[idx + 1],
                xs_bot[idx + 1] if len(xs_bot) > idx + 1 else xs_mid[idx + 1],
                xs_top[idx + 1] if len(xs_top) > idx + 1 else xs_mid[idx + 1],
            )
        else:
            bb = _contours_bbox(cs_base)
            sl = (bb[2] - vstem) if use_rightmost_stem else bb[0]
            sr = bb[2] if use_rightmost_stem else (bb[0] + vstem)
        w_l = _rect_ccw_radii(
            x_l_bar, y0b, sl + 5.0, y1b,
            r_bl=r_bar, r_br=0.0, r_tr=0.0, r_tl=r_bar, start_corner=0,
        )
        w_r = _rect_ccw_radii(
            sr - 5.0, y0b, x_r_bar, y1b,
            r_bl=0.0, r_br=r_bar, r_tr=r_bar, r_tl=0.0, start_corner=1,
        )
        return [w_l, w_r]

    # --- A. Bandial (Ᵽ ᵽ) & Moro (Ꟈ ꟈ) — native P/p/D/d + crisp flush-welded stroke wings ---
    # U+2C63 Ᵽ: Capital P + horizontal stroke across lower stem
    cs_P, adv_P = _get_u("P", 345.0)
    bb_P = _contours_bbox(cs_P)
    y_sp = bb_P[1] + 0.24 * cap_h
    bars_P = _split_stem_bar(cs_P, y_sp, bb_P[0] - 0.85 * vstem, bb_P[0] + 1.85 * vstem, bar_h, bar_r)
    _put(0x2C63, _shear_contours(cs_P + bars_P, tan_a, 345.0), adv_P)

    # U+1D7D ᵽ: Small p + horizontal stroke across descender stem
    cs_p, adv_p = _get_u("p", 264.0)
    bb_p = _contours_bbox(cs_p)
    y_spp = -0.14 * cap_h
    bars_p = _split_stem_bar(cs_p, y_spp, bb_p[0] - 0.80 * vstem, bb_p[0] + 1.80 * vstem, bar_h, bar_r)
    _put(0x1D7D, _shear_contours(cs_p + bars_p, tan_a, 264.0), adv_p)

    # U+A7C7 Ꟈ: Capital D + short stroke overlay across left vertical stem
    # (right wing sits inside D's depth-2 inner counter -> clamp cleanly inside counter & keep explicit CCW winding!)
    cs_D, adv_D = _get_u("D", 345.0)
    bb_D = _contours_bbox(cs_D)
    y_sd = 0.50 * cap_h
    xs_D = _horizontal_x_bounds_at_y(cs_D, y_sd)
    x_d_right_lim = (xs_D[2] - 26.0) if len(xs_D) >= 4 else (bb_D[0] + 1.90 * vstem)
    x_d_r = min(bb_D[0] + 1.90 * vstem, max((xs_D[1] + 24.0) if len(xs_D) >= 2 else (bb_D[0] + vstem + 24.0), x_d_right_lim))
    bars_D = _split_stem_bar(cs_D, y_sd, bb_D[0] - 0.90 * vstem, x_d_r, bar_h, bar_r)
    _put(0xA7C7, _shear_contours(cs_D + bars_D, tan_a, 345.0), adv_D, fix_winding=False)

    # U+A7C8 ꟈ: Small d + short stroke overlay across right ascender stem
    cs_d, adv_d = _get_u("d", 264.0)
    bb_d = _contours_bbox(cs_d)
    y_sdd = x_h + 0.52 * (bb_d[3] - x_h)
    bars_d = _split_stem_bar(
        cs_d, y_sdd, bb_d[2] - 1.85 * vstem, bb_d[2] + 0.85 * vstem, bar_h, bar_r, use_rightmost_stem=True
    )
    _put(0xA7C8, _shear_contours(cs_d + bars_d, tan_a, 264.0), adv_d)

    # --- B. Khanty Cyrillic Tje (Ᲊ ᲊ: U+1C89 / U+1C8A) — Т/т + flush right-attached Ь/ь C-bowl! ---
    # Single-contour C-bowl calibrated directly from native Ь/ь metrics (<0.8% weld overlap, 0 winding flags!)
    for cp, g_T, g_B, y_piv in ((0x1C89, "uni0422", "uni042C", 345.0), (0x1C8A, "uni0442", "uni044C", 264.0)):
        cs_T, adv_T = _get_u(g_T, y_piv)
        cs_B, adv_B = _get_u(g_B, y_piv)
        bb_T = _contours_bbox(cs_T)
        bb_B = _contours_bbox(cs_B)
        h_T = bb_T[3] - bb_T[1]
        # Measure exact rightmost vertical stem face & crossbar bottom of Т/т
        # (handles both 1-stem upright Т/т and 3-legged cursive Italic т cleanly!)
        xs_stem = _horizontal_x_bounds_at_y(cs_T, 0.25 * h_T)
        x_stem_l = xs_stem[-2] if len(xs_stem) >= 2 else (0.5 * (bb_T[0] + bb_T[2]) - 0.5 * vstem)
        x_stem_r = xs_stem[-1] if len(xs_stem) >= 2 else (0.5 * (bb_T[0] + bb_T[2]) + 0.5 * vstem)
        # Measure crossbar underside at right wing of Т/т (if present)
        ys_cross = _vertical_y_bounds_at_x(cs_T, min(bb_T[2] - 10.0, x_stem_r + 0.4 * (bb_T[2] - x_stem_r))) if (bb_T[2] - x_stem_r) > 25.0 else []
        y_cross_bot = ys_cross[0] if ys_cross else (bb_T[3] - hbar)
        # Extract native Ь/ь bowl proportions (outer vs inner counter)
        if len(cs_B) >= 2:
            b_areas = sorted([(abs(contour_signed_area(c)), c) for c in cs_B], key=lambda t: -t[0])
            bb_bo = _contours_bbox([b_areas[0][1]])
            bb_bi = _contours_bbox([b_areas[1][1]])
            h_rail = max(14.0, bb_bi[1] - bb_bo[1])
            v_wall = max(16.0, bb_bo[2] - bb_bi[2])
            bowl_protr = max(v_wall + 40.0, (bb_bo[2] - bb_bi[0]) * 0.90)
            bowl_h_nat = (bb_bi[3] + h_rail) * 0.92
        else:
            h_rail = max(14.0, hbar * 0.85)
            v_wall = max(16.0, vstem * 0.95)
            bowl_protr = max(v_wall + 50.0, 0.55 * (bb_B[2] - bb_B[0]))
            bowl_h_nat = 0.58 * h_T
        bowl_h = min(y_cross_bot - max(36.0, 0.35 * hbar), max(2.2 * h_rail + 28.0, bowl_h_nat))
        y_mid_b = 0.5 * bowl_h
        r_out_y = 0.5 * bowl_h
        r_in_y = max(12.0, r_out_y - h_rail)
        r_out_x = min(r_out_y * 1.05, max(v_wall + 24.0, bowl_protr * 0.68))
        r_in_x = max(10.0, r_out_x - v_wall)
        x_out_r = x_stem_r + bowl_protr
        x_in_r = x_out_r - v_wall
        x_oc = x_out_r - r_out_x  # horizontal straight-to-curve transition on outer bowl
        x_ic = x_in_r - r_in_x    # horizontal straight-to-curve transition on inner counter
        # Weld bottom-left cleanly into Т's rounded foot if Rounded (avoiding bottom corner notch!)
        x_weld_top = x_stem_r - 6.0
        xs_bot = _horizontal_x_bounds_at_y(cs_T, 4.0)
        x_weld_bot = (xs_bot[-1] - 6.0) if (rounded and len(xs_bot) >= 2 and xs_bot[-1] < x_stem_r) else (x_stem_r - 6.0)
        x_weld_bot = max(0.5 * (x_stem_l + x_stem_r) + 2.0, min(x_stem_r - 6.0, x_weld_bot))
        kx_o, ky_o = r_out_x * KAPPA_90, r_out_y * KAPPA_90
        kx_i, ky_i = r_in_x * KAPPA_90, r_in_y * KAPPA_90
        # Start at rightmost outer point (OUTSIDE Т/т -> 0 winding flags!), trace CCW!
        p_or = (x_out_r, y_mid_b)
        p_ot = (x_oc, bowl_h)
        p_ob = (x_oc, 0.0)
        p_ir = (x_in_r, y_mid_b)
        p_it = (x_ic, bowl_h - h_rail)
        p_ib = (x_ic, h_rail)
        bowl_c = [
            ("curve", (p_or, (x_out_r, y_mid_b + ky_o), (x_oc + kx_o, bowl_h), p_ot)),
            ("line", (p_ot, (x_weld_top, bowl_h))),
            ("line", ((x_weld_top, bowl_h), (x_weld_top, bowl_h - h_rail))),
            ("line", ((x_weld_top, bowl_h - h_rail), p_it)),
            ("curve", (p_it, (x_ic + kx_i, bowl_h - h_rail), (x_in_r, y_mid_b + ky_i), p_ir)),
            ("curve", (p_ir, (x_in_r, y_mid_b - ky_i), (x_ic + kx_i, h_rail), p_ib)),
            ("line", (p_ib, (x_weld_top, h_rail))),
            ("line", ((x_weld_top, h_rail), (x_weld_bot, 0.0))),
            ("line", ((x_weld_bot, 0.0), p_ob)),
            ("curve", (p_ob, (x_oc + kx_o, 0.0), (x_out_r, y_mid_b - ky_o), p_or)),
        ]
        bb_comb = _contours_bbox(cs_T + [bowl_c])
        rsb_ref = max(35.0, adv_B - bb_B[2])
        adv_out = max(adv_T, bb_comb[2] + rsb_ref)
        _put(cp, _shear_contours(cs_T + [bowl_c], tan_a, y_piv), adv_out)

    # --- C. Zenaga (ˁ U+02C1) — Horizontal mirror of existing uni02C0 (ˀ) ---
    cs_2c0, adv_2c0 = _get_u("uni02C0", 480.0)
    bb_2c0 = _contours_bbox(cs_2c0)
    cs_2c1 = _mirror_contours_x(cs_2c0, 0.5 * (bb_2c0[0] + bb_2c0[2]))
    _put(0x02C1, _shear_contours(cs_2c1, tan_a, 480.0), adv_2c0)

    # --- D. Uduk Combining Double Macron Below (U+035F uni035F) — GDEF class 3 mark ---
    cs_331 = extract_contours(src_font, "uni0331")
    cs_331, _ = fix_disjoint_outer_winding(cs_331)
    cs_35f = _scale_contours_x_center(cs_331, 1.95, is_italic=is_italic)
    bb_35f = _contours_bbox(cs_35f)
    cy_35f = 0.5 * (bb_35f[1] + bb_35f[3])
    # Center across x=0 along Italic slant (matches uni035C / uni0360 convention!)
    target_cx = (cy_35f - 0.0) * tan_a
    cs_35f = _translate_contours(cs_35f, target_cx - 0.5 * (bb_35f[0] + bb_35f[2]), 0.0)
    if rounded:
        cs_35f = _round_mark_contours("uni035F", cs_35f, sharp_metrics)
    _put(0x035F, cs_35f, 0, gdef_class=3)

    # --- E. Teso 9 Superscript Modifier Letters (ᵃ ᵉ ⁱ ᵒ ᵘ ᵋ ᵓ ᶤ ᶶ) ---
    # Calibrated to match existing superscripts (`ordfeminine` / `uni02C0` top ≈ cap_h + 15)
    sup_top = cap_h + 14.0
    sup_scale = 0.58
    teso_map = (
        (0x1D43, "a"),
        (0x1D49, "e"),
        (0x2071, "i"),
        (0x1D52, "o"),
        (0x1D58, "u"),
        (0x1D4B, "uni025B"),
        (0x1D53, "uni0254"),
        (0x1DA4, "uni0268"),
        (0x1DB6, "uni0289"),
    )
    for cp, donor in teso_map:
        cs_d, adv_d = _get_u(donor, 264.0)
        bb_d = _contours_bbox(cs_d)
        # Scale slightly wider horizontally (0.61 x 0.57) for optical superscript weight preservation
        sx_s = 0.61
        sy_s = 0.57
        cs_s = _scale_contours(cs_d, sx_s, sy_s, bb_d[0], 0.0)
        bb_s = _contours_bbox(cs_s)
        # Place bottom at cap_h - 0.57*x_h (aligning top of x-height superscripts cleanly to cap_h!)
        dy_s = (sup_top - sy_s * x_h) - 0.0
        if donor == "i":
            # Keep dot of ⁱ aligned near sup_top + 45 without soaring too high
            dy_s = sup_top - (bb_s[3] - bb_s[1]) * 0.78
        cs_s = _translate_contours(cs_s, 0.0, dy_s)
        # Apply slant around baseline pivot so superscript leans cleanly forward in Italic
        cs_s = _shear_contours(cs_s, tan_a, 264.0)
        adv_s = max(180.0, adv_d * sx_s + 24.0)
        _put(cp, cs_s, adv_s)

    # --- F. Church Slavic 18 Historical Cyrillic Letters ---
    # 1. Koppa Ҁ/ҁ (U+0480 / U+0481): С/с + crisp vertical tail cleanly welded to bottom bowl (<= 0.8% overlap!)
    for cp, g_C, y_piv, tail_len in ((0x0480, "uni0421", 345.0, 175.0), (0x0481, "uni0441", 264.0, 165.0)):
        cs_C, adv_C = _get_u(g_C, y_piv)
        bb_C = _contours_bbox(cs_C)
        cx_c = bb_C[0] + 0.52 * (bb_C[2] - bb_C[0])
        tw = max(18.0, vstem * 0.88)
        r_tw = (0.45 * tw) if rounded else 0.0
        tail = _rect_ccw_radii(
            cx_c - 0.5 * tw, bb_C[1] - tail_len, cx_c + 0.5 * tw, bb_C[1] + 10.0,
            r_bl=r_tw, r_br=r_tw, r_tr=0.0, r_tl=0.0,
        )
        _put(cp, _shear_contours(cs_C + [tail], tan_a, y_piv), adv_C)

    # 2. Round Omega Ѻ/ѻ (U+047A / U+047B): wider round О/о (1.16x)
    for cp, g_O, y_piv in ((0x047A, "uni041E", 345.0), (0x047B, "uni043E", 264.0)):
        cs_O, adv_O = _get_u(g_O, y_piv)
        bb_O = _contours_bbox(cs_O)
        sx_o = 1.16
        cs_w = _scale_contours(cs_O, sx_o, 1.0, bb_O[0], 0.0)
        _put(cp, _shear_contours(cs_w, tan_a, y_piv), adv_O * sx_o)

    # 3. Broad Omega Ꙍ/ꙍ (U+A64C / U+A64D): wider Ѡ/ѡ (1.15x)
    for cp, g_W, y_piv in ((0xA64C, "uni0460", 345.0), (0xA64D, "uni0461", 264.0)):
        cs_W, adv_W = _get_u(g_W, y_piv)
        bb_W = _contours_bbox(cs_W)
        sx_w = 1.15
        cs_ww = _scale_contours(cs_W, sx_w, 1.0, bb_W[0], 0.0)
        _put(cp, _shear_contours(cs_ww, tan_a, y_piv), adv_W * sx_w)

    # 4. Omega with Titlo Ѽ/ѽ (U+047C / U+047D): Ѡ/ѡ + crisp overhead inverted-breve (uni0311) + comma (uni0313)
    cs_311, _ = _get_u("uni0311", 600.0)
    bb_311 = _contours_bbox(cs_311)
    cs_313, _ = _get_u("uni0313", 600.0)
    bb_313 = _contours_bbox(cs_313)
    for cp, g_W, y_piv in ((0x047C, "uni0460", 345.0), (0x047D, "uni0461", 264.0)):
        cs_W, adv_W = _get_u(g_W, y_piv)
        bb_W = _contours_bbox(cs_W)
        cx_w = 0.5 * (bb_W[0] + bb_W[2])
        # Small psili mark nestled cleanly above Ѡ top with crisp clearance
        ps = _scale_contours(cs_313, 0.72, 0.72, 0.5 * (bb_313[0] + bb_313[2]), bb_313[1])
        bb_p = _contours_bbox(ps)
        ps = _translate_contours(ps, cx_w - 0.5 * (bb_p[0] + bb_p[2]), bb_W[3] + 22.0 - bb_p[1])
        bb_p2 = _contours_bbox(ps)
        # Wide arch clears ps cleanly across Thin..Heavy (0% overlap!)
        arch = _scale_contours(cs_311, 1.55, 0.92, 0.5 * (bb_311[0] + bb_311[2]), bb_311[1])
        bb_a = _contours_bbox(arch)
        y_a_bot = bb_p2[3] + max(28.0, 0.24 * hbar)
        arch = _translate_contours(arch, cx_w - 0.5 * (bb_a[0] + bb_a[2]), y_a_bot - bb_a[1])
        _put(cp, _shear_contours(cs_W + arch + ps, tan_a, y_piv), adv_W)

    # 5. Ot Ѿ/ѿ (U+047E / U+047F): Ѡ/ѡ + miniature Т/т perched cleanly above center stem
    for cp, g_W, g_T, y_piv in (
        (0x047E, "uni0460", "uni0422", 345.0),
        (0x047F, "uni0461", "uni0442", 264.0),
    ):
        cs_W, adv_W = _get_u(g_W, y_piv)
        cs_T, _ = _get_u(g_T, y_piv)
        bb_W = _contours_bbox(cs_W)
        bb_T = _contours_bbox(cs_T)
        cx_w = 0.5 * (bb_W[0] + bb_W[2])
        sc_t = 0.44
        t_mini = _scale_contours(cs_T, sc_t * 1.08, sc_t, 0.5 * (bb_T[0] + bb_T[2]), bb_T[1])
        bb_tm = _contours_bbox(t_mini)
        t_mini = _translate_contours(t_mini, cx_w - 0.5 * (bb_tm[0] + bb_tm[2]), bb_W[3] + 42.0 - bb_tm[1])
        _put(cp, _shear_contours(cs_W + t_mini, tan_a, y_piv), adv_W)

    # 6. Zemlya Ꙁ/ꙁ (U+A640 / U+A641): З/з + angled descender tail horizontally flush-welded into bottom bowl
    for cp, g_Z, y_piv, t_drop in ((0xA640, "uni0417", 345.0, 175.0), (0xA641, "uni0437", 264.0, 165.0)):
        cs_Z, adv_Z = _get_u(g_Z, y_piv)
        bb_Z = _contours_bbox(cs_Z)
        sw_z = max(18.0, vstem * 0.85)
        hw_z = 0.5 * sw_z
        x_t0 = bb_Z[0] + 0.55 * (bb_Z[2] - bb_Z[0])
        x_t1 = bb_Z[0] + 0.12 * (bb_Z[2] - bb_Z[0])
        p_free = (x_t1, bb_Z[1] - t_drop)
        # Measure exact bottom curve y across the tail's join width so horizontal top weld stays <=1.0% overlap!
        ys_zc = _vertical_y_bounds_at_x(cs_Z, x_t0)
        ys_zl = _vertical_y_bounds_at_x(cs_Z, x_t0 - 0.42 * sw_z)
        ys_zr = _vertical_y_bounds_at_x(cs_Z, x_t0 + 0.42 * sw_z)
        y_cut_l = (ys_zl[0] + 10.0) if ys_zl else (bb_Z[1] + 14.0)
        y_cut_r = (ys_zr[0] + 10.0) if ys_zr else (bb_Z[1] + 14.0)
        y_cut_c = (ys_zc[0] + 10.0) if ys_zc else (bb_Z[1] + 10.0)
        y_cut = max(y_cut_c, min(y_cut_l, y_cut_r) + 4.0)
        dx_z, dy_z = x_t0 - p_free[0], y_cut - p_free[1]
        Lz = max(1e-6, math.hypot(dx_z, dy_z))
        ux_z, uy_z = dx_z / Lz, dy_z / Lz
        nx_z, ny_z = -uy_z, ux_z
        th_z = math.atan2(dy_z, dx_z)
        a0 = (p_free[0] - nx_z * hw_z, p_free[1] - ny_z * hw_z)
        b0 = (p_free[0] + nx_z * hw_z, p_free[1] + ny_z * hw_z)
        # Intersect both side edges with the exact bottom curve heights y_cut_r / y_cut_l!
        t_r = (y_cut_r - a0[1]) / max(0.2, uy_z)
        t_l = (y_cut_l - b0[1]) / max(0.2, uy_z)
        a1 = (a0[0] + t_r * ux_z, y_cut_r)
        b1 = (b0[0] + t_l * ux_z, y_cut_l)
        if not rounded:
            tail_z = [("line", (a0, a1)), ("line", (a1, b1)), ("line", (b1, b0)), ("line", (b0, a0))]
        else:
            c0a = _arc_cubic(p_free, hw_z, th_z + math.pi * 0.5, th_z + math.pi)
            c0b = _arc_cubic(p_free, hw_z, th_z + math.pi, th_z + math.pi * 1.5)
            tail_z = [
                ("line", (a0, a1)),
                ("line", (a1, b1)),
                ("line", (b1, b0)),
                ("curve", (b0, c0a[1][1], c0a[1][2], c0a[1][3])),
                ("curve", (c0b[1][0], c0b[1][1], c0b[1][2], a0)),
            ]
        _put(cp, _shear_contours(cs_Z + [tail_z], tan_a, y_piv), adv_Z)

    # 7. Dzelo Ꙃ/ꙃ (U+A642 / U+A643): Ѕ/ѕ + clean top-left curved serif/tail flag welded flush to upper-left shoulder
    for cp, g_S, y_piv in ((0xA642, "uni0405", 345.0), (0xA643, "uni0455", 264.0)):
        cs_S, adv_S = _get_u(g_S, y_piv)
        bb_S = _contours_bbox(cs_S)
        sw_s = max(16.0, hbar * 0.82)
        y_f0, y_f1 = bb_S[3] - sw_s, bb_S[3]
        x_f_l = bb_S[0] - 0.45 * vstem
        xs_fb = _horizontal_x_bounds_at_y(cs_S, y_f0 + 2.0)
        xs_ft = _horizontal_x_bounds_at_y(cs_S, y_f1 - max(4.0, 0.12 * sw_s))
        x_s_bot = (xs_fb[0] + 8.0) if xs_fb else (bb_S[0] + 0.35 * vstem)
        x_s_top = (xs_ft[0] + 8.0) if xs_ft else (bb_S[0] + 0.55 * vstem)
        x_s_bot = max(x_f_l + 24.0, x_s_bot)
        x_s_top = max(x_f_l + 24.0, x_s_top)
        pts_f = [(x_f_l, y_f0), (x_s_bot, y_f0), (x_s_top, y_f1), (x_f_l, y_f1)]
        if not rounded:
            flag_s = _kc_to_rounder([_sharp_polygon_contour(pts_f)])[0]
        else:
            r_f = min(0.45 * sw_s, 0.48 * min(x_s_bot - x_f_l, x_s_top - x_f_l))
            flag_s = _kc_to_rounder([_rounded_polygon_contour(pts_f, [r_f, 0.0, 0.0, r_f])])[0]
        dx_f = max(0.0, 35.0 - x_f_l)
        cs_dz = _translate_contours(cs_S + [flag_s], dx_f, 0.0)
        _put(cp, _shear_contours(cs_dz, tan_a, y_piv), adv_S + dx_f)

    # 8. Monograph Uk Ꙋ/ꙋ (U+A64A / U+A64B): О/о bottom bowl + open V/v upper horns (clean crisp waist weld!)
    for cp, g_O, g_V, y_piv in (
        (0xA64A, "uni041E", "V", 345.0),
        (0xA64B, "uni043E", "v", 264.0),
    ):
        cs_O, adv_O = _get_u(g_O, y_piv)
        cs_V, _ = _get_u(g_V, y_piv)
        bb_O = _contours_bbox(cs_O)
        bb_V = _contours_bbox(cs_V)
        cx_o = 0.5 * (bb_O[0] + bb_O[2])
        # Lower bowl occupies bottom 53% of height; V-cup sits cleanly on top 48.5% (~1.5% crisp waist weld!)
        bowl = _scale_contours(cs_O, 0.96, 0.53, cx_o, bb_O[1])
        cup = _scale_contours(cs_V, 0.88, 0.485, 0.5 * (bb_V[0] + bb_V[2]), bb_V[3])
        bb_cp = _contours_bbox(cup)
        cup = _translate_contours(cup, cx_o - 0.5 * (bb_cp[0] + bb_cp[2]), bb_O[3] - bb_cp[3])
        _put(cp, _shear_contours(bowl + cup, tan_a, y_piv), adv_O)

    # 9. Iotified A Ꙗ/ꙗ (U+A656 / U+A657): І/dotlessi + flush bridge bar + А/а (Ю-style Cyrillic ligature!)
    for cp, g_I, g_A, y_piv in (
        (0xA656, "uni0406", "uni0410", 345.0),
        (0xA657, "dotlessi", "uni0430", 264.0),
    ):
        cs_I, adv_I = _get_u(g_I, y_piv)
        cs_A, adv_A = _get_u(g_A, y_piv)
        bb_I = _contours_bbox(cs_I)
        bb_A = _contours_bbox(cs_A)
        # Slight horizontal compression of А/а (0.90x) so ligature width matches Ю cleanly!
        cs_As = _scale_contours(cs_A, 0.90, 1.0, bb_A[0], 0.0)
        bb_As = _contours_bbox(cs_As)
        bridge_gap = max(78.0, min(140.0, 0.95 * vstem + 28.0))
        dx_a = (bb_I[2] + bridge_gap) - bb_As[0]
        cs_As = _translate_contours(cs_As, dx_a, 0.0)
        bb_As2 = _contours_bbox(cs_As)
        y_br = 0.46 * (bb_I[3] - bb_I[1])
        br_h = max(16.0, hbar * 0.85)
        y_b0, y_b1 = y_br - 0.5 * br_h, y_br + 0.5 * br_h
        xs_i = _horizontal_x_bounds_at_y(cs_I, y_br)
        x_i_r = xs_i[-1] if xs_i else bb_I[2]
        xs_ab = _horizontal_x_bounds_at_y(cs_As, y_b0 + 1.0)
        xs_am = _horizontal_x_bounds_at_y(cs_As, y_br)
        xs_at = _horizontal_x_bounds_at_y(cs_As, y_b1 - 1.0)
        x_a_bot = (xs_ab[0] + 4.0) if xs_ab else (bb_As2[0] + 0.12 * (bb_As2[2] - bb_As2[0]))
        x_a_top = (xs_at[0] + 4.0) if xs_at else (bb_As2[0] + 0.16 * (bb_As2[2] - bb_As2[0]))
        if xs_am:
            # Cap convex bow overhang on lowercase `а` cleanly so overlap stays <= 1.2%!
            x_a_bot = min(x_a_bot, xs_am[0] + 24.0)
            x_a_top = min(x_a_top, xs_am[0] + 24.0)
        bridge = _quad_ccw_midstart(x_i_r - 5.0, y_b0, x_a_bot, x_a_top, y_b1)
        rsb_a = max(30.0, adv_A - bb_A[2])
        adv_ia = bb_As2[2] + rsb_a
        _put(cp, _shear_contours(cs_I + [bridge] + cs_As, tan_a, y_piv), adv_ia)


def inject_v110_expansion_49(
    font,
    weight_class,
    width_mode,
    is_italic=False,
    rounded=False,
    sharp_ref_font=None,
    sharp_metrics=None,
):
    """
    Inject all 49 pure-native Batumi Sans expansion glyphs (+4 currencies, +10 keycaps/UI,
    +35 Google Fonts shape_languages closure glyphs) cleanly & idempotently into a CFF OTF!
    """
    if "CFF " not in font:
        return {"added": 0}
    src_font = sharp_ref_font if (rounded and sharp_ref_font is not None) else font
    if sharp_metrics is None:
        sharp_metrics = measure_font_metrics(src_font)

    _build_currencies_4(font, src_font, sharp_metrics, weight_class, width_mode, is_italic, rounded)
    _build_keycaps_ui_10(font, src_font, weight_class, width_mode, is_italic, rounded)
    _build_shape_languages_35(font, src_font, sharp_metrics, weight_class, width_mode, is_italic, rounded)
    return {"added": len(EXPANSION_49_CPS)}

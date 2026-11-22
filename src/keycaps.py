#!/usr/bin/env python3
"""
Parametric Keyboard & Arrow Keycap Generator for Batumi Sans:
  - U+21E6 (⇦, uni21E6): Hollow Left Arrow
  - U+21E7 (⇧, uni21E7): Shift / Hollow Up Arrow (exact sleek macOS 0.853 W/H silhouette)
  - U+21E8 (⇨, uni21E8): Hollow Right Arrow
  - U+21E9 (⇩, uni21E9): Hollow Down Arrow
  - U+21EA (⇪, uni21EA): Caps Lock (Sleek Hollow Up Arrow + Hollow Base Bar)
  - U+23CE (⏎, uni23CE): Return Key (Sweeping ~235u-radius curved elbow + centered 45° chevron)
  - U+232B (⌫, uni232B): Delete Left (Shield + Pill-Rounded X Cutout)

Key Engineering Guarantees:
  1. Calibrated directly to proportions with crisp Sharp/Rounded differentiation:
     - Sharp (`rounded=False`): razor-sharp geometric corners r=0 on `⇦ ⇧ ⇨ ⇩ ⇪` + `⌫` shield &
       flat-ended `×` cutout; sweeping curved return elbow + razor-sharp flat terminals & 90° apex on `⏎`.
     - Rounded (`rounded=True`): plush concentric round-joins on `⇦ ⇧ ⇨ ⇩ ⇪`, semicircular
       pill caps & rounded nose on `⏎`, rounded shield + smooth pill-rounded `×` cutout on `⌫`.
  2. Weight-matched optical strokes across Thin (100) .. Heavy (900) — airy open interiors even
     in Heavy Extra Condensed!
  3. True stem-preserving width scaling across Extra Condensed / Condensed / Normal / Expanded.
  4. Exact -8.0° Italic slant preservation via shear around vertical cap-height midpoint.
  5. 100% Variable-Font topology compatibility: every glyph emits the EXACT same contour count,
     winding order (CCW outer / CW inner), start vertex, and segment signature across all 9 weights
     and all 4 widths!
"""

import math

KAPPA_90_CIRCLE = 4.0 / 3.0 * (math.sqrt(2.0) - 1.0)
ROUND_TENSION_RATIO = 0.580 / KAPPA_90_CIRCLE

KEYCAP_GLYPHS = (
    "uni21E6",  # ⇦ U+21E6
    "uni21E7",  # ⇧ U+21E7
    "uni21E8",  # ⇨ U+21E8
    "uni21E9",  # ⇩ U+21E9
    "uni21EA",  # ⇪ U+21EA
    "uni23CE",  # ⏎ U+23CE
    "uni232B",  # ⌫ U+232B
)

KEYCAP_CODEPOINTS = {
    0x21E6: "uni21E6",
    0x21E7: "uni21E7",
    0x21E8: "uni21E8",
    0x21E9: "uni21E9",
    0x21EA: "uni21EA",
    0x23CE: "uni23CE",
    0x232B: "uni232B",
}

# optical stroke widths (UPM=1000, CapH=689)
# Reference `⇧` wall_t = 50.0u at Regular; lighter hollow-icon progression in Bold..Heavy
# so double walls NEVER choke the inner triangular wing pockets even at Heavy Extra Condensed!
HOLLOW_SW = {
    100: 22.0,
    200: 31.0,
    300: 39.0,
    400: 48.0,
    500: 55.0,
    600: 61.0,
    700: 67.0,
    800: 73.0,
    900: 78.0,
}

# Reference `⏎` stroke_t = 72.6u at Regular -> smooth monotonic ramp Thin..Heavy!
SINGLE_SW = {
    100: 24.0,
    200: 40.0,
    300: 54.0,
    400: 72.0,
    500: 86.0,
    600: 98.0,
    700: 108.0,
    800: 118.0,
    900: 126.0,
}

# Pill-rounded X cutout arm thickness inside `⌫` shield
DELETE_X_SW = {
    100: 48.0,
    200: 56.0,
    300: 62.0,
    400: 68.0,
    500: 74.0,
    600: 79.0,
    700: 84.0,
    800: 89.0,
    900: 94.0,
}

WIDTH_SCALE = {
    "extra_condensed": 0.86,
    "condensed": 0.925,
    "normal": 1.00,
    "expanded": 1.13,
}

CAP_H = 689.0
CY = 345.0


# ---------------------------------------------------------------------------
# Vector & Exact Geometric Helpers
# ---------------------------------------------------------------------------

def _add(a, b): return (a[0] + b[0], a[1] + b[1])
def _sub(a, b): return (a[0] - b[0], a[1] - b[1])
def _mul(a, s): return (a[0] * s, a[1] * s)
def _dot(a, b): return a[0] * b[0] + a[1] * b[1]
def _cross(a, b): return a[0] * b[1] - a[1] * b[0]
def _len(a): return math.hypot(a[0], a[1])


def _norm(a):
    L = math.hypot(a[0], a[1])
    return (a[0] / L, a[1] / L) if L > 1e-12 else (1.0, 0.0)


def _rot90_ccw(v): return (-v[1], v[0])


def _line_intersect(p1, d1, p2, d2):
    """Intersect lines p1 + t*d1 and p2 + u*d2."""
    denom = _cross(d1, d2)
    if abs(denom) < 1e-9:
        return ((p1[0] + p2[0]) * 0.5, (p1[1] + p2[1]) * 0.5)
    diff = _sub(p2, p1)
    t = _cross(diff, d2) / denom
    return _add(p1, _mul(d1, t))


def _offset_polygon_outward(pts, offset):
    """
    Exact constant-width outward miter offset of a CCW polygon `pts` by `offset` > 0.
    Returns CCW outer polygon vertices.
    """
    n = len(pts)
    shifted_lines = []
    for i in range(n):
        p0 = pts[i]
        p1 = pts[(i + 1) % n]
        d = _norm(_sub(p1, p0))
        outward_n = (d[1], -d[0])  # Right normal points OUTSIDE a CCW polygon
        shifted_lines.append((_add(p0, _mul(outward_n, offset)), d))

    outer_ccw = []
    for i in range(n):
        p_prev, d_prev = shifted_lines[(i - 1) % n]
        p_curr, d_curr = shifted_lines[i]
        outer_ccw.append(_line_intersect(p_prev, d_prev, p_curr, d_curr))
    return outer_ccw


def _offset_polygon_inward(pts, offset):
    """
    Exact constant-width inward miter offset of a CCW polygon `pts` by `offset` > 0.
    Returns CW hole polygon vertices in reversed order (PostScript CW hole winding).
    """
    n = len(pts)
    shifted_lines = []
    for i in range(n):
        p0 = pts[i]
        p1 = pts[(i + 1) % n]
        d = _norm(_sub(p1, p0))
        inward_n = _rot90_ccw(d)  # Left normal points INSIDE a CCW polygon
        shifted_lines.append((_add(p0, _mul(inward_n, offset)), d))

    inner_ccw = []
    for i in range(n):
        p_prev, d_prev = shifted_lines[(i - 1) % n]
        p_curr, d_curr = shifted_lines[i]
        inner_ccw.append(_line_intersect(p_prev, d_prev, p_curr, d_curr))
    return list(reversed(inner_ccw))


def _sharp_polygon_contour(pts):
    """
    Build a strictly VF-topology-compatible razor-sharp (r = 0) closed contour from polygon `pts`.
    Always emits EXACTLY `len(pts)` straight `"line"` segments starting at vertex 0.
    """
    n = len(pts)
    return [("line", (pts[i], pts[(i + 1) % n])) for i in range(n)]


def _rounded_polygon_contour(pts, radii, max_edge_frac=0.45, tension=ROUND_TENSION_RATIO):
    """
    Build a strictly VF-topology-compatible closed contour from polygon `pts` and per-vertex
    radii `radii`. Always emits EXACTLY `2 * len(pts)` segments: alternating (cubic corner arc,
    straight edge line) starting at vertex 0's entry tangent point.
    Supports per-vertex custom `max_edge_frac` (float or list of floats).
    """
    n = len(pts)
    assert len(radii) == n
    entries, exits, arcs = [], [], []

    for i in range(n):
        p_prev = pts[(i - 1) % n]
        p_cur = pts[i]
        p_next = pts[(i + 1) % n]
        e_in = _sub(p_cur, p_prev)
        e_out = _sub(p_next, p_cur)
        L_in, L_out = _len(e_in), _len(e_out)
        u_in, u_out = _norm(e_in), _norm(e_out)

        ang = math.atan2(_cross(u_in, u_out), max(-1.0, min(1.0, _dot(u_in, u_out))))
        abs_ang = max(1e-4, abs(ang))
        tan_half = math.tan(abs_ang * 0.5)

        r_req = max(1.0, float(radii[i]))
        frac = max_edge_frac[i] if isinstance(max_edge_frac, (list, tuple)) else max_edge_frac
        pull = min(r_req * tan_half, min(L_in, L_out) * frac)
        r_eff = pull / max(tan_half, 1e-4)

        pa = _sub(p_cur, _mul(u_in, pull))
        pb = _add(p_cur, _mul(u_out, pull))
        k = min((4.0 / 3.0) * math.tan(abs_ang / 4.0) * tension * r_eff, pull * 0.96)
        c1 = _add(pa, _mul(u_in, k))
        c2 = _sub(pb, _mul(u_out, k))

        entries.append(pa)
        exits.append(pb)
        arcs.append(("cubic", (pa, c1, c2, pb)))

    segs = []
    for i in range(n):
        segs.append(arcs[i])
        segs.append(("line", (exits[i], entries[(i + 1) % n])))
    return segs


def _arc_cubic(center, radius, th0, th1, tension=ROUND_TENSION_RATIO):
    """Single cubic Bézier arc around `center` from angle `th0` to `th1` (CCW or CW)."""
    dth = th1 - th0
    sgn = 1.0 if dth >= 0 else -1.0
    k = (4.0 / 3.0) * math.tan(abs(dth) / 4.0) * tension * radius
    p0 = (center[0] + radius * math.cos(th0), center[1] + radius * math.sin(th0))
    p3 = (center[0] + radius * math.cos(th1), center[1] + radius * math.sin(th1))
    t0 = (-sgn * math.sin(th0), sgn * math.cos(th0))
    t1 = (-sgn * math.sin(th1), sgn * math.cos(th1))
    c1 = (p0[0] + k * t0[0], p0[1] + k * t0[1])
    c2 = (p3[0] - k * t1[0], p3[1] - k * t1[1])
    return ("cubic", (p0, c1, c2, p3))


def _transform_contours(contours, fn):
    return [[(k, tuple(fn(p) for p in pts)) for k, pts in c] for c in contours]


def _rotate_contours(contours, angle_deg, cx, cy):
    rad = math.radians(angle_deg)
    ca, sa = math.cos(rad), math.sin(rad)

    def rot(p):
        dx, dy = p[0] - cx, p[1] - cy
        return (cx + dx * ca - dy * sa, cy + dx * sa + dy * ca)

    return _transform_contours(contours, rot)


def _apply_italic_slant(contours, cy=CY, angle_deg=8.0):
    shear = math.tan(math.radians(angle_deg))
    return _transform_contours(contours, lambda p: (p[0] + (p[1] - cy) * shear, p[1]))


def _bounds_x(contours):
    xs = [p[0] for c in contours for _, pts in c for p in pts]
    return (min(xs), max(xs)) if xs else (0.0, 0.0)


# ---------------------------------------------------------------------------
# Individual Keycap Builders
# ---------------------------------------------------------------------------

def _stroke_closed_polygon(center_pts, sw, outer_r_base, inner_r_base, outer_clamps=None, inner_clamps=None):
    """
    concentric stroked-centerline closed path builder:
      - Outer boundary = exact +sw/2 outward offset rounded with concentric radii `r_c + sw/2`
      - Inner hole     = exact -sw/2 inward offset (reversed CW) rounded with inner radii
    Eliminates sharp-miter double-wall choking at 135° arrow wings so triangular inner wing
    pockets stay wide open across Thin..Heavy and Extra Condensed..Expanded!
    """
    hw = sw * 0.5
    outer_pts = _offset_polygon_outward(center_pts, hw)
    inner_pts = _offset_polygon_inward(center_pts, hw)  # Reversed CW order

    # Outer concentric radii: add hw on convex vertices so outer arc wraps concentrically around centerline!
    outer_r = [r + hw for r in outer_r_base]
    inner_r = list(reversed(inner_r_base))

    c_outer = _rounded_polygon_contour(
        outer_pts, outer_r, max_edge_frac=outer_clamps if outer_clamps is not None else 0.48
    )
    c_inner = _rounded_polygon_contour(
        inner_pts, inner_r, max_edge_frac=inner_clamps if inner_clamps is not None else 0.45
    )
    return [c_outer, c_inner]


def _build_shift_arrow(weight_class, sx, rounded, y_bot=6.0, y_top=686.0, sw_scale=1.0,
                       sh_frac=0.525, head_c_base=278.0):
    """
    Build `shift` hollow upward arrow `⇧` via true stroked centerline:
      - Wide flaring triangular head with generous open left & right triangular wing pockets
        INSIDE the hollow cutout (inner_wing_overhang >= 120u even in Extra Condensed Heavy 900!)
      - Rounded (`rounded=True`): plush concentric round-joins (14 segments/contour).
      - Sharp (`rounded=False`): razor-sharp geometric corners r=0 (zero circular corner fillets,
        pure 7-line outer + 7-line inner contours), 100% VF-compatible across all 72 Sharp masters!
    """
    sw = HOLLOW_SW[weight_class] * sw_scale * (0.94 if sx < 0.90 else 1.0)
    hw = sw * 0.5
    total_h = y_top - y_bot

    if not rounded:
        # Razor-sharp geometric hollow arrow (r = 0, zero circular corner fillets!)
        # Slightly lower shoulder gives crisper ~48 deg arrowhead pitch while keeping wide-open
        # inner triangular wing pockets (>= 122u even at Extra Condensed Heavy!) and balanced width.
        sh_frac_s = sh_frac - 0.04
        y_bot_c = y_bot + hw
        y_top_c = y_top - 1.25 * hw
        y_sh_c = y_bot + sh_frac_s * total_h

        stem_c_hw = max((104.0 + 0.22 * sw) * sx, hw + 56.0 * max(0.88, sx))
        head_c_hw = (266.0 + 0.30 * sw) * sx
        head_c_hw = max(head_c_hw, stem_c_hw + (136.0 + 0.90 * sw) * sx)

        center_pts = [
            (0.0, y_top_c),              # 0: apex
            (-head_c_hw, y_sh_c),        # 1: left wing tip
            (-stem_c_hw, y_sh_c),        # 2: left inner shoulder
            (-stem_c_hw, y_bot_c),       # 3: bottom-left
            (stem_c_hw, y_bot_c),        # 4: bottom-right
            (stem_c_hw, y_sh_c),         # 5: right inner shoulder
            (head_c_hw, y_sh_c),         # 6: right wing tip
        ]
        outer_pts = _offset_polygon_outward(center_pts, hw)
        inner_pts = _offset_polygon_inward(center_pts, hw)
        return [_sharp_polygon_contour(outer_pts), _sharp_polygon_contour(inner_pts)], stem_c_hw + hw

    # Centerline vertical bounds so actual outer contour spans [y_bot, y_top] cleanly
    y_bot_c = y_bot + hw
    y_top_c = y_top - hw
    y_sh_c = y_bot + sh_frac * total_h

    # Wide centerline arrowhead + sleek slender stem (reference stem_outer/head_outer ≈ 0.40..0.44)
    head_c_hw = (head_c_base + 0.55 * sw) * sx
    stem_c_hw = max((104.0 + 0.22 * sw) * sx, hw + 56.0 * max(0.88, sx))
    # Guarantee large unmistakable inner wing pockets (>= 115u in XCon Heavy, >= 140u Normal!)
    head_c_hw = max(head_c_hw, stem_c_hw + (142.0 + 1.15 * sw) * sx)

    center_pts = [
        (0.0, y_top_c),              # 0: apex
        (-head_c_hw, y_sh_c),        # 1: left wing tip
        (-stem_c_hw, y_sh_c),        # 2: left inner shoulder
        (-stem_c_hw, y_bot_c),       # 3: bottom-left
        (stem_c_hw, y_bot_c),        # 4: bottom-right
        (stem_c_hw, y_sh_c),         # 5: right inner shoulder
        (head_c_hw, y_sh_c),         # 6: right wing tip
    ]

    # Centerline corner radii (outer gets +hw automatically for exact concentric round-join!)
    r_tip, r_wing, r_sh, r_bot = 16.0, 12.0, 6.0, 32.0
    ir_tip, ir_wing, ir_sh, ir_bot = 6.0, 5.0, 8.0, 20.0

    # At concave shoulder vertices (2 & 5), outer boundary is concave -> keep small crisp radius (not +hw!)
    outer_pts = _offset_polygon_outward(center_pts, hw)
    inner_pts = _offset_polygon_inward(center_pts, hw)

    outer_r = [
        r_tip + hw,   # 0: apex (convex -> concentric!)
        r_wing + hw,  # 1: left wing tip (convex -> concentric!)
        r_sh,         # 2: left shoulder (concave -> crisp!)
        r_bot + hw,   # 3: bottom-left (convex -> concentric!)
        r_bot + hw,   # 4: bottom-right (convex -> concentric!)
        r_sh,         # 5: right shoulder (concave -> crisp!)
        r_wing + hw,  # 6: right wing tip (convex -> concentric!)
    ]
    # inner_pts is reversed order of center_pts: [6, 5, 4, 3, 2, 1, 0]
    inner_r = [ir_wing, ir_sh, ir_bot, ir_bot, ir_sh, ir_wing, ir_tip]

    # Allow wing tips (1, 6) to pull back up to 0.78 of the horizontal shoulder edge for true concentricity
    # while keeping inner shoulder (2, 5) tight (<= 0.16) so they never touch!
    outer_clamps = [0.46, 0.78, 0.16, 0.45, 0.45, 0.16, 0.78]
    inner_clamps = [0.42, 0.25, 0.44, 0.44, 0.25, 0.42, 0.44]

    c_outer = _rounded_polygon_contour(outer_pts, outer_r, max_edge_frac=outer_clamps)
    c_inner = _rounded_polygon_contour(inner_pts, inner_r, max_edge_frac=inner_clamps)
    return [c_outer, c_inner], stem_c_hw + hw


def _build_horizontal_hollow_arrow(weight_class, sx, rounded, direction="left"):
    """
    Build sleek wide-wing horizontal hollow arrow (`⇦` or `⇨`) via stroked centerline,
    matching `⇧`'s exact wide open triangular wing pockets in horizontal orientation while
    preserving stroke weight cleanly across Extra Condensed..Expanded!
    """
    sw = HOLLOW_SW[weight_class] * (0.94 if sx < 0.90 else 1.0)
    hw = sw * 0.5
    total_w = 682.0 * sx

    if not rounded:
        x_tip_c = -total_w * 0.5 + 1.25 * hw
        x_back_c = total_w * 0.5 - hw
        x_sh_c = x_back_c - 0.455 * (x_back_c - x_tip_c)

        stem_c_hh = max(100.0 + 0.20 * sw, hw + 54.0)
        head_c_hh = max(254.0 + 0.25 * sw, stem_c_hh + (125.0 + 0.74 * sw))

        center_pts = [
            (x_tip_c, CY),                # 0: left tip
            (x_sh_c, CY - head_c_hh),     # 1: bottom wing tip
            (x_sh_c, CY - stem_c_hh),     # 2: bottom inner shoulder
            (x_back_c, CY - stem_c_hh),   # 3: back-bottom
            (x_back_c, CY + stem_c_hh),   # 4: back-top
            (x_sh_c, CY + stem_c_hh),     # 5: top inner shoulder
            (x_sh_c, CY + head_c_hh),     # 6: top wing tip
        ]
        outer_pts = _offset_polygon_outward(center_pts, hw)
        inner_pts = _offset_polygon_inward(center_pts, hw)
        contours = [_sharp_polygon_contour(outer_pts), _sharp_polygon_contour(inner_pts)]
        if direction == "right":
            contours = _rotate_contours(contours, 180.0, 0.0, CY)
        return contours

    x_tip_c = -total_w * 0.5 + hw
    x_back_c = total_w * 0.5 - hw
    x_sh_c = x_back_c - 0.525 * (x_back_c - x_tip_c)

    head_c_hh = 278.0 + 0.55 * sw
    stem_c_hh = max(104.0 + 0.22 * sw, hw + 56.0)
    head_c_hh = max(head_c_hh, stem_c_hh + (142.0 + 1.15 * sw))

    center_pts = [
        (x_tip_c, CY),                # 0: left tip
        (x_sh_c, CY - head_c_hh),     # 1: bottom wing tip
        (x_sh_c, CY - stem_c_hh),     # 2: bottom inner shoulder
        (x_back_c, CY - stem_c_hh),   # 3: back-bottom
        (x_back_c, CY + stem_c_hh),   # 4: back-top
        (x_sh_c, CY + stem_c_hh),     # 5: top inner shoulder
        (x_sh_c, CY + head_c_hh),     # 6: top wing tip
    ]

    r_tip, r_wing, r_sh, r_bot = 16.0, 12.0, 6.0, 32.0
    ir_tip, ir_wing, ir_sh, ir_bot = 6.0, 5.0, 8.0, 20.0

    outer_pts = _offset_polygon_outward(center_pts, hw)
    inner_pts = _offset_polygon_inward(center_pts, hw)
    outer_r = [r_tip + hw, r_wing + hw, r_sh, r_bot + hw, r_bot + hw, r_sh, r_wing + hw]
    inner_r = [ir_wing, ir_sh, ir_bot, ir_bot, ir_sh, ir_wing, ir_tip]
    outer_clamps = [0.46, 0.78, 0.16, 0.45, 0.45, 0.16, 0.78]
    inner_clamps = [0.42, 0.25, 0.44, 0.44, 0.25, 0.42, 0.44]

    contours = [
        _rounded_polygon_contour(outer_pts, outer_r, max_edge_frac=outer_clamps),
        _rounded_polygon_contour(inner_pts, inner_r, max_edge_frac=inner_clamps),
    ]
    if direction == "right":
        contours = _rotate_contours(contours, 180.0, 0.0, CY)
    return contours


def _build_capslock(weight_class, sx, rounded):
    """
    Build sleek wide-wing `⇪` (capslock): wide hollow upward arrow with unmistakable
    open triangular side pockets above a matching sleek hollow horizontal base bar (slit >= 50u!).
    Always 4 contours (2 outer CCW + 2 inner CW holes), 100% VF-compatible!
    """
    sw_arrow = HOLLOW_SW[weight_class] * 0.92 * (0.94 if sx < 0.90 else 1.0)
    sw_bar = HOLLOW_SW[weight_class] * 0.76 * (0.94 if sx < 0.90 else 1.0)
    slit_h = max(50.0, 64.0 - 0.14 * sw_bar)
    bar_h = 2.0 * sw_bar + slit_h
    gap = max(48.0, 64.0 - 0.12 * sw_arrow)

    y_bar_bot = -14.0
    y_bar_top = y_bar_bot + bar_h
    y_arrow_bot = y_bar_top + gap
    y_arrow_top = 702.0

    arrow_contours, stem_outer_hw = _build_shift_arrow(
        weight_class, sx, rounded,
        y_bot=y_arrow_bot, y_top=y_arrow_top,
        sw_scale=0.92, sh_frac=0.40, head_c_base=278.0,
    )

    bar_hw = stem_outer_hw
    bar_outer_pts = [
        (-bar_hw, y_bar_bot),
        (bar_hw, y_bar_bot),
        (bar_hw, y_bar_top),
        (-bar_hw, y_bar_top),
    ]
    bar_inner_pts = _offset_polygon_inward(bar_outer_pts, sw_bar)

    if not rounded:
        c_bar_out = _sharp_polygon_contour(bar_outer_pts)
        c_bar_in = _sharp_polygon_contour(bar_inner_pts)
        return arrow_contours + [c_bar_out, c_bar_in]

    rb_out = min(44.0, bar_h * 0.36)
    rb_in = min(14.0, slit_h * 0.30)
    c_bar_out = _rounded_polygon_contour(bar_outer_pts, [rb_out] * 4)
    c_bar_in = _rounded_polygon_contour(bar_inner_pts, [rb_in] * 4)
    return arrow_contours + [c_bar_out, c_bar_in]


def _build_return_arrow(weight_class, sx, rounded):
    """
    Build `⏎` (return key) matching exact user reference proportions:
      - Aspect ratio W / H = 1.184 (W ≈ 758u, H = 640u, centered cleanly in CapH [24..664]!)
      - Horizontal shaft centered near vertical mid (`48%` from bottom = y ~ 332)!
      - Sweeping, generous curved elbow on the right (`r_outer ≈ 240u`!) flowing seamlessly
        from the right vertical stem into the horizontal shaft (NOT a tight boxy 90° corner!)
      - Rounded (`rounded=True`): lush semicircular pill caps & smooth rounded chevron nose (22 segs).
      - Sharp (`rounded=False`): identical sleek sweeping curved elbow, with RAZOR-SHARP flat top
        stem terminal, flat perpendicular 45° chevron tips, crisp inner crotches, and razor-sharp
        90° chevron apex (13 segments = 11 lines + 2 concentric elbow cubics, 100% VF-compatible!).
    """
    sw = SINGLE_SW[weight_class]
    hw = sw * 0.5
    s2 = math.sqrt(2.0)
    d45 = hw / s2

    # Reference geometry: H = 640 (y in [24, 664]), W = 758*sx, shaft_cy = 48% from bottom
    y_bot = 24.0
    y_top = 664.0
    y_shaft = y_bot + 0.48 * (y_top - y_bot)  # ~331.2

    total_w = 758.0 * sx
    x_nose = -total_w * 0.5
    x_right = total_w * 0.5 - hw  # Right vertical stem centerline x (outer edge at +total_w/2)

    # Chevron 45° symmetric wings spanning cleanly to y_top (upper) & y_bot (lower)
    pc_x = x_nose + hw * s2
    arm_up = (y_top - y_shaft) - d45 - 6.0
    arm_dn = (y_shaft - y_bot) - d45 - 6.0
    arm_len = min(arm_up, arm_dn, 305.0 * max(0.86, sx))

    ut_x = pc_x + arm_len
    ut_y = y_shaft + arm_len
    lt_x = pc_x + arm_len
    lt_y = y_shaft - arm_len

    # Exact inner crotches where 45° wing inner edges meet horizontal shaft y = y_shaft ± hw
    x_crotch = pc_x + hw * (1.0 + s2)

    # Sweeping generous curved elbow radius (reference r_outer ≈ 0.355 * H ≈ 227..245u!)
    # Available horizontal run between chevron crotch and right vertical stem:
    avail_x = max(120.0, (x_right - hw) - x_crotch)
    avail_y = max(120.0, (y_top - hw) - (y_shaft + hw))
    # Cap inner elbow radius so the sweeping curve fills ~75% of the right-side bend gracefully
    # without colliding with either the top stem cap or the chevron crotch!
    r_elb_in = min(avail_x * 0.80, avail_y * 0.78, 178.0 * sx)
    r_elb_in = max(72.0 * sx, r_elb_in)
    r_elb_out = r_elb_in + sw

    pts = [
        (x_right + hw, y_top),           # 0: top-right of vertical stem
        (x_right - hw, y_top),           # 1: top-left of vertical stem
        (x_right - hw, y_shaft + hw),    # 2: inner sweeping elbow
        (x_crotch, y_shaft + hw),        # 3: upper chevron crotch
        (ut_x + d45, ut_y - d45),        # 4: upper wing inner cap corner
        (ut_x - d45, ut_y + d45),        # 5: upper wing outer cap corner
        (x_nose, y_shaft),               # 6: chevron left nose
        (lt_x - d45, lt_y - d45),        # 7: lower wing outer cap corner
        (lt_x + d45, lt_y + d45),        # 8: lower wing inner cap corner
        (x_crotch, y_shaft - hw),        # 9: lower chevron crotch
        (x_right + hw, y_shaft - hw),    # 10: outer sweeping elbow
    ]

    if not rounded:
        # Sweeping concentric curved elbow at vertices 2 & 10, razor-sharp r=0 terminals & apex everywhere else!
        l_12 = _len(_sub(pts[2], pts[1]))
        l_23 = _len(_sub(pts[3], pts[2]))
        pull_in = min(r_elb_in, l_12 * 0.82, l_23 * 0.82)
        l_9_10 = _len(_sub(pts[10], pts[9]))
        l_10_0 = _len(_sub(pts[0], pts[10]))
        pull_out = min(pull_in + sw, l_9_10 * 0.86, l_10_0 * 0.86)

        k_90 = (4.0 / 3.0) * math.tan(math.pi / 8.0) * ROUND_TENSION_RATIO
        k_in = min(k_90 * pull_in, pull_in * 0.96)
        k_out = min(k_90 * pull_out, pull_out * 0.96)

        # Inner elbow (vertex 2: down along 1->2, then left along 2->3)
        p2_a = (pts[2][0], pts[2][1] + pull_in)
        p2_b = (pts[2][0] - pull_in, pts[2][1])
        c2_1 = (p2_a[0], p2_a[1] - k_in)
        c2_2 = (p2_b[0] + k_in, p2_b[1])

        # Outer elbow (vertex 10: right along 9->10, then up along 10->0)
        p10_a = (pts[10][0] - pull_out, pts[10][1])
        p10_b = (pts[10][0], pts[10][1] + pull_out)
        c10_1 = (p10_a[0] + k_out, p10_a[1])
        c10_2 = (p10_b[0], p10_b[1] - k_out)

        contour = [
            ("line", (pts[0], pts[1])),
            ("line", (pts[1], p2_a)),
            ("cubic", (p2_a, c2_1, c2_2, p2_b)),
            ("line", (p2_b, pts[3])),
            ("line", (pts[3], pts[4])),
            ("line", (pts[4], pts[5])),
            ("line", (pts[5], pts[6])),
            ("line", (pts[6], pts[7])),
            ("line", (pts[7], pts[8])),
            ("line", (pts[8], pts[9])),
            ("line", (pts[9], p10_a)),
            ("cubic", (p10_a, c10_1, c10_2, p10_b)),
            ("line", (p10_b, pts[0])),
        ]
        return [contour]

    r_cap = hw * 0.99
    r_nose = hw * 0.96
    r_crotch = min(14.0, hw * 0.24)

    radii = [
        r_cap, r_cap,         # 0, 1: top stem cap
        r_elb_in,             # 2: inner sweeping elbow
        r_crotch,             # 3: upper crotch
        r_cap, r_cap,         # 4, 5: upper wing cap
        r_nose,               # 6: chevron nose
        r_cap, r_cap,         # 7, 8: lower wing cap
        r_crotch,             # 9: lower crotch
        r_elb_out,            # 10: outer sweeping elbow
    ]
    # Allow elbow vertices (2 & 10) to sweep generously up to 0.82 of their long arm lengths
    # while keeping cap pairs strictly <= 0.492 so semicircular pill caps stay seamless!
    edge_clamps = [
        0.492, 0.492,   # 0, 1: top cap
        0.82,           # 2: inner elbow (sweeping!)
        0.16,           # 3: upper crotch (stays tight!)
        0.492, 0.492,   # 4, 5: upper wing cap
        0.46,           # 6: chevron nose
        0.492, 0.492,   # 7, 8: lower wing cap
        0.16,           # 9: lower crotch
        0.84,           # 10: outer elbow (sweeping!)
    ]
    contour = _rounded_polygon_contour(pts, radii, max_edge_frac=edge_clamps)
    return [contour]


def _build_delete_left(weight_class, sx, rounded):
    """
    Build `delete.left.fill` (`⌫`, uni232B):
      - Rounded (`rounded=True`): Plush rounded 5-point shield + smooth PILL-ROUNDED X cutout
        (4 exact semicircular capsule arms crossing cleanly with softened 90° inner crotches).
      - Sharp (`rounded=False`): Razor-sharp architectural 5-point shield (r=0) + crisp sharp
        flat-ended X cutout (12-line CW polygon, zero rounded fillets!).
    Always 2 contours with 100% identical VF topology across all masters!
    """
    sh_h = 564.0
    y0 = CY - sh_h * 0.5
    y1 = CY + sh_h * 0.5
    # Plush rounded nose pulls back ~8u more than sharp tip; add +8u*sx to nose_w & total_w
    # on rounded=True so body width (572*sx) and final visual footprint match Sharp 1:1.
    total_w = (832.0 if rounded else 824.0) * sx
    nose_w = (260.0 if rounded else 252.0) * sx
    x0 = -total_w * 0.5
    x1 = total_w * 0.5

    shield_pts = [
        (x0, CY),              # 0: left chevron tip
        (x0 + nose_w, y0),     # 1: bottom-left shoulder
        (x1, y0),              # 2: bottom-right
        (x1, y1),              # 3: top-right
        (x0 + nose_w, y1),     # 4: top-left shoulder
    ]

    xc = x0 + nose_w + (0.452 if rounded else 0.455) * (total_w - nose_w)
    yc = CY
    sw_x = DELETE_X_SW[weight_class] * (0.94 if sx < 0.90 else 1.0)
    hw = sw_x * 0.5
    L_c = 132.0 * min(1.04, max(0.88, sx))
    s2 = math.sqrt(2.0)
    d_crotch = hw * s2
    arm_angles_cw = [math.radians(45), math.radians(-45), math.radians(-135), math.radians(135)]

    if not rounded:
        c_shield = _sharp_polygon_contour(shield_pts)
        # Optical arm reach matching pill-ended X span without crowding shield edges
        L_sharp = L_c + 0.55 * hw
        x_pts_cw = []
        for th in arm_angles_cw:
            u = (math.cos(th), math.sin(th))
            n_left = (-math.sin(th), math.cos(th))
            n_right = (math.sin(th), -math.cos(th))
            th_in_c = th + math.radians(45)
            c_in = (xc + d_crotch * math.cos(th_in_c), yc + d_crotch * math.sin(th_in_c))
            cap_end = (xc + L_sharp * u[0], yc + L_sharp * u[1])
            p_left = _add(cap_end, _mul(n_left, hw))
            p_right = _add(cap_end, _mul(n_right, hw))
            x_pts_cw.extend([c_in, p_left, p_right])
        c_x = _sharp_polygon_contour(x_pts_cw)
        return [c_shield, c_x]

    # `delete.left.fill` outer shield radii (superelliptical κ=0.580):
    # - r_right    ≈ 118..135u: generously pillowy right corners
    # - r_shoulder ≈ 123..141u: seamless soft flow across the 48° obtuse chevron shoulders
    # - r_nose     ≈  74..85u : tactile rounded left nose preserving unmistakable delete silhouette
    w_scale = min(1.01, max(0.88, sx))
    r_nose = 84.0 * w_scale
    r_shoulder = 140.0 * w_scale
    r_right = 134.0 * w_scale
    sh_r = [r_nose, r_shoulder, r_right, r_right, r_shoulder]
    c_shield = _rounded_polygon_contour(shield_pts, sh_r)

    f_crotch = hw * 0.18
    x_segs = []
    for th in arm_angles_cw:
        u = (math.cos(th), math.sin(th))
        n_left = (-math.sin(th), math.cos(th))
        n_right = (math.sin(th), -math.cos(th))

        th_in_c = th + math.radians(45)
        th_out_c = th - math.radians(45)
        c_in = (xc + d_crotch * math.cos(th_in_c), yc + d_crotch * math.sin(th_in_c))
        c_out = (xc + d_crotch * math.cos(th_out_c), yc + d_crotch * math.sin(th_out_c))

        cap_c = (xc + L_c * u[0], yc + L_c * u[1])
        w_in_start = _add(c_in, _mul(u, f_crotch))
        cap_entry = _add(cap_c, _mul(n_left, hw))
        cap_exit = _add(cap_c, _mul(n_right, hw))
        w_out_end = _add(c_out, _mul(u, f_crotch))

        x_segs.append(("line", (w_in_start, cap_entry)))
        arc1 = _arc_cubic(cap_c, hw, th + math.pi * 0.5, th)
        arc2 = _arc_cubic(cap_c, hw, th, th - math.pi * 0.5)
        arc1 = ("cubic", (cap_entry, arc1[1][1], arc1[1][2], arc1[1][3]))
        arc2 = ("cubic", (arc2[1][0], arc2[1][1], arc2[1][2], cap_exit))
        x_segs.append(arc1)
        x_segs.append(arc2)
        x_segs.append(("line", (cap_exit, w_out_end)))

        u_next = n_right
        next_start = _add(c_out, _mul(u_next, f_crotch))
        k_c = f_crotch * 0.58
        x_segs.append(("cubic", (w_out_end, _sub(w_out_end, _mul(u, k_c)), _sub(next_start, _mul(u_next, k_c)), next_start)))

    return [c_shield, x_segs]


# ---------------------------------------------------------------------------
# Public Entry Point
# ---------------------------------------------------------------------------

def generate_keycap_glyph(gname, weight_class, width_mode="normal", is_italic=False, rounded=False):
    """
    Generate parametric contours and advance width for any of the 7 keycap glyphs:
      uni21E6 (⇦), uni21E7 (⇧), uni21E8 (⇨), uni21E9 (⇩), uni21EA (⇪), uni23CE (⏎), uni232B (⌫).
    Returns (contours, advance_width).
    """
    sx = WIDTH_SCALE.get(width_mode, 1.0)
    sb = round(84.0 * sx)

    if gname == "uni21E7":  # ⇧ Shift / Up
        contours, _ = _build_shift_arrow(weight_class, sx, rounded)
    elif gname == "uni21E9":  # ⇩ Down
        contours, _ = _build_shift_arrow(weight_class, sx, rounded)
        contours = _rotate_contours(contours, 180.0, 0.0, CY)
    elif gname == "uni21E6":  # ⇦ Left
        contours = _build_horizontal_hollow_arrow(weight_class, sx, rounded, direction="left")
    elif gname == "uni21E8":  # ⇨ Right
        contours = _build_horizontal_hollow_arrow(weight_class, sx, rounded, direction="right")
    elif gname == "uni21EA":  # ⇪ Caps Lock
        contours = _build_capslock(weight_class, sx, rounded)
    elif gname == "uni23CE":  # ⏎ Return
        contours = _build_return_arrow(weight_class, sx, rounded)
    elif gname == "uni232B":  # ⌫ Delete Left
        contours = _build_delete_left(weight_class, sx, rounded)
    else:
        raise ValueError(f"Unsupported keycap glyph: {gname}")

    if is_italic:
        contours = _apply_italic_slant(contours, cy=CY, angle_deg=8.0)

    x0, x1 = _bounds_x(contours)
    shift_x = sb - x0
    contours = _transform_contours(contours, lambda p: (p[0] + shift_x, p[1]))
    adv_width = int(round((x1 - x0) + 2.0 * sb))
    return contours, adv_width

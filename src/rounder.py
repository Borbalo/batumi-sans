#!/usr/bin/env python3
"""
High-craft cubic Bézier stroke-terminal & outer-corner rounding engine
for the Borbalo GO superfamily, with round stroke ends's geometric grammar:
  - Full inscribed semicircular caps (h = r = stroke_width / 2)
  - Rounded superelliptical cubic tension (kappa = 0.580 at 90°)
  - Subtle optical overshoot on baseline / x-height / cap / ascender terminals
  - Crisp inner concave junctions (0 fillet) to preserve counter openness
  - Smooth outer convex corner fillets (r = 0.55 * stem_w) on non-terminal bends (ჟ, ჯ, ჳ, etc.)
  - Exact de Casteljau Bézier splitting (zero degradation of original bowls)
  - Safe topological even-odd contour winding normalization (CCW outer / CW inner for CFF)
"""

import math
import numpy as np
import pathops
from scipy.optimize import least_squares
from fontTools.pens.recordingPen import RecordingPen

# a rounded reference empirically measured cubic handle factor at 90°
KAPPA_90_CIRCLE = 4.0 / 3.0 * (math.sqrt(2.0) - 1.0)  # 0.5522847498
ROUND_TENSION_RATIO = 0.580 / KAPPA_90_CIRCLE            # ~1.05018


def v_add(a, b): return (a[0] + b[0], a[1] + b[1])
def v_sub(a, b): return (a[0] - b[0], a[1] - b[1])
def v_mul(a, s): return (a[0] * s, a[1] * s)
def v_dot(a, b): return a[0] * b[0] + a[1] * b[1]
def v_cross(a, b): return a[0] * b[1] - a[1] * b[0]
def v_len(a): return math.hypot(a[0], a[1])


def v_norm(a):
    L = math.hypot(a[0], a[1])
    return (a[0] / L, a[1] / L) if L > 1e-12 else (1.0, 0.0)


def rot90_ccw(v): return (-v[1], v[0])
def rot90_cw(v): return (v[1], -v[0])


# ---------------------------------------------------------------------------
# Segment primitives: ('line', (p0, p1)) or ('cubic', (p0, p1, p2, p3))
# ---------------------------------------------------------------------------

def eval_seg(seg, t):
    kind, pts = seg
    if kind == "line":
        p0, p1 = pts
        return (p0[0] + t * (p1[0] - p0[0]), p0[1] + t * (p1[1] - p0[1]))
    p0, p1, p2, p3 = pts
    mt = 1.0 - t
    mt2, t2 = mt * mt, t * t
    return (
        mt2 * mt * p0[0] + 3 * mt2 * t * p1[0] + 3 * mt * t2 * p2[0] + t2 * t * p3[0],
        mt2 * mt * p0[1] + 3 * mt2 * t * p1[1] + 3 * mt * t2 * p2[1] + t2 * t * p3[1],
    )


def deriv_seg(seg, t):
    kind, pts = seg
    if kind == "line":
        p0, p1 = pts
        return (p1[0] - p0[0], p1[1] - p0[1])
    p0, p1, p2, p3 = pts
    mt = 1.0 - t
    dx = 3 * mt * mt * (p1[0] - p0[0]) + 6 * mt * t * (p2[0] - p1[0]) + 3 * t * t * (p3[0] - p2[0])
    dy = 3 * mt * mt * (p1[1] - p0[1]) + 6 * mt * t * (p2[1] - p1[1]) + 3 * t * t * (p3[1] - p2[1])
    if math.hypot(dx, dy) < 1e-7:
        eps = 1e-4 if t < 0.5 else -1e-4
        a = eval_seg(seg, max(0.0, min(1.0, t)))
        b = eval_seg(seg, max(0.0, min(1.0, t + eps)))
        return ((b[0] - a[0]) / eps, (b[1] - a[1]) / eps)
    return (dx, dy)


def tan_seg(seg, t):
    return v_norm(deriv_seg(seg, t))


def split_seg(seg, t):
    """Exact de Casteljau split at parameter t in (0, 1). Returns (left_seg, right_seg)."""
    t = max(0.0, min(1.0, t))
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


def sub_seg(seg, t0, t1):
    """Extract sub-segment on [t0, t1] where 0 <= t0 < t1 <= 1."""
    if t0 <= 1e-9 and t1 >= 1.0 - 1e-9:
        return seg
    if t0 > 1e-9:
        _, right = split_seg(seg, t0)
        t1_adj = (t1 - t0) / (1.0 - t0)
        if t1_adj >= 1.0 - 1e-9:
            return right
        left, _ = split_seg(right, t1_adj)
        return left
    else:
        left, _ = split_seg(seg, t1)
        return left


def seg_arc_table(seg, samples=32):
    """Return cumulative arc-length table (ts, lengths) for fast s <-> t lookup."""
    kind, pts = seg
    if kind == "line":
        L = v_len(v_sub(pts[1], pts[0]))
        return np.array([0.0, 1.0]), np.array([0.0, L])
    ts = np.linspace(0.0, 1.0, samples + 1)
    lens = np.zeros(samples + 1)
    prev = pts[0]
    acc = 0.0
    for i in range(1, samples + 1):
        cur = eval_seg(seg, float(ts[i]))
        acc += math.hypot(cur[0] - prev[0], cur[1] - prev[1])
        lens[i] = acc
        prev = cur
    return ts, lens


def seg_length(seg):
    if seg[0] == "line":
        return v_len(v_sub(seg[1][1], seg[1][0]))
    _, lens = seg_arc_table(seg, samples=24)
    return float(lens[-1])


def turn_angle_deg(t_in, t_out):
    return math.degrees(math.atan2(v_cross(t_in, t_out), max(-1.0, min(1.0, v_dot(t_in, t_out)))))


def contour_signed_area(segs):
    pts = []
    for seg in segs:
        if seg[0] == "line":
            pts.append(seg[1][0])
        else:
            for k in range(8):
                pts.append(eval_seg(seg, k / 8.0))
    area = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def reverse_contour(segs):
    """Reverse segment order & control points of a single contour."""
    rev = []
    for kind, pts in reversed(segs):
        if kind == "line":
            rev.append(("line", (pts[1], pts[0])))
        else:
            rev.append(("cubic", (pts[3], pts[2], pts[1], pts[0])))
    return rev


def fix_disjoint_outer_winding(contours):
    """
    Enforce exact PostScript winding via topological even-odd nesting depth:
      depth even (outer contours) -> CCW (+area)
      depth odd  (inner holes)    -> CW  (-area)
    Uses multi-point containment + strict area hierarchy so overlapping multi-component
    glyphs are never falsely inverted, while fixing all upstream FiraGO/FiraSans
    winding bugs (Lcaron, lcaron, lcaron.sc, Italic zero, Italic percent, etc.).
    Returns (fixed_contours, changed_flag).
    """
    if not contours:
        return contours, False
    if len(contours) == 1:
        area = contour_signed_area(contours[0])
        if area < -1.0:
            return [reverse_contour(contours[0])], True
        return contours, False

    paths = []
    areas = []
    for c in contours:
        p = pathops.Path()
        draw_contours_to_pen([c], p.getPen(), round_coords=False)
        paths.append(p)
        areas.append(contour_signed_area(c))

    out = []
    changed = False
    for i, c in enumerate(contours):
        if abs(areas[i]) < 1.0:
            out.append(c)
            continue
        pts = [seg[1][0] for seg in c]
        step = max(1, len(pts) // 6)
        samples = pts[::step][:6]
        depth = 0
        for j in range(len(contours)):
            if j == i or abs(areas[j]) <= abs(areas[i]):
                continue
            inside = sum(1 for pt in samples if paths[j].contains(pt))
            if inside >= max(1, len(samples) - 1):
                depth += 1
        want_positive = (depth % 2 == 0)
        is_positive = (areas[i] > 0)
        if want_positive != is_positive:
            out.append(reverse_contour(c))
            changed = True
        else:
            out.append(c)
    return out, changed


def extract_contours(font, gname):
    """Extract closed cubic/line contours from a font glyph (CFF or TTF via quadratic elevation)."""
    pen = RecordingPen()
    font.getGlyphSet()[gname].draw(pen)
    contours, segs = [], []
    cur = start = None
    for op, args in pen.value:
        if op == "moveTo":
            if segs:
                contours.append(segs)
            segs = []
            cur = start = (float(args[0][0]), float(args[0][1]))
        elif op == "lineTo":
            p1 = (float(args[0][0]), float(args[0][1]))
            if cur is not None and v_len(v_sub(p1, cur)) > 1e-3:
                segs.append(("line", (cur, p1)))
                cur = p1
        elif op == "curveTo":
            p1 = (float(args[0][0]), float(args[0][1]))
            p2 = (float(args[1][0]), float(args[1][1]))
            p3 = (float(args[2][0]), float(args[2][1]))
            if cur is not None and (v_len(v_sub(p3, cur)) > 1e-3 or v_len(v_sub(p1, cur)) > 1e-3):
                segs.append(("cubic", (cur, p1, p2, p3)))
                cur = p3
        elif op == "qCurveTo":
            # Exact TrueType quadratic spline decomposition + degree elevation to cubic
            pts = [(float(p[0]), float(p[1])) for p in args if p is not None]
            if not pts or cur is None:
                continue
            p0 = cur
            for idx in range(len(pts) - 1):
                q = pts[idx]
                if idx < len(pts) - 2:
                    p2 = ((q[0] + pts[idx + 1][0]) * 0.5, (q[1] + pts[idx + 1][1]) * 0.5)
                else:
                    p2 = pts[-1]
                c1 = (p0[0] + (2.0 / 3.0) * (q[0] - p0[0]), p0[1] + (2.0 / 3.0) * (q[1] - p0[1]))
                c2 = (p2[0] + (2.0 / 3.0) * (q[0] - p2[0]), p2[1] + (2.0 / 3.0) * (q[1] - p2[1]))
                if v_len(v_sub(p2, p0)) > 1e-3:
                    segs.append(("cubic", (p0, c1, c2, p2)))
                p0 = p2
            cur = p0
        elif op == "closePath":
            if start is not None and cur is not None and v_len(v_sub(start, cur)) > 1e-3:
                segs.append(("line", (cur, start)))
            if segs:
                contours.append(segs)
            segs = []
            cur = start = None
    if segs:
        contours.append(segs)
    return contours


def draw_contours_to_pen(contours, pen, round_coords=True, half_unit=False):
    """Replay contours onto a fontTools segment pen."""
    def _snap_half(v):
        r = round(v * 2.0) / 2.0
        return int(r) if r == int(r) else r

    def fmt(p):
        if half_unit:
            return (_snap_half(p[0]), _snap_half(p[1]))
        return (int(round(p[0])), int(round(p[1]))) if round_coords else p

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
            p_nxt_start = nxt[1][0]
            if p_end != p_nxt_start:
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


# ---------------------------------------------------------------------------
# Smooth Chain Walker (walks across G1-smooth nodes up to next sharp corner)
# ---------------------------------------------------------------------------

class SmoothChain:
    """Arc-length parameterized walk along consecutive G1-smooth contour segments."""
    def __init__(self, segs, indices, reverse=False):
        self.segs = segs
        self.indices = indices
        self.reverse = reverse
        self.tables = []
        self.cum_starts = []
        acc = 0.0
        for idx in indices:
            ts, lens = seg_arc_table(segs[idx], samples=36)
            L = float(lens[-1])
            self.tables.append((ts, lens, L))
            self.cum_starts.append(acc)
            acc += L
        self.total_len = acc

    def locate(self, s):
        s = max(0.0, min(self.total_len, float(s)))
        for k, idx in enumerate(self.indices):
            ts, lens, L = self.tables[k]
            s0 = self.cum_starts[k]
            if s <= s0 + L + 1e-9 or k == len(self.indices) - 1:
                local_s = max(0.0, min(L, s - s0))
                target = max(0.0, L - local_s) if self.reverse else local_s
                if L < 1e-9:
                    t = 1.0 if self.reverse else 0.0
                else:
                    t = float(np.interp(target, lens, ts))
                return k, idx, t
        return 0, self.indices[0], (1.0 if self.reverse else 0.0)

    def eval_point_and_inward_normal(self, s):
        _, idx, t = self.locate(s)
        seg = self.segs[idx]
        pt = eval_seg(seg, t)
        ft = tan_seg(seg, t)
        inward_n = rot90_ccw(ft)
        return pt, ft, inward_n


def build_chain(segs, turns, start_seg_idx, reverse, max_segs=6, corner_thresh=20.0):
    n = len(segs)
    indices = [start_seg_idx]
    cur = start_seg_idx
    for _ in range(max_segs - 1):
        if reverse:
            if abs(turns[cur]) > corner_thresh:
                break
            nxt = (cur - 1) % n
        else:
            nxt_v = (cur + 1) % n
            if abs(turns[nxt_v]) > corner_thresh:
                break
            nxt = nxt_v
        if nxt in indices:
            break
        indices.append(nxt)
        cur = nxt
    return SmoothChain(segs, indices, reverse=reverse)


# ---------------------------------------------------------------------------
# Circular / Superelliptical Cubic Arc Builders
# ---------------------------------------------------------------------------

def arc_cubic_segment(center, radius, theta0, theta1, tension_ratio=ROUND_TENSION_RATIO):
    dtheta = theta1 - theta0
    k = (4.0 / 3.0) * math.tan(dtheta / 4.0) * tension_ratio
    p0 = (center[0] + radius * math.cos(theta0), center[1] + radius * math.sin(theta0))
    p3 = (center[0] + radius * math.cos(theta1), center[1] + radius * math.sin(theta1))
    t0 = (-math.sin(theta0), math.cos(theta0))
    t1 = (-math.sin(theta1), math.cos(theta1))
    p1 = (p0[0] + k * radius * t0[0], p0[1] + k * radius * t0[1])
    p2 = (p3[0] - k * radius * t1[0], p3[1] - k * radius * t1[1])
    return ("cubic", (p0, p1, p2, p3))


def build_cap_arcs(center, radius, pt_a, pt_b, n_cap):
    th_a = math.atan2(pt_a[1] - center[1], pt_a[0] - center[0])
    th_b = math.atan2(pt_b[1] - center[1], pt_b[0] - center[0])
    sweep = (th_b - th_a) % (2.0 * math.pi)
    if sweep < 1e-3:
        sweep += 2.0 * math.pi

    th_mid = th_a + 0.5 * sweep
    th_ncap = math.atan2(n_cap[1], n_cap[0])
    rel_ncap = (th_ncap - th_a) % (2.0 * math.pi)
    if 0.35 * sweep <= rel_ncap <= 0.65 * sweep and rel_ncap <= math.radians(102) and (sweep - rel_ncap) <= math.radians(102):
        th_split = th_a + rel_ncap
    else:
        th_split = th_mid

    if sweep > math.radians(205):
        t1 = th_a + sweep / 3.0
        t2 = th_a + 2.0 * sweep / 3.0
        arcs = [
            arc_cubic_segment(center, radius, th_a, t1),
            arc_cubic_segment(center, radius, t1, t2),
            arc_cubic_segment(center, radius, t2, th_a + sweep),
        ]
    else:
        arcs = [
            arc_cubic_segment(center, radius, th_a, th_split),
            arc_cubic_segment(center, radius, th_split, th_a + sweep),
        ]

    p0, p1, p2, p3 = arcs[0][1]
    arcs[0] = ("cubic", (pt_a, p1, p2, p3))
    q0, q1, q2, q3 = arcs[-1][1]
    arcs[-1] = ("cubic", (q0, q1, q2, pt_b))
    return arcs


def build_corner_arc(center, radius, pt_a, pt_b):
    th_a = math.atan2(pt_a[1] - center[1], pt_a[0] - center[0])
    th_b = math.atan2(pt_b[1] - center[1], pt_b[0] - center[0])
    sweep = (th_b - th_a) % (2.0 * math.pi)
    if sweep > math.radians(105):
        th_m = th_a + 0.5 * sweep
        arcs = [
            arc_cubic_segment(center, radius, th_a, th_m),
            arc_cubic_segment(center, radius, th_m, th_a + sweep),
        ]
    else:
        arcs = [arc_cubic_segment(center, radius, th_a, th_a + sweep)]
    p0, p1, p2, p3 = arcs[0][1]
    arcs[0] = ("cubic", (pt_a, p1, p2, p3))
    q0, q1, q2, q3 = arcs[-1][1]
    arcs[-1] = ("cubic", (q0, q1, q2, pt_b))
    return arcs


# ---------------------------------------------------------------------------
# Exact Inscribed-Circle Solvers
# ---------------------------------------------------------------------------

def solve_inscribed_cap(chain_in, chain_out, p0, p1, overshoot=0.0, max_s_in=None, max_s_out=None):
    edge = v_sub(p1, p0)
    L_cap = v_len(edge)
    e = v_norm(edge)
    n_cap = rot90_cw(e)
    mid = ((p0[0] + p1[0]) * 0.5, (p0[1] + p1[1]) * 0.5)

    _, ft_in0, _ = chain_in.eval_point_and_inward_normal(0.0)
    _, ft_out0, _ = chain_out.eval_point_and_inward_normal(0.0)
    d_out = v_norm(v_sub(ft_in0, ft_out0))
    n_perp = rot90_ccw(d_out)
    w_perp = abs(v_dot(edge, n_perp))
    r_init = max(2.0, w_perp * 0.5)

    # Local arc-length search bound prevents sliding around tight 180° hooks
    max_local_s = max(2.75 * r_init, 1.55 * L_cap)
    lim_in = min(chain_in.total_len * 0.96, max_local_s, max_s_in if max_s_in is not None else chain_in.total_len * 0.96)
    lim_out = min(chain_out.total_len * 0.96, max_local_s, max_s_out if max_s_out is not None else chain_out.total_len * 0.96)

    def try_solve(tip_shift):
        m_tip = v_add(mid, v_mul(n_cap, tip_shift))

        def residuals(x):
            s0, s1, r = float(x[0]), float(x[1]), float(x[2])
            pa, _, na = chain_in.eval_point_and_inward_normal(s0)
            pb, _, nb = chain_out.eval_point_and_inward_normal(s1)
            ca = v_add(pa, v_mul(na, r))
            cb = v_add(pb, v_mul(nb, r))
            cm = ((ca[0] + cb[0]) * 0.5, (ca[1] + cb[1]) * 0.5)
            tip_err = v_dot(v_sub(cm, m_tip), n_cap) + r
            return [ca[0] - cb[0], ca[1] - cb[1], tip_err]

        if lim_in < 0.5 or lim_out < 0.5:
            return None
        proj_diff = v_dot(v_sub(p1, p0), d_out)
        s0_init = max(0.0, min(lim_in * 0.8, r_init - tip_shift - 0.5 * proj_diff))
        s1_init = max(0.0, min(lim_out * 0.8, r_init - tip_shift + 0.5 * proj_diff))
        r_lo = max(0.5, r_init * 0.45)
        r_hi = max(r_lo + 1.0, r_init * 1.55)
        r_init_c = max(r_lo, min(r_hi, r_init))

        res = least_squares(
            residuals,
            x0=[s0_init, s1_init, r_init_c],
            bounds=([0.0, 0.0, r_lo], [lim_in, lim_out, r_hi]),
            ftol=1e-9, xtol=1e-9, gtol=1e-9, max_nfev=200,
        )
        err = math.sqrt(sum(v * v for v in res.fun))
        s0, s1, r = float(res.x[0]), float(res.x[1]), float(res.x[2])
        if err < 0.85:
            pa, _, na = chain_in.eval_point_and_inward_normal(s0)
            pb, _, nb = chain_out.eval_point_and_inward_normal(s1)
            ca = v_add(pa, v_mul(na, r))
            cb = v_add(pb, v_mul(nb, r))
            center = ((ca[0] + cb[0]) * 0.5, (ca[1] + cb[1]) * 0.5)
            sideways_drift = abs(v_dot(v_sub(center, m_tip), e))
            if sideways_drift > max(0.85 * r_init, 0.55 * L_cap):
                return None
            th_a = math.atan2(pa[1] - center[1], pa[0] - center[0])
            th_b = math.atan2(pb[1] - center[1], pb[0] - center[0])
            sweep = (th_b - th_a) % (2.0 * math.pi)
            if math.radians(85) <= sweep <= math.radians(240):
                return {
                    "kind": "full_cap",
                    "s0": s0, "s1": s1, "r": r,
                    "center": center, "pa": pa, "pb": pb,
                    "n_cap": n_cap, "err": err,
                }
        return None

    sol = try_solve(overshoot)
    if sol is not None:
        return sol

    for frac in (0.12, 0.24, 0.36):
        sol = try_solve(overshoot + frac * r_init)
        if sol is not None:
            return sol

    return {
        "kind": "short_stub_fallback",
        "r_nom": r_init,
        "lim_in": lim_in,
        "lim_out": lim_out,
        "n_cap": n_cap,
        "overshoot": overshoot,
    }


def solve_corner_fillet(chain_in, chain_out, target_r, max_s_in=None, max_s_out=None):
    lim_in = min(chain_in.total_len * 0.85, max_s_in if max_s_in is not None else chain_in.total_len * 0.85)
    lim_out = min(chain_out.total_len * 0.85, max_s_out if max_s_out is not None else chain_out.total_len * 0.85)

    if lim_in < 0.2 or lim_out < 0.2:
        return None

    _, ft_in, _ = chain_in.eval_point_and_inward_normal(0.0)
    _, ft_out, _ = chain_out.eval_point_and_inward_normal(0.0)
    ang = math.radians(max(5.0, min(175.0, turn_angle_deg(ft_in, ft_out))))
    tan_half = math.tan(ang * 0.5)
    # Cap pullback distance on acute cusps (>94°, e.g. 135° arrowheads ⇧/⇩/⇪ or crescent ⏾)
    # while leaving all <=94° corners (ჟ, ჯ, ჳ, E, L, Д, Щ) 100% untouched!
    max_pull = target_r * 1.08
    max_r_geom = min(lim_in, lim_out, max_pull) / max(tan_half, 0.1) * 0.92
    r = min(target_r, max_r_geom)
    if r < 1.5:
        return None

    for scale in (1.0, 0.8, 0.6, 0.4):
        r_try = r * scale
        if r_try < 1.5:
            break
        s_guess = max(0.05, min(lim_in * 0.7, lim_out * 0.7, r_try * tan_half))

        def residuals(x):
            s0, s1 = float(x[0]), float(x[1])
            pa, _, na = chain_in.eval_point_and_inward_normal(s0)
            pb, _, nb = chain_out.eval_point_and_inward_normal(s1)
            ca = v_add(pa, v_mul(na, r_try))
            cb = v_add(pb, v_mul(nb, r_try))
            return [ca[0] - cb[0], ca[1] - cb[1]]

        res = least_squares(
            residuals,
            x0=[s_guess, s_guess],
            bounds=([0.05, 0.05], [lim_in, lim_out]),
            ftol=1e-9, xtol=1e-9, gtol=1e-9, max_nfev=150,
        )
        err = math.sqrt(res.fun[0]**2 + res.fun[1]**2)
        if err < 0.35:
            s0, s1 = float(res.x[0]), float(res.x[1])
            pa, _, na = chain_in.eval_point_and_inward_normal(s0)
            pb, _, nb = chain_out.eval_point_and_inward_normal(s1)
            ca = v_add(pa, v_mul(na, r_try))
            cb = v_add(pb, v_mul(nb, r_try))
            center = ((ca[0] + cb[0]) * 0.5, (ca[1] + cb[1]) * 0.5)
            return {
                "s0": s0, "s1": s1, "r": r_try,
                "center": center, "pa": pa, "pb": pb,
            }
    return None


# ---------------------------------------------------------------------------
# Contour-Level Rounding Orchestrator
# ---------------------------------------------------------------------------

def measure_font_metrics(font):
    """Measure key vertical zones and reference vertical stem width from a font."""
    os2 = font["OS/2"]
    x_height = float(getattr(os2, "sxHeight", 527))
    cap_height = float(getattr(os2, "sCapHeight", 689))

    def collect_stems(glyph_list):
        widths = []
        asc_tops = []
        gs = font.getGlyphSet()
        for gname in glyph_list:
            if gname not in gs:
                continue
            for segs in extract_contours(font, gname):
                n = len(segs)
                if n < 3:
                    continue
                turns = [turn_angle_deg(tan_seg(segs[(i - 1) % n], 1.0), tan_seg(segs[i], 0.0)) for i in range(n)]
                for i, seg in enumerate(segs):
                    if seg[0] == "line" and turns[i] > 50 and turns[(i + 1) % n] > 50:
                        p0, p1 = seg[1]
                        t_prev = tan_seg(segs[(i - 1) % n], 1.0)
                        t_next = tan_seg(segs[(i + 1) % n], 0.0)
                        if v_dot(t_prev, t_next) < -0.9:
                            L = v_len(v_sub(p1, p0))
                            if 10 < L < 260:
                                widths.append(L)
                                my = 0.5 * (p0[1] + p1[1])
                                if my > cap_height + 15:
                                    asc_tops.append(my)
        return widths, asc_tops

    widths, asc_tops = collect_stems(("uni10E5", "uni10EB", "uni10EE", "uni10E2", "uni10E1", "uni10D8"))
    if len(widths) < 4:
        w2, a2 = collect_stems(("I", "H", "l", "n"))
        widths.extend(w2)
        asc_tops.extend(a2)

    stem_w = float(np.median(widths)) if widths else 88.0
    asc_top = float(np.median(asc_tops)) if asc_tops else (cap_height + 60.0)
    return {
        "stem_w": stem_w,
        "x_height": x_height,
        "cap_height": cap_height,
        "asc_top": asc_top,
    }


def compute_optical_overshoot(p0, p1, n_cap, metrics):
    stem_w = metrics["stem_w"]
    mid_y = 0.5 * (p0[1] + p1[1])

    if n_cap[1] < -0.85 and abs(p0[1]) <= 6.0 and abs(p1[1]) <= 6.0:
        return min(0.085 * stem_w, 10.0)

    if n_cap[1] > 0.85:
        if abs(mid_y - metrics["x_height"]) <= 12.0:
            return min(0.065 * stem_w, 8.0)
        if abs(mid_y - metrics["cap_height"]) <= 14.0:
            return min(0.065 * stem_w, 8.0)
        if abs(mid_y - metrics["asc_top"]) <= 18.0:
            return min(0.060 * stem_w, 7.5)

    return 0.0


def round_contour(segs, metrics, enable_outer_corners=True, enable_overshoot=True):
    """
    Round all stroke terminals and sharp outer convex corners on a single PostScript contour.
    Preserves all concave junctions (inner crotches) crisp and leaves all untouched curves exact.
    """
    n = len(segs)
    if n < 3:
        return segs

    stem_w = metrics["stem_w"]
    seg_lens = [seg_length(s) for s in segs]
    turns = [turn_angle_deg(tan_seg(segs[(i - 1) % n], 1.0), tan_seg(segs[i], 0.0)) for i in range(n)]

    # ---- Step 1: Identify Terminal Caps ----
    raw_caps = []
    for i in range(n):
        if segs[i][0] != "line":
            continue
        a0, a1 = turns[i], turns[(i + 1) % n]
        if a0 > 25.0 and a1 > 25.0:
            t_prev = tan_seg(segs[(i - 1) % n], 1.0)
            t_next = tan_seg(segs[(i + 1) % n], 0.0)
            wdot = v_dot(t_prev, t_next)
            if wdot < -0.72:
                p0, p1 = segs[i][1]
                d_out = v_norm(v_sub(t_prev, t_next))
                n_perp = rot90_ccw(d_out)
                w_perp = abs(v_dot(v_sub(p1, p0), n_perp))
                L = seg_lens[i]
                if w_perp <= 1.52 * stem_w and L <= 1.65 * stem_w and L >= 4.0:
                    raw_caps.append((i, L, w_perp))

    raw_caps.sort(key=lambda x: x[1])
    cap_indices = set()
    used_verts = set()
    for i, L, w_perp in raw_caps:
        v0, v1 = i, (i + 1) % n
        if v0 in used_verts or v1 in used_verts:
            continue
        prev_i = (i - 1) % n
        next_i = (i + 1) % n
        if segs[prev_i][0] == "line" and segs[next_i][0] == "line":
            if L > 1.15 * max(seg_lens[prev_i], seg_lens[next_i]) and turns[prev_i] > 25 and turns[(next_i + 1) % n] > 25:
                continue
        cap_indices.add(i)
        used_verts.add(v0)
        used_verts.add(v1)

    # ---- Step 2: Identify Standalone Outer Convex Corners ----
    corner_verts = set()
    if enable_outer_corners:
        for i in range(n):
            if i in used_verts:
                continue
            if turns[i] > 28.0:
                corner_verts.add(i)

    if not cap_indices and not corner_verts:
        return segs

    # ---- Step 3: Compute available arc-length budgets ----
    def chain_budget(chain):
        last_idx = chain.indices[-1]
        far_v = last_idx if chain.reverse else (last_idx + 1) % n
        if far_v in used_verts or far_v in corner_verts:
            return max(chain.total_len * 0.48, min(chain.total_len * 0.72, chain.total_len - 0.65 * stem_w))
        return chain.total_len * 0.95

    operations = []

    for i in sorted(cap_indices):
        p0, p1 = segs[i][1]
        edge = v_sub(p1, p0)
        n_cap = rot90_cw(v_norm(edge))
        overshoot = compute_optical_overshoot(p0, p1, n_cap, metrics) if enable_overshoot else 0.0

        chain_in = build_chain(segs, turns, (i - 1) % n, reverse=True)
        chain_out = build_chain(segs, turns, (i + 1) % n, reverse=False)
        b_in = chain_budget(chain_in)
        b_out = chain_budget(chain_out)

        sol = solve_inscribed_cap(chain_in, chain_out, p0, p1, overshoot=overshoot, max_s_in=b_in, max_s_out=b_out)

        if sol["kind"] == "full_cap":
            k_in, seg_in_idx, t_in = chain_in.locate(sol["s0"])
            k_out, seg_out_idx, t_out = chain_out.locate(sol["s1"])
            arcs = build_cap_arcs(sol["center"], sol["r"], sol["pa"], sol["pb"], sol["n_cap"])
            swallowed = {i}
            for kk in range(k_in):
                swallowed.add(chain_in.indices[kk])
            for kk in range(k_out):
                swallowed.add(chain_out.indices[kk])
            operations.append({
                "type": "cap",
                "anchor": i,
                "seg_in": seg_in_idx, "t_in": t_in,
                "seg_out": seg_out_idx, "t_out": t_out,
                "swallowed": swallowed,
                "arcs": arcs,
            })
        else:
            r_nom = sol["r_nom"]
            pull = max(1.0, min(b_in, b_out, r_nom) * 0.90)
            k_in, seg_in_idx, t_in = chain_in.locate(pull)
            k_out, seg_out_idx, t_out = chain_out.locate(pull)
            pa, ft_a, _ = chain_in.eval_point_and_inward_normal(pull)
            pb, ft_b, _ = chain_out.eval_point_and_inward_normal(pull)

            ab = v_sub(pb, pa)
            rx = max(1.0, 0.5 * v_len(ab))
            e_base = v_norm(ab)
            n_dome = rot90_cw(e_base)
            base_mid = ((pa[0] + pb[0]) * 0.5, (pa[1] + pb[1]) * 0.5)
            orig_mid = ((p0[0] + p1[0]) * 0.5, (p0[1] + p1[1]) * 0.5)
            h_orig = max(1.0, v_dot(v_sub(orig_mid, base_mid), n_dome))

            deficit = max(0.0, rx - h_orig)
            bump = min(0.34 * rx, deficit * 0.60) + overshoot
            ry = min(rx, max(h_orig + overshoot, h_orig + bump))
            apex = v_add(base_mid, v_mul(n_dome, ry))

            c1a = v_add(pa, v_mul(ft_a, 0.580 * ry))
            c2a = v_sub(apex, v_mul(e_base, 0.580 * rx))
            c1b = v_add(apex, v_mul(e_base, 0.580 * rx))
            c2b = v_sub(pb, v_mul(ft_b, 0.580 * ry))
            arcs = [
                ("cubic", (pa, c1a, c2a, apex)),
                ("cubic", (apex, c1b, c2b, pb)),
            ]

            swallowed = {i}
            for kk in range(k_in):
                swallowed.add(chain_in.indices[kk])
            for kk in range(k_out):
                swallowed.add(chain_out.indices[kk])
            operations.append({
                "type": "cap_stub",
                "anchor": i,
                "seg_in": seg_in_idx, "t_in": t_in,
                "seg_out": seg_out_idx, "t_out": t_out,
                "swallowed": swallowed,
                "arcs": arcs,
            })

    target_corner_r = 0.55 * stem_w
    for v in sorted(corner_verts):
        chain_in = build_chain(segs, turns, (v - 1) % n, reverse=True)
        chain_out = build_chain(segs, turns, v, reverse=False)
        b_in = chain_budget(chain_in)
        b_out = chain_budget(chain_out)
        sol = solve_corner_fillet(chain_in, chain_out, target_corner_r, max_s_in=b_in, max_s_out=b_out)
        if sol is None:
            continue
        k_in, seg_in_idx, t_in = chain_in.locate(sol["s0"])
        k_out, seg_out_idx, t_out = chain_out.locate(sol["s1"])
        arcs = build_corner_arc(sol["center"], sol["r"], sol["pa"], sol["pb"])
        swallowed = set()
        for kk in range(k_in):
            swallowed.add(chain_in.indices[kk])
        for kk in range(k_out):
            swallowed.add(chain_out.indices[kk])
        operations.append({
            "type": "corner",
            "anchor": v,
            "seg_in": seg_in_idx, "t_in": t_in,
            "seg_out": seg_out_idx, "t_out": t_out,
            "swallowed": swallowed,
            "arcs": arcs,
        })

    if not operations:
        return segs

    # ---- Step 4: Splice all operations cleanly onto the cyclic contour ----
    t_start = [0.0] * n
    t_end = [1.0] * n
    removed = set()
    insert_after = {}

    for op in operations:
        removed.update(op["swallowed"])
        si, so = op["seg_in"], op["seg_out"]
        t_end[si] = min(t_end[si], op["t_in"])
        t_start[so] = max(t_start[so], op["t_out"])
        insert_after[si] = op

    for i in range(n):
        if i not in removed and t_start[i] > t_end[i]:
            tm = 0.5 * (t_start[i] + t_end[i])
            t_start[i] = tm
            t_end[i] = tm

    new_segs = []
    for i in range(n):
        if i not in removed:
            if t_end[i] - t_start[i] > 1e-4:
                new_segs.append(sub_seg(segs[i], t_start[i], t_end[i]))
        if i in insert_after:
            new_segs.extend(insert_after[i]["arcs"])

    return new_segs


def refine_bani_finial(contours, gname, metrics, is_italic=False, rounded=True):
    """
    Optically sculpt the top S-hook finial of Georgian Mtavruli Ბ (uni10D1.case) — and lightly
    Heavy Rounded Mkhedruli ბ (uni10D1) — so the iconic leftward S-neck remains tall, tapered,
    and unmistakable after semicircular terminal rounding across Bold/ExtraBold/Heavy and all
    4 widths (Extra Condensed .. Expanded), matching a rounded reference's legibility
    while preserving exact -8° Italic slant and G1 bowl-neck continuity.
    """
    if gname not in ("uni10D1.case", "uni10D1") or not contours:
        return contours

    stem_w = metrics["stem_w"]
    is_mtav = (gname == "uni10D1.case")

    # Smooth weight ramp: 0 below stem_w=105 (Thin..Regular), 1.0 at Heavy (stem_w≈188)
    wt = max(0.0, min(1.0, (stem_w - 105.0) / 83.0))
    if wt <= 0.01:
        return contours

    outer = contours[0]
    all_pts = [p for _, pts in outer for p in (pts[0], pts[-1])]
    if not all_pts:
        return contours
    y_max = max(p[1] for p in all_pts)
    y_min = min(p[1] for p in all_pts)

    # Locate the top flat cap segment near y_max
    cap_idx = None
    best_y = -1e9
    for i, (k, pts) in enumerate(outer):
        if k == "line":
            ym = 0.5 * (pts[0][1] + pts[1][1])
            dx = abs(pts[1][0] - pts[0][0])
            if ym > y_max - 45 and dx > 15 and ym > best_y:
                best_y = ym
                cap_idx = i
    if cap_idx is None:
        return contours

    cap_p0, cap_p1 = outer[cap_idx][1]
    cap_right_x = max(cap_p0[0], cap_p1[0])
    cap_w = abs(cap_p0[0] - cap_p1[0])
    cap_mid_x = 0.5 * (cap_p0[0] + cap_p1[0])

    # Measure bowl horizontal span to scale swing cleanly across Extra Condensed .. Expanded
    bowl_xs = [p[0] for p in all_pts if p[1] < y_min + 0.60 * (y_max - y_min)]
    bowl_w = (max(bowl_xs) - min(bowl_xs)) if bowl_xs else 560.0
    width_scale = max(0.75, min(1.25, bowl_w / 560.0))

    # Bowl-neck saddle height (concave armpit where finial meets bowl)
    if len(contours) > 1:
        inner_pts = [p for _, pts in contours[1] for p in (pts[0], pts[-1])]
        hole_ymax = max(p[1] for p in inner_pts)
        hole_ymin = min(p[1] for p in inner_pts)
        bot_wall = max(40.0, hole_ymin - y_min)
        y_saddle = hole_ymax + 0.85 * bot_wall
    else:
        y_saddle = y_max - (185.0 if is_mtav else 215.0)

    neck_h = max(60.0, y_max - y_saddle)
    saddle_xs = [p[0] for p in all_pts if abs(p[1] - y_saddle) <= 45 and abs(p[0] - cap_mid_x) <= 220]
    saddle_mid_x = 0.5 * (min(saddle_xs) + max(saddle_xs)) if len(saddle_xs) >= 2 else (cap_mid_x + 45.0)

    if is_mtav:
        if rounded:
            # Post-L1.07: L1.07 already gives uni10D1.case the full +44.5u tall neck,
            # so add only subtle +6u optical rounded-cap overshoot (zero double-lift!)
            # while keeping full rounded finial taper, S-hook swing & tilt.
            dy_lift = 6.0 * wt
            taper_end = 1.0 - 0.21 * wt
            dx_swing = -28.0 * wt * width_scale
            left_tilt = -12.0 * wt
        else:
            # Post-L1.07: Sharp uni10D1.case already has its exact +44.5u tall neck from L1.07
            return contours
    else:
        if not rounded:
            return contours
        # Gentle Heavy Rounded finial taper & S-hook poise for Mkhedruli ბ
        dy_lift = 10.0 * wt
        taper_end = 1.0 - 0.14 * wt
        dx_swing = -14.0 * wt * width_scale
        left_tilt = 0.0

    shear = math.tan(math.radians(8.0)) if is_italic else 0.0

    def map_pt(pt):
        x, y = pt
        if y <= y_saddle:
            return pt
        u = max(0.0, min(1.0, (y - y_saddle) / neck_h))
        s_w = u * u * (3.0 - 2.0 * u)
        s_y = 0.25 * u + 0.75 * s_w

        dy = dy_lift * s_y
        cx_u = saddle_mid_x + u * (cap_mid_x - saddle_mid_x)
        scale_w = 1.0 + (taper_end - 1.0) * s_w
        new_x = cx_u + (x - cx_u) * scale_w + dx_swing * s_w + dy * shear
        new_y = y + dy

        if left_tilt != 0.0 and u > 0.85:
            left_frac = max(0.0, min(1.0, (cap_right_x - x) / max(cap_w, 1.0)))
            tip_blend = (u - 0.85) / 0.15
            new_y += left_tilt * left_frac * tip_blend

        return (new_x, new_y)

    new_outer = [(kind, tuple(map_pt(p) for p in pts)) for kind, pts in outer]
    return [new_outer] + list(contours[1:])


def round_contours(contours, metrics, enable_outer_corners=True, enable_overshoot=True):
    """
    Round a list of PostScript contours directly.
    Automatically detects thin-stroke wireframe/technical icons (e.g. hollow arrows ⇧/⇩/⇪ or
    crescent ⏾ whose stroke thickness stays thin even in Bold/Heavy) via the exact 2*area/perim
    stroke-width estimator so corner fillets never punch through thin icon walls!
    """
    local_metrics = metrics
    if contours and metrics.get("stem_w", 0) > 60.0:
        net_area = abs(sum(contour_signed_area(c) for c in contours))
        tot_perim = sum(seg_length(s) for c in contours for s in c)
        if tot_perim > 100.0 and net_area > 500.0:
            w_est = 2.0 * net_area / tot_perim
            # Only clamp when glyph's own average stroke is substantially thinner than font stem_w
            # (strictly skips normal Georgian/Latin/Cyrillic/Math letters while protecting thin icons!)
            if w_est < 0.58 * metrics["stem_w"]:
                local_metrics = dict(metrics)
                local_metrics["stem_w"] = max(14.0, w_est)

    return [
        round_contour(segs, local_metrics, enable_outer_corners=enable_outer_corners, enable_overshoot=enable_overshoot)
        for segs in contours
    ]


def round_glyph_contours(font, gname, metrics, enable_outer_corners=True, enable_overshoot=True):
    contours, _ = fix_disjoint_outer_winding(extract_contours(font, gname))
    return round_contours(contours, metrics, enable_outer_corners=enable_outer_corners, enable_overshoot=enable_overshoot)

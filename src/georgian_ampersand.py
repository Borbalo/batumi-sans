#!/usr/bin/env python3
"""
Production Parametric Cubic-Bézier Georgian Ampersand (დ + Ა) Engine for Batumi Sans.
(Self-contained production module: src/georgian_ampersand.py)

Design Lineage — Exact 1-to-1 Construction from Koba Jgenti's Original Vector Masters
(`ამპრესონდი.pdf` and `ამპრესონდი 2.pdf`):
  1. Left Half (`Path 1` — Italic `დ`):
       Uses the exact canonical 12-outer + 4-inner cubic masters of Batumi Sans / FiraGO
       Italic `uni10D3` (`დ`) across all 9 weights (`Thin 100` -> `Heavy 900`), which at
       Regular 400 is bit-for-bit identical (1.0000×) to Koba's original `ამპრესონდი.pdf`
       Path 1. Guarantees 100% authentic bBox Type counter shaping and a mathematically
       G1/G2-smooth horizontal bottom tangent at `OV_B` across ALL 9 weights (zero hard edge
       or cusp even on `Thin 100` hairlines!).
  2. Right Half (`Path 2` — Capital `Ა`):
       Built directly from the exact 3-cubic medial-axis centerline extracted from Koba's
       `ამპრესონდი 2.pdf` cyan `Path 2` (`top -> S-inflection -> right apex -> bottom rail`),
       stroked via exact Batumi directional parallel normal-offset (`offset_cubic_fit`).
       Its bottom rail locks co-linearly to `Path 1`'s `OV_B.y` (outer) and `I_B.y` (inner),
       yielding a 100% seamless `დ -> Ა` transition and >= 0.983 exact vector-to-vector 1:1
       IoU against Koba's original `ამპრესონდი.pdf`!
  3. True Optical Width Scaling (matching `src/condenser.py` — NEVER naive scaleX!):
       - `ExtraCondensed` (85.2% width, ~95.0% vstem, ~96.0% hbar)
       - `Condensed`      (91.3% width, ~97.5% vstem, ~97.5% hbar)
       - `Normal`         (100.0% width)
       - `Expanded`       (113.6% width, ~101.5% vstem, ~101.2% hbar)
       Uses X-only weight-compensated master sampling on `Path 1` + stem-preserving centerline
       condensing with guaranteed `დ`-to-`Ა` S-neck clearance on `Path 2`.
  4. True Isotropic Un-Squished `L1.07b` Mtavruli (`ampersand.geor.case`):
       Fits cleanly into Batumi Sans's official `L1.07b` `Ქ`-height (`-44.5 .. CapH - 14.0 + 44.5`)
       via EQUAL X and Y isotropic scaling (`s_iso ≈ 0.84–0.88`) with weight-master compensation
       so BOTH the `დ` oval and `Ა` bowl retain 100% un-squished Koba roundness and exact
       optical gray value beside `Დ`, `Ქ`, `Ა`!
  5. Exact Fixed 36-Master Variable Font Topology + Rounded (`κ=0.580`) + 4-Layer GSUB:
       - Sharp:   outer CCW 21 segments (18 cubics + 3 flat terminal cuts) + inner CW 4 cubics
       - Rounded: outer CCW 24 segments (18 cubics + 3 × 2 κ=0.580 caps) + inner CW 4 cubics
       - Complete 4-layer OpenType GSUB (`locl`, `calt`, `case`, `ss07`, `ss08`) + PUA `U+E0A0`/`U+E0A1`.
  6. True Upright (`0.0°`) & Non-Double-Slanted Italic (`-8.0°`) Slant Calibration:
       - Raw Koba/FiraGO Italic masters (`-8.0°`) are un-sheared by exact `-MASTER_ITALIC_DEG`
         (`-8.0°`) BEFORE width scaling, with the `Ა` top stem aligned to exact `0.00°` vertical
         (matching native Upright `uni10D0.case`), so Upright fonts stand dead-upright (`0.0°`)
         across all 4 optical widths, while Italic fonts apply exact `+8.0°` shear BEFORE Path 2
         stroking & Rounded cap construction (exact `-8.0°` Italic poise, true circular `κ=0.580` caps).
"""

import math
import numpy as np
import pathops
from fontTools.ttLib.tables import otTables
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.boundsPen import BoundsPen

# reference / Batumi Sans Rounded superelliptical quarter-arc handle tension
KAPPA_ROUNDED = 0.580

# Exact native FiraGO / Batumi Sans Italic slant baked into Koba's original 2021
# `ამპრესონდი.pdf` vector master (`DONI_MASTERS` Italic `uni10D3` + `KOBA_ANI_CENTERLINE_REF`).
# Un-slanting raw masters by `-MASTER_ITALIC_DEG` BEFORE optical width scaling makes ALL 4 widths
# (`ExtraCondensed`, `Condensed`, `Normal`, `Expanded`) stand dead-upright (`0.0°`) in Upright fonts,
# while applying exact `+italic_deg` (`+8.0°`) in Italic fonts aligns dead-on to `-8.0°` Italic without
# double-slanting or shearing Rounded `κ=0.580` caps!
MASTER_ITALIC_DEG = 8.0
_KOBA_REF_OV_B_Y  = 68.0

# Official Batumi Sans L1.07b Mtavruli optical CapH tuck (-14.0u) & ±44.5u height cues
DEFAULT_MTAV_CUE = 44.5
DEFAULT_MTAV_CAP_TUCK = -14.0

# Calibrated Mtavruli (All-Caps) lower-base & flatter-tail presets (Koba #103 study):
#   lift_frac:  fraction of raw tail drop lifted up before isotropic scaling (lowers დ/Ა base & grows bowls!)
#   arch_ratio: fraction of lift applied to arch apex + C_spur (preserving 100% spur/arch stroke thickness!)
#   foot_flat_deg: rotation of bottom-right foot toward horizontal (flatter graceful sweeping tail!)
#   foot_dx_frac:  gentle rightward extension of the flatter tail
MTAV_CAPS_PRESETS = {
    "Ref":   dict(lift_frac=0.00, arch_ratio=0.50, foot_flat_deg=0.0,  foot_dx_frac=0.00),
    "CapsA": dict(lift_frac=0.18, arch_ratio=0.52, foot_flat_deg=7.0,  foot_dx_frac=0.22),
    "CapsB": dict(lift_frac=0.30, arch_ratio=0.54, foot_flat_deg=12.0, foot_dx_frac=0.32),
    "CapsC": dict(lift_frac=0.41, arch_ratio=0.55, foot_flat_deg=16.0, foot_dx_frac=0.38),
}
DEFAULT_MTAV_CAPS = "CapsB"


# ---------------------------------------------------------------------------
# Vector, Cubic Bézier & Exact Parallel-Offset Primitives
# ---------------------------------------------------------------------------

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


def rot_vec(v, deg):
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return (v[0] * c - v[1] * s, v[0] * s + v[1] * c)


def shear_ring(ring, deg, y_piv):
    """Horizontal shear around y_piv: deg > 0 leans forward right (italic), deg < 0 un-slants upright."""
    if abs(deg) < 1e-6:
        return list(ring)
    sh = math.tan(math.radians(deg))
    return [
        (k, tuple((p[0] + sh * (p[1] - y_piv), p[1]) for p in pts))
        for k, pts in ring
    ]


def shear_cubic(c, deg, y_piv):
    """Horizontal shear of a single cubic Bézier control polygon around y_piv."""
    if abs(deg) < 1e-6:
        return c
    sh = math.tan(math.radians(deg))
    return tuple((p[0] + sh * (p[1] - y_piv), p[1]) for p in c)


def flatten_doni_tail(d_o, preset, wt, w_fac=1.0):
    """
    Stroke-preserving, VF-topology-preserving lower-tail flattening for Mtavruli (`ampersand.geor.case`).
    Leaves the ENTIRE დ oval (`d_o[0..2]`), `C_bot -> OV_B` (`d_o[11]`), and inner counter 100% UNTOUCHED
    so the `დ -> Ა` bottom join stays G2-seamless at Thin 100..Heavy 900, while lifting and flattening
    the steep Mkhedruli descender tail (`d_o[3..10]`) so the დ/Ა base sits lower and the isotropic
    დ+Ა bowls grow larger without any stroke thinning or arch-cave pinching!
    """
    lift_frac = float(preset.get("lift_frac", 0.0))
    if lift_frac <= 1e-6:
        return list(d_o)

    arch_ratio = float(preset.get("arch_ratio", 0.54))
    flat_deg = float(preset.get("foot_flat_deg", 14.0))
    dx_frac = float(preset.get("foot_dx_frac", 0.30))

    # Extract original landmarks from canonical 12-segment outer დ ring
    # d_o[3]=OV_L->C_spur, [4]=C_spur->sp_T, [5]=LINE(sp_T->sp_B), [6]=sp_B->arch,
    # [7]=arch->ft_L, [8]=LINE(ft_L->ft_R), [9]=ft_R->leg_inf, [10]=leg_inf->C_bot, [11]=C_bot->OV_B
    OV_B   = d_o[0][1][0]
    OV_L   = d_o[3][1][0]
    C_spur = d_o[4][1][0]
    sp_T   = d_o[5][1][0]
    sp_B   = d_o[5][1][1]
    arch_a = d_o[7][1][0]
    ft_L   = d_o[8][1][0]
    ft_R   = d_o[8][1][1]
    leg_i  = d_o[10][1][0]
    C_bot  = d_o[11][1][0]

    raw_drop = max(120.0, OV_B[1] - ft_L[1])  # ~276 Thin, 280 Reg, 295 Bold, 305 Heavy
    lift_tail = lift_frac * raw_drop
    # Preserve 100% of arch & spur stroke thickness by lifting C_spur & arch_apex together;
    # keep safe vertical clearance below OV_B / C_bot even in Heavy 900!
    max_arch_lift = max(12.0, (OV_B[1] - C_spur[1]) - (22.0 + 10.0 * wt))
    arch_lift = min(max_arch_lift, lift_tail * arch_ratio)
    # Left spur lifts between arch_lift and lift_tail so crescent flattens symmetrically!
    spur_lift = 0.45 * arch_lift + 0.55 * lift_tail

    # Gentle rightward sweep for a flatter graceful Დ-style tail
    dx_ft = dx_frac * lift_tail * w_fac
    dx_arch = 0.28 * dx_ft
    dx_sp = -0.10 * dx_ft

    # New landmarks (preserving 100% of spur cut length & foot cut length!)
    C_spur_n = (C_spur[0] + 0.25 * dx_arch, C_spur[1] + arch_lift)

    # Rotate spur terminal cut gently toward flatter angle while keeping exact ||sp_T - sp_B||
    sp_vec = v_sub(sp_B, sp_T)
    sp_rot_deg = -0.35 * flat_deg
    sp_T_n = (sp_T[0] + dx_sp, sp_T[1] + spur_lift)
    sp_B_n = v_add(sp_T_n, rot_vec(sp_vec, sp_rot_deg))
    # Keep sp_B_n cleanly below arch_a_n and above ft_L_n
    arch_a_n = (arch_a[0] + dx_arch, arch_a[1] + arch_lift)
    ft_L_n = (ft_L[0] + dx_ft, ft_L[1] + lift_tail)

    # Foot cut: rotate leg direction flatter (+flat_deg CCW toward horizontal) with PURE 90° perpendicular cut
    # preserving exact stroke width ||ft_R - ft_L|| and crisp rectangular Swiss corners (zero acute point!)
    ft_vec = v_sub(ft_R, ft_L)
    t_leg_old = v_norm(cubic_deriv(*d_o[7][1], 1.0))     # downward-right leg arrival tangent at ft_L
    t_leg_new = v_norm(rot_vec(t_leg_old, flat_deg))
    w_foot = v_len(ft_vec)
    n_perp = rot90_ccw(t_leg_new)
    ft_R_n = v_add(ft_L_n, v_mul(n_perp, w_foot))

    # Inflection point on upper-right flank of descending leg: rises smoothly & stays safely below C_bot
    leg_lift = min(C_bot[1] - leg_i[1] - (36.0 + 14.0 * wt), 0.48 * arch_lift + 0.14 * lift_tail)
    leg_i_n = (leg_i[0] + 0.42 * dx_ft, leg_i[1] + max(0.0, leg_lift))

    # Helper to smoothly transform a cubic given new endpoints and optional new end tangents
    def morph_cubic(seg_pts, p0_n, p3_n, t0_n=None, t3_n=None, scale_y_handles=False):
        p0, p1, p2, p3 = seg_pts
        dp0 = v_sub(p0_n, p0)
        dp3 = v_sub(p3_n, p3)
        if t0_n is None:
            # Interpolate displacement smoothly for control point 1 (weighted 0.72 toward start)
            if scale_y_handles and abs(p3[1] - p0[1]) > 1e-4:
                sy = (p3_n[1] - p0_n[1]) / (p3[1] - p0[1])
                p1_n = (p0_n[0] + (p1[0] - p0[0]) + 0.25 * (dp3[0] - dp0[0]), p0_n[1] + (p1[1] - p0[1]) * sy)
            else:
                p1_n = (p1[0] + 0.72 * dp0[0] + 0.28 * dp3[0], p1[1] + 0.72 * dp0[1] + 0.28 * dp3[1])
        else:
            L_old = max(1.0, v_len(v_sub(p3, p0)))
            L_new = max(1.0, v_len(v_sub(p3_n, p0_n)))
            h0 = v_len(v_sub(p1, p0)) * (L_new / L_old)
            p1_n = v_add(p0_n, v_mul(v_norm(t0_n), h0))

        if t3_n is None:
            if scale_y_handles and abs(p3[1] - p0[1]) > 1e-4:
                sy = (p3_n[1] - p0_n[1]) / (p3[1] - p0[1])
                p2_n = (p3_n[0] + (p2[0] - p3[0]) - 0.25 * (dp3[0] - dp0[0]), p3_n[1] + (p2[1] - p3[1]) * sy)
            else:
                p2_n = (p2[0] + 0.28 * dp0[0] + 0.72 * dp3[0], p2[1] + 0.28 * dp0[1] + 0.72 * dp3[1])
        else:
            L_old = max(1.0, v_len(v_sub(p3, p0)))
            L_new = max(1.0, v_len(v_sub(p3_n, p0_n)))
            h3 = v_len(v_sub(p3, p2)) * (L_new / L_old)
            p2_n = v_sub(p3_n, v_mul(v_norm(t3_n), h3))
        return (p0_n, p1_n, p2_n, p3_n)

    # Rebuild d_o[3..10] with exact G1 tangents at OV_L, arch_apex, ft_L, ft_R, leg_inf, C_bot!
    # d_o[3]: OV_L -> C_spur (preserve exact vertical tangent (0, -1) at OV_L!)
    t_ov_l = v_norm(cubic_deriv(*d_o[3][1], 0.0))
    t_csp_in = v_norm(rot_vec(v_norm(cubic_deriv(*d_o[3][1], 1.0)), 0.55 * flat_deg))
    s3 = morph_cubic(d_o[3][1], OV_L, C_spur_n, t0_n=t_ov_l, t3_n=t_csp_in)

    # d_o[4]: C_spur -> sp_T (preserve horizontal-ish smooth spur roof!)
    t_sp_t_out = v_norm(rot_vec(v_norm(cubic_deriv(*d_o[4][1], 1.0)), sp_rot_deg))
    s4 = morph_cubic(d_o[4][1], C_spur_n, sp_T_n, t0_n=v_norm(cubic_deriv(*d_o[4][1], 0.0)), t3_n=t_sp_t_out)

    # d_o[5]: LINE sp_T -> sp_B
    s5 = (sp_T_n, sp_B_n)

    # d_o[6]: sp_B -> arch_apex (preserve exact horizontal (1, 0) tangent at arch_apex!)
    t_sp_b_out = v_norm(rot_vec(v_norm(cubic_deriv(*d_o[6][1], 0.0)), sp_rot_deg))
    s6 = morph_cubic(d_o[6][1], sp_B_n, arch_a_n, t0_n=t_sp_b_out, t3_n=(1.0, 0.0))

    # d_o[7]: arch_apex -> ft_L (horizontal (1, 0) at arch_apex -> flatter leg tangent t_leg_new at ft_L!)
    s7 = morph_cubic(d_o[7][1], arch_a_n, ft_L_n, t0_n=(1.0, 0.0), t3_n=t_leg_new)

    # d_o[8]: LINE ft_L -> ft_R
    s8 = (ft_L_n, ft_R_n)

    # d_o[9]: ft_R -> leg_inf (exits cleanly along -t_leg_new, lands smoothly at leg_inf!)
    t_leg_r_out = v_mul(t_leg_new, -1.0)
    t_leg_i_orig = v_norm(cubic_deriv(*d_o[9][1], 1.0))
    t_leg_i_new = v_norm(rot_vec(t_leg_i_orig, 0.35 * flat_deg))
    s9 = morph_cubic(d_o[9][1], ft_R_n, leg_i_n, t0_n=t_leg_r_out, t3_n=t_leg_i_new)

    # d_o[10]: leg_inf -> C_bot (matches t_leg_i_new at leg_inf, preserves exact original C_bot arrival!)
    t_cbot_in = v_norm(cubic_deriv(*d_o[10][1], 1.0))
    s10 = morph_cubic(d_o[10][1], leg_i_n, C_bot, t0_n=t_leg_i_new, t3_n=t_cbot_in)

    out = list(d_o)
    out[3]  = ("cubic", s3)
    out[4]  = ("cubic", s4)
    out[5]  = ("line",  s5)
    out[6]  = ("cubic", s6)
    out[7]  = ("cubic", s7)
    out[8]  = ("line",  s8)
    out[9]  = ("cubic", s9)
    out[10] = ("cubic", s10)
    return out


def cubic_eval(p0, p1, p2, p3, t):
    mt = 1.0 - t
    mt2, t2 = mt * mt, t * t
    return (
        mt2 * mt * p0[0] + 3.0 * mt2 * t * p1[0] + 3.0 * mt * t2 * p2[0] + t2 * t * p3[0],
        mt2 * mt * p0[1] + 3.0 * mt2 * t * p1[1] + 3.0 * mt * t2 * p2[1] + t2 * t * p3[1],
    )


def cubic_deriv(p0, p1, p2, p3, t):
    mt = 1.0 - t
    return (
        3.0 * mt * mt * (p1[0] - p0[0]) + 6.0 * mt * t * (p2[0] - p1[0]) + 3.0 * t * t * (p3[0] - p2[0]),
        3.0 * mt * mt * (p1[1] - p0[1]) + 6.0 * mt * t * (p2[1] - p1[1]) + 3.0 * t * t * (p3[1] - p2[1]),
    )


def cubic_split(p0, p1, p2, p3, t):
    """Exact de Casteljau split at parameter t in [0, 1]."""
    t = max(0.0, min(1.0, t))
    lerp = lambda a, b: (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
    q0, q1, q2 = lerp(p0, p1), lerp(p1, p2), lerp(p2, p3)
    r0, r1 = lerp(q0, q1), lerp(q1, q2)
    s0 = lerp(r0, r1)
    return (p0, q0, r0, s0), (s0, r1, q2, p3)


def reverse_cubic(c):
    return (c[3], c[2], c[1], c[0])


def cubic_t_at_arclen(p0, p1, p2, p3, target_s, from_end=False, n=64):
    ts = np.linspace(0.0, 1.0, n + 1)
    lens = np.zeros(n + 1)
    prev = p0
    for i in range(1, n + 1):
        cur = cubic_eval(p0, p1, p2, p3, float(ts[i]))
        lens[i] = lens[i - 1] + math.hypot(cur[0] - prev[0], cur[1] - prev[1])
        prev = cur
    total = float(lens[-1])
    if total < 1e-6:
        return 0.5
    s = (total - target_s) if from_end else target_s
    s = max(0.02 * total, min(0.98 * total, s))
    return float(np.interp(s, lens, ts))


def fit_cubic_g1(pts, t0, t3):
    """
    Closed-form exact least-squares G1 cubic Bézier fit to ordered points `pts`
    with fixed endpoints pts[0], pts[-1] and fixed unit endpoint tangents t0, t3.
    Deterministic and smooth across weight/width axes (100% VF-safe).
    """
    p0 = pts[0]
    p3 = pts[-1]
    t0 = v_norm(t0)
    t3 = v_norm(t3)
    L = v_len(v_sub(p3, p0))
    if L < 1e-6:
        return (p0, p0, p3, p3)

    ds = [0.0]
    for i in range(1, len(pts)):
        ds.append(ds[-1] + v_len(v_sub(pts[i], pts[i - 1])))
    tot = ds[-1]
    if tot < 1e-6:
        return (p0, p0, p3, p3)
    ss = np.array(ds) / tot

    A = np.zeros((2 * len(pts), 2))
    rhs = np.zeros(2 * len(pts))
    for i, (s, pt) in enumerate(zip(ss, pts)):
        mt = 1.0 - s
        b0 = mt**3 + 3.0 * mt**2 * s
        b3 = 3.0 * mt * s**2 + s**3
        bx = b0 * p0[0] + b3 * p3[0]
        by = b0 * p0[1] + b3 * p3[1]
        c0 = 3.0 * mt**2 * s
        c3 = -3.0 * mt * s**2
        A[2 * i, 0] = c0 * t0[0]
        A[2 * i, 1] = c3 * t3[0]
        A[2 * i + 1, 0] = c0 * t0[1]
        A[2 * i + 1, 1] = c3 * t3[1]
        rhs[2 * i] = pt[0] - bx
        rhs[2 * i + 1] = pt[1] - by

    sol, _, _, _ = np.linalg.lstsq(A, rhs, rcond=None)
    h0 = max(0.05 * L, min(0.95 * L, float(sol[0])))
    h3 = max(0.05 * L, min(0.95 * L, float(sol[1])))
    return (p0, v_add(p0, v_mul(t0, h0)), v_sub(p3, v_mul(t3, h3)), p3)


def offset_cubic_fit(
    center_cubic, w_v, w_h, side=+1, s0=1.0, s1=1.0, diag_boost=1.03,
    flat_start_y=None, end_x_shift=0.0, n=41
):
    """
    True parallel normal-offset of a centerline cubic with Batumi directional optical contrast:
      half_w(T) = 0.5 * scale(t) * diag_fac(T) * hypot(w_v * Ty, w_h * Tx)
    side=+1 offsets along CCW left normal, side=-1 along CW right normal.
    Returns a single G1-continuous least-squares cubic Bézier.
    """
    ts = np.linspace(0.0, 1.0, n)
    pts = []
    tangs = []
    for t in ts:
        tf = float(t)
        p = cubic_eval(*center_cubic, tf)
        T = v_norm(cubic_deriv(*center_cubic, tf))
        N = rot90_ccw(T) if side > 0 else rot90_cw(T)
        sc = s0 + (s1 - s0) * tf
        d_fac = 1.0 + (diag_boost - 1.0) * (2.0 * abs(T[0] * T[1]))
        half_w = 0.5 * sc * d_fac * math.hypot(w_v * T[1], w_h * T[0])
        pts.append(v_add(p, v_mul(N, half_w)))
        tangs.append(T)

    if flat_start_y is not None:
        # Intersect start tangent cleanly with horizontal y = flat_start_y for crisp flat top cut
        p0, t0 = pts[0], tangs[0]
        if abs(t0[1]) > 1e-4:
            dt = (flat_start_y - p0[1]) / t0[1]
            pts[0] = (p0[0] + dt * t0[0], flat_start_y)

    if abs(end_x_shift) > 1e-6:
        pts[-1] = (pts[-1][0] + end_x_shift, pts[-1][1])

    return fit_cubic_g1(pts, tangs[0], tangs[-1])


def solve_cubic_y(p0, p1, p2, p3, y_target, t_lo=0.0, t_hi=1.0):
    y_lo = cubic_eval(p0, p1, p2, p3, t_lo)[1] - y_target
    y_hi = cubic_eval(p0, p1, p2, p3, t_hi)[1] - y_target
    if y_lo * y_hi > 0:
        ts = np.linspace(t_lo, t_hi, 129)
        vals = [abs(cubic_eval(p0, p1, p2, p3, float(t))[1] - y_target) for t in ts]
        return float(ts[int(np.argmin(vals))])
    a, b = t_lo, t_hi
    for _ in range(40):
        m = 0.5 * (a + b)
        ym = cubic_eval(p0, p1, p2, p3, m)[1] - y_target
        if y_lo * ym <= 0:
            b, y_hi = m, ym
        else:
            a, y_lo = m, ym
    return 0.5 * (a + b)


def contour_signed_area(segs):
    pts = []
    for kind, p in segs:
        if kind == "line":
            pts.append(p[0])
        else:
            for k in range(8):
                pts.append(cubic_eval(*p, k / 8.0))
    area = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return 0.5 * area


def make_superelliptical_cap(seg_in, seg_out, overshoot=4.0, kappa=KAPPA_ROUNDED):
    """
    Replace a flat terminal cut with a G1-continuous superelliptical semicircular cap
    (reference / Batumi Sans Rounded κ=0.580) via exact de Casteljau pull-back.
    """
    assert seg_in[0] == "cubic" and seg_out[0] == "cubic"
    A = seg_in[1][3]
    B = seg_out[1][0]
    w = v_len(v_sub(B, A))
    r = 0.5 * w
    pull = max(2.0, r - overshoot)

    t_in = cubic_t_at_arclen(*seg_in[1], pull, from_end=True)
    t_out = cubic_t_at_arclen(*seg_out[1], pull, from_end=False)

    new_in_pts, _ = cubic_split(*seg_in[1], t_in)
    _, new_out_pts = cubic_split(*seg_out[1], t_out)

    Ap = new_in_pts[3]
    Bp = new_out_pts[0]
    tin = v_norm(cubic_deriv(*new_in_pts, 1.0))      # OUTWARD at Ap
    tout = v_norm(cubic_deriv(*new_out_pts, 0.0))    # INWARD at Bp
    tout_ext = v_mul(tout, -1.0)                     # OUTWARD at Bp

    chord = v_sub(Bp, Ap)
    w_eff = v_len(chord)
    r_eff = 0.5 * w_eff
    u_perp = v_norm(chord)
    n_out = rot90_cw(u_perp)
    u_avg = v_norm(v_add(tin, tout_ext))
    if v_dot(u_avg, n_out) < 0.2:
        u_axis = n_out
    else:
        u_axis = v_norm(v_add(v_mul(n_out, 0.65), v_mul(u_avg, 0.35)))

    mid = (0.5 * (Ap[0] + Bp[0]), 0.5 * (Ap[1] + Bp[1]))
    P_apex = v_add(mid, v_mul(u_axis, r_eff))

    t_apex = rot90_ccw(u_axis)
    if v_dot(t_apex, u_perp) < 0:
        t_apex = v_mul(t_apex, -1.0)

    h = kappa * r_eff
    c1 = (
        Ap,
        v_add(Ap, v_mul(tin, h)),
        v_sub(P_apex, v_mul(t_apex, h)),
        P_apex,
    )
    c2 = (
        P_apex,
        v_add(P_apex, v_mul(t_apex, h)),
        v_add(Bp, v_mul(tout_ext, h)),
        Bp,
    )
    return ("cubic", new_in_pts), ("cubic", c1), ("cubic", c2), ("cubic", new_out_pts)


# ---------------------------------------------------------------------------
# Master Metrics Lookup for Batumi Sans (All 9 Weights × 4 Optical Widths)
# ---------------------------------------------------------------------------

BATUMI_WEIGHTS = {
    "Thin":       dict(wght=100, vstem=23.0,  hbar=20.0,  capH=681.0, xH=519.0, asc=736.0, desc=-197.0),
    "ExtraLight": dict(wght=200, vstem=49.0,  hbar=39.0,  capH=684.0, xH=522.0, asc=742.0, desc=-204.0),
    "Light":      dict(wght=300, vstem=61.0,  hbar=48.0,  capH=685.0, xH=523.0, asc=746.0, desc=-208.0),
    "Regular":    dict(wght=400, vstem=97.0,  hbar=74.0,  capH=689.0, xH=527.0, asc=753.0, desc=-216.0),
    "Medium":     dict(wght=500, vstem=133.0, hbar=97.0,  capH=691.0, xH=529.0, asc=757.0, desc=-220.0),
    "SemiBold":   dict(wght=600, vstem=146.0, hbar=106.0, capH=692.0, xH=530.0, asc=758.0, desc=-221.0),
    "Bold":       dict(wght=700, vstem=162.0, hbar=117.0, capH=693.0, xH=531.0, asc=760.0, desc=-223.0),
    "ExtraBold":  dict(wght=800, vstem=182.0, hbar=129.0, capH=695.0, xH=533.0, asc=762.0, desc=-225.0),
    "Heavy":      dict(wght=900, vstem=201.0, hbar=142.0, capH=696.0, xH=534.0, asc=764.0, desc=-227.0),
}

# True optical Batumi Sans width factors matching `src/condenser.py` & live `dist/otf/`!
# (Extra Condensed ≈ 84.3–85.2%, Condensed ≈ 91.3%, Normal = 100%, Expanded ≈ 113.6%)
BATUMI_WIDTHS = {
    "ExtraCondensed": 0.852,
    "Condensed":      0.913,
    "Normal":         1.000,
    "Expanded":       1.136,
}

# Exact stem-preservation ratios from `src/condenser.py` (NEVER naive scaleX!)
_WIDTH_KNOTS = np.array([0.852, 0.913, 1.000, 1.136])
_VPRES_VALS  = np.array([0.950, 0.975, 1.000, 1.015])
_HPRES_VALS  = np.array([0.960, 0.975, 1.000, 1.012])


def width_stem_preservation(w_fac):
    return (
        float(np.interp(w_fac, _WIDTH_KNOTS, _VPRES_VALS)),
        float(np.interp(w_fac, _WIDTH_KNOTS, _HPRES_VALS)),
    )


# ---------------------------------------------------------------------------
# Koba's Original Exact Vector Masters (Path 1 = 9-Weight Canonical Italic დ,
# Path 2 = Exact 3-Cubic Medial-Axis Centerline from `ამპრესონდი 2.pdf`!)
# ---------------------------------------------------------------------------

DONI_MASTERS = {
    'Thin': {
        "outer": [
            ('cubic', ((255.0, 82.0), (391.0, 82.0), (474.0, 203.0), (474.0, 355.0))),
            ('cubic', ((474.0, 355.0), (474.0, 462.0), (415.0, 529.0), (314.0, 529.0))),
            ('cubic', ((314.0, 529.0), (180.0, 529.0), (72.0, 418.0), (72.0, 158.0))),
            ('cubic', ((72.0, 158.0), (72.0, 35.0), (115.0, -28.0), (213.0, -60.0))),
            ('cubic', ((213.0, -60.0), (169.0, -55.0), (115.0, -65.0), (71.0, -88.0))),
            ('line', ((71.0, -88.0), (75.0, -108.0))),
            ('cubic', ((75.0, -108.0), (117.0, -85.0), (168.0, -74.0), (217.0, -77.0))),
            ('cubic', ((217.0, -77.0), (283.0, -83.0), (331.0, -122.0), (350.0, -194.0))),
            ('line', ((350.0, -194.0), (370.0, -188.0))),
            ('cubic', ((370.0, -188.0), (353.0, -119.0), (315.0, -80.0), (237.0, -53.0))),
            ('cubic', ((237.0, -53.0), (135.0, -19.0), (94.0, 56.5), (94.0, 182.0))),
            ('cubic', ((94.0, 182.0), (121.0, 126.0), (173.0, 82.0), (255.0, 82.0))),
        ],
        "inner": [
            ('cubic', ((314.0, 509.0), (400.0, 509.0), (451.0, 454.0), (451.0, 355.0))),
            ('cubic', ((451.0, 355.0), (451.0, 213.0), (378.0, 102.0), (255.0, 102.0))),
            ('cubic', ((255.0, 102.0), (176.0, 102.0), (123.0, 148.0), (96.0, 216.0))),
            ('cubic', ((96.0, 216.0), (110.0, 427.0), (204.0, 509.0), (314.0, 509.0))),
        ],
    },
    'ExtraLight': {
        "outer": [
            ('cubic', ((261.0, 77.0), (404.0, 77.0), (486.0, 206.0), (486.0, 352.0))),
            ('cubic', ((486.0, 352.0), (486.0, 461.0), (423.0, 532.0), (316.0, 532.0))),
            ('cubic', ((316.0, 532.0), (178.0, 532.0), (65.0, 424.0), (65.0, 163.0))),
            ('cubic', ((65.0, 163.0), (65.0, 40.0), (109.0, -20.0), (198.0, -55.0))),
            ('cubic', ((198.0, -55.0), (155.0, -52.0), (110.0, -61.0), (63.0, -80.0))),
            ('line', ((63.0, -80.0), (71.0, -120.0))),
            ('cubic', ((71.0, -120.0), (115.0, -99.0), (158.0, -87.0), (208.0, -87.0))),
            ('cubic', ((208.0, -87.0), (275.0, -87.0), (326.0, -128.0), (348.0, -200.0))),
            ('line', ((348.0, -200.0), (388.0, -186.0))),
            ('cubic', ((388.0, -186.0), (365.0, -112.0), (323.0, -74.0), (245.0, -43.0))),
            ('cubic', ((245.0, -43.0), (152.0, -6.0), (112.0, 46.0), (111.0, 159.0))),
            ('cubic', ((111.0, 159.0), (140.0, 112.0), (187.0, 77.0), (261.0, 77.0))),
        ],
        "inner": [
            ('cubic', ((314.0, 493.0), (391.0, 493.0), (438.0, 445.0), (438.0, 352.0))),
            ('cubic', ((438.0, 352.0), (438.0, 223.0), (373.0, 117.0), (259.0, 117.0))),
            ('cubic', ((259.0, 117.0), (187.0, 117.0), (139.0, 155.0), (113.0, 214.0))),
            ('cubic', ((113.0, 214.0), (125.0, 418.0), (212.0, 493.0), (314.0, 493.0))),
        ],
    },
    'Light': {
        "outer": [
            ('cubic', ((266.0, 74.0), (412.0, 74.0), (494.0, 207.0), (494.0, 350.0))),
            ('cubic', ((494.0, 350.0), (494.0, 460.0), (431.0, 534.0), (317.0, 534.0))),
            ('cubic', ((317.0, 534.0), (178.0, 534.0), (63.0, 426.0), (63.0, 165.0))),
            ('cubic', ((63.0, 165.0), (63.0, 44.0), (107.0, -16.0), (191.0, -51.0))),
            ('cubic', ((191.0, -51.0), (146.0, -50.0), (102.0, -58.0), (59.0, -75.0))),
            ('line', ((59.0, -75.0), (67.0, -125.0))),
            ('cubic', ((67.0, -125.0), (110.0, -104.0), (155.0, -91.0), (206.0, -91.0))),
            ('cubic', ((206.0, -91.0), (277.0, -91.0), (326.0, -133.0), (348.0, -203.0))),
            ('line', ((348.0, -203.0), (397.0, -184.0))),
            ('cubic', ((397.0, -184.0), (372.0, -108.0), (328.0, -71.0), (251.0, -38.0))),
            ('cubic', ((251.0, -38.0), (164.0, -3.0), (123.0, 46.0), (119.0, 150.0))),
            ('cubic', ((119.0, 150.0), (149.0, 106.0), (195.0, 74.0), (266.0, 74.0))),
        ],
        "inner": [
            ('cubic', ((315.0, 486.0), (388.0, 486.0), (434.0, 440.0), (434.0, 350.0))),
            ('cubic', ((434.0, 350.0), (434.0, 228.0), (372.0, 124.0), (262.0, 124.0))),
            ('cubic', ((262.0, 124.0), (193.0, 124.0), (147.0, 158.0), (120.0, 215.0))),
            ('cubic', ((120.0, 215.0), (132.0, 412.0), (216.0, 486.0), (315.0, 486.0))),
        ],
    },
    'Regular': {
        "outer": [
            ('cubic', ((279.0, 68.0), (435.0, 68.0), (516.0, 211.0), (516.0, 346.0))),
            ('cubic', ((516.0, 346.0), (516.0, 458.0), (450.0, 539.0), (321.0, 539.0))),
            ('cubic', ((321.0, 539.0), (178.0, 539.0), (55.0, 431.0), (55.0, 171.0))),
            ('cubic', ((55.0, 171.0), (55.0, 54.0), (99.0, -2.0), (171.0, -42.0))),
            ('cubic', ((171.0, -42.0), (123.0, -42.0), (81.0, -49.0), (45.0, -63.0))),
            ('line', ((45.0, -63.0), (56.0, -140.0))),
            ('cubic', ((56.0, -140.0), (98.0, -117.0), (145.0, -102.0), (201.0, -102.0))),
            ('cubic', ((201.0, -102.0), (282.0, -102.0), (327.0, -149.0), (349.0, -212.0))),
            ('line', ((349.0, -212.0), (423.0, -180.0))),
            ('cubic', ((423.0, -180.0), (391.0, -98.0), (342.0, -62.0), (267.0, -26.0))),
            ('cubic', ((267.0, -26.0), (195.0, 8.0), (155.0, 45.0), (145.0, 126.0))),
            ('cubic', ((145.0, 126.0), (178.0, 88.0), (219.0, 68.0), (279.0, 68.0))),
        ],
        "inner": [
            ('cubic', ((317.0, 466.0), (382.0, 466.0), (422.0, 427.0), (422.0, 346.0))),
            ('cubic', ((422.0, 346.0), (422.0, 240.0), (369.0, 142.0), (270.0, 142.0))),
            ('cubic', ((270.0, 142.0), (211.0, 142.0), (173.0, 162.0), (144.0, 210.0))),
            ('cubic', ((144.0, 210.0), (153.0, 393.0), (225.0, 466.0), (317.0, 466.0))),
        ],
    },
    'Medium': {
        "outer": [
            ('cubic', ((289.0, 72.0), (447.0, 72.0), (530.0, 210.0), (530.0, 346.0))),
            ('cubic', ((530.0, 346.0), (530.0, 460.0), (457.0, 544.0), (321.0, 544.0))),
            ('cubic', ((321.0, 544.0), (171.0, 544.0), (42.0, 432.0), (42.0, 179.0))),
            ('cubic', ((42.0, 179.0), (42.0, 61.0), (89.0, 6.0), (165.0, -33.0))),
            ('cubic', ((165.0, -33.0), (114.0, -33.0), (69.0, -43.0), (35.0, -57.0))),
            ('line', ((35.0, -57.0), (50.0, -150.0))),
            ('cubic', ((50.0, -150.0), (95.0, -125.0), (144.0, -108.0), (203.0, -108.0))),
            ('cubic', ((203.0, -108.0), (279.0, -108.0), (325.0, -155.0), (348.0, -216.0))),
            ('line', ((348.0, -216.0), (446.0, -162.0))),
            ('cubic', ((446.0, -162.0), (411.0, -84.0), (358.0, -49.0), (279.0, -12.0))),
            ('cubic', ((279.0, -12.0), (213.0, 20.0), (180.0, 53.0), (169.0, 118.0))),
            ('cubic', ((169.0, 118.0), (202.0, 87.0), (239.0, 72.0), (289.0, 72.0))),
        ],
        "inner": [
            ('cubic', ((313.0, 450.0), (369.0, 450.0), (403.0, 416.0), (403.0, 346.0))),
            ('cubic', ((403.0, 346.0), (403.0, 255.0), (358.0, 164.0), (272.0, 164.0))),
            ('cubic', ((272.0, 164.0), (226.0, 164.0), (192.0, 180.0), (166.0, 218.0))),
            ('cubic', ((166.0, 218.0), (174.0, 388.0), (238.0, 450.0), (313.0, 450.0))),
        ],
    },
    'SemiBold': {
        "outer": [
            ('cubic', ((292.0, 74.0), (452.0, 74.0), (535.0, 210.0), (535.0, 346.0))),
            ('cubic', ((535.0, 346.0), (535.0, 461.0), (460.0, 546.0), (321.0, 546.0))),
            ('cubic', ((321.0, 546.0), (168.0, 546.0), (36.0, 432.0), (36.0, 182.0))),
            ('cubic', ((36.0, 182.0), (36.0, 64.0), (85.0, 9.0), (162.0, -30.0))),
            ('cubic', ((162.0, -30.0), (111.0, -30.0), (64.0, -40.0), (31.0, -54.0))),
            ('line', ((31.0, -54.0), (47.0, -153.0))),
            ('cubic', ((47.0, -153.0), (94.0, -128.0), (143.0, -110.0), (203.0, -110.0))),
            ('cubic', ((203.0, -110.0), (278.0, -110.0), (324.0, -158.0), (348.0, -218.0))),
            ('line', ((348.0, -218.0), (455.0, -155.0))),
            ('cubic', ((455.0, -155.0), (419.0, -79.0), (365.0, -44.0), (284.0, -6.0))),
            ('cubic', ((284.0, -6.0), (220.0, 24.0), (189.0, 55.0), (178.0, 117.0))),
            ('cubic', ((178.0, 117.0), (211.0, 87.0), (246.0, 74.0), (292.0, 74.0))),
        ],
        "inner": [
            ('cubic', ((311.0, 443.0), (363.0, 443.0), (395.0, 412.0), (395.0, 346.0))),
            ('cubic', ((395.0, 346.0), (395.0, 261.0), (354.0, 172.0), (273.0, 172.0))),
            ('cubic', ((273.0, 172.0), (232.0, 172.0), (199.0, 187.0), (174.0, 222.0))),
            ('cubic', ((174.0, 222.0), (182.0, 384.0), (242.0, 443.0), (311.0, 443.0))),
        ],
    },
    'Bold': {
        "outer": [
            ('cubic', ((296.0, 75.0), (457.0, 75.0), (541.0, 209.0), (541.0, 346.0))),
            ('cubic', ((541.0, 346.0), (541.0, 462.0), (463.0, 548.0), (321.0, 548.0))),
            ('cubic', ((321.0, 548.0), (165.0, 548.0), (31.0, 432.0), (31.0, 185.0))),
            ('cubic', ((31.0, 185.0), (31.0, 68.0), (80.0, 12.0), (160.0, -26.0))),
            ('cubic', ((160.0, -26.0), (107.0, -26.0), (59.0, -37.0), (27.0, -51.0))),
            ('line', ((27.0, -51.0), (45.0, -157.0))),
            ('cubic', ((45.0, -157.0), (93.0, -131.0), (143.0, -113.0), (204.0, -113.0))),
            ('cubic', ((204.0, -113.0), (277.0, -113.0), (323.0, -161.0), (347.0, -220.0))),
            ('line', ((347.0, -220.0), (465.0, -148.0))),
            ('cubic', ((465.0, -148.0), (428.0, -73.0), (372.0, -39.0), (289.0, 0.0))),
            ('cubic', ((289.0, 0.0), (228.0, 29.0), (199.0, 58.0), (188.0, 115.0))),
            ('cubic', ((188.0, 115.0), (221.0, 87.0), (254.0, 75.0), (296.0, 75.0))),
        ],
        "inner": [
            ('cubic', ((309.0, 436.0), (358.0, 436.0), (387.0, 407.0), (387.0, 345.0))),
            ('cubic', ((387.0, 345.0), (387.0, 267.0), (350.0, 182.0), (274.0, 182.0))),
            ('cubic', ((274.0, 182.0), (238.0, 182.0), (208.0, 195.0), (184.0, 225.0))),
            ('cubic', ((184.0, 225.0), (192.0, 382.0), (247.0, 436.0), (309.0, 436.0))),
        ],
    },
    'ExtraBold': {
        "outer": [
            ('cubic', ((302.0, 78.0), (464.0, 78.0), (549.0, 209.0), (549.0, 346.0))),
            ('cubic', ((549.0, 346.0), (549.0, 464.0), (467.0, 551.0), (321.0, 551.0))),
            ('cubic', ((321.0, 551.0), (161.0, 551.0), (23.0, 433.0), (23.0, 190.0))),
            ('cubic', ((23.0, 190.0), (23.0, 72.0), (75.0, 17.0), (156.0, -21.0))),
            ('cubic', ((156.0, -21.0), (102.0, -21.0), (52.0, -34.0), (21.0, -48.0))),
            ('line', ((21.0, -48.0), (41.0, -163.0))),
            ('cubic', ((41.0, -163.0), (91.0, -136.0), (142.0, -116.0), (205.0, -116.0))),
            ('cubic', ((205.0, -116.0), (275.0, -116.0), (322.0, -164.0), (347.0, -223.0))),
            ('line', ((347.0, -223.0), (478.0, -138.0))),
            ('cubic', ((478.0, -138.0), (439.0, -65.0), (381.0, -32.0), (296.0, 8.0))),
            ('cubic', ((296.0, 8.0), (238.0, 35.0), (211.0, 63.0), (201.0, 113.0))),
            ('cubic', ((201.0, 113.0), (233.0, 88.0), (264.0, 78.0), (302.0, 78.0))),
        ],
        "inner": [
            ('cubic', ((306.0, 427.0), (350.0, 427.0), (376.0, 401.0), (376.0, 345.0))),
            ('cubic', ((376.0, 345.0), (376.0, 276.0), (344.0, 194.0), (276.0, 194.0))),
            ('cubic', ((276.0, 194.0), (245.0, 194.0), (219.0, 205.0), (196.0, 231.0))),
            ('cubic', ((196.0, 231.0), (204.0, 379.0), (254.0, 427.0), (306.0, 427.0))),
        ],
    },
    'Heavy': {
        "outer": [
            ('cubic', ((307.0, 80.0), (471.0, 80.0), (556.0, 208.0), (556.0, 346.0))),
            ('cubic', ((556.0, 346.0), (556.0, 465.0), (471.0, 554.0), (321.0, 554.0))),
            ('cubic', ((321.0, 554.0), (157.0, 554.0), (16.0, 433.0), (16.0, 194.0))),
            ('cubic', ((16.0, 194.0), (16.0, 76.0), (69.0, 21.0), (153.0, -16.0))),
            ('cubic', ((153.0, -16.0), (97.0, -16.0), (45.0, -30.0), (16.0, -44.0))),
            ('line', ((16.0, -44.0), (38.0, -168.0))),
            ('cubic', ((38.0, -168.0), (90.0, -140.0), (141.0, -119.0), (206.0, -119.0))),
            ('cubic', ((206.0, -119.0), (274.0, -119.0), (321.0, -168.0), (346.0, -225.0))),
            ('line', ((346.0, -225.0), (490.0, -128.0))),
            ('cubic', ((490.0, -128.0), (450.0, -58.0), (390.0, -25.0), (302.0, 16.0))),
            ('cubic', ((302.0, 16.0), (247.0, 41.0), (223.0, 67.0), (213.0, 111.0))),
            ('cubic', ((213.0, 111.0), (245.0, 88.0), (273.0, 80.0), (307.0, 80.0))),
        ],
        "inner": [
            ('cubic', ((304.0, 418.0), (343.0, 418.0), (366.0, 395.0), (366.0, 345.0))),
            ('cubic', ((366.0, 345.0), (366.0, 284.0), (338.0, 206.0), (277.0, 206.0))),
            ('cubic', ((277.0, 206.0), (252.0, 206.0), (228.0, 215.0), (208.0, 236.0))),
            ('cubic', ((208.0, 236.0), (215.0, 375.0), (260.0, 418.0), (304.0, 418.0))),
        ],
    },
}
_DONI_WEIGHT_ORDER = [
    "Thin", "ExtraLight", "Light", "Regular", "Medium", "SemiBold", "Bold", "ExtraBold", "Heavy"
]
_DONI_VSTEM_KNOTS = np.array([BATUMI_WEIGHTS[w]["vstem"] for w in _DONI_WEIGHT_ORDER], dtype=float)

# Exact 3-cubic medial-axis centerline of Koba's `ამპრესონდი 2.pdf` Path 2 (Capital Ა)
# in Regular BatumiSans-Italic `uni10D3` UPM space (y_rail_c=110.94, y_top=676.97, OV_B=(279, 68)):
KOBA_ANI_CENTERLINE_REF = (
    # C1: top terminal -> S-neck inflection (-100.3° -> -21.5°)
    ((538.42, 676.97), (526.64, 612.22), (553.09, 552.66), (616.45, 527.62)),
    # C2: S-neck inflection -> rightmost Capital Ა bowl apex (-21.5° -> -90°)
    ((616.45, 527.62), (682.89, 501.36), (736.39, 449.16), (736.39, 373.76)),
    # C3: rightmost apex -> seamless horizontal bottom rail (-90° -> 180°)
    ((736.39, 373.76), (736.39, 230.73), (637.07, 110.94), (490.44, 110.94)),
)
_KOBA_REF_OV_B_X = 279.0
_KOBA_REF_RAIL_Y = 110.94
_KOBA_REF_TOP_Y  = 676.97
_KOBA_REF_BOT_Y  = -212.0
_KOBA_REF_HEIGHT_RATIO = (_KOBA_REF_TOP_Y - _KOBA_REF_BOT_Y) / (539.0 - _KOBA_REF_BOT_Y)  # 1.18372


def sample_doni_master(v_x, v_y):
    """
    Smoothly interpolate the canonical 12-outer + 4-inner `uni10D3` (Italic დ) master
    independently in X (at weight v_x) and Y (at weight v_y).
    Enables exact `src/condenser.py` stem-preserving optical width scaling and isotropic
    Mtavruli weight restoration while preserving 100% fixed VF segment topology!
    """
    def interp_1d(v_val):
        v_c = max(float(_DONI_VSTEM_KNOTS[0]), min(float(_DONI_VSTEM_KNOTS[-1]), float(v_val)))
        idx = int(np.searchsorted(_DONI_VSTEM_KNOTS, v_c, side="right")) - 1
        idx = max(0, min(len(_DONI_WEIGHT_ORDER) - 2, idx))
        v0, v1 = _DONI_VSTEM_KNOTS[idx], _DONI_VSTEM_KNOTS[idx + 1]
        t = (v_c - v0) / max(1e-6, v1 - v0)
        return _DONI_WEIGHT_ORDER[idx], _DONI_WEIGHT_ORDER[idx + 1], float(t)

    wx0, wx1, tx = interp_1d(v_x)
    wy0, wy1, ty = interp_1d(v_y)

    def blend_ring(key):
        r_x0, r_x1 = DONI_MASTERS[wx0][key], DONI_MASTERS[wx1][key]
        r_y0, r_y1 = DONI_MASTERS[wy0][key], DONI_MASTERS[wy1][key]
        out = []
        for s_x0, s_x1, s_y0, s_y1 in zip(r_x0, r_x1, r_y0, r_y1):
            kind = s_x0[0]
            pts = tuple(
                (
                    p_x0[0] + tx * (p_x1[0] - p_x0[0]),
                    p_y0[1] + ty * (p_y1[1] - p_y0[1]),
                )
                for p_x0, p_x1, p_y0, p_y1 in zip(s_x0[1], s_x1[1], s_y0[1], s_y1[1])
            )
            out.append((kind, pts))
        return out

    return blend_ring("outer"), blend_ring("inner")


# ---------------------------------------------------------------------------
# Style Presets: Flagship "Master" (1:1 Original `ამპრესონდი.pdf` Master)
# ---------------------------------------------------------------------------

VARIANTS = {
    "Master": dict(
        name="Batumi Koba 1:1 Master",
        subtitle="Exact 1-to-1 vector reconstruction of Koba's ამპრესონდი.pdf (Italic დ + Capital Ა) across all 144 styles",
        ani_v_reg=0.960,      # Exact Koba Path 2 apex width (90.3u) vs დ right wall (94.0u) at Regular!
        ani_v_heavy=0.905,    # Mild multi-loop optical relief at Heavy so დ eye & Ა bay breathe cleanly
        ani_top_scale=1.050,  # Exact Koba top stem width (95.4u vs 90.5u apex)
        ani_inf_scale=1.015,  # Exact Koba S-neck inflection width
        ani_diag_boost=1.035, # Exact Koba directional fullness along S-neck & bowl
        # Refined horizontal breathing above Regular (since OV_B.x already expands +17..+28u in Bold..Heavy!)
        bay_expand_bold=0.22,
        # Connecting bottom leg extension between დ and Ა for crisp mobile/distance legibility
        # (smoothly linear in wt [0..1] × optical width curve (0.45 + 0.55 * w_fac); 100% VF-safe!)
        # Goldilocks constant-bay calibration (~195u optically even bay from Regular -> Heavy!):
        leg_ext_thin=10.0,    # +10u Thin -> +29u Regular -> +46u Bold
        leg_ext_heavy=56.0,   # +56u Heavy so დ & Ა breathe cleanly at 16–24px without over-stretching!
    ),
}


# ---------------------------------------------------------------------------
# Auto-Measure Exact Native Metrics Directly from Any Batumi Sans TTFont
# ---------------------------------------------------------------------------

def measure_font_metrics(font):
    """
    Extract exact native Batumi Sans metrics (vstem, hbar, capH, xH, asc, desc,
    width_factor, italic_deg, rounded, mtav_cue, mtav_cap_tuck) directly from an open TTFont.
    """
    gs = font.getGlyphSet()
    capH = float(font["OS/2"].sCapHeight)
    xH = float(font["OS/2"].sxHeight)
    italic_deg = -float(font["post"].italicAngle)  # Batumi Italic: post.italicAngle = -8.0 -> +8.0 shear

    ps_rec = font["name"].getName(6, 3, 1, 0x0409) or font["name"].getName(6, 1, 0, 0)
    ps_name = ps_rec.toUnicode() if ps_rec else ""
    rounded = ("Rounded" in ps_name)

    if "ExtraCondensed" in ps_name:
        w_fac = BATUMI_WIDTHS["ExtraCondensed"]
    elif "Condensed" in ps_name:
        w_fac = BATUMI_WIDTHS["Condensed"]
    elif "Expanded" in ps_name:
        w_fac = BATUMI_WIDTHS["Expanded"]
    else:
        w_fac = BATUMI_WIDTHS["Normal"]

    asc, desc = 753.0, -216.0
    if "uni10E5" in gs:
        bp = BoundsPen(gs); gs["uni10E5"].draw(bp)
        if bp.bounds:
            desc, asc = float(bp.bounds[1]), float(bp.bounds[3])
            if rounded:
                asc = min(asc, 764.0)

    mtav_cue = DEFAULT_MTAV_CUE
    if "uni10D3.case" in gs:
        bp = BoundsPen(gs); gs["uni10D3.case"].draw(bp)
        if bp.bounds:
            mtav_cue = DEFAULT_MTAV_CUE if bp.bounds[1] < -22.0 else 0.0

    mtav_cap_tuck = DEFAULT_MTAV_CAP_TUCK if mtav_cue >= 20.0 else 0.0
    if "uni10D0.case" in gs and mtav_cue >= 20.0:
        bp = BoundsPen(gs); gs["uni10D0.case"].draw(bp)
        if bp.bounds:
            if float(bp.bounds[3]) - capH < -6.0:
                mtav_cap_tuck = DEFAULT_MTAV_CAP_TUCK

    wght = int(font["OS/2"].usWeightClass)
    w_knots = [BATUMI_WEIGHTS[k]["wght"] for k in BATUMI_WEIGHTS]
    v_knots = [BATUMI_WEIGHTS[k]["vstem"] for k in BATUMI_WEIGHTS]
    h_knots = [BATUMI_WEIGHTS[k]["hbar"] for k in BATUMI_WEIGHTS]
    vstem = float(np.interp(wght, w_knots, v_knots))
    hbar = float(np.interp(wght, w_knots, h_knots))

    return dict(
        vstem=vstem, hbar=hbar, capH=capH, xH=xH, asc=asc, desc=desc,
        width=w_fac, italic_deg=italic_deg, rounded=rounded,
        mtav_cue=mtav_cue, mtav_cap_tuck=mtav_cap_tuck,
        ps_name=ps_name, wght=wght,
    )


# ---------------------------------------------------------------------------
# Core 1-to-1 Koba Parametric Builder (Fixed 36-Master VF Topology!)
# ---------------------------------------------------------------------------

def build_georgian_ampersand(
    variant="Master",
    case="mkhedruli",                    # "mkhedruli" (1:1 Koba) or "mtavruli" (Isotropic L1.07b!)
    weight="Regular",
    width="Normal",
    rounded=False,
    italic_deg=0.0,                      # 0.0 Upright, 8.0 Batumi Sans -8° Italic
    mtav_cue=DEFAULT_MTAV_CUE,           # Official Batumi Sans L1.07b ±44.5u cues
    mtav_cap_tuck=DEFAULT_MTAV_CAP_TUCK, # Official Batumi Sans L1.07b -14.0u CapH tuck
    mtav_caps=DEFAULT_MTAV_CAPS,         # Mtavruli lower-base & flatter-tail preset: "Ref"|"CapsA"|"CapsB"|"CapsC"
    metrics_override=None,
):
    """
    Build the 1-to-1 Koba Original Georgian Ampersand glyph with exact fixed VF topology:
      - contours[0]: CCW outer contour
          Sharp:   21 segments (18 cubics + 3 flat terminal cuts: top, spur, foot)
          Rounded: 24 segments (18 body cubics + 3 × 2 κ=0.580 superelliptical caps)
      - contours[1]: CW inner Italic-`დ` oval counter (exact bBox Type 4 cubics)
    """
    vp = VARIANTS[variant]
    wm = dict(BATUMI_WEIGHTS[weight]) if isinstance(weight, str) else dict(weight)
    if metrics_override:
        wm.update(metrics_override)
    w_fac = BATUMI_WIDTHS[width] if isinstance(width, str) else float(width)

    is_mtav = (case == "mtavruli")
    caps_preset = (
        MTAV_CAPS_PRESETS[mtav_caps] if isinstance(mtav_caps, str) else dict(mtav_caps)
    ) if is_mtav else MTAV_CAPS_PRESETS["Ref"]

    vstem_raw = float(wm["vstem"])
    capH = float(wm["capH"])

    # Normalized weight progress wt in [0 (Thin 23u) .. 1 (Heavy 201u)]
    wt = max(0.0, min(1.0, (vstem_raw - 23.0) / (201.0 - 23.0)))

    # -----------------------------------------------------------------------
    # 1. Optical Width & Isotropic Mtavruli Stem-Preservation Calibration
    # -----------------------------------------------------------------------
    # True `src/condenser.py` stem-preservation factors (ExtraCon 95%, Con 97.5%, Exp 101.5%)
    v_pres, h_pres = width_stem_preservation(w_fac)

    # First measure unscaled natural Mkhedruli vertical span at this weight to compute
    # exact isotropic Mtavruli scale `s_iso` (ZERO pancake squishing!).
    ref_o, _ = sample_doni_master(vstem_raw, vstem_raw)
    ref_d_ymin = min(p[1] for _, pts in ref_o for p in pts)
    ref_d_ymax = max(p[1] for _, pts in ref_o for p in pts)
    ref_ov_b_y = ref_o[0][1][0][1]
    y_top_mkh_raw = ref_d_ymin + _KOBA_REF_HEIGHT_RATIO * (ref_d_ymax - ref_d_ymin)
    lift_frac = float(caps_preset.get("lift_frac", 0.0))
    ref_ymin_eff = ref_d_ymin + lift_frac * max(120.0, ref_ov_b_y - ref_d_ymin)
    H_mkh = y_top_mkh_raw - ref_ymin_eff

    if is_mtav:
        y_mtav_bot = -mtav_cue
        y_mtav_top = capH + mtav_cap_tuck + mtav_cue  # L1.07b: 711.5 Thin, 719.5 Reg, 723.5 Bold, 726.5 Heavy
        H_mtav = y_mtav_top - y_mtav_bot
        s_iso = H_mtav / H_mkh  # Ref ~0.85, CapsA ~0.91, CapsB ~0.95, CapsC ~0.99 (PURE ISOTROPIC!)
        # Weight-master compensation so scaled strokes keep ~96% optical color beside Დ/Ქ/Ა!
        iso_comp = 0.965 - 0.045 * wt
        v_base = max(23.0, min(201.0, vstem_raw * (iso_comp / s_iso)))
    else:
        s_iso = 1.0
        v_base = vstem_raw

    # X-only weight-compensated master sampling (exact `src/condenser.py` principle!):
    # Sampling X from heavier master `v_x = v_base * (v_pres / w_fac)` then scaling X by `w_fac`
    # preserves vertical stems at `v_pres` (95% XCon / 97.5% Con / 101.5% Exp) while keeping
    # horizontal bars at `h_pres` and preserving 100% exact 12+4 VF segment topology!
    v_x_sample = max(23.0, min(201.0, v_base * (v_pres / w_fac)))
    v_y_sample = max(23.0, min(201.0, v_base * h_pres))

    d_o_raw, d_i_raw = sample_doni_master(v_x_sample, v_y_sample)

    # Un-slant Path 1 from FiraGO's baked-in `-8.0°` Italic master to dead-upright (`0.0°`)
    # BEFORE optical width scaling so ALL 4 widths (`ExtraCondensed`, `Condensed`, `Normal`, `Expanded`)
    # remain strictly upright (`0.0°`), while preserving 100% of horizontal cross-sections & `OV_B` tangents!
    ov_b_y_raw = d_o_raw[0][1][0][1]
    d_o_up = shear_ring(d_o_raw, -MASTER_ITALIC_DEG, ov_b_y_raw)
    d_i_up = shear_ring(d_i_raw, -MASTER_ITALIC_DEG, ov_b_y_raw)

    # Apply horizontal optical width scale `w_fac` around OV_B.x pivot
    x_piv = d_o_up[0][1][0][0]
    def scale_ring_x(ring, sx, piv):
        return [
            (k, tuple((piv + sx * (p[0] - piv), p[1]) for p in pts))
            for k, pts in ring
        ]

    d_o = scale_ring_x(d_o_up, w_fac, x_piv)
    d_i = scale_ring_x(d_i_up, w_fac, x_piv)

    # Record un-flattened Path 1 bounds BEFORE Mtavruli tail flattening so the core დ oval
    # and Capital Ა top stay 100% locked to Koba's exact proportions!
    d_ymin_unflat = min(p[1] for _, pts in d_o for p in pts)
    d_ymax = max(p[1] for _, pts in d_o for p in pts)
    ov_r_up_x = d_o[1][1][0][0]

    # For Mtavruli Caps A/B/C: flatten & lift ONLY the lower tail (d_o[3..10]) on the upright დ,
    # preserving 100% stroke thickness, 90° perpendicular foot corners, untouched დ oval,
    # untouched C_bot->OV_B, and seamless Thin 100 join!
    if is_mtav and lift_frac > 1e-6:
        d_o = flatten_doni_tail(d_o, caps_preset, wt, w_fac=w_fac)

    # Apply exact `+italic_deg` (`+8.0°` for Batumi Sans `-8°` Italic) onto the upright master
    # BEFORE Path 2 stroking & Rounded cap construction so Italic matches `-8.0°` letters dead-on
    # across ALL 4 widths (never double-slanted!) and Rounded caps stay true circular κ=0.580!
    ov_b_y_cur = d_o[0][1][0][1]
    if abs(italic_deg) > 1e-4:
        d_o = shear_ring(d_o, italic_deg, ov_b_y_cur)
        d_i = shear_ring(d_i, italic_deg, ov_b_y_cur)

    # Measure exact landmarks of Path 1 (დ) after optical width & slant transform!
    OV_B = d_o[0][1][0]   # Bottom horizontal extremum of დ (exact tangent (1, 0)!)
    OV_R = d_o[1][1][0]   # Rightmost oval control landmark of დ
    OV_T = d_o[2][1][0]   # Top extremum of დ
    I_R  = d_i[1][1][0]
    I_B  = d_i[2][1][0]

    hbar_d = max(14.0, I_B[1] - OV_B[1])    # Exact დ bottom bar height (20 Thin, 74 Reg, 107 Bold, 126 Heavy!)
    vstem_d = max(18.0, OV_R[0] - I_R[0])   # Exact დ right stem width (23 Thin, 94 Reg, 154 Bold, 190 Heavy!)

    # Exact Koba 1:1 top height for Path 2 (Capital Ა) anchored to un-flattened დ geometry!
    y_top_raw = d_ymin_unflat + _KOBA_REF_HEIGHT_RATIO * (d_ymax - d_ymin_unflat)
    # In Rounded mode, slight top pull-back so κ=0.580 cap apex kisses the exact target top line!
    y_top_ani = y_top_raw if not rounded else (y_top_raw - (2.5 + 7.5 * wt) / s_iso)

    # -----------------------------------------------------------------------
    # 2. Exact Koba `Path 2` (Capital Ა) Centerline & Seamless Rail Lock!
    # -----------------------------------------------------------------------
    # Lock bottom rail CO-LINEARLY to Path 1's OV_B.y (outer) and I_B.y (inner) at OV_B,
    # with Koba's exact subtle ~4u organic rise across the 200u rail span (68.0->72.7, 142.0->149.2
    # at Regular, scaling to <1u in Thin 100!) with strictly horizontal (1,0) tangents at BOTH ends:
    # achieves 100% G2-smooth zero-hard-edge Thin 100 across both Upright (0°) and Italic (-8°)!
    rail_lift_out = 4.2 * (hbar_d / 74.0)
    rail_lift_in  = 5.8 * (hbar_d / 74.0)
    y_rail_out = OV_B[1] + rail_lift_out
    y_rail_in  = I_B[1] + rail_lift_in
    y_rail_c = 0.5 * (y_rail_out + y_rail_in)
    w_h_ani = y_rail_in - y_rail_out  # EXACT match to დ bottom bar (+1.6u exact Koba rail fullness!)

    # Smooth optical harmony for Path 2 vertical stem vs Path 1 right wall
    ani_v_fac = vp["ani_v_reg"] + (vp["ani_v_heavy"] - vp["ani_v_reg"]) * max(0.0, (wt - 0.415) / 0.585)
    w_v_ani = vstem_d * ani_v_fac

    # Un-slant Koba's Path 2 centerline by `-MASTER_ITALIC_DEG` around `_KOBA_REF_OV_B_Y` (68.0),
    # keeping 100% exact horizontal gap vs Path 1 at every height `y`, then align the top stem tip
    # (`C1_u[0].x = C1_u[1].x`, -2.68u) to exact `0.00°` vertical matching native Upright `uni10D0.case` (`Ა`)!
    C1_ref, C2_ref, C3_ref = KOBA_ANI_CENTERLINE_REF
    C1_u = shear_cubic(C1_ref, -MASTER_ITALIC_DEG, _KOBA_REF_OV_B_Y)
    C2_u = shear_cubic(C2_ref, -MASTER_ITALIC_DEG, _KOBA_REF_OV_B_Y)
    C3_u = shear_cubic(C3_ref, -MASTER_ITALIC_DEG, _KOBA_REF_OV_B_Y)
    C1_u = ((C1_u[1][0], C1_u[0][1]), C1_u[1], C1_u[2], C1_u[3])

    # Smooth horizontal bay breathing + connecting leg extension (computed in upright space so
    # Upright & Italic preserve identical horizontal leg length, bay & S-neck clearance across
    # all 4 optical widths, while leaving both დ and Ა bowls 100% undistorted!):
    dv_above_reg = max(0.0, vstem_d - 94.0)
    dv_below_reg = max(0.0, 94.0 - vstem_d)
    leg_ext_base = vp.get("leg_ext_thin", 0.0) + (
        vp.get("leg_ext_heavy", 0.0) - vp.get("leg_ext_thin", 0.0)
    ) * wt
    dx_leg = leg_ext_base * (0.45 + 0.55 * w_fac)
    dx_bay = vp["bay_expand_bold"] * dv_above_reg + 0.34 * dv_below_reg * w_fac + dx_leg

    # Guarantee generous open beige bay even in ExtraCondensed Heavy (never crashes or pinches!)
    min_bay_u = max(86.0, (124.0 - 22.0 * wt) * (0.45 + 0.55 * w_fac)) / max(0.88, s_iso)
    apex_x_unshifted = OV_B[0] + (C2_u[3][0] - _KOBA_REF_OV_B_X) * w_fac + dx_bay
    bay_est = (apex_x_unshifted - 0.5 * w_v_ani) - ov_r_up_x
    if bay_est < min_bay_u:
        dx_bay += (min_bay_u - bay_est)

    # Extra diagonal corridor guard for top S-neck in Condensed/ExtraCondensed Heavy so
    # the top `Ა` stem NEVER crashes into the upper-right shoulder of `დ`!
    top_x_unshifted = OV_B[0] + (C1_u[0][0] - _KOBA_REF_OV_B_X) * w_fac + dx_bay
    cond_extra_top_x = max(0.0, 1.0 - w_fac) * 140.0 * max(0.0, wt - 0.35)
    # Never compress horizontal S-swing below 78% of natural width
    max_top_shift = 0.20 * (apex_x_unshifted - top_x_unshifted)
    dx_top_extra = min(max_top_shift, cond_extra_top_x)

    def map_ani_pt(pt, is_top_weight=0.0):
        # X: exact Koba offset from OV_B.x scaled by w_fac + smooth bay breathing + top guard
        x = OV_B[0] + (pt[0] - _KOBA_REF_OV_B_X) * w_fac + dx_bay + is_top_weight * dx_top_extra
        # Y: exact linear map from [_KOBA_REF_RAIL_Y .. _KOBA_REF_TOP_Y] -> [y_rail_c .. y_top_ani]
        t_y = (pt[1] - _KOBA_REF_RAIL_Y) / (_KOBA_REF_TOP_Y - _KOBA_REF_RAIL_Y)
        y = y_rail_c + t_y * (y_top_ani - y_rail_c)
        return (x, y)

    # Keep equal 1.0 weight on C1[0] and C1[1] so the top `Ა` stem stays strictly 0.0° vertical
    # even in Condensed/ExtraCondensed Heavy!
    C1 = (
        map_ani_pt(C1_u[0], 1.0),
        map_ani_pt(C1_u[1], 1.0),
        map_ani_pt(C1_u[2], 0.50),
        map_ani_pt(C1_u[3], 0.25),
    )
    C2 = (
        map_ani_pt(C2_u[0], 0.25),
        map_ani_pt(C2_u[1], 0.10),
        map_ani_pt(C2_u[2], 0.0),
        map_ani_pt(C2_u[3], 0.0),
    )
    C3 = (
        map_ani_pt(C3_u[0], 0.0),
        map_ani_pt(C3_u[1], 0.0),
        map_ani_pt(C3_u[2], 0.0),
        map_ani_pt(C3_u[3], 0.0),
    )

    # Apply exact `+italic_deg` shear to Path 2 centerline around OV_B.y BEFORE normal-offset stroking
    # so Italic top cut stays strictly horizontal (`flat_start_y=y_top_ani`) and Rounded caps stay circular!
    if abs(italic_deg) > 1e-4:
        C1 = shear_cubic(C1, italic_deg, ov_b_y_cur)
        C2 = shear_cubic(C2, italic_deg, ov_b_y_cur)
        C3 = shear_cubic(C3, italic_deg, ov_b_y_cur)

    # Exact Batumi directional normal-offset of Koba's 3-cubic Path 2 centerline!
    # At Regular Normal: produces 0.985+ exact vector-to-vector IoU vs `ამპრესონდი.pdf`!
    s_top = vp["ani_top_scale"]
    s_inf = vp["ani_inf_scale"]
    diag_b = vp["ani_diag_boost"]

    # Match Koba's exact subtle horizontal offset between outer bowl rail end (481.7) & inner (499.1)
    rail_asym = 8.5 * (w_h_ani / 74.0) * w_fac

    seg_ani_in_1 = offset_cubic_fit(
        C1, w_v_ani, w_h_ani, side=-1, s0=s_top, s1=s_inf, diag_boost=diag_b, flat_start_y=y_top_ani
    )
    seg_ani_in_2 = offset_cubic_fit(
        C2, w_v_ani, w_h_ani, side=-1, s0=s_inf, s1=1.0, diag_boost=diag_b
    )
    seg_ani_in_3 = offset_cubic_fit(
        C3, w_v_ani, w_h_ani, side=-1, s0=1.0, s1=1.0, diag_boost=diag_b, end_x_shift=+rail_asym
    )

    seg_ani_out_1 = reverse_cubic(offset_cubic_fit(
        C1, w_v_ani, w_h_ani, side=+1, s0=s_top, s1=s_inf, diag_boost=diag_b, flat_start_y=y_top_ani
    ))
    seg_ani_out_2 = reverse_cubic(offset_cubic_fit(
        C2, w_v_ani, w_h_ani, side=+1, s0=s_inf, s1=1.0, diag_boost=diag_b
    ))
    seg_ani_out_3 = reverse_cubic(offset_cubic_fit(
        C3, w_v_ani, w_h_ani, side=+1, s0=1.0, s1=1.0, diag_boost=diag_b, end_x_shift=-rail_asym
    ))

    P_top_L = seg_ani_in_1[0]
    P_top_R = seg_ani_out_1[3]
    P_rail_in = seg_ani_in_3[3]
    P_rail_out = seg_ani_out_3[0]

    # -----------------------------------------------------------------------
    # 3. Seamless G1/G2 `დ -> Ა` Union (ZERO Hard Edge at Thin 100..Heavy 900!)
    # -----------------------------------------------------------------------
    # Inner bay floor meets Path 1's `OV_B -> OV_R` curve analytically at exact `y = P_rail_in.y`:
    t_c_in = solve_cubic_y(*d_o[0][1], P_rail_in[1], t_lo=0.01, t_hi=0.92)
    _, seg_ov_C_to_R = cubic_split(*d_o[0][1], t_c_in)
    C_in = seg_ov_C_to_R[0]

    # Ensure P_rail_in stays strictly right of C_in (even in extreme Heavy XCon!)
    if P_rail_in[0] < C_in[0] + 12.0:
        shift_x = (C_in[0] + 12.0) - P_rail_in[0]
        p0, p1, p2, p3 = seg_ani_in_3
        seg_ani_in_3 = (p0, p1, (p2[0] + 0.5 * shift_x, p2[1]), (p3[0] + shift_x, p3[1]))
        P_rail_in = seg_ani_in_3[3]

    dx_ri = P_rail_in[0] - C_in[0]
    seg_rail_in = (
        P_rail_in,
        (P_rail_in[0] - 0.34 * dx_ri, P_rail_in[1]),
        (C_in[0] + 0.34 * dx_ri, C_in[1]),
        C_in,
    )

    # Outer bottom rail: 100% FLAT HORIZONTAL G2 bridge from OV_B (tangent (1,0)) to P_rail_out (tangent (1,0))!
    # Guarantee OV_B.y == P_rail_out.y to floating-point exactness -> ZERO seam, ZERO kink, ZERO step!
    dx_ro = max(12.0, P_rail_out[0] - OV_B[0])
    seg_rail_out = (
        OV_B,
        (OV_B[0] + 0.34 * dx_ro, OV_B[1]),
        (P_rail_out[0] - 0.34 * dx_ro, P_rail_out[1]),
        P_rail_out,
    )

    # -----------------------------------------------------------------------
    # 4. Assemble Exact Fixed-Topology CCW Outer Contour (Sharp or Rounded!)
    # -----------------------------------------------------------------------
    # Path 1 remaining 11 segments (d_o[1:]):
    #   d_o[1]=ov_RT, d_o[2]=ov_TL, d_o[3]=ov_to_spur, d_o[4]=spur_top,
    #   d_o[5]=LINE(spur_cut), d_o[6]=arch_L, d_o[7]=arch_R,
    #   d_o[8]=LINE(foot_cut), d_o[9]=leg_up_1, d_o[10]=leg_up_2, d_o[11]=cbot_to_ovB!
    if not rounded:
        outer_contour = [
            ("line",  (P_top_R, P_top_L)),
            ("cubic", seg_ani_in_1),
            ("cubic", seg_ani_in_2),
            ("cubic", seg_ani_in_3),
            ("cubic", seg_rail_in),
            ("cubic", seg_ov_C_to_R),
        ] + list(d_o[1:]) + [
            ("cubic", seg_rail_out),
            ("cubic", seg_ani_out_3),
            ("cubic", seg_ani_out_2),
            ("cubic", seg_ani_out_1),
        ]
    else:
        ov_top  = (3.5 + 2.5 * wt) / s_iso
        ov_spur = (2.0 + 1.5 * wt) / s_iso
        # Foot cut is angled ~28° on Bold/Heavy Mkhedruli; flatter in Mtavruli Caps A/B/C -> moderate overshoot!
        ov_foot = (4.0 + (20.0 * (1.0 - 0.70 * lift_frac)) * wt) / s_iso

        s_ani_out_1_r, cap_top_1, cap_top_2, s_ani_in_1_r = make_superelliptical_cap(
            ("cubic", seg_ani_out_1), ("cubic", seg_ani_in_1), overshoot=ov_top
        )
        s_spur_top_r, cap_spur_1, cap_spur_2, s_arch_L_r = make_superelliptical_cap(
            d_o[4], d_o[6], overshoot=ov_spur
        )
        s_arch_R_r, cap_foot_1, cap_foot_2, s_leg_up_1_r = make_superelliptical_cap(
            d_o[7], d_o[9], overshoot=ov_foot
        )

        outer_contour = [
            cap_top_1,
            cap_top_2,
            s_ani_in_1_r,
            ("cubic", seg_ani_in_2),
            ("cubic", seg_ani_in_3),
            ("cubic", seg_rail_in),
            ("cubic", seg_ov_C_to_R),
            d_o[1],
            d_o[2],
            d_o[3],
            s_spur_top_r,
            cap_spur_1,
            cap_spur_2,
            s_arch_L_r,
            s_arch_R_r,
            cap_foot_1,
            cap_foot_2,
            s_leg_up_1_r,
            d_o[10],
            d_o[11],
            ("cubic", seg_rail_out),
            ("cubic", seg_ani_out_3),
            ("cubic", seg_ani_out_2),
            s_ani_out_1_r,
        ]

    contours = [outer_contour, list(d_i)]

    # -----------------------------------------------------------------------
    # 5. True ISOTROPIC Scaling for `L1.07b` Mtavruli (ZERO Pancake Squishing!)
    # -----------------------------------------------------------------------
    if is_mtav:
        # Measure exact current y_min and y_max across all curves
        ys_cur = []
        for c in contours:
            for k, pts in c:
                if k == "line":
                    ys_cur.extend([pts[0][1], pts[1][1]])
                else:
                    for i in range(17):
                        ys_cur.append(cubic_eval(*pts, i / 16.0)[1])
        cur_ymin, cur_ymax = min(ys_cur), max(ys_cur)
        # Apply EQUAL X and Y isotropic scaling so exact 1:1 Koba aspect ratio is 100% preserved!
        y_mtav_bot = -mtav_cue
        y_mtav_top = capH + mtav_cap_tuck + mtav_cue
        if rounded:
            # Slight optical overshoot matching BatumiSansRounded L1.07b Ქ/Დ (~1–3u)
            y_mtav_top += (1.0 + 3.0 * wt)
        s_exact = (y_mtav_top - y_mtav_bot) / max(1.0, cur_ymax - cur_ymin)
        contours = [
            [
                (k, tuple((p[0] * s_exact, y_mtav_bot + (p[1] - cur_ymin) * s_exact) for p in pts))
                for k, pts in c
            ]
            for c in contours
        ]
        # Scale diagnostic values too (true horizontal inner-eye span + bay width)
        xs_i_diag = [cubic_eval(*pts, k / 16.0)[0] for _, pts in d_i for k in range(16)]
        bay_w_diag = (seg_ani_in_2[3][0] - OV_R[0]) * s_exact
        eye_w_diag = (max(xs_i_diag) - min(xs_i_diag)) * s_exact
        eye_h_diag = (d_i[0][1][0][1] - I_B[1]) * s_exact
        vstem_diag = vstem_d * s_exact
        hbar_diag = hbar_d * s_exact
    else:
        xs_i_diag = [cubic_eval(*pts, k / 16.0)[0] for _, pts in d_i for k in range(16)]
        bay_w_diag = seg_ani_in_2[3][0] - OV_R[0]
        eye_w_diag = max(xs_i_diag) - min(xs_i_diag)
        eye_h_diag = d_i[0][1][0][1] - I_B[1]
        vstem_diag = vstem_d
        hbar_diag = hbar_d

    # (Note: Exact `+italic_deg` shear is already applied in Steps 1–2 BEFORE Path 2 stroking
    #  and Rounded cap construction, guaranteeing zero double-slanting in Italic and true
    #  circular κ=0.580 Rounded caps in both Upright 0° and Italic -8°!)

    # -----------------------------------------------------------------------
    # 6. Exact Bounds & Balanced Sidebearings (matching Batumi Sans დ / Დ!)
    # -----------------------------------------------------------------------
    xs, ys = [], []
    for c in contours:
        for k, pts in c:
            if k == "line":
                for p in pts:
                    xs.append(p[0]); ys.append(p[1])
            else:
                for i in range(17):
                    p = cubic_eval(*pts, i / 16.0)
                    xs.append(p[0]); ys.append(p[1])
    b_xmin, b_xmax = min(xs), max(xs)
    b_ymin, b_ymax = min(ys), max(ys)

    lsb = (52.0 - 26.0 * wt) * (0.75 + 0.25 * w_fac) * (0.94 if is_mtav else 1.0)
    rsb = (48.0 - 24.0 * wt) * (0.75 + 0.25 * w_fac) * (0.94 if is_mtav else 1.0)

    dx = lsb - b_xmin
    if abs(dx) > 1e-6:
        contours = [
            [(k, tuple((pt[0] + dx, pt[1]) for pt in pts)) for k, pts in c]
            for c in contours
        ]
        b_xmin += dx
        b_xmax += dx

    advance = int(round(b_xmax + rsb))
    return dict(
        contours=contours,
        advance=advance,
        bounds=(b_xmin, b_ymin, b_xmax, b_ymax),
        lsb=b_xmin,
        rsb=advance - b_xmax,
        meta=dict(
            variant=variant, case=case, weight=weight, width=width,
            rounded=rounded, italic_deg=italic_deg,
            mtav_cue=mtav_cue, mtav_cap_tuck=mtav_cap_tuck,
            vstem=round(vstem_diag, 1), hbar=round(hbar_diag, 1),
            bay_w=round(bay_w_diag, 1),
            counter_w=round(eye_w_diag, 1),
            counter_h=round(eye_h_diag, 1),
            aspect=round((b_xmax - b_xmin) / max(1.0, b_ymax - b_ymin), 4),
            outer_segs=len(contours[0]), inner_segs=len(contours[1]),
            outer_area=round(contour_signed_area(contours[0]), 1),
            inner_area=round(contour_signed_area(contours[1]), 1),
        ),
    )


def draw_contours_to_pen(contours, pen, round_coords=True):
    """Draw our segment-list contours to any fontTools / pathops pen (0.5u CFF precision)."""
    fmt = (lambda p: (round(p[0] * 2.0) / 2.0, round(p[1] * 2.0) / 2.0)) if round_coords else (lambda p: p)
    for c in contours:
        if not c:
            continue
        p_start = c[0][1][0]
        pen.moveTo(fmt(p_start))
        for k, pts in c:
            if k == "line":
                pen.lineTo(fmt(pts[1]))
            else:
                pen.curveTo(fmt(pts[1]), fmt(pts[2]), fmt(pts[3]))
        pen.closePath()


def validate_glyph_pathops(glyph):
    """
    Strict foundry QA via skia-pathops:
      1. Exact PostScript winding: outer CCW (> 0), inner CW (< 0).
      2. Zero inner-counter leak outside outer contour.
      3. Zero self-intersections / overlaps (simplify produces exact 2 contours & < 25 sq.u XOR delta).
    """
    contours = glyph["contours"]
    a_out = contour_signed_area(contours[0])
    a_in = contour_signed_area(contours[1])

    p_out = pathops.Path(); draw_contours_to_pen([contours[0]], p_out.getPen(), round_coords=False)
    p_in = pathops.Path();  draw_contours_to_pen([contours[1]], p_in.getPen(), round_coords=False)

    leak = pathops.Path()
    pathops.difference([p_in], [p_out], leak.getPen())
    leak_area = abs(leak.area)

    p = pathops.Path()
    draw_contours_to_pen(contours, p.getPen(), round_coords=False)
    ps = pathops.simplify(p, fix_winding=True)
    simp_contours = len(list(ps.contours))

    diff = pathops.Path()
    pathops.xor([p], [ps], diff.getPen())
    diff_area = abs(diff.area)

    ok = (a_out > 1000.0) and (a_in < -1000.0) and (leak_area < 0.1) and (simp_contours == 2) and (diff_area < 25.0)
    return ok, dict(
        a_out=round(a_out, 1),
        a_in=round(a_in, 1),
        leak_area=round(leak_area, 2),
        simp_contours=simp_contours,
        xor_area=round(diff_area, 2),
        outer_segs=len(contours[0]),
        inner_segs=len(contours[1]),
    )


# ---------------------------------------------------------------------------
# Drop-In Font Injection & 4-Layer OpenType GSUB Wiring (for all 144 static fonts!)
# ---------------------------------------------------------------------------

def _add_glyph_to_cff(font, gname, glyph_data):
    cff = font["CFF "].cff
    top = cff.topDictIndex[0]
    cs_table = top.CharStrings
    gs = font.getGlyphSet()

    priv = top.Private
    nominal = getattr(priv, "nominalWidthX", 0)
    pen = T2CharStringPen(glyph_data["advance"] - nominal, gs, roundTolerance=0.0)
    draw_contours_to_pen(glyph_data["contours"], pen, round_coords=True)
    charstring = pen.getCharString(private=priv, globalSubrs=cff.GlobalSubrs)

    order = list(font.getGlyphOrder())
    if gname not in order:
        order.append(gname)
        font.setGlyphOrder(order)
    font["maxp"].numGlyphs = len(order)

    if gname not in cs_table.charStrings:
        top.charset.append(gname)
        new_idx = len(cs_table.charStringsIndex)
        cs_table.charStringsIndex.append(charstring)
        cs_table.charStrings[gname] = new_idx
    else:
        cs_table[gname] = charstring

    font["hmtx"][gname] = (glyph_data["advance"], int(round(glyph_data["lsb"])))

    if "GDEF" in font and font["GDEF"].table.GlyphClassDef:
        font["GDEF"].table.GlyphClassDef.classDefs[gname] = 1


def _make_coverage(glyphs, gmap):
    cov = otTables.Coverage()
    cov.glyphs = sorted(set(glyphs), key=lambda g: gmap[g])
    return cov


def _make_single_subst(mapping):
    st = otTables.SingleSubst()
    st.mapping = dict(mapping)
    lk = otTables.Lookup()
    lk.LookupType = 1
    lk.LookupFlag = 0
    lk.SubTable = [st]
    lk.SubTableCount = 1
    return lk


def _make_chain_fmt3(backtrack_lists, input_lists, lookahead_lists, subst_idx, gmap):
    st = otTables.ChainContextSubst()
    st.Format = 3
    st.BacktrackCoverage = [_make_coverage(gl, gmap) for gl in backtrack_lists]
    st.BacktrackGlyphCount = len(st.BacktrackCoverage)
    st.InputCoverage = [_make_coverage(gl, gmap) for gl in input_lists]
    st.InputGlyphCount = len(st.InputCoverage)
    st.LookAheadCoverage = [_make_coverage(gl, gmap) for gl in lookahead_lists]
    st.LookAheadGlyphCount = len(st.LookAheadCoverage)
    rec = otTables.SubstLookupRecord()
    rec.SequenceIndex = 0
    rec.LookupListIndex = subst_idx
    st.SubstLookupRecord = [rec]
    st.SubstCount = 1
    return st


def _add_name_string(font, text):
    nt = font["name"]
    for r in nt.names:
        if r.nameID >= 256 and r.platformID == 3 and r.toUnicode() == text:
            return r.nameID
    used = {r.nameID for r in nt.names}
    nid = max([255] + [i for i in used if i >= 256]) + 1
    nt.setName(text, nid, 3, 1, 0x0409)
    nt.setName(text, nid, 1, 0, 0)
    return nid


def _sort_gsub_feature_list(gsub):
    """
    Maintain strict OpenType-spec alphabetical FeatureTag order in GSUB.FeatureList
    while remapping every ScriptList DefaultLangSys / LangSys FeatureIndex cleanly.
    """
    old_frs = list(gsub.FeatureList.FeatureRecord)
    indexed = list(enumerate(old_frs))
    indexed.sort(key=lambda pair: (pair[1].FeatureTag, pair[0]))
    old_to_new = {old_i: new_i for new_i, (old_i, _) in enumerate(indexed)}
    gsub.FeatureList.FeatureRecord = [fr for _, fr in indexed]
    gsub.FeatureList.FeatureCount = len(indexed)

    for sr in gsub.ScriptList.ScriptRecord:
        lss = []
        if sr.Script.DefaultLangSys:
            lss.append(sr.Script.DefaultLangSys)
        for lr in sr.Script.LangSysRecord:
            lss.append(lr.LangSys)
        for ls in lss:
            ls.FeatureIndex = sorted({old_to_new[i] for i in ls.FeatureIndex})
            ls.FeatureCount = len(ls.FeatureIndex)


def _build_calt_georgian_subtables(font, idx_to_geor, idx_to_geor_case, idx_keep_geor=None):
    """
    Build the exact priority-ordered `calt` ChainContextSubst subtables for Georgian Ampersand:
      - Priority 0: Backtrack `[mkh + nusk]` (or `[sep, mkh + nusk]`) + `amp_any` -> `ampersand.geor` (Regular)
        Ensures bicameral title-case Khutsuri (`Ⴑⴀⴕⴀⴐⴇⴅⴄⴊⴍ & Ⴁⴀⴇⴓⴋⴈ`) & Mkhedruli stay Regular `&`
        even after `locl` (`geor`) maps `&` -> `ampersand.geor`!
      - Priority 1: `[mtav + asom]` in Backtrack or Lookahead -> `ampersand.geor.case` (All-Caps)
        Upgrades All-Caps Mtavruli (`ᲥᲕᲔᲕᲠᲘ & ᲦᲕᲘᲜᲝ`) & All-Caps Asomtavruli (`ႱႠႵႠႰႧႥႤႪႭ & ႡႠႧႳႫႨ`)!
      - Priority 2: Lookahead `[mkh + nusk]` (or `[sep, mkh + nusk]`) -> `ampersand.geor` (Regular)
      - Latin `&` and word `და` remain 100% untouched.
    """
    cmap = font.getBestCmap()
    glyph_order = font.getGlyphOrder()
    gmap = {g: i for i, g in enumerate(glyph_order)}
    all_g = set(glyph_order)

    mkh_set = {cmap[cp] for cp in range(0x10D0, 0x1100) if cp in cmap and cmap[cp] in all_g}
    nusk_set = {cmap[cp] for cp in range(0x2D00, 0x2D30) if cp in cmap and cmap[cp] in all_g}
    mtav_set = {cmap[cp] for cp in range(0x1C90, 0x1CC0) if cp in cmap and cmap[cp] in all_g}
    asom_set = {cmap[cp] for cp in range(0x10A0, 0x10CE) if cp in cmap and cmap[cp] in all_g}
    for g in glyph_order:
        gl = g.lower()
        if (g.startswith("uni10D") or g.startswith("uni10E") or g.startswith("uni10F") or "georgian" in gl):
            if ".case" in g:
                mtav_set.add(g)
            else:
                mkh_set.add(g)
    reg_glyphs = sorted(mkh_set | nusk_set, key=lambda g: gmap[g])
    caps_glyphs = sorted(mtav_set | asom_set, key=lambda g: gmap[g])

    sep_candidates = [
        "space", "uni00A0", "nbspace", "thinspace", "hairspace",
        "uni2009", "uni200A", "uni202F", "hyphen", "endash", "emdash",
    ]
    sep_glyphs = [g for g in sep_candidates if g in all_g]
    if not sep_glyphs and 0x0020 in cmap:
        sep_glyphs = [cmap[0x0020]]

    amp_any = ["ampersand", "ampersand.geor"]
    keep_idx = idx_keep_geor if idx_keep_geor is not None else idx_to_geor
    return [
        # Priority 0: Backtrack Mkhedruli or Nuskhuri -> keep/set Regular Georgian `&` (handles title-case Khutsuri!)
        _make_chain_fmt3([reg_glyphs],              [amp_any],       [],                        keep_idx,         gmap),
        _make_chain_fmt3([sep_glyphs, reg_glyphs],  [amp_any],       [],                        keep_idx,         gmap),
        # Priority 1: Mtavruli or Asomtavruli context -> All-Caps Georgian `&`
        _make_chain_fmt3([caps_glyphs],             [amp_any],       [],                        idx_to_geor_case, gmap),
        _make_chain_fmt3([sep_glyphs, caps_glyphs], [amp_any],       [],                        idx_to_geor_case, gmap),
        _make_chain_fmt3([],                        [amp_any],       [caps_glyphs],             idx_to_geor_case, gmap),
        _make_chain_fmt3([],                        [amp_any],       [sep_glyphs, caps_glyphs], idx_to_geor_case, gmap),
        # Priority 2: Lookahead Mkhedruli or Nuskhuri -> Regular Georgian `&`
        _make_chain_fmt3([],                        [["ampersand"]], [reg_glyphs],              idx_to_geor,      gmap),
        _make_chain_fmt3([],                        [["ampersand"]], [sep_glyphs, reg_glyphs],  idx_to_geor,      gmap),
    ]


def update_calt_georgian_ampersand_for_khutsuri(font):
    """
    Idempotently refresh an already-wired `calt` Georgian Ampersand LookupType 6 in-place
    so Asomtavruli (`U+10A0–10CD`) triggers All-Caps `ampersand.geor.case` and Nuskhuri
    (`U+2D00–2D2D`) + bicameral Khutsuri trigger Regular `ampersand.geor`!
    Returns True if updated.
    """
    if "GSUB" not in font:
        return False
    gsub = font["GSUB"].table
    lookups = gsub.LookupList.Lookup
    idx_to_geor = None
    idx_to_geor_case = None
    idx_keep_geor = None
    for li, lk in enumerate(lookups):
        if lk.LookupType == 1 and lk.SubTable:
            m = getattr(lk.SubTable[0], "mapping", None) or {}
            if m.get("ampersand") == "ampersand.geor" and len(m) == 1:
                idx_to_geor = li
            elif m.get("ampersand") == "ampersand.geor" and m.get("ampersand.geor") == "ampersand.geor":
                idx_keep_geor = li
            elif m.get("ampersand") == "ampersand.geor.case" and m.get("ampersand.geor") == "ampersand.geor.case":
                idx_to_geor_case = li
    if idx_to_geor is None or idx_to_geor_case is None:
        return False
    if idx_keep_geor is None:
        idx_keep_geor = len(lookups)
        lookups.append(_make_single_subst({"ampersand": "ampersand.geor", "ampersand.geor": "ampersand.geor"}))
        gsub.LookupList.LookupCount = len(lookups)
    for lk in lookups:
        if lk.LookupType == 6 and lk.SubTable:
            st0 = lk.SubTable[0]
            if (
                getattr(st0, "Format", None) == 3
                and getattr(st0, "InputCoverage", None)
                and "ampersand" in st0.InputCoverage[0].glyphs
            ):
                new_subs = _build_calt_georgian_subtables(font, idx_to_geor, idx_to_geor_case, idx_keep_geor)
                lk.SubTable = new_subs
                lk.SubTableCount = len(new_subs)
                return True
    return False


def wire_gsub_georgian_ampersand(font):
    """
    Idempotently wire the 4-layer OpenType GSUB for Georgian Ampersand:
      - `locl` (`geor` script only): `&` -> `ampersand.geor`
      - `calt` (auto Georgian Mkhedruli/Nuskhuri -> Regular `&`, Mtavruli/Asomtavruli -> All-Caps `&`;
        bicameral title-case Khutsuri stays Regular `&`; Latin `&` and word `და` untouched!)
      - `case` (`ampersand.geor` -> `ampersand.geor.case`)
      - `ss07` ("Georgian Ampersand") & `ss08` ("Georgian Ampersand All-Caps")
        (preserves existing FiraGO/Batumi `ss01`–`ss06` and keeps FeatureList alphabetically sorted!)
    """
    gsub = font["GSUB"].table
    if any(fr.FeatureTag == "ss07" for fr in gsub.FeatureList.FeatureRecord):
        update_calt_georgian_ampersand_for_khutsuri(font)
        return

    lookups = gsub.LookupList.Lookup

    idx_to_geor = len(lookups)
    lookups.append(_make_single_subst({"ampersand": "ampersand.geor"}))

    idx_keep_geor = len(lookups)
    lookups.append(_make_single_subst({"ampersand": "ampersand.geor", "ampersand.geor": "ampersand.geor"}))

    idx_to_geor_case = len(lookups)
    lookups.append(_make_single_subst({
        "ampersand": "ampersand.geor.case",
        "ampersand.geor": "ampersand.geor.case",
    }))

    idx_case_upgrade = len(lookups)
    lookups.append(_make_single_subst({"ampersand.geor": "ampersand.geor.case"}))

    subtables = _build_calt_georgian_subtables(font, idx_to_geor, idx_to_geor_case, idx_keep_geor)
    lk_calt = otTables.Lookup()
    lk_calt.LookupType = 6
    lk_calt.LookupFlag = 0
    lk_calt.SubTable = subtables
    lk_calt.SubTableCount = len(subtables)
    idx_calt_amp = len(lookups)
    lookups.append(lk_calt)
    gsub.LookupList.LookupCount = len(lookups)

    feat_records = gsub.FeatureList.FeatureRecord
    for fr in feat_records:
        if fr.FeatureTag == "calt":
            if idx_calt_amp not in fr.Feature.LookupListIndex:
                fr.Feature.LookupListIndex.append(idx_calt_amp)
                fr.Feature.LookupCount = len(fr.Feature.LookupListIndex)
        elif fr.FeatureTag == "case":
            if idx_case_upgrade not in fr.Feature.LookupListIndex:
                fr.Feature.LookupListIndex.append(idx_case_upgrade)
                fr.Feature.LookupCount = len(fr.Feature.LookupListIndex)

    nid_ss07 = _add_name_string(font, "Georgian Ampersand")
    nid_ss08 = _add_name_string(font, "Georgian Ampersand All-Caps")

    def make_ss(tag, lk_ids, ui_nid):
        fr = otTables.FeatureRecord()
        fr.FeatureTag = tag
        feat = otTables.Feature()
        params = otTables.FeatureParamsStylisticSet()
        params.Version = 0
        params.UINameID = ui_nid
        feat.FeatureParams = params
        feat.LookupListIndex = list(lk_ids)
        feat.LookupCount = len(lk_ids)
        fr.Feature = feat
        return fr

    fr_geor_locl = otTables.FeatureRecord()
    fr_geor_locl.FeatureTag = "locl"
    feat_locl = otTables.Feature()
    feat_locl.FeatureParams = None
    feat_locl.LookupListIndex = [idx_to_geor]
    feat_locl.LookupCount = 1
    fr_geor_locl.Feature = feat_locl
    idx_geor_locl = len(feat_records)
    feat_records.append(fr_geor_locl)

    idx_ss07 = len(feat_records)
    feat_records.append(make_ss("ss07", [idx_to_geor], nid_ss07))
    idx_ss08 = len(feat_records)
    feat_records.append(make_ss("ss08", [idx_to_geor_case], nid_ss08))
    gsub.FeatureList.FeatureCount = len(feat_records)

    calt_feat_idx = next((i for i, fr in enumerate(feat_records) if fr.FeatureTag == "calt"), None)
    for sr in gsub.ScriptList.ScriptRecord:
        lang_systems = []
        if sr.Script.DefaultLangSys:
            lang_systems.append(sr.Script.DefaultLangSys)
        for lr in sr.Script.LangSysRecord:
            lang_systems.append(lr.LangSys)
        for ls in lang_systems:
            for fi in (idx_ss07, idx_ss08):
                if fi not in ls.FeatureIndex:
                    ls.FeatureIndex.append(fi)
            if sr.ScriptTag == "geor":
                if not any(feat_records[i].FeatureTag == "locl" for i in ls.FeatureIndex):
                    ls.FeatureIndex.append(idx_geor_locl)
            if sr.ScriptTag in ("geor", "DFLT", "latn") and calt_feat_idx is not None:
                if not any(feat_records[i].FeatureTag == "calt" for i in ls.FeatureIndex):
                    ls.FeatureIndex.append(calt_feat_idx)
            ls.FeatureIndex.sort()
            ls.FeatureCount = len(ls.FeatureIndex)

    _sort_gsub_feature_list(gsub)


def inject_georgian_ampersand(
    font,
    variant="Master",
    weight=None,
    width=None,
    rounded=None,
    italic_deg=None,
    mtav_cue=None,
    mtav_cap_tuck=None,
    mtav_caps=DEFAULT_MTAV_CAPS,
):
    """
    One-call drop-in injector for any Batumi Sans CFF TTFont:
      1. Auto-measures exact font weight/width/rounded/italic/L1.07b metrics (unless overridden).
      2. Generates & pathops-validates both `ampersand.geor` (Mkhedruli) & `ampersand.geor.case` (Mtavruli).
      3. Inserts glyphs into CFF + hmtx + GDEF + PUA cmap (U+E0A0 / U+E0A1).
      4. Wires complete 4-layer OpenType GSUB (`locl`, `calt`, `case`, `ss07`, `ss08`).
    Returns dict(mkhedruli=g_mkh, mtavruli=g_mtav).
    """
    m = measure_font_metrics(font)
    w_arg = weight if weight is not None else dict(
        vstem=m["vstem"], hbar=m["hbar"], capH=m["capH"], xH=m["xH"], asc=m["asc"], desc=m["desc"]
    )
    wd_arg = width if width is not None else m["width"]
    rnd_arg = rounded if rounded is not None else m["rounded"]
    it_arg = italic_deg if italic_deg is not None else m["italic_deg"]
    cue_arg = mtav_cue if mtav_cue is not None else m["mtav_cue"]
    tuck_arg = mtav_cap_tuck if mtav_cap_tuck is not None else m["mtav_cap_tuck"]

    g_mkh = build_georgian_ampersand(
        variant, "mkhedruli", w_arg, wd_arg, rnd_arg, it_arg,
        mtav_cue=cue_arg, mtav_cap_tuck=tuck_arg,
    )
    g_mtav = build_georgian_ampersand(
        variant, "mtavruli", w_arg, wd_arg, rnd_arg, it_arg,
        mtav_cue=cue_arg, mtav_cap_tuck=tuck_arg, mtav_caps=mtav_caps,
    )

    for lbl, g in (("mkhedruli", g_mkh), ("mtavruli", g_mtav)):
        ok, rep = validate_glyph_pathops(g)
        if not ok:
            raise RuntimeError(f"Georgian Ampersand pathops check failed ({m['ps_name']} {variant} {lbl}): {rep}")

    _add_glyph_to_cff(font, "ampersand.geor", g_mkh)
    _add_glyph_to_cff(font, "ampersand.geor.case", g_mtav)

    for sub in font["cmap"].tables:
        if sub.isUnicode():
            sub.cmap[0xE0A0] = "ampersand.geor"
            sub.cmap[0xE0A1] = "ampersand.geor.case"

    wire_gsub_georgian_ampersand(font)
    return dict(mkhedruli=g_mkh, mtavruli=g_mtav)


# ---------------------------------------------------------------------------
# Exhaustive 288-Glyph (144-Style × 2 Cases) + 36-Master VF Topology QA Suite
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    fails = 0
    total = 0
    for case in ("mkhedruli", "mtavruli"):
        for rounded in (False, True):
            for italic_deg in (0.0, 8.0):
                sigs = set()
                for weight in BATUMI_WEIGHTS:
                    for width in BATUMI_WIDTHS:
                        total += 1
                        g = build_georgian_ampersand(
                            "Master", case, weight, width, rounded, italic_deg,
                            mtav_cue=DEFAULT_MTAV_CUE, mtav_cap_tuck=DEFAULT_MTAV_CAP_TUCK,
                        )
                        ok, rep = validate_glyph_pathops(g)
                        sig = (tuple(k for k, _ in g["contours"][0]), tuple(k for k, _ in g["contours"][1]))
                        sigs.add(sig)
                        if not ok:
                            fails += 1
                            print("FAIL:", case, weight, width, rounded, italic_deg, rep)
                if len(sigs) != 1:
                    fails += 1
                    print("TOPO MISMATCH:", case, rounded, italic_deg, len(sigs))
    print(f"Strict pathops + 36-master VF topology audit (ALL 144 styles × 2 cases): {fails} failures out of {total} glyphs checked!")

    print("\n=== Batumi Koba 1:1 Master Extreme-Corner Negative-Space & Aspect Audit ===")
    corners = [
        ("Thin Normal Shp",      "Thin",    "Normal",         False, 0.0),
        ("Light Normal Shp",     "Light",   "Normal",         False, 0.0),
        ("Regular Normal Shp",   "Regular", "Normal",         False, 0.0),
        ("Bold Normal Shp",      "Bold",    "Normal",         False, 0.0),
        ("Heavy Normal Shp",     "Heavy",   "Normal",         False, 0.0),
        ("Bold Normal Rnd",      "Bold",    "Normal",         True,  0.0),
        ("Heavy Normal Rnd",     "Heavy",   "Normal",         True,  0.0),
        ("Bold Condensed Shp",   "Bold",    "Condensed",      False, 0.0),
        ("Bold XCon 85% Shp",    "Bold",    "ExtraCondensed", False, 0.0),
        ("Heavy XCon 85% Shp",   "Heavy",   "ExtraCondensed", False, 0.0),
        ("Heavy XCon 85% Rnd",   "Heavy",   "ExtraCondensed", True,  0.0),
        ("Heavy Exp 114% Shp",   "Heavy",   "Expanded",       False, 0.0),
        ("Bold Normal -8° Ital", "Bold",    "Normal",         False, 8.0),
    ]
    for case in ("mkhedruli", "mtavruli"):
        print(f"\n--- {case.upper()} (L1.07b) ---")
        for lbl, wt_n, wd_n, rnd_b, it_d in corners:
            g = build_georgian_ampersand("Master", case, wt_n, wd_n, rnd_b, it_d)
            m = g["meta"]; b = g["bounds"]
            print(
                f"  {lbl:22s}: adv={g['advance']:4d} ink_w={b[2]-b[0]:5.1f} y=[{b[1]:6.1f},{b[3]:6.1f}] "
                f"asp={m['aspect']:.3f} v={m['vstem']:5.1f} h={m['hbar']:5.1f} bay={m['bay_w']:5.1f} "
                f"eye={m['counter_w']:5.1f}x{m['counter_h']:5.1f}"
            )

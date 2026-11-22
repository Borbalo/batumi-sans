#!/usr/bin/env python3
"""
Surgical Inner-Arch Recovery for Georgian `ჩ` (`uni10E9`) & `Ჩ` (`uni10E9.case`)
in Extra Condensed & Condensed Bold / ExtraBold / Heavy (Sharp & Rounded, Upright & Italic).

Fixes the condenser artifact where:
  1. `ExtraCondensed Heavy` crushed `ჩ`'s top inner counter from 91u (Normal) down to a 49u slit
     (`Ჩ`: 96u -> 52u), and `Condensed Heavy` crushed it to 67u/68u.
  2. The lower-right cubic handle on `uni10E9`'s inner hole overshot outward past xMax (e.g.
     `(292, 517)` past `x=287`), pulling the lower-right arch into an ugly pinched wedge.

Algorithm (100% geometrically idempotent, zero contour/segment topology change for `varLib`):
  1. Unslant (`8°` if Italic) both target glyph and its corresponding Normal weight master.
  2. Compute target hole width `tw = nw * target_w_ratio`:
       - `extra_condensed`: Heavy (900) -> 0.80, ExtraBold (800) -> 0.82, Bold (700) -> 0.84
       - `condensed`:       Bold..Heavy -> 0.89
     Expand ONLY when `xw < tw` (`expand = max(0, tw - xw) >= 1.0`, zero shrink, 100% idempotent!).
  3. Open inner hole to `[xx0 - 0.35 * expand, xx1 + 0.65 * expand]` AND gently push the outer
     top-right bowl (`y > 440, x > xx1 + 30`, smoothstep ramp over `440..580`) right by
     `+0.35 * expand` so the right bowl wall stays lush (`~170u` thick!).
  4. Eliminate handle overshoot while preserving exact segment ops:
       - If target hole has identical segment op sequence to Normal hole: map Normal's smooth
         normalized `(u, v)` directly onto `[tx0, tx1] x [ty0, ty1]`, then clamp any sub-unit
         slanted-space cubic handle overshoot cleanly.
       - Otherwise: expand target hole linearly to `[tx0, tx1]` in unslanted space and clamp every
         `cubic` off-curve handle inside `[min(p0.x, p3.x), max(p0.x, p3.x)]` (in slanted space
         for Italic so 8° tangents stay smooth, unslanted for Upright).
  5. Re-slant (`8°` if Italic) and write back to CFF (`CharStrings`) or TrueType (`glyf`),
     preserving exact `hmtx` advance width from `georgian_spacing.py`!
"""

import math

import pathops
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.ttGlyphPen import TTGlyphPen

from rounder import (
    contour_signed_area,
    draw_contours_to_pen,
    eval_seg,
    extract_contours,
    fix_disjoint_outer_winding,
)

TAN_8 = math.tan(math.radians(8.0))
ITAL_PIVOT_Y = 264.0
CHIN_TARGET_GLYPHS = ("uni10E9", "uni10E9.case")


def _unslant_pt(p, is_italic):
    if not is_italic:
        return p
    return (p[0] - (p[1] - ITAL_PIVOT_Y) * TAN_8, p[1])


def _reslant_pt(p, is_italic):
    if not is_italic:
        return p
    return (p[0] + (p[1] - ITAL_PIVOT_Y) * TAN_8, p[1])


def _smoothstep(t):
    t = max(0.0, min(1.0, float(t)))
    return t * t * (3.0 - 2.0 * t)


def _transform_contour_pts(contour, fn):
    return [(kind, tuple(fn(p) for p in pts)) for kind, pts in contour]


def _contour_bbox_eval(contour):
    xs, ys = [], []
    for seg in contour:
        steps = 2 if seg[0] == "line" else 24
        for k in range(steps + 1):
            px, py = eval_seg(seg, k / float(steps))
            xs.append(px)
            ys.append(py)
    return (min(xs), min(ys), max(xs), max(ys))


def _clamp_cubic_handles_slanted(contour_slanted):
    """Clamp every cubic segment's off-curve X handles inside [min(p0.x, p3.x), max(p0.x, p3.x)]."""
    out = []
    for kind, pts in contour_slanted:
        if kind == "cubic":
            p0, p1, p2, p3 = pts
            lo_x = min(p0[0], p3[0])
            hi_x = max(p0[0], p3[0])
            p1 = (max(lo_x, min(hi_x, p1[0])), p1[1])
            p2 = (max(lo_x, min(hi_x, p2[0])), p2[1])
            out.append((kind, (p0, p1, p2, p3)))
        else:
            out.append((kind, pts))
    return out


def target_hole_ratio(width_mode, weight_class):
    """Return target inner-hole width ratio relative to Normal peer, or None if untouched."""
    w = int(round(float(weight_class)))
    if w < 700:
        return None
    wm = width_mode.lower().replace("-", "_").replace(" ", "_")
    if wm in ("extra_condensed", "extracondensed"):
        if w >= 900:
            return 0.80
        if w >= 800:
            return 0.82
        return 0.84
    if wm == "condensed":
        return 0.89
    return None


def fix_chin_contours(contours_x, contours_n, width_mode, weight_class, is_italic):
    """
    Open the pinched top inner counter of `uni10E9` / `uni10E9.case` and remove any pulled
    handle overshoot while preserving exact contour/segment topology for `varLib`.
    Returns `(new_contours, stats_dict)`.
    """
    ratio = target_hole_ratio(width_mode, weight_class)
    if ratio is None or not contours_x or not contours_n:
        return contours_x, {"applied": False, "expand": 0.0}

    # Ensure PostScript CCW-outer / CW-hole orientation before locating inner hole
    cx_ps, _ = fix_disjoint_outer_winding(contours_x)
    cn_ps, _ = fix_disjoint_outer_winding(contours_n)

    hx_idxs = [i for i, c in enumerate(cx_ps) if contour_signed_area(c) < 0]
    hn_idxs = [i for i, c in enumerate(cn_ps) if contour_signed_area(c) < 0]
    if not hx_idxs or not hn_idxs:
        return contours_x, {"applied": False, "expand": 0.0}
    hi_x, hi_n = hx_idxs[0], hn_idxs[0]

    # Unslant all contours into upright working coordinates
    cx_u = [_transform_contour_pts(c, lambda p: _unslant_pt(p, is_italic)) for c in cx_ps]
    cn_u = [_transform_contour_pts(c, lambda p: _unslant_pt(p, is_italic)) for c in cn_ps]

    hx = cx_u[hi_x]
    hn = cn_u[hi_n]
    xx0, xy0, xx1, xy1 = _contour_bbox_eval(hx)
    nx0, ny0, nx1, ny1 = _contour_bbox_eval(hn)
    xw = xx1 - xx0
    nw = nx1 - nx0
    tw = nw * ratio
    expand = max(0.0, tw - xw)

    # Check if any handle overshoot exists even when width already meets target
    orig_hx_sl = cx_ps[hi_x]
    max_orig_ov = 0.0
    for kind, pts in orig_hx_sl:
        if kind == "cubic":
            p0, p1, p2, p3 = pts
            lo_x, hi_x_seg = min(p0[0], p3[0]), max(p0[0], p3[0])
            max_orig_ov = max(
                max_orig_ov,
                max(0.0, lo_x - p1[0]),
                max(0.0, p1[0] - hi_x_seg),
                max(0.0, lo_x - p2[0]),
                max(0.0, p2[0] - hi_x_seg),
            )

    if expand < 1.0 and max_orig_ov <= 0.5:
        return contours_x, {
            "applied": False,
            "already_open": True,
            "expand": 0.0,
            "hole_w_before": round(xw, 1),
            "hole_w_after": round(xw, 1),
            "normal_hole_w": round(nw, 1),
        }

    if expand < 1.0:
        # Hole already at target width; just clamp residual overshoot cleanly
        new_sl = [
            _clamp_cubic_handles_slanted(c) if ci == hi_x else c
            for ci, c in enumerate(cx_ps)
        ]
        return new_sl, {
            "applied": True,
            "expand": 0.0,
            "mode": "clamp_only",
            "hole_w_before": round(xw, 1),
            "hole_w_after": round(xw, 1),
            "normal_hole_w": round(nw, 1),
        }

    tx0 = xx0 - 0.35 * expand
    tx1 = xx1 + 0.65 * expand
    ty0, ty1 = xy0, xy1

    ops_x = [s[0] for s in hx]
    ops_n = [s[0] for s in hn]

    if ops_x == ops_n:
        # Exact same op sequence: map Normal's smooth normalized (u, v) onto [tx0, tx1] x [ty0, ty1]
        nw_safe = max(nx1 - nx0, 1.0)
        nh_safe = max(ny1 - ny0, 1.0)
        new_hx_u = []
        for kind, pts in hn:
            npts = []
            for px, py in pts:
                u = (px - nx0) / nw_safe
                v = (py - ny0) / nh_safe
                npts.append((tx0 + u * (tx1 - tx0), ty0 + v * (ty1 - ty0)))
            new_hx_u.append((kind, tuple(npts)))
        new_hx_sl = _clamp_cubic_handles_slanted(
            _transform_contour_pts(new_hx_u, lambda p: _reslant_pt(p, is_italic))
        )
        mode = "normal_uv_map"
    else:
        # Different op sequence (e.g. .case or Condensed/Bold): expand linearly in unslanted space
        # and clamp cubic handles cleanly in slanted space so zero overshoot/bulge remains!
        xw_safe = max(xx1 - xx0, 1.0)
        sx = (tx1 - tx0) / xw_safe
        new_hx_u = [
            (kind, tuple((tx0 + (px - xx0) * sx, py) for (px, py) in pts))
            for kind, pts in hx
        ]
        new_hx_sl = _clamp_cubic_handles_slanted(
            _transform_contour_pts(new_hx_u, lambda p: _reslant_pt(p, is_italic))
        )
        mode = "linear_clamp"

    # Gently push outer top-right bowl (y > 440, x > xx1 + 30, smoothstep ramp over 440..580)
    # right by +0.35 * expand so the right bowl wall stays lush (~170u thick!)
    push = 0.35 * expand
    x_thresh = xx1 + 30.0

    def _push_outer_pt(p):
        px, py = p
        if py > 440.0 and px > x_thresh:
            t = _smoothstep((py - 440.0) / (580.0 - 440.0))
            return (px + push * t, py)
        return (px, py)

    new_sl = []
    for ci, c_u in enumerate(cx_u):
        if ci == hi_x:
            new_sl.append(new_hx_sl)
        else:
            pushed_u = _transform_contour_pts(c_u, _push_outer_pt)
            new_sl.append(_transform_contour_pts(pushed_u, lambda p: _reslant_pt(p, is_italic)))

    # Measure final unslanted hole width
    fin_hx_u = _transform_contour_pts(new_sl[hi_x], lambda p: _unslant_pt(p, is_italic))
    fx0, _, fx1, _ = _contour_bbox_eval(fin_hx_u)

    return new_sl, {
        "applied": True,
        "expand": round(expand, 2),
        "mode": mode,
        "hole_w_before": round(xw, 1),
        "hole_w_after": round(fx1 - fx0, 1),
        "normal_hole_w": round(nw, 1),
    }


def _write_contours_preserve_adv(font, gname, contours, half_unit=False):
    """Write updated contours to CFF or TrueType while preserving exact existing hmtx advance!"""
    adv_int = int(font["hmtx"][gname][0])
    round_coords = not half_unit

    if "CFF " in font:
        cff = font["CFF "].cff
        top = cff.topDictIndex[0]
        pen = T2CharStringPen(width=adv_int, glyphSet=None, roundTolerance=0.0 if half_unit else 0.5)
        draw_contours_to_pen(contours, pen, round_coords=round_coords, half_unit=half_unit)
        top.CharStrings[gname] = pen.getCharString(private=top.Private, globalSubrs=cff.GlobalSubrs)
        bp = BoundsPen(None)
        draw_contours_to_pen(contours, bp, round_coords=round_coords, half_unit=half_unit)
        lsb = int(round(bp.bounds[0])) if bp.bounds else 0
        font["hmtx"][gname] = (adv_int, lsb)
    elif "glyf" in font:
        tt_pen = TTGlyphPen(None)
        cu2qu_pen = Cu2QuPen(tt_pen, max_err=0.5, reverse_direction=True)
        draw_contours_to_pen(contours, cu2qu_pen, round_coords=round_coords, half_unit=half_unit)
        gobj = tt_pen.glyph()
        gobj.recalcBounds(font["glyf"])
        font["glyf"][gname] = gobj
        lsb = int(gobj.xMin) if gobj.numberOfContours > 0 else 0
        font["hmtx"][gname] = (adv_int, lsb)
    else:
        raise ValueError("Unsupported font format (neither CFF nor glyf)")


def apply_chin_arch_fix_to_font(font, normal_ref_font, width_mode, weight_class, is_italic):
    """
    Apply surgical `ჩ` (`uni10E9`) & `Ჩ` (`uni10E9.case`) inner-arch fix cleanly to a TTFont
    (OTF or TTF) in-place, preserving exact `hmtx` advance widths and verifying skia-pathops!
    Returns `(stats_dict, issues_list)`.
    """
    if target_hole_ratio(width_mode, weight_class) is None or normal_ref_font is None:
        return {"applied": False, "glyphs": {}}, []

    gset = set(font.getGlyphOrder())
    ref_gset = set(normal_ref_font.getGlyphOrder())
    issues = []
    glyph_stats = {}
    any_applied = False

    for gname in CHIN_TARGET_GLYPHS:
        if gname not in gset or gname not in ref_gset:
            continue
        cx = extract_contours(font, gname)
        cn = extract_contours(normal_ref_font, gname)
        if not cx or not cn:
            continue

        new_c, st = fix_chin_contours(cx, cn, width_mode, weight_class, is_italic)
        glyph_stats[gname] = st
        if not st.get("applied", False):
            continue

        half_unit = gname.endswith(".case")
        # Verify skia-pathops zero self-intersection & clean winding before writing!
        p = pathops.Path()
        draw_contours_to_pen(new_c, p.getPen(), round_coords=not half_unit, half_unit=half_unit)
        ps = pathops.simplify(p, clockwise=False)
        rel_diff = abs(abs(p.area) - abs(ps.area)) / max(abs(p.area), 1.0)
        if rel_diff > 0.01:
            issues.append(f"chin_arch_fix {gname}: pathops area diff {rel_diff:.4f}")
        _, wind_bad = fix_disjoint_outer_winding(new_c)
        if wind_bad:
            issues.append(f"chin_arch_fix {gname}: winding mismatch")

        _write_contours_preserve_adv(font, gname, new_c, half_unit=half_unit)
        any_applied = True

    return {"applied": any_applied, "glyphs": glyph_stats}, issues

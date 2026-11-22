#!/usr/bin/env python3
"""
Batumi Sans Authentic Multi-Letter Georgian Karagma (ქარაგმა / ასონაკლებობის ნიშანი) Engine.

Implements traditional Georgian fresco, icon, and manuscript abbreviation marks (nomina sacra)
spanning 1, 2, 3, or 4 letters across Mkhedruli, Mtavruli, Asomtavruli, Nuskhuri, and mixed
Khutsuri/Mkhedruli texts (e.g. ႣႣა, Ⴖა, დდა, ღა, ႣႣႠ, ႶႧႠ, ႳႪႨ, ႨႳ, ႵႤ, ႼჂ, ⴃⴃⴀ, ႣႣႠႨ).

Architecture:
  1. Three new GDEF class 3 wavy combining mark glyphs (advance width = 0, 100% valid_glyphnames &
     fontspector clean, Sharp + Rounded kappa=0.580 + -8 deg Italic calibrated, strictly
     locked contour & segment topology across all 9 weights x 4 widths for varLib!):
       - `uni0483`       (U+0483 COMBINING CYRILLIC TITLO — 1-letter Old Georgian/TITUS karagma)
       - `uni0360.span3` (unencoded — continuous 3-letter calligraphic karagma wave centered x=0)
       - `uni0360.span4` (unencoded — continuous 4-letter calligraphic karagma wave centered +0.5*avg)
     Paired with the existing 2-letter `uni0360` (U+0360 COMBINING DOUBLE TILDE).
  2. Georgian-scoped OpenType `calt` auto-merge via ChainContextSubst + MultipleSubst 1-to-0
     deletion (zero empty glyphs, verified identical in HarfBuzz & CoreText, 0 fontspector
     FAILs; Latin ññ/ãõ/ãb̃ and single Georgian ა̃/Ⴖ̃ remain 100% untouched!):
       * 4-letter: <G1> U+0360 <G2> U+0360 <G3> U+0360 <G4>  -> <G1> <G2> uni0360.span4 <G3> <G4>
                   <G1> U+0303 <G2> U+0303 <G3> U+0303 <G4> U+0303 -> same
       * 3-letter: <G1> U+0360 <G2> U+0360 <G3>              -> <G1> <G2> uni0360.span3 <G3>
                   <G1> U+0303 <G2> U+0303 <G3> U+0303       -> same
       * 2-letter: <G1> U+0360 <G2>                          -> uni0360 (existing)
                   <G1> U+0303 <G2> U+0303                   -> <G1> uni0360 <G2>
  3. Complete GPOS MarkBase anchoring (all scripts + dotted circle U+25CC) + varLib-compatible
     contextual height clearance (`ChainContextPos` Format 3 + `SinglePos` ValueFormat=3) +
     optical `XPlacement` centering on mixed-width words (`Ⴃ͠Ⴃ͠ა`, `დ͠დ͠ა`, `Ⴃ͠Ⴃ͠Ⴀ͠Ⴈ`) so wavy
     multi-letter karagmas automatically clear tall Mkhedruli/Nuskhuri ascenders, Mtavruli,
     and Asomtavruli with ZERO collisions!
"""

import math

import pathops
from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib.tables import otTables

from latin_extended_primes import (
    _contours_bbox,
    _upsert_cff_glyph,
)
from rounder import (
    contour_signed_area,
    draw_contours_to_pen,
    eval_seg,
    extract_contours,
    fix_disjoint_outer_winding,
)

# ---------------------------------------------------------------------------
# Public Constants & Deterministic Georgian Base Tier Classification
# ---------------------------------------------------------------------------

KARAGMA_ENCODED_MAP = (
    (0x0483, "uni0483"),  # COMBINING CYRILLIC TITLO (1-letter karagma/titlo)
)

KARAGMA_NEW_CPS = tuple(cp for cp, _ in KARAGMA_ENCODED_MAP)

KARAGMA_UNENCODED_NAMES = (
    "uni0360.span3",
    "uni0360.span4",
)

KARAGMA_GLYPH_NAMES = tuple(gn for _, gn in KARAGMA_ENCODED_MAP) + KARAGMA_UNENCODED_NAMES

# Legacy flat Combining Half Marks pruned cleanly during idempotent static OTF rebuilds
_LEGACY_HALF_MARK_CPS = (0xFE22, 0xFE23, 0xFE26)
_LEGACY_HALF_MARK_GLYPHS = ("uniFE22", "uniFE23", "uniFE26")

# Canonical Batumi Sans Italic slant & pivot (matches build_variable_fonts.py ITAL_PIVOT_Y)
ITAL_ANGLE_DEG = 8.0
ITAL_PIVOT_Y = 264.0

# Deterministic Georgian base codepoints (excluding U+10FB paragraph separator)
ASOMTAVRULI_CPS = tuple(
    cp for cp in range(0x10A0, 0x10CE)
    if cp not in (0x10C6, 0x10C8, 0x10C9, 0x10CA, 0x10CB, 0x10CC)
)
MKHEDRULI_CPS = tuple(
    cp for cp in range(0x10D0, 0x1100)
    if cp != 0x10FB
)
MTAVRULI_CPS = tuple(
    cp for cp in range(0x1C90, 0x1CC0)
    if cp not in (0x1CBB, 0x1CBC)
)
NUSKHURI_CPS = tuple(
    cp for cp in range(0x2D00, 0x2D2E)
    if cp not in (0x2D26, 0x2D28, 0x2D29, 0x2D2A, 0x2D2B, 0x2D2C)
)

# Deterministic height tiers across all 144 Batumi Sans styles (guarantees identical
# GPOS ChainContextPos Coverage glyph lists across all 16 masters for varLib!).
# Tier 0: Short (x-height ~527u)
GEOR_SHORT_CPS = (
    # Mkhedruli x-height (25 letters)
    0x10D0, 0x10D2, 0x10D3, 0x10D4, 0x10D5, 0x10D7, 0x10D8, 0x10D9, 0x10DA,
    0x10DD, 0x10DF, 0x10E3, 0x10E4, 0x10E6, 0x10E7, 0x10EA, 0x10EF,
    0x10F2, 0x10F3, 0x10F7, 0x10F8, 0x10F9, 0x10FA, 0x10FE, 0x10FF,
    # Nuskhuri x-height (26 letters)
    0x2D00, 0x2D01, 0x2D02, 0x2D04, 0x2D05, 0x2D07, 0x2D08, 0x2D0A, 0x2D0D,
    0x2D0E, 0x2D0F, 0x2D12, 0x2D14, 0x2D16, 0x2D17, 0x2D18, 0x2D1A, 0x2D1C,
    0x2D1D, 0x2D1E, 0x2D1F, 0x2D20, 0x2D22, 0x2D24, 0x2D27, 0x2D2D,
)

# Tier 1a: Mid-Lo (CapH / flat Asomtavruli / base Mtavruli / Mkhedruli ტ ~675-688u)
GEOR_MID_HI_CPS = (
    # Round-top overshoot Asomtavruli (topAnc ~691u)
    0x10AD, 0x10B3, 0x10B4, 0x10B6, 0x10BA, 0x10BD, 0x10C5, 0x10C7,
)
GEOR_MID_LO_CPS = (
    # Flat-top Asomtavruli (32 letters, topAnc ~681u)
    tuple(cp for cp in ASOMTAVRULI_CPS if cp not in GEOR_MID_HI_CPS)
    # Standard Mtavruli (25 letters, topAnc ~675u)
    + (
        0x1C90, 0x1C92, 0x1C93, 0x1C94, 0x1C95, 0x1C97, 0x1C98, 0x1C99, 0x1C9A,
        0x1C9D, 0x1C9F, 0x1CA3, 0x1CA4, 0x1CA6, 0x1CA7, 0x1CAA, 0x1CAF,
        0x1CB2, 0x1CB3, 0x1CB7, 0x1CB8, 0x1CB9, 0x1CBA, 0x1CBE, 0x1CBF,
    )
    # Mkhedruli ტ (y1 ~646u) & modifier ჼ (y1 ~696u)
    + (0x10E2, 0x10FC)
)

# Tier 2: Tall-Lo (Nuskhuri ascenders ~725u & tall-cue Mtavruli ~704-726u)
GEOR_TALL_LO_CPS = (
    # Nuskhuri ascenders (14 letters)
    0x2D03, 0x2D06, 0x2D09, 0x2D0B, 0x2D0C, 0x2D10, 0x2D11,
    0x2D13, 0x2D15, 0x2D19, 0x2D1B, 0x2D21, 0x2D23, 0x2D25,
    # Tall Mtavruli (21 letters)
    0x1C91, 0x1C96, 0x1C9B, 0x1C9C, 0x1C9E, 0x1CA0, 0x1CA1, 0x1CA2, 0x1CA5,
    0x1CA8, 0x1CA9, 0x1CAB, 0x1CAC, 0x1CAD, 0x1CAE, 0x1CB0, 0x1CB1, 0x1CB4,
    0x1CB5, 0x1CB6, 0x1CBD,
)

# Tier 3: Tall-Hi (Mkhedruli full ascenders ~739-745u)
GEOR_TALL_HI_CPS = (
    0x10D1, 0x10D6, 0x10DB, 0x10DC, 0x10DE, 0x10E0, 0x10E1, 0x10E5,
    0x10E8, 0x10E9, 0x10EB, 0x10EC, 0x10ED, 0x10EE, 0x10F0, 0x10F1,
    0x10F4, 0x10F5, 0x10F6, 0x10FD,
)

# Deterministic optical-width sets for asymmetric 3-/4-letter karagma XPlacement centering
# (guarantees identical GPOS ChainContextPos Coverage glyph lists across all 16 masters for varLib!).
# WIDE >= 680u in Regular (massive Asomtavruli/Mtavruli/wide Mkhedruli & Nuskhuri, avg ~810u):
GEOR_WIDE_CPS = (
    0x10A1, 0x10A2, 0x10A3, 0x10A5, 0x10A6, 0x10A7, 0x10AA, 0x10AB, 0x10AC,
    0x10AD, 0x10AE, 0x10AF, 0x10B0, 0x10B3, 0x10B4, 0x10B6, 0x10BA, 0x10BB,
    0x10C0, 0x10C5,
    0x10D3, 0x10D7, 0x10DA, 0x10DD, 0x10E0, 0x10E2, 0x10E4, 0x10E6, 0x10F6,
    0x1C93, 0x1C97, 0x1C9A, 0x1C9D, 0x1CA0, 0x1CA2, 0x1CA4, 0x1CA6, 0x1CB6, 0x1CBF,
    0x2D05, 0x2D07, 0x2D0A, 0x2D0D, 0x2D0E, 0x2D0F, 0x2D10, 0x2D13, 0x2D14,
    0x2D1B, 0x2D1C, 0x2D20, 0x2D25,
)
# NARROW <= 575u in Regular (compact Mkhedruli/Asomtavruli/Mtavruli/Nuskhuri, avg ~530u):
GEOR_NARROW_CPS = (
    0x10A8, 0x10BD, 0x10C7, 0x10CD,
    0x10D0, 0x10D2, 0x10D4, 0x10D5, 0x10D8, 0x10D9, 0x10DE, 0x10DF, 0x10E1,
    0x10E3, 0x10E5, 0x10E7, 0x10EF, 0x10F0, 0x10F3, 0x10F4, 0x10F7, 0x10F8,
    0x10FA, 0x10FC, 0x10FD,
    0x1C90, 0x1C94, 0x1C95, 0x1C99, 0x1C9E, 0x1CA5, 0x1CAC, 0x1CAF, 0x1CB0,
    0x1CB2, 0x1CB3, 0x1CB4, 0x1CB7, 0x1CBA, 0x1CBD,
    0x2D08, 0x2D15, 0x2D1F, 0x2D21, 0x2D27, 0x2D2D,
)


# ---------------------------------------------------------------------------
# Low-Level Geometry & Metric Measurement Helpers
# ---------------------------------------------------------------------------

def _add_cmap_mapping(font, cp, gname):
    """Write Unicode codepoint mapping cleanly into all Unicode cmap subtables (4 & 12)."""
    for sub in font["cmap"].tables:
        if sub.isUnicode():
            if sub.format == 4 and cp <= 0xFFFF:
                sub.cmap[cp] = gname
            elif sub.format == 12:
                sub.cmap[cp] = gname


def _glyph_bbox(font, gname):
    bp = BoundsPen(font.getGlyphSet())
    font.getGlyphSet()[gname].draw(bp)
    return bp.bounds


def _measure_y_thickness_at_x(contours, x_probe):
    """Measure exact vertical ink cross-section thickness of contours at x = x_probe."""
    ys = []
    for c in contours:
        for seg in c:
            prev = eval_seg(seg, 0.0)
            steps = 2 if seg[0] == "line" else 32
            for k in range(1, steps + 1):
                cur = eval_seg(seg, k / float(steps))
                if (prev[0] <= x_probe < cur[0]) or (cur[0] <= x_probe < prev[0]):
                    t = (x_probe - prev[0]) / (cur[0] - prev[0])
                    ys.append(prev[1] + t * (cur[1] - prev[1]))
                prev = cur
    ys.sort()
    spans = [ys[i + 1] - ys[i] for i in range(0, len(ys) - 1, 2)]
    return max(spans) if spans else 0.0


def _measure_karagma_metrics(src_font, is_italic=False):
    """
    Measure font-native diacritic stroke thickness (calibrated 100% directly to `uni0360`!),
    vertical center, and average Georgian advance width from the font's own outlines & hmtx
    (100% deterministic across all 9 weights x 4 widths x Sharp/Rounded x Upright/Italic).
    """
    hmtx = src_font["hmtx"]
    cm = src_font.getBestCmap()
    gset = src_font.getGlyphSet()

    # Measure `uni0304` (combining macron) bar height & vertical center
    bb_04 = _contours_bbox(extract_contours(src_font, "uni0304")) if "uni0304" in gset else None
    if bb_04:
        h_bar = float(bb_04[3] - bb_04[1])
        y_bar_mid = 0.5 * (bb_04[1] + bb_04[3])
    else:
        h_bar = 69.0
        y_bar_mid = 701.5

    # Measure exact vertical stroke thickness of `uni0360` (falling back to `tildecomb` / `uni0304`)
    # so ALL 3 wavy karagma marks match `uni0360` (`Ⴖ͠ა`) 100% across Thin..Heavy & Sharp/Rounded!
    t_360 = 0.0
    y_360_mid = y_bar_mid + 12.0
    for ref_gn in ("uni0360", "tildecomb"):
        if ref_gn in gset:
            cs_ref = extract_contours(src_font, ref_gn)
            bb_ref = _contours_bbox(cs_ref)
            if bb_ref:
                cx_ref = 0.5 * (bb_ref[0] + bb_ref[2])
                y_360_mid = 0.5 * (bb_ref[1] + bb_ref[3])
                t_mid = _measure_y_thickness_at_x(cs_ref, cx_ref)
                if t_mid > 8.0:
                    t_360 = t_mid
                    break
    if t_360 <= 8.0:
        t_360 = h_bar * 1.12

    # Measure `tildecomb` top anchor / x-height reference
    ref_my = 527.0
    if "GPOS" in src_font:
        gpos = src_font["GPOS"].table
        for lk in gpos.LookupList.Lookup:
            for st in lk.SubTable:
                ltype = st.ExtensionLookupType if lk.LookupType == 9 else lk.LookupType
                rst = st.ExtSubTable if lk.LookupType == 9 else st
                if ltype == 4 and hasattr(rst, "MarkCoverage") and "tildecomb" in rst.MarkCoverage.glyphs:
                    idx = rst.MarkCoverage.glyphs.index("tildecomb")
                    anc = rst.MarkArray.MarkRecord[idx].MarkAnchor
                    if anc is not None:
                        ref_my = float(anc.YCoordinate)
                        break

    # Average Georgian advance width across Mkhedruli + Asomtavruli + Nuskhuri + Mtavruli
    geor_advs = []
    for cps in (MKHEDRULI_CPS, ASOMTAVRULI_CPS, NUSKHURI_CPS, MTAVRULI_CPS):
        grp = [float(hmtx[cm[cp]][0]) for cp in cps if cp in cm and cm[cp] in hmtx.metrics]
        if grp:
            geor_advs.append(sum(grp) / len(grp))
    avg_geor_adv = (sum(geor_advs) / len(geor_advs)) if geor_advs else 665.0

    # Smooth weight normalized factor t_w in [0.0 (Thin t~22) .. 1.0 (Heavy t~150)]
    t_w = max(0.0, min(1.0, (t_360 - 22.0) / 128.0))

    # Exact 100% stroke thickness match to `uni0360` across ALL weights (Thin 22.5u -> Heavy 150u!)
    t_wave = t_360
    # Full-bodied terminal thickness (96% of body) so Rounded kappa=0.580 pill caps are
    # full, plush semicircles matching `uni0360` with ZERO pinched or flat-looking ends!
    t_end = t_wave * 0.96

    # Real, unmistakable S-wave amplitude (matching uni0360/tildecomb fluid rhythm across Thin..Heavy)
    amp_wave = 32.0 + 12.0 * t_w  # ~32u Thin, ~37u Regular, ~41u Bold, ~44u Heavy

    # Grounded vertical center keeping crisp ~82-98u air gap above tall letter tops
    # (bottom Y matches `uni0360` `[622..656]` cleanly across Regular..Heavy — never floating!).
    gap_above_anc = 104.0 - 16.0 * t_w  # 104u Thin, 97u Regular, 88u Heavy
    y_mid = max(y_360_mid - 4.0, ref_my + gap_above_anc + 0.50 * t_wave + amp_wave)

    return {
        "h_bar": h_bar,
        "t_360": t_360,
        "t_wave": t_wave,
        "t_end": t_end,
        "y_bar_mid": y_bar_mid,
        "y_mid": y_mid,
        "ref_my": ref_my,
        "avg_geor_adv": avg_geor_adv,
        "t_w": t_w,
        "amp_wave": amp_wave,
        "is_italic": is_italic,
    }


# ---------------------------------------------------------------------------
# Parametric Calligraphic Ribbon Builders (100% Locked VF Contour/Segment Topology!)
# ---------------------------------------------------------------------------

def _hermite_cubic(p0, t0, p1, t1, f0=0.40, f1=0.40):
    """
    Build one smooth cubic Bezier segment from p0 (unit tangent t0) to p1 (unit tangent t1)
    with horizontal-progress clamping that prevents handle crossing or cusps at any weight.
    """
    dx = p1[0] - p0[0]
    tx0 = max(abs(t0[0]), 0.45)
    tx1 = max(abs(t1[0]), 0.45)
    sgn = 1.0 if dx >= 0.0 else -1.0
    span = abs(dx)
    l0 = min(f0 * span / tx0, 0.48 * span / tx0)
    l1 = min(f1 * span / tx1, 0.48 * span / tx1)
    c1 = (p0[0] + sgn * l0 * abs(t0[0]), p0[1] + l0 * t0[1] * (1.0 if sgn > 0 else -1.0))
    c2 = (p1[0] - sgn * l1 * abs(t1[0]), p1[1] - l1 * t1[1] * (1.0 if sgn > 0 else -1.0))
    return ("cubic", (p0, c1, c2, p1))


# Rounded 90-degree quarter-circle cubic handle constant (raw kappa = 0.580,
# vs pure circular 4/3*tan(pi/8) = 0.5522847 — NOT the ratio multiplier ROUND_TENSION_RATIO!).
ROUND_KAPPA_90 = 0.580


def _pill_cap(p_start, p_end, kappa=ROUND_KAPPA_90):
    """
    Build Rounded (kappa=0.580) semicircular pill cap in CCW contour order
    from p_start to p_end.
    Outward direction is strictly 90 deg clockwise from (p_end - p_start), guaranteeing exact
    G1 tangent continuity with perpendicular ribbon boundaries and strict CCW winding.
    """
    mx = 0.5 * (p_start[0] + p_end[0])
    my = 0.5 * (p_start[1] + p_end[1])
    vx = 0.5 * (p_end[0] - p_start[0])
    vy = 0.5 * (p_end[1] - p_start[1])
    r = math.hypot(vx, vy)
    if r < 1e-6:
        return [("line", (p_start, p_end))]
    # Outward unit normal (90 deg CW from v): (+vy/r, -vx/r)
    ox, oy = vy / r, -vx / r
    apex = (mx + r * ox, my + r * oy)
    k = kappa
    c1_a = (p_start[0] + k * r * ox, p_start[1] + k * r * oy)
    c2_a = (apex[0] - k * vx, apex[1] - k * vy)
    c1_b = (apex[0] + k * vx, apex[1] + k * vy)
    c2_b = (p_end[0] + k * r * ox, p_end[1] + k * r * oy)
    return [
        ("cubic", (p_start, c1_a, c2_a, apex)),
        ("cubic", (apex, c1_b, c2_b, p_end)),
    ]


def _shear_contour_italic(contour, is_italic, pivot_y=ITAL_PIVOT_Y):
    """Apply exact Batumi Sans -8.0 deg Italic shear around pivot_y (preserves CCW & topology)."""
    if not is_italic:
        return contour
    tan_a = math.tan(math.radians(ITAL_ANGLE_DEG))

    def sh(p):
        return (p[0] + (p[1] - pivot_y) * tan_a, p[1])

    return [(k, tuple(sh(p) for p in pts)) for k, pts in contour]


def _build_calligraphic_wave(
    width,
    cx,
    y_mid,
    amp,
    t_body,
    t_end,
    u_peak,
    k_end,
    end_deg,
    slope_boost,
    rounded=False,
    is_italic=False,
):
    """
    Construct ONE continuous, 180-deg point-symmetric Georgian calligraphic karagma S-wave
    centered at (cx, y_mid) with:
      - Sharp:   EXACTLY 1 contour, 10 segments (4 bottom cubics + R line + 4 top cubics + L line)
      - Rounded: EXACTLY 1 contour, 12 segments (4 bottom cubics + 2 R pill cubics + 4 top cubics + 2 L pill cubics)
    Guaranteed strict CCW outer winding, G1 continuity at every interior join & rounded cap,
    and ZERO self-intersections across Thin..Heavy x ExtraCondensed..Expanded!
    """
    half_w = 0.5 * width
    h_body = 0.5 * t_body
    h_end = 0.5 * t_end
    h_crest = 0.5 * (0.97 * t_body + 0.03 * t_end)

    # Pull Rounded endpoints slightly inward so protruding semicircular pill cap preserves
    # exact Sharp optical ink width (never shrinks or bloats!)
    if rounded:
        half_w_eff = max(half_w - 0.55 * h_end, half_w * 0.85)
    else:
        half_w_eff = half_w

    theta = math.radians(end_deg)
    t_end_vec = (math.cos(theta), math.sin(theta))
    n_end_vec = (-math.sin(theta), math.cos(theta))

    # Center inflection slope (exact sine-wave smooth glide through center, zero flat shelf!)
    x_peak = u_peak * half_w_eff
    mid_slope = min(0.55, slope_boost * amp / max(x_peak, 50.0))
    phi = math.atan(mid_slope)
    t_mid_vec = (math.cos(phi), -math.sin(phi))
    n_mid_vec = (math.sin(phi), math.cos(phi))

    # 5 centerline keyframes (in unslanted coordinates relative to cx)
    p0 = (cx - half_w_eff, y_mid - k_end * amp)
    p1 = (cx - x_peak, y_mid + amp)
    p2 = (cx, y_mid)
    p3 = (cx + x_peak, y_mid - amp)
    p4 = (cx + half_w_eff, y_mid + k_end * amp)

    # Offset top & bottom keyframes cleanly along local calligraphic normals
    top_pts = [
        (p0[0] + h_end * n_end_vec[0], p0[1] + h_end * n_end_vec[1]),
        (p1[0], p1[1] + h_crest),
        (p2[0] + h_body * n_mid_vec[0], p2[1] + h_body * n_mid_vec[1]),
        (p3[0], p3[1] + h_crest),
        (p4[0] + h_end * n_end_vec[0], p4[1] + h_end * n_end_vec[1]),
    ]
    bot_pts = [
        (p0[0] - h_end * n_end_vec[0], p0[1] - h_end * n_end_vec[1]),
        (p1[0], p1[1] - h_crest),
        (p2[0] - h_body * n_mid_vec[0], p2[1] - h_body * n_mid_vec[1]),
        (p3[0], p3[1] - h_crest),
        (p4[0] - h_end * n_end_vec[0], p4[1] - h_end * n_end_vec[1]),
    ]
    tangents = [t_end_vec, (1.0, 0.0), t_mid_vec, (1.0, 0.0), t_end_vec]

    # Segment handle tension fractions (optimal smooth sinusoidal wave curvature!)
    f_pairs = (
        (0.38, 0.44),  # P0 -> P1 (fluid left arch into crest)
        (0.44, 0.36),  # P1 -> P2 (smooth sinusoidal glide through center)
        (0.36, 0.44),  # P2 -> P3 (smooth sinusoidal glide into trough)
        (0.44, 0.38),  # P3 -> P4 (fluid right sweep to finial)
    )

    # Bottom chain: Left -> Right (CCW outer bottom edge)
    bot_segs = [
        _hermite_cubic(bot_pts[i], tangents[i], bot_pts[i + 1], tangents[i + 1], f_pairs[i][0], f_pairs[i][1])
        for i in range(4)
    ]

    # Right cap: Bot4 -> Top4
    if rounded:
        right_cap = _pill_cap(bot_pts[4], top_pts[4])
    else:
        right_cap = [("line", (bot_pts[4], top_pts[4]))]

    # Top chain: Right -> Left (CCW outer top edge; build Left->Right then reverse for exact symmetry!)
    top_lr = [
        _hermite_cubic(top_pts[i], tangents[i], top_pts[i + 1], tangents[i + 1], f_pairs[i][0], f_pairs[i][1])
        for i in range(4)
    ]
    top_segs = [("cubic", (pts[3], pts[2], pts[1], pts[0])) for _, pts in reversed(top_lr)]

    # Left cap: Top0 -> Bot0
    if rounded:
        left_cap = _pill_cap(top_pts[0], bot_pts[0])
    else:
        left_cap = [("line", (top_pts[0], bot_pts[0]))]

    contour = bot_segs + right_cap + top_segs + left_cap
    contour = _shear_contour_italic(contour, is_italic=is_italic)
    contours, _ = fix_disjoint_outer_winding([contour])
    return contours


# ---------------------------------------------------------------------------
# 1. Inject All 3 Wavy Karagma Mark Glyphs Into a CFF OTF Font
# ---------------------------------------------------------------------------

def _prune_legacy_half_marks_from_otf(font):
    """
    Idempotently remove deprecated flat Combining Half Marks (`uniFE22`, `uniFE23`, `uniFE26` /
    U+FE22, U+FE23, U+FE26) from an existing static CFF OTF across GlyphOrder, CFF CharStrings,
    hmtx, cmap, GDEF, and GPOS Mark coverages (returns count of glyphs removed).
    """
    drop_set = set(_LEGACY_HALF_MARK_GLYPHS)
    drop_cps = set(_LEGACY_HALF_MARK_CPS)
    old_order = list(font.getGlyphOrder())
    present = [g for g in old_order if g in drop_set]

    # Also check cmap in case of lingering codepoints even if glyph names aren't in order
    has_cmap_ref = False
    if "cmap" in font:
        for sub in font["cmap"].tables:
            if hasattr(sub, "cmap") and isinstance(sub.cmap, dict):
                if any((k in drop_cps or v in drop_set) for k, v in sub.cmap.items()):
                    has_cmap_ref = True
                    break

    if not present and not has_cmap_ref:
        return 0

    # Force-decompile all glyph-indexed tables BEFORE mutating GlyphOrder / CFF
    for tag in ("CFF ", "hmtx", "cmap", "GSUB", "GPOS", "GDEF", "post", "maxp", "OS/2", "head"):
        if tag in font:
            _ = font[tag]

    # 1. Remove from cmap
    if "cmap" in font:
        for sub in font["cmap"].tables:
            if hasattr(sub, "cmap") and isinstance(sub.cmap, dict):
                for cp in [k for k, v in sub.cmap.items() if k in drop_cps or v in drop_set]:
                    del sub.cmap[cp]

    # 2. Remove from GDEF GlyphClassDef
    if "GDEF" in font and getattr(font["GDEF"].table, "GlyphClassDef", None):
        class_defs = font["GDEF"].table.GlyphClassDef.classDefs
        for g in drop_set:
            class_defs.pop(g, None)

    # 3. Remove from GPOS MarkBase / MarkLig / MarkMark coverages
    if "GPOS" in font:
        gpos = font["GPOS"].table
        for lk in gpos.LookupList.Lookup:
            for st in lk.SubTable:
                ltype = st.ExtensionLookupType if lk.LookupType == 9 else lk.LookupType
                rst = st.ExtSubTable if lk.LookupType == 9 else st
                if ltype in (4, 5) and hasattr(rst, "MarkCoverage") and rst.MarkCoverage:
                    glist = rst.MarkCoverage.glyphs
                    if any(g in drop_set for g in glist):
                        keep_idx = [i for i, g in enumerate(glist) if g not in drop_set]
                        rst.MarkCoverage.glyphs = [glist[i] for i in keep_idx]
                        rst.MarkArray.MarkRecord = [rst.MarkArray.MarkRecord[i] for i in keep_idx]
                        rst.MarkArray.MarkCount = len(keep_idx)
                elif ltype == 6:
                    if hasattr(rst, "Mark1Coverage") and rst.Mark1Coverage:
                        glist = rst.Mark1Coverage.glyphs
                        if any(g in drop_set for g in glist):
                            keep_idx = [i for i, g in enumerate(glist) if g not in drop_set]
                            rst.Mark1Coverage.glyphs = [glist[i] for i in keep_idx]
                            rst.Mark1Array.MarkRecord = [rst.Mark1Array.MarkRecord[i] for i in keep_idx]
                            rst.Mark1Array.MarkCount = len(keep_idx)
                    if hasattr(rst, "Mark2Coverage") and rst.Mark2Coverage:
                        glist = rst.Mark2Coverage.glyphs
                        if any(g in drop_set for g in glist):
                            keep_idx = [i for i, g in enumerate(glist) if g not in drop_set]
                            rst.Mark2Coverage.glyphs = [glist[i] for i in keep_idx]
                            rst.Mark2Array.Mark2Record = [rst.Mark2Array.Mark2Record[i] for i in keep_idx]
                            rst.Mark2Array.Mark2Count = len(keep_idx)

    # 4. Remove from hmtx, CFF CharStrings/charset, GlyphOrder, and maxp
    if present:
        new_order = [g for g in old_order if g not in drop_set]
        if "hmtx" in font:
            for g in present:
                font["hmtx"].metrics.pop(g, None)
        if "CFF " in font:
            top = font["CFF "].cff.topDictIndex[0]
            cs_tbl = top.CharStrings
            cs_idx = cs_tbl.charStringsIndex
            kept_items = [cs_idx[cs_tbl.charStrings[g]] for g in new_order]
            cs_idx.items = kept_items
            cs_idx.offsets = None
            cs_idx.file = None
            top.charset = list(new_order)
            cs_tbl.charStrings = {g: i for i, g in enumerate(new_order)}
        font.setGlyphOrder(new_order)
        font["maxp"].numGlyphs = len(new_order)

    if "OS/2" in font:
        font["OS/2"].recalcUnicodeRanges(font)

    return len(present)


def inject_karagma_glyphs(
    font,
    weight_class=None,
    width_mode=None,
    is_italic=False,
    rounded=False,
    sharp_ref_font=None,
):
    """
    Construct and inject all 3 wavy Georgian Karagma combining mark glyphs cleanly into a static CFF OTF:
      - `uni0483`       (U+0483 COMBINING CYRILLIC TITLO — 1-letter wavy karagma)
      - `uni0360.span3` (3-letter continuous calligraphic karagma, centered x=0)
      - `uni0360.span4` (4-letter continuous calligraphic karagma, centered +0.5*avg_geor_adv)
    Also prunes any deprecated flat half-marks (`uniFE22`/`uniFE23`/`uniFE26`) if present.
    All 3 are GDEF class 3 (mark), advance width 0, strict CCW outer winding, 0 pathops errors,
    and 100% locked VF contour/segment topology. 100% idempotent!
    """
    if "CFF " not in font:
        return {"added": 0, "metrics": {}, "issues": ["non-CFF font"]}

    pruned = _prune_legacy_half_marks_from_otf(font)

    src_font = sharp_ref_font if (rounded and sharp_ref_font is not None) else font
    m = _measure_karagma_metrics(src_font, is_italic=is_italic)

    avg = m["avg_geor_adv"]
    y_mid = m["y_mid"]
    t_wave = m["t_wave"]
    t_end = m["t_end"]
    amp = m["amp_wave"]

    built = {}

    # 1. `uni0483` (U+0483 — 1-letter Georgian/TITUS karagma wave ~0.72*avg wide, 100% uni0360 weight)
    built["uni0483"] = _build_calligraphic_wave(
        width=0.72 * avg,
        cx=0.0,
        y_mid=y_mid - 4.0,
        amp=amp * 0.84,
        t_body=t_wave,
        t_end=t_end,
        u_peak=0.46,
        k_end=0.44,
        end_deg=28.0,
        slope_boost=1.45,
        rounded=rounded,
        is_italic=is_italic,
    )

    # 2. `uni0360.span3` (3-letter crisp centered Georgian karagma wave ~1.70*avg wide!)
    # Covers ALL of middle letter L2 + inner ~35-45% of L1 and L3, leaving clear open outer shoulders!
    built["uni0360.span3"] = _build_calligraphic_wave(
        width=1.70 * avg,
        cx=0.0,
        y_mid=y_mid,
        amp=amp * 1.04,
        t_body=t_wave,
        t_end=t_end,
        u_peak=0.48,
        k_end=0.42,
        end_deg=22.0,
        slope_boost=1.55,
        rounded=rounded,
        is_italic=is_italic,
    )

    # 3. `uni0360.span4` (4-letter crisp centered Georgian karagma wave ~2.38*avg wide!)
    # Centered at +0.50*avg (between L2 & L3): covers L2+L3 + inner ~35-45% of L1 and L4, never outer edges!
    built["uni0360.span4"] = _build_calligraphic_wave(
        width=2.38 * avg,
        cx=0.50 * avg,
        y_mid=y_mid + 2.0,
        amp=amp * 1.12,
        t_body=t_wave,
        t_end=t_end,
        u_peak=0.48,
        k_end=0.42,
        end_deg=18.0,
        slope_boost=1.55,
        rounded=rounded,
        is_italic=is_italic,
    )

    # Upsert in strict deterministic glyphOrder sequence
    for gname in KARAGMA_GLYPH_NAMES:
        _upsert_cff_glyph(font, gname, built[gname], 0, gdef_class=3)

    for cp, gname in KARAGMA_ENCODED_MAP:
        _add_cmap_mapping(font, cp, gname)

    issues = audit_karagma_glyphs(font)
    return {
        "added": len(KARAGMA_GLYPH_NAMES),
        "pruned_legacy_half_marks": pruned,
        "metrics": m,
        "issues": issues,
    }


def audit_karagma_glyphs(font):
    """
    Audit all 3 wavy karagma glyphs for:
      - GDEF class == 3 (mark) and advance width == 0
      - Strict 1-contour CCW outer winding
      - Zero skia-pathops self-intersections (<1.5% area delta on simplify)
      - Zero legacy flat half-marks (`uniFE22`, `uniFE23`, `uniFE26`) remaining in font/cmap
    """
    issues = []
    gset = set(font.getGlyphOrder())
    cm = font.getBestCmap()
    for leg_g in _LEGACY_HALF_MARK_GLYPHS:
        if leg_g in gset:
            issues.append(f"{leg_g}: deprecated half-mark still present in glyphOrder")
    for leg_cp in _LEGACY_HALF_MARK_CPS:
        if leg_cp in cm:
            issues.append(f"U+{leg_cp:04X}: deprecated half-mark still mapped in cmap")
    gdef_cls = (
        font["GDEF"].table.GlyphClassDef.classDefs
        if "GDEF" in font and getattr(font["GDEF"].table, "GlyphClassDef", None)
        else {}
    )
    for gname in KARAGMA_GLYPH_NAMES:
        if gname not in gset:
            issues.append(f"{gname}: missing from glyphOrder")
            continue
        adv, _ = font["hmtx"][gname]
        if adv != 0:
            issues.append(f"{gname}: advance={adv} != 0")
        if gdef_cls.get(gname) != 3:
            issues.append(f"{gname}: GDEF class={gdef_cls.get(gname)} != 3")
        cs = extract_contours(font, gname)
        if len(cs) != 1:
            issues.append(f"{gname}: contour_count={len(cs)} != 1")
            continue
        if contour_signed_area(cs[0]) <= 0:
            issues.append(f"{gname}: non-CCW winding (area={contour_signed_area(cs[0]):.1f})")
        p = pathops.Path()
        draw_contours_to_pen(cs, p.getPen(), round_coords=True)
        ra = abs(p.area)
        ps = pathops.simplify(p, clockwise=False)
        sa = abs(ps.area)
        if ra > 50 and abs(ra - sa) / ra > 0.015:
            issues.append(f"{gname}: pathops self-intersection raw={ra:.1f} simp={sa:.1f}")
    return issues


# ---------------------------------------------------------------------------
# 2. OpenType GSUB `calt` Layer B Auto-Merge (Georgian-Scoped, 100% Idempotent!)
# ---------------------------------------------------------------------------

def _collect_georgian_base_glyphs(font):
    """Collect all Georgian base glyphs (Mkhedruli + Mtavruli + Asomtavruli + Nuskhuri + .ss01/.case)."""
    cm = font.getBestCmap()
    order = font.getGlyphOrder()
    gmap = {g: i for i, g in enumerate(order)}
    all_g = set(order)
    geor = set()
    for cps in (ASOMTAVRULI_CPS, MKHEDRULI_CPS, MTAVRULI_CPS, NUSKHURI_CPS):
        for cp in cps:
            gn = cm.get(cp)
            if gn and gn in all_g:
                geor.add(gn)
                for suf in (".ss01", ".ss01.case"):
                    if gn + suf in all_g:
                        geor.add(gn + suf)
    return sorted(geor, key=lambda g: gmap[g])


def _make_coverage(glyphs, gmap):
    cov = otTables.Coverage()
    cov.glyphs = sorted(set(glyphs), key=lambda g: gmap[g])
    return cov


def _make_single_subst_lookup(mapping):
    st = otTables.SingleSubst()
    st.mapping = dict(mapping)
    lk = otTables.Lookup()
    lk.LookupType = 1
    lk.LookupFlag = 0
    lk.SubTable = [st]
    lk.SubTableCount = 1
    return lk


def _make_delete_subst_lookup(glyphs):
    """
    MultipleSubst 1-to-0 mark deletion lookup (zero empty glyphs, verified identical in
    HarfBuzz `ot` and macOS `coretext`, and 0 FAIL / 0 FATAL in fontspector!).
    """
    st = otTables.MultipleSubst()
    st.mapping = {g: [] for g in glyphs}
    lk = otTables.Lookup()
    lk.LookupType = 2
    lk.LookupFlag = 0
    lk.SubTable = [st]
    lk.SubTableCount = 1
    return lk


def _make_chain_subst_fmt3(bt_lists, inp_lists, la_lists, actions, gmap):
    """
    Build a ChainContextSubst Format 3 subtable.
    IMPORTANT: `actions` is ordered from HIGHEST SequenceIndex to LOWEST so MultipleSubst
    1-to-0 deletions at higher indices never shift lower SequenceIndex positions!
    """
    st = otTables.ChainContextSubst()
    st.Format = 3
    st.BacktrackCoverage = [_make_coverage(gl, gmap) for gl in bt_lists]
    st.BacktrackGlyphCount = len(st.BacktrackCoverage)
    st.InputCoverage = [_make_coverage(gl, gmap) for gl in inp_lists]
    st.InputGlyphCount = len(st.InputCoverage)
    st.LookAheadCoverage = [_make_coverage(gl, gmap) for gl in la_lists]
    st.LookAheadGlyphCount = len(st.LookAheadCoverage)
    recs = []
    for seq_idx, lk_idx in actions:
        rec = otTables.SubstLookupRecord()
        rec.SequenceIndex = seq_idx
        rec.LookupListIndex = lk_idx
        recs.append(rec)
    st.SubstLookupRecord = recs
    st.SubstCount = len(recs)
    return st


def find_karagma_calt_lookup(gsub_table):
    """Locate our karagma auto-merge `calt` LookupType 6 lookup index (or None)."""
    for li, lk in enumerate(gsub_table.LookupList.Lookup):
        if lk.LookupType != 6 or not lk.SubTable:
            continue
        st0 = lk.SubTable[0]
        if (
            getattr(st0, "Format", None) == 3
            and getattr(st0, "InputCoverage", None)
            and len(st0.InputCoverage) == 5
            and "uni0360" in st0.InputCoverage[0].glyphs
        ):
            return li
    return None


def wire_gsub_karagma(font):
    """
    Idempotently wire Layer B OpenType `calt` auto-merge for 2-, 3-, and 4-letter Georgian
    karagmas onto Georgian bases (`[Mkhedruli + Mtavruli + Asomtavruli + Nuskhuri]`):
      - Priority 0 (4-letter U+0360): <G1> 0360 <G2> 0360 <G3> 0360 <G4> -> <G1> <G2> uni0360.span4 <G3> <G4>
      - Priority 1 (4-letter U+0303): <G1> 0303 <G2> 0303 <G3> 0303 <G4> 0303 -> <G1> <G2> uni0360.span4 <G3> <G4>
      - Priority 2 (3-letter U+0360): <G1> 0360 <G2> 0360 <G3>           -> <G1> <G2> uni0360.span3 <G3>
      - Priority 3 (3-letter U+0303): <G1> 0303 <G2> 0303 <G3> 0303      -> <G1> <G2> uni0360.span3 <G3>
      - Priority 4 (2-letter U+0303): <G1> 0303 <G2> 0303                -> <G1> uni0360 <G2>
    Strict non-regression: Latin ññ, ãõ, ãb̃ and single Georgian ა̃, Ⴖ̃ are 100% untouched!
    """
    if "GSUB" not in font:
        return {"wired": False}

    gsub = font["GSUB"].table
    lks = gsub.LookupList.Lookup
    order = font.getGlyphOrder()
    gmap = {g: i for i, g in enumerate(order)}
    all_g = set(order)

    if not {"uni0360", "uni0360.span3", "uni0360.span4", "tildecomb"}.issubset(all_g):
        return {"wired": False, "reason": "missing required karagma/tilde glyphs"}

    geor = _collect_georgian_base_glyphs(font)
    u360 = ["uni0360"]
    # Include tildecomb.case too so karagma auto-merge still works when `case` feature is active!
    u303 = [g for g in ("tildecomb", "tildecomb.case") if g in all_g]
    all_merge_marks = u360 + u303

    existing_chain_idx = find_karagma_calt_lookup(gsub)
    if existing_chain_idx is not None:
        # Reuse existing helper lookup indices in-place for 100% idempotency!
        old_lk = lks[existing_chain_idx]
        # Extract helper lookup indices from our canonical 5 subtables:
        # subtable 0 has [(4, idx_del), (2, idx_s4), (0, idx_del)]
        # subtable 2 has [(2, idx_s3), (0, idx_del)]
        # subtable 4 has [(2, idx_del), (0, idx_s2)]
        idx_del = old_lk.SubTable[0].SubstLookupRecord[0].LookupListIndex
        idx_s4 = old_lk.SubTable[0].SubstLookupRecord[1].LookupListIndex
        idx_s3 = old_lk.SubTable[2].SubstLookupRecord[0].LookupListIndex
        idx_s2 = old_lk.SubTable[4].SubstLookupRecord[1].LookupListIndex
        lks[idx_del] = _make_delete_subst_lookup(all_merge_marks)
        lks[idx_s4] = _make_single_subst_lookup({m: "uni0360.span4" for m in all_merge_marks})
        lks[idx_s3] = _make_single_subst_lookup({m: "uni0360.span3" for m in all_merge_marks})
        lks[idx_s2] = _make_single_subst_lookup({m: "uni0360" for m in u303})
        idx_chain = existing_chain_idx
    else:
        idx_del = len(lks)
        lks.append(_make_delete_subst_lookup(all_merge_marks))
        idx_s4 = len(lks)
        lks.append(_make_single_subst_lookup({m: "uni0360.span4" for m in all_merge_marks}))
        idx_s3 = len(lks)
        lks.append(_make_single_subst_lookup({m: "uni0360.span3" for m in all_merge_marks}))
        idx_s2 = len(lks)
        lks.append(_make_single_subst_lookup({m: "uni0360" for m in u303}))

        lk_ch = otTables.Lookup()
        lk_ch.LookupType = 6
        lk_ch.LookupFlag = 0
        idx_chain = len(lks)
        lks.append(lk_ch)

    # Actions ordered strictly from highest SequenceIndex -> lowest so 1-to-0 deletions
    # never shift earlier indices in HarfBuzz or CoreText!
    subtables = [
        # Priority 0 (4a): <G1> [0360 <G2> 0360 <G3> 0360] <G4>
        _make_chain_subst_fmt3(
            [geor],
            [u360, geor, u360, geor, u360],
            [geor],
            [(4, idx_del), (2, idx_s4), (0, idx_del)],
            gmap,
        ),
        # Priority 1 (4b): <G1> [0303 <G2> 0303 <G3> 0303 <G4> 0303]
        _make_chain_subst_fmt3(
            [geor],
            [u303, geor, u303, geor, u303, geor, u303],
            [],
            [(6, idx_del), (4, idx_del), (2, idx_s4), (0, idx_del)],
            gmap,
        ),
        # Priority 2 (3a): <G1> [0360 <G2> 0360] <G3>
        _make_chain_subst_fmt3(
            [geor],
            [u360, geor, u360],
            [geor],
            [(2, idx_s3), (0, idx_del)],
            gmap,
        ),
        # Priority 3 (3b): <G1> [0303 <G2> 0303 <G3> 0303]
        _make_chain_subst_fmt3(
            [geor],
            [u303, geor, u303, geor, u303],
            [],
            [(4, idx_del), (2, idx_s3), (0, idx_del)],
            gmap,
        ),
        # Priority 4 (2b): <G1> [0303 <G2> 0303]
        _make_chain_subst_fmt3(
            [geor],
            [u303, geor, u303],
            [],
            [(2, idx_del), (0, idx_s2)],
            gmap,
        ),
    ]

    lks[idx_chain].SubTable = subtables
    lks[idx_chain].SubTableCount = len(subtables)
    gsub.LookupList.LookupCount = len(lks)

    # Wire into every `calt` feature record across all scripts (idempotently)
    attached = 0
    for fr in gsub.FeatureList.FeatureRecord:
        if fr.FeatureTag == "calt":
            if idx_chain not in fr.Feature.LookupListIndex:
                fr.Feature.LookupListIndex.append(idx_chain)
                fr.Feature.LookupCount = len(fr.Feature.LookupListIndex)
            attached += 1

    return {
        "wired": True,
        "chain_lookup_idx": idx_chain,
        "geor_bases": len(geor),
        "calt_features_updated": attached,
    }


# ---------------------------------------------------------------------------
# 3. GPOS MarkBase Registration + Contextual Height Clearance & Optical Centering
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


def _make_single_pos_lookup(font, glyphs, dx, dy):
    """Build a varLib-compatible SinglePos Format 1 lookup with fixed ValueFormat=3 (XPlacement|YPlacement)."""
    lk = otTables.Lookup()
    lk.LookupType = 1
    lk.LookupFlag = 0
    st = otTables.SinglePos()
    st.Format = 1
    cov = otTables.Coverage()
    cov.glyphs = sorted(set(glyphs), key=font.getGlyphID)
    st.Coverage = cov
    vr = otTables.ValueRecord()
    vr.XPlacement = int(round(dx))
    vr.YPlacement = int(round(dy))
    st.ValueFormat = 3  # Always XPlacement | YPlacement for strict varLib ValueFormat uniformity
    st.Value = vr
    lk.SubTable = [st]
    lk.SubTableCount = 1
    return lk


def _make_chain_pos_fmt3(bt_lists, inp_lists, la_lists, lookup_idx, gmap):
    st = otTables.ChainContextPos()
    st.Format = 3
    st.BacktrackCoverage = [_make_coverage(gl, gmap) for gl in bt_lists]
    st.BacktrackGlyphCount = len(st.BacktrackCoverage)
    st.InputCoverage = [_make_coverage(gl, gmap) for gl in inp_lists]
    st.InputGlyphCount = len(st.InputCoverage)
    st.LookAheadCoverage = [_make_coverage(gl, gmap) for gl in la_lists]
    st.LookAheadGlyphCount = len(st.LookAheadCoverage)
    rec = otTables.PosLookupRecord()
    rec.SequenceIndex = 0
    rec.LookupListIndex = lookup_idx
    st.PosLookupRecord = [rec]
    st.PosCount = 1
    return st


def find_karagma_chain_lookup(gpos_table):
    """Locate our Georgian Karagma contextual vertical clearance LookupType 8 lookup index (or None)."""
    for li, lk in enumerate(gpos_table.LookupList.Lookup):
        if lk.LookupType != 8 or not lk.SubTable:
            continue
        st0 = lk.SubTable[0]
        if (
            getattr(st0, "Format", None) == 3
            and getattr(st0, "InputCoverage", None)
            and len(lk.SubTable) >= 20
            and any(g in ("uni0360.span3", "uni0360.span4") for g in st0.InputCoverage[0].glyphs)
        ):
            return li
    return None


def find_karagma_xshift_chain_lookup(gpos_table):
    """Locate our Georgian Karagma optical XPlacement centering LookupType 8 lookup index (or None)."""
    for li, lk in enumerate(gpos_table.LookupList.Lookup):
        if lk.LookupType != 8 or not lk.SubTable:
            continue
        st0 = lk.SubTable[0]
        if (
            getattr(st0, "Format", None) == 3
            and getattr(st0, "InputCoverage", None)
            and len(lk.SubTable) == 4
            and "uni0360.span3" in st0.InputCoverage[0].glyphs
            and getattr(st0, "BacktrackGlyphCount", 0) == 2
            and getattr(st0, "LookAheadGlyphCount", 0) == 1
        ):
            return li
    return None


def _resolve_tier_glyphs(font, cps):
    cm = font.getBestCmap()
    all_g = set(font.getGlyphOrder())
    out = set()
    for cp in cps:
        gn = cm.get(cp)
        if gn and gn in all_g:
            out.add(gn)
            for suf in (".ss01", ".ss01.case"):
                if gn + suf in all_g:
                    out.add(gn + suf)
    return out


def _measure_anchor_tiers(font, geor_rst):
    """
    Measure exact top-anchor Y coordinates of each Georgian height tier directly from the
    font's Georgian MarkBase subtable (falls back to glyph bbox tops if absent).
    """
    bmap = {}
    if geor_rst is not None:
        for g, brec in zip(geor_rst.BaseCoverage.glyphs, geor_rst.BaseArray.BaseRecord):
            if brec.BaseAnchor and brec.BaseAnchor[0] is not None:
                bmap[g] = float(brec.BaseAnchor[0].YCoordinate)

    def probe(gnames, default_y):
        vals = [bmap[g] for g in gnames if g in bmap]
        if vals:
            vals.sort()
            return vals[len(vals) // 2]
        # Fallback from actual glyph bbox
        tops = []
        gset = set(font.getGlyphOrder())
        for g in gnames:
            if g in gset:
                bb = _glyph_bbox(font, g)
                if bb:
                    tops.append(float(bb[3]) - 8.0)
        return (sorted(tops)[len(tops) // 2]) if tops else default_y

    y_short = probe(["uni10D0", "uni10D3", "uni10DD"], 527.0)
    y_mid_lo = probe(["uni10A3", "uni10A0", "uni10A7"], 681.0)
    y_mid_hi = probe(["uni10B6", "uni10B3", "uni10AD"], 691.0)
    y_tall_lo = probe(["uni2D03", "uni2D13", "uni10D6.case"], 725.0)
    y_tall_hi = probe(["uni10D6", "uni10DB", "uni10D1"], 745.0)
    return y_short, y_mid_lo, y_mid_hi, y_tall_lo, y_tall_hi


def patch_gpos_karagma(font, is_italic=False):
    """
    Complete GPOS MarkBase & contextual clearance hardening for all 3 wavy Georgian karagma marks:
      1. Registers `uni0483`, `uni0360.span3`, `uni0360.span4` into EVERY MarkBase subtable
         containing `tildecomb` (automatically covering Georgian, Latin, Cyrillic, and `uni25CC`
         dotted circle!).
         All 3 marks anchor cleanly at `x = (ref_my - ITAL_PIVOT_Y) * tan(8 deg)` (0 on Upright),
         matching `build_variable_fonts.py`'s `shear_gpos_anchors` to 0.000u!
      2. Installs/updates a single idempotent, varLib-compatible `ChainContextPos` (LookupType 8)
         lookup in `mark` with fixed `SinglePos` (`ValueFormat=3`) helper lookups so:
           - `uni0360.span3` clears taller letters on `<L1>` OR `<L3>` (e.g. `Ⴃ͠ა͠ა`, `ა͠ა͠ბ`, `ბ͠ა͠ა`)
           - `uni0360.span4` clears taller letters on `<L1>`, `<L3>`, OR `<L4>` (`ა͠ა͠ა͠ბ`, `Ⴃ͠ა͠ა͠ა`)
      3. Installs/updates optical `XPlacement` centering (`ChainContextPos` LookupType 8) for
         asymmetric mixed-width 3-/4-letter words (`Ⴃ͠Ⴃ͠ა`, `დ͠დ͠ა`, `Ⴃ͠Ⴃ͠Ⴀ͠Ⴈ`).
    """
    if "GPOS" not in font:
        return {"marks_registered": 0, "chain_subtables": 0}

    gpos = font["GPOS"].table
    order = font.getGlyphOrder()
    gmap = {g: i for i, g in enumerate(order)}
    gset = set(order)
    tan_a = math.tan(math.radians(ITAL_ANGLE_DEG)) if is_italic else 0.0

    # --- Step 1: Register all 3 wavy mark glyphs in every MarkBase subtable having `tildecomb` ---
    marks_registered = 0
    geor_rst = None
    for lk in gpos.LookupList.Lookup:
        for st in lk.SubTable:
            ltype = st.ExtensionLookupType if lk.LookupType == 9 else lk.LookupType
            rst = st.ExtSubTable if lk.LookupType == 9 else st
            if ltype != 4 or not hasattr(rst, "MarkCoverage") or not hasattr(rst, "BaseCoverage"):
                continue
            if "uni10D0" in rst.BaseCoverage.glyphs and geor_rst is None:
                geor_rst = rst
            mcov = rst.MarkCoverage.glyphs
            if "tildecomb" not in mcov:
                continue
            t_idx = mcov.index("tildecomb")
            t_rec = rst.MarkArray.MarkRecord[t_idx]
            if t_rec.MarkAnchor is None:
                continue
            cls = t_rec.Class
            ref_my = float(t_rec.MarkAnchor.YCoordinate)
            # Every karagma glyph was built centered around unslanted anchor x=0 (with span4
            # shifted +0.5*avg inside its outline itself!) and sheared around ITAL_PIVOT_Y.
            # Therefore MarkAnchor X is ALWAYS `(ref_my - ITAL_PIVOT_Y) * tan_a` (0 on Upright)!
            ax = (ref_my - ITAL_PIVOT_Y) * tan_a
            for mg in KARAGMA_GLYPH_NAMES:
                if mg in gset:
                    _insert_mark_into_subtable(font, rst, mg, cls, ax, ref_my)
                    marks_registered += 1

    # --- Step 2: Contextual Height Clearance (varLib-safe LookupType 8) ---
    short_g = sorted(_resolve_tier_glyphs(font, GEOR_SHORT_CPS), key=lambda g: gmap[g])
    mid_lo_g = sorted(_resolve_tier_glyphs(font, GEOR_MID_LO_CPS), key=lambda g: gmap[g])
    mid_hi_g = sorted(_resolve_tier_glyphs(font, GEOR_MID_HI_CPS), key=lambda g: gmap[g])
    mid_all_g = sorted(set(mid_lo_g) | set(mid_hi_g), key=lambda g: gmap[g])
    tall_lo_g = sorted(_resolve_tier_glyphs(font, GEOR_TALL_LO_CPS), key=lambda g: gmap[g])
    tall_hi_g = sorted(_resolve_tier_glyphs(font, GEOR_TALL_HI_CPS), key=lambda g: gmap[g])
    tall_all_g = sorted(set(tall_lo_g) | set(tall_hi_g), key=lambda g: gmap[g])
    any_geor_g = sorted(set(short_g) | set(mid_all_g) | set(tall_all_g), key=lambda g: gmap[g])

    if not short_g or not any_geor_g:
        return {"marks_registered": marks_registered, "chain_subtables": 0}

    y_short, y_mid_lo, y_mid_hi, y_tall_lo, y_tall_hi = _measure_anchor_tiers(font, geor_rst)

    # Exact deterministic lift deltas (10 shared SinglePos Format 1 ValueFormat=3 helpers)
    # Every helper covers BOTH contextual wavy karagma marks so varLib merges cleanly across all 16 masters!
    ctx_marks = [g for g in ("uni0360.span3", "uni0360.span4") if g in gset]
    if not ctx_marks:
        return {"marks_registered": marks_registered, "chain_subtables": 0}

    lift_specs = (
        ("short_to_tall_hi", max(0.0, y_tall_hi - y_short)),
        ("short_to_tall_lo", max(0.0, y_tall_lo - y_short)),
        ("short_to_mid_hi",  max(0.0, y_mid_hi - y_short)),
        ("short_to_mid_lo",  max(0.0, y_mid_lo - y_short)),
        ("mid_lo_to_tall_hi", max(0.0, y_tall_hi - y_mid_lo)),
        ("mid_lo_to_tall_lo", max(0.0, y_tall_lo - y_mid_lo)),
        ("mid_lo_to_mid_hi",  max(0.0, y_mid_hi - y_mid_lo)),
        ("mid_hi_to_tall_hi", max(0.0, y_tall_hi - y_mid_hi)),
        ("mid_hi_to_tall_lo", max(0.0, y_tall_lo - y_mid_hi)),
        ("tall_lo_to_tall_hi", max(0.0, y_tall_hi - y_tall_lo)),
    )

    lks = gpos.LookupList.Lookup
    existing_idx = find_karagma_chain_lookup(gpos)

    helper_map = {}
    if existing_idx is not None:
        # Collect unique existing helper lookup indices in order of first appearance (100% idempotent!)
        seen_helpers = []
        for st in lks[existing_idx].SubTable:
            if getattr(st, "PosLookupRecord", None):
                hi = st.PosLookupRecord[0].LookupListIndex
                if hi not in seen_helpers:
                    seen_helpers.append(hi)
        for idx_s, (key, dy) in enumerate(lift_specs):
            dx = dy * tan_a
            if idx_s < len(seen_helpers):
                h_idx = seen_helpers[idx_s]
                lks[h_idx] = _make_single_pos_lookup(font, ctx_marks, dx, dy)
            else:
                h_idx = len(lks)
                lks.append(_make_single_pos_lookup(font, ctx_marks, dx, dy))
            helper_map[key] = h_idx
        chain_idx = existing_idx
    else:
        for key, dy in lift_specs:
            dx = dy * tan_a
            h_idx = len(lks)
            lks.append(_make_single_pos_lookup(font, ctx_marks, dx, dy))
            helper_map[key] = h_idx
        chain_lk = otTables.Lookup()
        chain_lk.LookupType = 8
        chain_lk.LookupFlag = 0
        chain_idx = len(lks)
        lks.append(chain_lk)

    subtables = []

    def add_rule(bt, inp, la, key):
        subtables.append(_make_chain_pos_fmt3(bt, inp, la, helper_map[key], gmap))

    SPAN3 = [["uni0360.span3"]]
    SPAN4 = [["uni0360.span4"]]

    # --- A. `uni0360.span3` (<L1> <L2> span3 <L3>) — BT[0]=L2, BT[1]=L1, LA[0]=L3 ---
    # Ordered strictly tallest-target-first so only the highest needed lift fires!
    for base_grp, tiers in (
        (short_g, (
            (tall_hi_g, "short_to_tall_hi"),
            (tall_lo_g, "short_to_tall_lo"),
            (mid_hi_g,  "short_to_mid_hi"),
            (mid_lo_g,  "short_to_mid_lo"),
        )),
        (mid_lo_g, (
            (tall_hi_g, "mid_lo_to_tall_hi"),
            (tall_lo_g, "mid_lo_to_tall_lo"),
            (mid_hi_g,  "mid_lo_to_mid_hi"),
        )),
        (mid_hi_g, (
            (tall_hi_g, "mid_hi_to_tall_hi"),
            (tall_lo_g, "mid_hi_to_tall_lo"),
        )),
        (tall_lo_g, (
            (tall_hi_g, "tall_lo_to_tall_hi"),
        )),
    ):
        for target_grp, key in tiers:
            add_rule([base_grp, target_grp], SPAN3, [], key)            # L1 taller than L2
            add_rule([base_grp],             SPAN3, [target_grp], key)  # L3 taller than L2

    # --- B. `uni0360.span4` (<L1> <L2> span4 <L3> <L4>) — BT[0]=L2, BT[1]=L1, LA[0]=L3, LA[1]=L4 ---
    for base_grp, tiers in (
        (short_g, (
            (tall_hi_g, "short_to_tall_hi"),
            (tall_lo_g, "short_to_tall_lo"),
            (mid_hi_g,  "short_to_mid_hi"),
            (mid_lo_g,  "short_to_mid_lo"),
        )),
        (mid_lo_g, (
            (tall_hi_g, "mid_lo_to_tall_hi"),
            (tall_lo_g, "mid_lo_to_tall_lo"),
            (mid_hi_g,  "mid_lo_to_mid_hi"),
        )),
        (mid_hi_g, (
            (tall_hi_g, "mid_hi_to_tall_hi"),
            (tall_lo_g, "mid_hi_to_tall_lo"),
        )),
        (tall_lo_g, (
            (tall_hi_g, "tall_lo_to_tall_hi"),
        )),
    ):
        for target_grp, key in tiers:
            add_rule([base_grp, target_grp], SPAN4, [], key)                       # L1 taller
            add_rule([base_grp],             SPAN4, [target_grp], key)             # L3 taller
            add_rule([base_grp],             SPAN4, [any_geor_g, target_grp], key) # L4 taller

    lks[chain_idx].SubTable = subtables
    lks[chain_idx].SubTableCount = len(subtables)

    # --- Step 3: Optical XPlacement Centering for Asymmetric Mixed-Width 3-/4-Letter Spans ---
    # Shifts uni0360.span3 / uni0360.span4 left when L1 is massive/wide (e.g. Ⴃ, დ, Დ, Ⴓ) and
    # L_last is compact/narrow (e.g. ა, Ა, Ⴈ) — making `Ⴃ͠Ⴃ͠ა`, `დ͠დ͠ა`, `Ⴓ͠Ⴊ͠Ⴈ`, `Ⴃ͠Ⴃ͠Ⴀ͠Ⴈ`
    # dead-centered over true visual mass (and symmetric +dx when L1 narrow & L_last wide)!
    wide_g = sorted(_resolve_tier_glyphs(font, GEOR_WIDE_CPS), key=lambda g: gmap[g])
    narrow_g = sorted(_resolve_tier_glyphs(font, GEOR_NARROW_CPS), key=lambda g: gmap[g])
    span_x_marks = [g for g in ("uni0360.span3", "uni0360.span4") if g in gset]
    chain_x_idx = None
    dx_opt = 0

    if wide_g and narrow_g and len(span_x_marks) == 2:
        hmtx = font["hmtx"]
        cm = font.getBestCmap()
        geor_advs = []
        for cps in (MKHEDRULI_CPS, ASOMTAVRULI_CPS, NUSKHURI_CPS, MTAVRULI_CPS):
            grp = [float(hmtx[cm[cp]][0]) for cp in cps if cp in cm and cm[cp] in hmtx.metrics]
            if grp:
                geor_advs.append(sum(grp) / len(grp))
        avg_geor_adv = (sum(geor_advs) / len(geor_advs)) if geor_advs else 665.0
        dx_opt = int(round(0.16 * avg_geor_adv))

        existing_x_idx = find_karagma_xshift_chain_lookup(gpos)
        if existing_x_idx is not None:
            old_x_lk = lks[existing_x_idx]
            h_left = old_x_lk.SubTable[0].PosLookupRecord[0].LookupListIndex
            h_right = old_x_lk.SubTable[1].PosLookupRecord[0].LookupListIndex
            lks[h_left] = _make_single_pos_lookup(font, span_x_marks, -dx_opt, 0)
            lks[h_right] = _make_single_pos_lookup(font, span_x_marks, +dx_opt, 0)
            chain_x_idx = existing_x_idx
        else:
            h_left = len(lks)
            lks.append(_make_single_pos_lookup(font, span_x_marks, -dx_opt, 0))
            h_right = len(lks)
            lks.append(_make_single_pos_lookup(font, span_x_marks, +dx_opt, 0))
            lk_x = otTables.Lookup()
            lk_x.LookupType = 8
            lk_x.LookupFlag = 0
            chain_x_idx = len(lks)
            lks.append(lk_x)

        x_subtables = [
            # Subtable 0: span3 wide L1 + narrow L3 -> shift LEFT (-dx_opt) (e.g. Ⴃ͠Ⴃ͠ა, დ͠დ͠ა, Ⴓ͠Ⴊ͠Ⴈ)
            _make_chain_pos_fmt3([any_geor_g, wide_g],   SPAN3, [narrow_g],             h_left,  gmap),
            # Subtable 1: span3 narrow L1 + wide L3 -> shift RIGHT (+dx_opt) (e.g. ა͠ა͠დ, Ⴈ͠Ⴃ͠Ⴊ)
            _make_chain_pos_fmt3([any_geor_g, narrow_g], SPAN3, [wide_g],               h_right, gmap),
            # Subtable 2: span4 wide L1 + narrow L4 -> shift LEFT (-dx_opt) (e.g. Ⴃ͠Ⴃ͠Ⴀ͠Ⴈ)
            _make_chain_pos_fmt3([any_geor_g, wide_g],   SPAN4, [any_geor_g, narrow_g], h_left,  gmap),
            # Subtable 3: span4 narrow L1 + wide L4 -> shift RIGHT (+dx_opt) (e.g. ა͠ა͠ა͠დ)
            _make_chain_pos_fmt3([any_geor_g, narrow_g], SPAN4, [any_geor_g, wide_g],   h_right, gmap),
        ]
        lks[chain_x_idx].SubTable = x_subtables
        lks[chain_x_idx].SubTableCount = len(x_subtables)

    gpos.LookupList.LookupCount = len(lks)

    # Wire into every `mark` feature record right after MarkBase (idempotently)
    for fr in gpos.FeatureList.FeatureRecord:
        if fr.FeatureTag == "mark":
            if chain_idx not in fr.Feature.LookupListIndex:
                fr.Feature.LookupListIndex.append(chain_idx)
            if chain_x_idx is not None and chain_x_idx not in fr.Feature.LookupListIndex:
                fr.Feature.LookupListIndex.append(chain_x_idx)
            fr.Feature.LookupCount = len(fr.Feature.LookupListIndex)

    return {
        "marks_registered": marks_registered,
        "chain_lookup_idx": chain_idx,
        "chain_subtables": len(subtables),
        "xshift_lookup_idx": chain_x_idx,
        "dx_opt": dx_opt,
        "helper_lifts": {k: round(dy, 1) for k, dy in lift_specs},
    }


# ---------------------------------------------------------------------------
# 4. One-Call Drop-In Entrypoint for Static CFF OTFs (100% Idempotent!)
# ---------------------------------------------------------------------------

def apply_georgian_karagma_to_otf(
    font,
    weight_class=None,
    width_mode=None,
    is_italic=False,
    rounded=False,
    sharp_ref_font=None,
):
    """
    Complete, 100%-idempotent Georgian Karagma injection pass for any Batumi Sans CFF OTF:
      1. Injects all 3 wavy GDEF class 3 combining mark glyphs (`uni0483`, `uni0360.span3`,
         `uni0360.span4`) with locked VF contour/segment topology (pruning deprecated flat
         half-marks `uniFE22`/`uniFE23`/`uniFE26` if present).
      2. Wires Georgian-scoped OpenType `calt` auto-merge (2-, 3-, 4-letter spans).
      3. Registers MarkBase anchors across all scripts + `uni25CC` AND installs varLib-safe
         contextual height clearance & optical XPlacement centering in GPOS `mark`.
    """
    glyph_stats = inject_karagma_glyphs(
        font,
        weight_class=weight_class,
        width_mode=width_mode,
        is_italic=is_italic,
        rounded=rounded,
        sharp_ref_font=sharp_ref_font,
    )
    gsub_stats = wire_gsub_karagma(font)
    gpos_stats = patch_gpos_karagma(font, is_italic=is_italic)
    return {
        "glyphs": glyph_stats,
        "gsub": gsub_stats,
        "gpos": gpos_stats,
        "issues": glyph_stats.get("issues", []),
    }

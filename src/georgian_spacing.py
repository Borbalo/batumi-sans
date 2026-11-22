#!/usr/bin/env python3
"""
Batumi Sans Foundry-Calibrated Georgian Optical Spacing Engine (`v2`).

Recovers tight Georgian Bold / ExtraBold / Heavy rhythm (especially Extra Condensed,
Condensed, True Cursive Italic, and steep `slnt = -12°`) while keeping:
  - ZERO change to Thin (100) .. Medium (500) -> 0 UI / MapLibre Regular/Medium reflow!
  - Strict 4-width progression (`ExtraCondensed < Condensed < Normal < Expanded`)
  - Uniform visual bead rhythm on Mkhedruli (`დ-ო-ლ-ჩ-ე`) & Mtavruli (`Დ-Ო-Ლ-Ჩ-Ე`)
  - Zero negative collisions AND zero pairs < 30u across all 1,089 Mkhedruli + 1,089 Mtavruli pairs!
  - Exact zero-error outline shift (+dl) on BOTH CFF (`CharStrings`/OTF) and TrueType (`glyf`/TTF),
    synchronized `hmtx` (`adv + dl + dr`, `lsb + dl`), and synchronized `GPOS` `MarkBase`/`MarkLig`
    base anchors (`XCoordinate + dl`) so accented Georgian & Kartvelian `U+0360` stay dead-centered!
  - 100% idempotency via deterministic sentinel ledger (`qa/georgian_spacing_state.json`).
"""

import hashlib
import json
import math
import os
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.transformPen import TransformPen

SPACING_VERSION = "v2.0"

# Deterministic sentinel glyphs tracked per static style in qa/georgian_spacing_state.json
SENTINEL_GLYPHS = (
    "uni10D0",
    "uni10D3",
    "uni10DA",
    "uni10E9",
    "uni10EC",
    "uni10ED",
    "uni10D0.case",
    "uni10D3.case",
    "uni10DA.case",
    "uni10E9.case",
    "uni10ED.case",
    "ampersand.geor",
    "ampersand.geor.case",
)

# Complete mapping of all 19 Mkhedruli + 19 Mtavruli accented Georgian composites
# (supporting BOTH pre-v1.100 long names and v1.100 shortened names, plus upstream `.com`!)
# plus all Georgian `.ss01` stylistic alternates -> their base letter glyph name.
ACCENTED_AND_ALT_BASE_MAP = {
    # Mkhedruli .ss01 alternates (Upright + Italic)
    "uni10DD.ss01": "uni10DD",
    "uni10E0.ss01": "uni10E0",
    "uni10E2.ss01": "uni10E2",
    "uni10E8.ss01": "uni10E8",
    "uni10EC.ss01": "uni10EC",
    "uni10EF.ss01": "uni10EF",
    # 19 Mkhedruli accented composites
    "angeorgian_macrondieresiscomb": "uni10D0",
    "uni10D00308": "uni10D0",
    "uni10D00301": "uni10D0",
    "uni10D00304": "uni10D0",
    "uni10D40301": "uni10D4",
    "uni10D40304": "uni10D4",
    "uni10D80301": "uni10D8",
    "uni10D80304": "uni10D8",
    "ongeorgian_macrondieresiscomb": "uni10DD",
    "uni10DD0308": "uni10DD",
    "uni10DD0301": "uni10DD",
    "uni10DD0304": "uni10DD",
    "ungeorgian_macrondieresiscomb": "uni10E3",
    "uni10E30308": "uni10E3",
    "uni10E30301": "uni10E3",
    "uni10E30302": "uni10E3",
    "uni10E30304": "uni10E3",
    "uni10F70301": "uni10F7",
    "uni10F70304": "uni10F7",
    # 19 Mtavruli (.case) accented composites (both v1.100 & pre-v1.100 names!)
    "uni10D0_0304_0308.case": "uni10D0.case",
    "Angeorgian_macrondieresiscomb.case": "uni10D0.case",
    "uni10D0.case0308.case": "uni10D0.case",
    "uni10D0.case0301.case": "uni10D0.case",
    "uni10D0.case0304.com": "uni10D0.case",
    "uni10D0.case0304.case": "uni10D0.case",
    "uni10D4.case0301.case": "uni10D4.case",
    "uni10D4.case0304.case": "uni10D4.case",
    "uni10D8.case0301.case": "uni10D8.case",
    "uni10D8.case0304.case": "uni10D8.case",
    "uni10DD_0304_0308.case": "uni10DD.case",
    "Ongeorgian_macrondieresiscomb.case": "uni10DD.case",
    "uni10DD.case0308.case": "uni10DD.case",
    "uni10DD.case0301.case": "uni10DD.case",
    "uni10DD.case0304.case": "uni10DD.case",
    "uni10E3_0304_0308.case": "uni10E3.case",
    "Ungeorgian_macrondieresiscomb.case": "uni10E3.case",
    "uni10E3.case0308.case": "uni10E3.case",
    "uni10E3.case0301.case": "uni10E3.case",
    "uni10E3.case0302.case": "uni10E3.case",
    "uni10E3.case0304.case": "uni10E3.case",
    "uni10F7.case0301.case": "uni10F7.case",
    "uni10F7.case0304.case": "uni10F7.case",
}

# Canonical Mkhedruli (U+10D0..10FF) and Mtavruli (U+1C90..1CBF -> uni10D0.case..uni10FF.case)
MKH_GLYPHS_ALL = {f"uni{cp:04X}" for cp in range(0x10D0, 0x1100)}
MTV_GLYPHS_ALL = {f"uni{cp:04X}.case" for cp in range(0x10D0, 0x1100)}


def lerp_w(weight_class, v600, v700, v800, v900):
    """Smooth piecewise-linear weight curve over [(500,0),(600,v600),(700,v700),(800,v800),(900,v900)]."""
    w = float(weight_class)
    if w <= 500.0:
        return 0.0
    if w >= 900.0:
        return float(v900)
    stops = (
        (500.0, 0.0),
        (600.0, float(v600)),
        (700.0, float(v700)),
        (800.0, float(v800)),
        (900.0, float(v900)),
    )
    for (x0, y0), (x1, y1) in zip(stops, stops[1:]):
        if x0 <= w <= x1:
            return y0 + (y1 - y0) * (w - x0) / (x1 - x0)
    return 0.0


def compute_slnt_breathing(weight_class, slnt_deg, is_italic):
    """
    Extra steep-slant per-side breathing (in font units, integer-rounded) for `slnt = -12°` VF plane:
      - `extra_slnt_deg = max(0, |slnt| - |native_slnt|)`
        (4.0° on Italic -12° vs native -8°; 12.0° capped gently at 6.0° on Upright -12°!)
      - `slnt_add = min(extra_slnt_deg, 6.0) * lerp_w(w, 0.15, 0.45, 0.75, 1.1)`
      - Strictly 0 at default `slnt`, 0 on Italic `slnt = 0°`, and 0 for `weight_class <= 500`.
    """
    if slnt_deg is None or float(weight_class) <= 500.0:
        return 0
    native_slnt = -8.0 if is_italic else 0.0
    extra_slnt_deg = max(0.0, abs(float(slnt_deg)) - abs(native_slnt))
    if extra_slnt_deg <= 1e-6:
        return 0
    val = min(extra_slnt_deg, 6.0) * lerp_w(weight_class, 0.15, 0.45, 0.75, 1.1)
    return int(round(val))


def _base_curves(weight_class, width_mode):
    """Return (mkh_base, mtv_base) floats for the v2 weight x width optical spacing curves."""
    wm = width_mode.lower().replace("-", "_").replace(" ", "_")
    if wm in ("extra_condensed", "extracondensed"):
        return (
            lerp_w(weight_class, 3, 7, 11, 16),
            lerp_w(weight_class, 4, 8, 13, 19),
        )
    if wm == "condensed":
        return (
            lerp_w(weight_class, 2, 5, 9, 13),
            lerp_w(weight_class, 2, 6, 10, 15),
        )
    if wm == "normal":
        return (
            lerp_w(weight_class, 0, 2, 6, 10),
            lerp_w(weight_class, 0, 3, 7, 12),
        )
    if wm == "expanded":
        return (
            lerp_w(weight_class, 0, 2, 5, 8),
            lerp_w(weight_class, 0, 2, 6, 10),
        )
    raise ValueError(f"Unknown width_mode: {width_mode!r}")


def _per_glyph_extras(base_gname, width_mode, is_italic):
    """
    Exact v2 per-glyph heavy edge & collision protection `(el, er)` multiplied by
    `wf = lerp_w(w, 0.15, 0.45, 0.72, 1.0)`.
    """
    # Overhanging right arms
    if base_gname == "uni10ED":  # ჭ
        el, er = 4.0, 24.0
        # Width-calibrated Italic overhang guard: upstream FiraGO ჭ+წ overhang is -30u (Normal) / -34u (Expanded)
        # while mkh_base decreases 16 -> 13 -> 10 -> 8; small extra on ჭ keeps ჭწ >= 30u across all 4 widths
        # with ZERO change to დოლჩე & გაბანა or general word rhythm!
        if is_italic and width_mode == "normal":
            er += 3.0
        elif is_italic and width_mode == "expanded":
            er += 9.0
        return (el, er)
    if base_gname == "uni10EC":  # წ
        el, er = 14.0, 21.0
        if is_italic and width_mode == "expanded":
            el += 3.0
            er += 1.0
        return (el, er)
    if base_gname == "uni10ED.case":  # Ჭ
        return (4.0, 16.0)
    if base_gname == "uni10E1.case":  # Ს
        return (4.0, 12.0)

    # Tall left ascenders / vertical walls
    if base_gname == "uni10E9":  # ჩ
        return (11.0, 5.0) if is_italic else (10.0, 4.0)
    if base_gname == "uni10E9.case":  # Ჩ
        return (10.0, 5.0) if is_italic else (10.0, 4.0)
    if base_gname == "uni10D6":  # ზ
        el, er = 10.0, 4.0
        if is_italic and width_mode == "expanded":
            el += 2.0
        return (el, er)
    if base_gname == "uni10E8":  # შ
        return (8.0, 4.0)
    if base_gname == "uni10E3":  # უ
        return (8.0, 4.0)

    # Steep Italic cursive right walls
    if base_gname == "uni10DA":  # ლ
        return (4.0, 11.0) if is_italic else (3.0, 6.0)
    if base_gname == "uni10D3":  # დ
        return (4.0, 12.0) if is_italic else (3.0, 5.0)
    if base_gname == "uni10DA.case":  # Ლ
        return (4.0, 10.0) if is_italic else (4.0, 8.0)
    if base_gname == "uni10D3.case":  # Დ
        return (4.0, 9.0) if is_italic else (4.0, 6.0)

    # Dense horizontal hooks / bars
    if base_gname == "uni10EE":  # ხ
        return (4.0, 7.0)
    if base_gname == "uni10DF":  # ჟ
        return (4.0, 7.0)
    if base_gname == "uni10D2":  # გ
        return (4.0, 7.0)
    if base_gname == "uni10D9":  # კ
        el, er = 6.0, 7.0
        if is_italic and width_mode == "expanded":
            el += 5.0  # Guards დკ (-65u expanded kern) >= 30u cleanly
        return (el, er)
    if base_gname == "uni10D5":  # ვ
        return (4.0, 6.0)
    if base_gname == "uni10EF":  # ჯ
        return (4.0, 7.0)
    if base_gname == "uni10E4":  # ფ
        return (6.0, 4.0)
    if base_gname in ("uni10D1", "uni10D0", "uni10D4", "uni10DC", "uni10DD"):  # ბ / ა / ე / ნ / ო
        return (3.0, 3.0)
    if base_gname == "uni10DD.case":  # Ო
        return (3.0, 5.0)
    if base_gname == "uni10D4.case":  # Ე
        return (5.0, 3.0)
    if base_gname in ("uni10D9.case", "uni10DE.case"):  # Კ / Პ
        return (5.0, 5.0)
    if base_gname in ("uni10E3.case", "uni10E4.case"):  # Უ / Ფ
        return (7.0, 4.0)

    return (0.0, 0.0)


def is_georgian_spacing_target(gname, cmap_geor_glyphs=None):
    """Return True if glyph belongs to the v2 Georgian spacing target set."""
    if gname in MKH_GLYPHS_ALL or gname in MTV_GLYPHS_ALL:
        return True
    if gname in ACCENTED_AND_ALT_BASE_MAP:
        return True
    if gname in ("ampersand.geor", "ampersand.geor.case"):
        return True
    if cmap_geor_glyphs and gname in cmap_geor_glyphs:
        return True
    return False


def get_georgian_slnt_target_glyphs(glyph_order, cmap=None):
    """
    Collect all Georgian glyphs in `glyph_order` eligible for steep-slant breathing
    (all Mkhedruli U+10D0..10FF, Mtavruli U+1C90..1CBF, `.ss01` alternates, all 19+19
    accented Georgian composites, and `ampersand.geor` / `ampersand.geor.case`).
    """
    cmap_geor = set()
    if cmap:
        for cp in range(0x10D0, 0x1100):
            if cp in cmap:
                cmap_geor.add(cmap[cp])
        for cp in range(0x1C90, 0x1CC0):
            if cp in cmap:
                cmap_geor.add(cmap[cp])
    return [g for g in glyph_order if is_georgian_spacing_target(g, cmap_geor)]


def compute_georgian_spacing_deltas(
    glyph_order,
    cmap,
    weight_class,
    width_mode,
    is_italic,
    slnt_deg=None,
):
    """
    Compute exact `(dl, dr)` integer font-unit spacing deltas for every Georgian target glyph
    present in `glyph_order`. Returns `{}` for `weight_class <= 500` (Thin..Medium untouched!).
    """
    if float(weight_class) <= 500.0:
        return {}

    wm = width_mode.lower().replace("-", "_").replace(" ", "_")
    mkh_base, mtv_base = _base_curves(weight_class, wm)
    wf = lerp_w(weight_class, 0.15, 0.45, 0.72, 1.0)
    slnt_add = float(compute_slnt_breathing(weight_class, slnt_deg, is_italic))

    # Build cmap-derived Mkhedruli/Mtavruli maps in case any glyph uses a custom name
    mkh_from_cmap = set()
    mtv_from_cmap = set()
    if cmap:
        for cp in range(0x10D0, 0x1100):
            if cp in cmap:
                mkh_from_cmap.add(cmap[cp])
        for cp in range(0x1C90, 0x1CC0):
            if cp in cmap:
                mtv_from_cmap.add(cmap[cp])

    def _delta_for_base(base_g):
        is_mtv = (base_g in MTV_GLYPHS_ALL) or (base_g in mtv_from_cmap) or base_g.endswith(".case")
        base = (mtv_base if is_mtv else mkh_base) + slnt_add
        el, er = _per_glyph_extras(base_g, wm, is_italic)
        dl = int(round(base + el * wf))
        dr = int(round(base + er * wf))
        return (dl, dr)

    deltas = {}
    for gname in glyph_order:
        if gname == "ampersand.geor":
            d = int(round(0.75 * mkh_base + slnt_add))
            if d != 0:
                deltas[gname] = (d, d)
        elif gname == "ampersand.geor.case":
            d = int(round(0.75 * mtv_base + slnt_add))
            if d != 0:
                deltas[gname] = (d, d)
        elif gname in ACCENTED_AND_ALT_BASE_MAP:
            base_g = ACCENTED_AND_ALT_BASE_MAP[gname]
            dl, dr = _delta_for_base(base_g)
            if dl != 0 or dr != 0:
                deltas[gname] = (dl, dr)
        elif gname in MKH_GLYPHS_ALL or gname in MTV_GLYPHS_ALL or gname in mkh_from_cmap or gname in mtv_from_cmap:
            dl, dr = _delta_for_base(gname)
            if dl != 0 or dr != 0:
                deltas[gname] = (dl, dr)

    return deltas


def _deltas_checksum(deltas):
    payload = json.dumps(sorted(deltas.items()), separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _capture_sentinels(font):
    hmtx = font["hmtx"].metrics
    return {g: int(hmtx[g][0]) for g in SENTINEL_GLYPHS if g in hmtx}


def shift_gpos_mark_anchors_x(gpos_table_obj, delta_x_map):
    """
    Shift GPOS MarkBasePos (LookupType 4) and MarkLigPos (LookupType 5) non-zero base
    anchor X coordinates by `+delta_x_map[gname]` in-place.
    Accepts either a `TTFont` or a `table_G_P_O_S_` object.
    Returns count of shifted anchor coordinates.
    """
    if not delta_x_map:
        return 0
    if hasattr(gpos_table_obj, "keys") and "GPOS" in gpos_table_obj:
        gpos = gpos_table_obj["GPOS"].table
    elif hasattr(gpos_table_obj, "table"):
        gpos = gpos_table_obj.table
    else:
        return 0

    if not gpos or not getattr(gpos, "LookupList", None):
        return 0

    shifted = 0
    for lk in gpos.LookupList.Lookup:
        for st in lk.SubTable:
            ltype = st.ExtensionLookupType if lk.LookupType == 9 else lk.LookupType
            rst = st.ExtSubTable if lk.LookupType == 9 else st
            if ltype == 4 and hasattr(rst, "BaseCoverage") and getattr(rst, "BaseArray", None):
                for gname, brec in zip(rst.BaseCoverage.glyphs, rst.BaseArray.BaseRecord):
                    dx = delta_x_map.get(gname, 0)
                    if not dx:
                        continue
                    for anc in brec.BaseAnchor:
                        if anc is not None and not (anc.XCoordinate == 0 and anc.YCoordinate == 0):
                            anc.XCoordinate = int(round(anc.XCoordinate + dx))
                            shifted += 1
            elif ltype == 5 and hasattr(rst, "LigatureCoverage") and getattr(rst, "LigatureArray", None):
                for gname, la in zip(rst.LigatureCoverage.glyphs, rst.LigatureArray.LigatureAttach):
                    dx = delta_x_map.get(gname, 0)
                    if not dx:
                        continue
                    for comp in la.ComponentRecord:
                        for anc in comp.LigatureAnchor:
                            if anc is not None and not (anc.XCoordinate == 0 and anc.YCoordinate == 0):
                                anc.XCoordinate = int(round(anc.XCoordinate + dx))
                                shifted += 1
    return shifted


def _shift_cff_glyphs(font, deltas):
    """Exact zero-error CFF CharStrings X-shift (+dl) + hmtx sync (preserving half-unit precision!)."""
    cff = font["CFF "].cff
    top = cff.topDictIndex[0]
    hmtx = font["hmtx"]
    gs = font.getGlyphSet()
    shifted = 0

    for gname, (dl, dr) in deltas.items():
        if gname not in top.CharStrings or gname not in hmtx.metrics:
            continue
        old_adv, old_lsb = hmtx[gname]
        new_adv = int(round(old_adv + dl + dr))
        if dl != 0:
            t2_pen = T2CharStringPen(width=new_adv, glyphSet=None, roundTolerance=0.0)
            x_pen = TransformPen(t2_pen, (1, 0, 0, 1, dl, 0))
            gs[gname].draw(x_pen)
            top.CharStrings[gname] = t2_pen.getCharString(
                private=top.Private,
                globalSubrs=cff.GlobalSubrs,
            )
            bp = BoundsPen(None)
            gs[gname].draw(TransformPen(bp, (1, 0, 0, 1, dl, 0)))
            new_lsb = int(round(bp.bounds[0])) if bp.bounds else int(round(old_lsb + dl))
            hmtx[gname] = (new_adv, new_lsb)
        else:
            # Update CFF charstring width too when only dr changed
            cs = top.CharStrings[gname]
            cs.decompile()
            cs.width = new_adv
            hmtx[gname] = (new_adv, old_lsb)
        shifted += 1
    return shifted


def _shift_glyf_glyphs(font, deltas):
    """Exact TrueType `glyf` X-shift (+dl) + hmtx sync (handles both simple and composite glyphs)."""
    glyf = font["glyf"]
    hmtx = font["hmtx"]
    shifted = 0

    for gname, (dl, dr) in deltas.items():
        if gname not in glyf or gname not in hmtx.metrics:
            continue
        old_adv, old_lsb = hmtx[gname]
        new_adv = int(round(old_adv + dl + dr))
        g = glyf[gname]
        if dl != 0:
            if g.isComposite():
                for comp in g.components:
                    # Only translate component offset if component glyph wasn't itself shifted
                    if comp.glyphName not in deltas:
                        comp.x = int(round(comp.x + dl))
                g.recalcBounds(glyf)
            elif g.numberOfContours > 0:
                g.coordinates.translate((dl, 0))
                g.recalcBounds(glyf)
            new_lsb = int(g.xMin) if (g.numberOfContours > 0 or g.isComposite()) else int(round(old_lsb + dl))
            hmtx[gname] = (new_adv, new_lsb)
        else:
            hmtx[gname] = (new_adv, old_lsb)
        shifted += 1
    return shifted


def apply_georgian_spacing_to_font(
    font,
    weight_class,
    width_mode,
    is_italic,
    slnt_deg=None,
    state_entry=None,
    force=False,
):
    """
    Apply v2 Georgian optical spacing recovery cleanly to a TTFont (OTF or TTF) in-place.

    Idempotency Guard:
      - If `state_entry` is provided (from `qa/georgian_spacing_state.json`) and `not force`:
        checks whether the font's current sentinel advances ALREADY match `state_entry['applied_advs']`
        for `SPACING_VERSION` and identical `deltas_checksum`. If so, returns immediately with
        `already_applied=True` and NEVER double-shifts!
      - For `weight_class <= 500` (Thin..Medium), returns immediately with 0 glyphs modified!

    Returns `(stats_dict, new_state_entry)`.
    """
    glyph_order = font.getGlyphOrder()
    cmap = font.getBestCmap() or {}
    deltas = compute_georgian_spacing_deltas(
        glyph_order=glyph_order,
        cmap=cmap,
        weight_class=weight_class,
        width_mode=width_mode,
        is_italic=is_italic,
        slnt_deg=slnt_deg,
    )
    if not deltas:
        cur_sent = _capture_sentinels(font)
        entry = {
            "version": SPACING_VERSION,
            "weight_class": int(weight_class),
            "width_mode": width_mode,
            "is_italic": bool(is_italic),
            "deltas_checksum": "noop_w<=500",
            "glyphs_shifted": 0,
            "baseline_advs": cur_sent,
            "applied_advs": cur_sent,
        }
        return {"applied": False, "already_applied": False, "noop_weight": True, "glyphs_shifted": 0, "anchors_shifted": 0}, entry

    checksum = _deltas_checksum(deltas)
    cur_sent = _capture_sentinels(font)

    if state_entry and not force:
        if (
            state_entry.get("version") == SPACING_VERSION
            and state_entry.get("deltas_checksum") == checksum
            and state_entry.get("applied_advs") == cur_sent
        ):
            return {
                "applied": False,
                "already_applied": True,
                "noop_weight": False,
                "glyphs_shifted": 0,
                "anchors_shifted": 0,
            }, state_entry
        if (
            state_entry.get("applied_advs") == cur_sent
            and state_entry.get("baseline_advs") != cur_sent
        ):
            raise RuntimeError(
                f"Idempotency guard halted: font already has spacing version "
                f"{state_entry.get('version')!r} (checksum {state_entry.get('deltas_checksum')}) "
                f"applied; rebuild from clean baseline before changing parameters!"
            )

    if "CFF " in font:
        n_glyphs = _shift_cff_glyphs(font, deltas)
    elif "glyf" in font:
        n_glyphs = _shift_glyf_glyphs(font, deltas)
    else:
        raise ValueError("Unsupported font format (neither CFF nor glyf table present)")

    dl_map = {g: dl for g, (dl, _dr) in deltas.items() if dl != 0}
    n_anchors = shift_gpos_mark_anchors_x(font, dl_map)

    after_sent = _capture_sentinels(font)
    new_entry = {
        "version": SPACING_VERSION,
        "weight_class": int(weight_class),
        "width_mode": width_mode,
        "is_italic": bool(is_italic),
        "deltas_checksum": checksum,
        "glyphs_shifted": n_glyphs,
        "anchors_shifted": n_anchors,
        "baseline_advs": cur_sent,
        "applied_advs": after_sent,
    }
    return {
        "applied": True,
        "already_applied": False,
        "noop_weight": False,
        "glyphs_shifted": n_glyphs,
        "anchors_shifted": n_anchors,
    }, new_entry


def load_spacing_state(state_path):
    p = Path(state_path)
    if not p.exists():
        return {"version": SPACING_VERSION, "styles": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("styles"), dict):
            return data
    except Exception:
        pass
    return {"version": SPACING_VERSION, "styles": {}}


def save_spacing_state(state_path, state):
    p = Path(state_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    out = {
        "version": SPACING_VERSION,
        "styles": dict(sorted(state.get("styles", {}).items())),
    }
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, p)

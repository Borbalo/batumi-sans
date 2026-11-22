#!/usr/bin/env python3
"""
Independent World-Class Georgian Type Critic & QA Auditor for src/condenser.py (Milestone 1).

Builds temporary QA fonts in qa/condenser_audit/tmp_fonts/ combining:
- Condensed & Extra Condensed: condenser's Georgian + official FiraSansCondensed / FiraSansCompressed Latin
- Expanded: condenser's Georgian + condenser's Latin/digits/punctuation

Runs independent metrology, slant, counter-openness, skia-pathops topology checks,
and generates visual diagnostic sheets (full 33 Mkhedruli + 33 Mtavruli + Lari + ss01 + archaic,
zoomed vector overlays, and bilingual rhythm proofs) for direct visual inspection.
"""

import argparse
import json
import math
import os
import sys
import numpy as np
from fontTools.ttLib import TTFont
from fontTools.pens.t2CharStringPen import T2CharStringPen
from PIL import Image, ImageDraw, ImageFont

QA_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(QA_DIR)
sys.path.insert(0, QA_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "src"))

import qa_geometry as qg
import condenser

FONTS_HOME = os.path.expanduser("~/Library/Fonts")
REF_COND_DIR = os.path.join(BASE_DIR, "reference_fonts", "firasans_condensed")
REF_XCON_DIR = os.path.join(BASE_DIR, "reference_fonts", "firasans_extracondensed")
OUT_DIR = os.path.join(QA_DIR, "condenser_audit")
TMP_DIR = os.path.join(OUT_DIR, "tmp_fonts")

AUDIT_STYLES = [
    ("Thin",             False, "Thin",       100),
    ("ExtraLight",       False, "ExtraLight", 200),
    ("Light",            False, "Light",      300),
    ("Regular",          False, "Regular",    400),
    ("Medium",           False, "Medium",     500),
    ("SemiBold",         False, "SemiBold",   600),
    ("Bold",             False, "Bold",       700),
    ("ExtraBold",        False, "ExtraBold",  800),
    ("Heavy",            False, "Heavy",      900),
    ("ThinItalic",       True,  "Thin",       100),
    ("ExtraLightItalic", True,  "ExtraLight", 200),
    ("LightItalic",      True,  "Light",      300),
    ("Italic",           True,  "Regular",    400),
    ("MediumItalic",     True,  "Medium",     500),
    ("SemiBoldItalic",   True,  "SemiBold",   600),
    ("BoldItalic",       True,  "Bold",       700),
    ("ExtraBoldItalic",  True,  "ExtraBold",  800),
    ("HeavyItalic",      True,  "Heavy",      900),
]

# Note: FiraGO filename suffixes use "Italic" for Regular Italic, "BoldItalic" for Bold Italic, etc.
def firago_path(style_suffix):
    return os.path.join(FONTS_HOME, f"FiraGO-{style_suffix}.otf")

def ref_latin_path(mode, style_suffix):
    if mode == "condensed":
        return os.path.join(REF_COND_DIR, f"FiraSansCondensed-{style_suffix}.otf")
    if mode == "extra_condensed":
        return os.path.join(REF_XCON_DIR, f"FiraSansCompressed-{style_suffix}.otf")
    return None


def map_mtavruli_cmap(font):
    gset = set(font.getGlyphOrder())
    for sub in font["cmap"].tables:
        if sub.isUnicode():
            for off in range(0x00, 0x30):
                cn = f"uni{0x10D0 + off:04X}.case"
                if cn in gset:
                    sub.cmap[0x1C90 + off] = cn


def build_qa_font(mode, style_suffix, weight_name, is_italic):
    """Build a standalone QA OTF to inspect & measure condenser output directly."""
    src_path = firago_path(style_suffix)
    font = TTFont(src_path)
    cff_top = font["CFF "].cff.topDictIndex[0]
    cs = cff_top.CharStrings
    hmtx = font["hmtx"]
    gset = set(font.getGlyphOrder())
    cm = font.getBestCmap()

    tr = condenser.WidthTransformer(
        font=font,
        mode=mode,
        weight=weight_name,
        is_italic=is_italic,
    )

    geo_glyphs = qg.collect_georgian_glyphs(font)
    curr_glyphs = qg.collect_currency_glyphs(font)
    quote_glyphs = qg.collect_quote_glyphs(font)
    # Basic Latin + Latin-1 + digits + punctuation + all 19 currencies + 10 Georgian quotes
    lat_glyphs = []
    for cp in (list(range(0x0021, 0x007F)) + [0x00B7, 0x2013, 0x2014, 0x2022]
               + qg.CURRENCY_CODEPOINTS + qg.GEORGIAN_QUOTE_CODEPOINTS):
        g = cm.get(cp)
        if g and g in gset and g not in lat_glyphs:
            lat_glyphs.append(g)

    # 1. Transform Georgian glyphs + uni060B (Afghani) + uni20BE (Lari) via condenser;
    #    For Expanded, also transform ALL Basic Latin + ALL 19 currency glyphs + 10 Georgian quotes!
    transformed_glyphs = list(geo_glyphs)
    for g in ("uni060B", "uni20BE"):
        if g in gset and g not in transformed_glyphs:
            transformed_glyphs.append(g)
    if mode == "expanded":
        for g in lat_glyphs + curr_glyphs + quote_glyphs:
            if g in gset and g not in transformed_glyphs:
                transformed_glyphs.append(g)

    transform_errors = []
    for gname in transformed_glyphs:
        try:
            new_contours, new_adv, lsb_delta = tr.transform_glyph(gname)
            pen = T2CharStringPen(width=int(round(new_adv)), glyphSet=None)
            condenser.draw_contours_to_pen(new_contours, pen, round_coords=True)
            cs[gname] = pen.getCharString(private=cff_top.Private, globalSubrs=font["CFF "].cff.GlobalSubrs)
            # Recompute actual lsb from new_contours bounds
            b = condenser.contours_bounds(new_contours)
            new_lsb = int(round(b[0])) if b else hmtx[gname][1]
            hmtx[gname] = (int(round(new_adv)), new_lsb)
        except Exception as exc:
            transform_errors.append(f"{gname}: {exc}")

    # 2. For Condensed / Extra Condensed: splice official FiraSansCondensed / Compressed Latin + 17 currencies
    ref_p = ref_latin_path(mode, style_suffix)
    if ref_p and os.path.exists(ref_p):
        ref_f = TTFont(ref_p)
        ref_gs = ref_f.getGlyphSet()
        ref_hmtx = ref_f["hmtx"]
        ref_gset = set(ref_f.getGlyphOrder())
        for gname in lat_glyphs + curr_glyphs:
            if gname in ("uni060B", "uni20BE"):
                continue  # transformed by condenser
            if gname in ref_gset:
                adv, lsb = ref_hmtx[gname]
                pen = T2CharStringPen(width=adv, glyphSet=None)
                ref_gs[gname].draw(pen)
                cs[gname] = pen.getCharString(private=cff_top.Private, globalSubrs=font["CFF "].cff.GlobalSubrs)
                hmtx[gname] = (adv, lsb)
        ref_f.close()

    map_mtavruli_cmap(font)
    os.makedirs(TMP_DIR, exist_ok=True)
    out_p = os.path.join(TMP_DIR, f"QA_{mode}_{style_suffix}.otf")
    font.save(out_p)
    font.close()
    return out_p, transformed_glyphs, transform_errors


def render_full_georgian_grid(otf_path, mode, style_suffix, out_path):
    """Render ALL 33 Mkhedruli + ALL 33 Mtavruli + Lari + archaic + ss01 at crisp size."""
    f_tt = TTFont(otf_path)
    gset = set(f_tt.getGlyphOrder())
    f_pil = ImageFont.truetype(otf_path, 76)
    try:
        lbl = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
        small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 11)
    except Exception:
        lbl = small = ImageFont.load_default()

    # Sections: Mkhedruli (33), Mtavruli (33), Archaic (15), All 19 Currencies, plus ss01 vector panel
    sections = [
        ("33 Modern Mkhedruli (U+10D0..U+10F0)", list(qg.MKH_MODERN)),
        ("33 Modern Mtavruli (U+1C90..U+1CB0)", list(qg.MTV_MODERN)),
        ("Archaic / Extended (U+10F1..U+10FF)", [chr(cp) for cp in list(range(0x10F1, 0x1100)) if cp != 0x10FB]),
        ("All 19 Currency Signs (Sc)", [chr(cp) for cp in qg.CURRENCY_CODEPOINTS]),
    ]

    cols = 11
    cell_w, cell_h = 128, 126
    margin = 24
    # Compute total height
    h = margin + 40
    for _, chars in sections:
        rows = (len(chars) + cols - 1) // cols
        h += 34 + rows * cell_h + 16
    # Add ss01 vector row
    ss01_present = [g for g in ("uni10E2.ss01", "uni10E8.ss01", "uni10EC.ss01", "uni10EF.ss01", "uni10DD.ss01", "uni10E0.ss01") if g in gset]
    h += 34 + cell_h + 30

    w = margin * 2 + cols * cell_w
    img = Image.new("RGB", (w, h), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((margin, 14), f"Borbalo GO Condenser QA — {mode.upper()} · {style_suffix} (Full Georgian Inventory)", fill=(15, 20, 35), font=lbl)

    y_cur = margin + 40
    for title, chars in sections:
        draw.rectangle([(margin, y_cur), (w - margin, y_cur + 26)], fill=(242, 245, 250))
        draw.text((margin + 10, y_cur + 5), title, fill=(35, 45, 65), font=lbl)
        y_cur += 34
        rows = (len(chars) + cols - 1) // cols
        for idx, ch in enumerate(chars):
            r, c = divmod(idx, cols)
            x0 = margin + c * cell_w
            y0 = y_cur + r * cell_h
            draw.rectangle([(x0, y0), (x0 + cell_w - 4, y0 + cell_h - 4)], outline=(232, 235, 240))
            draw.text((x0 + 5, y0 + 3), f"U+{ord(ch):04X}", fill=(140, 145, 160), font=small)
            draw.text((x0 + 22, y0 + 22), ch, fill=(10, 10, 15), font=f_pil)
        y_cur += rows * cell_h + 16

    # Render ss01 alternates as crisp vector polygons/outlines (since Pillow doesn't activate ss01 without Raqm)
    draw.rectangle([(margin, y_cur), (w - margin, y_cur + 26)], fill=(242, 245, 250))
    draw.text((margin + 10, y_cur + 5), f"OpenType ss01 Alternates ({', '.join(ss01_present)})", fill=(35, 45, 65), font=lbl)
    y_cur += 34
    for idx, gname in enumerate(ss01_present):
        x0 = margin + idx * cell_w
        y0 = y_cur
        draw.rectangle([(x0, y0), (x0 + cell_w - 4, y0 + cell_h - 4)], outline=(232, 235, 240))
        draw.text((x0 + 5, y0 + 3), gname, fill=(140, 145, 160), font=small)
        polys = qg.glyph_to_polylines(f_tt, gname)
        sc = 0.085
        ox = x0 + 24
        oy = y0 + 96
        draw.line([(x0 + 6, oy), (x0 + cell_w - 10, oy)], fill=(220, 225, 235), width=1)
        qg.draw_glyph_on_canvas(draw, polys, ox, oy, sc, outline=(20, 20, 30), width=2)

    f_tt.close()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path)
    return out_path


def render_critical_vector_overlay(orig_otf, qa_otf, mode, style_suffix, out_path):
    """4x zoomed vector overlay: Blue = original FiraGO, Red = condensed/expanded, with guides & annotations."""
    f_orig = TTFont(orig_otf)
    f_qa = TTFont(qa_otf)
    ia = f_qa["post"].italicAngle

    glyphs = [
        ("ლ", "uni10DA"), ("დ", "uni10D3"), ("ღ", "uni10E6"), ("ო", "uni10DD"),
        ("რ", "uni10E0"), ("თ", "uni10D7"), ("ტ", "uni10E2"), ("ფ", "uni10E4"),
        ("გ", "uni10D2"), ("მ", "uni10DB"), ("ზ", "uni10D6"), ("ჭ", "uni10ED"),
        ("ჯ", "uni10EF"), ("₾", "uni20BE"), ("Ლ", "uni10DA.case"), ("Დ", "uni10D3.case"),
        ("Ღ", "uni10E6.case"), ("Ო", "uni10DD.case"), ("Რ", "uni10E0.case"), ("Ტ", "uni10E2.case"),
        ("Გ", "uni10D2.case"), ("Მ", "uni10DB.case"), ("Ჭ", "uni10ED.case"), ("Ჯ", "uni10EF.case"),
    ]
    if mode == "expanded":
        # Add key Latin glyphs to inspect Expanded Latin stems & bowls too!
        glyphs.extend([("H", "H"), ("O", "O"), ("R", "R"), ("a", "a"), ("g", "g"), ("o", "o")])

    cols = 6
    cell_w, cell_h = 260, 250
    rows = (len(glyphs) + cols - 1) // cols
    margin = 24
    w = margin * 2 + cols * cell_w
    h = margin * 2 + 44 + rows * cell_h
    img = Image.new("RGB", (w, h), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        lbl = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
        small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 12)
    except Exception:
        lbl = small = ImageFont.load_default()

    draw.text((margin, 14), f"Vector Overlay QA: {mode.upper()} · {style_suffix} — Blue=FiraGO Normal | Red=Transformed (baseline/xH=527/capH=689)", fill=(15, 20, 35), font=lbl)

    y_top = margin + 44
    sc = 0.19
    for idx, (ch, gname) in enumerate(glyphs):
        r, c = divmod(idx, cols)
        x0 = margin + c * cell_w
        y0 = y_top + r * cell_h
        draw.rectangle([(x0, y0), (x0 + cell_w - 6, y0 + cell_h - 6)], outline=(228, 232, 238))
        ox = x0 + 36
        oy = y0 + 185
        # Guides: baseline (0), x-height (527), cap-height (689)
        for gy, col in ((0, (205, 212, 224)), (527, (220, 235, 220)), (689, (225, 220, 235))):
            yp = oy - gy * sc
            draw.line([(x0 + 6, yp), (x0 + cell_w - 12, yp)], fill=col, width=1)
        p_orig = qg.glyph_to_polylines(f_orig, gname)
        p_qa = qg.glyph_to_polylines(f_qa, gname)
        qg.draw_glyph_on_canvas(draw, p_orig, ox, oy, sc, outline=(70, 130, 220), width=1)
        qg.draw_glyph_on_canvas(draw, p_qa, ox, oy, sc, outline=(215, 35, 35), width=2)

        aw0 = f_orig["hmtx"][gname][0]
        aw1 = f_qa["hmtx"][gname][0]
        cnt = qg.scan_counter_openness(f_qa, gname, ia)
        mg_str = f"gap={cnt['min_gap']:.0f}" if cnt["min_gap"] is not None else "gap=-"
        draw.text((x0 + 8, y0 + 6), f"{gname}  adv:{aw1}/{aw0} ({aw1/aw0*100:.1f}%)  {mg_str}", fill=(40, 45, 60), font=small)

    f_orig.close()
    f_qa.close()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path)
    return out_path


def render_bilingual_rhythm(qa_fonts_map, out_path):
    """Put Condensed, Extra Condensed, Normal, and Expanded Georgian right next to Latin on same lines."""
    styles = ["Regular", "Bold", "Heavy", "BoldItalic", "HeavyItalic"]
    modes = ["normal", "condensed", "extra_condensed", "expanded"]
    labels = {"normal": "Normal (FiraGO)", "condensed": "Condensed (Geo+FiraCond)",
              "extra_condensed": "ExtraCond (Geo+FiraXCon)", "expanded": "Expanded (Geo+Lat)"}

    sample = "თბილისი Tbilisi · საქართველო Georgia · ᲑᲝᲠᲑᲐᲚᲝ BORBALO · ლდღორთტფ ₾2026"
    row_h = 56
    block_h = 34 + len(modes) * row_h + 18
    w = 2200
    h = 70 + len(styles) * block_h
    img = Image.new("RGB", (w, h), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        title_f = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 20)
        lbl_f = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 15)
    except Exception:
        title_f = lbl_f = ImageFont.load_default()

    draw.text((24, 18), "Borbalo GO QA — Bilingual Georgian + Latin Optical Rhythm & Weight Parity Across All 4 Widths", fill=(15, 20, 35), font=title_f)
    y = 64
    for st in styles:
        draw.rectangle([(20, y), (w - 20, y + 28)], fill=(238, 242, 248))
        draw.text((30, y + 5), f"STYLE: {st}", fill=(20, 30, 50), font=lbl_f)
        y += 34
        for m in modes:
            p = firago_path(st) if m == "normal" else qa_fonts_map.get((m, st))
            if not p or not os.path.exists(p):
                continue
            f_pil = ImageFont.truetype(p, 40)
            draw.text((28, y + 12), f"{labels[m]:26s}", fill=(100, 105, 120), font=lbl_f)
            draw.text((255, y + 4), sample, fill=(12, 12, 16), font=f_pil)
            draw.line([(20, y + row_h - 2), (w - 20, y + row_h - 2)], fill=(242, 242, 245), width=1)
            y += row_h
        y += 18

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path)
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--modes", nargs="*", default=["condensed", "extra_condensed", "expanded"])
    args = parser.parse_args()

    report = {"modes": {}, "issues": []}
    qa_fonts_map = {}

    for mode in args.modes:
        report["modes"][mode] = {}
        print(f"\n{'='*80}\nAUDITING CONDENSER MODE: {mode.upper()}\n{'='*80}")
        for style_suffix, is_italic, weight_name, weight_class in AUDIT_STYLES:
            qa_otf, transformed_glyphs, tr_errs = build_qa_font(mode, style_suffix, weight_name, is_italic)
            qa_fonts_map[(mode, style_suffix)] = qa_otf

            f_orig = TTFont(firago_path(style_suffix))
            f_qa = TTFont(qa_otf)
            ia = f_qa["post"].italicAngle

            lat_m = qg.measure_latin_strokes(f_qa, ia)
            geo_m = qg.measure_georgian_strokes(f_qa, ia)
            n_lat = qg.measure_latin_strokes(f_orig, f_orig["post"].italicAngle)
            n_geo = qg.measure_georgian_strokes(f_orig, f_orig["post"].italicAngle)

            v_gl_ratio = geo_m["vstem_avg"] / lat_m["vstem_avg"] if lat_m["vstem_avg"] else 0
            h_gl_ratio = geo_m["hbar_avg"] / lat_m["hbar_avg"] if lat_m["hbar_avg"] else 0
            gv_vs_norm = geo_m["vstem_avg"] / n_geo["vstem_avg"] if n_geo["vstem_avg"] else 0
            gh_vs_norm = geo_m["hbar_avg"] / n_geo["hbar_avg"] if n_geo["hbar_avg"] else 0
            lv_vs_norm = lat_m["vstem_avg"] / n_lat["vstem_avg"] if n_lat["vstem_avg"] else 0
            lh_vs_norm = lat_m["hbar_avg"] / n_lat["hbar_avg"] if n_lat["hbar_avg"] else 0

            # Advance width ratios
            mkh_adv_r = float(np.mean([
                f_qa["hmtx"][f"uni{ord(c):04X}"][0] / f_orig["hmtx"][f"uni{ord(c):04X}"][0]
                for c in qg.MKH_MODERN
            ]))
            mtv_adv_r = float(np.mean([
                f_qa["hmtx"][f"uni{ord(c):04X}.case"][0] / f_orig["hmtx"][f"uni{ord(c):04X}.case"][0]
                for c in qg.MKH_MODERN
            ]))
            cm_qa = f_qa.getBestCmap()
            cm_or = f_orig.getBestCmap()
            lat_adv_r = float(np.mean([
                f_qa["hmtx"][cm_qa[ord(c)]][0] / f_orig["hmtx"][cm_or[ord(c)]][0]
                for c in "ABCDEFGHIKLMNOPRSTUVWabcdefghiklmnoprstuvw"
            ]))

            # Topology, inner hole area-ratio, & vertical alignment zone check on ALL transformed glyphs
            topo_issues = list(tr_errs)
            hole_issues = []
            y_drift_issues = []
            for g in transformed_glyphs:
                topo_issues.extend(qg.audit_glyph_topology(f_qa, g, is_ttf=False))
                hole_issues.extend(qg.audit_hole_area_ratios(f_orig, f_qa, g, mode, weight_class=weight_class))
                # Check y-bounds didn't drift off baseline / x-height / cap-height
                bo = qg.poly_bounds(qg.glyph_to_polylines(f_orig, g))
                bq = qg.poly_bounds(qg.glyph_to_polylines(f_qa, g))
                if bo and bq:
                    dy_bot = abs(bq[1] - bo[1])
                    dy_top = abs(bq[3] - bo[3])
                    if dy_bot > 10.0 or dy_top > 10.0:
                        y_drift_issues.append(f"{g}: y-drift bot={bq[1]-bo[1]:+.1f} top={bq[3]-bo[3]:+.1f}")

            # Counter openness on critical multi-arch glyphs
            counters = {}
            collapsed = []
            for cg in qg.CRITICAL_MULTI_ARCH:
                if cg in f_qa.getGlyphOrder():
                    sc = qg.scan_counter_openness(f_qa, cg, ia)
                    if sc["min_gap"] is not None:
                        counters[cg] = round(sc["min_gap"], 1)
                        if sc["min_gap"] < 14.0:
                            collapsed.append(f"{cg}={sc['min_gap']:.1f}u")

            style_issues = []
            # 1. Optical stroke parity (within ~5% -> 0.93..1.05, accounting for FiraGO baseline 0.98-0.99)
            if not (0.93 <= v_gl_ratio <= 1.05):
                style_issues.append(f"GEO/LAT VSTEM DELTA >5%: ratio={v_gl_ratio:.3f} (Geo={geo_m['vstem_avg']:.1f}, Lat={lat_m['vstem_avg']:.1f})")
            if not (0.92 <= h_gl_ratio <= 1.06):
                style_issues.append(f"GEO/LAT HBAR DELTA: ratio={h_gl_ratio:.3f} (Geo={geo_m['hbar_avg']:.1f}, Lat={lat_m['hbar_avg']:.1f})")
            if geo_m["hbar_avg"] > geo_m["vstem_avg"] * 1.02:
                style_issues.append(f"REVERSE CONTRAST: Geo hbar={geo_m['hbar_avg']:.1f} > vstem={geo_m['vstem_avg']:.1f}")
            # 2. Expanded anti-bloat check
            if mode == "expanded":
                if gv_vs_norm > 1.065:
                    style_issues.append(f"EXPANDED GEO STEM BLOAT: {gv_vs_norm:.3f}x Normal")
                if lv_vs_norm > 1.065:
                    style_issues.append(f"EXPANDED LAT STEM BLOAT: {lv_vs_norm:.3f}x Normal")
                if gh_vs_norm < 0.95:
                    style_issues.append(f"EXPANDED GEO THIN HBAR: {gh_vs_norm:.3f}x Normal")
                if lh_vs_norm < 0.95:
                    style_issues.append(f"EXPANDED LAT THIN HBAR: {lh_vs_norm:.3f}x Normal")
            # 3. Italic exact -8 deg slant check
            if is_italic:
                if abs(geo_m["slant_deg"] - (-8.0)) > 0.5:
                    style_issues.append(f"ITALIC SLANT DRIFT: Geo={geo_m['slant_deg']:.2f}° (target -8.0°)")
                if abs(geo_m["slant_deg"] - lat_m["slant_deg"]) > 0.5:
                    style_issues.append(f"ITALIC SLANT MISMATCH: Geo={geo_m['slant_deg']:.2f}° vs Lat={lat_m['slant_deg']:.2f}°")
            if topo_issues:
                style_issues.append(f"TOPOLOGY ISSUES ({len(topo_issues)}): {topo_issues[:5]}")
            if hole_issues:
                style_issues.append(f"HOLE COUNTER PINCH/COLLAPSE ({len(hole_issues)}): {hole_issues[:8]}")
            if y_drift_issues:
                style_issues.append(f"Y-ZONE DRIFT ({len(y_drift_issues)}): {y_drift_issues[:5]}")
            if collapsed:
                style_issues.append(f"TIGHT/COLLAPSED COUNTERS: {', '.join(collapsed)}")

            rec = {
                "geo_v": round(geo_m["vstem_avg"], 1),
                "lat_v": round(lat_m["vstem_avg"], 1),
                "v_gl_ratio": round(v_gl_ratio, 3),
                "gv_vs_norm": round(gv_vs_norm, 3),
                "lv_vs_norm": round(lv_vs_norm, 3),
                "geo_h": round(geo_m["hbar_avg"], 1),
                "lat_h": round(lat_m["hbar_avg"], 1),
                "h_gl_ratio": round(h_gl_ratio, 3),
                "gh_vs_norm": round(gh_vs_norm, 3),
                "geo_slant": round(geo_m["slant_deg"], 2),
                "lat_slant": round(lat_m["slant_deg"], 2),
                "mkh_adv_pct": round(mkh_adv_r * 100, 2),
                "mtv_adv_pct": round(mtv_adv_r * 100, 2),
                "lat_adv_pct": round(lat_adv_r * 100, 2),
                "topo_count": len(topo_issues),
                "y_drift_count": len(y_drift_issues),
                "counters": counters,
                "issues": style_issues,
            }
            report["modes"][mode][style_suffix] = rec
            if style_issues:
                report["issues"].append((mode, style_suffix, style_issues))

            status = "PASS" if not style_issues else f"WARN/FAIL ({len(style_issues)})"
            print(
                f"  [{status:14s}] {style_suffix:12s} | "
                f"adv Mkh={rec['mkh_adv_pct']:5.1f}% Mtv={rec['mtv_adv_pct']:5.1f}% Lat={rec['lat_adv_pct']:5.1f}% | "
                f"v={rec['geo_v']:5.1f}/{rec['lat_v']:5.1f} ({rec['v_gl_ratio']:.3f}, {rec['gv_vs_norm']:.3f}N) | "
                f"h={rec['geo_h']:5.1f}/{rec['lat_h']:5.1f} ({rec['h_gl_ratio']:.3f}) | "
                f"sl={rec['geo_slant']:+5.2f}/{rec['lat_slant']:+5.2f} | topo={rec['topo_count']}"
            )
            for si in style_issues:
                print(f"      -> {si}")

            # Render visual proofs for Regular, Bold, Heavy, BoldItalic, HeavyItalic
            if style_suffix in ("Regular", "Bold", "Heavy", "BoldItalic", "HeavyItalic"):
                render_full_georgian_grid(
                    qa_otf, mode, style_suffix,
                    os.path.join(OUT_DIR, f"grid_all_{mode}_{style_suffix}.png"),
                )
            if style_suffix in ("Regular", "Heavy", "BoldItalic", "HeavyItalic"):
                render_critical_vector_overlay(
                    firago_path(style_suffix), qa_otf, mode, style_suffix,
                    os.path.join(OUT_DIR, f"overlay_critical_{mode}_{style_suffix}.png"),
                )

            f_orig.close()
            f_qa.close()

    # Bilingual rhythm master comparison across all 4 widths
    p_bi = render_bilingual_rhythm(qa_fonts_map, os.path.join(OUT_DIR, "bilingual_rhythm_all_modes.png"))
    print(f"\nRendered bilingual master proof: {p_bi}")

    rep_p = os.path.join(OUT_DIR, "condenser_audit_report.json")
    with open(rep_p, "w", encoding="utf-8") as fp:
        json.dump(report, fp, indent=2, ensure_ascii=False)
    print(f"Report saved: {rep_p}")
    print(f"Total flagged mode-styles: {len(report['issues'])}")
    sys.exit(0 if not report["issues"] else 2)


if __name__ == "__main__":
    main()

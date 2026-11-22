#!/usr/bin/env python3
"""
Independent Automated + Visual Superfamily QA Auditor for Batumi Sans.
Verifies ALL 8 subfamilies x 18 styles x 3 formats (OTF, TTF, WOFF2) + CSS.

Can be run incrementally (e.g. --subfamilies normal normal_rounded) or full (--all).
"""

import argparse
import os
import re
import sys
import json
from collections import defaultdict
from fontTools.ttLib import TTFont
from fontTools.pens.boundsPen import BoundsPen
from PIL import Image, ImageDraw, ImageFont
import numpy as np

QA_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(QA_DIR)
sys.path.insert(0, QA_DIR)
import qa_geometry as qg

DIST_DIR = os.path.join(BASE_DIR, "dist")
OUT_DIR = os.path.join(QA_DIR, "build_audit")

EXPECTED_STYLES = [
    ("Thin",             100, False, False),
    ("ExtraLight",       200, False, False),
    ("Light",            300, False, False),
    ("Regular",          400, False, False),
    ("Medium",           500, False, False),
    ("SemiBold",         600, False, False),
    ("Bold",             700, True,  False),
    ("ExtraBold",        800, False, False),
    ("Heavy",            900, False, False),
    ("ThinItalic",       100, False, True),
    ("ExtraLightItalic", 200, False, True),
    ("LightItalic",      300, False, True),
    ("Italic",           400, False, True),
    ("MediumItalic",     500, False, True),
    ("SemiBoldItalic",   600, False, True),
    ("BoldItalic",       700, True,  True),
    ("ExtraBoldItalic",  800, False, True),
    ("HeavyItalic",      900, False, True),
]

SUBFAMILY_EXPECTATIONS = {
    "BatumiSansExtraCondensed": {
        "family": "Batumi Sans Extra Condensed",
        "width_class": 2,
        "rounded": False,
        "sharp_peer": None,
        "normal_peer": "BatumiSans",
        "mode": "extra_condensed",
    },
    "BatumiSansCondensed": {
        "family": "Batumi Sans Condensed",
        "width_class": 3,
        "rounded": False,
        "sharp_peer": None,
        "normal_peer": "BatumiSans",
        "mode": "condensed",
    },
    "BatumiSans": {
        "family": "Batumi Sans",
        "width_class": 5,
        "rounded": False,
        "sharp_peer": None,
        "normal_peer": None,
        "mode": "normal",
    },
    "BatumiSansExpanded": {
        "family": "Batumi Sans Expanded",
        "width_class": 7,
        "rounded": False,
        "sharp_peer": None,
        "normal_peer": "BatumiSans",
        "mode": "expanded",
    },
    "BatumiSansExtraCondensedRounded": {
        "family": "Batumi Sans Extra Condensed Rounded",
        "width_class": 2,
        "rounded": True,
        "sharp_peer": "BatumiSansExtraCondensed",
        "normal_peer": "BatumiSansRounded",
        "mode": "extra_condensed",
    },
    "BatumiSansCondensedRounded": {
        "family": "Batumi Sans Condensed Rounded",
        "width_class": 3,
        "rounded": True,
        "sharp_peer": "BatumiSansCondensed",
        "normal_peer": "BatumiSansRounded",
        "mode": "condensed",
    },
    "BatumiSansRounded": {
        "family": "Batumi Sans Rounded",
        "width_class": 5,
        "rounded": True,
        "sharp_peer": "BatumiSans",
        "normal_peer": None,
        "mode": "normal",
    },
    "BatumiSansExpandedRounded": {
        "family": "Batumi Sans Expanded Rounded",
        "width_class": 7,
        "rounded": True,
        "sharp_peer": "BatumiSansExpanded",
        "normal_peer": "BatumiSansRounded",
        "mode": "expanded",
    },
}

VALID_RIBBI = {"Regular", "Bold", "Italic", "Bold Italic"}


def check_metadata(font, ps_prefix, style_suffix, exp_wclass, exp_bold, exp_italic, exp_width_class, exp_family):
    """Audit name table RIBBI, RFN leaks, OS/2 weight/width/fsSelection, head.macStyle, CFF names."""
    issues = []
    name_tbl = font["name"]

    def get_name(nid):
        rec = name_tbl.getName(nid, 3, 1, 0x409)
        return rec.toUnicode() if rec else None

    # 1. Zero "Fira" Reserved Font Name leaks AND zero stale "Borbalo" family-name leaks in nameID 1, 3, 4, 6, 16, 17
    # Note: Per Google Fonts `googlefonts/font_names`, RIBBI styles (Regular/Bold/Italic/Bold Italic)
    # MUST omit redundant nameID 16/17!
    is_ribbi_style = style_suffix in ("Regular", "Bold", "Italic", "BoldItalic")
    for nid in (1, 3, 4, 6, 16, 17):
        val = get_name(nid)
        if val is None:
            if nid in (16, 17) and is_ribbi_style:
                continue
            issues.append(f"nameID {nid} missing (Win/Unicode/en-US)")
        elif "fira" in val.lower():
            issues.append(f"RFN LEAK in nameID {nid}: {val!r}")
        elif "borbalo" in val.lower():
            issues.append(f"STALE BRAND LEAK in nameID {nid}: {val!r}")

    # 2. RIBBI nameID 2 check
    n2 = get_name(2)
    if n2 not in VALID_RIBBI:
        issues.append(f"nameID 2 not valid RIBBI: {n2!r}")
    else:
        exp_n2 = ("Bold Italic" if (exp_bold and exp_italic)
                  else "Bold" if exp_bold
                  else "Italic" if exp_italic
                  else "Regular")
        if n2 != exp_n2:
            issues.append(f"nameID 2 mismatch: got {n2!r}, expected {exp_n2!r}")

    # 3. Typographic family nameID 16
    n16 = get_name(16)
    if n16 and n16 != exp_family:
        issues.append(f"nameID 16 mismatch: got {n16!r}, expected {exp_family!r}")

    # 4. OS/2 usWeightClass & usWidthClass
    os2 = font["OS/2"]
    if os2.usWeightClass != exp_wclass:
        issues.append(f"OS/2.usWeightClass={os2.usWeightClass}, expected {exp_wclass}")
    if os2.usWidthClass != exp_width_class:
        issues.append(f"OS/2.usWidthClass={os2.usWidthClass}, expected {exp_width_class}")

    # 5. OS/2 fsSelection & head macStyle consistency with RIBBI bold/italic
    fs = os2.fsSelection
    mac = font["head"].macStyle
    if bool(fs & 0x01) != exp_italic:
        issues.append(f"OS/2.fsSelection ITALIC bit={bool(fs & 0x01)}, expected {exp_italic}")
    if bool(mac & 0x02) != exp_italic:
        issues.append(f"head.macStyle ITALIC bit={bool(mac & 0x02)}, expected {exp_italic}")
    if bool(fs & 0x20) != exp_bold:
        issues.append(f"OS/2.fsSelection BOLD bit={bool(fs & 0x20)}, expected {exp_bold}")
    if bool(mac & 0x01) != exp_bold:
        issues.append(f"head.macStyle BOLD bit={bool(mac & 0x01)}, expected {exp_bold}")
    exp_reg = (not exp_bold) and (not exp_italic)
    if bool(fs & 0x40) != exp_reg:
        issues.append(f"OS/2.fsSelection REGULAR bit={bool(fs & 0x40)}, expected {exp_reg}")

    # 6. post.italicAngle check
    ia = font["post"].italicAngle
    if exp_italic and abs(ia - (-8.0)) > 0.5:
        issues.append(f"post.italicAngle={ia}, expected ~-8.0 for Italic")
    elif (not exp_italic) and abs(ia) > 0.1:
        issues.append(f"post.italicAngle={ia}, expected 0.0 for Upright")

    # 7. CFF table RFN & stale brand leak check (for OTF)
    if "CFF " in font:
        cff = font["CFF "].cff
        for fn in cff.fontNames:
            if "fira" in fn.lower() or "borbalo" in fn.lower():
                issues.append(f"RFN/BRAND LEAK in CFF.fontNames: {fn!r}")
        td = cff.topDictIndex[0]
        for attr in ("FullName", "FamilyName"):
            v = getattr(td, attr, "")
            if v and ("fira" in v.lower() or "borbalo" in v.lower()):
                issues.append(f"RFN/BRAND LEAK in CFF.{attr}: {v!r}")

    return issues


def check_cmap_and_opentype(font):
    """Verify Unicode Mtavruli U+1C90..U+1CBF cmap + GSUB (case, ss01, ccmp) + GPOS (kern)."""
    issues = []
    cm = font.getBestCmap()
    gset = set(font.getGlyphOrder())

    # 1. All 33 Mkhedruli + all 19 currency signs (#21) + all 10 Georgian quotes (#24/#25/#27)
    for ch in qg.MKH_MODERN:
        if ord(ch) not in cm:
            issues.append(f"cmap missing U+{ord(ch):04X} ({ch})")
    missing_curr = [f"U+{cp:04X}" for cp in qg.CURRENCY_CODEPOINTS if cp not in cm]
    if missing_curr:
        issues.append(f"cmap missing currency signs: {missing_curr}")
    missing_quotes = [f"U+{cp:04X}" for cp in qg.GEORGIAN_QUOTE_CODEPOINTS if cp not in cm]
    if missing_quotes:
        issues.append(f"cmap missing Georgian quotes: {missing_quotes}")

    # 2. All 46 Unicode Mtavruli U+1C90..U+1CBA, U+1CBD..U+1CBF
    missing_mtv = []
    for cp in qg.MTAVRULI_CODEPOINTS:
        g = cm.get(cp)
        if not g:
            missing_mtv.append(f"U+{cp:04X}")
        elif g not in gset:
            issues.append(f"cmap U+{cp:04X} -> missing glyph {g}")
    if missing_mtv:
        issues.append(f"cmap missing {len(missing_mtv)} Mtavruli codepoints (e.g. {missing_mtv[:5]})")

    # 3. OpenType GSUB: case, ss01, ccmp
    if "GSUB" not in font:
        issues.append("GSUB table missing!")
    else:
        feats = {fr.FeatureTag for fr in font["GSUB"].table.FeatureList.FeatureRecord}
        for req in ("case", "ss01", "ccmp"):
            if req not in feats:
                issues.append(f"GSUB missing required feature '{req}'")
        # Check that 'case' actually maps Georgian Mkhedruli -> .case
        case_maps_geo = False
        for fr in font["GSUB"].table.FeatureList.FeatureRecord:
            if fr.FeatureTag == "case":
                for li in fr.Feature.LookupListIndex:
                    lk = font["GSUB"].table.LookupList.Lookup[li]
                    for st in lk.SubTable:
                        mapping = getattr(st, "mapping", {})
                        if "uni10D0" in mapping and mapping["uni10D0"] == "uni10D0.case":
                            case_maps_geo = True
        if not case_maps_geo:
            issues.append("GSUB 'case' does not map uni10D0 -> uni10D0.case")

        # Check ss01 maps Georgian alternates (Upright: uni10E2->.ss01; Italic: uni10DD/uni10E0->.ss01)
        ss01_maps_geo = False
        for fr in font["GSUB"].table.FeatureList.FeatureRecord:
            if fr.FeatureTag == "ss01":
                for li in fr.Feature.LookupListIndex:
                    lk = font["GSUB"].table.LookupList.Lookup[li]
                    for st in lk.SubTable:
                        mapping = getattr(st, "mapping", {})
                        if (mapping.get("uni10E2") == "uni10E2.ss01"
                                or mapping.get("uni10DD") == "uni10DD.ss01"
                                or mapping.get("uni10E0") == "uni10E0.ss01"):
                            ss01_maps_geo = True
        if not ss01_maps_geo:
            issues.append("GSUB 'ss01' does not map Georgian .ss01 alternates")

    # 4. OpenType GPOS: kern
    if "GPOS" not in font:
        issues.append("GPOS table missing!")
    else:
        gpos_feats = {fr.FeatureTag for fr in font["GPOS"].table.FeatureList.FeatureRecord}
        if "kern" not in gpos_feats:
            issues.append("GPOS missing 'kern' feature")

    return issues


def check_freetype_render(font_path):
    """Verify Pillow FreeType loads and renders Mkhedruli + Mtavruli + Latin + Lari without error/blank."""
    try:
        pil_font = ImageFont.truetype(font_path, 48)
        img = Image.new("L", (1100, 90), 255)
        draw = ImageDraw.Draw(img)
        draw.text((12, 16), "თბილისი ᲗᲑᲘᲚᲘᲡᲘ Tbilisi 2026 ₾120", font=pil_font, fill=0)
        arr = np.array(img)
        ink_px = int(np.sum(arr < 200))
        if ink_px < 1500:
            return [f"FreeType render nearly blank ({ink_px} dark pixels)"]
        return []
    except Exception as exc:
        return [f"FreeType load/render FAILED: {exc}"]


def check_rounded_vs_sharp(sharp_font, round_font, glyphs):
    """Catch slid rounded hooks, short-stub blowups, or collapsed counters vs sharp counterpart."""
    issues = []
    gs_s = sharp_font.getGlyphSet()
    gs_r = round_font.getGlyphSet()
    for g in glyphs:
        if g not in gs_s or g not in gs_r:
            continue
        ps = qg.glyph_to_pathops(sharp_font, g)
        pr = qg.glyph_to_pathops(round_font, g)
        if not ps.bounds or not pr.bounds:
            continue
        # Contour count check
        cs_n = len(list(ps.contours))
        cr_n = len(list(pr.contours))
        if cs_n != cr_n:
            issues.append(f"{g}: contour count changed sharp->round ({cs_n} -> {cr_n})")
        sx0, sy0, sx1, sy1 = ps.bounds
        rx0, ry0, rx1, ry1 = pr.bounds
        grow = max(sx0 - rx0, sy0 - ry0, rx1 - sx1, ry1 - sy1)
        shrink = max(rx0 - sx0, ry0 - sy0, sx1 - rx1, sy1 - ry1)
        if grow > 60:
            issues.append(f"{g}: rounded bbox blew up by {grow:.1f}u vs sharp")
        if shrink > 85:
            issues.append(f"{g}: rounded bbox shrunk/slid by {shrink:.1f}u vs sharp")
        sa, ra = abs(ps.area), abs(pr.area)
        if sa > 3000 and (sa - ra) / sa > 0.16:
            issues.append(f"{g}: rounded area dropped {(sa-ra)/sa*100:.1f}% vs sharp")
    return issues


def check_css(dist_dir):
    """Verify dist/batumi-sans.css references existing non-empty font files with zero broken paths or stale Borbalo leaks."""
    css_path = os.path.join(dist_dir, "batumi-sans.css")
    if not os.path.exists(css_path):
        return [f"Missing stylesheet: {css_path}"], 0
    with open(css_path, "r", encoding="utf-8") as fp:
        txt = fp.read()
    urls = re.findall(r"url\(['\"]?([^'\")]+)['\"]?\)", txt)
    issues = []
    if not urls:
        issues.append("batumi-sans.css contains zero url() declarations!")
    if "borbalo" in txt.lower():
        issues.append("STALE BRAND LEAK ('borbalo') in batumi-sans.css!")
    # Verify zero stale BorbaloGO* files left behind in dist/
    for sub in ("", "otf", "ttf", "woff2"):
        d = os.path.join(dist_dir, sub) if sub else dist_dir
        if os.path.isdir(d):
            stale = [fn for fn in os.listdir(d) if "borbalo" in fn.lower()]
            if stale:
                issues.append(f"STALE BORBALO FILES in dist/{sub}: {stale[:5]}")
    for u in urls:
        full = os.path.normpath(os.path.join(dist_dir, u))
        if not os.path.exists(full):
            issues.append(f"CSS broken path: {u} -> {full}")
        elif os.path.getsize(full) < 1000:
            issues.append(f"CSS tiny/corrupt file: {u} ({os.path.getsize(full)} bytes)")
    return issues, len(urls)


def render_otf_vs_ttf_sheet(dist_dir, prefixes, out_path):
    """Side-by-side FreeType OTF vs TTF render check for visual inspection."""
    styles = ["Regular", "Bold", "Heavy", "BoldItalic"]
    row_h = 84
    w = 2320
    h = 100 + len(prefixes) * len(styles) * row_h
    img = Image.new("RGB", (w, h), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        lbl_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
    except Exception:
        lbl_font = ImageFont.load_default()
    draw.text((24, 24), "Borbalo GO QA — OTF (left) vs TTF (right) FreeType Raster Parity Check", fill=(20, 20, 20), font=lbl_font)
    sample = "თბილისი ᲗᲑᲘᲚᲘᲡᲘ ლდღორთტფჭჯ₾ · Tbilisi 2026"
    y = 75
    for pref in prefixes:
        for st in styles:
            otf_p = os.path.join(dist_dir, "otf", f"{pref}-{st}.otf")
            ttf_p = os.path.join(dist_dir, "ttf", f"{pref}-{st}.ttf")
            if not (os.path.exists(otf_p) and os.path.exists(ttf_p)):
                continue
            draw.line([(20, y - 6), (w - 20, y - 6)], fill=(235, 235, 235), width=1)
            draw.text((24, y), f"{pref}-{st}", fill=(90, 90, 100), font=lbl_font)
            f_o = ImageFont.truetype(otf_p, 36)
            f_t = ImageFont.truetype(ttf_p, 36)
            draw.text((24, y + 22), "OTF: " + sample, fill=(15, 15, 20), font=f_o)
            draw.text((1170, y + 22), "TTF: " + sample, fill=(15, 40, 95), font=f_t)
            y += row_h
    img = img.crop((0, 0, w, max(y + 20, 200)))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path)
    return out_path



def render_critical_rounded_sheet(dist_dir, prefix, styles, out_path):
    """Zoomed FreeType grid of critical Georgian + Mtavruli + Latin + all 19 currency glyphs for QA."""
    chars = list("ლდღორთტფგმზწჭჟჯშᲚᲓᲦᲝᲠᲗᲢᲤᲒᲛᲭᲯHBRgosa08") + [chr(cp) for cp in qg.CURRENCY_CODEPOINTS]
    cols = 14
    cell_w, cell_h = 130, 145
    rows_per_style = (len(chars) + cols - 1) // cols
    margin = 30
    header_h = 46
    total_h = margin + len(styles) * (header_h + rows_per_style * cell_h + 24)
    total_w = margin * 2 + cols * cell_w
    img = Image.new("RGB", (total_w, total_h), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        lbl = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 18)
        small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 12)
    except Exception:
        lbl = small = ImageFont.load_default()

    y_cur = margin
    for st in styles:
        otf_p = os.path.join(dist_dir, "otf", f"{prefix}-{st}.otf")
        if not os.path.exists(otf_p):
            continue
        draw.rectangle([(margin, y_cur), (total_w - margin, y_cur + 34)], fill=(242, 245, 250))
        draw.text((margin + 12, y_cur + 7), f"{prefix}-{st} (Critical Glyphs @ 96px)", fill=(20, 25, 40), font=lbl)
        y_cur += header_h
        f = ImageFont.truetype(otf_p, 92)
        for idx, ch in enumerate(chars):
            r, c = divmod(idx, cols)
            x0 = margin + c * cell_w
            y0 = y_cur + r * cell_h
            draw.rectangle([(x0, y0), (x0 + cell_w - 4, y0 + cell_h - 4)], outline=(232, 234, 238))
            draw.text((x0 + 6, y0 + 4), f"U+{ord(ch):04X}", fill=(140, 145, 155), font=small)
            draw.text((x0 + 24, y0 + 22), ch, fill=(10, 10, 15), font=f)
        y_cur += rows_per_style * cell_h + 24

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path)
    return out_path



def render_bani_mtavruli_compare(dist_dir, out_path):
    """Side-by-side 120px Sharp vs Rounded comparison of Ბ (U+1C91) and ბ (U+10D1) across all 4 widths & Bold..Heavy."""
    pairs = [
        ("Normal", "BatumiSans", "BatumiSansRounded"),
        ("Condensed", "BatumiSansCondensed", "BatumiSansCondensedRounded"),
        ("ExtraCond", "BatumiSansExtraCondensed", "BatumiSansExtraCondensedRounded"),
        ("Expanded", "BatumiSansExpanded", "BatumiSansExpandedRounded"),
    ]
    weights = ["Regular", "Bold", "ExtraBold", "Heavy", "HeavyItalic"]
    active = [(lbl, sp, rp) for (lbl, sp, rp) in pairs
              if os.path.exists(os.path.join(dist_dir, "otf", f"{sp}-Heavy.otf"))
              and os.path.exists(os.path.join(dist_dir, "otf", f"{rp}-Heavy.otf"))]
    if not active:
        return None
    col_w = 340
    row_h = 165
    margin = 24
    w = margin * 2 + 130 + len(weights) * col_w
    h = margin * 2 + 48 + len(active) * row_h
    img = Image.new("RGB", (w, h), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        title_f = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 20)
        lbl_f = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 15)
    except Exception:
        title_f = lbl_f = ImageFont.load_default()
    draw.text((margin, 14), "Borbalo GO QA — Mtavruli Ბ (U+1C91) & Mkhedruli ბ Finial Check: Sharp (Black) vs Rounded (Blue)", fill=(15, 20, 35), font=title_f)
    for wi, wt in enumerate(weights):
        draw.text((margin + 135 + wi * col_w, 46), wt, fill=(60, 70, 90), font=lbl_f)
    y = 72
    for lbl, sp, rp in active:
        draw.line([(margin, y - 4), (w - margin, y - 4)], fill=(228, 232, 238), width=1)
        draw.text((margin, y + 60), lbl, fill=(30, 35, 50), font=lbl_f)
        for wi, wt in enumerate(weights):
            x0 = margin + 130 + wi * col_w
            sp_p = os.path.join(dist_dir, "otf", f"{sp}-{wt}.otf")
            rp_p = os.path.join(dist_dir, "otf", f"{rp}-{wt}.otf")
            if os.path.exists(sp_p):
                fs = ImageFont.truetype(sp_p, 112)
                draw.text((x0 + 8, y + 14), "Ბბ", fill=(15, 15, 20), font=fs)
            if os.path.exists(rp_p):
                fr = ImageFont.truetype(rp_p, 112)
                draw.text((x0 + 168, y + 14), "Ბბ", fill=(15, 60, 165), font=fr)
        y += row_h
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path)
    return out_path



def render_zhar_quotes_currencies_sheet(dist_dir, prefixes, out_path):
    """Visual check for ჟრ/ჟს/ჟბ/ჟჩ spacing, Georgian quotes „“«», and all 19 currency signs."""
    styles = ["Bold", "Heavy", "BoldItalic", "HeavyItalic"]
    row_h = 68
    w = 2250
    h = 90 + len(prefixes) * len(styles) * row_h
    img = Image.new("RGB", (w, h), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        title_f = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 19)
        lbl_f = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
    except Exception:
        title_f = lbl_f = ImageFont.load_default()
    draw.text((24, 18), "Borbalo GO QA — ჟრ/ჟს/ჟბ/ჟჩ Spacing · Georgian Quotes „ქართული“ «» · All 19 Currency Signs", fill=(15, 20, 35), font=title_f)
    sample = "ჟრ ჟს ჟბ ჟჩ თბილისი · „ქართული“ «ქართული» ‚‘’”‹› · $ ¢ £ ¤ ¥ ฿ ₡ ₦ ₩ ₪ ₫ € ₯ ₴ ₹ ₺ ₽ ₾"
    y = 66
    for pref in prefixes:
        for st in styles:
            p = os.path.join(dist_dir, "otf", f"{pref}-{st}.otf")
            if not os.path.exists(p):
                continue
            draw.line([(20, y - 4), (w - 20, y - 4)], fill=(238, 240, 244), width=1)
            draw.text((24, y + 18), f"{pref}-{st}", fill=(90, 95, 110), font=lbl_f)
            f = ImageFont.truetype(p, 40)
            draw.text((340, y + 8), sample, fill=(12, 12, 18), font=f)
            y += row_h
    img = img.crop((0, 0, w, max(y + 20, 200)))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path)
    return out_path


def render_cyrillic_math_punct_sheet(dist_dir, prefixes, out_path):
    """Visual QA sheet for Rounded/Expanded Cyrillic (Д Ж Ц Щ Я Й Ф), Punctuation & Math/Arrows (#40/#42)."""
    styles = ["Regular", "Bold", "Heavy", "HeavyItalic"]
    row_h = 112
    w = 2320
    h = 90 + len(prefixes) * len(styles) * row_h
    img = Image.new("RGB", (w, h), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        title_f = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 19)
        lbl_f = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 13)
    except Exception:
        title_f = lbl_f = ImageFont.load_default()
    draw.text((24, 18), "Borbalo GO QA — Cyrillic (А–Я а–я ДЖЦЩЯЙФ), Punctuation & Math/Arrows (±×÷≠≤≥≈∞√∑∫←→)", fill=(15, 20, 35), font=title_f)
    line1 = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ · Д Ж Ц Щ Я Й Ф · абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
    line2 = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ · αβγδεζηθικλμνξοπρσςτυφχψω · ἈἉἊἋἌἍἎἏ ἘἙ ἨἩ ὈὉ Ὑ ὨὩ ᾶ ῆ ῖ ῦ ῶ"
    line3 = "± × ÷ ≠ ≤ ≥ ≈ ∞ √ ∑ ∏ ∂ ∆ ∫ ← → ↑ ↓ ↔ · ! ? « » „ “ — – … § ¶ † ‡ • ¿ ¡ ( ) [ ] { }"
    row_h = 150
    h = 90 + len(prefixes) * len(styles) * row_h
    img = Image.new("RGB", (w, h), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((24, 18), "Borbalo GO QA — Cyrillic (А–Я ДЖЦЩЯ), Greek & Polytonic (Α–Ω α–ω Ἀ–ῶ), Punctuation & Math/Arrows", fill=(15, 20, 35), font=title_f)
    y = 64
    for pref in prefixes:
        if pref not in ("BatumiSansExpanded", "BatumiSansRounded", "BatumiSansCondensedRounded",
                        "BatumiSansExtraCondensedRounded", "BatumiSansExpandedRounded"):
            continue
        for st in styles:
            p = os.path.join(dist_dir, "otf", f"{pref}-{st}.otf")
            if not os.path.exists(p):
                continue
            draw.line([(20, y - 4), (w - 20, y - 4)], fill=(234, 237, 242), width=1)
            draw.text((24, y + 52), f"{pref}-{st}", fill=(85, 90, 108), font=lbl_f)
            f = ImageFont.truetype(p, 33)
            draw.text((345, y + 6), line1, fill=(12, 12, 18), font=f)
            draw.text((345, y + 52), line2, fill=(15, 75, 45), font=f)
            draw.text((345, y + 98), line3, fill=(25, 45, 90), font=f)
            y += row_h
    img = img.crop((0, 0, w, max(y + 20, 200)))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path)
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefixes", nargs="*", default=None,
                        help="Subset of PS prefixes to audit (default: all present in dist/otf)")
    parser.add_argument("--quick-styles", action="store_true",
                        help="Only audit key styles (Thin, Regular, Bold, Heavy, BoldItalic, HeavyItalic)")
    parser.add_argument("--no-images", action="store_true")
    args = parser.parse_args()

    otf_dir = os.path.join(DIST_DIR, "otf")
    ttf_dir = os.path.join(DIST_DIR, "ttf")
    woff2_dir = os.path.join(DIST_DIR, "woff2")

    if args.prefixes:
        prefixes = args.prefixes
    else:
        prefixes = [p for p in SUBFAMILY_EXPECTATIONS
                    if os.path.exists(os.path.join(otf_dir, f"{p}-Regular.otf"))]

    if not prefixes:
        print("NO built fonts found in", otf_dir)
        sys.exit(1)

    styles_to_run = EXPECTED_STYLES
    if args.quick_styles:
        keep = {"Thin", "Regular", "Bold", "Heavy", "BoldItalic", "HeavyItalic"}
        styles_to_run = [s for s in EXPECTED_STYLES if s[0] in keep]

    summary = {"prefixes": prefixes, "files_checked": 0, "failures": defaultdict(list), "metrics": {}}
    total_issues = 0

    for pref in prefixes:
        spec = SUBFAMILY_EXPECTATIONS[pref]
        print(f"\n{'='*76}\nAUDITING SUBFAMILY: {spec['family']} ({pref}, widthClass={spec['width_class']})\n{'='*76}")
        for suffix, wclass, is_bold, is_italic in styles_to_run:
            otf_p = os.path.join(otf_dir, f"{pref}-{suffix}.otf")
            ttf_p = os.path.join(ttf_dir, f"{pref}-{suffix}.ttf")
            w2_p = os.path.join(woff2_dir, f"{pref}-{suffix}.woff2")

            style_key = f"{pref}-{suffix}"
            issues = []

            for tag, p in (("OTF", otf_p), ("TTF", ttf_p), ("WOFF2", w2_p)):
                if not os.path.exists(p):
                    issues.append(f"MISSING {tag}: {p}")
                elif os.path.getsize(p) < 5000:
                    issues.append(f"TINY {tag}: {os.path.getsize(p)} bytes")

            if os.path.exists(otf_p):
                summary["files_checked"] += 1
                f_otf = TTFont(otf_p)
                issues.extend(check_metadata(f_otf, pref, suffix, wclass, is_bold, is_italic,
                                             spec["width_class"], spec["family"]))
                issues.extend(check_cmap_and_opentype(f_otf))
                issues.extend(check_freetype_render(otf_p))

                # Topology audit on Georgian + Ampersands + 19 currencies + 10 quotes + Cyrillic + Greek + Punctuation + Math/Arrows + Basic Latin
                geo_glyphs = qg.collect_georgian_glyphs(f_otf)
                amp_glyphs = [g for g in ("ampersand.geor", "ampersand.geor.case") if g in f_otf.getGlyphOrder()]
                curr_glyphs = qg.collect_currency_glyphs(f_otf)
                quote_glyphs = qg.collect_quote_glyphs(f_otf)
                cyr_glyphs = qg.collect_cyrillic_glyphs(f_otf)
                grk_glyphs = qg.collect_greek_glyphs(f_otf)
                punct_glyphs = qg.collect_punctuation_glyphs(f_otf)
                math_glyphs = qg.collect_math_arrow_glyphs(f_otf)
                cm = f_otf.getBestCmap()
                lat_glyphs = [cm[cp] for cp in range(0x0021, 0x007F) if cp in cm]
                audit_glyphs = list(dict.fromkeys(
                    geo_glyphs + amp_glyphs + curr_glyphs + quote_glyphs + cyr_glyphs + grk_glyphs + punct_glyphs + math_glyphs + lat_glyphs
                ))
                # Official L1.07b (±44.5u + -14u CapH tuck) Mtavruli vertical-cue check
                _, l107b_iss = qg.check_mtavruli_l107(f_otf, is_italic=is_italic)
                if l107b_iss:
                    issues.extend([f"L1.07b: {m}" for m in l107b_iss])
                topo_otf = []
                for g in audit_glyphs:
                    for m in qg.audit_glyph_topology(f_otf, g, is_ttf=False):
                        if "split contours" in m:
                            # Ignore sub-pixel dust (<25u^2) if total area delta < 0.5%
                            import pathops
                            pr = qg.glyph_to_pathops(f_otf, g)
                            ps = pathops.simplify(pr, clockwise=False)
                            real_n = 0
                            for c in ps.contours:
                                cp_p = pathops.Path(); c.draw(cp_p.getPen())
                                if abs(cp_p.area) > 25.0:
                                    real_n += 1
                            if real_n <= len(qg.glyph_contour_paths(f_otf, g)) and abs(abs(pr.area) - abs(ps.area)) / max(abs(pr.area), 1.0) < 0.005:
                                continue
                        topo_otf.append(m)
                if topo_otf:
                    issues.extend([f"OTF-TOPO: {m}" for m in topo_otf[:15]])
                    if len(topo_otf) > 15:
                        issues.append(f"OTF-TOPO: ... and {len(topo_otf)-15} more")

                # ჟრ / ჟს / ჟბ / ჟჩ collision check (#24/#25/#27)
                if suffix in ("Bold", "ExtraBold", "Heavy", "BoldItalic", "ExtraBoldItalic", "HeavyItalic"):
                    min_allowed = 32.0 if spec["mode"] == "extra_condensed" else 40.0 if spec["mode"] == "condensed" else 48.0
                    for g1, g2 in qg.CRITICAL_ZHAR_PAIRS:
                        gap = qg.measure_pair_min_gap(f_otf, g1, g2)
                        if gap is not None and gap < min_allowed:
                            kval = qg.lookup_gpos_kern(f_otf, g1, g2)
                            issues.append(f"ZHAR-COLLISION: {g1}+{g2} min_gap={gap:.1f}u < {min_allowed:.0f}u (kern={kval})")

                # Hole counter area-ratio check vs Normal peer (catches pinched/twisted counters like #20 uni10D7!)
                if spec["mode"] != "normal" and spec["normal_peer"]:
                    norm_peer_p = os.path.join(otf_dir, f"{spec['normal_peer']}-{suffix}.otf")
                    if os.path.exists(norm_peer_p):
                        f_np = TTFont(norm_peer_p)
                        hole_check_glyphs = list(dict.fromkeys(geo_glyphs + curr_glyphs + (lat_glyphs if spec["mode"] == "expanded" else [])))
                        hole_warns = []
                        for g in hole_check_glyphs:
                            if g in f_np.getGlyphSet() and g in f_otf.getGlyphSet():
                                hole_warns.extend(qg.audit_hole_area_ratios(f_np, f_otf, g, spec["mode"], weight_class=wclass))
                        if hole_warns:
                            issues.extend([f"HOLE-GUARD: {m}" for m in hole_warns[:15]])
                            if len(hole_warns) > 15:
                                issues.append(f"HOLE-GUARD: ... and {len(hole_warns)-15} more")
                        f_np.close()

                # Rounded vs Sharp guard
                if spec["rounded"] and spec["sharp_peer"]:
                    sharp_p = os.path.join(otf_dir, f"{spec['sharp_peer']}-{suffix}.otf")
                    if os.path.exists(sharp_p):
                        f_sharp = TTFont(sharp_p)
                        rvs = check_rounded_vs_sharp(f_sharp, f_otf, audit_glyphs)
                        if rvs:
                            issues.extend([f"ROUND-GUARD: {m}" for m in rvs[:15]])
                            if len(rvs) > 15:
                                issues.append(f"ROUND-GUARD: ... and {len(rvs)-15} more")
                        f_sharp.close()

                # Optical stroke & slant & counter check on representative weights
                if suffix in ("Regular", "Bold", "Heavy", "BoldItalic", "HeavyItalic"):
                    ia = f_otf["post"].italicAngle
                    lat_m = qg.measure_latin_strokes(f_otf, ia)
                    geo_m = qg.measure_georgian_strokes(f_otf, ia)
                    v_ratio = geo_m["vstem_avg"] / lat_m["vstem_avg"] if lat_m["vstem_avg"] > 0 else 0
                    h_ratio = geo_m["hbar_avg"] / lat_m["hbar_avg"] if lat_m["hbar_avg"] > 0 else 0
                    min_counters = {}
                    for cg in ("uni10DA", "uni10D3", "uni10E6", "uni10DD", "uni10E0", "uni10E2", "uni10E4", "uni10ED"):
                        sc = qg.scan_counter_openness(f_otf, cg, ia)
                        if sc["min_gap"] is not None:
                            min_counters[cg] = round(sc["min_gap"], 1)
                    summary["metrics"][style_key] = {
                        "lat_v": round(lat_m["vstem_avg"], 1),
                        "geo_v": round(geo_m["vstem_avg"], 1),
                        "v_ratio": round(v_ratio, 3),
                        "lat_h": round(lat_m["hbar_avg"], 1),
                        "geo_h": round(geo_m["hbar_avg"], 1),
                        "h_ratio": round(h_ratio, 3),
                        "lat_slant": round(lat_m["slant_deg"], 2),
                        "geo_slant": round(geo_m["slant_deg"], 2),
                        "min_counters": min_counters,
                    }
                    # Flag optical mismatches
                    if not (0.92 <= v_ratio <= 1.06):
                        issues.append(f"OPTICAL VSTEM MISMATCH: Geo/Lat={v_ratio:.3f} (Geo={geo_m['vstem_avg']:.1f}, Lat={lat_m['vstem_avg']:.1f})")
                    if is_italic and abs(geo_m["slant_deg"] - lat_m["slant_deg"]) > 0.6:
                        issues.append(f"ITALIC SLANT MISMATCH: Geo={geo_m['slant_deg']:.2f} vs Lat={lat_m['slant_deg']:.2f}")
                    if is_italic and abs(geo_m["slant_deg"] - (-8.0)) > 0.6:
                        issues.append(f"ITALIC SLANT DRIFT FROM -8 DEG: Geo={geo_m['slant_deg']:.2f}, Lat={lat_m['slant_deg']:.2f}")
                    if geo_m["hbar_avg"] > geo_m["vstem_avg"] * 1.03:
                        issues.append(f"REVERSE CONTRAST: Geo hbar={geo_m['hbar_avg']:.1f} > vstem={geo_m['vstem_avg']:.1f}")
                    for cg, mg in min_counters.items():
                        if mg < 12.0:
                            issues.append(f"COLLAPSED COUNTER: {cg} min_gap={mg:.1f}u")

                    # Check Expanded against Normal peer (no stem bloat, no thin horizontals, ~115% width)
                    if spec["mode"] == "expanded" and spec["normal_peer"]:
                        norm_p = os.path.join(otf_dir, f"{spec['normal_peer']}-{suffix}.otf")
                        if os.path.exists(norm_p):
                            f_norm = TTFont(norm_p)
                            n_lat = qg.measure_latin_strokes(f_norm, f_norm["post"].italicAngle)
                            n_geo = qg.measure_georgian_strokes(f_norm, f_norm["post"].italicAngle)
                            gv_vs_norm = geo_m["vstem_avg"] / n_geo["vstem_avg"] if n_geo["vstem_avg"] else 0
                            lv_vs_norm = lat_m["vstem_avg"] / n_lat["vstem_avg"] if n_lat["vstem_avg"] else 0
                            gh_vs_norm = geo_m["hbar_avg"] / n_geo["hbar_avg"] if n_geo["hbar_avg"] else 0
                            lh_vs_norm = lat_m["hbar_avg"] / n_lat["hbar_avg"] if n_lat["hbar_avg"] else 0
                            # Advance width ratio on modern Mkhedruli + A-Z/a-z
                            geo_adv_r = np.mean([
                                f_otf["hmtx"][f"uni{ord(c):04X}"][0] / f_norm["hmtx"][f"uni{ord(c):04X}"][0]
                                for c in qg.MKH_MODERN
                                if f"uni{ord(c):04X}" in f_otf["hmtx"].metrics and f_norm["hmtx"][f"uni{ord(c):04X}"][0] > 0
                            ])
                            lat_adv_r = np.mean([
                                f_otf["hmtx"][cm[ord(c)]][0] / f_norm["hmtx"][f_norm.getBestCmap()[ord(c)]][0]
                                for c in "ABCDEFGHIKLMNOPRSTUVWabcdefghiklmnoprstuvw"
                                if ord(c) in cm and ord(c) in f_norm.getBestCmap()
                            ])
                            summary["metrics"][style_key].update({
                                "exp_geo_v_vs_norm": round(gv_vs_norm, 3),
                                "exp_lat_v_vs_norm": round(lv_vs_norm, 3),
                                "exp_geo_h_vs_norm": round(gh_vs_norm, 3),
                                "exp_lat_h_vs_norm": round(lh_vs_norm, 3),
                                "exp_geo_adv_ratio": round(float(geo_adv_r), 3),
                                "exp_lat_adv_ratio": round(float(lat_adv_r), 3),
                            })
                            if gv_vs_norm > 1.07:
                                issues.append(f"EXPANDED GEO STEM BLOAT: {gv_vs_norm:.3f}x Normal (target ~1.00-1.03)")
                            if lv_vs_norm > 1.07:
                                issues.append(f"EXPANDED LAT STEM BLOAT: {lv_vs_norm:.3f}x Normal (target ~1.00-1.03)")
                            if gh_vs_norm < 0.94:
                                issues.append(f"EXPANDED GEO THIN HBAR: {gh_vs_norm:.3f}x Normal")
                            if lh_vs_norm < 0.94:
                                issues.append(f"EXPANDED LAT THIN HBAR: {lh_vs_norm:.3f}x Normal")
                            if not (1.10 <= geo_adv_r <= 1.20):
                                issues.append(f"EXPANDED GEO WIDTH OUT OF RANGE: {geo_adv_r:.3f}x")
                            if not (1.10 <= lat_adv_r <= 1.20):
                                issues.append(f"EXPANDED LAT WIDTH OUT OF RANGE: {lat_adv_r:.3f}x")
                            f_norm.close()
                f_otf.close()

            if os.path.exists(ttf_p):
                summary["files_checked"] += 1
                f_ttf = TTFont(ttf_p)
                issues.extend(check_freetype_render(ttf_p))
                # Verify TTF winding (CW outer!) on Georgian + Ampersands + 19 currencies + quotes + Cyrillic + Punct + Math + Basic Latin
                geo_glyphs = qg.collect_georgian_glyphs(f_ttf)
                amp_glyphs_ttf = [g for g in ("ampersand.geor", "ampersand.geor.case") if g in f_ttf.getGlyphOrder()]
                curr_glyphs = qg.collect_currency_glyphs(f_ttf)
                quote_glyphs = qg.collect_quote_glyphs(f_ttf)
                cyr_glyphs = qg.collect_cyrillic_glyphs(f_ttf)
                punct_glyphs = qg.collect_punctuation_glyphs(f_ttf)
                math_glyphs = qg.collect_math_arrow_glyphs(f_ttf)
                cm = f_ttf.getBestCmap()
                lat_sample = [cm[cp] for cp in range(0x0021, 0x007F) if cp in cm]
                topo_ttf = []
                for g in list(dict.fromkeys(
                    geo_glyphs + amp_glyphs_ttf + curr_glyphs + quote_glyphs + cyr_glyphs + punct_glyphs + math_glyphs + lat_sample
                )):
                    for m in qg.audit_glyph_topology(f_ttf, g, is_ttf=True):
                        if "split contours" in m:
                            import pathops
                            pr = qg.glyph_to_pathops(f_ttf, g)
                            ps = pathops.simplify(pr, clockwise=True)
                            real_n = 0
                            for c in ps.contours:
                                cp_p = pathops.Path(); c.draw(cp_p.getPen())
                                if abs(cp_p.area) > 25.0:
                                    real_n += 1
                            if real_n <= len(qg.glyph_contour_paths(f_ttf, g)) and abs(abs(pr.area) - abs(ps.area)) / max(abs(pr.area), 1.0) < 0.005:
                                continue
                        topo_ttf.append(m)
                if topo_ttf:
                    issues.extend([f"TTF-TOPO: {m}" for m in topo_ttf[:15]])
                    if len(topo_ttf) > 15:
                        issues.append(f"TTF-TOPO: ... and {len(topo_ttf)-15} more")
                f_ttf.close()

            if os.path.exists(w2_p):
                summary["files_checked"] += 1
                try:
                    f_w2 = TTFont(w2_p)
                    if f_w2.flavor != "woff2":
                        issues.append(f"WOFF2 invalid flavor: {f_w2.flavor}")
                    f_w2.close()
                except Exception as exc:
                    issues.append(f"WOFF2 corrupt: {exc}")

            if issues:
                summary["failures"][style_key] = issues
                total_issues += len(issues)
                print(f"  [FAIL] {style_key} ({len(issues)} issues):")
                for iss in issues[:10]:
                    print(f"         - {iss}")
                if len(issues) > 10:
                    print(f"         ... +{len(issues)-10} more")
            else:
                m_str = ""
                if style_key in summary["metrics"]:
                    m = summary["metrics"][style_key]
                    m_str = f" | v={m['geo_v']}/{m['lat_v']} ({m['v_ratio']:.3f}) h={m['geo_h']}/{m['lat_h']} sl={m['geo_slant']:+.2f}/{m['lat_slant']:+.2f}"
                print(f"  [PASS] {style_key}{m_str}")

    # CSS check
    css_issues, css_urls = check_css(DIST_DIR)
    print(f"\nCSS CHECK (batumi-sans.css, {css_urls} url entries): {'PASS' if not css_issues else f'FAIL ({len(css_issues)} issues)'}")
    for ci in css_issues[:15]:
        print("  -", ci)
    if css_issues:
        summary["failures"]["batumi-sans.css"] = css_issues
        total_issues += len(css_issues)

    # Save machine-readable JSON report
    os.makedirs(OUT_DIR, exist_ok=True)
    rep_path = os.path.join(OUT_DIR, "audit_report.json")
    with open(rep_path, "w", encoding="utf-8") as fp:
        json.dump(summary, fp, indent=2, ensure_ascii=False)

    # Render visual verification PNGs
    if not args.no_images:
        p1 = render_otf_vs_ttf_sheet(DIST_DIR, prefixes, os.path.join(OUT_DIR, "otf_vs_ttf_parity.png"))
        print(f"Rendered: {p1}")
        p_bani = render_bani_mtavruli_compare(DIST_DIR, os.path.join(OUT_DIR, "qa_bani_mtavruli_compare.png"))
        if p_bani:
            print(f"Rendered: {p_bani}")
        p_zqc = render_zhar_quotes_currencies_sheet(DIST_DIR, prefixes, os.path.join(OUT_DIR, "qa_zhar_quotes_currencies.png"))
        print(f"Rendered: {p_zqc}")
        p_cmp = render_cyrillic_math_punct_sheet(DIST_DIR, prefixes, os.path.join(OUT_DIR, "qa_cyrillic_math_punct_rounded.png"))
        print(f"Rendered: {p_cmp}")
        for pref in prefixes:
            if SUBFAMILY_EXPECTATIONS[pref]["rounded"]:
                p2 = render_critical_rounded_sheet(
                    DIST_DIR, pref, ["Regular", "Bold", "Heavy", "HeavyItalic"],
                    os.path.join(OUT_DIR, f"critical_{pref}.png"),
                )
                print(f"Rendered: {p2}")

    print(f"\nTOTAL FILES CHECKED: {summary['files_checked']} | TOTAL ISSUES: {total_issues}")
    print(f"Report saved: {rep_path}")
    sys.exit(0 if total_issues == 0 else 2)


if __name__ == "__main__":
    main()

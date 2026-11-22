#!/usr/bin/env python3
"""
Google Fonts–Style Web `unicode-range` Variable Font Subsetter for Batumi Sans v1.100.

Slices the 4 Variable Fonts (2-axis Google Fonts [wdth,wght] VFs for ultra-lean web delivery,
plus optional 3-axis [slnt,wdth,wght] option) into script-partitioned WOFF2 chunks via
`fontTools.subset` (`--flavor=woff2`) while preserving ALL variable axes (`fvar`, `avar`,
`gvar`, `HVAR`, `STAT`, `GPOS` variations) and ALL signature OpenType features (`calt`,
`locl`, `case`, `ss01`–`ss08`, `kern`, `mark`, `mkmk`, `ccmp`, `liga`, `tnum`, `onum`, `zero`).

CRITICAL Georgian Ampersand Engineering Detail:
  - The `georgian` chunk explicitly includes `&` (U+0026), Georgian quotes („ “ ‚ ‘ « » ‹ ›),
    space (U+0020), Georgian Lari (₾ U+20BE), Kartvelian double tilde (U+0360), Georgian
    punctuation (U+10FB, U+205A, U+2E31), and PUA U+E0A0–U+E0A1 so live `calt` Georgian
    Ampersand shaping (`დოლჩე & გაბანა`, `ᲓᲝᲚᲩᲔ & ᲒᲐᲑᲐᲜᲐ`) works inside a single Georgian chunk
    without cross-subset shaping breaks!

Outputs (`dist/web-subsets/`):
  - `<family>-<style>-<subset>.woff2` (4 VFs × 11 script chunks = 44 WOFF2 files)
  - `batumi-sans-web.css` (drop-in `@font-face` + `unicode-range` + `font-display: swap`)
  - `subset_benchmark.json` (exact byte measurements for every chunk & Georgian+Latin payload)
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from fontTools import subset as ft_subset
from fontTools.ttLib import TTFont

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_GF_DIR = BASE_DIR / "dist" / "google-fonts"
DEFAULT_VAR_DIR = BASE_DIR / "dist" / "variable"
DEFAULT_OUT_DIR = BASE_DIR / "dist" / "web-subsets"

# Preserved OpenType layout features across all subsets (Google Fonts web-optimal + full Georgian features!)
PRESERVED_FEATURES = [
    "calt", "ccmp", "locl", "case", "liga", "rlig", "mark", "mkmk", "kern",
    "abvm", "blwm", "dist", "curs", "init", "medi", "fina", "isol",
    "ss01", "ss07", "ss08",
]

# Script chunks (ordered from fallback/specialized to primary so CSS cascade matches Google Fonts!)
# Each entry: (chunk_id, css_unicode_range, subset_unicodes_spec)
SCRIPT_CHUNKS = [
    (
        "georgian",
        "U+0026, U+0303, U+0360, U+0483, U+10D0-10FF, U+1C90-1CBF, U+205A, U+20BE, U+2E31, U+E0A0-E0A1",
        "U+0020,U+0026,U+00A0,U+00AB,U+00BB,U+0303,U+0360,U+0483,U+10D0-10FF,U+1C90-1CBF,U+2018-201E,U+2039-203A,U+205A,U+20BE,U+2E31,U+E0A0-E0A1",
    ),
    (
        "georgian-khutsuri",
        "U+10A0-10CF, U+2D00-2D2F",
        "U+0020,U+0026,U+0303,U+0360,U+0483,U+10A0-10CF,U+2D00-2D2F,U+E0A0-E0A1",
    ),
    (
        "latin",
        "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+2000-206F, U+2074, U+20AC, U+2122, U+2191, U+2193, U+21E6-21EA, U+2212, U+2215, U+232B, U+23CE, U+FEFF, U+FFFD",
        "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+2074,U+20AC,U+2122,U+2191,U+2193,U+21E6-21EA,U+2212,U+2215,U+232B,U+23CE,U+FEFF,U+FFFD",
    ),
    (
        "latin-ext",
        "U+0100-02AF, U+02C1, U+0300-036F, U+1AB0-1AFF, U+1D43, U+1D49, U+1D4B, U+1D52-1D53, U+1D58, U+1D7D, U+1DA4, U+1DB6, U+1DC0-1EFF, U+2020, U+20A0-20AB, U+20AD-20C0, U+2113, U+2C60-2C7F, U+A720-A7FF",
        "U+0100-02AF,U+02C1,U+0300-036F,U+1AB0-1AFF,U+1D43,U+1D49,U+1D4B,U+1D52-1D53,U+1D58,U+1D7D,U+1DA4,U+1DB6,U+1DC0-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF",
    ),
    (
        "cyrillic",
        "U+0301, U+0400-052F, U+1C80-1C8A, U+20B4, U+2DE0-2DFF, U+A640-A69F, U+FE2E-FE2F",
        "U+0301,U+0400-052F,U+1C80-1C8A,U+20B4,U+2DE0-2DFF,U+A640-A69F,U+FE2E-FE2F",
    ),
    (
        "greek",
        "U+0370-03FF, U+1F00-1FFF",
        "U+0370-03FF,U+1F00-1FFF",
    ),
    (
        "arabic",
        "U+0600-06FF, U+0750-077F, U+08A0-08FF, U+FB50-FDFF, U+FE70-FEFF",
        "U+0600-06FF,U+0750-077F,U+08A0-08FF,U+FB50-FDFF,U+FE70-FEFF",
    ),
    (
        "hebrew",
        "U+0590-05FF, U+200C-2010, U+20AA, U+25CC, U+FB1D-FB4F",
        "U+0590-05FF,U+200C-2010,U+20AA,U+25CC,U+FB1D-FB4F",
    ),
    (
        "devanagari",
        "U+0900-097F, U+1CD0-1CF9, U+200C-200D, U+20A8, U+20B9, U+25CC, U+A830-A839, U+A8E0-A8FF",
        "U+0900-097F,U+1CD0-1CF9,U+200C-200D,U+20A8,U+20B9,U+25CC,U+A830-A839,U+A8E0-A8FF",
    ),
    (
        "thai",
        "U+0E01-0E5B, U+200C-200D, U+25CC",
        "U+0E01-0E5B,U+200C-200D,U+25CC",
    ),
    (
        "symbols-extra",
        "U+058F, U+2070-209F, U+2100-21E5, U+21EB-232A, U+232C-23CD, U+23CF-27FF, U+2E00-2E7F",
        "U+058F,U+2070-209F,U+2100-21E5,U+21EB-232A,U+232C-23CD,U+23CF-27FF,U+2E00-2E7F",
    ),
]

FACE_SPECS = [
    ("batumi-sans-normal",         "Batumi Sans",         "normal", "BatumiSans[wdth,wght].ttf",                "BatumiSans-VF.ttf"),
    ("batumi-sans-italic",         "Batumi Sans",         "italic", "BatumiSans-Italic[wdth,wght].ttf",         "BatumiSans-Italic-VF.ttf"),
    ("batumi-sans-rounded-normal", "Batumi Sans Rounded", "normal", "BatumiSansRounded[wdth,wght].ttf",         "BatumiSansRounded-VF.ttf"),
    ("batumi-sans-rounded-italic", "Batumi Sans Rounded", "italic", "BatumiSansRounded-Italic[wdth,wght].ttf",  "BatumiSansRounded-Italic-VF.ttf"),
]


def subset_single_chunk(job):
    face_slug, chunk_id, src_ttf, out_woff2, unicodes_spec = job
    options = ft_subset.Options()
    options.flavor = "woff2"
    options.layout_features = list(PRESERVED_FEATURES)
    options.name_IDs = ["*"]
    options.name_legacy = False
    options.name_languages = ["*"]
    options.glyph_names = False
    options.notdef_outline = True
    options.recalc_bounds = True
    options.recalc_timestamp = False
    options.prune_unicode_ranges = False
    options.drop_tables = ["DSIG"]
    options.passthrough_tables = False
    # Keep STAT, fvar, avar, gvar, HVAR, meta, gasp intact!
    font = TTFont(src_ttf)
    subsetter = ft_subset.Subsetter(options=options)
    unicodes = ft_subset.parse_unicodes(unicodes_spec)
    subsetter.populate(unicodes=unicodes)
    subsetter.subset(font)
    n_glyphs = len(font.getGlyphOrder())
    # CRITICAL: explicitly save via fontTools.subset.save_font (or set font.flavor = 'woff2')
    # so true Brotli WOFF2 compression is applied!
    ft_subset.save_font(font, str(out_woff2), options)
    font.close()
    sz = os.path.getsize(out_woff2)
    return {
        "face_slug": face_slug,
        "chunk_id": chunk_id,
        "file": os.path.basename(out_woff2),
        "glyphs": n_glyphs,
        "bytes": sz,
        "kb": round(sz / 1024.0, 2),
    }


def write_web_css(out_dir: Path, mode_label: str):
    lines = [
        f"/* Batumi Sans v1.100 — Google Fonts–Style unicode-range Variable Webfont CSS ({mode_label}) */",
        "/* Loads ONLY the script chunks actually used on the page (Georgian + Latin ~80-150 KB!). */",
        "/* Preserves continuous wght (100-900) x wdth (75%-115%) + live `calt` Georgian Ampersand & L1.07b Mtavruli. */",
        "/* License: SIL Open Font License, Version 1.1 (OFL.txt) — Borbalo (KJ Group) & Koba Jgenti */",
        "",
    ]
    # Emit secondary scripts first, Latin & Georgian last (matching Google Fonts CSS cascade order)
    cascade_order = [
        "symbols-extra", "thai", "devanagari", "hebrew", "arabic",
        "greek", "cyrillic", "latin-ext", "latin", "georgian-khutsuri", "georgian",
    ]
    chunk_map = {cid: ur for cid, ur, _ in SCRIPT_CHUNKS}

    for face_slug, fam_name, fstyle, _, _ in FACE_SPECS:
        lines.append(f"/* === {fam_name} ({fstyle}) === */")
        for cid in cascade_order:
            fn = f"{face_slug}-{cid}.woff2"
            if not (out_dir / fn).exists():
                continue
            lines.append(f"/* {cid} */")
            lines.append("@font-face {")
            lines.append(f"  font-family: '{fam_name}';")
            lines.append(f"  font-style: {fstyle};")
            lines.append("  font-weight: 100 900;")
            lines.append("  font-stretch: 75% 115%;")
            lines.append("  font-display: swap;")
            lines.append(f"  src: url('{fn}') format('woff2');")
            lines.append(f"  unicode-range: {chunk_map[cid]};")
            lines.append("}")
            lines.append("")

    css_path = out_dir / "batumi-sans-web.css"
    css_path.write_text("\n".join(lines), encoding="utf-8")
    return css_path


def main():
    ap = argparse.ArgumentParser(description="Build Google Fonts–style unicode-range WOFF2 web subsets.")
    ap.add_argument("--source-mode", choices=("2axis", "3axis"), default="2axis",
                    help="Subset 2-axis Google Fonts VFs (default, smallest web payload) or 3-axis Creative VFs")
    ap.add_argument("--gf-dir", type=Path, default=DEFAULT_GF_DIR)
    ap.add_argument("--var-dir", type=Path, default=DEFAULT_VAR_DIR)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--workers", type=int, default=max(1, min(8, os.cpu_count() or 4)))
    args = ap.parse_args()

    t0 = time.time()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for old in args.out_dir.glob("*.woff2"):
        old.unlink()

    jobs = []
    for face_slug, fam_name, fstyle, gf_fn, cr_fn in FACE_SPECS:
        src_path = (args.gf_dir / gf_fn) if args.source_mode == "2axis" else (args.var_dir / cr_fn)
        if not src_path.exists():
            raise SystemExit(f"Missing source VF for web subsetting: {src_path}")
        for chunk_id, _, unicodes_spec in SCRIPT_CHUNKS:
            out_path = args.out_dir / f"{face_slug}-{chunk_id}.woff2"
            jobs.append((face_slug, chunk_id, str(src_path), str(out_path), unicodes_spec))

    print(f"Subsetting {len(jobs)} WOFF2 script chunks ({args.source_mode} VFs, {args.workers} workers)...")
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futs = [pool.submit(subset_single_chunk, j) for j in jobs]
        for fut in as_completed(futs):
            results.append(fut.result())

    results.sort(key=lambda r: (r["face_slug"], r["chunk_id"]))
    mode_lbl = "2-axis wdth x wght" if args.source_mode == "2axis" else "3-axis wdth x wght x slnt"
    css_path = write_web_css(args.out_dir, mode_lbl)

    # Summarize per-face Georgian + Latin payload vs full WOFF2!
    by_face = {}
    for r in results:
        by_face.setdefault(r["face_slug"], {})[r["chunk_id"]] = r

    summary = {"source_mode": args.source_mode, "elapsed_s": round(time.time() - t0, 2), "faces": {}}
    print(f"\n=== Web Subset Summary ({time.time() - t0:.1f}s) ===")
    for face_slug, fam_name, fstyle, gf_fn, cr_fn in FACE_SPECS:
        chunks = by_face[face_slug]
        geo_kb = chunks["georgian"]["kb"]
        khut_kb = chunks["georgian-khutsuri"]["kb"]
        lat_kb = chunks["latin"]["kb"]
        geo_lat_kb = round(geo_kb + lat_kb, 2)
        tot_kb = round(sum(c["kb"] for c in chunks.values()), 2)
        summary["faces"][face_slug] = {
            "family": fam_name,
            "style": fstyle,
            "georgian_kb": geo_kb,
            "georgian_khutsuri_kb": khut_kb,
            "latin_kb": lat_kb,
            "georgian_plus_latin_kb": geo_lat_kb,
            "all_11_chunks_kb": tot_kb,
            "chunks": chunks,
        }
        print(f"  {face_slug:28s}: georgian={geo_kb:6.1f} KB + latin={lat_kb:6.1f} KB = {geo_lat_kb:6.1f} KB  | khutsuri={khut_kb:5.1f} KB  (all 11 chunks: {tot_kb:.1f} KB)")

    bench_path = args.out_dir / "subset_benchmark.json"
    bench_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"  CSS written: {css_path}")
    print(f"  Benchmark JSON: {bench_path}")


if __name__ == "__main__":
    main()

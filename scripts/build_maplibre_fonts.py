#!/usr/bin/env python3
"""
Build Dedicated MapLibre-Centred Static TTF Package for Batumi Sans (ISS-002).

Forensic Root Cause (verified directly in MapLibre GL JS `SHAPING_DEFAULT_OFFSET = -17`
& decoded Wayfinder PBFs):
  - For single-line `symbol-placement: line` labels (`text-anchor: center`), MapLibre GL JS
    sets `positionedGlyph.y = -17` (`SHAPING_DEFAULT_OFFSET`) and draws each glyph at:
      * `y_top_ink = -17 - metrics.top = ascender_px - 17 - glyph_yMax_px`
      * `y_bot_ink = -17 - metrics.top + metrics.height = ascender_px - 17 - glyph_yMin_px`
      * `y_mid_ink = ascender_px - 17 - (glyph_yMax_px + glyph_yMin_px) / 2`
    where screen Y increases DOWNWARD relative to the road centreline (`y = 0`).
  - With Desktop `hhea.ascent = 935` (`ascender_px = ceil(935*24/1000) = 23 px`):
      * Latin Caps (`'H'`: `yMax=17, h=17, top=-6`): `y_ink = [-11, +6]` -> `-2.50 px` UP (`-1.35 px` @13px)
      * Mtavruli `L1.07b` (`'Ა'`: `yMax=16, h=16, top=-7`): `y_ink = [-10, +6]` -> `-2.00 px` UP (`-1.08 px` @13px)
  - Setting dedicated MapLibre metrics `hhea.ascent = 1040`, `hhea.descent = -265`,
    `hhea.lineGap = 0`, `OS/2.sTypoAscender = 1040`, `OS/2.usWinAscent = max(usWinAscent, 1040)`
    gives `ascender_px = ceil(1040 * 24 / 1000) = ceil(24.96) = 25 px`:
      * Georgian Mtavruli `L1.07b` (`'Ა'`: `top = -9, h = 16`): `y_ink = [-8.0, +8.0]` -> **0.00 px EXACT DEAD CENTER**!
      * Latin Caps (`'H'`: `top = -8, h = 17`): `y_ink = [-9.0, +8.0]` -> **-0.50 px** (`-0.27 px` @13px / `-0.33 px` @16px)!
      * Georgian Mkhedruli (`'ა'`: `top = -12, h = 13`): `y_ink = [-5.0, +8.0]` -> **+1.50 px** (`+0.81 px` @13px — 1.0 px tighter than Noto Sans's `+2.50 px`!)
  - Desktop/Web/iOS builds (`dist/{otf,ttf,woff2,variable}/`) MUST KEEP `hhea.ascent = 935,
    hhea.descent = -265` untouched so Figma, macOS, Web, and iOS line metrics stay 100% safe.

Outputs:
  1. `dist/maplibre-ttf/*.ttf` (all 144 static styles) + `dist/maplibre-ttf/OFL.txt`
  2. `releases/BatumiSans-Static-MapLibre.zip` (145 files under `BatumiSans-Static-TTF/`)
  3. Syncs `releases/BatumiSans-Static-TTF/` if that unzipped directory exists.
"""

import argparse
import math
import os
import shutil
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from fontTools.ttLib import TTFont

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SRC = BASE_DIR / "dist" / "ttf"
DEFAULT_OUT = BASE_DIR / "dist" / "maplibre-ttf"
DEFAULT_OFL = BASE_DIR / "OFL.txt"
DEFAULT_ZIP = BASE_DIR / "releases" / "BatumiSans-Static-MapLibre.zip"
DEFAULT_UNZIPPED = BASE_DIR / "releases" / "BatumiSans-Static-TTF"

MAPLIBRE_HHEA_ASCENT = 1040
MAPLIBRE_HHEA_DESCENT = -265
MAPLIBRE_HHEA_LINEGAP = 0


def tune_single_ttf(args):
    src_path, dst_path = args
    font = TTFont(src_path)

    # Set MapLibre-centred vertical metrics (ascender_px = ceil(1040 * 24 / 1000) = 25 px)
    hhea = font["hhea"]
    hhea.ascent = MAPLIBRE_HHEA_ASCENT
    hhea.descent = MAPLIBRE_HHEA_DESCENT
    hhea.lineGap = MAPLIBRE_HHEA_LINEGAP

    # Keep OS/2 typographic ascenders consistent with MapLibre hhea=1040/-265/0
    # while preserving family-wide ISS-003 usWinAscent/usWinDescent (>= 1480/740)!
    os2 = font["OS/2"]
    os2.sTypoAscender = MAPLIBRE_HHEA_ASCENT
    os2.sTypoDescender = MAPLIBRE_HHEA_DESCENT
    os2.sTypoLineGap = MAPLIBRE_HHEA_LINEGAP
    os2.usWinAscent = max(os2.usWinAscent, MAPLIBRE_HHEA_ASCENT, 1480)
    os2.usWinDescent = max(os2.usWinDescent, abs(MAPLIBRE_HHEA_DESCENT), 740)

    font.save(dst_path)
    upm = font["head"].unitsPerEm
    asc_px = math.ceil(hhea.ascent * 24 / upm)
    n_glyphs = len(font.getGlyphOrder())
    font.close()
    return (Path(dst_path).name, n_glyphs, hhea.ascent, hhea.descent, asc_px, os2.sTypoAscender, os2.usWinAscent, os2.usWinDescent)


def build_release_zip(out_dir: Path, zip_path: Path, unzipped_dir: Path | None):
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_zip = zip_path.with_suffix(".zip.tmp")
    files = sorted(p for p in out_dir.iterdir() if p.is_file() and (p.suffix == ".ttf" or p.name == "OFL.txt"))
    with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in files:
            zf.write(p, arcname=f"BatumiSans-Static-TTF/{p.name}")
    os.replace(tmp_zip, zip_path)

    if unzipped_dir is not None and unzipped_dir.exists():
        # Keep existing releases/BatumiSans-Static-TTF/ strictly synced (zero stale TTFs!)
        for old in unzipped_dir.glob("*.ttf"):
            old.unlink()
        for p in files:
            shutil.copy2(p, unzipped_dir / p.name)
    return len(files)


def main():
    ap = argparse.ArgumentParser(description="Build MapLibre-centred static TTFs (ISS-002: hhea.ascent=1040 -> ascender_px=25).")
    ap.add_argument("--src-dir", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--zip-out", type=Path, default=DEFAULT_ZIP)
    ap.add_argument("--workers", type=int, default=max(1, min(8, os.cpu_count() or 4)))
    ap.add_argument("--skip-zip", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    ttfs = sorted(args.src_dir.glob("BatumiSans*.ttf"))
    if len(ttfs) != 144:
        raise SystemExit(f"Expected 144 static TTFs in {args.src_dir}, found {len(ttfs)}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for old in args.out_dir.glob("*.ttf"):
        old.unlink()

    jobs = [(str(p), str(args.out_dir / p.name)) for p in ttfs]
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futs = [pool.submit(tune_single_ttf, j) for j in jobs]
        for fut in as_completed(futs):
            results.append(fut.result())

    if DEFAULT_OFL.exists():
        shutil.copy2(DEFAULT_OFL, args.out_dir / "OFL.txt")

    asc_vals = {r[2] for r in results}
    desc_vals = {r[3] for r in results}
    asc_px_vals = {r[4] for r in results}
    typo_vals = {r[5] for r in results}
    win_vals = {r[6] for r in results}
    win_desc_vals = {r[7] for r in results}
    gcounts = {r[1] for r in results}

    print(f"Built {len(results)}/144 MapLibre-centred static TTFs in {args.out_dir} ({time.time() - t0:.1f}s)")
    print(
        f"  hhea.ascent={asc_vals}, hhea.descent={desc_vals}, 24px ascender_px={asc_px_vals}, "
        f"sTypoAscender={typo_vals}, usWinAscent={win_vals}, usWinDescent={win_desc_vals}, glyphs={gcounts}"
    )

    # Double-check desktop dist/ttf/ was NOT modified
    sample_desktop = TTFont(ttfs[0])
    assert sample_desktop["hhea"].ascent == 935, "Desktop TTF hhea.ascent unexpectedly changed!"
    assert sample_desktop["hhea"].descent == -265
    sample_desktop.close()
    print("  Verified desktop dist/ttf/ untouched: hhea.ascent=935, hhea.descent=-265")

    if not args.skip_zip:
        t_z = time.time()
        n_zip = build_release_zip(args.out_dir, args.zip_out, DEFAULT_UNZIPPED)
        mb = args.zip_out.stat().st_size / (1024 * 1024)
        sync_note = f" + synced {DEFAULT_UNZIPPED}" if DEFAULT_UNZIPPED.exists() else ""
        print(f"  Packaged {args.zip_out} ({n_zip} files, {mb:.1f} MB, {time.time() - t_z:.1f}s){sync_note}")


if __name__ == "__main__":
    main()

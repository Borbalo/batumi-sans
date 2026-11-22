#!/usr/bin/env python3
"""
Multi-Platform Release Packager for Batumi Sans v1.100 (Borbalo / KJ Group).

Builds clean, zero-junk platform packages:
  1. `dist/android/` + `releases/BatumiSans-Android.zip`
       - Lowercase `res/font/*.ttf` (Android resource naming spec: `[a-z0-9_]`)
       - `res/font/batumi_sans.xml` & `res/font/batumi_sans_rounded.xml` (`<font-family>` XML)
       - `BatumiSansCompose.kt` (drop-in Jetpack Compose `FontFamily` Kotlin snippet)
       - `OFL.txt`
  2. `releases/BatumiSans-iOS.mobileconfig`
       - 12 pure-static subroutinized v1.100 OTFs (`0` `fvar` tables, iOS/iPadOS native)
       - Borbalo (KJ Group) payload org & identifier `ge.borbalo.fonts.batumisans`
  3. `releases/BatumiSans-Variable.zip`
       - 4 Creative 3-axis VFs (`dist/variable/*.ttf`)
       - 4 Google Fonts 2-axis `[wdth,wght]` VFs (`dist/google-fonts/*[wdth,wght].ttf`)
       - `OFL.txt`, `AUTHORS.txt`, `CHANGELOG.md`, `README.md`
  4. `releases/BatumiSans-Web.zip`
       - Subsetted `unicode-range` WOFF2s + `batumi-sans-web.css` (`dist/web-subsets/`)
       - Full 3-axis Variable WOFF2s + `batumi-sans-variable.css` (`dist/variable/*.woff2`)
       - Full 2-axis GF Variable WOFF2s (`dist/google-fonts/*.woff2`)
       - `OFL.txt`
  5. `releases/BatumiSans-Static-Desktop.zip`
       - 144 subroutinized OTFs (`dist/otf/`) + 144 `gasp`-enabled Desktop TTFs (`dist/ttf/`, `hhea=935`) + `OFL.txt`
  6. `releases/BatumiSans-Static-MapLibre.zip` (built by `scripts/build_maplibre_fonts.py`)
  7. `releases/SHA256SUMS.txt` (exact SHA-256 digests for every release artifact)
"""

import hashlib
import os
import plistlib
import shutil
import uuid
import zipfile
from pathlib import Path

from fontTools.ttLib import TTFont

BASE_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = BASE_DIR / "dist"
RELEASES_DIR = BASE_DIR / "releases"
ANDROID_DIR = DIST_DIR / "android"

IOS_12_STYLES = [
    "BatumiSans-Regular.otf",
    "BatumiSans-Italic.otf",
    "BatumiSans-Medium.otf",
    "BatumiSans-Bold.otf",
    "BatumiSans-BoldItalic.otf",
    "BatumiSans-Heavy.otf",
    "BatumiSansRounded-Regular.otf",
    "BatumiSansRounded-Italic.otf",
    "BatumiSansRounded-Medium.otf",
    "BatumiSansRounded-Bold.otf",
    "BatumiSansRounded-BoldItalic.otf",
    "BatumiSansRounded-Heavy.otf",
]

ANDROID_WEIGHTS = [
    (100, "Thin",             "thin",              "normal"),
    (200, "ExtraLight",       "extralight",        "normal"),
    (300, "Light",            "light",             "normal"),
    (400, "Regular",          "regular",           "normal"),
    (500, "Medium",           "medium",            "normal"),
    (600, "SemiBold",         "semibold",          "normal"),
    (700, "Bold",             "bold",              "normal"),
    (800, "ExtraBold",        "extrabold",         "normal"),
    (900, "Heavy",            "heavy",             "normal"),
    (100, "ThinItalic",       "thin_italic",       "italic"),
    (200, "ExtraLightItalic", "extralight_italic", "italic"),
    (300, "LightItalic",      "light_italic",      "italic"),
    (400, "Italic",           "italic",            "italic"),
    (500, "MediumItalic",     "medium_italic",     "italic"),
    (600, "SemiBoldItalic",   "semibold_italic",   "italic"),
    (700, "BoldItalic",       "bold_italic",       "italic"),
    (800, "ExtraBoldItalic",  "extrabold_italic",  "italic"),
    (900, "HeavyItalic",      "heavy_italic",      "italic"),
]


def _write_zip(zip_path: Path, entries):
    """Write deterministic clean ZIP (no .DS_Store / __MACOSX). entries = [(src_path, arcname)]."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = zip_path.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for src, arc in entries:
            zf.write(src, arcname=arc)
    os.replace(tmp, zip_path)
    return zip_path.stat().st_size


def build_android_bundle():
    shutil.rmtree(ANDROID_DIR, ignore_errors=True)
    res_font = ANDROID_DIR / "res" / "font"
    res_font.mkdir(parents=True, exist_ok=True)

    families = [
        ("BatumiSans",        "batumi_sans",         "BatumiSans"),
        ("BatumiSansRounded", "batumi_sans_rounded", "BatumiSansRounded"),
    ]
    copied = []
    for ps_prefix, res_prefix, _ in families:
        xml_lines = [
            '<?xml version="1.0" encoding="utf-8"?>',
            '<font-family xmlns:android="http://schemas.android.com/apk/res/android"',
            '    xmlns:app="http://schemas.android.com/apk/res-auto">',
        ]
        for wval, suf, res_suf, fstyle in ANDROID_WEIGHTS:
            src_ttf = DIST_DIR / "ttf" / f"{ps_prefix}-{suf}.ttf"
            dst_name = f"{res_prefix}_{res_suf}.ttf"
            shutil.copy2(src_ttf, res_font / dst_name)
            copied.append(res_font / dst_name)
            res_id = dst_name[:-4]
            xml_lines.extend([
                "    <font",
                f'        android:fontStyle="{fstyle}"',
                f'        android:fontWeight="{wval}"',
                f'        android:font="@font/{res_id}"',
                f'        app:fontStyle="{fstyle}"',
                f'        app:fontWeight="{wval}"',
                f'        app:font="@font/{res_id}" />',
            ])
        xml_lines.append("</font-family>\n")
        (res_font / f"{res_prefix}.xml").write_text("\n".join(xml_lines), encoding="utf-8")

    # Jetpack Compose FontFamily Kotlin snippet
    compose_kt = """// Batumi Sans v1.100 — Jetpack Compose FontFamily Definitions
// Place `res/font/*.ttf` and `res/font/batumi_sans*.xml` inside `app/src/main/res/font/`.
// License: SIL Open Font License, Version 1.1 (Borbalo / KJ Group & Koba Jgenti)

package ge.borbalo.ui.theme

import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import ge.borbalo.app.R

val BatumiSans = FontFamily(
    Font(R.font.batumi_sans_thin, FontWeight.Thin, FontStyle.Normal),
    Font(R.font.batumi_sans_extralight, FontWeight.ExtraLight, FontStyle.Normal),
    Font(R.font.batumi_sans_light, FontWeight.Light, FontStyle.Normal),
    Font(R.font.batumi_sans_regular, FontWeight.Normal, FontStyle.Normal),
    Font(R.font.batumi_sans_medium, FontWeight.Medium, FontStyle.Normal),
    Font(R.font.batumi_sans_semibold, FontWeight.SemiBold, FontStyle.Normal),
    Font(R.font.batumi_sans_bold, FontWeight.Bold, FontStyle.Normal),
    Font(R.font.batumi_sans_extrabold, FontWeight.ExtraBold, FontStyle.Normal),
    Font(R.font.batumi_sans_heavy, FontWeight.Black, FontStyle.Normal),
    Font(R.font.batumi_sans_thin_italic, FontWeight.Thin, FontStyle.Italic),
    Font(R.font.batumi_sans_extralight_italic, FontWeight.ExtraLight, FontStyle.Italic),
    Font(R.font.batumi_sans_light_italic, FontWeight.Light, FontStyle.Italic),
    Font(R.font.batumi_sans_italic, FontWeight.Normal, FontStyle.Italic),
    Font(R.font.batumi_sans_medium_italic, FontWeight.Medium, FontStyle.Italic),
    Font(R.font.batumi_sans_semibold_italic, FontWeight.SemiBold, FontStyle.Italic),
    Font(R.font.batumi_sans_bold_italic, FontWeight.Bold, FontStyle.Italic),
    Font(R.font.batumi_sans_extrabold_italic, FontWeight.ExtraBold, FontStyle.Italic),
    Font(R.font.batumi_sans_heavy_italic, FontWeight.Black, FontStyle.Italic),
)

val BatumiSansRounded = FontFamily(
    Font(R.font.batumi_sans_rounded_thin, FontWeight.Thin, FontStyle.Normal),
    Font(R.font.batumi_sans_rounded_extralight, FontWeight.ExtraLight, FontStyle.Normal),
    Font(R.font.batumi_sans_rounded_light, FontWeight.Light, FontStyle.Normal),
    Font(R.font.batumi_sans_rounded_regular, FontWeight.Normal, FontStyle.Normal),
    Font(R.font.batumi_sans_rounded_medium, FontWeight.Medium, FontStyle.Normal),
    Font(R.font.batumi_sans_rounded_semibold, FontWeight.SemiBold, FontStyle.Normal),
    Font(R.font.batumi_sans_rounded_bold, FontWeight.Bold, FontStyle.Normal),
    Font(R.font.batumi_sans_rounded_extrabold, FontWeight.ExtraBold, FontStyle.Normal),
    Font(R.font.batumi_sans_rounded_heavy, FontWeight.Black, FontStyle.Normal),
    Font(R.font.batumi_sans_rounded_thin_italic, FontWeight.Thin, FontStyle.Italic),
    Font(R.font.batumi_sans_rounded_extralight_italic, FontWeight.ExtraLight, FontStyle.Italic),
    Font(R.font.batumi_sans_rounded_light_italic, FontWeight.Light, FontStyle.Italic),
    Font(R.font.batumi_sans_rounded_italic, FontWeight.Normal, FontStyle.Italic),
    Font(R.font.batumi_sans_rounded_medium_italic, FontWeight.Medium, FontStyle.Italic),
    Font(R.font.batumi_sans_rounded_semibold_italic, FontWeight.SemiBold, FontStyle.Italic),
    Font(R.font.batumi_sans_rounded_bold_italic, FontWeight.Bold, FontStyle.Italic),
    Font(R.font.batumi_sans_rounded_extrabold_italic, FontWeight.ExtraBold, FontStyle.Italic),
    Font(R.font.batumi_sans_rounded_heavy_italic, FontWeight.Black, FontStyle.Italic),
)
"""
    (ANDROID_DIR / "BatumiSansCompose.kt").write_text(compose_kt, encoding="utf-8")
    shutil.copy2(BASE_DIR / "OFL.txt", ANDROID_DIR / "OFL.txt")

    entries = []
    for p in sorted(ANDROID_DIR.rglob("*")):
        if p.is_file():
            entries.append((p, f"BatumiSans-Android/{p.relative_to(ANDROID_DIR)}"))
    sz = _write_zip(RELEASES_DIR / "BatumiSans-Android.zip", entries)
    print(f"  Built BatumiSans-Android.zip ({len(entries)} files, {sz/1024/1024:.2f} MB)")
    return sz


def build_ios_mobileconfig():
    """Build 1-tap iOS/iPadOS profile with 12 subroutinized v1.100 pure-static OTFs (0 fvar)."""
    payload_content = []
    for fn in IOS_12_STYLES:
        fp = DIST_DIR / "otf" / fn
        if not fp.exists():
            raise FileNotFoundError(f"Missing iOS static OTF: {fp}")
        # Verify strictly pure-static (no fvar!)
        ft = TTFont(fp, lazy=True)
        assert "fvar" not in ft, f"{fn} unexpectedly contains fvar!"
        ft.close()
        stem = fn[:-4]
        payload_content.append({
            "Font": fp.read_bytes(),
            "Name": fn,
            "PayloadDisplayName": stem,
            "PayloadIdentifier": f"ge.borbalo.fonts.batumisans.{stem.lower()}",
            "PayloadType": "com.apple.font",
            "PayloadUUID": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"ge.borbalo.fonts.batumisans.v1100.{stem}")).upper(),
            "PayloadVersion": 1,
        })

    profile = {
        "PayloadContent": payload_content,
        "PayloadDescription": (
            "Installs Batumi Sans and Batumi Sans Rounded (12 styles). "
            "Designed for Borbalo by Koba Jgenti."
        ),
        "PayloadDisplayName": "Batumi Sans & Rounded v1.100 (12 Styles)",
        "PayloadIdentifier": "ge.borbalo.fonts.batumisans",
        "PayloadOrganization": "Borbalo (KJ Group)",
        "PayloadRemovalDisallowed": False,
        "PayloadType": "Configuration",
        "PayloadUUID": str(uuid.uuid5(uuid.NAMESPACE_DNS, "ge.borbalo.fonts.batumisans.v1100.profile")).upper(),
        "PayloadVersion": 1,
    }
    out_path = RELEASES_DIR / "BatumiSans-iOS.mobileconfig"
    with open(out_path, "wb") as fp:
        plistlib.dump(profile, fp, fmt=plistlib.FMT_XML, sort_keys=True)
    sz = out_path.stat().st_size
    print(f"  Built BatumiSans-iOS.mobileconfig (12 pure-static subroutinized OTFs, {sz/1024/1024:.2f} MB)")
    return sz


def build_variable_zip():
    entries = []
    # Creative 3-axis VFs
    for p in sorted((DIST_DIR / "variable").glob("BatumiSans*.ttf")):
        entries.append((p, f"BatumiSans-Variable/creative-3axis/{p.name}"))
    # Google Fonts 2-axis VFs
    for p in sorted((DIST_DIR / "google-fonts").glob("BatumiSans*.ttf")):
        entries.append((p, f"BatumiSans-Variable/google-fonts-2axis/{p.name}"))
    # Docs & license
    for doc in ("OFL.txt", "AUTHORS.txt", "CHANGELOG.md", "README.md"):
        dp = BASE_DIR / doc
        if dp.exists():
            entries.append((dp, f"BatumiSans-Variable/{doc}"))
    sz = _write_zip(RELEASES_DIR / "BatumiSans-Variable.zip", entries)
    print(f"  Built BatumiSans-Variable.zip ({len(entries)} files, {sz/1024/1024:.2f} MB)")
    return sz


def build_web_zip():
    entries = []
    # Subsetted unicode-range WOFF2s + CSS
    for p in sorted((DIST_DIR / "web-subsets").glob("*.woff2")):
        entries.append((p, f"BatumiSans-Web/subsets/{p.name}"))
    web_css = DIST_DIR / "web-subsets" / "batumi-sans-web.css"
    if web_css.exists():
        entries.append((web_css, "BatumiSans-Web/subsets/batumi-sans-web.css"))
    # Full 3-axis WOFF2s + CSS
    for p in sorted((DIST_DIR / "variable").glob("BatumiSans*.woff2")):
        entries.append((p, f"BatumiSans-Web/variable-3axis/{p.name}"))
    var_css = DIST_DIR / "variable" / "batumi-sans-variable.css"
    if var_css.exists():
        entries.append((var_css, "BatumiSans-Web/variable-3axis/batumi-sans-variable.css"))
    # Full 2-axis GF WOFF2s
    for p in sorted((DIST_DIR / "google-fonts").glob("BatumiSans*.woff2")):
        entries.append((p, f"BatumiSans-Web/variable-2axis/{p.name}"))
    entries.append((BASE_DIR / "OFL.txt", "BatumiSans-Web/OFL.txt"))
    sz = _write_zip(RELEASES_DIR / "BatumiSans-Web.zip", entries)
    print(f"  Built BatumiSans-Web.zip ({len(entries)} files, {sz/1024/1024:.2f} MB)")
    return sz


def build_static_desktop_zip():
    entries = []
    for p in sorted((DIST_DIR / "otf").glob("BatumiSans*.otf")):
        entries.append((p, f"BatumiSans-Static-Desktop/otf/{p.name}"))
    for p in sorted((DIST_DIR / "ttf").glob("BatumiSans*.ttf")):
        entries.append((p, f"BatumiSans-Static-Desktop/ttf/{p.name}"))
    entries.append((BASE_DIR / "OFL.txt", "BatumiSans-Static-Desktop/OFL.txt"))
    sz = _write_zip(RELEASES_DIR / "BatumiSans-Static-Desktop.zip", entries)
    print(f"  Built BatumiSans-Static-Desktop.zip ({len(entries)} files, {sz/1024/1024:.2f} MB)")
    return sz


def write_sha256sums():
    # Clean any .DS_Store inside releases/
    ds_store = RELEASES_DIR / ".DS_Store"
    if ds_store.exists():
        ds_store.unlink()

    targets = [
        "BatumiSans-Variable.zip",
        "BatumiSans-Web.zip",
        "BatumiSans-Static-Desktop.zip",
        "BatumiSans-Static-MapLibre.zip",
        "BatumiSans-Android.zip",
        "BatumiSans-iOS.mobileconfig",
    ]
    lines = []
    for fn in targets:
        fp = RELEASES_DIR / fn
        if fp.exists():
            h = hashlib.sha256(fp.read_bytes()).hexdigest()
            lines.append(f"{h}  {fn}")
    out = RELEASES_DIR / "SHA256SUMS.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  Wrote {out} ({len(lines)} artifacts)")


def main():
    RELEASES_DIR.mkdir(parents=True, exist_ok=True)
    print("Packaging Batumi Sans v1.100 Multi-Platform Releases...")
    build_android_bundle()
    build_ios_mobileconfig()
    build_variable_zip()
    build_web_zip()
    build_static_desktop_zip()
    write_sha256sums()
    print("All releases packaged cleanly!")


if __name__ == "__main__":
    main()

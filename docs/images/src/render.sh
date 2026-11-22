#!/bin/sh
# Renders the pictures in docs/images from figures.html with headless Chrome,
# so they show what a browser really does with the fonts in dist/variable.
# Usage: sh docs/images/src/render.sh
set -e
here="$(cd "$(dirname "$0")" && pwd)"
out="$(dirname "$here")"
chrome="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
profile="$(mktemp -d)"

shot() {  # board id, output name, height in CSS pixels
  "$chrome" --headless=new --disable-gpu --hide-scrollbars \
    --user-data-dir="$profile" --allow-file-access-from-files \
    --force-device-scale-factor=2 --window-size=1500,"$3" \
    --virtual-time-budget=8000 \
    --screenshot="$out/$2" "file://$here/figures.html#$1" >/dev/null 2>&1
  echo "$2"
}

shot pair      georgian-ampersand-forms.png      600
shot examples  georgian-ampersand-examples.png   700
shot glyphs    georgian-ampersand-two-forms.png  640
shot unchanged georgian-ampersand-unchanged.png  380
shot karagma   old-abbreviations.png             740

shot hero         hero.png                         640
shot widths       widths.png                       600
shot rounded      rounded.png                      300
shot mtavruli     mtavruli-height-cues.png         640
shot amp-problem  georgian-ampersand-problem.png   580
shot map-centred  map-centred.png                  560
shot map-ba       map-before-after.png             600
shot in-use       in-use.png                       760

# Pictures for the Google Fonts article folders, 2048 x 1024.
repo="$(cd "$here/../../.." && pwd)"
shot_gf() {  # board id, family folder, file name
  "$chrome" --headless=new --disable-gpu --hide-scrollbars \
    --user-data-dir="$profile" --allow-file-access-from-files \
    --force-device-scale-factor=2 --window-size=1024,512 \
    --virtual-time-budget=8000 \
    --screenshot="$repo/google-fonts/$2/article/$3" "file://$here/figures.html#$1" >/dev/null 2>&1
  cp "$repo/google-fonts/$2/article/$3" "$repo/documentation/article/$3"
  echo "$3"
}
shot_gf gf-hero            batumisans        batumi_sans_specimen_hero.png
shot_gf gf-weights         batumisans        batumi_sans_multiscript_waterfall.png
shot_gf gf-hero-rounded    batumisansrounded batumi_sans_rounded_specimen_hero.png
shot_gf gf-weights-rounded batumisansrounded batumi_sans_rounded_multiscript_waterfall.png

rm -rf "$profile"

# Changelog

## 1.100 (22 November 2026)

First public release.

### What is in it

- **Two designs, four widths.** Batumi Sans and Batumi Sans Rounded, each in Extra Condensed, Condensed, Normal and Expanded. That is 8 families of 18 styles, 144 styles in all, as OTF and TTF.
- **Variable fonts.** Four with weight, width and slant axes for design tools and websites, and four with weight and width for Google Fonts.
- **About 4,800 glyphs and 2,800 characters.** Georgian in all its scripts (Mkhedruli, Mtavruli, Asomtavruli, Nuskhuri), Latin, Cyrillic and Greek, plus the Arabic, Hebrew, Devanagari and Thai of FiraGO.
- **Builds for each platform.** Web subsets split by script, an Android resource folder with a Compose file, an iPhone and iPad profile, and a set with metrics tuned for MapLibre and Mapbox labels.

### What it adds to FiraGO

- Condensed, Extra Condensed and Expanded widths, and a rounded version of every style.
- Mtavruli capitals that keep a small rise and drop, so look-alike letters can be told apart.
- A Georgian ampersand in a regular and an all-caps form. It appears when `&` is typed in Georgian text, `ss07` and `ss08` force it, and the word და is never changed.
- Asomtavruli and Nuskhuri, adapted from Noto Sans Georgian.
- The abbreviation mark of old Georgian writing, ქარაგმა, over two, three or four letters.
- Latin letters with a line below for romanizing Arabic, Persian and Hebrew place names, prime marks for coordinates, and the diacritics of Kartvelian linguistics.
- Currency signs for the manat, dram, tenge and bitcoin, next to the lari.
- Keyboard and interface symbols such as ⌘ ⌥ ⌃ ⇧ ⎋ ✓ ✕ ★, drawn to stay open in narrow and heavy styles.
- Letters needed by more Latin and Cyrillic languages, including Church Slavic.

### Repairs to the outlines we started from

- Outlines that ran in the wrong direction: 8 upright glyphs and 49 italic.
- 31 glyphs whose outlines started at different points in neighbouring weights, which twisted them in the variable fonts.
- ჟ and რ touching in the Bold and Heavy italics.

### Download sizes

| File | Size |
|---|---|
| `BatumiSans-Web.zip` | 28 MB |
| `BatumiSans-Variable.zip` | 30 MB |
| `BatumiSans-Static-Desktop.zip` | 119 MB |
| `BatumiSans-Static-MapLibre.zip` | 60 MB |
| `BatumiSans-Android.zip` | 15 MB |
| `BatumiSans-iOS.mobileconfig` | 12 MB |

On a website the subsets load by script: Georgian is about 160 KB and basic Latin about 170 KB.

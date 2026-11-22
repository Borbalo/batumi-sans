#!/usr/bin/env python3
"""Writes docs/LANGUAGES.md: the languages the fonts support, by script.

Usage: python scripts/list_languages.py

Needs Hyperglot (pip install hyperglot), an open database of the characters
each language needs. A language is listed when the fonts have every base
character of its main spelling. Run it again after characters are added.
"""
import logging
from pathlib import Path

import hyperglot
from hyperglot.checker import FontChecker

ROOT = Path(__file__).resolve().parent.parent
FONTS = sorted((ROOT / "fonts" / "variable").glob("*.ttf"))
OUT = ROOT / "docs" / "LANGUAGES.md"

# The scripts the family was made for, in the order they are listed.
CORE = ["Georgian", "Latin", "Cyrillic", "Greek"]
# Kept unchanged from FiraGO.
KEPT = ["Arabic", "Hebrew", "Devanagari", "Thai"]

# National languages of European states, by ISO 639-3 code.
EUROPE = {
    "Albanian": ["als", "aln", "sqi"], "Armenian": ["hye"], "Azerbaijani": ["azj"],
    "Belarusian": ["bel"], "Bosnian": ["bos"], "Bulgarian": ["bul"], "Catalan": ["cat"],
    "Croatian": ["hrv"], "Czech": ["ces"], "Danish": ["dan"], "Dutch": ["nld"],
    "English": ["eng"], "Estonian": ["ekk", "est"], "Finnish": ["fin"], "French": ["fra"],
    "Georgian": ["kat"], "German": ["deu"], "Greek": ["ell"], "Hungarian": ["hun"],
    "Icelandic": ["isl"], "Irish": ["gle"], "Italian": ["ita"],
    "Latvian": ["lvs", "lav"], "Lithuanian": ["lit"], "Luxembourgish": ["ltz"],
    "Macedonian": ["mkd"], "Maltese": ["mlt"], "Montenegrin": ["cnr"],
    "Norwegian": ["nob", "nno", "nor"], "Polish": ["pol"], "Portuguese": ["por"],
    "Romanian": ["ron"], "Romansh": ["roh"], "Russian": ["rus"], "Serbian": ["srp"],
    "Slovak": ["slk"], "Slovenian": ["slv"], "Spanish": ["spa"], "Swedish": ["swe"],
    "Turkish": ["tur"], "Ukrainian": ["ukr"],
}
# Languages of Georgia, with the script each is written in.
GEORGIA = [("Georgian", "kat"), ("Mingrelian", "xmf"), ("Laz", "lzz"), ("Svan", "sva"),
           ("Abkhaz", "abk"), ("Ossetian", "oss"), ("Azerbaijani", "azj"), ("Russian", "rus"),
           ("Armenian", "hye")]


def supported(font):
    """{script: {iso code: language name}} for one font."""
    result = FontChecker(str(font)).get_supported_languages()
    return {script: {iso: lang.name for iso, lang in langs.items()} for script, langs in result.items()}


def names(langs):
    return ", ".join(sorted(langs.values(), key=str.casefold))


def main():
    logging.disable(logging.CRITICAL)  # shaping notes for scripts we only carry over
    results = [supported(font) for font in FONTS]
    if any(r != results[0] for r in results[1:]):
        raise SystemExit("The fonts do not support the same languages.")
    by_script = results[0]
    unknown = set(by_script) - set(CORE) - set(KEPT)
    if unknown:
        raise SystemExit(f"Scripts not expected: {sorted(unknown)}")

    core_codes = set().union(*(by_script[s] for s in CORE))
    all_codes = set().union(*by_script.values())
    europe_missing = [name for name, codes in EUROPE.items() if not all_codes.intersection(codes)]
    europe_have = [name for name in EUROPE if name not in europe_missing]
    georgia_have = [name for name, code in GEORGIA if code in all_codes]
    georgia_missing = [name for name, code in GEORGIA if code not in all_codes]

    lines = [
        "# Languages",
        "",
        f"Batumi Sans supports {len(core_codes)} living languages in its four scripts: "
        "Georgian, Latin, Cyrillic and Greek. Every style of Batumi Sans and Batumi Sans Rounded "
        "supports the same languages.",
        "",
        "| Script | Languages |",
        "|---|---|",
    ]
    lines += [f"| {script} | {len(by_script[script])} |" for script in CORE]
    lines += [
        "",
        "A few languages are written in two of these scripts and appear in both lists.",
        "",
        "## Languages of Europe",
        "",
        f"The fonts cover the national language of every European state except "
        f"{' and '.join(europe_missing)}, which we plan to add:",
        "",
        ", ".join(europe_have) + ".",
        "",
        "## Languages of Georgia",
        "",
        "Of the languages spoken in Georgia, the fonts cover " + ", ".join(georgia_have[:-1])
        + f" and {georgia_have[-1]}. {' and '.join(georgia_missing)} is planned.",
        "",
    ]
    for script in CORE:
        lines += [f"## {script} script", "", names(by_script[script]) + ".", ""]
    lines += [
        "## Kept from FiraGO",
        "",
        "The fonts also keep the Arabic, Hebrew, Devanagari and Thai of FiraGO, as FiraGO drew them:",
        "",
    ]
    lines += [f"- **{script}** ({len(by_script[script])}): {names(by_script[script])}." for script in KEPT]
    lines += [
        "",
        "## How this was counted",
        "",
        f"The list comes from [Hyperglot](https://hyperglot.rosettatype.com) {hyperglot.__version__}, an open "
        "database of the characters each language needs. A language is listed when the fonts have every "
        "base character of its main spelling. To make the list again, run `python scripts/list_languages.py`.",
        "",
    ]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {len(core_codes)} languages in {', '.join(CORE)}")


if __name__ == "__main__":
    main()

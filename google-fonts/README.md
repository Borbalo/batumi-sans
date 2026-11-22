# Google Fonts staging

Files prepared for a submission to [google/fonts](https://github.com/google/fonts). There are two families, and each goes in its own pull request:

- `batumisans/` becomes `ofl/batumisans/`
- `batumisansrounded/` becomes `ofl/batumisansrounded/`

Nothing has been submitted yet.

## What is in each folder

| File | What it is |
|---|---|
| `…[wdth,wght].ttf` and `…-Italic[wdth,wght].ttf` | The upright and italic variable fonts, with width and weight axes. |
| `OFL.txt` | The licence. |
| `METADATA.pb` | Catalogue metadata. `commit:` still holds a placeholder and has to be set to the release commit. |
| `article/ARTICLE.en_us.html` and its images | The About text shown on the family's Google Fonts page. |
| `DESCRIPTION.en_us.html` | The older, short description format. Do not copy it into the pull request. The checker fails a family folder that has both a description and an article. |

The three-axis variable fonts in `dist/variable/` are not part of the submission. Google Fonts does not accept an italic file that also has a slant axis.

## Check

```bash
./.venv/bin/fontspector --profile googlefonts --skip-network \
  google-fonts/batumisans/BatumiSans\[wdth,wght\].ttf \
  google-fonts/batumisans/BatumiSans-Italic\[wdth,wght\].ttf \
  google-fonts/batumisans/OFL.txt \
  google-fonts/batumisans/METADATA.pb \
  google-fonts/batumisans/article/ARTICLE.en_us.html \
  google-fonts/batumisans/article/*.png
```

Use the same command with `batumisansrounded` and `BatumiSansRounded` for the rounded family.

Result on 22 November 2026, with fontspector 1.9.0. Nothing is fatal in either family, and each has 27 warnings.

- **Batumi Sans** has one failing check, `googlefonts/tofu`: some languages need characters that are outside the subsets listed in `METADATA.pb`.
- **Batumi Sans Rounded** has two. One is the same `googlefonts/tofu`. The other is `name/family_and_style_max_length`: four italic instance names, such as "Batumi Sans Rounded ExtraLight Italic", are longer than 32 characters.

One more check, `googlefonts/axes_match`, needs network access and does not run with `--skip-network`.

Running the checker on the font files alone skips the metadata checks and reports fewer failures. A pull request is checked with the metadata, so that is the result that counts.

## Before opening the pull requests

- Publish the source repository and tag the release.
- Set `commit:` in both `METADATA.pb` files.
- Resolve or explain the `googlefonts/tofu` failure.
- Resolve or explain `name/family_and_style_max_length` in Batumi Sans Rounded.
- Sign the Google contributor agreement.
- Add designer profiles to `catalog/designers/`.
- Open an onboarding issue for each family before the pull request.
- Leave out `DESCRIPTION.en_us.html`.

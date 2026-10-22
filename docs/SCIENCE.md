# Scientific scope and data sources

[Back to README](../README.md) · [User guide](USER_GUIDE.md) · [Validation](VALIDATION.md)

SPACER uses astronomical distances to guide photographed stars through an imagined forward camera movement. It is an artistic visualization with catalogue-based depth, not a full reconstruction of the scene or a precision astrometric product.

## Stellar distances

The default reference uses **Gaia DR3** positions/proper motions and **Bailer-Jones et al. (2021)** geometric distance estimates, accessed through GAVO. Positions are propagated from epoch 2016 to the image's observation date before pixel matching.

Strict selection requires finite RUWE ≤1.4, positive ordered distance bounds and fractional interval half-width ≤20%:

```text
(lower ≤ median ≤ upper), lower > 0
fractional interval half-width = (upper − lower) / (2 × median)
```

RUWE and interval screens cannot guarantee a correct distance, association or image separation. The catalogue bounds describe posterior uncertainty; overlapping intervals can leave depth ordering uncertain.

### Optional approximate coverage

**Include approximate distances** is off by default. Selection order is:

1. Keep a qualifying strict Gaia geometric estimate.
2. If strict Gaia distance selection fails, try a screened Hipparcos-2 parallax.
3. Otherwise, with acceptable Gaia RUWE, use a photogeometric interval with fractional half-width ≤50%.
4. Finally, allow a broader geometric interval with the same ≤50% limit.

Photogeometric estimates combine parallax with catalogue colour, apparent magnitude and Galactic priors. They do not estimate depth from the brightness of pixels in the uploaded photograph. Both broader Gaia choices are labelled approximate.

Hipparcos-2 fallback requires a single-component ordinary five-parameter solution, positive parallax/error, relative parallax error ≤20%, and goodness of fit ≤3. At this significance SPACER uses `distance_pc = 1000 / parallax_mas`, with bounds `1000 / (parallax ± quoted_error)`. These transformed bounds are not the same kind of interval as the Gaia Bayesian posterior. Hipparcos estimates remain labelled approximate; systematics are possible.

Hipparcos positions are propagated from epoch **1991.25** to **2016** before duplicate screening against Gaia, then onward to the image date for pixel matching. A unique association within 1 arcsecond may supply Hipparcos data when strict Gaia distance quality fails. Multiple Gaia candidates within 3 arcseconds, or an uncertain 1–3 arcsecond association, are deferred. Hipparcos entries without Gaia counterparts are also tested. Independent HIP identifiers remain in distance provenance.

Extra catalogue coverage does not guarantee extra movers: image association and extraction screens still apply. Each accepted star stores its distance source, identifier, approximate flag and bounds. Scenes, coverage reports and render metadata retain method counts.

## Image separation

Both desktop launchers expose **Iterative** separation. Internally, conservative extraction fits compact cores over local background planes, with separate colour amplitudes. Bright-group refinement alternates smooth halo/spike and neighbouring-core fits, excluding neighbouring cores from measured spike strips. Some non-converging groups receive bounded stabilised retries.

These are approximate models of photographed light. They are not a full telescope point-spread-function reconstruction. Broad saturated stars, unresolved companions, overlapping bright halos and unstable fits may remain stationary. Faint spike crosses or residual halos can remain. Individual small neighbours must not move at a bright star's depth simply because their light overlaps.

Only available stellar light is subtracted from the photographic background. Unaccepted/unselected light remains there. Subpixel placement smooths motion, but distance quality cannot repair an incorrect extraction. Better separation of overlapping bright stars is the current development priority.

## Camera geometry

Let `s` be forward travel and `D` the target/background distance. In target-distance mode, background scale is:

```text
background scale = D / (D − s), with 0 ≤ s < D
```

Each moving star uses its own optical-axis depth `z`:

```text
stellar position scale = z / (z − s)
z = stellar distance × cos(angle from optical axis)
```

The target/background scale is not multiplied into stellar perspective a second time. Camera zoom mode instead applies an independent enlargement to the background and stellar presentation in addition to parallax. The photographed stellar profile is retained for presentation rather than modelling physical changes in luminosity or diffraction during travel.

Nebulae, galaxies and unseparated stars occupy one flat photographic layer. Internal object depth, dust occlusion, radiative transfer and newly revealed unseen structure are not reconstructed. A galaxy target can be millions of parsecs away while foreground stars are much nearer; large physical travel can move foreground stars out of view. Camera zoom remains useful when a literal distance-derived enlargement is visually modest.

## Target distances

The optional SIMBAD picker identifies familiar catalogue objects whose centres lie inside the solved image. These are catalogue associations, not detections proving an object is visible. The list is deliberately bounded rather than exhaustive.

Each target uses a practical median of available published distance measurements, rounded to two significant figures. Individual values, references and their range remain saved. This is not a statistically combined scientific estimate; no one paper's uncertainty is attached to the summary. Missing distances support manual entry rather than an invented default. The target plane does not determine individual stellar distances or re-centre the camera.

## Data credits and external tools

- [Gaia DR3 documentation](https://www.cosmos.esa.int/web/gaia/dr3): stellar astrometry from ESA's Gaia mission and DPAC.
- [Bailer-Jones et al. (2021), geometric and photogeometric distances](https://bailer-jones.www3.mpia.de/gedr3_distances.html).
- [GAVO distance-table metadata](https://dc.g-vo.org/tableinfo/gedr3dist.main): catalogue access used by SPACER.
- [Hipparcos-2, van Leeuwen (2007), through NASA HEASARC](https://heasarc.gsfc.nasa.gov/W3Browse/all/hipnewcat.html).
- [SIMBAD](https://simbad.cds.unistra.fr/simbad/): optional target identification and published distance measurements.
- [Astro-TIFF specification](https://siril.readthedocs.io/en/stable/file-formats/Astro-TIFF.html): supported embedded image metadata.
- [ASTAP command-line documentation](https://www.hnsky.org/astap.htm#astap_command_line): optional standalone solving.

Image processing runs locally; SPACER sends catalogue queries/field coordinates to the selected catalogue services, not image pixels. ASTAP/database, StarXTerminator, StarNet and FFmpeg are external tools and are not bundled with this repository.

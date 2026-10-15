# SPACER development handoff

**Stellar Parallax Animation through Catalogue-based Extraction and Reprojection.**
Version 0.6.0 adds the standalone desktop app. The 0.5.x releases simplified the interface; 0.4.0 added persistent projects; 0.3.0 is the first explicitly versioned baseline. This repository is the canonical source.

## Architecture

- SPACER.py: standalone desktop entry point; opens FITS, TIFF/PNG plus WCS, or an existing project.
- gaia_flythrough/app.py: shared Qt interface and worker; no Siril import.
- gaia_flythrough/image_source.py: disk input validation and channel/row normalization.
- Siril_Gaia_Flythrough.py: thin Siril launcher; snapshots current pixels and WCS without modifying the source. Requires an existing plate solution; suggests Siril/ASTAP when absent. Automatic solving was deliberately excluded.
- gaia_flythrough/siril_pipeline.py: export, external removal engines, cached fields and non-overwriting render variants.
- gaia_flythrough/flythrough.py: catalogue matching, compact-star extraction, subpixel rendering and prototype CLI.
- gaia_flythrough/iterative_deblend.py: alternating bright-star halo/spike and neighbouring-core fits.
- gaia_flythrough/viewer.html: self-contained interactive preview.
- gaia_flythrough/version.py: shared version and provenance.

The standalone GUI is implemented. File input uses already-stretched pixels and an existing plate solution; Siril linked autostretch remains exclusive to the Siril image source. The prototype rendering CLI still takes separate photo, starless and WCS inputs. A unified headless CLI, bundled installers and website remain future directions.

## Preserve these decisions

Both desktop entry points expose only Iterative. Conservative core extraction remains an internal input; legacy Natural/Dynamic assets are preserved.
Iterative repeatedly separates isolated bright groups, excluding catalogue neighbour cores from measured spike strips. Faint residual crosses can remain. Unresolved/overlapping groups and non-converged fits are deferred.

Accuracy and visual quality matter more than analysis/rendering speed. Preserve subpixel motion and full-resolution deep-zoom sampling.

Reuse saved images, WCS, catalogue and scenes even after switching the current Siril image. Do not repeat AI removal or Gaia queries when a suitable cache exists.

Defaults: 60 seconds, 1.3× final zoom, 24 fps, 80 pc travel, 1.5-second easing at each end. The interface uses 1×–101×. Project `zoom` and pipeline options retain percent increase (0–10000%) for compatibility; convert only at the UI boundary.

Never overwrite exports. Names record version/mode/duration/zoom; collisions get numeric suffixes. Field preparation version/time and rendering version/time are separate. Historical unversioned analysis must remain labelled unversioned.

Commit each completed change with its release version in the commit message. Keep each change independently referenceable; bump the shared version and changelog under the major.minor.patch rules.

Standalone launches must not import `sirilpy` or require Siril. Keep image loading at the source boundary and share the same project/render pipeline between entry points. Treat TIFF/PNG WCS references as user-supplied framing assertions; validate dimensions, do not claim that dimensions verify registration.

## Interface conventions

Keep project choice, duration, direct final zoom scale and one state-specific primary action in the main window. Advanced preparation/tool paths live in a scrollable dialog; diagnostics use a separate Details disclosure. Use native palette and widgets, meaningful text, keyboard focus and visible progress. Surface required setup when validation fails. Disable settings and project switching during worker execution. Test new, partial, prepared, busy and failed states after changing the interface.

## Scientific scope

Gaia DR3 positions are propagated to the observation epoch. Bailer-Jones geometric distance estimates and bounds are used. RUWE and uncertainty screens do not guarantee accurate distances or correct separation of photographed light. Nebulosity is flat; brightness/PSF presentation is not physical light transport.

StarXTerminator, StarNet and FFmpeg are external. Do not bundle proprietary models, binaries or licenses. Images are processed locally; field coordinates are queried through GAVO.

## Validation

    python -m unittest discover -s gaia_flythrough -p "test_*.py"

Initial import: 13 passing tests. Version 0.5.0 adds five offscreen Qt workflow tests (skipped if PyQt6 is unavailable). For visual changes also inspect real-image first/middle/final frames and close-ups around moved bright stars. Tests alone previously missed spike artifacts.

Large M45/NGC6914 audit fields and videos are excluded from Git. Locate an existing local prepared field or request one when real-image validation is needed; preserve historical comparisons.

## New-chat prompt

Continue developing SPACER in this repository. Read README.md, DEVELOPMENT.md and gaia_flythrough/CHANGELOG.md, then inspect the code and git status. Preserve the Iterative-only workflow, persistent projects, reusable prepared fields, provenance and non-overwriting exports. Keep scientific confidence separate from cosmetic motion. Bump the shared version and update the changelog for shipped changes. Run relevant tests; inspect real first/middle/final frames and bright-star close-ups for visual changes. My next requested change is: [describe change].

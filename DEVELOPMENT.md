# SPACER development handoff

**Stellar Parallax Animation through Catalogue-based Extraction and Reprojection.**
Version 0.5.0 simplifies the interface; 0.4.0 added persistent projects; 0.3.0 is the first explicitly versioned baseline. This repository is the canonical source.

## Architecture

- Siril_Gaia_Flythrough.py: PyQt6 Siril launcher; snapshots current pixels and WCS without modifying the source. Requires an existing plate solution; suggests Siril/ASTAP when absent. Automatic solving was deliberately excluded.
- gaia_flythrough/siril_pipeline.py: export, external removal engines, cached fields and non-overwriting render variants.
- gaia_flythrough/flythrough.py: catalogue matching, compact-star extraction, subpixel rendering and prototype CLI.
- gaia_flythrough/iterative_deblend.py: alternating bright-star halo/spike and neighbouring-core fits.
- gaia_flythrough/viewer.html: self-contained interactive preview.
- gaia_flythrough/version.py: shared version and provenance.

The prototype CLI takes separate photo, starless and WCS inputs. A unified single-file CLI, standalone GUI and website are future directions, not implemented features.

## Preserve these decisions

The Siril workflow exposes only Iterative. Conservative core extraction remains an internal input; legacy Natural/Dynamic assets are preserved.
Iterative repeatedly separates isolated bright groups, excluding catalogue neighbour cores from measured spike strips. Faint residual crosses can remain. Unresolved/overlapping groups and non-converged fits are deferred.

Accuracy and visual quality matter more than analysis/rendering speed. Preserve subpixel motion and full-resolution deep-zoom sampling.

Reuse saved images, WCS, catalogue and scenes even after switching the current Siril image. Do not repeat AI removal or Gaia queries when a suitable cache exists.

Defaults: 60 seconds, 30% zoom increase, 24 fps, 80 pc travel, 1.5-second easing at each end. Zoom range is 0–10000%.

Never overwrite exports. Names record version/mode/duration/zoom; collisions get numeric suffixes. Field preparation version/time and rendering version/time are separate. Historical unversioned analysis must remain labelled unversioned.

## Interface conventions

Keep project choice, duration, zoom and one state-specific primary action in the main window. Advanced preparation/tool paths live in a scrollable dialog; diagnostics use a separate Details disclosure. Use native palette and widgets, meaningful text, keyboard focus and visible progress. Surface required setup when validation fails. Disable settings and project switching during worker execution. Test new, partial, prepared, busy and failed states after changing the interface.

## Scientific scope

Gaia DR3 positions are propagated to the observation epoch. Bailer-Jones geometric distance estimates and bounds are used. RUWE and uncertainty screens do not guarantee accurate distances or correct separation of photographed light. Nebulosity is flat; brightness/PSF presentation is not physical light transport.

StarXTerminator, StarNet and FFmpeg are external. Do not bundle proprietary models, binaries or licenses. Images are processed locally; field coordinates are queried through GAVO.

## Validation

    python -m unittest discover -s gaia_flythrough -p "test_*.py"

Initial import: 13 passing tests. Version 0.5.0 adds five offscreen Qt workflow tests (skipped if PyQt6 is unavailable). For visual changes also inspect real-image first/middle/final frames and close-ups around moved bright stars. Tests alone previously missed spike artifacts.

Large M45/NGC6914 audit fields and videos are excluded from Git. Locate an existing local prepared field or request one when real-image validation is needed; preserve historical comparisons.

## New-chat prompt

Continue developing SPACER in this repository. Read README.md, DEVELOPMENT.md and gaia_flythrough/CHANGELOG.md, then inspect the code and git status. Preserve the Iterative-only workflow, persistent projects, reusable prepared fields, provenance and non-overwriting exports. Keep scientific confidence separate from cosmetic motion. Bump the shared version and update the changelog for shipped changes. Run relevant tests; inspect real first/middle/final frames and bright-star close-ups for visual changes. My next requested change is: [describe change].

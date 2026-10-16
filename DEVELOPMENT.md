# SPACER development handoff

**Stellar Parallax Animation through Catalogue-based Extraction and Reprojection.**
Version 0.9.10 expands Advanced settings fields; 0.9.9 adds determinate preparation progress and makes Details always diagnostic; 0.9.8 bounds new preparation to 5° radius with crop guidance; 0.9.7 removes the catalogue footprint limit with resumable region queries; 0.9.6 fixes header height/spacing; 0.9.5 reads existing Siril JPEG EXIF solutions; 0.9.4 stabilizes progress layout and adds opt-in verbose diagnostics; 0.9.3 repairs processed-image solving and surfaces the optional object hint; 0.9.2 streams solver diagnostics; 0.9.1 improves render progress; 0.9.0 infers matching dates with provenance; 0.8.0 remembers navigation and explains the matching date; 0.7.0 added JPEG input and optional ASTAP solving; 0.6.2 reads embedded Astro-TIFF solutions; 0.6.1 clarified raster coordinate selection; 0.6.0 added the standalone desktop app. The 0.5.x releases simplified the interface; 0.4.0 added persistent projects; 0.3.0 is the first explicitly versioned baseline. This repository is the canonical source.

## Architecture

- SPACER.py: standalone desktop entry point; opens FITS, TIFF, PNG, JPEG or an existing project.
- gaia_flythrough/catalog.py: spherical footprint subdivision, TAP/VOTable completion checking, resumable per-query parts and deduplicated catalogue assembly.
- gaia_flythrough/photo_date.py: date parsing/inference from capture metadata, export/file metadata and filesystem dates; carries source/approximation provenance.
- gaia_flythrough/preferences.py: portable, atomic local navigation settings in ignored `.spacer-settings.json`; injected temporary paths in tests.
- gaia_flythrough/app.py: shared Qt interface and worker; no Siril import.
- gaia_flythrough/task_progress.py: throttled per-stage counts and tagged diagnostic messages shared by preparation, catalogue queries and Iterative refinement.
- gaia_flythrough/astap_solver.py: cancellable ASTAP worker operation using a same-size mono proxy; only WCS is merged into the original colour snapshot.
- gaia_flythrough/image_source.py: disk input validation, embedded Astro-TIFF FITS-header parsing and channel/row normalization.
- Siril_Gaia_Flythrough.py: thin Siril launcher; snapshots current pixels and WCS without modifying the source. Requires an existing plate solution; suggests Siril/ASTAP when absent. Siril integration still expects a solved image; the standalone app now offers explicit ASTAP solving.
- gaia_flythrough/siril_pipeline.py: export, external removal engines, cached fields and non-overwriting render variants.
- gaia_flythrough/flythrough.py: catalogue matching, compact-star extraction, subpixel rendering and prototype CLI.
- gaia_flythrough/iterative_deblend.py: alternating bright-star halo/spike and neighbouring-core fits.
- gaia_flythrough/viewer.html: self-contained interactive preview.
- gaia_flythrough/version.py: shared version and provenance.

The standalone GUI is implemented. File input uses already-stretched pixels and an existing or explicitly requested ASTAP plate solution; Siril linked autostretch remains exclusive to the Siril image source. The prototype rendering CLI still takes separate photo, starless and WCS inputs. A unified headless CLI, bundled installers and website remain future directions.

## Preserve these decisions

Both desktop entry points expose only Iterative. Conservative core extraction remains an internal input; legacy Natural/Dynamic assets are preserved.
Iterative repeatedly separates isolated bright groups, excluding catalogue neighbour cores from measured spike strips. Faint residual crosses can remain. Unresolved/overlapping groups and non-converged fits are deferred.

Accuracy and visual quality matter more than analysis/rendering speed. Preserve subpixel motion and full-resolution deep-zoom sampling.

Reuse saved images, WCS, catalogue and scenes even after switching the current Siril image. Do not repeat AI removal or Gaia queries when a suitable cache exists.

Defaults: 60 seconds, 1.3× final zoom, 24 fps, 80 pc travel, 1.5-second easing at each end. The interface uses 1×–101×. Project `zoom` and pipeline options retain percent increase (0–10000%) for compatibility; convert only at the UI boundary.

Never overwrite exports. Names record version/mode/duration/zoom; collisions get numeric suffixes. Field preparation version/time and rendering version/time are separate. Historical unversioned analysis must remain labelled unversioned.

Commit each completed change with its release version in the commit message. Keep each change independently referenceable; bump the shared version and changelog under the major.minor.patch rules. Use patch releases for small usability/presentation refinements; reserve minor releases for substantive capabilities or deliberate extraction/rendering behavior changes. Keep the already-released 0.9.0 version as requested.

Astro-TIFF uses ImageDescription tag 270, short FITS cards and LF/CRLF endings. TIFF dimensions are authoritative; preserve WCS/SIP/date cards and use the TIFF Orientation tag for raster storage, not the embedded ROWORDER. Tested with local M45/M33/M13/zenith Astro-TIFF files.

Standalone launches must not import `sirilpy` or require Siril. Keep image loading at the source boundary and share the same project/render pipeline between entry points. Treat TIFF/PNG WCS references as user-supplied framing assertions; validate dimensions, do not claim that dimensions verify registration.

## Navigation and date UX

Standalone startup without explicit input restores the last selected image/project, including an external WCS reference when available. Explicit CLI inputs win; Siril keeps its current-image workflow. File dialogs start in the last successfully selected folder. Missing/corrupt preferences and missing last inputs must not block startup. Remember project folders after successful preparation or partial work so a restart resumes saved snapshots. Preferences are local to the checkout; avoid putting user paths in Git. A read-only preferences location must not break processing.

Explain that observation date is for Gaia proper-motion matching, not an export timestamp or a check that rendering succeeds. Prefer capture metadata. Since 0.9.0, export/file metadata and filesystem creation/modification time can supply a clearly labelled approximate matching epoch when capture time is absent. Never use POSIX ctime as creation time. Manual year/month values are approximate. Carry date_info through solving, preparation, scene/render provenance and restarts, with DATEAPPX/DATESRC on internal FITS copies. Do not reinterpret existing prepared fields or change extraction/cache schemas.

## Solver diagnostics

Worker stage messages go to both timestamped terminal output and the in-app Details log. Diagnostic string events carry a detail flag through the worker signal; verbose-only output never replaces the stage label. Terminal output stays concise. Details always contains the full captured worker log, including diagnostics collected while collapsed; there is no Verbose checkbox or filtering/replay preference. Ignore legacy verbose preferences. Capture worker tracebacks in Details without replacing the concise status. Keep complete raw solver logs regardless of verbosity. ASTAP stdout/stderr is captured in a retained per-attempt `.spacer-logs/` file and tailed incrementally while the process runs. Enable its `-progress` flag; preserve split UTF-8 characters and partial/CR-delimited lines. Poll without blocking cancellation; report elapsed time after ten seconds of quiet. Do not wait until exit or keep only the last lines. Keep errors concise and link the full log path. Persistent logs are outside project folders and ignored by Git; failure still creates no new project.

NGC2403 JPEG diagnostic (4624×3063): no embedded WCS. The old 500-star search failed although the matching linear FITS solved immediately. Raising the sample to 2000 found the processed field; refinement on original mono pixels at the measured scale with 5000 stars recovered SIP and reduced corner differences from ~90 arcsec to <2 arcsec against its existing FITS solution. Preserve full diagnostics across all attempts.

## Optional plate solving

Only offer Solve sky position for standalone images without a usable solution. Reuse native FITS/Astro-TIFF and Siril JPEG EXIF WCS. JPEG pixels are EXIF-transposed before solving/preparation so both use the same frame. Solving runs in the shared worker with timeout/cancellation; never pass the original file to ASTAP with `-update`.

The primary proxy is same-size mono scaled to 0–65535, following the local Siril_ASTAP_PlateSolve reference. Search uses 2000 stars, then a background-subtracted compact-peak proxy, then a 500-star original-pixel fallback. All candidates must be confirmed on original mono pixels: try 5000 and 2000 stars at the measured FOV, then 3000 at a 1% wider scale bracket. Compact proxies are seeds only; never commit their astrometry directly. Compare centre/corners and parity against the seed and reject an inexact final scale. This consistency screen is not an independent catalogue validation. A seed explicitly marked inexact permits a wider edge correction. More stars are not always better: real M45 5000-star refinement produced catastrophic SIP, and NGC2403 10000-star refinement was worse. Keep the bounded samples and rejection tests. One total timeout covers attempts; cancellation and logs apply to each. Record actual star sample, FOV/radius and acceptance per attempt. An optional target in the main panel limits initial searches to min(configured radius, 5°); final original fallback retains the configured radius. Validate ASTAP's return code, PLTSOLVD flag, dimensions, celestial WCS, scale and finite corner coordinates. Remove old astrometry before merging WCS/SIP; preserve original colour pixels, geometry and date. Commit `source_wcs.fits` and a stage=`solved` project only after success. Solve failure leaves the selected image and no new project directory. A solved project resumes without ASTAP/source access; require a documented matching epoch (captured or inferred) and permit engine selection until first preparation. Do not redo existing preparation after settings changes.

Real validation: installed ASTAP/D20 solved a downsampled finished M13 JPEG with position/field-height hints in approximately 0.5 s solver time. Center agreed with the original WCS to 0.8 arcsec; corners differed by 38–44 arcsec (ASTAP reported insufficient quads for SIP). In 0.9.3, full-resolution M45/M33 JPEG exports solved with approximate position hints and auto FOV: maximum centre/corner differences 7.71 and 3.04 arcsec against their embedded TIFF solutions. The supplied original NGC2403 JPEG solved using its object name and auto FOV: centre 0.42 arcsec, corners <1.97 arcsec against the matching linear FITS. Source hashes stayed unchanged. M45 needed the third refinement bracket after a rejected unstable SIP and a failed smaller sample. Offscreen UI inspection confirms the object field is visible beside Solve without Advanced settings. This checks integration and orientation, not universal solvability or physical accuracy. Astrometry retains solver settings, SPACER version/time and the raw solver log.

## Interface conventions

Keep project choice, duration, direct final zoom scale and one state-specific primary action in the main window. Advanced preparation/tool paths live in a scrollable dialog; diagnostics use a separate Details disclosure. Use native palette and widgets, meaningful text, keyboard focus and visible progress. Surface required setup when validation fails. Disable settings and project switching during worker execution. Test new, partial, prepared, busy and failed states after changing the interface. Render progress uses structured frame/total/elapsed callbacks, throttled to roughly four updates per second; never parse log text for counters. Keep the finalizing stage below 100% until FFmpeg and project recording succeed. ETA is an estimate based on completed frames; unknown-duration preparation uses an activity indicator. Reset counters for a new run/input and keep successful 100% visible until then.

## Scientific scope

Gaia DR3 positions are propagated to the observation epoch. Bailer-Jones geometric distance estimates and bounds are used. RUWE and uncertainty screens do not guarantee accurate distances or correct separation of photographed light. Nebulosity is flat; brightness/PSF presentation is not physical light transport.

ASTAP and its star database, StarXTerminator, StarNet and FFmpeg are external. Do not bundle proprietary models, binaries or licenses. Images are processed locally; field coordinates are queried through GAVO.

## Validation

    python -m unittest discover -s gaia_flythrough -p "test_*.py"

Initial import: 13 passing tests. Version 0.5.0 adds five offscreen Qt workflow tests (skipped if PyQt6 is unavailable). For visual changes also inspect real-image first/middle/final frames and close-ups around moved bright stars. Tests alone previously missed spike artifacts.

Large M45/NGC6914 audit fields and videos are excluded from Git. Locate an existing local prepared field or request one when real-image validation is needed; preserve historical comparisons.

## New-chat prompt

Continue developing SPACER in this repository. Read README.md, DEVELOPMENT.md and gaia_flythrough/CHANGELOG.md, then inspect the code and git status. Preserve the Iterative-only workflow, persistent projects, reusable prepared fields, provenance and non-overwriting exports. Keep scientific confidence separate from cosmetic motion. Bump the shared version and update the changelog for shipped changes. Run relevant tests; inspect real first/middle/final frames and bright-star close-ups for visual changes. My next requested change is: [describe change].

Progress layout: reserve two lines for stage/counters and retain hidden progress/cancel sizes. New messages must not change window/progress/action geometry. Show main and Advanced solver controls only when a selected standalone image lacks usable coordinates. Test visibility transitions, geometry under wrapped messages, full diagnostic capture while collapsed, no verbosity control and concise terminal output.

Siril JPEG metadata: EXIF ImageDescription (270) may contain the same newline-separated FITS cards as Astro-TIFF, including WCS/SIP and DATE-OBS. Reuse it only with a complete header, exactly matching NAXIS1/NAXIS2, normal EXIF orientation (1/absent) and a finite nonsingular sky transform. A resized or EXIF-rotated JPEG must be solved in its displayed frame; never attach stale original geometry. Keep ordinary/incomplete descriptions unsolved. Preserve orientation handling for unsolved JPEGs. The supplied m27_duo.jpg (5198×3471) already carries a full solution identical to m27_duo.fit at centre/corners; opening now bypasses ASTAP, hides solver controls and uses capture date 2026-07-17. Raw ASTAP retries on this processed JPEG still failed confirmation; this fix reuses existing astrometry and does not claim improved solving of metadata-free M27 images. JPEG pixels and hash verified unchanged; inspected its ready-to-prepare window.

Header layout: keep the title/subtitle in one vertically fixed container with an explicit gap. A final expanding spacer absorbs spare window height below all content; do not distribute it among header labels or sections. Verify header/project-top geometry across tall/wide windows, Details toggles and unsolved input selection.

Catalogue queries: preserve existing catalog.csv/scene caches. For new queries, sample a 9×9 grid per pixel rectangle, use its ICRS centre and maximum spherical separation plus 5% margin. Keep a single cone up to 3°; recursively quarter wider regions until ≤2.5°. Test dense coverage at both poles and across RA=0; do not use RA/Dec bounding boxes. This targets ordinary solved photographic fields, not arbitrary all-sky projections; invalid/nonfinite or highly distorted footprints fail explicitly.

Use TAP VOTable QUERY_STATUS (including trailing OVERFLOW) and the per-response 200000 row bound; never assume a successful HTTP status or CSV proves completeness. Overflow regions subdivide without changing magnitude, distance or RUWE screening. Empty parts are valid; an entirely empty catalogue is an error. Sequential queries avoid flooding the service. Each server job has a five-minute polling deadline and bounded HTTP calls; cancellation checks polling and requests a remote abort. Check cancellation during CPU matching too. The overall wide-field download can exceed five minutes because it contains several jobs. Progress remains concise.

catalog-parts/ hashes include endpoint, request schema, row bound, exact cone and magnitude. Only completed parts are written via temporary+replace; overflow markers allow retries to skip known-too-dense parents. Merge by exact Gaia source_id (never floating point); publish final CSV atomically only after every region succeeds. Keep parts on failure/cancel. Existing preparation/Iterative schemas are unchanged. Test partial retry, overflow, trailing status, missing status/errors, empty results, duplicate IDs, 64-bit IDs, cancellation/abort and query-key isolation. A larger field can increase first-download/matching/render time; never claim zero slowdown.

Real wide-field validation: the saved Polaris WCS (5292×3488, centre Dec≈89.50°, corner radius≈3.92°) produces four ~2.075° cones. Installed-environment live GAVO download at G<18 returned 86412 unique sources in 276.84 seconds; cached reload took 0.23 seconds. Test outputs are under /private/tmp/spacer-wide-polaris, separate from the user project. These timings are observations, not service guarantees.

The same real Polaris layers completed core preparation with 32746 moving stars from 50795 detected peaks in 156.35 seconds, using the downloaded catalogue and existing star-removal layers. The existing project metadata was verified unchanged. All 40401 sampled points across the actual SIP footprint fall inside the planned cones. This validates catalogue-to-image matching; it is not a full Iterative refinement/video timing benchmark.

Wide-field guard: new preparation supports a maximum 5° centre-to-footprint radius (approximately a 10° diagonal). Check the unpadded sampled footprint before new project creation/star removal and before catalogue downloads, including resumptions using the saved WCS. Larger inputs get an approximate same-aspect central crop size, with 2% margin, based on tangent-plane scaling. Require a fresh solution and new project for cropped images; never crop automatically. Prepared historical scenes still render directly. This bounds supported angular extent, not star density or guaranteed runtime. The real Polaris radius 3.92486° passes.

Preparation progress (0.9.9): pass options.stage_progress through pipeline args and Iterative refinement to the worker's structured (label, done, total, elapsed) signal. StageProgress emits start, completed-item updates at most about four times/second, and exact completion; negative totals denote unknown work, zero is a known empty stage. Generator tracking counts skipped/deferred entries after they return, and never counts an entry that fails or is cancelled. Cover peak location, group association/separation, measurements, Gaia positions/matching, core fitting, Iterative selection/groups, and catalogue regions. Region totals expand on overflow subdivision. Do not parse log strings for counts. Each stage has its own percentage/ETA; do not imply overall-job progress. Unknown native operations explicitly switch to activity mode. Keep video finalization below 100% until export completion. Log per-group Gaia IDs as diagnostics so they cannot replace the stage label. Preserve numerical extraction behavior and cache schemas.

Validation: 75 tests pass, including real synthetic extraction with per-stage exact totals, deferred/failed Iterative-group counting, cancellation/error non-completion, throttling, pipeline forwarding, adaptive catalogue counts, Qt stage resets/geometry and full diagnostics available on first opening Details. Offscreen screenshots of known/unknown stages and expanded Details were inspected. No extraction/rendering parameter changes.

Advanced settings width: explicitly use AllNonFixedFieldsGrow on all three forms so platform-specific form defaults do not constrain path rows. Path containers and inputs expand horizontally, with stretch assigned to the input and compact fixed Browse buttons. Check both normal and wide dialogs, including engine, ASTAP/database, FFmpeg and project paths; do not hardcode field widths. Verified 700/1100 px dialogs: outer path fields expand 507→907 px; native platform rendering may differ.

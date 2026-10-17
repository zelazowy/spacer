# Gaia Flythrough releases

## 0.10.1 — 2026-10-17

- Raise the default and supported maximum moving-star limit to 50,000; desktop Advanced settings accepts 100–50,000, and the core API/CLI accepts 1–50,000. Share the upper boundary across validation, UI and CLI help.
- Preserve explicitly saved project limits; older 5,000 settings can be raised in Advanced settings. Existing prepared fields can use only already saved stars; additional omitted cores still need fresh preparation.
- Keep the 16-attempt/64-neighbour Iterative guards and full-reference matching checks. A higher limit permits more reliable stars but does not guarantee 50,000 matches or the speed measured with a 5,000 limit.
- Verify the new default/boundaries, UI forwarding and saved lower limits with 81 passing tests. Corrective tuning of the 0.10 limit; algorithms and cache schemas are unchanged.

## 0.10.0 — 2026-10-17

- Default to at most 5,000 moving-star core candidates, prioritizing photographed brightness after full-reference ambiguity and unchanged distance/quality checks. Expose Moving stars (maximum) in Advanced settings and remember it per project. Record selection/budget provenance in scenes and render metadata.
- Bound Iterative work to 16 attempted fits and 64 neighbours per fit. Defer entire crowded groups rather than discarding their neighbours; use spatial neighbour queries and preserve catalogue fit order. Retain all Gaia reference data and existing catalogue/star-removal caches.
- Apply lower limits to existing prepared fields without rewriting their saved scenes: restore unselected sprites into the stationary layer using exact PNG light addition. Reapply the cap after Iterative recovery. Higher limits can use only stars available in saved analysis.
- Validate supplied M8 and Polaris with 5,000-mover views: exact first-frame reconstruction, inspected first/middle/final samples, unchanged source scene/project hashes. M8 guarded refinement took 8.6 s; three-frame Polaris rendering measured 4.3 s vs 22.6 s for its original 33,145-star field. Fresh cached-layer core preparation took 41 s for M8 and 30 s for Polaris, fitting 5,000 candidates in each case. First catalogue downloads remain unchanged.
- Add capped-fit/ambiguity, reconstruction, cancellation, saved-scene/render preference and dense-group/fit-budget regression coverage. Minor release for deliberate moving-star selection and refinement-work limits; compatible extraction/cache schemas remain unchanged.

## 0.9.11 — 2026-10-16

- Use indeterminate activity progress while waiting for a live Gaia region query or its unknown-size result download. Hide stale region counters/time estimates during that wait.
- Restore counted region progress once each completed result is saved, including fast requests. Add a remote-wait/count-restoration regression check; query behavior and caching are unchanged.

## 0.9.10 — 2026-10-16

- Let Advanced settings inputs use the available dialog width, including engine/ASTAP/database, FFmpeg and project paths. Keep Browse buttons compact and give extra row space to the input.
- Set form growth explicitly across platforms; inspect normal and wide dialog layouts. Corrective layout patch; settings and processing are unchanged.

## 0.9.9 — 2026-10-16

- Show determinate progress with completed/total counts, elapsed time and estimated remaining time for counted preparation work: peak location, star groups/measurements, Gaia positions/matching, core fitting, Iterative selection/groups and catalogue regions.
- Use structured per-stage callbacks, throttled to about four updates/second. Count processed skipped/deferred entries; failed or cancelled entries never claim completion. Reset progress for each stage and use activity mode only for unknown totals. Preserve video finalization behavior.
- Remove the Verbose checkbox. Details immediately shows the full captured diagnostic log, including messages collected while collapsed; keep the current step and launching terminal concise. Put per-group identifiers and worker tracebacks in diagnostics.
- Add preparation/Iterative counting, cancellation, throttling, callback forwarding, adaptive catalogue totals and Qt display/logging regressions; inspect progress/Details screenshots. Presentation patch; extraction algorithms, cache schemas and saved projects are unchanged.

## 0.9.8 — 2026-10-15

- Bound new preparation to a 5° centre-to-footprint radius (about a 10° diagonal), retaining support for the tested 300 mm full-frame Polaris field.
- Reject larger fields before creating new outputs, running star removal or requesting Gaia data. Suggest an approximate central crop size and ask for a newly solved cropped image in a new project; never alter source pixels automatically.
- Use the saved solution when resuming incomplete projects; prepared historical scenes keep rendering directly. Add limit/crop and early-rejection regression checks. Corrective scope/usability patch; no extraction changes.

## 0.9.7 — 2026-10-15

- Replace the prototype's 3° catalogue-radius rejection with overlapping spherical image-region queries. Cover polar fields and RA wrap; keep compact fields to one request when possible.
- Check TAP VOTable completion and trailing overflow status. Subdivide dense/truncated regions without dropping faint stars or changing quality/distance screens; deduplicate exact Gaia identifiers.
- Cache complete region downloads and subdivision decisions for retries. Publish the merged catalogue atomically only after complete success; preserve existing catalogues, prepared scenes and star-removal work.
- Add region/star-count progress, cancellation during polling/matching and remote aborts. First preparation still depends on field density and service speed; subsequent renders reuse preparation.
- Validate the real 5292×3488 Polaris footprint near Dec +89.5°: four regions, 86,412 unique sources; first query 277 s, cached reload 0.23 s on this run. Full-resolution core matching accepted 32,746 moving stars in 156 s using existing star-removal layers.
- Add wide/polar/wrap coverage, overflow, partial retry, deduplication, empty/incomplete response, cancellation and query-key regression checks. Corrective catalogue-coverage patch; extraction/rendering algorithms and cache schemas are unchanged.

## 0.9.6 — 2026-10-15

- Keep title/subtitle height and spacing fixed in a single header container. Put spare window height below the content instead of stretching header labels and section spacing.
- Check header geometry across window resizing, Details toggles and image-state changes; inspect the M27 window. Presentation patch; image processing and saved projects are unchanged.

## 0.9.5 — 2026-10-15

- Read existing Siril FITS-style metadata from JPEG EXIF ImageDescription, preserving WCS/SIP and capture date. Share the complete description parser with Astro-TIFF.
- Reuse only matching dimensions and normal EXIF orientation; reject stale/resized/rotated or invalid geometry for a fresh solve. Keep original pixels/files untouched.
- Fix the supplied M27 JPEG opening as unsolved: its embedded solution now opens ready to prepare, with solver/object controls hidden and no ASTAP run. Its coordinates match the corresponding FITS at centre/corners and the capture date is restored.
- Add JPEG metadata, SIP/date/pixel preservation, stale/rotated/incomplete metadata and no-solver UI regressions. Input-compatibility patch; ASTAP algorithms and existing project caches are unchanged.

## 0.9.4 — 2026-10-15

- Keep status and counter areas at fixed heights and reserve progress/cancel space; wrapped messages no longer move the controls.
- Default to concise step logs. Add a remembered Verbose checkbox beside Details for live diagnostic output and replay of the retained session history. Technical messages do not replace the current step; raw solver files remain complete.
- Hide Advanced ASTAP controls as well as the main solve/object fields unless a standalone image lacks a solution. Keep Details closed during solving unless the user opens it; failures still reveal it.
- Add geometry, visibility, diagnostic-filtering/replay and terminal-verbosity regression checks. Corrective interface patch; solving and rendering algorithms are unchanged.

## 0.9.3 — 2026-10-15

- Fix processed JPEG solving with a larger initial star sample, a measured compact-peak fallback and confirmation on original photographic pixels at the recovered scale. Keep original RGB pixels and source files unchanged.
- Reject unstable centre/corner/parity changes and inexact final scales. Retry bounded star samples and a small scale bracket; compact proxy solutions are never committed directly.
- Put optional Object name beside Solve sky position. Accept names or numeric RA/Dec; start nearby when a target is provided and preserve the configured broader radius for the final fallback.
- Retain live diagnostics, cancellation and one overall timeout across attempts; record strategy, sample and actual search settings in project provenance.
- Validate installed ASTAP/D20 on the supplied NGC2403 JPEG and full-resolution M45/M33 JPEG exports with approximate targets and auto FOV. Maximum centre/corner differences against existing WCS: 1.97, 7.71 and 3.04 arcsec respectively; source hashes unchanged. Reject a real unstable M45 refinement before accepting its alternate sample.
- Add proxy-grid, confirmation/failure, unstable-refinement, target-radius and scale-bracket regressions; inspect the revised main window. Corrective patch; rendering and existing project caches are unchanged.

## 0.9.2 — 2026-10-15

- Stream ASTAP stdout/stderr while it runs, including its progress messages; show Details automatically during solving.
- Mirror worker stage messages to the launching terminal and timestamp terminal/in-app logs. Report source dimensions, search settings, database, exact command, exit status and elapsed time.
- Add quiet-solver elapsed-time updates and retained per-attempt diagnostics in ignored `.spacer-logs/`, including failed/cancelled/timed-out attempts. Keep error dialogs concise with the diagnostic path.
- Preserve partial lines and UTF-8 split across output chunks. Add live-before-exit, retained-log, Unicode and quiet-heartbeat regressions.
- Inspect the supplied NGC2403 JPEG with installed ASTAP; no match in the initial guided trial despite ~500 detected stars. Source verified unchanged.
- Patch diagnostics improvement; solver search defaults, image pixels and rendering are unchanged.

## 0.9.1 — 2026-10-15

- Replace the video-render activity indicator with a filling bar, completed/total frame counts, elapsed time and an estimated remaining time.
- Report structured renderer progress through the worker, throttled to keep the interface responsive. Count sparse audit-frame exports by frames actually submitted.
- Show Finalizing MP4 after all frames are submitted; retain successful 100% until another input/run. Failures and cancellation do not claim completion. Preparation without known totals keeps its activity indicator.
- Add renderer-count/cancellation, pipeline-forwarding and Qt finalization/reset regression coverage. No image, matching, extraction or export-format changes.
- Patch presentation update. Retain 0.9.0 as released; use patch versions for small usability refinements.

## 0.9.0 — 2026-10-15

- Fill the matching date from FITS/Astro-TIFF observation headers, EXIF capture/digitized dates or a matching WCS reference. Fall back to image file-date metadata, filesystem creation time where supported, or modification time.
- Label fallback dates as estimates and show their source in Advanced settings. Accept manual year/month estimates, using mid-year/mid-month dates explicitly marked approximate.
- Preserve date value/source/approximation through ASTAP solving, project preparation, saved scenes, render metadata and reopening. Add DATEAPPX/DATESRC to internal FITS snapshots; never change source files or historical prepared scenes.
- Add metadata precedence, invalid-date, filesystem, partial-date and Qt autofill/override regression coverage.
- Minor usability feature; matching algorithms, extraction schemas and Iterative revision are unchanged.

## 0.8.0 — 2026-10-15

- Remember the last standalone image/project and WCS reference across launches. Restore it on startup without arguments; explicit CLI input takes priority and Siril keeps its current image.
- Remember successful image/project/reference picker directories. Skip missing remembered inputs safely; tolerate missing, corrupt or unwritable local preferences.
- Keep atomic navigation settings in the ignored `.spacer-settings.json` beside the app; project data and export provenance remain separate.
- Explain observation date beside the input and in documentation: Gaia positions are corrected for stellar proper motion at capture time. A render completing with a random date does not validate the match. Date handling and scientific calculations are unchanged.
- Add restart/restore regression coverage. Minor navigation feature release; extraction schemas and cache revisions are unchanged.

## 0.7.0 — 2026-10-15

- Accept finished JPEG images, applying EXIF orientation consistently before solving and preparation.
- Add explicit Solve sky position for unsolved standalone FITS/TIFF/PNG/JPEG input. Keep existing FITS/Astro-TIFF solutions automatic; move the separate-FITS fallback to Advanced settings.
- Discover ASTAP; expose its executable/database and optional object-name or numeric-position, field-height, search-radius and downsampling hints in Advanced settings. Use the existing Siril ASTAP script as the proxy/CLI reference.
- Run ASTAP with timeout/cancellation on a temporary same-size monochrome proxy. Validate its solution and merge only astrometry into original RGB pixels; source files and existing projects remain untouched.
- Save successful WCS, source snapshot, solver provenance/settings and log in a reusable stage=solved project. Permit date/engine setup before first preparation; resume without the source image or ASTAP. Failures keep the image selected for retry.
- Validate with mocked success/failure/timeout/cancel tests, JPEG orientation and Qt workflow tests, plus an actual installed-ASTAP solve of a processed M13 JPEG. M45/M33 trial copies did not solve; matching remains image-dependent.
- Minor feature release; extraction schemas, Iterative revision and render behavior are unchanged.

## 0.6.2 — 2026-10-15

- Read embedded Astro-TIFF plate solutions directly from TIFF ImageDescription tag 270, including observation date and SIP distortion coefficients. Support short FITS cards and LF/CRLF line endings; use TIFF dimensions when redundant FITS axis cards are absent.
- Solved Astro-TIFF opens ready for preparation without a separate reference chooser. Plain or unsolved TIFF/PNG retains the explicit coordinate-reference step.
- Respect TIFF Orientation independently of embedded ROWORDER; reject unsupported rotated orientations. Preserve source files and existing rendering/cache contracts.
- Add parser/orientation/UI regression tests and validate input loading against local M45, M33, M13 and zenith TIFF files.
- Corrective input-compatibility patch; extraction schemas and rendering algorithms are unchanged.

## 0.6.1 — 2026-10-15

- Remove the automatic second file dialog after opening a TIFF/PNG. Keep the photo selected and show an explicit sky-coordinate requirement and Choose solved FITS action in the main Project panel.
- Explain that the reference is the same image's plate solution, separate from the automatically selected output folder. Disable rendering until a reference is selected; cancelling retains the photo.
- Validate reference dimensions/pixels before accepting it. Add a regression check for the single image chooser and cancel behavior.
- Corrective usability patch; project formats and rendering algorithms are unchanged.

## 0.6.0 — 2026-10-15

- Add `SPACER.py`, a standalone desktop entry point with image/WCS/project startup arguments and version reporting; no Siril import or installation is needed.
- Extract the shared Qt window/worker into `app.py`; retain the Siril launcher as a thin optional integration with unchanged pixel snapshot/autostretch support.
- Add file loading for already-stretched solved FITS, or monochrome/RGB TIFF/PNG plus a matching solved FITS reference. Validate pixels, dimensions and celestial WCS; normalize row orientation without changing source files.
- Open/resume projects from either launcher without the source image. Keep Iterative-only scenes, defaults, cache contracts, framing and non-overwriting exports.
- Standalone input intentionally requires pre-stretched pixels; no plate solver or replacement for Siril autostretch is added. Document installation and external engine/FFmpeg requirements.
- Minor feature release; extraction schemas and Iterative cache revision are unchanged.

## 0.5.1 — 2026-10-15

- Replace “Final zoom increase” percentages and the explanatory hint with direct “Final zoom” scale (default 1.3×, range 1×–101×).
- Preserve existing project values, pipeline units, framing and export metadata through conversion at the UI boundary. Keep fractional values from older projects without rounding them away.
- Record the development rule to commit every completed change with its version.
- Corrective interface patch; rendering algorithms, extraction schemas and cache revision are unchanged.

## 0.5.0 — 2026-10-15

- Reorganize the Siril window around Project and Flight, with one primary action for preparation, resuming or rendering.
- Move stretch, star-removal tools, observation date, FFmpeg and folder paths into a scrollable Advanced settings dialog; automatically reveal required setup errors.
- Keep status and indeterminate progress visible; hide diagnostics under Details, opening it after processing errors. Show cancellation while processing and lock project/settings changes until the worker stops.
- Add explicit New from Siril project creation, readable saved/current-image summaries, automatic installed-engine selection and a live zoom magnification hint.
- Preserve native Qt controls/palette, existing defaults, Iterative extraction, caches and export provenance. Add five offscreen interface workflow tests and inspect rendered UI states.
- Minor feature release; extraction schemas and Iterative cache revision remain unchanged.

## 0.4.0 — 2026-10-15

- Iterative is the sole Siril scene style; new projects no longer prepare Dynamic scenes.
- Stable per-image project folders replace timestamped defaults. Open projects across restarts with saved duration, zoom, FFmpeg and latest export links.
- Atomic `project.json` records schema, project provenance, preparation progress and render settings separately from field/export provenance.
- Resume partial projects using the saved snapshot, validated star-removal output and cached catalogue. Completed fields reuse all analysis for new render variants.
- Older prepared folders remain importable; historical exports and Natural/Dynamic assets are preserved. Changed source pixels or removal choices use a separate project folder.
- Minor feature release under major.minor.patch rules; extraction schemas and Iterative revision are unchanged.

## 0.3.0 — 2026-10-15

First explicit release baseline after the M45 iterative experiments.

- Natural, Dynamic and experimental Iterative modes; reusable prepared fields.
- Iterative separation measures coloured diffraction-spike details while excluding catalogue neighbour cores.
- Tool version appears in the Siril window, preview heading, output filenames, JSON metadata and MP4 comment.
- Field preparation version and time are recorded separately from render version and time. Older fields are explicitly unversioned.
- Existing exports remain unchanged; filename collisions receive numbered suffixes.

Use major.minor.patch: major for incompatible workflows, minor for features or deliberate extraction/rendering behaviour changes, patch for corrective fixes. Update the shared VERSION in version.py and add a release entry whenever shipping changes. Internal extraction schemas and iterative cache revisions are separate compatibility markers.

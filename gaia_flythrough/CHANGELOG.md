# Gaia Flythrough releases

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

# Development context

[Agent rules](../AGENTS.md) · [Changelog](../CHANGELOG.md) · [Scientific scope](SCIENCE.md) · [Validation record](VALIDATION.md)

This file describes the current implementation. Repository-wide working rules live in `AGENTS.md`; release-by-release history belongs in the changelog.

## Current state and next direction

SPACER has standalone and Siril Qt launchers, reusable projects, revisioned star calculations, interactive previews and MP4 export. Both launchers expose Iterative separation. Standalone solving is optional; Siril input requires an existing plate solution. Approximate distance coverage is optional and off by default.

The next priority is **separation of overlapping bright-star halos and diffraction spikes**. The M45 extended-distance test increased movers from 6,328 to 9,392 while accepted bright groups stayed at 14. Broader catalogues helped faint-star motion; bright-bright overlap remains the dominant separation blocker. A promising next experiment is simultaneous modelling of overlapping bright PSFs and their smaller neighbours, evaluated against preserved baseline scenes. This direction is not implemented yet. Do not replace the remaining guards with whole-island motion.

A unified headless CLI, packaged installers and website remain future work. `flythrough.py` is still a prototype CLI with separate photo/starless/WCS inputs.

## Module map

| File in `gaia_flythrough/` unless noted | Responsibility |
| --- | --- |
| `../SPACER.py` | Standalone entry point and launch arguments |
| `../Siril_Gaia_Flythrough.py` | Thin Siril adapter; snapshots current image/header |
| `app.py` | Shared Qt controls, worker, projects, target picker and diagnostics |
| `image_source.py` | Disk inputs, embedded Astro-TIFF/JPEG metadata, raster orientation |
| `siril_pipeline.py` | Working layers, external engines, project state, calculation revisions and exports |
| `flythrough.py` | Matching, conservative compact-core extraction, subpixel renderer, prototype CLI |
| `iterative_deblend.py` | Alternating halo/spike/neighbour fits and bounded retries |
| `density.py` | Moving-star limits, bright-group budgets and stationary-light restoration |
| `catalog.py` | Spherical query planning, TAP completeness, resumable parts and exact-ID merge |
| `distances.py` | Distance-selection policy, Hipparcos-2 ingestion and Gaia duplicate screening |
| `motion.py` | Independent-zoom and target-distance projection contracts |
| `targets.py` | Bounded familiar-object SIMBAD queries and distance summaries |
| `photo_date.py` | Matching-date inference and provenance |
| `preferences.py` | Local atomic navigation settings |
| `task_progress.py` | Structured per-stage counts and diagnostic events |
| `astap_solver.py` | Cancellable solver attempts, original-pixel confirmation and logs |
| `viewer.html` | Self-contained interactive scene/inspection template |
| `version.py` | Shared public version and UTC provenance timestamps |

## Setup and checks

Install [requirements.txt](../requirements.txt) in an isolated Python environment. The standalone app and core tests do not need Siril; only its launcher uses `sirilpy`. FFmpeg is needed for actual video exports; ASTAP/database and removal engines are separate dependencies.

```sh
python -m unittest discover -s gaia_flythrough -p 'test_*.py'
python SPACER.py --version
```

Tests include synthetic matching/extraction, projection, rendering, caches/revisions, solver command plans, source preservation, catalogue overflow/cancellation and offscreen Qt workflows. Use [validation guidance](../AGENTS.md#validation-and-releases) and the [recorded image checks](VALIDATION.md) when selecting additional checks. Large image fixtures and generated exports are deliberately excluded from Git.

## Project lifecycle and provenance

A project saves source pixels/WCS, star-removal layers, catalogue references, core and refined scenes. `project.json` records stage/settings and, after recalculation, a `calculation_path` pointing into `calculations/`. Readers, UI summaries and render metadata must follow this active revision. Reject missing or escaping paths instead of silently loading older root scenes.

Recalculation requires saved photo/starless PNGs, WCS and the original catalogue. Fit into a temporary project-local directory, then rename to `calculations/v<version>_<index>/` and atomically switch state only after success. Preserve root analysis, old revisions and exports. It ends ready to render without a video or FFmpeg requirement. Optional coverage may download missing supplemental references; ordinary cached recalculation needs neither network nor star removal.

Keep preparation version/time separate from render version/time. Exports include settings, motion/selection provenance and active calculation revision. Existing compatibility admits Iterative revision ≥2; new fitting currently records revision 3 and extraction version 6 (conservative core version 4). These are compatibility markers, not public release numbers. Do not bump them just to force old projects through new fitting.

### Moving-star limits

- Default/maximum: **50,000**; desktop range 100–50,000; core API/CLI range 1–50,000. Respect saved lower limits.
- Preserve the complete catalogue for uniqueness/companion checks. After screening, prioritize expensive core fits by photographed peak strength.
- Bright-group work is bounded to **16 attempted fits**, with up to **96 neighbours** per group. Reject the whole oversized group; never trim neighbours to fit the budget. Failed fits count as attempted work.
- Use a finite-coordinate spatial index, then original strict tile/distance predicates and catalogue ordering.
- A lower render cap creates an in-memory view: select by exact PNG sprite flux, restore omitted sprites to the stationary PNG by integer addition/clipping, and preserve saved analysis. Reject unsupported fractional sprite origins. Apply the cap again after recovery and refresh coverage counts.

### Bright-star fitting

Conservative cores use smooth local Gaussian models and per-channel amplitudes. Iterative refinement fits isolated bright groups with independently modelled neighbours and measured coloured spikes; neighbour cores are excluded from spike strips.

Keep the convergence threshold **relative model change <0.001** and mean absolute residual **≤0.015**. Up to four non-converging, sufficiently low-residual groups can receive stabilised retries of up to 20 iterations. Retries retain admitted compact-neighbour shapes, refit amplitudes against robust local planes, damp updates and hold spike direction. Reject retry orientations more than 5° from a strong accepted-field consensus (at least three stars, circular concentration ≥0.98, modulo 90°). Unresolved/overlapping groups remain deferred.

## Catalogue contracts

### Gaia / GAVO

For each pixel rectangle, sample a 9×9 WCS grid, use the ICRS centre and maximum spherical separation plus 5% margin. A single cone can cover up to 3°; quarter wider regions recursively until ≤2.5°. Handle poles and RA wrap spherically, never with RA/Dec bounding boxes. Reject nonfinite/highly distorted footprints. Check the unpadded **5° field-radius limit** before new project creation/star removal and downloads; suggest a same-aspect central crop with margin, requiring a fresh solution.

Use VOTable `QUERY_STATUS`, including trailing `OVERFLOW`, and the per-response 200,000-row bound. HTTP success/CSV alone does not prove completeness. Subdivide overflow regions without making magnitude/distance/quality screening shallower. Empty parts are valid; an entirely empty catalogue is an error. Queries are sequential, with bounded HTTP calls and a five-minute polling deadline per job. Cancellation checks polling and CPU matching and requests remote abort when applicable.

Part-cache keys include endpoint, query schema, row bound, exact cone and magnitude. Only complete parts are atomically published; overflow markers retain subdivision decisions. Merge exact string/integer Gaia source IDs, never floating point. Publish final CSV only after every region completes. Preserve nullable/extra fields and completed parts on failure/cancellation. Existing `catalog.csv` remains authoritative.

### Optional distance coverage

`choose_distance` prefers strict geometric Gaia (finite RUWE ≤1.4; interval half-width ≤20%), then screened Hipparcos fallback, then photogeometric and broader geometric Gaia (half-width ≤50%, same RUWE gate). See [science](SCIENCE.md#stellar-distances) for interpretation. Retain the BJ flag as provenance; do not introduce an undocumented flag cut or invent RUWE for Hipparcos.

Supplementary caches are `catalog-extended.csv`, `catalog-hipparcos2.csv` and merged `catalog-motion.csv`; preserve the original catalogue. The Gaia extended query uses a left join so rows lacking distances still constrain image ambiguity. New extended calculation revisions retain the merged reference snapshot. Scenes/export metadata and `distance_coverage.json` record moving counts by source; keep those counts consistent after selection limits.

NASA HEASARC TAP `hipnewcat` serves degrees at epoch 1991.25 and proper motions in mas/year. Use `FORMAT=votable` with verified completion; its CSV format is unsupported. Filter ordinary single-component five-parameter solutions (`new_solution_type=5`, components=1), positive parallax/error, fractional error ≤0.2 and fit quality ≤3. Propagate to 2016 before unique ≤1 arcsecond Gaia matching. Reject multiple candidates within 3 arcseconds or uncertain 1–3 arcsecond associations. Preserve independent HIP IDs when attaching data to Gaia rows, then propagate selected astrometry to the image epoch.

The checkbox does not reinterpret cached analysis. Require explicit recalculation for a coverage change, remember it for partial preparation, publish it with successful revisions, and default historical scenes to strict coverage.

### SIMBAD targets

`targets.py` queries a padded cone, then filters actual WCS inclusion. Fetch at most 100 main familiar objects before their distance measurements; do not limit the joined object/measurement rowset. Use class descendants through `otypedef.path` (M33 is `GiG`, not plain `G`). Filter familiar aliases before applying the object bound; naturally order M, IC, NGC and the curated catalogues, preserving original names/aliases.

Distance measurements use bounded keyset pagination on `(oidref, mespos)` with 2,000-row pages. Reject overflow/incomplete results; do not silently truncate an object's measurements before deriving its approximate median. Retain individual values/references/range; the rounded summary does not inherit one paper's error bar. Selection is render provenance, not stellar-depth data or an optical-axis change.

Keep lookup off the GUI thread; discard stale-field responses. Closing must wait for the bounded worker. New images reset target distance to the unset zero state. Saved targets restore unless recorded coordinates lie outside the saved footprint.

## Motion contract

`motion.py` computes background and stellar scales separately. In target-distance mode, background uses `D/(D-s)` and extra stellar zoom is 1; stars already use their own `z/(z-s)` perspective. Never multiply target/background enlargement into stellar perspective again. Independent camera zoom retains its extra enlargement. Travel must be nonnegative and smaller than the target distance in target mode.

The UI presents a zoom scale **1×–101×**; project/pipeline `zoom` remains **percent increase 0–10000%**. Convert at the UI boundary only. The prototype CLI's scale range is separately limited to 1–1.5. Defaults: 60 s, 1.3×, 24 fps, 80 pc and 1.5 s end ramps.

## Image metadata and matching epoch

Astro-TIFF uses ImageDescription tag 270 with short FITS cards and LF/CRLF. TIFF dimensions are authoritative; keep WCS/SIP/date cards but use TIFF Orientation for raster storage, not embedded ROWORDER. External references assert same framing; dimensions cannot validate registration.

JPEG EXIF tag 270 may contain the same FITS-style solution. Reuse only complete, dimension-matching, finite/nonsingular WCS with normal orientation. EXIF-transpose unsolved JPEG pixels before solving and preparation. Never attach stale WCS to resized/rotated pixels.

Prefer capture metadata; file dates are labelled approximations. Never infer capture from POSIX ctime. Manual year/month values are approximate. Carry `date_info`, `DATEAPPX` and `DATESRC` through private snapshots, solving, scenes, renders and restarts. Existing prepared fields keep their matching epoch.

## ASTAP implementation

The optional solver works on same-size private mono proxies scaled to 0–65535, following relevant strategies from the separate Siril helper. Never import that helper or reproduce its source-update/mirror workflow.

With usable pointing/optics hints, prepend header-guided 500/2,000-star ordinary attempts and a compact attempt. Explicit target/FOV wins; omit command overrides only when delegating those hints to ASTAP. Optics without pointing must not force a local 30° search. Other recovery uses 2,000-star ordinary, reusable background-subtracted compact peaks and a 500-star original fallback. Skip redundant ordinary attempts after insufficient detection.

Compact results are seeds only. Confirm on original mono pixels using 5,000/2,000 stars at measured FOV, then 3,000 at a 1% wider bracket. Compare centre/corners, parity and scale; reject inexact final scale and unstable refinements. More stars can worsen SIP. This is consistency screening, not independent catalogue validation. An explicitly inexact seed allows wider edge correction; retain warnings when WCS sidecars omit them.

Validate return code, PLTSOLVD, dimensions, finite celestial WCS/corners and scale. Repair invalid EQUINOX, remove obsolete PC/SIP when appropriate, clean stale sidecars before attempts and merge into a private copy of the original header. One total timeout covers attempts. Save snapshot/project only after success; failure creates no new project. A solved project resumes without ASTAP or the source and keeps removal settings editable until preparation starts.

Retain per-attempt stdout/stderr logs in ignored `.spacer-logs/` or a temporary fallback. Tail incrementally with `-progress`; preserve split UTF-8, partial lines and CR updates. Keep cancellation responsive between operations, report elapsed time after ten seconds of quiet, and include raw logs/warnings/crashes in diagnostics.

## Qt, progress and navigation

`refresh_motion_ui` owns contextual visibility and target summaries; call it after restoring state or assigning catalogue provenance. Use `setRowVisible` so labels follow controls. Prepared/current-image transitions must preserve stable Advanced geometry; solved-but-unprepared projects still allow first-preparation choices. See [AGENTS.md](../AGENTS.md#interface) for layout rules and the [historical audit](INTERFACE_AUDIT.md) for regression background.

Use `StageProgress` structured `(label, done, total, elapsed)` events, throttled to about four updates per second with exact completion. Negative totals mean unknown work; zero is a known empty stage. Count skipped/deferred entries after they return, but not failed/cancelled ones. Stage percentages/ETA are not overall-job progress. Remote TAP waits/downloads switch to activity mode; force counted updates when a region is saved even if it completed inside the throttle interval. Per-group IDs are diagnostics, never stage labels.

Details always contains full captured diagnostics, including while collapsed; ignore legacy verbose preferences. Preserve tracebacks in Details and concise stage/error messages. Keep status/counter heights reserved and hidden progress/cancel size policies. Finalization remains below 100% until FFmpeg and project recording succeed.

Standalone explicit launch inputs override remembered navigation. Missing/corrupt preferences or unwritable settings locations must not block processing. Pickers start at current locations or nearest existing parents. Remember partial/successful projects; keep preferences local and ignored. Failed/cancelled runs restore earlier export links and release controls only after workers stop.

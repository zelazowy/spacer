# Validation record

[Development](DEVELOPMENT.md) · [Scientific scope](SCIENCE.md) · [Historical interface audit](INTERFACE_AUDIT.md)

These are recorded local observations, not performance guarantees or proof of every catalogue distance and star extraction. Large images and generated artifacts are excluded from Git. Automated tests use synthetic/temporary fixtures; real-image work should use a separate validation folder and preserve the user's source/project.

## Native interactive preview — 0.19.0

The suite passed **141 tests**, including atlas downsampling with unchanged coordinates/provenance, non-destructive moving-star caps, both projection modes and camera-plane crossing, fractional movement, picking, settings isolation, active-revision selection, invalid target distances, scrubbing/playback and cancellation during window/main-window closing. No WebEngine/server dependency was added.

A real B150 field (4084×2717, 13,259 movers) loaded to a 1200×798 background plus packed atlas in about **1.12 s**. Five sampled native redraws averaged about **19.2 ms** on the local offscreen Qt runtime. First/middle/final target-mode frames and a camera-zoom frame were inspected. These measurements are not runtime guarantees; native platform styling and live Siril integration may differ. Original source, project and active-scene hashes stayed unchanged. Extraction/rendering algorithms and existing cache compatibility were not changed.

## Latest distance-coverage check — 0.17.0

The complete suite passed **133 tests**, covering selection/provenance, proper-motion epoch conversion, catalogue duplicates/ambiguity and caches, actual synthetic extraction, immutable revision retention, render coverage guards, moving-limit consistency and Qt state/layout. Preview JavaScript passed `node --check`.

M45, using the same cached image/starless/WCS inputs:

| Measurement | Result |
| --- | --- |
| Previous movers | 6,328 |
| Extended-coverage movers | 9,392 (+48.4%) |
| Strict Gaia geometric | 6,328 |
| Gaia photogeometric | 3,034 |
| Broader Gaia geometric | 30 |
| Hipparcos-2 moving sprites | 0 |
| Hipparcos references | 11 added, 34 matched, 1 ambiguous association |
| Accepted bright groups | 14, unchanged in count |
| Preparation/refinement including first downloads | About 198 s |

The mover total is a net comparison; it does not imply that every earlier sprite/group remained identical after recalculation. Broader catalogues improve faint-star motion here, but do not solve bright-bright overlap.

Inspected 30%-zoom first/middle/final frames at 80 pc travel and bright-star close-ups at 20 pc travel; many nearby bright movers leave the frame at 80 pc. Main/Advanced Qt views were inspected, with no unnecessary Advanced scrollbar on the offscreen test display. Native platform appearance can differ.

## ASTAP consistency checks

These compare against existing WCS solutions, not independent truth. Original source hashes remained unchanged.

| Release/check | Observation |
| --- | --- |
| Early M13 finished JPEG, downsampled, hinted | About 0.5 s solve; centre difference 0.8 arcsec, corners 38–44 arcsec; insufficient quads for SIP |
| 0.9.3 full-resolution M45/M33 JPEGs, approximate hints/auto FOV | Maximum centre/corner differences 7.71 / 3.04 arcsec against embedded TIFF solutions |
| NGC2403 JPEG, 4624×3063 | 2,000-star search plus original-pixel confirmation reduced earlier corner errors around 90 arcsec to <1.97 arcsec; centre 0.42 arcsec |
| M27 Siril JPEG with EXIF solution | Embedded solution agreed with matching FITS at centre/corners; reuse bypassed solving. Metadata-free recovery was not established. |
| 0.16.0 M33 Astro-TIFF, installed ASTAP/D20 | Header-guided search plus confirmation: centre 0.27485 arcsec, max corner 2.76792 arcsec |

M45 demonstrated that a 5,000-star refinement can produce unstable SIP; NGC2403's 10,000-star refinement was worse. Keep bounded confirmation strategies and rejection tests rather than assuming larger samples always improve accuracy.

## Wide-field coverage — 0.9.7 / 0.9.8

A 5292×3488 Polaris field near Dec 89.50° had a 3.92486° footprint radius, within the 5° guard. Its plan used four roughly 2.075° cones. Live GAVO at G<18 returned 86,412 unique references in 276.84 s; cache reload took 0.23 s. All 40,401 sampled SIP-footprint points lay in the planned cones.

Using cached layers/catalogue, core preparation produced 32,746 movers from 50,795 detected peaks in 156.35 s. This checks catalogue-to-image integration; it is not full Iterative/video timing or a general all-sky projection test. Original project metadata stayed unchanged.

## Density bounds and recalculation

Historical 0.10 checks explicitly used a **5,000-star limit**, before the default increased to 50,000. Do not apply their timings to the current default.

M8 had 442,587 references and 345–2,717 neighbours per bright group; Polaris had 86,412 references and 173–432. Bounded render views reconstructed identical first-frame bytes while preserving saved analysis. Three-frame 1920 px samples took 2.95 s for limited M8 versus 4.20 s for its original core field, and 4.33 s for limited Polaris versus 22.64 s original. These are short samples, not full-video guarantees. Oversized groups were deferred intact.

Fresh 5,000-candidate core runs accepted 3,945 M8 movers in 41.30 s and 3,860 Polaris movers in 29.66 s, excluding network/removal. Later 50,000-limit M8 recalculation accepted **10,491 movers from 12,215 candidates in 81.15 s** through Iterative refinement. Source/project/cached-input hashes stayed unchanged; first/middle/final frames and bright-star crops were inspected.

## Interface coverage

The [interface audit](INTERFACE_AUDIT.md) records 0.11.x layout/recovery findings and the 0.15.0 simplification. Offscreen checks covered new/unsolved/solved/partial/prepared/busy/failed states, stable Advanced geometry, expanding paths, progress/diagnostics, cancellation and export-link recovery. Screenshots used an 800×800 available screen; they do not establish native file-dialog or display-scaling parity.

Real star-removal engine checks processed an image crop through both installed engines. A test or desktop check does not establish every live Siril integration state; exercise that boundary when changing it.

## Shared solver extraction (0.18.0, 2026-10-24)

The complete 133-test SPACER suite passed after moving ASTAP implementation to
`astro-platesolve`. Solver tests still cover original preservation, project reuse,
cancellation/timeout, logs/UTF-8/heartbeats, source metadata, recovery ordering and
original-pixel refinement/rejection. No extraction/rendering behavior was changed.
Shared-library API/Skyshot schema tests and Siril/alignment adapter tests were run
separately. M39 was processed through shared ASTAP and native registration with the
same crop/residual measurements as before extraction. Skyshot lacks an installed
runtime/index here: adapter simulation is not an accuracy or speed benchmark.

## 1.0.0 workspace release — 2026-10-29

- Full suite: **149 tests passed**. Added separate layer/calculation-stage checks, output-quality forwarding/provenance, light-year entry and locale conversion, shared-canvas geometry, stale preview cancellation and tool-preference coverage. Existing scientific/cache/solver tests pass.
- Reopened the real B150 saved revision with **13,259 moving stars**. Inspected Qt captures for Prepare, Calculate, Preview, Export, image-free Tool setup, expanded motion controls and first/middle/last preview positions. Image bounds were identical across all image steps and expanded controls at a fixed window size. Capture artifacts remain outside the repository.
- Encoded an actual B150 **4.000 s**, **30 fps**, **1920×1278** MP4 with **120 frames** in an isolated validation folder. Inspected decoded first/middle/final frames. Original saved photo, project and active scene SHA256 hashes were unchanged; no catalogue/extraction/engine work was needed for export. This validates the new export options on a real field, not improved separation accuracy.
- Desktop screenshots/tests used Qt's offscreen platform. A Cocoa launch was attempted, but native visual inspection through Computer Use was unavailable because permissions were not granted. Native macOS appearance/file-dialog parity and a live Siril connection were not verified in this release check. Existing standalone/Siril boundary tests and synthetic external-engine workflow checks pass; no proprietary engine/model/license was reactivated or bundled.
- Scientific algorithms, cache markers and stored parsec units are unchanged. Existing bright-star separation limits still apply.

## 1.0.2 numeric responsiveness — 2026-10-29

- **151 tests passed**, including actual key entry of grouped million-light-year values, decimal-comma conversion, and absence of project refresh/redraw per typed digit.
- Loaded the real B150 13,259-star scene in offscreen Qt: seven typed digits took about 1.5 ms in the synthetic QTest event run, with zero value-change events during typing and one committed event on Enter. This is an event-path regression check, not a native OS input-latency guarantee.
- Committed changes schedule one coalesced preview sync after 120 ms; source data, projection and render settings remain unchanged.

# Validation record

[Development](DEVELOPMENT.md) · [Scientific scope](SCIENCE.md) · [Historical interface audit](INTERFACE_AUDIT.md)

These are recorded local observations, not performance guarantees or proof of every catalogue distance and star extraction. Large images and generated artifacts are excluded from Git. Automated tests use synthetic/temporary fixtures; real-image work should use a separate validation folder and preserve the user's source/project.

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

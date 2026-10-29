# Working on SPACER

These instructions apply throughout this repository. User instructions take precedence.

## Start here

Read [README.md](README.md) for the product and [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for current architecture and implementation context. Inspect `git status` before editing. Consult [CHANGELOG.md](CHANGELOG.md) for release history and [docs/VALIDATION.md](docs/VALIDATION.md) for existing evidence. Do not treat historical benchmarks as current guarantees.

## Product and scientific rules

- Prioritize accurate separation and smooth movement over analysis/rendering speed. Never inflate motion counts by assigning one star's depth to unrelated neighbours.
- Keep Iterative as the only exposed desktop scene style. Conservative core extraction remains internal; preserve historical Natural/Dynamic assets.
- Preserve floating-point subpixel placement and original-resolution background sampling for deep zoom.
- Keep distance confidence and visual appeal distinct. Preserve source IDs, uncertainty bounds, approximate flags and catalogue provenance. Do not infer distance from photographed brightness.
- Defer ambiguous matches, unresolved companions and unstable fits. Do not relax overlap/convergence screens merely to animate more stars.
- Follow the current numerical and catalogue contracts in [development context](docs/DEVELOPMENT.md) when touching extraction, motion, solving or queries.

## Images, projects and compatibility

- Never modify an original source image. Process snapshots; standalone solving must not use ASTAP `-update` on the original.
- Reuse saved image/starless layers, WCS, suitable catalogue caches and prepared scenes across restarts and image switches. Do not rerun star removal or network queries unnecessarily.
- Apply new extraction or distance-coverage choices through explicit **Recalculate stars**. Rendering an existing field must not silently replace it with new analysis.
- Publish recalculations as separate revisions and switch the active revision only after success. Failure/cancellation preserves the previous calculation and exports. Validate calculation paths within the project.
- Never overwrite exports. Names include tool version and parameters; add numeric suffixes for collisions. Keep field-preparation provenance separate from rendering provenance; historical unlabelled fields remain unversioned.
- Preserve public option units: UI zoom is a scale; project/pipeline `zoom` is percent increase. UI distance text is light-years; DistanceSpinBox values and project/pipeline/catalogue `*_pc` quantities remain parsecs. Change schemas/compatibility markers only when required and documented.
- Keep standalone imports independent of `sirilpy`. Share the processing pipeline between launchers; image-source handling belongs at their boundary.
- Do not commit images, videos, generated projects, private paths, local preferences, engine binaries/models or proprietary licenses.

## Interface

- Use the approved dark-only resizable workspace: Prepare image → Calculate stars → Preview flight → Export, with completed steps revisitable. Keep one state-specific primary action; advanced controls are contextual disclosures and diagnostics live in Details. Tool setup is a dedicated image-free view.
- Keep preparation and recalculation sections visible in stable positions across new, partial and prepared projects; disable inapplicable controls. The exception is solver controls, which appear only for unsolved standalone inputs.
- Preserve native Qt widgets, keyboard access, expanding path fields and screen-bounded layouts with a scroll fallback; the approved app theme is dark only. Keep one stable canvas/playback area across image-related steps, independent of right-panel content. File pickers start at current/remembered locations.
- Reserve status/progress/action geometry. Wrapped messages, Details and worker updates must not move the main buttons unexpectedly.
- Use structured progress callbacks, never parsed log text. Unknown work uses activity progress; do not show stale ETA. Report 100% only after export finalization succeeds.
- Keep complete diagnostics even while Details is closed; terminal/status messages stay concise. Lock settings/project switching while processing and retain cancellation/error recovery.
- Reset image-specific target distances and preparation defaults when switching to an unrelated image; restore saved project settings when reopening one.

## Validation and releases

- Run checks appropriate to the change. The full suite is `python -m unittest discover -s gaia_flythrough -p 'test_*.py'` in an environment with `requirements.txt` installed.
- For extraction/rendering changes, also inspect real first/middle/final frames and close-ups around moved bright stars. Unit tests previously missed visible spike artifacts. Use separate validation folders and verify source preservation.
- For UI changes, check new, partial, prepared, busy and failed states, including stable preview geometry and independently scrolling advanced controls. Offscreen Qt screenshots do not establish native-platform parity.
- Commit each completed change with its version in the commit message. Update `gaia_flythrough/version.py` and root `CHANGELOG.md`: major for incompatible workflows, minor for capabilities or deliberate extraction/rendering changes, patch for fixes, presentation or documentation cleanup. Extraction schemas and cache revisions are separate markers.
- Keep README focused on current setup/use. Put detailed usage in `docs/USER_GUIDE.md`, scientific contracts in `docs/SCIENCE.md`, engineering context in `docs/DEVELOPMENT.md`, evidence in `docs/VALIDATION.md`, and chronological changes only in `CHANGELOG.md`.

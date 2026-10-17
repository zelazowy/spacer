# SPACER interface audit — 2026-10-17

Reviewed after adding saved-project recalculation in 0.11.0 and fixing Advanced sizing/path pickers in 0.11.1. Follow-up fixes ship in 0.11.2.

## Scope and checks

Qt screenshots were inspected for empty, unsolved JPEG, solved FITS, saved M8, changed star limit, expanded Details, counted/unknown progress, busy recalculation and cancellation. Checked compact and wide Advanced layouts, keyboard focus on the recalculation action, screen bounds, reserved status/action geometry and transitions between new and saved inputs. Automated coverage also exercises solved/unsolved TIFF/JPEG, missing tools/date, failure recovery, legacy projects and active calculation revisions.

| Area | Finding and result |
| --- | --- |
| Recalculation | Advanced now offers Recalculate stars beside the limit, explains cache reuse and lists missing inputs. A higher limit prompts recalculation. Completion returns to Render flight; no video starts automatically. |
| Recovery and history | New calculation revisions become active only after success. Cancellation/failure retains previous analysis and exports. Missing active revisions block stale rendering and leave recalculation available. |
| Advanced layout | Replaced the 440 px fixed starting height with content/screen sizing. Inspected settings had no unnecessary scrollbar; smaller screens retain a fallback. Removed disabled first-preparation controls from prepared-project settings, leaving the relevant controls visible. |
| Path selection | Project Browse starts at the current directory, or the nearest existing parent of a new path. Executable/database pickers follow the same rule. Native file-dialog starting arguments are tested. |
| Empty output folders | Found that Browse could select an empty folder that preparation/solving then rejected. New projects now accept empty folders; nonempty unrelated folders remain protected. |
| New-image defaults | Found a saved project's 5,000 limit carrying into unrelated new images. New images and new Siril projects now reset to 50,000; reopening a project still restores its saved choice. |
| Existing exports | Found preview/video links staying disabled after a cancelled run. They now recover from the project's last successful export. |
| Screen bounds | Expanded Details and unsolved-image controls could force the main window beyond a short screen. Window height is now bounded with a scroll fallback. Header spacing and progress/action geometry remain fixed during status updates. |
| Progress and diagnostics | Counted stages retain counters/ETA; remote waits remain indeterminate. Details includes diagnostics captured while closed. Cancel returns controls, and completion waits for successful finalization. |

## Evidence and limits

93 tests pass. Screenshots were inspected using Qt's offscreen macOS plugin with an 800×800 available screen; native Finder presentation and other display scaling can differ. Current-path picker arguments are verified rather than claiming a manual Finder interaction. Wide settings continue to expand path inputs.

An isolated real M8 project reused the supplied image/starless/WCS/catalogue with a 50,000 candidate limit: 12,215 eligible candidates, 10,491 moving stars, 81.15 seconds through Iterative refinement. Source scene, project and cached-input hashes were unchanged. This is a local cached-layer measurement, not a network or full-video runtime guarantee. First/middle/final M8 samples and bright-star crops were also inspected. Validation files remain under `/private/tmp/spacer-interface-audit` and `/private/tmp/spacer-recalculation-m8`; they are not installed into the user's project.

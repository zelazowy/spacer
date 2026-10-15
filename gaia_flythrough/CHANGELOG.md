# Gaia Flythrough releases

## 0.3.0 — 2026-10-15

First explicit release baseline after the M45 iterative experiments.

- Natural, Dynamic and experimental Iterative modes; reusable prepared fields.
- Iterative separation measures coloured diffraction-spike details while excluding catalogue neighbour cores.
- Tool version appears in the Siril window, preview heading, output filenames, JSON metadata and MP4 comment.
- Field preparation version and time are recorded separately from render version and time. Older fields are explicitly unversioned.
- Existing exports remain unchanged; filename collisions receive numbered suffixes.

Use major.minor.patch: major for incompatible workflows, minor for features or deliberate extraction/rendering behaviour changes, patch for corrective fixes. Update the shared VERSION in version.py and add a release entry whenever shipping changes. Internal extraction schemas and iterative cache revisions are separate compatibility markers.

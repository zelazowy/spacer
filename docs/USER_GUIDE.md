# User guide

[Back to README](../README.md) · [Scientific scope](SCIENCE.md) · [Release history](../CHANGELOG.md)

## Input images

Standalone SPACER opens FITS, TIFF, PNG and JPEG. Supply finished, already-stretched pixels; standalone input does not use Siril's autostretch. Floating-point pixels must be normalized to [0,1]; integer images use their datatype range. Monochrome and RGB are supported.

FITS and Astro-TIFF can carry their own plate solution. Siril JPEGs may also contain FITS-style coordinates in EXIF ImageDescription. JPEG solution reuse requires matching stored dimensions and normal EXIF orientation; resized or rotated exports need a new solution. Unsolved JPEGs are EXIF-transposed before solving and preparation. TIFF orientations 1–4 are supported; export orientations 5–8 with top-left orientation first. Some compressed TIFFs require an optional codec; uncompressed TIFF is an alternative.

**Choose solved FITS…** under Advanced can attach a reference to a raster image. It must have the same dimensions **and framing**. Matching dimensions alone do not prove alignment. Never attach an uncropped solution to a cropped, rotated or differently registered image.

New preparation supports a centre-to-edge radius up to **5°**, about a **10° diagonal**. Larger fields receive an approximate central-crop suggestion before star removal/downloads. Crop manually, plate-solve the result and start a new project; SPACER does not crop the original automatically.

## Plate solving

The standalone app offers **Solve sky position** only when a usable solution is missing. Install ASTAP and its star database, then check **Advanced → Plate solving (ASTAP)**. Browse accepts an executable or macOS `.app`; the database folder is optional when ASTAP already knows its installation.

An optional object name, such as `M45` or `NGC 2403`, or numeric RA/Dec can help locate the field. Object-name lookup needs internet. Blind solving and numeric hints work offline. Auto field height searches roughly 0.3–10°; provide a field height under Advanced when needed. A target limits initial searches to a nearby region, with a broader fallback.

The solver confirms candidate solutions on the original photographic pixels and saves only to a working snapshot. Success creates a resumable solved project; choose **Resume and render** next. A failed solve leaves the source unchanged. One ten-minute timeout covers all attempts; cancellation waits for the current operation to stop.

The Siril launcher requires an already-solved current image. It suggests Siril's solver or `Siril_ASTAP_PlateSolve.py` if coordinates are missing.

## First preparation

In **Advanced settings**, check these groups:

| Group | Settings |
| --- | --- |
| Motion details | Travel distance; optional manual target distance and source |
| First preparation only | Pixel stretch, removal engine/executable, observation date |
| Star calculations | Moving-star maximum, approximate distance coverage, recalculation |
| Output and tools | FFmpeg executable and project folder |

In Siril, choose **Current pixels** for an already-stretched image or **Linked autostretch** for linear pixels. A display stretch alone is not part of an ordinary snapshot. Unsaved Siril pixel edits are included.

StarXTerminator needs its installed CLI, model and active license. StarNet 2.5+ needs its executable and companion model. SPACER does not install engines, activate licenses or download their models. Changing an engine or its path after preparation does not change saved starless pixels; use a new project to prepare with a different removal engine or changed source pixels.

**Prepare and render** saves the working image/WCS, removes stars, downloads catalogue references, matches stars, fits their light, refines bright groups, and exports the flight. Large or dense images can take time. Additional renders reuse the completed calculations.

### Observation date

The date corrects catalogue positions for stellar proper motion before pixel matching. Use the photo's capture date; an export date can be a poor substitute. A successful render does not verify the date or every match.

SPACER prefers capture metadata, including a matching WCS reference when available. Missing capture time falls back to labelled file-metadata or filesystem estimates. Review **Estimated** dates under Advanced. Manual `YYYY` uses July 1 and `YYYY-MM` uses the 15th, both marked approximate; full dates are accepted too. File change time (`ctime`) is not used as capture time.

The date and its source are saved with the project and preparation. Rendering an existing field does not rematch it at a new date.

## Motion

| Style | Behavior |
| --- | --- |
| **Camera zoom** | Set Final zoom, from **1× to 101×**. Background enlargement is combined with each moving star's catalogue-based parallax. |
| **Travel toward a target** | Choose a target distance; background enlargement follows travel toward that plane. Stellar perspective uses each star's own distance. |

Defaults are **60 s**, **1.3×**, **24 fps**, **80 pc travel** and **1.5 s easing** at each end. Adjust travel in **Advanced → Motion details**. Target distance must exceed travel: a 400 pc target and 80 pc flight give 1.25× background enlargement. Independent Final zoom is hidden in target-distance mode. Nearby stars may leave the frame as travel increases.

**Choose target…** uses an optional online SIMBAD lookup for a shortlist of familiar nebulae, clusters and galaxies within the solved footprint. It prefers Messier, IC and NGC names, followed by common nebula/cluster catalogues. Each object appears once, using an approximate median of published distances rounded to two significant figures. Original measurements and references remain in provenance. This summary is an animation input, not a combined scientific measurement.

The list is limited to 100 main candidates and a 6° lookup radius; it is not an exhaustive object detector. Unsupported/unlisted objects or missing distances can use manual entry under Motion details. Selection does not move the camera's optical axis onto the chosen object. Switching images clears the previous target; reopening a project restores its saved selection.

## More moving stars

Enable **Advanced → Star calculations → Include approximate distances** before preparation, or enable it in an existing project and click **Recalculate stars**. It is off by default. Good Gaia geometric distances remain preferred; extra sources include screened Hipparcos-2, Gaia photogeometric and broader geometric estimates. Their provenance and approximate flags remain visible. See [distance selection](SCIENCE.md#stellar-distances) for exact criteria.

First use downloads supplementary references. Later recalculations reuse the caches. Changing the checkbox alone cannot change an existing prepared scene: recalculate first, then render.

**Moving stars (maximum)** defaults to **50,000**; the desktop range is 100–50,000. Lower values reduce fitting/rendering work; unselected stars stay in the photograph. Increasing the limit beyond the prepared set needs recalculation. The complete catalogue remains the ambiguity reference, so this limit does not reduce the initial download.

A catalogue row count is not a moving-star count. Stars can remain stationary because of missing/uncertain distances, ambiguous associations, unresolved companions, saturated cores, overlapping halos/spikes or unstable fits. Extraction currently attempts up to 16 bright-group fits with up to 96 catalogue neighbours per group; larger groups are deferred intact.

## Reuse and recalculate projects

The default project is `flythrough/<image-name>/` beside the source. Choose another empty folder for a new project or **Open project…** to revisit saved work from either launcher. Existing projects always use their saved image, even if a different image is open in Siril. Unrelated nonempty folders are rejected.

After preparation, change duration/motion/zoom and choose **Render flight**. No star removal or catalogue request is needed. Exports include the running version and parameters; repeated settings get `_02`, `_03`, etc. rather than overwriting.

**Recalculate stars** reruns matching and separation from saved `photo.png`, `starless.png`, `source_wcs.fits` and catalogue caches. It does not repeat plate solving or star removal. Extra catalogue downloads are needed only if the requested coverage is not already cached. Successful calculations become a new `calculations/v<version>_<revision>/` directory; the active revision switches only after success. Failure/cancellation preserves previous analysis and exports. Recalculation finishes ready to render, without automatically starting a video.

Old prepared fields retain their original extraction. Rendering alone does not apply a newer separation algorithm. Missing cached inputs are listed beside the disabled recalculation action. Missing or invalid active revisions block stale rendering; rebuild from saved layers when available.

Standalone startup remembers the last successful image/project, unless explicit launch arguments choose another. Pickers remember locations; missing inputs or corrupt preferences do not block startup. Preferences live in ignored `.spacer-settings.json` beside the app. Delete it to reset locations. A read-only preferences location does not prevent processing.

## Outputs

| File or folder | Purpose |
| --- | --- |
| `project.json` | Preparation stage, active calculation revision, saved settings and latest export |
| `source_wcs.fits` | Working pixels and solved header |
| `photo.jpg`, `starless.jpg` | Convenient matching JPEG layers |
| `photo.png`, `starless.png` | Lossless layers used internally |
| `catalog.csv`, `catalog-parts/` | Original Gaia reference and resumable download parts |
| `catalog-extended.csv`, `catalog-hipparcos2.csv`, `catalog-motion.csv` | Optional supplementary/merged references |
| `scene.json`, `scene_iterative.json` | Core and refined prepared scenes, at the root or in the active calculation revision |
| `matched_stars.csv`, `rejected_blends.csv`, `iterative_report.json` | Matching and separation diagnostics |
| `distance_coverage.json` | Moving-star counts by distance source |
| `calculations/` | Preserved recalculation revisions and their diagnostics |
| `flythrough_v<version>_iterative_….html/.mp4/.json` | Interactive preview, video and render settings/provenance |
| `star-removal.log`, working FITS/TIFF files | External-engine diagnostics and working layers |

Videos are H.264, up to 1920 px wide. HTML previews retain the full-resolution scene and need no local server. **Open video** opens the latest completed MP4. **Open preview** opens the native preview described below. Use **Open exported HTML** inside that window to view the latest completed full-resolution HTML export, including its saved parameters and pixel-patch inspection.

## Lightweight preview window

After preparing or recalculating stars, click **Open preview**. It opens a separate native window in both Siril and standalone SPACER, without rendering a video, querying catalogues or running star removal. The preview uses the active saved calculation and the main window's current settings, which can differ from the last exported flight.

The background and star textures are downsampled to at most 1200 px for quick loading; star positions, distances and perspective remain based on the saved scene. Textures share one atlas, and preparation runs in a cancellable background worker. No browser, local web server or extra WebEngine package is needed. Video/HTML exports retain their existing resolution and behavior.

Use **Play/Pause** or the timeline to inspect movement. Switch **Motion**, adjust **Final zoom**, **Travel**, **Target distance** and **Duration**, or enable **Show extracted star boundaries**. Clicking a mover shows its catalogue ID and distance provenance. These preview changes do not edit saved scenes or project settings. **Use these settings** copies the values into the main controls; **Render flight** then creates a new export as usual. Applying settings is blocked if the main window has switched projects or is processing.

Target-distance mode needs a target distance greater than travel; it does not invent a missing distance. The star maximum follows the main window's current limit. Legacy projects with only an exported HTML preview can still open that file directly. Closing while loading cancels preparation safely, and closing playback stops its timer.

## Progress and troubleshooting

Progress percentages apply to the current stage, not the entire job. Remote catalogue waits and other unknown work use an activity indicator. Dense regions can increase the planned request count. Video progress includes frame counts, elapsed time and an estimated remaining time; **Finalizing MP4…** completes before 100% is shown.

**Details** contains full diagnostics even when it was collapsed. ASTAP retains per-attempt logs in `.spacer-logs/` beside the app, or a temporary fallback; the reported path identifies them. Solver logs include attempts and warnings. Keep these logs when investigating failed solutions.

Cancellation retains completed catalogue regions, reusable preparation and earlier exports. An outstanding HTTP request must return or time out first. Wait for the worker to stop before closing the window. Reopen an interrupted project and choose **Resume and render**.

- **No usable solution:** solve the displayed image, or supply a solved FITS reference with exactly matching framing.
- **Too few movers:** inspect distance coverage and extraction deferrals; raising the maximum cannot repair ambiguous light separation.
- **Field too wide:** crop manually, plate-solve the crop and create a new project.
- **Poor JPEG solve:** use a solved TIFF/FITS or an embedded solution when available; processing/compression can hinder solving.
- **Old settings after image switching:** existing projects deliberately retain saved pixels/settings; start a new project for a different source or removal engine.

## Command-line entry points

The desktop launcher can preselect an image or project:

```sh
python SPACER.py /path/to/solved.fits
python SPACER.py /path/to/finished.jpg
python SPACER.py /path/to/finished.tif --wcs /path/to/matching_solved.fits
python SPACER.py --project /path/to/flythrough/M45
python SPACER.py --version
```

The separate prototype CLI uses already-created photo/starless layers and a same-framing WCS. It does not run the unified desktop preparation workflow. Use a new output directory:

```sh
python gaia_flythrough/flythrough.py \
  --photo /path/to/photo.png \
  --starless /path/to/starless.png \
  --wcs /path/to/source_wcs.fits \
  --output /path/to/new-flight \
  --seconds 60 --fps 24 --zoom 1.3 --travel 80 --ease-seconds 1.5 \
  --approximate-distances --mp4
```

Its zoom argument is a scale and its current range is 1–1.5, unlike the desktop's wider zoom range. Omit `--approximate-distances` for strict coverage. Supply `--epoch` if the WCS has no observation date. Run `--help` for all prototype options. A unified headless CLI is planned.

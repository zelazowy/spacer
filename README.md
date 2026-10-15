# SPACER

**Stellar Parallax Animation through Catalogue-based Extraction and Reprojection**

*A walk through your astrophotography.*

Current version: **0.9.6**. Run SPACER as a standalone desktop app or from Siril.

## Standalone desktop app

Siril is optional. Install Python 3.10+ and the dependencies in an isolated environment:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python SPACER.py
```

On Windows, activate with `.venv\Scripts\activate` instead. FFmpeg and a supported star-removal engine must be installed separately. SPACER discovers them automatically; change their paths in Advanced settings.

Click **Open image…** to select a finished FITS, TIFF, PNG or JPEG. Existing FITS, Astro-TIFF and Siril JPEG EXIF plate solutions are read automatically, including SIP distortion terms and observation date when present. JPEG reuse requires matching stored image dimensions and normal EXIF orientation; resized or EXIF-rotated copies need a fresh solve. A JPEG can carry a solution even when its extension gives no indication of it. Astro-TIFF uses the FITS-style metadata described in the [format specification](https://siril.readthedocs.io/en/stable/file-formats/Astro-TIFF.html).

If the image has no solution, click **Solve sky position**. SPACER uses your installed ASTAP and its star database. In **Advanced settings → Plate solving (ASTAP)**, choose the executable (or macOS `.app`) and optional database folder. Defaults are blind search, automatic field height and automatic downsampling. Solving and object-name controls appear only when the loaded image has no usable solution. The optional **Object name** field beside **Solve sky position** accepts names such as `NGC 2403` or `M45`, or RA/Dec (`16 41 38 +36 27 16`). A target starts a nearby search (up to 5°), with the configured broader radius retained for the final fallback. If needed, set the image height on the sky in degrees under Advanced settings. Object-name lookup needs internet; numeric coordinates and blind solving work offline. ASTAP’s automatic field-height search covers roughly 0.3–10°; supply a height outside that range. The current step appears above progress. Details and the launching terminal show concise step messages by default; enable **Verbose** beside Details for live ASTAP output, dimensions, settings and commands. Verbose can be changed during processing and reveals retained session diagnostics in Details. Its preference is remembered. If ASTAP is quiet, an elapsed-time message appears about every ten seconds. Every attempt retains a full log in `.spacer-logs/` beside the app (or a temporary-file fallback if that folder is not writable); the console reports its path. Logs survive failures, timeouts and cancellation. A blind search can take several minutes; solving times out after ten minutes and can be cancelled. See [ASTAP’s command-line documentation](https://www.hnsky.org/astap.htm#astap_command_line).

A successful solve creates the project with the original colour pixels and its new WCS in `source_wcs.fits`, plus solver settings/provenance in `project.json` and `astap.log`. Original image files are never updated. Click **Resume and render** to prepare the star layers and render. The matching date is filled automatically from capture metadata or a labelled file-date estimate. Review or override it in Advanced settings when needed. Star-removal settings remain editable until preparation starts. Reopen this project to reuse its solution without ASTAP or the original source file.

**Choose solved FITS…** remains an alternative under Advanced settings. The reference must have exactly the same dimensions and framing. Matching dimensions alone cannot verify registration: do not use a cropped, rotated or differently registered reference. The output folder is selected automatically beside the image and can be changed in Advanced settings.

File pixels must already be stretched and normalized (floating pixels in [0,1]; integer images use their datatype range). Standalone SPACER does not replace Siril's autostretch. Standard FITS row orders and TIFF Orientation 1–4 are supported; TIFF Orientation 5–8 requires an export with top-left orientation. JPEG EXIF rotation is applied before both solving and preparation. Monochrome and RGB images are supported. Some compressed TIFFs need an optional codec; export uncompressed TIFF if prompted. JPEG compression and heavy processing can prevent a reliable solve; TIFF/FITS are preferable when available. The revised solver uses an expanded star sample, retries a compact-peak proxy when needed, and confirms candidates on the original photographic pixels. It rejects inconsistent refinements and inexact final scales. Local ASTAP/D20 checks solved the supplied NGC2403 JPEG and full-resolution M45/M33 JPEG exports with approximate targets and automatic field height; comparison against existing solutions differed by less than 8 arcseconds at the centre/corners. This is a limited sample, not a guarantee for every processed image.

**Open project…** reopens saved projects from either launcher without opening the source image or Siril. Launching standalone SPACER without arguments reopens the last successfully selected image or project; explicit image/`--project` arguments take priority. Image, project and WCS-reference pickers remember their last successful folders. If the last input is missing, the app opens normally so you can choose another.

Navigation preferences are stored locally in `.spacer-settings.json` beside `SPACER.py` (ignored by Git). Delete it to reset remembered locations. If that location is not writable, opening/rendering still works but navigation may not persist.

You can select input when launching:

```sh
python SPACER.py /path/to/solved.fits
python SPACER.py /path/to/finished.jpg
python SPACER.py /path/to/finished.tif --wcs /path/to/matching_solved.fits
python SPACER.py --project /path/to/flythrough/M45
python SPACER.py --version
```

This is a Python desktop application, not a bundled installer. The original prototype CLI remains separate.

## Siril integration

Launch `Siril_Gaia_Flythrough.py` from Siril with a single plate-solved FITS or TIFF image open. If the image is not solved, the script stops before creating outputs and recommends `Siril_ASTAP_PlateSolve.py` or Siril’s plate solver. Download or clone this repository, then add its folder to Siril’s Python script search paths. Refresh the script listing or restart Siril. Alternatively, enter this in Siril's console:

```text
pyscript "/path/to/spacer/Siril_Gaia_Flythrough.py"
```

Keep the launcher beside the `gaia_flythrough` folder. Keep the entire `gaia_flythrough` folder, including the shared `app.py` and `image_source.py`; previous render folders are not needed to run the script.

## Workflow

1. Open your finished, plate-solved image. Unsaved edits are included because the script snapshots the current pixels and header rather than reopening the disk file.
2. Set duration and **Final zoom**. Defaults are **60 seconds and 1.3×**; zoom supports **1×–101×**. Rendering stays at **24 fps**, with **80 pc** of travel and **1.5-second** easing at each end. Deep zoom samples the background at its original resolution.
3. In **Advanced settings…**, keep **Current pixels** if the image has already been stretched. For linear pixels, select **Linked autostretch**; it uses Siril's linked 8-bit autostretch preview for the working copy. A display stretch in Siril alone is not applied to an ordinary pixel snapshot.
4. Advanced settings automatically selects an available **StarXTerminator** or **StarNet 2.5+**; change it if needed. The script discovers installed CLI tools; Browse can select a portable executable. StarXTerminator requires its installed model and active license; StarNet requires its companion model. The script does not activate licenses or download engines/models.
5. Click **Prepare and render**. By default, preparation and renders share `flythrough/<image-name>/` beside the source. Browse selects a project folder. Review the automatically detected or estimated matching date if needed. Gaia coordinates are propagated to that date before matching.

The current Siril image is left unchanged. Existing plate solutions are reused; the Siril launcher expects an already-solved image. Standalone input can use the optional ASTAP step. For a TIFF without DATE-OBS, enter the observation date before starting.

## Why the observation date matters

SPACER uses the date to correct Gaia catalogue positions for stellar proper motion before matching them to the photograph. It is the photo's capture date, not when the file was exported. Most stars move little over a short interval, so a different date can still produce a successful render; success does not verify the date or every star match. An unrelated date can shift fast-moving stars away from their photographed positions and cause missed or incorrect matches.

SPACER fills the date automatically, preferring FITS/Astro-TIFF `DATE-OBS`/`DATE-AVG` or numeric observation epochs, then EXIF capture/digitized dates and a matching WCS-reference observation date. If these are absent or invalid, it uses EXIF/TIFF/PNG or FITS file-date metadata, then filesystem creation time when available, otherwise modification time. Filesystem change time (`ctime`) is not treated as creation time. These fallbacks are estimates and may reflect copying, processing or export rather than capture.

Advanced settings shows the selected date and its source; fallback dates are marked **Estimated**. You may override with `YYYY`, `YYYY-MM` or a full date. Year-only input uses July 1; month-only input uses the 15th, both explicitly approximate. The selected date/source/approximation is saved with the project, snapshot (`DATEAPPX`/`DATESRC`), new prepared scene and render settings. Original images are unchanged. Historical prepared fields retain their original matching; changing duration/zoom or reopening the project does not redate them.

## Interface

The main window contains the current project, duration and **Final zoom**, expressed directly as a scale such as **1.3×** or **2×**. **Prepare and render** prepares a new image; **Resume and render** finishes partial preparation; **Render flight** reuses a completed project. **Open preview** and **Open video** become available when an export exists.

Use **Open project…** to return to saved work. In standalone mode, **Open image…** selects a disk image. In Siril, **New from Siril…** chooses a fresh project folder for the current image and opens its setup. The main project summary states whether SPACER uses current pixels or a saved image.

**Advanced settings…** opens a scrollable dialog with image stretch, removal engine and executable, observation date, FFmpeg and project location. Tools are discovered automatically; the date comes from the image. Missing setup opens this dialog. For a linear image, choose linked autostretch before preparation. Prepared projects disable preparation options because they reuse their saved image and tools. Newly solved projects keep these options editable until star removal starts.

Progress and cancellation stay in the main window. Video export shows a filling progress bar, completed/total frame counts, elapsed time and an approximate time remaining. After the last frame, **Finalizing MP4…** indicates that FFmpeg is still writing the file; 100% appears only after the export succeeds. Solving and preparation steps without a known total keep an activity indicator. **Details** reveals the processing log and opens automatically after a processing failure. **Verbose** adds technical diagnostics without replacing the current step. The title and subtitle keep a fixed height and gap; extra window space stays below the content. Status, progress and frame-counter space stay reserved so wrapping messages do not move the buttons. Plate-solving controls, including Advanced ASTAP settings, appear only for an unsolved standalone image. Rendering locks project/settings controls until the worker has stopped. Cancellation keeps preparation and earlier exports and returns a status message. Defaults remain 60 seconds, 1.3× final zoom, 24 fps, 80 pc travel and 1.5-second easing.

## Additional versions

After the first run, change duration and zoom, then click **Render flight**. The saved star layers, WCS and Gaia distances are reused: star removal and catalogue matching are not repeated. Every version is saved alongside the others, for example `flythrough_v0.9.6_iterative_60s_zoom30pct_24fps.mp4` or `flythrough_v0.9.6_iterative_20s_zoom50pct_24fps.mp4`, with a matching HTML preview and settings JSON. Repeating the same parameters adds `_02`, `_03`, etc. instead of overwriting.

Use **Open project…** to reuse a run folder after reopening the script. It accepts `scene.json` from this version, or imports the embedded field from an older `preview.html`. Additional versions always use that saved image, even if a different image is currently open in Siril.

## Outputs

- `photo.jpg`, `starless.jpg`: automatically prepared, matching JPEGs.
- `photo.png`, `starless.png`: lossless versions used for star extraction; avoids extra JPEG compression artifacts.
- `source_wcs.fits`: a snapshot of the working pixels with the plate-solve header.
- `flythrough_v<version>_iterative_<seconds>s_zoom<percent>pct_24fps.html`: self-contained preview. **Open preview** opens the most recently completed version, without a local web server.
- `flythrough_v<version>_iterative_<seconds>s_zoom<percent>pct_24fps.mp4`: H.264 at up to 1920 pixels wide. **Open video** opens the most recently completed version.
- `scene.json`: reusable prepared field, preserving the image layers and accepted star distances.
- `catalog.csv`, `matched_stars.csv`, per-version settings JSON and `star-removal.log`: data and diagnostics.
- Star-removal working FITS/TIFF files remain available for inspection.

Existing prepared run folders are reused for additional renders; individual videos are never overwritten. A folder without a prepared field is rejected rather than mixed with unrelated files. Cancelling retains partial outputs; cancellation during Gaia matching takes effect after the outstanding query returns. Wait for the worker to finish before closing the window.

Siril's Python environment needs numpy, scipy, astropy, Pillow, tifffile and PyQt6. The launcher uses `sirilpy.ensure_installed` to request missing Python dependencies. FFmpeg is an external executable and must already be installed. Both engines and all Python dependencies were found on this machine.

## Accuracy and validation

The animation uses the same photographed star sprites, Gaia DR3 positions, Bailer-Jones distances, distance screening, subpixel rendering and softened halos as the approved previews. Some stars remain in the flat background when they are unmatched, blended or have uncertain distances. The nebula is a flat photographic layer; its interior depth and radiometric travel effects are not reconstructed. See [the scientific scope in the development notes](DEVELOPMENT.md#scientific-scope) for the scientific scope and data credits.

Checked: automated tests covering matching, original-image reconstruction, fractional motion, easing, both engine export paths, row orientation, source preservation, prepared-field reuse, unique filenames and safe clipping at deep zoom; the Qt window was rendered and inspected; both installed star-removal engines successfully processed a real image crop. The full workflow still needs a run from your live Siril image. The interface also has offscreen Qt tests and visual checks; native platform rendering can differ.


## Blend safeguards and inspection

New preparations identify separate compact peaks and match them individually to Gaia. Moving sprites are smooth Gaussian core models fitted over a local background plane, with colour amplitudes fitted separately. They do not contain hard nearest-neighbour sectors of the observed halo. Very bright, broad or ambiguous cores remain in the flat background, including their diffraction spikes. This approximate photometric separation avoids transporting neighbouring stars and angular spike fragments, but changes the moving star profile and is not a full telescope-PSF reconstruction. The first-frame image is preserved by subtracting only available stellar light from the background; faint halos and complex spikes remain stationary.

`rejected_blends.csv` records rejected Gaia matches and the reason. In the HTML preview, enable **Show extracted star boundaries** and click a star to see its Gaia identifier, distance interval and actual extracted pixel patch.

Previously prepared fields keep their original extraction. **Render flight** does not repair those fields: choose a new project folder to prepare the image again with the new safeguards. Older fields can display patch boundaries, but may lack per-sprite Gaia identifiers.


## Projects and Iterative scenes

Iterative is the only scene style in the Siril workflow. It uses conservative core extraction internally and refines isolated bright-star groups with independently fitted neighbours, smooth halos and measured coloured diffraction spikes. This remains experimental: unresolved, overlapping or unstable groups are deferred. The extraction and animation algorithms are unchanged in 0.4.0 and 0.5.0.

The default project is `flythrough/<image-name>/` beside the source, with no timestamp. Reopening the script on that image automatically loads this project. **Open project…** opens any previous project or prepared run folder. Browse selects the exact project folder. To prepare changed pixels or try another removal engine, choose a new project folder; an existing project always uses its saved image.

`project.json` stores project schema, creation/update tool versions, source and removal settings, preparation stage, last render settings and latest completed export. Opening a project restores duration, zoom, FFmpeg and preview/video links. **Prepare and render** resumes partial preparation or renders a completed project. Changing duration or zoom only creates new HTML/settings/video exports; saved star removal, Gaia matching and Iterative separation are reused.

A preparation interrupted after validated star removal reuses that output. Matching reuses a saved `catalog.csv`; completed core and Iterative scenes are reused independently. A failed or cancelled render preserves preparation and earlier exports. Incomplete star-removal outputs are rerun. Older prepared folders can be opened directly when they contain a compatible core scene plus the saved layers/catalogue needed for Iterative, or a current `scene_iterative.json`. Incompatible old extraction requires a new project folder. Historical Natural/Dynamic files and all exports remain on disk.

## Versions

The current release is **0.9.6**. Both window titles show the running version. New export filenames include it, for example `flythrough_v0.9.6_iterative_60s_zoom30pct_24fps.mp4`. Previews and JSON sidecars show the rendering version, UTC creation time, and separate field preparation version; older unlabelled fields remain explicitly unversioned. MP4 files also carry the tool version in their comment metadata. Existing exports are preserved. Release history and version bump rules are in `gaia_flythrough/CHANGELOG.md`.

## Development

Install `requirements.txt` in a Python virtual environment. FFmpeg is required for MP4 export. Siril supplies `sirilpy` for the launcher; it is not needed for the core tests. Run:

```sh
python -m unittest discover -s gaia_flythrough -p "test_*.py"
```

See [DEVELOPMENT.md](DEVELOPMENT.md) for architecture, current limitations and a prompt for continuing development. Release history: [CHANGELOG](gaia_flythrough/CHANGELOG.md).

# SPACER

**Stellar Parallax Animation through Catalogue-based Extraction and Reprojection**

*A walk through your astrophotography.*

Current version: **0.5.0**. The Siril integration is available now; a standalone GUI and a unified CLI are planned.

Launch `Siril_Gaia_Flythrough.py` from Siril with a single plate-solved FITS or TIFF image open. If the image is not solved, the script stops before creating outputs and recommends `Siril_ASTAP_PlateSolve.py` or Siril’s plate solver. Download or clone this repository, then add its folder to Siril’s Python script search paths. Refresh the script listing or restart Siril. Alternatively, enter this in Siril's console:

```text
pyscript "/path/to/spacer/Siril_Gaia_Flythrough.py"
```

Keep the launcher beside the `gaia_flythrough` folder. The required helper files are `flythrough.py`, `siril_pipeline.py`, `iterative_deblend.py`, `version.py` and `viewer.html`; previous render folders are not needed to run the script.

## Workflow

1. Open your finished, plate-solved image. Unsaved edits are included because the script snapshots the current pixels and header rather than reopening the disk file.
2. Set duration and final zoom increase. Defaults are **60 seconds and 30%**; zoom now supports **0–10,000%** (100% = 2×; 900% = 10×). Rendering stays at **24 fps**, with **80 pc** of travel and **1.5-second** easing at each end. Deep zoom samples the background at its original resolution.
3. In **Advanced settings…**, keep **Current pixels** if the image has already been stretched. For linear pixels, select **Linked autostretch**; it uses Siril's linked 8-bit autostretch preview for the working copy. A display stretch in Siril alone is not applied to an ordinary pixel snapshot.
4. Advanced settings automatically selects an available **StarXTerminator** or **StarNet 2.5+**; change it if needed. The script discovers installed CLI tools; Browse can select a portable executable. StarXTerminator requires its installed model and active license; StarNet requires its companion model. The script does not activate licenses or download engines/models.
5. Click **Prepare and render**. By default, preparation and renders share `flythrough/<image-name>/` beside the source. Browse selects a project folder. If the image has no DATE-OBS, enter its observation date. Gaia coordinates are propagated to that date before matching.

The current Siril image is left unchanged. Existing plate solutions are reused; this tool does not run a plate solver. For a TIFF without DATE-OBS, enter the observation date before starting.

## Interface

The main window contains the current project, duration and final zoom increase. The zoom hint shows the resulting magnification. **Prepare and render** prepares a new image; **Resume and render** finishes partial preparation; **Render flight** reuses a completed project. **Open preview** and **Open video** become available when an export exists.

Use **Open project…** to return to saved work. **New from Siril…** chooses a fresh project folder for the current image and opens its setup. The main project summary states whether SPACER uses current pixels or a saved image.

**Advanced settings…** opens a scrollable dialog with image stretch, removal engine and executable, observation date, FFmpeg and project location. Tools are discovered automatically; the date comes from the image. Missing setup opens this dialog. For a linear image, choose linked autostretch before preparation. Saved projects disable preparation options because they reuse their saved image and tools.

Progress and cancellation stay in the main window. **Details** reveals the processing log and opens automatically after a processing failure. Rendering locks project/settings controls until the worker has stopped. Cancellation keeps preparation and earlier exports and returns a status message. Defaults remain 60 seconds, 30% final zoom increase, 24 fps, 80 pc travel and 1.5-second easing.

## Additional versions

After the first run, change duration and zoom, then click **Render flight**. The saved star layers, WCS and Gaia distances are reused: star removal and catalogue matching are not repeated. Every version is saved alongside the others, for example `flythrough_v0.5.0_iterative_60s_zoom30pct_24fps.mp4` or `flythrough_v0.5.0_iterative_20s_zoom50pct_24fps.mp4`, with a matching HTML preview and settings JSON. Repeating the same parameters adds `_02`, `_03`, etc. instead of overwriting.

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

The animation uses the same photographed star sprites, Gaia DR3 positions, Bailer-Jones distances, distance screening, subpixel rendering and softened halos as the approved previews. Some stars remain in the flat background when they are unmatched, blended or have uncertain distances. The nebula is a flat photographic layer; its interior depth and radiometric travel effects are not reconstructed. See [the renderer documentation](gaia_flythrough/README.md) for the scientific scope and data credits.

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

The current release is **0.5.0**. The Siril title shows the running version. New export filenames include it, for example `flythrough_v0.5.0_iterative_60s_zoom30pct_24fps.mp4`. Previews and JSON sidecars show the rendering version, UTC creation time, and separate field preparation version; older unlabelled fields remain explicitly unversioned. MP4 files also carry the tool version in their comment metadata. Existing exports are preserved. Release history and version bump rules are in `gaia_flythrough/CHANGELOG.md`.

## Development

Install `requirements.txt` in a Python virtual environment. FFmpeg is required for MP4 export. Siril supplies `sirilpy` for the launcher; it is not needed for the core tests. Run:

```sh
python -m unittest discover -s gaia_flythrough -p "test_*.py"
```

See [DEVELOPMENT.md](DEVELOPMENT.md) for architecture, current limitations and a prompt for continuing development. Release history: [CHANGELOG](gaia_flythrough/CHANGELOG.md).

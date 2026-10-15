# SPACER

**Stellar Parallax Animation through Catalogue-based Extraction and Reprojection**

*A walk through your astrophotography.*

Current version: **0.3.0**. The Siril integration is available now; a standalone GUI and a unified CLI are planned.

Launch `Siril_Gaia_Flythrough.py` from Siril with a single plate-solved FITS or TIFF image open. If the image is not solved, the script stops before creating outputs and recommends `Siril_ASTAP_PlateSolve.py` or Siril’s plate solver. Download or clone this repository, then add its folder to Siril’s Python script search paths. Refresh the script listing or restart Siril. Alternatively, enter this in Siril's console:

```text
pyscript "/path/to/spacer/Siril_Gaia_Flythrough.py"
```

Keep the launcher beside the `gaia_flythrough` folder. The required helper files are `flythrough.py`, `siril_pipeline.py`, `iterative_deblend.py`, `version.py` and `viewer.html`; previous render folders are not needed to run the script.

## Workflow

1. Open your finished, plate-solved image. Unsaved edits are included because the script snapshots the current pixels and header rather than reopening the disk file.
2. Set duration and final zoom increase. Defaults are **60 seconds and 30%**; zoom now supports **0–10,000%** (100% = 2×; 900% = 10×). Rendering stays at **24 fps**, with **80 pc** of travel and **1.5-second** easing at each end. Deep zoom samples the background at its original resolution.
3. Select **Current pixels** if the image has already been stretched. For linear pixels, select **Linked autostretch**; it uses Siril's linked 8-bit autostretch preview for the working copy. A display stretch in Siril alone is not applied to an ordinary pixel snapshot.
4. Choose **StarXTerminator** or **StarNet 2.5+**. The script discovers installed CLI tools; Browse can select a portable executable. StarXTerminator requires its installed model and active license; StarNet requires its companion model. The script does not activate licenses or download engines/models.
5. Click **Create flight**. By default, each run is saved beside the source image in `flythrough/<image-name>_<timestamp>/`. Browse can select another parent folder; a new run subfolder inside `flythrough` is created there. If the image has no DATE-OBS, enter its observation date. Gaia coordinates are propagated to that date before matching.

The current Siril image is left unchanged. Existing plate solutions are reused; this tool does not run a plate solver. For a TIFF without DATE-OBS, enter the observation date before starting.

## Additional versions

After the first run, change duration and zoom, then click **Render another version**. The saved star layers, WCS and Gaia distances are reused: star removal and catalogue matching are not repeated. Every version is saved alongside the others, for example `flythrough_60s_zoom30pct_24fps.mp4` or `flythrough_20s_zoom50pct_24fps.mp4`, with a matching HTML preview and settings JSON. Repeating the same parameters adds `_02`, `_03`, etc. instead of overwriting.

Use **Load prepared field…** to reuse a run folder after reopening the script. It accepts `scene.json` from this version, or imports the embedded field from an older `preview.html`. Additional versions always use that saved image, even if a different image is currently open in Siril.

## Outputs

- `photo.jpg`, `starless.jpg`: automatically prepared, matching JPEGs.
- `photo.png`, `starless.png`: lossless versions used for star extraction; avoids extra JPEG compression artifacts.
- `source_wcs.fits`: a snapshot of the working pixels with the plate-solve header.
- `flythrough_<seconds>s_zoom<percent>pct_24fps.html`: self-contained preview. **Open preview** opens the most recently completed version, without a local web server.
- `flythrough_<seconds>s_zoom<percent>pct_24fps.mp4`: H.264 at up to 1920 pixels wide. **Open video** opens the most recently completed version.
- `scene.json`: reusable prepared field, preserving the image layers and accepted star distances.
- `catalog.csv`, `matched_stars.csv`, per-version settings JSON and `star-removal.log`: data and diagnostics.
- Star-removal working FITS/TIFF files remain available for inspection.

Existing prepared run folders are reused for additional renders; individual videos are never overwritten. A folder without a prepared field is rejected rather than mixed with unrelated files. Cancelling retains partial outputs; cancellation during Gaia matching takes effect after the outstanding query returns. Wait for the worker to finish before closing the window.

Siril's Python environment needs numpy, scipy, astropy, Pillow, tifffile and PyQt6. The launcher uses `sirilpy.ensure_installed` to request missing Python dependencies. FFmpeg is an external executable and must already be installed. Both engines and all Python dependencies were found on this machine.

## Accuracy and validation

The animation uses the same photographed star sprites, Gaia DR3 positions, Bailer-Jones distances, distance screening, subpixel rendering and softened halos as the approved previews. Some stars remain in the flat background when they are unmatched, blended or have uncertain distances. The nebula is a flat photographic layer; its interior depth and radiometric travel effects are not reconstructed. See [the renderer documentation](gaia_flythrough/README.md) for the scientific scope and data credits.

Checked: eleven automated tests covering matching, original-image reconstruction, fractional motion, easing, both engine export paths, row orientation, source preservation, prepared-field reuse, unique filenames and safe clipping at deep zoom; the Qt window was rendered and inspected; both installed star-removal engines successfully processed a real image crop. The full new workflow still needs a first run from your live Siril image.


## Blend safeguards and inspection

New preparations identify separate compact peaks and match them individually to Gaia. Moving sprites are smooth Gaussian core models fitted over a local background plane, with colour amplitudes fitted separately. They do not contain hard nearest-neighbour sectors of the observed halo. Very bright, broad or ambiguous cores remain in the flat background, including their diffraction spikes. This approximate photometric separation avoids transporting neighbouring stars and angular spike fragments, but changes the moving star profile and is not a full telescope-PSF reconstruction. The first-frame image is preserved by subtracting only available stellar light from the background; faint halos and complex spikes remain stationary.

`rejected_blends.csv` records rejected Gaia matches and the reason. In the HTML preview, enable **Show extracted star boundaries** and click a star to see its Gaia identifier, distance interval and actual extracted pixel patch.

Previously prepared fields keep their original extraction. **Render another version** does not repair those fields: use **Create flight** to prepare the image again with the new safeguards. Older fields can display patch boundaries, but may lack per-sprite Gaia identifiers.


## Natural and Dynamic styles

The **Scene style** selector chooses:

- **Natural** (default): fits separate compact star cores. Complex bright stars and spikes stay in the background. This reduces false shared motion but is still an approximate model, not proof of cluster membership.
- **Dynamic**: moves original connected photographic patches, including halos and spikes, using the matched star's Gaia-based distance. More visually lively, but neighbouring stars in a blended patch can share the wrong depth. It does not use the angular deblending that caused broken spike fragments.

A new preparation saves both `scene.json` (Natural) and `scene_dynamic.json` (Dynamic), plus separate per-mode match reports. **Render another version** uses the selected style without repeating star removal or Gaia lookup. Filenames include `natural` or `dynamic`. Older prepared folders require a new **Create flight** run to gain both styles.


## Return to an existing image/run

Use **Load prepared field…**, **Browse…**, or paste an existing run folder into **Run folder (new or prepared)**. Click **Create flight** or **Render another version** to render the selected style, duration and zoom in that same folder. The saved image and Gaia field are used even if a different image is open in Siril; preparation tools and the current image are not accessed. The log identifies the reused folder. This works across script restarts. New variants keep their parameter-based filenames and numeric collision suffixes.


## Iterative bright-star separation (experimental)

**Iterative** starts from the Natural field and attempts isolated, well-matched bright-star groups. It alternates a smooth radial halo plus two crossing spike models with independent compact-core fits for catalogue neighbours, repeating until the summed model changes by less than 0.1%, up to 20 passes. Every catalogue neighbour participates in the light fit; only those passing the distance/astrometry screening are animated. Close unresolved companions, overlapping bright groups, overlapping analysis tiles, non-converged fits and large residuals are deferred.

Smooth additive model responsibilities replace hard polygon cut-outs. The decomposition preserves the starting image, and recovered neighbours keep their own catalogue distances. Convergence is numerical stability, not proof that the physical separation is correct. This remains an approximate PSF model, particularly for asymmetric or saturated stars; it does not recover information absent from the photograph.

The first Iterative render uses saved `photo.png`, `starless.png`, `source_wcs.fits`, `catalog.csv` and a current Natural `scene.json`; no additional star-removal run or Gaia query is needed. It saves `scene_iterative.json` for reuse and `iterative_report.json` with accepted/deferred groups and per-pass diagnostics. Natural and Dynamic fields are preserved. Spike colour and small width variations are measured along the actual arms, with catalogue neighbour cores excluded and interpolated across. This reduces coloured cross-shaped remnants, although faint residuals can remain. Older iterative caches are automatically refined again from the saved Natural field; the previous cache is backed up and existing exports are preserved. The experimental mode does not claim to separate all bright stars.

## Versions

The current release is **0.3.0**. The Siril title shows the running version. New export filenames include it, for example `flythrough_v0.3.0_iterative_60s_zoom30pct_24fps.mp4`. Previews and JSON sidecars show the rendering version, UTC creation time, and separate field preparation version; older unlabelled fields remain explicitly unversioned. MP4 files also carry the tool version in their comment metadata. Existing exports are preserved. Release history and version bump rules are in `gaia_flythrough/CHANGELOG.md`.

## Development

Install `requirements.txt` in a Python virtual environment. FFmpeg is required for MP4 export. Siril supplies `sirilpy` for the launcher; it is not needed for the core tests. Run:

```sh
python -m unittest discover -s gaia_flythrough -p "test_*.py"
```

See [DEVELOPMENT.md](DEVELOPMENT.md) for architecture, current limitations and a prompt for continuing development. Release history: [CHANGELOG](gaia_flythrough/CHANGELOG.md).

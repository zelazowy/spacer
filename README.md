# SPACER

**Stellar Parallax Animation through Catalogue-based Extraction and Reprojection**

*A walk through your astrophotography.*

SPACER turns a finished astrophotograph into a flythrough, using catalogue distances to move stars with depth-dependent parallax. Run it as a standalone Python desktop app or from Siril.

Current version: **1.0.1**. Star separation is experimental, especially around bright stars with overlapping halos and diffraction spikes.

## Requirements

- Python **3.10+** and the packages in [requirements.txt](requirements.txt).
- **FFmpeg** for MP4 export.
- **StarXTerminator CLI** with its model/license, or **StarNet 2.5+** with its model, for star removal.
- A plate-solved image, or **ASTAP** and its star database for the standalone app's optional solving step.
- Internet for initial stellar-catalogue downloads and optional target lookup. Prepared projects render offline.

Install the shared `astro-platesolve` library from the `siril_scripts` checkout before installing SPACER requirements (see setup below). Use the same editable source directory in Siril’s Python environment to share solver improvements. The library is currently installed from source, not PyPI.

External engines, models and databases are installed separately. SPACER discovers available executables; their paths can be changed in **Tool setup**.

## Standalone setup

```sh
git clone https://github.com/zelazowy/spacer.git
cd spacer
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e /path/to/siril_scripts/shared/astro-platesolve
python -m pip install -r requirements.txt
python SPACER.py
```

On Windows, activate with `.venv\Scripts\activate` instead.

1. On first use, open **Tool setup** and check star-removal, ASTAP (if needed) and FFmpeg paths. These are remembered across projects.
2. **Prepare image:** open a finished FITS, TIFF, PNG or JPEG; review the observation date and project folder. Reuse embedded coordinates or solve an unsolved standalone input. **Prepare image** saves the photographic layers without calculating stars or rendering a video.
3. **Calculate stars:** choose distance coverage and calculate the moving-star field. Completed calculations can be reused for many flights.
4. **Preview flight:** use the integrated preview to adjust duration, motion, zoom and travel. Distances are shown in **light-years**; the default travel is about **261 ly**. Defaults remain 60 seconds, 1.3× zoom and short 1.5-second easing.
5. **Export:** choose 24/30/60 fps and 1920/2560/3840 px width or original image size, then **Save video**. Output keeps the image's aspect ratio and never upscales.

The dark workspace opens in a large resizable window; maximize it when useful. The image steps share one stable preview area, with independently scrolling settings. Tool setup has its own image-free layout. Completed steps remain available in the rail.
Original images are left unchanged. Outputs go into `flythrough/<image-name>/` beside the source unless you choose another project folder.

## Run from Siril

Keep `Siril_Gaia_Flythrough.py` beside the entire `gaia_flythrough/` folder. Add the repository folder to Siril's Python script search paths, refresh its script list, and launch the script with a **plate-solved image open**. Alternatively, use Siril's console:

```text
pyscript "/path/to/spacer/Siril_Gaia_Flythrough.py"
```

For a linear Siril image, choose **Linked autostretch** in Prepare image. For a finished image, keep **Current pixels**. Siril's display stretch alone is not applied to an ordinary pixel snapshot. The launcher snapshots current pixels, including unsaved edits.

The Siril launcher requires an existing plate solution and suggests Siril's solver or `Siril_ASTAP_PlateSolve.py` when one is missing. Optional in-app ASTAP solving is available in the standalone app.

## Motion and saved projects

**Camera zoom** adds the chosen enlargement to stellar parallax. **Travel toward a target** derives background enlargement from target distance and travel; use **Choose target…** for a short catalogue list or enter a distance under Preview flight → Target distance. Target selection does not re-centre the camera.

Use **Open project…** to return to earlier work, even after switching images. Change duration or zoom and choose **Save video** in Export to reuse saved layers and calculations. Each export gets a new filename; previous videos remain available.

**Preview flight** uses a lightweight integrated 1200 px scene with play/pause, scrubbing, star boundaries and distance inspection. Its controls are the actual flight settings, so there is no separate Apply step. Saved scenes are never edited by previewing. **Open exported HTML** in Export retains access to the latest full-resolution HTML export.
To change the moving-star limit, enable approximate distances, or apply a newer separation algorithm, use **Calculate stars → Recalculate stars**, then export. Recalculation reuses saved layers and available catalogue caches, preserves earlier calculation revisions, and downloads supplementary catalogues only when needed.

## Accuracy

Stellar distances come from Gaia/Bailer-Jones, with optional screened Hipparcos-2 and broader Gaia estimates. Click a moving star in the preview to inspect its distance source, interval and extracted patch. Some stars remain stationary because their data, match or light separation is unsuitable.

Nebulosity and unseparated stars remain on a flat photographic layer. This is an artistic visualization informed by astronomical data; it is not a complete three-dimensional reconstruction. The current priority is better separation of overlapping bright stars and spikes. See [scientific scope and data credits](docs/SCIENCE.md).

## Documentation

| Document | Contents |
| --- | --- |
| [User guide](docs/USER_GUIDE.md) | Inputs, tools, motion, project reuse, outputs and troubleshooting |
| [Scientific scope](docs/SCIENCE.md) | Distance selection, projection, separation limits and data credits |
| [Changelog](CHANGELOG.md) | Release history |
| [Development](docs/DEVELOPMENT.md) | Architecture, implementation context and validation commands |
| [Validation](docs/VALIDATION.md) | Recorded image checks and their limits |
| [Agent instructions](AGENTS.md) | Repository rules for coding agents |

A unified headless CLI, bundled installers and a website are future work. The existing prototype CLI takes separate photo, starless and WCS inputs; see the [user guide](docs/USER_GUIDE.md#command-line-entry-points).

"""Optional ASTAP solving of a same-size proxy; original pixels stay untouched."""
import re
import uuid
from pathlib import Path
import tempfile
import threading
import time
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from image_source import FileImageSource
from siril_pipeline import save_project
from version import VERSION, created_stamp
from photo_date import stamp_date, date_info
from task_progress import Diagnostic
from density import DEFAULT_MAX_STARS


from astro_platesolve import SolveOptions, solve_image
# Backward-compatible utility imports; implementations live only in the library.
from astro_platesolve.astap import (find_astap, resolve_astap, SolverLogTail,
    solver_header, clean_solution_header, compact_star_proxy, run_attempt,
    refinement_consistent)

def diagnostic_path(options):
    directory=Path(getattr(options,'log_directory',Path(__file__).resolve().parents[1]/'.spacer-logs'))
    try:
        directory.mkdir(parents=True,exist_ok=True)
        return directory/('astap_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]+'.log')
    except OSError:
        with tempfile.NamedTemporaryFile(prefix='spacer_astap_',suffix='.log',delete=False) as file:
            return Path(file.name)


def solve_project(options,progress=lambda message:None,cancel=None):
    cancel=cancel or threading.Event()
    out=Path(options.output).expanduser().resolve()
    if out.exists() and any(out.iterdir()): raise ValueError('Choose a new or empty project folder before solving; existing projects are preserved.')
    source=FileImageSource(options.source,getattr(options,'wcs_path',None))
    progress('Loading solver input: '+str(source.path))
    pixels,header=source.snapshot(allow_unsolved=True)
    header=header.copy()
    progress(Diagnostic(f'Input: {pixels.shape[2]} × {pixels.shape[1]} pixels, {pixels.shape[0]} colour channels. Original file stays unchanged.'))
    info=getattr(options,'date_info',None) or (date_info(options.epoch,'Manual date') if options.epoch else source.date_info())
    if options.epoch: header['DATE-OBS']=options.epoch
    stamp_date(header,info)
    log_path=diagnostic_path(options);options.diagnostic_log=str(log_path)
    progress('Solver diagnostic log: '+str(log_path))
    result=solve_image(pixels,header,SolveOptions(
        executable=options.astap,database=options.database,target=options.target,
        fov=options.fov,radius=options.radius,binning=options.binning,
        timeout=getattr(options,'timeout',600),confirm_original=True,
        log_path=str(log_path)),progress,cancel)
    solved=result.header
    attempts=result.attempts;strategy=result.strategy;stars=result.maximum_stars
    output=log_path.read_text(errors='replace') if log_path.exists() else ''
    # Project/source policies remain local to SPACER.
    # Export only astrometry; proxy intensity/mono geometry must never replace the photo.
    astrometry=re.compile(r'(?:WCSAXES|WCSNAME|CTYPE[12]|CUNIT[12]|CRPIX[12]|CRVAL[12]|CDELT[12]|CROTA[12]|(?:CD|PC)[12]_[12]|PV[12]_\d+|(?:A|B|AP|BP)_(?:ORDER|DMAX|\d+_\d+)|LONPOLE|LATPOLE|RADESYS|RADECSYS|EQUINOX|PLTSOLVD|RA|DEC)')
    for key in list(header.keys()):
        if astrometry.fullmatch(key) or key in ('CHECKSUM','DATASUM'): del header[key]
    wcs=WCS(solved,naxis=2)
    header.update(wcs.to_header(relax=True));header['ROWORDER']='BOTTOM-UP'
    if cancel.is_set(): raise InterruptedError('Plate solving cancelled.')
    if out.exists() and any(out.iterdir()): raise ValueError('The chosen project folder is no longer empty; existing files are preserved.')
    out.mkdir(parents=True,exist_ok=True)
    temporary=out/'source_wcs.fits.tmp'
    fits.PrimaryHDU(pixels,header).writeto(temporary)
    temporary.replace(out/'source_wcs.fits')
    (out/'astap.log').write_text(output)
    save_project(out,created_with_version=VERSION,created_at=created_stamp(),stage='solved',
        source=str(source.path),engine=options.engine,executable=options.executable,epoch=str(header.get('DATE-OBS','')),
        seconds=options.seconds,zoom=options.zoom,ffmpeg=options.ffmpeg,date_info=info,max_stars=getattr(options,'max_stars',DEFAULT_MAX_STARS),
        astrometry=dict(solver=result.backend.upper(),tool_version=VERSION,solved_at=created_stamp(),executable=str(result.metadata.get('executable',options.astap)),
            database=options.database,target=options.target,fov=options.fov,radius=options.radius,binning=options.binning,
            strategy=strategy,maximum_stars=stars,attempts=attempts,solver_library='0.1.0',backend_metadata=result.metadata))
    progress('Sky position solved. The project is ready for preparation.')
    return out

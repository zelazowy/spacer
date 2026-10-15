"""Optional ASTAP solving of a same-size proxy; original pixels stay untouched."""
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.coordinates import SkyCoord
import astropy.units as u
from image_source import FileImageSource
from siril_pipeline import has_solution, save_project
from version import VERSION, created_stamp


def find_astap():
    for value in (shutil.which('astap'),shutil.which('astap_cli'),
                  '/Applications/astap.app/Contents/MacOS/astap','/usr/local/bin/astap'):
        if value and Path(value).is_file(): return str(Path(value).resolve())
    return ''


def resolve_astap(value):
    path=Path(value).expanduser()
    if path.is_dir(): path=path/'Contents'/'MacOS'/'astap' if path.suffix.lower()=='.app' else path/'astap'
    if not path.is_file() or not os.access(path,os.X_OK):
        raise ValueError('Choose an installed ASTAP executable in Advanced settings.')
    return path.resolve()


def solve_project(options,progress=lambda message:None,cancel=None):
    cancel=cancel or threading.Event()
    executable=resolve_astap(options.astap)
    out=Path(options.output).expanduser().resolve()
    if out.exists(): raise ValueError('Choose a new project folder before solving; existing projects are preserved.')
    if options.database and not Path(options.database).expanduser().is_dir():
        raise ValueError('ASTAP star database folder does not exist.')
    if not 0<=options.fov<=180 or not 0<options.radius<=180 or not 0<=options.binning<=8:
        raise ValueError('Invalid field height, search radius or downsampling.')
    source=FileImageSource(options.source,getattr(options,'wcs_path',None))
    pixels,header=source.snapshot(allow_unsolved=True)
    if options.epoch: header['DATE-OBS']=options.epoch
    ra=0.;dec=0.
    if options.target.strip():
        progress('Finding the approximate sky position…')
        try: center=SkyCoord(options.target,unit=(u.hourangle,u.deg),frame='icrs')
        except ValueError: center=SkyCoord.from_name(options.target)
        ra=float(center.icrs.ra.hour);dec=float(center.icrs.dec.deg)
    if cancel.is_set(): raise InterruptedError('Plate solving cancelled.')
    mono=pixels.mean(axis=0,dtype=np.float32)
    low=float(mono.min());high=float(mono.max())
    if high<=low: raise ValueError('This image is constant; no stars can be detected.')
    mono=(mono-low)*(65535./(high-low))
    progress('Solving sky position with ASTAP…')
    with tempfile.TemporaryDirectory(prefix='spacer_astap_') as work:
        proxy=Path(work)/'proxy.fits'
        fits.PrimaryHDU(mono,header).writeto(proxy)
        argv=[str(executable),'-f',str(proxy),'-r',str(options.radius),'-z',str(options.binning),
              '-fov',str(options.fov),'-ra',str(ra),'-spd',str(dec+90),'-sip','-wcs']
        if options.database: argv+=['-d',str(Path(options.database).expanduser().resolve())]
        log_path=Path(work)/'astap.log';started=time.monotonic()
        with log_path.open('w') as log:
            process=subprocess.Popen(argv,stdout=log,stderr=subprocess.STDOUT,cwd=work)
            try:
                while process.poll() is None:
                    if cancel.wait(.2): raise InterruptedError('Plate solving cancelled.')
                    if time.monotonic()-started>getattr(options,'timeout',600):
                        raise RuntimeError('ASTAP timed out. Retry with an approximate target and field height.')
            finally:
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill();process.wait()
        output=log_path.read_text(errors='replace')
        for line in output.splitlines()[-20:]: progress(line)
        if cancel.is_set(): raise InterruptedError('Plate solving cancelled.')
        ini=proxy.with_suffix('.ini')
        values={}
        if ini.exists():
            for line in ini.read_text(errors='replace').splitlines():
                if '=' in line:
                    key,value=line.split('=',1);values[key.strip()]=value.split('//')[0].strip()
        wcs_path=proxy.with_suffix('.wcs')
        if process.returncode!=0 or values.get('PLTSOLVD')!='T' or not wcs_path.exists():
            error=values.get('ERROR',output[-1500:] or f'exit code {process.returncode}')
            raise RuntimeError('ASTAP could not solve this image: '+error+'\nCheck its star database, or set a target and field height in Advanced settings.')
        text=wcs_path.read_text(encoding='ascii').rstrip('\x00')
        solved=fits.Header.fromstring(text,sep='\n' if '\n' in text else '')
        for key,size in (('NAXIS1',pixels.shape[2]),('NAXIS2',pixels.shape[1])):
            if key in solved and solved[key]!=size: raise RuntimeError('ASTAP changed image dimensions; solution rejected.')
        required={'CTYPE1','CTYPE2','CRPIX1','CRPIX2','CRVAL1','CRVAL2'}
        if not required.issubset(solved): raise RuntimeError('ASTAP returned no valid celestial solution.')
        solved['NAXIS']=2;solved['NAXIS1']=pixels.shape[2];solved['NAXIS2']=pixels.shape[1]
        if not has_solution(solved): raise RuntimeError('ASTAP returned no valid celestial solution.')
        wcs=WCS(solved,naxis=2)
        if not np.isfinite(wcs.pixel_scale_matrix).all() or abs(np.linalg.det(wcs.pixel_scale_matrix))<1e-15:
            raise RuntimeError('ASTAP returned an invalid sky scale.')
        if not np.isfinite(wcs.all_pix2world([[0,0],[pixels.shape[2]-1,pixels.shape[1]-1]],0)).all():
            raise RuntimeError('ASTAP returned invalid sky coordinates.')
        # Export only astrometry; proxy intensity/mono geometry must never replace the photo.
        astrometry=re.compile(r'(?:WCSAXES|WCSNAME|CTYPE[12]|CUNIT[12]|CRPIX[12]|CRVAL[12]|CDELT[12]|CROTA[12]|(?:CD|PC)[12]_[12]|PV[12]_\d+|(?:A|B|AP|BP)_(?:ORDER|DMAX|\d+_\d+)|LONPOLE|LATPOLE|RADESYS|RADECSYS|EQUINOX|PLTSOLVD|RA|DEC)')
        for key in list(header.keys()):
            if astrometry.fullmatch(key) or key in ('CHECKSUM','DATASUM'): del header[key]
        header.update(wcs.to_header(relax=True));header['ROWORDER']='BOTTOM-UP'
        if cancel.is_set(): raise InterruptedError('Plate solving cancelled.')
        out.mkdir(parents=True,exist_ok=False)
        temporary=out/'source_wcs.fits.tmp'
        fits.PrimaryHDU(pixels,header).writeto(temporary)
        temporary.replace(out/'source_wcs.fits')
        (out/'astap.log').write_text(output)
        save_project(out,created_with_version=VERSION,created_at=created_stamp(),stage='solved',
            source=str(source.path),engine=options.engine,executable=options.executable,epoch=str(header.get('DATE-OBS','')),
            seconds=options.seconds,zoom=options.zoom,ffmpeg=options.ffmpeg,
            astrometry=dict(solver='ASTAP',tool_version=VERSION,solved_at=created_stamp(),executable=str(executable),
                database=options.database,target=options.target,fov=options.fov,radius=options.radius,binning=options.binning))
    progress('Sky position solved. The project is ready for preparation.')
    return out

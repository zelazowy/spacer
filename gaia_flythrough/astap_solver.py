"""Optional ASTAP solving of a same-size proxy; original pixels stay untouched."""
import os
import codecs
import re
import shlex
import uuid
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
from photo_date import stamp_date, date_info


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


class SolverLogTail:
    """Read appended solver output without blocking or losing partial lines."""
    def __init__(self,reader,progress):
        self.reader=reader;self.progress=progress;self.pending=''
        self.decoder=codecs.getincrementaldecoder('utf-8')(errors='replace')

    def drain(self,final=False):
        data=self.reader.read()
        if isinstance(data,bytes): text=self.decoder.decode(data,final=final)
        else: text=data
        lines=(self.pending+text).replace('\r','\n').split('\n')
        self.pending=lines.pop()
        if final and self.pending: lines.append(self.pending);self.pending=''
        for line in lines:
            if line.strip(): self.progress('ASTAP | '+line.rstrip())
        return bool(data)


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
    executable=resolve_astap(options.astap)
    out=Path(options.output).expanduser().resolve()
    if out.exists(): raise ValueError('Choose a new project folder before solving; existing projects are preserved.')
    if options.database and not Path(options.database).expanduser().is_dir():
        raise ValueError('ASTAP star database folder does not exist.')
    if not 0<=options.fov<=180 or not 0<options.radius<=180 or not 0<=options.binning<=8:
        raise ValueError('Invalid field height, search radius or downsampling.')
    source=FileImageSource(options.source,getattr(options,'wcs_path',None))
    progress('Loading solver input: '+str(source.path))
    pixels,header=source.snapshot(allow_unsolved=True)
    progress(f'Input: {pixels.shape[2]} × {pixels.shape[1]} pixels, {pixels.shape[0]} colour channels. Original file stays unchanged.')
    info=getattr(options,'date_info',None) or (date_info(options.epoch,'Manual date') if options.epoch else source.date_info())
    if options.epoch: header['DATE-OBS']=options.epoch
    stamp_date(header,info)
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
    progress(f'ASTAP search: target {options.target or "blind/all sky"}; radius {options.radius:g}°; field height {format(options.fov,"g")+"°" if options.fov else "auto (about 0.3–10°)"}; downsampling {options.binning or "auto"}.')
    progress('ASTAP database: '+(options.database or 'ASTAP default location'))
    progress('Preparing the same-size monochrome solver copy…')
    with tempfile.TemporaryDirectory(prefix='spacer_astap_') as work:
        proxy=Path(work)/'proxy.fits'
        fits.PrimaryHDU(mono,header).writeto(proxy)
        argv=[str(executable),'-f',str(proxy),'-r',str(options.radius),'-z',str(options.binning),
              '-fov',str(options.fov),'-ra',str(ra),'-spd',str(dec+90),'-sip','-wcs','-progress']
        if options.database: argv+=['-d',str(Path(options.database).expanduser().resolve())]
        log_path=diagnostic_path(options);options.diagnostic_log=str(log_path)
        progress('Solver diagnostic log: '+str(log_path))
        progress('ASTAP command: '+shlex.join(argv))
        started=time.monotonic();last_output=started;last_heartbeat=started
        progress('Solving sky position with ASTAP…')
        with log_path.open('w') as log:
            log.write(f'SPACER v{VERSION}\nSource: {source.path}\nCommand: {shlex.join(argv)}\n\n');log.flush()
            with log_path.open('rb') as reader:
                reader.seek(log.tell())
                tail=SolverLogTail(reader,progress)
                process=subprocess.Popen(argv,stdout=log,stderr=subprocess.STDOUT,cwd=work)
                try:
                    while process.poll() is None:
                        if tail.drain(): last_output=time.monotonic()
                        if cancel.wait(.2): raise InterruptedError('Plate solving cancelled. Diagnostic log: '+str(log_path))
                        now=time.monotonic()
                        if now-last_heartbeat>=10 and now-last_output>=10:
                            progress(f'ASTAP still working — {now-started:.0f} s elapsed, {now-last_output:.0f} s since last output. Cancel is available.')
                            last_heartbeat=now
                        if now-started>getattr(options,'timeout',600):
                            raise RuntimeError('ASTAP timed out. Retry with an approximate target and field height. Diagnostic log: '+str(log_path))
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try: process.wait(timeout=5)
                        except subprocess.TimeoutExpired: process.kill();process.wait()
                    tail.drain(final=True)
        output=log_path.read_text(errors='replace')
        progress(f'ASTAP exited with code {process.returncode} after {time.monotonic()-started:.1f} s.')
        if cancel.is_set(): raise InterruptedError('Plate solving cancelled.')
        ini=proxy.with_suffix('.ini')
        values={}
        if ini.exists():
            for line in ini.read_text(errors='replace').splitlines():
                if '=' in line:
                    key,value=line.split('=',1);values[key.strip()]=value.split('//')[0].strip()
        wcs_path=proxy.with_suffix('.wcs')
        if process.returncode!=0 or values.get('PLTSOLVD')!='T' or not wcs_path.exists():
            reasons={1:'No matching star pattern found.',2:'Not enough usable stars detected.',16:'Could not read the solver image.',32:'ASTAP star database not found.',33:'Could not read the ASTAP star database.'}
            error=values.get('ERROR') or reasons.get(process.returncode,f'Exit code {process.returncode}.')
            raise RuntimeError('ASTAP could not solve this image: '+error+'\nCheck its star database, or set a target and field height in Advanced settings.\nDiagnostic log: '+str(log_path))
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
            seconds=options.seconds,zoom=options.zoom,ffmpeg=options.ffmpeg,date_info=info,
            astrometry=dict(solver='ASTAP',tool_version=VERSION,solved_at=created_stamp(),executable=str(executable),
                database=options.database,target=options.target,fov=options.fov,radius=options.radius,binning=options.binning))
    progress('Sky position solved. The project is ready for preparation.')
    return out

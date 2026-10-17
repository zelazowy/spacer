"""Optional ASTAP solving of a same-size proxy; original pixels stay untouched."""
import os
import codecs
import copy
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
from scipy import ndimage
from astropy.io import fits
from astropy.wcs import WCS
from astropy.coordinates import SkyCoord
import astropy.units as u
from image_source import FileImageSource
from siril_pipeline import has_solution, save_project
from version import VERSION, created_stamp
from photo_date import stamp_date, date_info
from task_progress import Diagnostic
from density import DEFAULT_MAX_STARS


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
            if line.strip(): self.progress(Diagnostic('ASTAP | '+line.rstrip()))
        return bool(data)


def diagnostic_path(options):
    directory=Path(getattr(options,'log_directory',Path(__file__).resolve().parents[1]/'.spacer-logs'))
    try:
        directory.mkdir(parents=True,exist_ok=True)
        return directory/('astap_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]+'.log')
    except OSError:
        with tempfile.NamedTemporaryFile(prefix='spacer_astap_',suffix='.log',delete=False) as file:
            return Path(file.name)


def compact_star_proxy(mono,cancel=None):
    """Measured star peaks only, in the unchanged pixel grid; not a render layer."""
    smooth=ndimage.gaussian_filter(mono,1)
    light=np.maximum(smooth-ndimage.gaussian_filter(mono,10),0)
    if cancel and cancel.is_set(): raise InterruptedError('Plate solving cancelled.')
    peaks=(light==ndimage.maximum_filter(light,9))&(light>np.percentile(light,99))
    yy,xx=np.where(peaks);strength=light[yy,xx]
    order=np.argsort(strength)[-1500:]
    if len(order)<12: return None
    result=np.zeros_like(mono)
    # Integer measured peaks preserve the verified proxy strategy. No resampling,
    # cropping, rotation or coordinate remapping is needed for the solved WCS.
    result[yy[order],xx[order]]=strength[order]
    return ndimage.gaussian_filter(result,2)


def run_attempt(executable,proxy,options,ra,dec,stars,log_path,progress,cancel,budget):
    argv=[str(executable),'-f',str(proxy),'-r',str(options.radius),'-z',str(options.binning),
          '-fov',str(options.fov),'-ra',str(ra),'-spd',str(dec+90),'-s',str(stars),'-sip','-wcs','-progress']
    if options.database: argv+=['-d',str(Path(options.database).expanduser().resolve())]
    progress(Diagnostic('ASTAP command: '+shlex.join(argv)))
    started=time.monotonic();last_output=started;last_heartbeat=started;timed_out=False
    with log_path.open('a') as log:
        log.write('\nCommand: '+shlex.join(argv)+'\n');log.flush()
        with log_path.open('rb') as reader:
            reader.seek(log.tell());tail=SolverLogTail(reader,progress)
            process=subprocess.Popen(argv,stdout=log,stderr=subprocess.STDOUT,cwd=str(proxy.parent))
            try:
                while process.poll() is None:
                    if tail.drain(): last_output=time.monotonic()
                    if cancel.wait(.2): raise InterruptedError('Plate solving cancelled. Diagnostic log: '+str(log_path))
                    now=time.monotonic()
                    if now-last_heartbeat>=10 and now-last_output>=10:
                        progress(f'ASTAP still working — {now-started:.0f} s in this attempt, {now-last_output:.0f} s since last output. Cancel is available.')
                        last_heartbeat=now
                    if now-started>budget: timed_out=True;break
            finally:
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill();process.wait()
                tail.drain(final=True)
    if timed_out:
        progress('Attempt time limit reached; trying the next available strategy.')
        return None,'Attempt time limit reached.'
    progress(Diagnostic(f'ASTAP exited with code {process.returncode} after {time.monotonic()-started:.1f} s.'))
    if cancel.is_set(): raise InterruptedError('Plate solving cancelled.')
    values={};ini=proxy.with_suffix('.ini')
    if ini.exists():
        for line in ini.read_text(errors='replace').splitlines():
            if '=' in line:
                key,value=line.split('=',1);values[key.strip()]=value.split('//')[0].strip()
    wcs_path=proxy.with_suffix('.wcs')
    if process.returncode==0 and values.get('PLTSOLVD')=='T' and wcs_path.exists():
        text=wcs_path.read_text(encoding='ascii').rstrip('\x00')
        return fits.Header.fromstring(text,sep='\n' if '\n' in text else ''),''
    reasons={1:'No matching star pattern found.',2:'Not enough usable stars detected.',16:'Could not read the solver image.',32:'ASTAP star database not found.',33:'Could not read the ASTAP star database.'}
    reason=values.get('ERROR') or reasons.get(process.returncode,f'Exit code {process.returncode}.')
    if process.returncode in (16,32,33):
        raise RuntimeError(reason+' Diagnostic log: '+str(log_path))
    return None,reason


def refinement_consistent(seed,refined,width,height):
    """Reject gross shifts, parity changes and unstable distortion at image edges."""
    try:
        before=seed.copy();after=refined.copy();before['NAXIS']=2;after['NAXIS']=2
        a=WCS(before,naxis=2);b=WCS(after,naxis=2)
        grid=np.array([[width/2,height/2],[0,0],[width-1,0],[0,height-1],[width-1,height-1]])
        errors=a.pixel_to_world(grid[:,0],grid[:,1]).separation(b.pixel_to_world(grid[:,0],grid[:,1])).arcsec
        scale=float(np.linalg.norm(a.pixel_scale_matrix,axis=0).mean()*3600)
        coarse='inexact scale' in str(seed.get('WARNING','')).lower()
        edge_limit=max(5*scale,float(np.linalg.norm(a.pixel_scale_matrix[:,1])*height*3600)*(.02 if coarse else .005))
        same_parity=np.linalg.det(a.pixel_scale_matrix)*np.linalg.det(b.pixel_scale_matrix)>0
        good=bool(np.isfinite(errors).all() and errors[0]<=max(2,3*scale) and errors[1:].max()<=edge_limit and same_parity)
        return good,f'center shift {errors[0]:.2f} arcsec, maximum corner shift {errors[1:].max():.2f} arcsec'
    except (ValueError,TypeError): return False,'invalid refined coordinate grid'


def solve_project(options,progress=lambda message:None,cancel=None):
    cancel=cancel or threading.Event()
    executable=resolve_astap(options.astap)
    out=Path(options.output).expanduser().resolve()
    if out.exists() and any(out.iterdir()): raise ValueError('Choose a new or empty project folder before solving; existing projects are preserved.')
    if options.database and not Path(options.database).expanduser().is_dir():
        raise ValueError('ASTAP star database folder does not exist.')
    if not 0<=options.fov<=180 or not 0<options.radius<=180 or not 0<=options.binning<=8:
        raise ValueError('Invalid field height, search radius or downsampling.')
    source=FileImageSource(options.source,getattr(options,'wcs_path',None))
    progress('Loading solver input: '+str(source.path))
    pixels,header=source.snapshot(allow_unsolved=True)
    progress(Diagnostic(f'Input: {pixels.shape[2]} × {pixels.shape[1]} pixels, {pixels.shape[0]} colour channels. Original file stays unchanged.'))
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
    progress(Diagnostic(f'ASTAP search: target {options.target or "blind/all sky"}; radius {options.radius:g}°; field height {format(options.fov,"g")+"°" if options.fov else "auto (about 0.3–10°)"}; downsampling {options.binning or "auto"}.'))
    progress(Diagnostic('ASTAP database: '+(options.database or 'ASTAP default location')))
    progress(Diagnostic('Preparing the same-size monochrome solver copy…'))
    log_path=diagnostic_path(options);options.diagnostic_log=str(log_path)
    log_path.write_text(f'SPACER v{VERSION}\nSource: {source.path}\n')
    progress('Solver diagnostic log: '+str(log_path))
    strategies=[('expanded-star',2000),('compact-peaks',500),('standard',500)]
    deadline=time.monotonic()+getattr(options,'timeout',600)
    solved=None;error='No matching star pattern found.';attempts=[]
    with tempfile.TemporaryDirectory(prefix='spacer_astap_') as work:
        for index,(strategy,stars) in enumerate(strategies):
            if cancel.is_set(): raise InterruptedError('Plate solving cancelled.')
            remaining=deadline-time.monotonic()
            if remaining<=0: raise RuntimeError('ASTAP timed out. Diagnostic log: '+str(log_path))
            proxy=Path(work)/f'proxy_{index+1}.fits'
            data=mono
            if strategy=='compact-peaks':
                progress('Building a compact-star proxy from measured peaks; keeping the original coordinate grid.')
                data=compact_star_proxy(mono,cancel)
                if data is None:
                    progress('Too few distinct peaks for a compact-star retry; skipping it.');continue
                data=data/max(float(data.max()),1e-10)*65535
            fits.PrimaryHDU(data,header).writeto(proxy)
            progress(f'Solving sky position: attempt {index+1}/{len(strategies)} — {strategy}, up to {stars} stars.')
            remaining=deadline-time.monotonic()
            if remaining<=0: raise RuntimeError('ASTAP timed out. Diagnostic log: '+str(log_path))
            budget=remaining/(len(strategies)-index)
            search=copy.copy(options)
            if options.target.strip() and strategy!='standard': search.radius=min(options.radius,5)
            progress(Diagnostic(f'Attempt search radius: {search.radius:g}°.'))
            solved,error=run_attempt(executable,proxy,search,ra,dec,stars,log_path,progress,cancel,budget)
            attempts.append(dict(strategy=strategy,stars=stars,fov=search.fov,radius=search.radius,solved=solved is not None,error=error))
            if solved is not None:
                # Every first match is a seed. Confirm the measured scale and
                # refine with more real photographed stars before committing WCS.
                progress('Candidate found; refining coordinates on original photographic pixels, up to 5000 stars.')
                seed=solved.copy();seed['NAXIS']=2
                if not has_solution(seed):
                    raise RuntimeError('ASTAP returned no valid celestial solution.')
                else:
                    seed_wcs=WCS(seed,naxis=2)
                    center=seed_wcs.pixel_to_world((pixels.shape[2]-1)/2,(pixels.shape[1]-1)/2)
                    guided=copy.copy(options)
                    guided.fov=float(np.linalg.norm(seed_wcs.pixel_scale_matrix[:,1])*pixels.shape[1])
                    guided.radius=min(options.radius,5)
                    if not np.isfinite(guided.fov) or not 0<guided.fov<=180:
                        raise RuntimeError('ASTAP returned an invalid sky scale.')
                    original_proxy=Path(work)/f'original_confirmation_{index}.fits'
                    fits.PrimaryHDU(mono,header).writeto(original_proxy)
                    solved=None
                    measured_fov=guided.fov
                    for refinement_index,(refinement_stars,scale_factor) in enumerate(((5000,1),(2000,1),(3000,1.01))):
                        # A slightly wider scale bracket helps processed fields whose
                        # first estimate lands on an unsuccessful quad selection.
                        guided.fov=measured_fov*scale_factor
                        remaining=deadline-time.monotonic()
                        if remaining<=0: raise RuntimeError('ASTAP timed out. Diagnostic log: '+str(log_path))
                        # Fresh output names prevent reusing a stale successful sidecar.
                        refinement_proxy=Path(work)/f'refine_{index}_{refinement_index}.fits'
                        shutil.copyfile(original_proxy,refinement_proxy)
                        candidate,error=run_attempt(executable,refinement_proxy,guided,float(center.ra.hour),float(center.dec.deg),
                            refinement_stars,log_path,progress,cancel,remaining/2)
                        accepted=False
                        if candidate is not None:
                            accepted,comparison=refinement_consistent(seed,candidate,pixels.shape[2],pixels.shape[1])
                            if 'inexact scale' in str(candidate.get('WARNING','')).lower(): accepted=False
                            progress(Diagnostic(('Refinement accepted: ' if accepted else 'Refinement rejected: ')+comparison))
                            if not accepted: error='Refined WCS failed consistency/scale checks.'
                        attempts.append(dict(strategy='original-refinement',stars=refinement_stars,fov=guided.fov,radius=guided.radius,solved=candidate is not None,accepted=accepted,error=error))
                        if accepted:
                            solved=candidate;strategy=strategy+'+original-refinement';stars=refinement_stars;break
                        progress('Retrying refinement with another star sample/scale bracket.' if refinement_index<2 else 'No reliable refinement; trying the next search strategy.')
            if solved is not None:
                progress(Diagnostic('Successful ASTAP strategy: '+strategy));break
            progress('Attempt did not solve: '+error)
        if solved is None:
            if time.monotonic()>=deadline: error='ASTAP timed out.'
            raise RuntimeError('ASTAP could not solve this image: '+error+'\nCheck its star database, or provide an object name or set the field height in Advanced settings.\nDiagnostic log: '+str(log_path))
        output=log_path.read_text(errors='replace')
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
        if out.exists() and any(out.iterdir()): raise ValueError('The chosen project folder is no longer empty; existing files are preserved.')
        out.mkdir(parents=True,exist_ok=True)
        temporary=out/'source_wcs.fits.tmp'
        fits.PrimaryHDU(pixels,header).writeto(temporary)
        temporary.replace(out/'source_wcs.fits')
        (out/'astap.log').write_text(output)
        save_project(out,created_with_version=VERSION,created_at=created_stamp(),stage='solved',
            source=str(source.path),engine=options.engine,executable=options.executable,epoch=str(header.get('DATE-OBS','')),
            seconds=options.seconds,zoom=options.zoom,ffmpeg=options.ffmpeg,date_info=info,max_stars=getattr(options,'max_stars',DEFAULT_MAX_STARS),
            astrometry=dict(solver='ASTAP',tool_version=VERSION,solved_at=created_stamp(),executable=str(executable),
                database=options.database,target=options.target,fov=options.fov,radius=options.radius,binning=options.binning,
                strategy=strategy,maximum_stars=stars,attempts=attempts))
    progress('Sky position solved. The project is ready for preparation.')
    return out

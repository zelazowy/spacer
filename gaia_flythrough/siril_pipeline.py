"""Shared SPACER preparation and rendering for desktop and Siril launchers."""
import argparse
import base64
import io
import json
from pathlib import Path
import shutil
import subprocess
import threading
import tempfile

import numpy as np
from PIL import Image
from astropy.io import fits
from astropy.wcs import WCS
import tifffile
from flythrough import prepare, render_video
from catalog import validate_field
from density import DEFAULT_MAX_STARS, moving_star_limit, limit_scene_stars
from version import VERSION, created_stamp
from photo_date import stamp_date, date_info


UNSOLVED_MESSAGE = ('This image has no valid plate solution. Plate-solve it with your preferred solver '
                    '(for example Siril_ASTAP_PlateSolve.py), then reopen the solved image.')


def normalized_pixels(pixels):
    a=np.asarray(pixels)
    if a.ndim==2:
        a=a[None,:,:]
    if a.ndim!=3 or a.shape[0] not in (1,3):
        raise ValueError('Open a monochrome or RGB image, not a sequence.')
    if np.issubdtype(a.dtype,np.integer):
        a=a.astype(np.float32)/np.iinfo(a.dtype).max
    else:
        a=a.astype(np.float32)
    if not np.isfinite(a).all() or a.min()<0 or a.max()>1:
        raise ValueError('Current pixels must be finite and in [0,1]. Normalize or stretch the image first.')
    if a.shape[0]==1:
        a=np.repeat(a,3,axis=0)
    return a


def parse_header(text,require_solution=True):
    if not isinstance(text,str) or not text.strip():
        if not require_solution: return fits.Header()
        raise ValueError('Current image has no FITS header. Plate-solve it first.')
    text=text.partition('\x00')[0]
    header=fits.Header.fromstring(text,sep='\n' if '\n' in text else '')
    if require_solution and not has_solution(header):
        raise ValueError(UNSOLVED_MESSAGE)
    return header


def has_solution(header):
    try:
        wcs=WCS(header,naxis=2)
        return wcs.has_celestial and np.isfinite(wcs.wcs.crval).all()
    except Exception:
        return False


def find_tool(name):
    candidates=[shutil.which(name)]
    if name=='ffmpeg':
        candidates+=['/opt/homebrew/bin/ffmpeg','/usr/local/bin/ffmpeg']
    elif name=='rc-astro':
        candidates+=['/usr/local/bin/rc-astro','/opt/homebrew/bin/rc-astro']
    else:
        candidates+=['/usr/local/bin/starnet2',str(Path.home()/'astro_soft/StarNet2.5.3/starnet2')]
    return next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file()),'')


def run_engine(argv,cwd,logfile,cancel,progress):
    progress('Removing stars…')
    with logfile.open('w') as log:
        process=subprocess.Popen(argv,cwd=cwd,stdout=log,stderr=subprocess.STDOUT)
        try:
            while process.poll() is None:
                if cancel.wait(.2):
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill();process.wait()
                    raise InterruptedError('Star removal cancelled. Working files retained.')
        finally:
            if process.poll() is None:
                process.terminate();process.wait()
    if process.returncode:
        raise RuntimeError(f'Star removal failed ({process.returncode}). See {logfile}\n'+logfile.read_text()[-2500:])


def export_layers(photo,starless,output):
    for name,a in [('photo',photo),('starless',starless)]:
        raster=np.flipud(np.moveaxis(a,0,-1))
        image=Image.fromarray(np.uint8(np.clip(raster,0,1)*255))
        image.save(output/f'{name}.png')
        image.save(output/f'{name}.jpg',quality=98,subsampling=0)


def read_project(out):
    path=Path(out)/'project.json'
    return json.loads(path.read_text()) if path.exists() else {}


def save_project(out, **changes):
    """Atomically commit project state only after a stage succeeds."""
    out=Path(out)
    state=read_project(out)
    state.update(changes, schema=1, updated_with_version=VERSION, updated_at=created_stamp())
    temporary=out/'project.json.tmp'
    temporary.write_text(json.dumps(state,indent=2,allow_nan=False))
    temporary.replace(out/'project.json')


def calculation_folder(out):
    """Resolve the active revision; never silently fall back to older analysis."""
    out=Path(out).resolve()
    relative=read_project(out).get('calculation_path')
    if not relative: return out
    folder=(out/relative).resolve()
    if not folder.is_relative_to(out/'calculations') or not (folder/'scene_iterative.json').is_file():
        raise ValueError('The active star calculations are missing or invalid. Recalculate stars from the saved layers.')
    return folder


def recalculation_missing(out):
    return [name for name in ('photo.png','starless.png','source_wcs.fits','catalog.csv') if not (Path(out)/name).is_file()]


def recalculate_project(out,options,progress=lambda message:None,cancel=None):
    """Publish a complete calculation revision, keeping old analysis on failure."""
    out=Path(out).resolve();cancel=cancel or threading.Event()
    missing=recalculation_missing(out)
    if missing: raise ValueError('Recalculation needs saved project files: '+', '.join(missing))
    max_stars=moving_star_limit(options.max_stars)
    state=read_project(out);header=fits.getheader(out/'source_wcs.fits')
    args=argparse.Namespace(photo=out/'photo.png',starless=out/'starless.png',wcs=out/'source_wcs.fits',
        catalog_path=out/'catalog.csv',epoch=header.get('DATE-OBS') or state.get('epoch'),
        magnitude=18,threshold=.008,match_pixels=3,max_uncertainty=.2,raster_bottom_up=False,
        max_stars=max_stars,progress=progress,cancel_event=cancel,stage_progress=getattr(options,'stage_progress',None))
    progress(f'Recalculating stars with limit {max_stars:,}. Reusing saved image, starless layer and Gaia catalogue.')
    with tempfile.TemporaryDirectory(prefix='.recalculate-',dir=out) as temporary:
        work=Path(temporary)
        scene,background=prepare(args,work)
        if state.get('date_info'): scene=dict(scene,date_info=state['date_info'])
        if cancel.is_set(): raise InterruptedError('Star recalculation cancelled. Previous calculations are kept.')
        (work/'scene.json').write_text(json.dumps(scene,allow_nan=False))
        from iterative_deblend import refine_prepared_field
        scene,background=refine_prepared_field(scene,out,progress,cancel,
            stage_progress=getattr(options,'stage_progress',None),report_folder=work)
        scene,_=limit_scene_stars(scene,max_stars,progress,cancel,getattr(options,'stage_progress',None))
        if cancel.is_set(): raise InterruptedError('Star recalculation cancelled. Previous calculations are kept.')
        (work/'scene_iterative.json').write_text(json.dumps(scene,allow_nan=False))
        history=out/'calculations';history.mkdir(exist_ok=True)
        index=1
        while (history/f'v{VERSION}_{index:03d}').exists(): index+=1
        revision=history/f'v{VERSION}_{index:03d}'
        work.rename(revision)
        save_project(out,calculation_path=str(revision.relative_to(out)),max_stars=max_stars,stage='ready')
    progress(f'Star calculations updated: {len(scene["stars"]):,} moving stars. Ready to render.')
    return out


def resume_project(out, options, progress=lambda message:None, cancel=None):
    """Resume the saved snapshot; never consult the currently open Siril image."""
    out=Path(out)
    active=calculation_folder(out)
    if (active/'scene.json').exists() or (active/'scene_iterative.json').exists() or (out/'preview.html').exists():
        return render_prepared(out,options,progress,cancel)
    state=read_project(out)
    if not state or not (out/'source_wcs.fits').exists():
        raise ValueError('This folder is not a SPACER project. Choose a new project folder.')
    if state.get('stage')=='solved':
        from astropy.time import Time
        epoch=getattr(options,'epoch','') or state.get('epoch','')
        if not epoch: raise ValueError('Enter the observation date in Advanced settings before preparing this project.')
        Time(epoch)
        info=getattr(options,'date_info',None) or (state.get('date_info') if epoch==state.get('epoch') else date_info(epoch,'Manual date'))
        save_project(out,date_info=info,engine=getattr(options,'engine',state['engine']),
            executable=getattr(options,'executable',state['executable']),epoch=epoch)
        state=read_project(out)
    options.max_stars=getattr(options,'max_stars',state.get('max_stars',DEFAULT_MAX_STARS))
    options.engine=state['engine']
    options.executable=state['executable']
    options.epoch=state['epoch']
    options.source=state['source']
    options.date_info=state.get('date_info')
    with fits.open(out/'source_wcs.fits') as hdul:
        return run_pipeline(hdul[0].data,hdul[0].header,options,progress,cancel)


def run_pipeline(pixels,header,options,progress=lambda message:None,cancel=None):
    cancel=cancel or threading.Event()
    max_stars=moving_star_limit(getattr(options,'max_stars',DEFAULT_MAX_STARS))
    photo=normalized_pixels(pixels)
    if not has_solution(header):
        raise ValueError(UNSOLVED_MESSAGE)
    out=Path(options.output).expanduser().resolve()
    if out.exists():
        if not read_project(out) or not (out/'source_wcs.fits').exists():
            raise ValueError('Existing folder is not a resumable SPACER project.')
        with fits.open(out/'source_wcs.fits') as saved:
            photo=normalized_pixels(saved[0].data)
            header=saved[0].header.copy()
    validate_field(WCS(header,naxis=2).celestial,photo.shape[2],photo.shape[1])
    if not out.exists():
        out.mkdir(parents=True)
        save_project(out, created_with_version=VERSION, created_at=created_stamp(),
            source=str(options.source), engine=options.engine, executable=options.executable,
            epoch=str(options.epoch or header.get('DATE-OBS','')), stage='snapshot')
    info=getattr(options,'date_info',None) or read_project(out).get('date_info')
    save_project(out,seconds=options.seconds,zoom=options.zoom,ffmpeg=options.ffmpeg,date_info=info,max_stars=max_stars)
    header=header.copy();header['ROWORDER']='BOTTOM-UP'
    if options.epoch: header['DATE-OBS']=str(options.epoch)
    stamp_date(header,info)
    if read_project(out).get('stage')=='solved':
        with fits.open(out/'source_wcs.fits',mode='update') as saved:
            saved[0].header['DATE-OBS']=str(options.epoch)
            stamp_date(saved[0].header,info)
        save_project(out,stage='snapshot')
    if not (out/'source_wcs.fits').exists():
        fits.PrimaryHDU(photo,header).writeto(out/'source_wcs.fits')
    if options.engine=='StarXTerminator':
        starless_path=out/'starless_work.fits'
        if read_project(out).get('starless_complete') is not True or not starless_path.exists():
            run_engine([options.executable,'sxt',str(out/'source_wcs.fits'),
                    '--output',str(starless_path),'--depth','32F'],
                   str(Path(options.executable).parent),out/'star-removal.log',cancel,progress)
        with fits.open(starless_path) as hdul:
            starless=normalized_pixels(hdul[0].data)
            if 'TOP-DOWN' in str(hdul[0].header.get('ROWORDER','')):
                starless=np.flip(starless,axis=-2)
    else:
        input_path=out/'starnet_input.tif';starless_path=out/'starless_work.tif'
        tifffile.imwrite(input_path,np.uint16(np.flipud(np.moveaxis(photo,0,-1))*65535),photometric='rgb')
        if read_project(out).get('starless_complete') is not True or not starless_path.exists():
            run_engine([options.executable,'--input',str(input_path),'--output',str(starless_path)],
                   str(Path(options.executable).parent),out/'star-removal.log',cancel,progress)
        # Pillow decodes StarNet's LZW RGB TIFF without an extra codec package.
        # The photographic layers are exported as 8-bit RGB in either branch.
        with Image.open(starless_path) as image:
            starless=np.flipud(np.asarray(image.convert('RGB')))
        starless=normalized_pixels(np.moveaxis(starless,-1,0))
    if starless.shape!=photo.shape:
        raise ValueError('Star-removal output changed image dimensions; cannot match it safely.')
    if cancel.is_set(): raise InterruptedError('Cancelled.')
    progress('Saving photo and starless JPEGs (lossless PNGs used internally)…')
    export_layers(photo,starless,out)
    save_project(out,starless_complete=True,stage='matching')
    if not (options.epoch or header.get('DATE-OBS')):
        raise ValueError('Observation date is missing. Enter its date in the script window and retry.')
    args=argparse.Namespace(photo=out/'photo.png',starless=out/'starless.png',wcs=out/'source_wcs.fits',
        epoch=options.epoch or None,magnitude=18,threshold=.008,match_pixels=3,max_uncertainty=.2,
        raster_bottom_up=False,travel=80,zoom=1+options.zoom/100,seconds=options.seconds,
        fps=24,video_width=1920,ease_seconds=1.5,cancel_event=cancel,progress=progress,
        stage_progress=getattr(options,'stage_progress',None),max_stars=max_stars)
    progress('Matching stars to Gaia and screening distance uncertainty…')
    scene,background=prepare(args,out)
    if info: scene=dict(scene,date_info=info)
    if cancel.is_set(): raise InterruptedError('Cancelled after catalogue matching.')
    (out/'scene.json').write_text(json.dumps(scene,allow_nan=False))
    save_project(out,stage='refinement')
    return render_prepared(out,options,progress,cancel)


def load_prepared_scene(out):
    out=calculation_folder(out)
    path=out/'scene.json'
    if path.exists(): return json.loads(path.read_text())
    legacy=out/'preview.html'
    if not legacy.exists(): raise ValueError('This folder has no saved scene.json or legacy preview.html.')
    text=legacy.read_text().partition('const scene=')[2]
    if not text: raise ValueError('This preview has no embedded prepared field.')
    scene,_=json.JSONDecoder().raw_decode(text)
    if not all(k in scene for k in ('width','height','stars','background')):
        raise ValueError('The prepared field is incomplete.')
    path.write_text(json.dumps(scene,allow_nan=False))
    return scene


def render_prepared(out,options,progress=lambda message:None,cancel=None,scene=None,background=None):
    """Render a new variant using the saved field, without another Gaia/AI run."""
    out=Path(out).resolve()
    cancel=cancel or threading.Event()
    mode='iterative'
    max_stars=moving_star_limit(getattr(options,'max_stars',read_project(out).get('max_stars',DEFAULT_MAX_STARS)))
    active=calculation_folder(out)
    save_project(out,seconds=options.seconds,zoom=options.zoom,ffmpeg=options.ffmpeg,max_stars=max_stars)
    if scene is None:
        if mode=='iterative':
            path=active/'scene_iterative.json'
            if path.exists(): scene=json.loads(path.read_text())
            if scene is None or scene.get('iterative_revision',0)<2:
                if path.exists():
                    backup=active/'scene_iterative_before_spike_refinement.json'
                    if not backup.exists(): backup.write_text(path.read_text())
                    progress('Updating cached spike separation using the saved field.')
                natural=load_prepared_scene(out)
                if natural.get('extraction_version',0)<4:
                    raise ValueError('This legacy field needs fresh preparation. Choose a new project folder; old exports are preserved.')
                from iterative_deblend import refine_prepared_field
                natural,_=limit_scene_stars(natural,max_stars,progress,cancel,getattr(options,'stage_progress',None))
                scene,background=refine_prepared_field(natural,out,progress,cancel,stage_progress=getattr(options,'stage_progress',None))
                scene,limited_background=limit_scene_stars(scene,max_stars,progress,cancel,getattr(options,'stage_progress',None))
                if limited_background is not None: background=limited_background
                path.write_text(json.dumps(scene,allow_nan=False))
        background=np.asarray(Image.open(io.BytesIO(base64.b64decode(scene['background'].split(',')[1]))),dtype=float)/255
    scene,limited_background=limit_scene_stars(scene,max_stars,progress,cancel,getattr(options,'stage_progress',None))
    if limited_background is not None: background=limited_background
    if scene.get('extraction_version',0)<4:
        progress('This cached field uses older extraction. Create a new flight to apply compact-core fitting; rendering alone does not repair old patches.')
    if options.seconds<=3 or not 0<=options.zoom<=10000:
        raise ValueError('Duration must exceed 3 seconds and zoom must be between 0 and 10000%.')
    def token(value): return format(float(value),'g').replace('.','p')
    base=f"flythrough_v{VERSION}_{mode}_{token(options.seconds)}s_zoom{token(options.zoom)}pct_24fps"
    stem=base;index=2
    while any((out/(stem+ext)).exists() for ext in ('.mp4','.html','.json')):
        stem=f'{base}_{index:02d}';index+=1
    options.result_stem=stem
    scene=dict(scene,render_version=VERSION,render_created_at=created_stamp(),render_name=stem)
    args=argparse.Namespace(seconds=options.seconds,zoom=1+options.zoom/100,travel=80,
        fps=24,video_width=1920,ease_seconds=1.5,cancel_event=cancel,progress=progress,ffmpeg=options.ffmpeg,
        frame_progress=getattr(options,'frame_progress',None))
    progress(f'Reusing prepared field: {len(scene["stars"])} stars. Creating {stem}.mp4')
    template=Path(__file__).with_name('viewer.html').read_text()
    html=template.replace('EASERAMP',str(1.5/args.seconds)).replace('DURATION',str(args.seconds*1000)).replace('MAXTRAVEL','160').replace('TRAVEL','80').replace('MAXZOOM',str(max(11,args.zoom))).replace('ZOOM',str(args.zoom)).replace('SCENE',json.dumps(scene,allow_nan=False))
    (out/(stem+'.html')).write_text(html)
    (out/(stem+'.json')).write_text(json.dumps(dict(tool_version=VERSION,created_at=scene['render_created_at'],render_name=stem,
        field_version=scene.get('prepared_with_version','unversioned'),field_created_at=scene.get('prepared_at'),date_info=scene.get('date_info'),
        extraction_version=scene.get('extraction_version'),iterative_revision=scene.get('iterative_revision'),
        calculation_path=read_project(out).get('calculation_path'),
        duration_seconds=args.seconds,fps=24,max_stars=max_stars,motion_selection=scene.get('motion_selection'),iterative_limits=scene.get('iterative_limits'),
        final_zoom=args.zoom,travel_pc=80,easing_seconds=1.5,mode=mode,matched_stars=len(scene['stars'])),indent=2))
    render_video(scene,background,args,out/(stem+'.mp4'))
    save_project(out,stage='ready',seconds=options.seconds,zoom=options.zoom,
        ffmpeg=options.ffmpeg,last_render=stem)
    progress('Complete.')
    return out

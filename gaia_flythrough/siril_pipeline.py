"""Non-UI preparation for the Siril Gaia fly-through launcher."""
import argparse
import base64
import io
import json
from pathlib import Path
import shutil
import subprocess
import threading

import numpy as np
from PIL import Image
from astropy.io import fits
from astropy.wcs import WCS
import tifffile
from flythrough import prepare, render_video
from version import VERSION, created_stamp


UNSOLVED_MESSAGE = ('This image has no valid plate solution. Run Siril_ASTAP_PlateSolve.py '
                    'or plate-solve it in Siril, then reopen Gaia Fly-through with the solved image.')


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


def run_pipeline(pixels,header,options,progress=lambda message:None,cancel=None):
    cancel=cancel or threading.Event()
    photo=normalized_pixels(pixels)
    if not has_solution(header):
        raise ValueError(UNSOLVED_MESSAGE)
    out=Path(options.output).expanduser().resolve()
    out.mkdir(parents=True,exist_ok=False)
    header=header.copy();header['ROWORDER']='BOTTOM-UP'
    if options.epoch: header['DATE-OBS']=str(options.epoch)
    fits.PrimaryHDU(photo,header).writeto(out/'source_wcs.fits')
    if options.engine=='StarXTerminator':
        starless_path=out/'starless_work.fits'
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
    if not (options.epoch or header.get('DATE-OBS')):
        raise ValueError('Observation date is missing. Enter its date in the script window and retry.')
    args=argparse.Namespace(photo=out/'photo.png',starless=out/'starless.png',wcs=out/'source_wcs.fits',
        epoch=options.epoch or None,magnitude=18,threshold=.008,match_pixels=3,max_uncertainty=.2,
        raster_bottom_up=False,travel=80,zoom=1+options.zoom/100,seconds=options.seconds,
        fps=24,video_width=1920,ease_seconds=1.5,cancel_event=cancel,progress=progress)
    progress('Matching stars to Gaia and screening distance uncertainty…')
    scene,background=prepare(args,out)
    if cancel.is_set(): raise InterruptedError('Cancelled after catalogue matching.')
    (out/'scene.json').write_text(json.dumps(scene,allow_nan=False))
    for name in ('matched_stars','rejected_blends'):
        if (out/(name+'.csv')).exists(): shutil.copyfile(out/(name+'.csv'),out/(name+'_natural.csv'))
    args.mode='dynamic'
    progress('Preparing Dynamic mode from the same images and cached Gaia data…')
    dynamic,dynamic_background=prepare(args,out)
    (out/'scene_dynamic.json').write_text(json.dumps(dynamic,allow_nan=False))
    for name in ('matched_stars','rejected_blends'):
        if (out/(name+'.csv')).exists(): shutil.copyfile(out/(name+'.csv'),out/(name+'_dynamic.csv'))
        if (out/(name+'_natural.csv')).exists(): shutil.copyfile(out/(name+'_natural.csv'),out/(name+'.csv'))
    if cancel.is_set(): raise InterruptedError('Cancelled after preparing both modes.')
    if getattr(options,'mode','natural')=='iterative':
        return render_prepared(out,options,progress,cancel)
    use_dynamic=getattr(options,'mode','natural')=='dynamic'
    return render_prepared(out,options,progress,cancel,
        dynamic if use_dynamic else scene,dynamic_background if use_dynamic else background)


def load_prepared_scene(out):
    out=Path(out)
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
    mode=getattr(options,'mode','natural')
    if mode not in ('natural','dynamic','iterative'): raise ValueError('Unknown rendering mode.')
    if scene is None:
        if mode=='iterative':
            path=out/'scene_iterative.json'
            if path.exists(): scene=json.loads(path.read_text())
            if scene is None or scene.get('iterative_revision',0)<2:
                if path.exists():
                    backup=out/'scene_iterative_before_spike_refinement.json'
                    if not backup.exists(): backup.write_text(path.read_text())
                    progress('Updating cached spike separation using the saved field.')
                natural=load_prepared_scene(out)
                if natural.get('extraction_version',0)<4:
                    raise ValueError('Create a new flight with Natural preparation before iterative refinement.')
                from iterative_deblend import refine_prepared_field
                scene,background=refine_prepared_field(natural,out,progress,cancel)
                path.write_text(json.dumps(scene,allow_nan=False))
        elif mode=='dynamic':
            path=out/'scene_dynamic.json'
            if not path.exists(): raise ValueError('Create a new flight to prepare both modes; this older cache has no Dynamic field.')
            scene=json.loads(path.read_text())
        else: scene=load_prepared_scene(out)
        background=np.asarray(Image.open(io.BytesIO(base64.b64decode(scene['background'].split(',')[1]))),dtype=float)/255
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
        fps=24,video_width=1920,ease_seconds=1.5,cancel_event=cancel,progress=progress,ffmpeg=options.ffmpeg)
    progress(f'Reusing prepared field: {len(scene["stars"])} stars. Creating {stem}.mp4')
    template=Path(__file__).with_name('viewer.html').read_text()
    html=template.replace('EASERAMP',str(1.5/args.seconds)).replace('DURATION',str(args.seconds*1000)).replace('MAXTRAVEL','160').replace('TRAVEL','80').replace('MAXZOOM',str(max(11,args.zoom))).replace('ZOOM',str(args.zoom)).replace('SCENE',json.dumps(scene,allow_nan=False))
    (out/(stem+'.html')).write_text(html)
    (out/(stem+'.json')).write_text(json.dumps(dict(tool_version=VERSION,created_at=scene['render_created_at'],render_name=stem,
        field_version=scene.get('prepared_with_version','unversioned'),field_created_at=scene.get('prepared_at'),
        extraction_version=scene.get('extraction_version'),iterative_revision=scene.get('iterative_revision'),
        duration_seconds=args.seconds,fps=24,
        final_zoom=args.zoom,travel_pc=80,easing_seconds=1.5,mode=mode,matched_stars=len(scene['stars'])),indent=2))
    render_video(scene,background,args,out/(stem+'.mp4'))
    progress('Complete.')
    return out

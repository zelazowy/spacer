"""Photo-based Gaia fly-through. See README.md."""
from version import VERSION, created_stamp
from catalog import get_catalog, check_cancel
from task_progress import StageProgress
from density import DEFAULT_MAX_STARS, MAX_MOVING_STARS, moving_star_limit
import argparse
import base64
import csv
import io
import json
from pathlib import Path
import subprocess
import time

import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.spatial import cKDTree
from scipy.optimize import least_squares
from astropy.io import fits
from astropy.coordinates import SkyCoord
from astropy.time import Time
from astropy.wcs import WCS
import astropy.units as u


def read_image(path):
    if Path(path).suffix.lower() in {'.fit', '.fits', '.fts'}:
        a = np.asarray(fits.getdata(path), dtype=float)
        if a.ndim == 3 and a.shape[0] in (1, 3):
            a = np.moveaxis(a, 0, -1)
        if a.ndim == 2:
            a = np.repeat(a[..., None], 3, axis=-1)
        if a.ndim != 3 or a.shape[-1] != 3:
            raise ValueError('Expected monochrome or RGB FITS.')
        if not np.isfinite(a).all() or a.min() < 0 or a.max() > 1:
            raise ValueError('FITS must be a finite, already stretched image in [0,1]. Use TIFF/PNG for the finished photo.')
        # FITS convention: row zero is bottom; WCS matching flips pixels below.
        return np.flipud(a).copy()
    return np.asarray(Image.open(path).convert('RGB'), dtype=float) / 255


def png_data(a):
    out = io.BytesIO()
    Image.fromarray(np.uint8(np.clip(a, 0, 1) * 255)).save(out, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode()



def number(row, key):
    try:
        return float(row[key])
    except (ValueError, KeyError, TypeError):
        return float('nan')


def fit_compact_sprite(residual,x,y,peak_tree):
    """Fit a compact stellar core over a local plane; never transport spike sectors."""
    h,w=residual.shape[:2]
    distances,_=peak_tree.query([x,y],k=2)
    separation=float(distances[1])
    max_sigma=min(3.,separation/3.)
    if max_sigma<=.8: return None
    radius=9
    sx=slice(max(0,int(x)-radius),min(w,int(x)+radius+2))
    sy=slice(max(0,int(y)-radius),min(h,int(y)+radius+2))
    patch=residual[sy,sx]
    yy,xx=np.mgrid[sy,sx];dx=xx-x;dy=yy-y
    light=patch.max(axis=2)
    core=light[dx*dx+dy*dy<4]
    if not core.size or core.max()>.75: return None
    baseline=float(np.median(light[dx*dx+dy*dy>36]))
    amplitude=max(.001,float(core.max())-baseline)
    def model(p):
        return p[0]*np.exp(-((dx-p[1])**2+(dy-p[2])**2)/(2*p[3]**2))+p[4]+p[5]*dx+p[6]*dy
    result=least_squares(lambda p:(model(p)-light).ravel(),
        [amplitude,0,0,min(1.4,max_sigma-.01),baseline,0,0],
        bounds=([0,-1.5,-1.5,.65,-1,-.1,-.1],[2,1.5,1.5,max_sigma,1,.1,.1]),
        loss='soft_l1',f_scale=.008,max_nfev=40)
    a,ox,oy,sigma,_,_,_=result.x
    if not result.success or a<.015 or sigma>=max_sigma*.98: return None
    gaussian=np.exp(-((dx-ox)**2+(dy-oy)**2)/(2*sigma*sigma))
    design=np.column_stack([gaussian.ravel(),np.ones(dx.size),dx.ravel(),dy.ravel()])
    colors=[]
    for channel in range(3):
        values=patch[:,:,channel].ravel()
        coefficients=np.linalg.lstsq(design,values,rcond=None)[0]
        for _ in range(2):
            error=np.abs(design@coefficients-values)
            weights=1/np.maximum(1,error/.008)
            coefficients=np.linalg.lstsq(design*weights[:,None],values*weights,rcond=None)[0]
        colors.append(max(0,float(coefficients[0])))
    sprite=gaussian[...,None]*np.asarray(colors)
    # Smooth model, bounded by available stellar light to preserve the initial image.
    sprite=np.minimum(sprite,patch)
    return sy,sx,sprite,sigma


def prepare(args, output):
    progress=getattr(args,'progress',None) or print
    cancel=getattr(args,'cancel_event',None)
    counter=getattr(args,'stage_progress',None)
    max_stars=moving_star_limit(getattr(args,'max_stars',DEFAULT_MAX_STARS))
    def stage(label,total=-1):
        return StageProgress(label,total,counter,progress,cancel)
    def counted(items,label):
        return stage(label,len(items)).track(items)
    stage('Loading saved image layers')
    photo, starless = read_image(args.photo), read_image(args.starless)
    if photo.shape != starless.shape:
        raise ValueError('Photo and starless image must have identical dimensions and alignment.')
    h, w = photo.shape[:2]
    header = fits.getheader(args.wcs)
    wcs = WCS(header, naxis=2).celestial
    if not wcs.has_celestial or (header.get('NAXIS1'), header.get('NAXIS2')) != (w, h):
        raise ValueError('WCS FITS must have the same dimensions and framing as the photo.')
    epoch = args.epoch or header.get('DATE-OBS')
    if not epoch:
        raise ValueError('Provide --epoch (e.g. 2026-10-12) when WCS has no DATE-OBS.')
    stage('Loading Gaia catalogue')
    rows = get_catalog(wcs,w,h,output/'catalog.csv',args.magnitude,
        progress=progress,cancel=cancel,stage_progress=counter)
    check_cancel(cancel)
    stage('Detecting star peaks')
    residual = np.maximum(photo-starless, 0)
    brightness = residual.max(axis=2)
    # Each connected island is kept intact; blends are rejected below.
    labels, count = ndimage.label(brightness > args.threshold)
    # Detect independent light peaks even when their halos are connected.
    smooth=ndimage.gaussian_filter(brightness,.8)
    peaks=(smooth==ndimage.maximum_filter(smooth,size=5))&(smooth>args.threshold*.35)
    peak_labels,_=ndimage.label(peaks)
    peak_slices=ndimage.find_objects(peak_labels)
    peak_positions=[]
    for sl in counted(peak_slices,'Locating star peaks'):
        if sl is None: continue
        yy,xx=np.unravel_index(np.argmax(smooth[sl]),smooth[sl].shape)
        peak_positions.append((xx+sl[1].start,yy+sl[0].start))
    peak_tree=cKDTree(peak_positions) if peak_positions else None
    objects = ndimage.find_objects(labels)
    # Split connected halos into separate peak-owned regions. Peaks without
    # usable catalogue distances still own pixels, so they cannot hitchhike.
    peak_islands={}
    for pi,(px,py) in enumerate(counted(peak_positions,'Identifying star groups')):
        original_label=int(labels[py,px])
        if original_label: peak_islands.setdefault(original_label,[]).append(pi)
    dynamic=getattr(args,'mode','natural')=='dynamic'
    split_count=0
    if not dynamic:
        deblended=np.zeros_like(labels)
        split_count=0
        for original_label,sl in enumerate(counted(objects,'Separating detected star groups'),1):
            if sl is None: continue
            seeds=peak_islands.get(original_label,[])
            if not seeds: continue
            island=labels[sl]==original_label
            yy,xx=np.nonzero(island)
            positions=np.column_stack([xx+sl[1].start,yy+sl[0].start])
            local_tree=cKDTree([peak_positions[pi] for pi in seeds])
            _,owners=local_tree.query(positions)
            region=deblended[sl]
            region[yy,xx]=np.asarray(seeds,dtype=np.int32)[owners]+1
            if len(seeds)>1: split_count+=1
        labels=deblended
        objects=ndimage.find_objects(labels)
    detections = []
    for label, sl in enumerate(counted(objects,'Measuring photographed stars'),1):
        if sl is None:
            continue
        mask = labels[sl] == label
        weights = brightness[sl]*mask
        if mask.sum() < 3 or weights.max() < args.threshold*3:
            continue
        # Anchor on the compact core, not a spike-weighted island centroid.
        if dynamic:
            y,x=ndimage.center_of_mass(weights)
            detections.append((x+sl[1].start,y+sl[0].start,label,sl))
        else:
            px,py=peak_positions[label-1]
            yy,xx=np.mgrid[sl[0],sl[1]]
            core=weights*((xx-px)**2+(yy-py)**2<=9)
            y,x=ndimage.center_of_mass(core)
            detections.append((x+sl[1].start,y+sl[0].start,label,sl))
    if not detections:
        raise ValueError('No stars detected; check starless alignment or lower --threshold.')
    positions_progress=stage('Calculating Gaia positions',len(rows))
    sky = SkyCoord(ra=[number(r,'ra') for r in rows]*u.deg,
        dec=[number(r,'dec') for r in rows]*u.deg,
        pm_ra_cosdec=np.nan_to_num([number(r,'pmra') for r in rows])*u.mas/u.yr,
        pm_dec=np.nan_to_num([number(r,'pmdec') for r in rows])*u.mas/u.yr,
        obstime=Time(2016.0, format='jyear'))
    sky = sky.apply_space_motion(new_obstime=Time(epoch))
    gx, gy = wcs.world_to_pixel(sky)
    if not args.raster_bottom_up:
        gy = h-1-gy
    positions_progress.update(len(rows))
    tree = cKDTree(np.array([(d[0], d[1]) for d in detections]))
    candidates = {}
    matching_progress=stage('Matching Gaia positions',len(rows))
    for i,(x,y) in enumerate(matching_progress.track(zip(gx,gy))):
        if not np.isfinite([x,y]).all():
            continue
        hits = tree.query_ball_point([x,y], args.match_pixels)
        if len(hits) == 1:
            candidates.setdefault(hits[0], []).append(i)
    eligible=[]
    for di,matches in counted(candidates.items(),'Selecting moving star candidates'):
        if len(matches)!=1: continue
        row=rows[matches[0]]
        median,lo,hi=[number(row,key) for key in ('r_med_geo','r_lo_geo','r_hi_geo')]
        ruwe=number(row,'ruwe')
        if not (0<lo<=median<=hi and (hi-lo)/(2*median)<=args.max_uncertainty and np.isfinite(ruwe) and ruwe<=1.4): continue
        eligible.append((di,matches))
    eligible_count=len(eligible)
    if eligible_count>max_stars:
        eligible.sort(key=lambda pair:(-float(brightness[int(round(detections[pair[0]][1])),int(round(detections[pair[0]][0]))]),pair[0]))
        eligible=eligible[:max_stars]
    progress(f'Gaia reference: {len(rows):,} sources; fitting up to {len(eligible):,} moving star cores (limit {max_stars:,}).')
    background = photo.copy()
    stars, report, rejected = [], [], []
    for di,matches in counted(eligible,'Fitting moving star cores'):
        row = rows[matches[0]]
        median, lo, hi = [number(row,k) for k in ('r_med_geo','r_lo_geo','r_hi_geo')]
        ruwe = number(row,'ruwe')
        x,y,label,sl = detections[di]
        if dynamic:
            sl=tuple(slice(max(0,s.start-8),min(limit,s.stop+8)) for s,limit in zip(sl,(h,w)))
            island=labels[sl]==label
            distance=ndimage.distance_transform_edt(~island)
            mask=np.clip((8-distance)/4,0,1)*((labels[sl]==0)|island)
            patch=residual[sl]*mask[...,None]
            sigma=None
        else:
            fitted=fit_compact_sprite(residual,x,y,peak_tree)
            if fitted is None:
                rejected.append(dict(source_id=row['source_id'],x=x,y=y,reason='core_fit_ambiguous_or_bright_spiked_star'))
                continue
            sy,sx,patch,sigma=fitted
            sl=(sy,sx)
        patch=np.minimum(patch,np.maximum(background[sl]-starless[sl],0))
        background[sl]-=patch
        direction=wcs.pixel_to_world(x,h-1-y if not args.raster_bottom_up else y)
        center=wcs.pixel_to_world((w-1)/2,(h-1)/2)
        depth=median*np.cos(center.separation(direction).rad)
        stars.append(dict(x=x,y=y,depth=depth,ax=x-sl[1].start,ay=y-sl[0].start,
            w=patch.shape[1],h=patch.shape[0],image=png_data(patch),source_id=row['source_id'],
            distance_pc=median,lower_pc=lo,upper_pc=hi,core_sigma=sigma))
        report.append(dict(source_id=row['source_id'],x=x,y=y,distance_pc=median,
            lower_pc=lo,upper_pc=hi,depth_pc=depth,ruwe=ruwe))
        continue
    if not stars:
        raise ValueError('No unambiguous stars with sufficiently reliable distances matched. Check orientation, WCS, epoch and alignment.')
    stage('Saving prepared star field')
    with (output/'matched_stars.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=list(report[0]));writer.writeheader();writer.writerows(report)
    with (output/'rejected_blends.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=['source_id','x','y','reason']);writer.writeheader();writer.writerows(rejected)
    print(f'{len(stars)} moving stars from {len(detections)} detected peaks; {split_count} connected islands deblended. Others remain in background.')
    return dict(width=w,height=h,background=png_data(background),stars=stars,extraction_version=4,
        prepared_with_version=VERSION,prepared_at=created_stamp(),
        motion_selection=dict(limit=max_stars,eligible_candidates=eligible_count,fitted_candidates=len(eligible),moving_stars=len(stars),method='brightest photographed peak'),
        mode='dynamic' if dynamic else 'natural',
        label=('Dynamic: Gaia-based patch depth; blended neighbours may share motion' if dynamic else 'Natural: Gaia distances; fitted cores; complex bright stars remain flat')), background


def demo():
    rng=np.random.default_rng(42)
    h,w=540,960
    yy,xx=np.mgrid[:h,:w]
    glow=np.exp(-((xx-w/2)**2/(w/6)**2+(yy-h/2)**2/(h/5)**2))
    background=np.stack([glow*.18,glow*.06,glow*.22],axis=-1)+.008
    stars=[]
    for i in range(100):
        y,x=rng.uniform(20,h-20),rng.uniform(20,w-20)
        sy,sx=np.mgrid[-7:8,-7:8]
        patch=np.exp(-(sx*sx+sy*sy)/3)[...,None]*rng.uniform(.3,1,(1,1,3))
        stars.append(dict(x=x,y=y,depth=float(rng.uniform(80,2500)),ax=7,ay=7,
            w=15,h=15,image=png_data(patch)))
    return dict(width=w,height=h,background=png_data(background),stars=stars,
        label='SYNTHETIC DEMO — invented star distances'),background


def ease_progress(t, ramp=.05):
    """Cosine velocity ramps over 5% at each end; constant speed between."""
    if t>1-ramp:
        return 1-ease_progress(1-t,ramp)
    if t<ramp:
        return (t/2-ramp/(2*np.pi)*np.sin(np.pi*t/ramp))/(1-ramp)
    return (t-ramp/2)/(1-ramp)


def sample_sprite(channels, x, y, zoom, viewport=None):
    """Place float RGB channels without snapping their position to pixels."""
    if isinstance(channels,np.ndarray):
        channels=tuple(Image.fromarray(channels[:,:,i].astype(np.float32)) for i in range(3))
    ix,iy=int(np.floor(x)),int(np.floor(y))
    ph,pw=int(np.ceil(channels[0].height*zoom))+1,int(np.ceil(channels[0].width*zoom))+1
    if viewport is not None:
        right,bottom=min(viewport[0],ix+pw),min(viewport[1],iy+ph)
        ix,iy=max(0,ix),max(0,iy)
        pw,ph=max(0,right-ix),max(0,bottom-iy)
        if not pw or not ph: return ix,iy,np.zeros((0,0,3),dtype=np.float32)
    transform=(1/zoom,0,-(x-ix)/zoom+(1/zoom-1)/2,
               0,1/zoom,-(y-iy)/zoom+(1/zoom-1)/2)
    scaled=np.stack([np.asarray(c.transform((pw,ph),Image.Transform.AFFINE,
        transform,Image.Resampling.BILINEAR)) for c in channels],axis=-1)
    return ix,iy,np.maximum(scaled,0)


def render_video(scene, background, args, path):
    frames=getattr(args,'frame_indices',range(round(args.seconds*args.fps)))
    if not hasattr(frames,'__len__'): frames=tuple(frames)
    total=len(frames);done=0
    frame_progress=getattr(args,'frame_progress',None)
    started=time.monotonic();last_update=started
    if frame_progress: frame_progress(0,total,0.)
    scale=min(1,args.video_width/scene['width'])
    w=round(scene['width']*scale);h=round(scene['height']*scale)
    video_stars=[dict(s,**{k:s[k]*scale for k in ('x','y','ax','ay','w','h')}) for s in scene['stars']]
    sprites=[]
    for s in video_stars:
        original=Image.open(io.BytesIO(base64.b64decode(s['image'].split(',')[1])))
        resized=original.resize((max(1,round(original.width*scale)),max(1,round(original.height*scale))),Image.Resampling.LANCZOS)
        patch=np.pad(np.asarray(resized,dtype=float)/255,((3,3),(3,3),(0,0)))
        s['ax']+=3;s['ay']+=3;s['w']=patch.shape[1];s['h']=patch.shape[0]
        sprites.append(tuple(Image.fromarray(patch[:,:,i].astype(np.float32)) for i in range(3)))
    cmd=[getattr(args,'ffmpeg','ffmpeg'),'-n','-loglevel','error','-f','rawvideo','-pix_fmt','rgb24','-s',f'{w}x{h}',
         '-r',str(args.fps),'-i','-','-an','-vf','pad=ceil(iw/2)*2:ceil(ih/2)*2','-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-metadata',f'comment=SPACER v{VERSION}',str(path)]
    process=subprocess.Popen(cmd,stdin=subprocess.PIPE)
    try:
        for frame in frames:
            if getattr(args,'cancel_event',None) is not None and args.cancel_event.is_set():
                raise InterruptedError('Rendering cancelled; partial outputs retained.')
            ease_seconds=getattr(args,'ease_seconds',None)
            ramp=.05 if ease_seconds is None else ease_seconds/args.seconds
            t=ease_progress(frame/max(1,round(args.seconds*args.fps)-1),ramp)
            z=1+(args.zoom-1)*t;move=args.travel*t
            offsets=[scene['height']/2*(1-1/z),scene['width']/2*(1-1/z),0]
            a=ndimage.affine_transform(background,[1/(scale*z),1/(scale*z),1],
                offset=offsets,output_shape=(h,w,3),order=1)
            for s,patch in zip(video_stars,sprites):
                if s['depth']<=move:
                    continue
                k=s['depth']/(s['depth']-move)*z
                x=w/2+(s['x']-w/2)*k-s['ax']*z;y=h/2+(s['y']-h/2)*k-s['ay']*z
                if x>=w or y>=h or x+s['w']*z<0 or y+s['h']*z<0:
                    continue
                # Continuous subpixel placement avoids the old one-pixel jumps.
                ix,iy,scaled=sample_sprite(patch,x,y,z,viewport=(w,h))
                ph,pw=scaled.shape[:2]
                xa,ya=max(0,ix),max(0,iy);xb,yb=min(w,ix+pw),min(h,iy+ph)
                if xb>xa and yb>ya:
                    a[ya:yb,xa:xb]+=scaled[ya-iy:yb-iy,xa-ix:xb-ix]
            process.stdin.write(np.uint8(np.clip(a,0,1)*255).tobytes())
            done+=1
            now=time.monotonic()
            if frame_progress and (done==1 or done==total or now-last_update>=.25):
                frame_progress(done,total,now-started);last_update=now
            if frame%120==0:
                print(f'Rendering {frame+1}/{round(args.seconds*args.fps)} frames',flush=True)
                if getattr(args,'progress',None) and not frame_progress:
                    args.progress(f'Rendering frame {frame+1}/{round(args.seconds*args.fps)}')
        if getattr(args,'progress',None): args.progress('Finalizing MP4…')
    finally:
        process.stdin.close()
        code=process.wait()
    if code:
        raise RuntimeError(f'FFmpeg exited with code {code}')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version',action='version',version=f'SPACER {VERSION}')
    p.add_argument('--photo');p.add_argument('--starless');p.add_argument('--wcs')
    p.add_argument('--epoch');p.add_argument('--demo',action='store_true')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--travel',type=float,default=30);p.add_argument('--zoom',type=float,default=1.08)
    p.add_argument('--magnitude',type=float,default=18)
    p.add_argument('--max-stars',type=int,default=DEFAULT_MAX_STARS,help=f'Maximum moving star candidates to fit (1–{MAX_MOVING_STARS}).')
    p.add_argument('--threshold',type=float,default=.008)
    p.add_argument('--match-pixels',type=float,default=3)
    p.add_argument('--max-uncertainty',type=float,default=.2)
    p.add_argument('--raster-bottom-up',action='store_true',help='Raster row zero corresponds to FITS row zero; default assumes normal top-down image.')
    p.add_argument('--mp4',action='store_true');p.add_argument('--seconds',type=float,default=12)
    p.add_argument('--fps',type=int,default=60)
    p.add_argument('--ease-seconds',type=float,help='Duration of each velocity ramp; default is 5%% of total duration.')
    p.add_argument('--video-width',type=int,default=1920,help='Maximum MP4 width; HTML retains full resolution.')
    args=p.parse_args()
    if args.ease_seconds is not None and not 0<args.ease_seconds<args.seconds/2:
        p.error('--ease-seconds must be positive and less than half the duration.')
    if not args.demo and not all([args.photo,args.starless,args.wcs]):
        p.error('Provide --photo, --starless and --wcs, or use --demo.')
    if args.travel<0 or not 1<=args.zoom<=1.5 or args.seconds<=0 or args.fps<=0 or args.threshold<=0 or args.match_pixels<=0:
        p.error('Invalid travel, zoom, duration, FPS, threshold or matching radius.')
    moving_star_limit(args.max_stars)
    args.output.mkdir(parents=True,exist_ok=True)
    if (args.output/'preview.html').exists():
        p.error('Use a new output directory to preserve existing results and catalogue cache.')
    scene,background=demo() if args.demo else prepare(args,args.output)
    scene=dict(scene,render_version=VERSION,render_created_at=created_stamp(),render_name='preview')
    template=Path(__file__).with_name('viewer.html').read_text()
    ramp=.05 if args.ease_seconds is None else args.ease_seconds/args.seconds
    html=template.replace('EASERAMP',str(ramp)).replace('DURATION',str(args.seconds*1000)).replace('MAXTRAVEL',str(max(args.travel*2,100))).replace('TRAVEL',str(args.travel)).replace('MAXZOOM',str(max(11,args.zoom))).replace('ZOOM',str(args.zoom)).replace('SCENE',json.dumps(scene,allow_nan=False))
    (args.output/'preview.html').write_text(html)
    if args.mp4:
        render_video(scene,background,args,args.output/'flight.mp4')
    print('Preview:',(args.output/'preview.html').resolve())


if __name__=='__main__':
    main()

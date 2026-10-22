"""Experimental alternating halo/spike and neighbour-core decomposition.

Models overlapping light additively. No Voronoi cut-outs are transported.
The bright-star position and each neighbour's depth remain catalogue anchored.
"""
import numpy as np
import json
from task_progress import StageProgress, Diagnostic
from density import MAX_ITERATIVE_GROUPS, MAX_GROUP_NEIGHBOURS
from distances import choose_distance, coverage_summary
import csv
import io
from version import VERSION, created_stamp
import base64
from pathlib import Path
from PIL import Image
from astropy.io import fits
from astropy.wcs import WCS
from astropy.coordinates import SkyCoord
from astropy.time import Time
import astropy.units as u
from scipy import ndimage
from scipy.optimize import nnls
from scipy.spatial import cKDTree


def measured_spikes(data,halo,center,angle,excluded,max_radius):
    """Empirical, colour-dependent spike strips with neighbour cores masked.

    Interpolate through protected cores along each arm before smoothing. This
    preserves extended chromatic structure without cutting out star sectors.
    """
    yy,xx=np.mgrid[:data.shape[0],:data.shape[1]]
    dx,dy=xx-center[0],yy-center[1]
    longitudinal=np.arange(-max_radius,max_radius+1,dtype=float)
    cross=np.arange(-12,13,dtype=float)
    along_grid,cross_grid=np.meshgrid(longitudinal,cross,indexing='ij')
    signal=np.maximum(data-halo,0)
    result=np.zeros_like(data,dtype=float)
    for a in (angle,angle+np.pi/2):
        sx=center[0]+along_grid*np.cos(a)-cross_grid*np.sin(a)
        sy=center[1]+along_grid*np.sin(a)+cross_grid*np.cos(a)
        coordinates=[sy,sx]
        protected=ndimage.map_coordinates(excluded.astype(float),coordinates,order=0,mode='constant',cval=1)>.5
        strip=np.stack([ndimage.map_coordinates(signal[:,:,c],coordinates,order=1,mode='constant') for c in range(3)],axis=-1)
        for j in range(len(cross)):
            good=~protected[:,j]
            for c in range(3):
                if good.sum()<2: strip[:,j,c]=0
                else: strip[:,j,c]=np.interp(longitudinal,longitudinal[good],strip[good,j,c],left=0,right=0)
        # Remove diffuse offsets beside the spike, not its coloured structure.
        baseline=np.median(strip[:,np.abs(cross)>=10,:],axis=1)
        strip=np.maximum(strip-baseline[:,None,:],0)
        strip=ndimage.median_filter(strip,size=(3,1,1))
        strip=ndimage.gaussian_filter(strip,sigma=(.4,.35,0))
        along=dx*np.cos(a)+dy*np.sin(a)
        across=-dx*np.sin(a)+dy*np.cos(a)
        taper=np.clip((12-np.abs(across))/3,0,1)
        for c in range(3):
            result[:,:,c]+=ndimage.map_coordinates(strip[:,:,c],[along+max_radius,across+12],order=1,mode='constant')*taper
    return result


def bright_psf(data,center,exclude,fixed_angle=None):
    h,w=data.shape[:2]
    yy,xx=np.mgrid[:h,:w];dx=xx-center[0];dy=yy-center[1]
    radius=np.hypot(dx,dy);bins=radius.astype(int)
    max_radius=int(min(center[0],center[1],w-1-center[0],h-1-center[1]))
    valid=(radius<max_radius)&~exclude
    radial=[]
    for channel in range(3):
        values=data[:,:,channel]
        profile=np.array([np.percentile(values[(bins==i)&valid],35)
            if np.any((bins==i)&valid) else np.nan for i in range(max_radius+1)])
        finite=np.isfinite(profile)
        profile=np.interp(np.arange(len(profile)),np.flatnonzero(finite),profile[finite])
        floor=np.median(profile[-max(3,max_radius//10):])
        profile=np.maximum(ndimage.gaussian_filter1d(profile,.8)-floor,0)
        profile=np.minimum.accumulate(profile)
        radial.append(np.interp(radius,np.arange(len(profile)),profile,right=0))
    halo=np.stack(radial,axis=-1)
    light=np.maximum(data-halo,0).mean(axis=2)
    rs=np.linspace(12,max_radius*.85,90)
    scores=[]
    angles=np.linspace(0,np.pi/2,180,endpoint=False)
    for angle in angles:
        rays=[]
        for j in range(4):
            a=angle+j*np.pi/2
            rays.append(ndimage.map_coordinates(light,[center[1]+rs*np.sin(a),center[0]+rs*np.cos(a)],order=1))
        scores.append(np.median(rays,axis=0).mean())
    angle=angles[int(np.argmax(scores))] if fixed_angle is None else np.radians(fixed_angle)
    basis=[]
    for a in (angle,angle+np.pi/2):
        along=dx*np.cos(a)+dy*np.sin(a)
        cross=-dx*np.sin(a)+dy*np.cos(a)
        for width in (1.,2.5):
            for length in (12.,35.,90.):
                basis.append(np.exp(-cross**2/(2*width**2))/(1+(along/length)**2))
    design=np.stack(basis,axis=-1).reshape(-1,len(basis))
    use=valid.ravel()&(radius.ravel()>3)
    target=(data-halo).reshape(-1,3)
    coefficients=[]
    for c in range(3):
        weights=np.ones(use.sum())
        for _ in range(3):
            coef=nnls(design[use]*weights[:,None],target[use,c]*weights)[0]
            error=design[use]@coef-target[use,c]
            weights=np.sqrt(1/np.maximum(1,np.abs(error)/.01))
        coefficients.append(coef)
    spikes=(design@np.stack(coefficients,axis=1)).reshape(h,w,3)
    empirical=measured_spikes(data,halo,center,angle,exclude,max_radius)
    blend=np.clip((radius-2)/4,0,1)
    blend=blend*blend*(3-2*blend)
    spikes=spikes*(1-blend[...,None])+empirical*blend[...,None]
    taper=np.clip((max_radius-radius)/(max_radius*.15),0,1)
    return np.maximum(halo+spikes,0)*taper[...,None],float(np.degrees(angle))


def consistent_spike_angle(angle,accepted_angles):
    """Use strong field consensus only; angles repeat every 90 degrees."""
    if angle is None or len(accepted_angles)<3:return True
    vectors=np.exp(4j*np.radians(accepted_angles))
    mean=vectors.mean()
    if abs(mean)<.98:return True
    reference=np.degrees(np.angle(mean))/4
    difference=abs((angle-reference+45)%90-45)
    return difference<=5


def refit_fixed_core(data,model):
    """Refit a previously admitted compact shape with a robust local plane."""
    sy,sx,patch,_=model
    h,w=patch.shape[:2];yy,xx=np.mgrid[:h,:w]
    result=np.zeros_like(patch)
    for c in range(3):
        template=patch[:,:,c]
        peak=float(template.max())
        if peak<=0:continue
        template=template/peak
        design=np.column_stack([template.ravel(),np.ones(h*w),xx.ravel()-w/2,yy.ravel()-h/2])
        target=data[sy,sx,c].ravel();weights=np.ones(h*w)
        for _ in range(3):
            coef=np.linalg.lstsq(design*weights[:,None],target*weights,rcond=None)[0]
            error=design@coef-target
            weights=np.sqrt(1/np.maximum(1,np.abs(error)/.01))
        result[:,:,c]=max(0,coef[0])*template
    return sy,sx,result,model[3]


def deblend_group(data,primary,neighbours,fit_core,iterations=8,cancel=None,stabilise=False):
    """Return per-source positive models, reconstruction and iteration metrics.

Neighbour positions are (x,y) in tile coordinates. Unmatched or uncertain
neighbours must also be supplied; their fitted light stays stationary later.
"""
    yy,xx=np.mgrid[:data.shape[0],:data.shape[1]]
    excluded=np.zeros(data.shape[:2],dtype=bool)
    for x,y in neighbours:
        excluded|=(xx-x)**2+(yy-y)**2<25
    tree=cKDTree([primary,*neighbours])
    cores=[np.zeros_like(data) for _ in neighbours]
    history=[];previous=None;fixed_angle=None;previous_main=None
    fixed_cores=[None for _ in neighbours]
    for iteration in range(iterations):
        if cancel is not None and cancel.is_set(): raise InterruptedError('Iterative separation cancelled.')
        core_sum=sum(cores,np.zeros_like(data))
        main,angle=bright_psf(np.maximum(data-core_sum,0),primary,excluded,fixed_angle=fixed_angle)
        if stabilise:
            if fixed_angle is None:fixed_angle=angle
            if previous_main is not None:main=.5*main+.5*previous_main
            previous_main=main.copy()
        for index,(x,y) in enumerate(neighbours):
            if cancel is not None and cancel.is_set(): raise InterruptedError('Iterative separation cancelled.')
            remainder=np.maximum(data-main-(core_sum-cores[index]),0)
            if stabilise and fixed_cores[index] is not None:
                fitted=refit_fixed_core(remainder,fixed_cores[index])
            else:
                fitted=fit_core(remainder,x,y,tree)
                if stabilise and fitted is not None:fixed_cores[index]=fitted
            new=np.zeros_like(data)
            if fitted is not None:
                sy,sx,patch,_=fitted;new[sy,sx]=patch
            if stabilise:new=.5*new+.5*cores[index]
            core_sum+=new-cores[index];cores[index]=new
        total=main+core_sum
        change=1. if previous is None else float(np.abs(total-previous).sum()/max(previous.sum(),1e-9))
        history.append(dict(iteration=iteration+1,relative_model_change=change,
            mean_absolute_residual=float(np.abs(data-total).mean()),spike_angle_deg=angle))
        if previous is not None and change<.001: break
        previous=total.copy()
    # Smooth model responsibilities preserve the starting photo exactly and
    # cannot subtract more light than actually exists at a given pixel/channel.
    factor=data/np.maximum(np.maximum(total,data),1e-12)
    layers=[main*factor,*[core*factor for core in cores]]
    background=data-sum(layers,np.zeros_like(data))
    return layers,background,history


def refine_prepared_field(scene,folder,progress=lambda message:None,cancel=None,stage_progress=None,report_folder=None):
    """Refine isolated catalogue-anchored bright groups in a Natural field.

    Close bright-bright overlaps and poorly fitted groups are deferred. All
    catalogue neighbours participate in light separation, even if their depth
    is too uncertain to animate. Natural and Dynamic caches stay untouched.
    """
    from flythrough import read_image,fit_compact_sprite,png_data,number
    StageProgress('Loading Iterative layers',-1,stage_progress,progress,cancel)
    folder=Path(folder)
    photo=read_image(folder/'photo.png');starless=read_image(folder/'starless.png')
    residual=np.maximum(photo-starless,0)
    h,w=photo.shape[:2]
    header=fits.getheader(folder/'source_wcs.fits');wcs=WCS(header,naxis=2).celestial
    with (folder/scene.get('motion_catalog','catalog.csv')).open() as file: rows=list(csv.DictReader(file))
    extended=scene.get('distance_coverage',{}).get('enabled',False)
    choices=[choose_distance(row,extended) for row in rows]
    positions_progress=StageProgress('Calculating Iterative catalogue positions',len(rows),stage_progress,progress,cancel)
    sky=SkyCoord(ra=[number(r,'ra') for r in rows]*u.deg,dec=[number(r,'dec') for r in rows]*u.deg,
        pm_ra_cosdec=np.nan_to_num([number(r,'pmra') for r in rows])*u.mas/u.yr,
        pm_dec=np.nan_to_num([number(r,'pmdec') for r in rows])*u.mas/u.yr,obstime=Time(2016.,format='jyear'))
    epoch=header.get('DATE-OBS')
    if not epoch:
        raise ValueError('Iterative refinement needs DATE-OBS in the saved snapshot. Create a new prepared field with the observation date.')
    sky=sky.apply_space_motion(new_obstime=Time(epoch))
    gx,gy=wcs.world_to_pixel(sky);gy=h-1-gy
    positions_progress.update(len(rows))
    def reliable(i):
        return choices[i] is not None
    candidates=[];core_flux={}
    selection=StageProgress('Selecting Iterative groups',len(rows),stage_progress,progress,cancel)
    for i,(x,y) in enumerate(selection.track(zip(gx,gy))):
        if not np.isfinite([x,y]).all() or not (170<x<w-170 and 170<y<h-170): continue
        if not reliable(i) or number(rows[i],'phot_g_mean_mag')>11: continue
        if residual[int(y)-3:int(y)+4,int(x)-3:int(x)+4].max()<.35: continue
        flux=float(residual[int(y)-8:int(y)+9,int(x)-8:int(x)+9].max(axis=2).sum())
        if flux<40: continue
        core_flux[i]=flux
        candidates.append(i)
    # Broad bright stars get priority; compact field stars must not reserve
    # analysis tiles before the halos this pass is intended to recover.
    candidates.sort(key=lambda index:core_flux[index],reverse=True)
    background=np.asarray(Image.open(io.BytesIO(base64.b64decode(scene['background'].split(',')[1]))),dtype=float)/255
    stars=list(scene['stars']);report=[];accepted_centers=[]
    optical_center=wcs.pixel_to_world((w-1)/2,(h-1)/2)
    valid=np.flatnonzero(np.isfinite(gx)&np.isfinite(gy))
    neighbour_tree=cKDTree(np.column_stack([gx[valid],gy[valid]]))
    fits_started=0;retries_started=0;accepted_angles=[]
    progress(f'Iterative limits: {MAX_ITERATIVE_GROUPS} fitted groups, {MAX_GROUP_NEIGHBOURS} neighbours per group; crowded halos stay in the photograph.')
    groups=StageProgress('Refining Iterative groups',len(candidates),stage_progress,progress,cancel)
    for step,primary_index in enumerate(groups.track(candidates)):
        if cancel is not None and cancel.is_set(): raise InterruptedError('Iterative separation cancelled.')
        x,y=float(gx[primary_index]),float(gy[primary_index]);radius=160
        source_id=rows[primary_index]['source_id']
        progress(Diagnostic(f'Iterative group {step+1}/{len(candidates)}: Gaia {source_id}'))
        close=valid[neighbour_tree.query_ball_point([x,y],5)]
        if any(j!=primary_index and np.hypot(gx[j]-x,gy[j]-y)<5 for j in close):
            report.append(dict(source_id=source_id,status='deferred_unresolved_catalogue_companion'));continue
        if any(j!=primary_index and np.hypot(gx[j]-x,gy[j]-y)<radius for j in candidates):
            report.append(dict(source_id=source_id,status='deferred_bright_bright_overlap'));continue
        if any(np.hypot(px-x,py-y)<2*radius+20 for px,py in accepted_centers):
            report.append(dict(source_id=source_id,status='deferred_overlapping_analysis_tiles'));continue
        left,top=int(x)-radius,int(y)-radius
        sy=slice(top,top+2*radius+1);sx=slice(left,left+2*radius+1)
        yy,xx=np.mgrid[sy,sx]
        weights=residual[sy,sx].max(axis=2)*np.exp(-((xx-x)**2+(yy-y)**2)/8)
        x=float((xx*weights).sum()/weights.sum());y=float((yy*weights).sum()/weights.sum())
        nearby=np.sort(valid[neighbour_tree.query_ball_point([left+radius,top+radius],np.sqrt(2)*(radius-10))])
        indices=[i for i in nearby if i!=primary_index
            and left+10<gx[i]<left+2*radius-10 and top+10<gy[i]<top+2*radius-10
            and np.hypot(gx[i]-x,gy[i]-y)>5]
        if len(indices)>MAX_GROUP_NEIGHBOURS:
            report.append(dict(source_id=source_id,status='deferred_dense_group',catalogue_neighbours=len(indices),neighbour_limit=MAX_GROUP_NEIGHBOURS));continue
        if fits_started>=MAX_ITERATIVE_GROUPS:
            report.append(dict(source_id=source_id,status='deferred_group_budget',group_limit=MAX_ITERATIVE_GROUPS));continue
        fits_started+=1
        positions=[(float(gx[i]-left),float(gy[i]-top)) for i in indices]
        layers,_,history=deblend_group(residual[sy,sx].astype(np.float32),(x-left,y-top),
            positions,fit_compact_sprite,iterations=20,cancel=cancel)
        converged=len(history)>1 and history[-1]['relative_model_change']<.001
        first_history=history;retried=False
        # Retry low-residual oscillating fits only; no looser distance,
        # ambiguity or image-residual thresholds. Bound extra work per field.
        if (not converged and len(history)>1 and history[-1]['mean_absolute_residual']<=.015
                and retries_started<4):
            retries_started+=1;retried=True
            progress(Diagnostic(f'Stabilising bright-star fit: Gaia {source_id} (retry {retries_started}/4)'))
            layers,_,history=deblend_group(residual[sy,sx].astype(np.float32),(x-left,y-top),
                positions,fit_compact_sprite,iterations=20,cancel=cancel,stabilise=True)
            converged=len(history)>1 and history[-1]['relative_model_change']<.001
        if not converged or history[-1]['mean_absolute_residual']>.015:
            report.append(dict(source_id=source_id,status='deferred_fit_not_converged',history=history,retried=retried,first_history=first_history if retried else None));continue
        angle=history[-1].get('spike_angle_deg')
        if retried and not consistent_spike_angle(angle,accepted_angles):
            report.append(dict(source_id=source_id,status='deferred_inconsistent_spike_angle',
                history=history,retried=True,first_history=first_history));continue
        ids={rows[i]['source_id'] for i in [primary_index,*indices]}
        retained=[]
        for star in stars:
            if star.get('source_id') not in ids:
                retained.append(star);continue
            patch=np.asarray(Image.open(io.BytesIO(base64.b64decode(star['image'].split(',')[1]))),dtype=float)/255
            x0=round(star['x']-star['ax']);y0=round(star['y']-star['ay'])
            background[y0:y0+star['h'],x0:x0+star['w']]+=patch
        recovered=[]
        for index,layer in zip([primary_index,*indices],layers):
            if not reliable(index) or layer.max()<.01: continue
            layer=np.minimum(layer,np.maximum(background[sy,sx]-starless[sy,sx],0))
            background[sy,sx]-=layer
            px,py=(x,y) if index==primary_index else (float(gx[index]),float(gy[index]))
            estimate=choices[index]
            d,lo,hi=[estimate[key] for key in ('distance_pc','lower_pc','upper_pc')]
            depth=d*np.cos(optical_center.separation(wcs.pixel_to_world(px,h-1-py)).rad)
            retained.append(dict(x=px,y=py,depth=float(depth),ax=px-left,ay=py-top,
                w=layer.shape[1],h=layer.shape[0],image=png_data(layer),source_id=rows[index]['source_id'],
                **estimate,iterative_group=source_id))
            recovered.append(rows[index]['source_id'])
        stars=retained;accepted_centers.append((x,y))
        if angle is not None:accepted_angles.append(angle)
        report.append(dict(source_id=source_id,status='accepted',history=history,retried=retried,first_history=first_history if retried else None,
            analysed_catalogue_sources=len(indices)+1,recovered_sources=recovered))
    StageProgress('Saving Iterative field',-1,stage_progress,progress,cancel)
    result=dict(scene,stars=stars,background=png_data(background),extraction_version=6,iterative_revision=3,prepared_with_version=VERSION,prepared_at=created_stamp(),mode='iterative',
        distance_coverage=coverage_summary(stars,extended),
        iterative_limits=dict(max_fitted_groups=MAX_ITERATIVE_GROUPS,max_neighbours=MAX_GROUP_NEIGHBOURS,fitted_groups=fits_started,stabilised_retries=retries_started,max_stabilised_retries=4),
        label='Experimental iterative halo/spike separation; uncertain bright groups remain stationary')
    if 'motion_selection' in scene:
        result['motion_selection']=dict(scene['motion_selection'],moving_stars=len(stars))
    (Path(report_folder or folder)/'iterative_report.json').write_text(json.dumps(report,indent=2))
    (Path(report_folder or folder)/'distance_coverage.json').write_text(json.dumps(result['distance_coverage'],indent=2))
    summary=result['distance_coverage']
    progress(f'Distance coverage: {len(stars):,} moving stars · {summary["approximate_stars"]:,} approximate. '+
        ', '.join(f'{source}: {count:,}' for source,count in summary['by_source'].items()))
    return result,background

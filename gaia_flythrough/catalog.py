"""Resumable Gaia/Bailer-Jones catalogue downloads for solved image footprints."""
import csv
import hashlib
import io
from pathlib import Path
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import numpy as np
from astropy.io.votable import parse_single_table
from task_progress import StageProgress

ENDPOINT='https://dc.g-vo.org/tap'
MAX_ROWS=200000
MAX_FIELD_RADIUS=5.0
COLUMNS=('source_id','ra','dec','pmra','pmdec','ruwe','phot_g_mean_mag','r_med_geo','r_lo_geo','r_hi_geo')


class CatalogOverflow(Exception):
    """The service returned only part of a region; retry smaller regions."""


def check_cancel(cancel):
    if cancel is not None and cancel.is_set(): raise InterruptedError('Catalogue download cancelled; completed regions are saved.')


def region_cone(wcs,bounds):
    x0,x1,y0,y1=bounds
    xx,yy=np.meshgrid(np.linspace(x0,x1,9),np.linspace(y0,y1,9))
    points=wcs.pixel_to_world(xx.ravel(),yy.ravel()).icrs
    center=wcs.pixel_to_world((x0+x1)/2,(y0+y1)/2).icrs
    radius=float(center.separation(points).deg.max())*1.05
    if not np.isfinite(radius) or not 0<radius<90:
        raise ValueError('Invalid or excessively distorted catalogue footprint. Check the image plate solution.')
    return float(center.ra.deg),float(center.dec.deg),radius


def validate_field(wcs,width,height):
    """Bound new preparation cost; suggest a central crop before any heavy work."""
    radius=region_cone(wcs,(0,width-1,0,height-1))[2]/1.05
    if radius>MAX_FIELD_RADIUS:
        fraction=min(.98,np.tan(np.deg2rad(MAX_FIELD_RADIUS))/np.tan(np.deg2rad(radius))*.98)
        crop_width=max(1,int(width*fraction));crop_height=max(1,int(height*fraction))
        raise ValueError(
            f'This field spans about {2*radius:.1f}° corner to corner; SPACER limits new preparation to about {2*MAX_FIELD_RADIUS:g}° '
            f'(centre-to-edge radius {MAX_FIELD_RADIUS:g}°). '
            f'Try a central crop of about {crop_width} × {crop_height} pixels or smaller, keeping the same aspect ratio. '
            'Plate-solve the cropped image and open it as a new project.')
    return radius


def split_region(bounds):
    x0,x1,y0,y1=bounds
    if x1-x0<2 or y1-y0<2:
        raise ValueError('Catalogue region cannot be split further. Check the plate solution or catalogue service.')
    xm=(x0+x1)/2;ym=(y0+y1)/2
    return [(x0,xm,y0,ym),(xm,x1,y0,ym),(x0,xm,ym,y1),(xm,x1,ym,y1)]


def plan_regions(wcs,bounds,limit=3,depth=0):
    cone=region_cone(wcs,bounds)
    if cone[2]<=limit: return [(bounds,cone)]
    if depth>=12: raise ValueError('Catalogue footprint is too distorted to subdivide safely.')
    return [item for child in split_region(bounds) for item in plan_regions(wcs,child,2.5,depth+1)]


def cone_query(cone,mag):
    ra,dec,radius=cone
    return f'''SELECT g.source_id,g.ra,g.dec,g.pmra,g.pmdec,g.ruwe,
      g.phot_g_mean_mag,d.r_med_geo,d.r_lo_geo,d.r_hi_geo
      FROM gaia.dr3lite AS g JOIN gedr3dist.main AS d USING (source_id)
      WHERE 1=CONTAINS(POINT('ICRS',g.ra,g.dec),
      CIRCLE('ICRS',{ra:.10f},{dec:.10f},{radius:.10f}))
      AND g.phot_g_mean_mag < {mag:.3f}'''


def parse_result(data):
    # CSV cannot reliably signal service-side truncation. TAP VOTables carry
    # QUERY_STATUS, including a trailing OVERFLOW after otherwise valid rows.
    root=ET.fromstring(data)
    statuses=[node for node in root.iter() if node.tag.rsplit('}',1)[-1]=='INFO' and node.get('name')=='QUERY_STATUS']
    if not statuses: raise ValueError('Catalogue response has no completion status; refusing an unverified result.')
    for node in statuses:
        status=node.get('value','').upper()
        if status=='ERROR': raise ValueError('Catalogue service: '+(node.text or 'query failed')[:500])
        if status not in ('OK','OVERFLOW'): raise ValueError('Unknown catalogue completion status: '+status)
    if any(node.get('value','').upper()=='OVERFLOW' for node in statuses): raise CatalogOverflow()
    table=parse_single_table(io.BytesIO(data)).array
    if not set(COLUMNS).issubset(table.dtype.names or ()): raise ValueError('Catalogue response is missing required columns.')
    if len(table)>=MAX_ROWS: raise CatalogOverflow()
    rows=[]
    for record in table:
        row={key:('' if np.ma.is_masked(record[key]) else str(record[key])) for key in COLUMNS}
        if not row['source_id']: raise ValueError('Catalogue response has a missing source identifier.')
        rows.append(row)
    return rows


def query_region(query,cancel=None,progress=print):
    check_cancel(cancel)
    payload=urllib.parse.urlencode(dict(REQUEST='doQuery',LANG='ADQL',QUERY=query,FORMAT='votable',MAXREC=MAX_ROWS)).encode()
    with urllib.request.urlopen(urllib.request.Request(ENDPOINT+'/async',data=payload),timeout=30) as response:
        job=response.url.rstrip('/');response.read()
    try:
        check_cancel(cancel)
        with urllib.request.urlopen(urllib.request.Request(job+'/phase',data=b'PHASE=RUN'),timeout=30) as response: response.read()
        started=time.monotonic();deadline=started+300;last_report=started
        while True:
            check_cancel(cancel)
            with urllib.request.urlopen(job+'/phase',timeout=30) as response: phase=response.read().decode().strip()
            if phase=='COMPLETED': break
            if phase in ('ERROR','ABORTED'):
                with urllib.request.urlopen(job+'/error',timeout=30) as response:
                    raise ValueError('Catalogue query failed: '+response.read().decode()[:1000])
            now=time.monotonic()
            if now-last_report>=10:
                progress(f'Gaia catalogue: waiting for region result ({now-started:.0f} s)…');last_report=now
            if now>deadline: raise TimeoutError('Gaia region query exceeded five minutes. Completed regions are saved; retry the project.')
            if cancel is None: time.sleep(2)
            elif cancel.wait(2): check_cancel(cancel)
        check_cancel(cancel)
        progress('Gaia catalogue: downloading region results…')
        with urllib.request.urlopen(job+'/results/result',timeout=120) as response:
            chunks=[];last_report=time.monotonic();received=0
            while True:
                chunk=response.read(256*1024)
                if not chunk: break
                chunks.append(chunk);received+=len(chunk);check_cancel(cancel)
                now=time.monotonic()
                if now-last_report>=10:
                    progress(f'Gaia catalogue: downloading region results ({received/1048576:.1f} MB)…');last_report=now
            data=b''.join(chunks)
        check_cancel(cancel)
        return parse_result(data)
    except (InterruptedError,TimeoutError):
        try:
            with urllib.request.urlopen(urllib.request.Request(job+'/phase',data=b'PHASE=ABORT'),timeout=10) as response: response.read()
        except OSError: pass
        raise


def write_rows(path,rows):
    temporary=path.with_suffix('.tmp')
    with temporary.open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=COLUMNS);writer.writeheader();writer.writerows(rows)
    temporary.replace(path)


def cached_rows(path):
    try:
        with path.open(newline='') as file:
            reader=csv.DictReader(file)
            if not set(COLUMNS).issubset(reader.fieldnames or ()): return None
            rows=list(reader)
        if len(rows)>=MAX_ROWS or any(not row.get('source_id') or any(row.get(key) is None for key in COLUMNS) for row in rows): return None
        return rows
    except (OSError,csv.Error): return None


def get_catalog(wcs,width,height,path,mag,progress=print,cancel=None,stage_progress=None):
    path=Path(path)
    check_cancel(cancel)
    validate_field(wcs,width,height)
    # Historical project catalogues remain authoritative, as before.
    if path.exists():
        with path.open() as file: return list(csv.DictReader(file))
    if not np.isfinite(mag): raise ValueError('Catalogue magnitude must be finite.')
    regions=plan_regions(wcs,(0,width-1,0,height-1))
    cache=path.parent/(path.stem+'-parts');cache.mkdir(exist_ok=True)
    counter=StageProgress('Downloading Gaia regions',len(regions),stage_progress,progress,cancel)
    progress(f'Downloading Gaia catalogue: {len(regions)} sky region(s). Completed regions are reused on retry.')
    rows={};completed=0
    def fetch(bounds,cone,depth=0):
        nonlocal completed
        check_cancel(cancel)
        query=cone_query(cone,mag)
        key=hashlib.sha256(('v1:'+ENDPOINT+':'+str(MAX_ROWS)+':'+query).encode()).hexdigest()
        part=cache/(key+'.csv');split=cache/(key+'.split')
        result=cached_rows(part) if part.exists() else None
        if result is None and not split.exists():
            try:
                # Region counts do not describe progress inside a remote job.
                StageProgress('Waiting for Gaia region result',-1,stage_progress,cancel=cancel)
                result=query_region(query,cancel,progress)
                check_cancel(cancel)
                write_rows(part,result)
            except CatalogOverflow:
                split.write_text('Service row limit reached; use subregions.\n')
        if result is None:
            if depth>=12: raise ValueError('Catalogue remains too dense after subdivision; no incomplete result has been saved.')
            counter.set_total(counter.total+3)
            progress('Dense catalogue region; downloading smaller areas without dropping faint stars…')
            for child in split_region(bounds): fetch(child,region_cone(wcs,child),depth+1)
            return
        for row in result: rows.setdefault(row['source_id'],row)
        # Restore region counts even when a fast request beats the throttle.
        completed+=1;counter.update(completed,force=True)
        progress(f'Gaia catalogue: {completed} region(s) ready · {len(rows):,} unique stars.')
    for bounds,cone in regions: fetch(bounds,cone)
    check_cancel(cancel)
    if not rows: raise ValueError('Catalogue query returned no usable stars in this field.')
    result=list(rows.values());write_rows(path,result)
    progress(f'Gaia catalogue saved: {len(result):,} unique stars. Matching to the photograph…')
    return result

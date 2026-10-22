"""Optional SIMBAD object/distance discovery; WCS inclusion is not pixel detection."""
import json
import math
import urllib.parse
import urllib.request
import numpy as np
from astropy.wcs import WCS

ENDPOINT='https://simbad.cds.unistra.fr/simbad/sim-tap/sync'
LIMIT=2000
MAX_OBJECTS=100
MAX_DISTANCE_PAGES=10

def field_query(header):
    wcs=WCS(header,naxis=2).celestial
    width,height=int(header['NAXIS1']),int(header['NAXIS2'])
    center=wcs.pixel_to_world((width-1)/2,(height-1)/2)
    # Sample boundaries to account for SIP distortions.
    edge=np.linspace(0,1,33)
    x=np.r_[edge*(width-1),edge*(width-1),np.zeros(33),np.full(33,width-1)]
    y=np.r_[np.zeros(33),np.full(33,height-1),edge*(height-1),edge*(height-1)]
    radius=float(center.separation(wcs.pixel_to_world(x,y)).deg.max())*1.01
    if not math.isfinite(radius) or not 0<radius<=6:
        raise ValueError('Target lookup needs a valid solved field within 6° radius.')
    query=f"""SELECT TOP {MAX_OBJECTS} b.oid,b.main_id,b.otype,b.ra,b.dec,b.nbref
FROM basic AS b
WHERE 1=CONTAINS(POINT('ICRS',b.ra,b.dec),CIRCLE('ICRS',{center.ra.deg:.10f},{center.dec.deg:.10f},{radius:.10f}))
AND (b.otype IN ('G','Cl*','OpC','GlC','Neb','RNe','HII','SNR','PN','GNe','DNe','As*','GCl','GrG')
OR b.otype IN (SELECT otype FROM otypedef WHERE path LIKE 'G > %' OR path LIKE 'Cl* > %'))
ORDER BY nbref DESC, oid"""
    return query,wcs,width,height

def in_field(wcs,width,height,ra,dec):
    x,y=wcs.world_to_pixel_values(float(ra),float(dec))
    return bool(np.isfinite([x,y]).all() and 0<=x<width and 0<=y<height)


def parse_targets(payload,wcs,width,height):
    names=[m['name'].lower() for m in payload['metadata']]
    rows=payload['data']
    result=[];seen=set()
    def error(value,factor):
        if value is None or not factor:return None
        number=abs(float(value)*factor)
        return number if math.isfinite(number) else None
    for values in rows:
        row=dict(zip(names,values))
        x,y=wcs.world_to_pixel_values(float(row['ra']),float(row['dec']))
        if not np.isfinite([x,y]).all() or not (0<=x<width and 0<=y<height): continue
        unit=str(row.get('unit') or '').strip()
        factor={'pc':1,'kpc':1000,'Mpc':1000000}.get(unit)
        distance=row.get('dist')
        distance=float(distance)*factor if distance is not None and factor else None
        if distance is not None and (not math.isfinite(distance) or distance<=0): distance=None
        entry=dict(name=row['main_id'].strip(),object_type=row['otype'],ra_deg=row['ra'],dec_deg=row['dec'],
            distance_pc=distance,method=row.get('method'),bibcode=row.get('bibcode'),quality=row.get('qual'),
            minus_error_pc=error(row.get('minus_err'),factor),
            plus_error_pc=error(row.get('plus_err'),factor),
            source='SIMBAD mesDistance',endpoint=ENDPOINT)
        key=(entry['name'],distance,entry['bibcode'],entry['method'])
        if key not in seen: result.append(entry);seen.add(key)
    return result

def tap_rows(query,maxrec):
    data=urllib.parse.urlencode(dict(REQUEST='doQuery',LANG='ADQL',FORMAT='json',QUERY=query,MAXREC=maxrec)).encode()
    with urllib.request.urlopen(urllib.request.Request(ENDPOINT,data=data),timeout=30) as response:
        payload=json.load(response)
    names=[column['name'].lower() for column in payload['metadata']]
    return [dict(zip(names,row)) for row in payload['data']]


def find_targets(header):
    query,wcs,width,height=field_query(header)
    objects=tap_rows(query,MAX_OBJECTS)
    # Restrict objects before fetching their (potentially numerous) papers.
    objects=[row for row in objects if in_field(wcs,width,height,row['ra'],row['dec'])]
    if not objects:return []
    ids=','.join(str(int(row['oid'])) for row in objects)
    measurements={int(row['oid']):[] for row in objects}
    cursor=None
    for _ in range(MAX_DISTANCE_PAGES):
        after='' if cursor is None else f' AND (oidref>{cursor[0]} OR (oidref={cursor[0]} AND mespos>{cursor[1]}))'
        query=f"""SELECT TOP {LIMIT+1} oidref,mespos,dist,unit,minus_err,plus_err,method,bibcode,qual
FROM mesDistance WHERE oidref IN ({ids}){after} ORDER BY oidref, mespos"""
        page=tap_rows(query,LIMIT+1)
        for row in page[:LIMIT]:measurements[int(row['oidref'])].append(row)
        if len(page)<=LIMIT:break
        next_cursor=(int(page[LIMIT-1]['oidref']),int(page[LIMIT-1]['mespos']))
        if cursor is not None and next_cursor<=cursor:
            raise ValueError('Distance lookup did not advance. Please retry.')
        cursor=next_cursor
    else:
        raise ValueError('Distance lookup exceeded its request budget. Please retry later or enter a distance manually.')
    combined=[]
    for obj in objects:
        for measurement in measurements[int(obj['oid'])] or [{}]:
            combined.append(dict(obj,**{key:value for key,value in measurement.items() if key not in obj}))
    names=['main_id','otype','ra','dec','dist','unit','minus_err','plus_err','method','bibcode','qual']
    payload=dict(metadata=[dict(name=n) for n in names],data=[[r.get(n) for n in names] for r in combined])
    return parse_targets(payload,wcs,width,height)

def approximate_targets(measurements):
    """One practical distance per object, not a combined scientific estimate."""
    from statistics import median
    groups={}
    for row in measurements:groups.setdefault(row['name'],[]).append(row)
    result=[]
    for name,rows in groups.items():
        distances=[r['distance_pc'] for r in rows if r.get('distance_pc') is not None]
        value=float(format(median(distances),'.2g')) if distances else None
        result.append(dict(rows[0],distance_pc=value,approximate=True,bibcode=None,method='approximate catalogue summary',quality=None,minus_error_pc=None,plus_error_pc=None,
            distance_summary='Median of available published estimates, rounded to two significant figures',
            measurement_count=len(distances),measurements=rows,
            distance_range_pc=[min(distances),max(distances)] if distances else None))
    return result


def approximate_distance_label(distance):
    if distance is None:return 'distance unavailable — enter manually'
    factor,unit=(1e6,'Mpc') if distance>=1e6 else ((1e3,'kpc') if distance>=1e3 else (1,'pc'))
    return f'about {float(format(distance/factor, ".2g")):g} {unit}'

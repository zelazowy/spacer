"""Optional SIMBAD object/distance discovery; WCS inclusion is not pixel detection."""
import json
import math
import urllib.parse
import urllib.request
import numpy as np
from astropy.wcs import WCS

ENDPOINT='https://simbad.cds.unistra.fr/simbad/sim-tap/sync'
LIMIT=2000

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
    query=f"""SELECT TOP {LIMIT+1} b.main_id,b.otype,b.ra,b.dec,b.nbref,d.dist,d.unit,d.minus_err,d.plus_err,d.method,d.bibcode,d.qual
FROM basic AS b LEFT JOIN mesDistance AS d ON b.oid=d.oidref
WHERE 1=CONTAINS(POINT('ICRS',b.ra,b.dec),CIRCLE('ICRS',{center.ra.deg:.10f},{center.dec.deg:.10f},{radius:.10f}))
AND b.otype IN ('G','Cl*','OpC','GlC','Neb','RNe','HII','SNR','PN','GNe','DNe','As*','GCl','GrG')
ORDER BY nbref DESC"""
    return query,wcs,width,height

def parse_targets(payload,wcs,width,height):
    names=[m['name'].lower() for m in payload['metadata']]
    rows=payload['data']
    if len(rows)>LIMIT:
        raise ValueError('Too many target measurements. Use a smaller field for a complete list.')
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

def find_targets(header):
    query,wcs,width,height=field_query(header)
    data=urllib.parse.urlencode(dict(REQUEST='doQuery',LANG='ADQL',FORMAT='json',QUERY=query,MAXREC=LIMIT+1)).encode()
    with urllib.request.urlopen(urllib.request.Request(ENDPOINT,data=data),timeout=30) as response:
        payload=json.load(response)
    return parse_targets(payload,wcs,width,height)

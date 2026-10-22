"""Optional extended distance coverage, with explicit per-star provenance."""
from collections import Counter
import csv
from pathlib import Path
import urllib.parse
import urllib.request
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.time import Time
import astropy.units as u
from scipy.spatial import cKDTree
from catalog import COLUMNS, get_catalog, cone_query, parse_result, write_rows, check_cancel, region_cone

HIP_ENDPOINT='https://heasarc.gsfc.nasa.gov/xamin/vo/tap/sync'
HIP_FIELDS=('hip_number','ra','dec','pm_ra','pm_dec','parallax','parallax_error','hip_mag','new_solution_type','number_components','quality_fit')


def number(row,key):
    try:return float(row.get(key,''))
    except (TypeError,ValueError):return float('nan')


def interval(d,lo,hi,limit):
    return bool(np.isfinite([d,lo,hi]).all() and 0<lo<=d<=hi and (hi-lo)/(2*d)<=limit)


def choose_distance(row,extended=False,strict_limit=.2):
    def result(d,lo,hi,source,approximate):
        return dict(distance_pc=float(d),lower_pc=float(lo),upper_pc=float(hi),
            distance_source=source,distance_approximate=bool(approximate),
            distance_catalogue_id=('HIP:'+str(row.get('hip_id','')) if source=='Hipparcos-2' else str(row.get('source_id',''))))
    d,lo,hi=[number(row,k) for k in ('r_med_geo','r_lo_geo','r_hi_geo')]
    gaia_ok=np.isfinite(number(row,'ruwe')) and number(row,'ruwe')<=1.4
    if gaia_ok and interval(d,lo,hi,strict_limit):
        return result(d,lo,hi,'Gaia geometric',False)
    if not extended:return None
    p,e=number(row,'hip_parallax'),number(row,'hip_parallax_error')
    if (np.isfinite([p,e,number(row,'hip_quality_fit')]).all() and p>0 and 0<e/p<=.2
            and number(row,'hip_solution_type')==5 and number(row,'hip_components')==1
            and number(row,'hip_quality_fit')<=3):
        return result(1000/p,1000/(p+e),1000/(p-e),'Hipparcos-2',True)
    if not gaia_ok:return None
    pd,pl,ph=[number(row,k) for k in ('r_med_photogeo','r_lo_photogeo','r_hi_photogeo')]
    if interval(pd,pl,ph,.5):return result(pd,pl,ph,'Gaia photogeometric',True)
    if interval(d,lo,hi,.5):return result(d,lo,hi,'Gaia geometric (extended)',True)
    return None


def extended_query(cone,mag):
    return cone_query(cone,mag).replace('d.r_hi_geo','d.r_hi_geo,d.r_med_photogeo,d.r_lo_photogeo,d.r_hi_photogeo,d.flag').replace(' JOIN gedr3dist',' LEFT JOIN gedr3dist')


def hipparcos_rows(wcs,width,height,root,epoch,cancel=None,progress=print):
    path=Path(root)/'catalog-hipparcos2.csv'
    if path.exists():
        with path.open() as file:return list(csv.DictReader(file))
    ra,dec,radius=region_cone(wcs,(0,width-1,0,height-1))
    # Cover proper-motion drift from the old catalogue epoch even at field edges.
    radius+=max(.5,abs(Time(epoch).jyear-1991.25)*15/3600)
    query=f"""SELECT TOP 10001 {','.join(HIP_FIELDS)} FROM hipnewcat
WHERE 1=CONTAINS(POINT('ICRS',ra,dec),CIRCLE('ICRS',{ra:.10f},{dec:.10f},{radius:.10f}))
AND parallax>0 AND parallax_error>0 AND parallax_error/parallax<=0.2
AND new_solution_type=5 AND number_components=1 AND quality_fit<=3"""
    progress('Downloading Hipparcos-2 bright-star fallback…');check_cancel(cancel)
    data=urllib.parse.urlencode(dict(REQUEST='doQuery',LANG='ADQL',FORMAT='votable',QUERY=query,MAXREC=10001)).encode()
    with urllib.request.urlopen(urllib.request.Request(HIP_ENDPOINT,data=data),timeout=30) as response:
        data=response.read()
    check_cancel(cancel)
    raw=parse_result(data,required=HIP_FIELDS)
    if len(raw)>=10000:raise ValueError('Hipparcos query exceeded its bounded field size.')
    rows=[]
    if raw:
        sky=SkyCoord(ra=[number(r,'ra') for r in raw]*u.deg,dec=[number(r,'dec') for r in raw]*u.deg,
            pm_ra_cosdec=[number(r,'pm_ra') for r in raw]*u.mas/u.yr,
            pm_dec=[number(r,'pm_dec') for r in raw]*u.mas/u.yr,
            obstime=Time(1991.25,format='jyear')).apply_space_motion(new_obstime=Time(2016,format='jyear'))
        for r,pos in zip(raw,sky):
            row={key:'' for key in COLUMNS}
            row.update(source_id='HIP:'+str(int(number(r,'hip_number'))),ra=pos.ra.deg,dec=pos.dec.deg,
                pmra=pos.pm_ra_cosdec.to_value(u.mas/u.yr),pmdec=pos.pm_dec.to_value(u.mas/u.yr),
                phot_g_mean_mag=r['hip_mag'],hip_id=r['hip_number'],hip_parallax=r['parallax'],
                hip_parallax_error=r['parallax_error'],hip_solution_type=r['new_solution_type'],
                hip_components=r['number_components'],hip_quality_fit=r['quality_fit'],position_source='Hipparcos-2')
            rows.append(row)
    write_rows(path,rows)
    return rows


def merge_hipparcos(gaia,hip):
    rows=[dict(row) for row in gaia]
    if not rows:return [dict(row) for row in hip],dict(added=len(hip),matched=0,ambiguous=0)
    valid=[i for i,r in enumerate(rows) if np.isfinite([number(r,'ra'),number(r,'dec')]).all()]
    sky=SkyCoord(ra=[number(rows[i],'ra') for i in valid]*u.deg,dec=[number(rows[i],'dec') for i in valid]*u.deg)
    tree=cKDTree(sky.cartesian.xyz.value.T);stats=dict(added=0,matched=0,ambiguous=0)
    claimed=set()
    for h in hip:
        if not np.isfinite([number(h,'ra'),number(h,'dec')]).all():continue
        pos=SkyCoord(number(h,'ra')*u.deg,number(h,'dec')*u.deg)
        hits=tree.query_ball_point(pos.cartesian.xyz.value,2*np.sin(np.deg2rad(3/3600)/2))
        if not hits:rows.append(dict(h));stats['added']+=1;continue
        if len(hits)!=1:
            stats['ambiguous']+=1;continue
        i=valid[hits[0]]
        separation=pos.separation(sky[hits[0]]).arcsec
        if separation>1 or i in claimed:
            stats['ambiguous']+=1;continue
        claimed.add(i);stats['matched']+=1
        if choose_distance(rows[i],False) is not None:continue
        rows[i].update({k:v for k,v in h.items() if k.startswith('hip_')})
        if choose_distance(rows[i],True) and choose_distance(rows[i],True)['distance_source']=='Hipparcos-2':
            rows[i].update({key:h[key] for key in ('ra','dec','pmra','pmdec')})
            rows[i]['position_source']='Hipparcos-2'
    return rows,stats


def motion_catalog(wcs,width,height,root,mag,epoch,cancel=None,progress=print,stage_progress=None):
    root=Path(root)
    gaia=get_catalog(wcs,width,height,root/'catalog-extended.csv',mag,progress,cancel,stage_progress,query_builder=extended_query)
    if not gaia or not all('r_med_photogeo' in row for row in gaia):
        raise ValueError('Extended catalogue cache lacks photogeometric fields. Remove only catalog-extended.csv and retry.')
    hip=hipparcos_rows(wcs,width,height,root,epoch,cancel,progress)
    rows,stats=merge_hipparcos(gaia,hip);check_cancel(cancel)
    write_rows(root/'catalog-motion.csv',rows)
    progress(f'Extended reference: {len(rows):,} sources; Hipparcos-2 added {stats["added"]}, cross-matched {stats["matched"]}, ambiguous {stats["ambiguous"]}.')
    return rows


def coverage_summary(stars,enabled):
    methods=Counter(s.get('distance_source','Gaia geometric') for s in stars)
    return dict(enabled=bool(enabled),by_source=dict(methods),
        moving_stars=len(stars),approximate_stars=sum(bool(s.get('distance_approximate',False)) for s in stars))

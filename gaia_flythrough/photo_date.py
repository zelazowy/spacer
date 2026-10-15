"""Best available matching epoch, with its source and approximation explicit."""
from datetime import datetime, timezone
from pathlib import Path
import re
from astropy.time import Time
from PIL import Image


def date_info(value,source,approximate=False):
    """Accept full dates, EXIF timestamps, or a user's approximate capture year."""
    text=str(value).strip().strip('\x00')
    if re.fullmatch(r'\d{4}',text):
        text+='-07-01';approximate=True
    elif re.fullmatch(r'\d{4}-\d{2}',text):
        text+='-15';approximate=True
    if re.match(r'^\d{4}:\d{2}:\d{2}',text):
        text=text[:10].replace(':','-')+text[10:]
    try:
        # datetime supports EXIF's optional UTC offset; FITS can also carry leap seconds.
        try: value=Time(datetime.fromisoformat(text.replace('Z','+00:00')))
        except ValueError: value=Time(text)
        if not value.isscalar: return None
        value=str(value.utc.isot)
    except (ValueError,TypeError,OverflowError): return None
    return dict(value=value,source=source,approximate=bool(approximate))


def infer_photo_date(path,header=None,reference=None):
    path=Path(path)
    def header_capture(header,label):
        if header is None: return None
        for key in ('DATE-OBS','DATE-AVG'):
            if header.get(key):
                result=date_info(header[key],header.get('DATESRC',label+' '+key),header.get('DATEAPPX',False))
                if result: return result
        for key,fmt in (('MJD-OBS','mjd'),('JD','jd')):
            if header.get(key) is not None:
                try: result=date_info(Time(float(header[key]),format=fmt).isot,label+' '+key)
                except (ValueError,TypeError,OverflowError): continue
                if result: return result
        return None
    result=header_capture(header,'Image header')
    if result: return result
    exif={};tags={};png={}
    try:
        with Image.open(path) as image:
            exif=dict(image.getexif())
            try: exif.update(image.getexif().get_ifd(34665))
            except (KeyError,ValueError,TypeError): pass
            tags=dict(getattr(image,'tag_v2',{}));png=dict(image.info)
    except (OSError,ValueError,SyntaxError): pass
    for key,label in ((36867,'EXIF capture date'),(36868,'EXIF digitized date')):
        if exif.get(key):
            offset=exif.get(36881 if key==36867 else 36882,'')
            result=date_info(str(exif[key])+str(offset),label,key==36868)
            if result: return result
    result=header_capture(reference,'WCS reference')
    if result: return result
    candidates=[(exif.get(306),'EXIF file date'),(tags.get(306),'TIFF file date')]
    if header is not None: candidates.append((header.get('DATE'),'Image header file date'))
    for key in ('Creation Time','creation_time','date:create','DateTime','date:modify'):
        candidates.append((png.get(key),'Image metadata '+key))
    for value,label in candidates:
        if value:
            result=date_info(value,label,True)
            if result: return result
    try:
        if not path.is_file(): return None
        stat=path.stat()
        for value,label in ((getattr(stat,'st_birthtime',None),'File creation date'),(stat.st_mtime,'File modification date')):
            if value is not None:
                result=date_info(datetime.fromtimestamp(value,timezone.utc).isoformat(),label,True)
                if result: return result
    except (OSError,ValueError,OverflowError): pass
    return None


def stamp_date(header,info):
    if info:
        header['DATE-OBS']=info['value']
        header['DATEAPPX']=(info['approximate'],'SPACER matching date is approximate')
        header['DATESRC']=(info['source'],'Origin of SPACER matching date')

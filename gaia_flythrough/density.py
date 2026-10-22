"""Bound expensive animation work while retaining complete ambiguity references."""
import base64
import io
import numpy as np
from PIL import Image
from task_progress import StageProgress

DEFAULT_MAX_STARS=50000
MAX_MOVING_STARS=50000
MAX_ITERATIVE_GROUPS=16
MAX_GROUP_NEIGHBOURS=96


def moving_star_limit(value=DEFAULT_MAX_STARS):
    message=f'Moving star limit must be an integer from 1 to {MAX_MOVING_STARS}.'
    try: limit=int(value)
    except (ValueError,TypeError,OverflowError): raise ValueError(message)
    if limit!=value or not 1<=limit<=MAX_MOVING_STARS: raise ValueError(message)
    return limit


def decode_layer(value):
    with Image.open(io.BytesIO(base64.b64decode(value.split(',',1)[1]))) as image:
        return np.asarray(image.convert('RGB')).copy()


def limit_scene_stars(scene,limit=DEFAULT_MAX_STARS,progress=lambda message:None,cancel=None,stage_progress=None):
    """Make a bounded render view; restore excluded sprites to the flat photo.

    Do not rewrite the saved analysis. Integer PNG light is added exactly, so
    the starting reconstruction stays unchanged, including overlapping sprites.
    """
    limit=moving_star_limit(limit);stars=scene['stars']
    if len(stars)<=limit: return scene,None
    counter=StageProgress('Selecting moving stars',len(stars),stage_progress,progress,cancel)
    scores=[]
    for index,star in enumerate(counter.track(stars)):
        scores.append((int(decode_layer(star['image']).sum(dtype=np.uint64)),index))
    selected={index for _,index in sorted(scores,key=lambda pair:(-pair[0],pair[1]))[:limit]}
    background=decode_layer(scene['background']).astype(np.uint32)
    height,width=background.shape[:2]
    excluded=[(i,star) for i,star in enumerate(stars) if i not in selected]
    counter=StageProgress('Keeping unselected stars stationary',len(excluded),stage_progress,progress,cancel)
    for _,star in counter.track(excluded):
        patch=decode_layer(star['image']);ph,pw=patch.shape[:2]
        x0=round(star['x']-star['ax']);y0=round(star['y']-star['ay'])
        if abs(star['x']-star['ax']-x0)>1e-5 or abs(star['y']-star['ay']-y0)>1e-5:
            raise ValueError('This legacy scene has fractional sprite origins; use a new project to apply the star limit safely.')
        xa,xb=max(0,x0),min(width,x0+pw);ya,yb=max(0,y0),min(height,y0+ph)
        if xb>xa and yb>ya: background[ya:yb,xa:xb]+=patch[ya-y0:yb-y0,xa-x0:xb-x0].astype(np.uint32)
    background=np.minimum(background,255).astype(np.uint8)
    output=io.BytesIO();Image.fromarray(background).save(output,format='PNG')
    result=dict(scene,stars=[star for i,star in enumerate(stars) if i in selected],
        background='data:image/png;base64,'+base64.b64encode(output.getvalue()).decode(),
        motion_selection=dict(limit=limit,source_stars=len(stars),moving_stars=limit,method='brightest photographed sprite flux'))
    if 'distance_coverage' in scene:
        from distances import coverage_summary
        result['distance_coverage']=coverage_summary(result['stars'],scene['distance_coverage']['enabled'])
    progress(f'Moving stars limited to {limit:,} of {len(stars):,}; the remainder stay in the photograph.')
    return result,background.astype(float)/255

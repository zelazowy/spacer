"""Disk image input in the pipeline's channel-first, bottom-up convention."""
from pathlib import Path
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
import tifffile
from PIL import Image, ImageOps
from siril_pipeline import normalized_pixels, has_solution
from photo_date import infer_photo_date

FITS_SUFFIXES={'.fits','.fit','.fts'}


def description_header(description):
    """FITS cards saved by Siril in an image's description (TIFF or JPEG EXIF)."""
    if isinstance(description,bytes): description=description.decode('ascii',errors='replace')
    if not isinstance(description,str): return None
    description=description.rstrip('\x00').strip()
    lines=description.splitlines()
    if not description.startswith('SIMPLE') or not lines or lines[-1].strip()!='END': return None
    try: return fits.Header.fromstring('\n'.join(line.ljust(80) for line in lines),sep='\n')
    except (ValueError,TypeError): return None


def jpeg_header(path):
    """Reuse embedded WCS only when its dimensions and orientation still match."""
    with Image.open(path) as image:
        exif=image.getexif();header=description_header(exif.get(270))
        if header is None or exif.get(274,1)!=1: return None
        if (header.get('NAXIS1'),header.get('NAXIS2'))!=image.size: return None
        if has_solution(header):
            wcs=WCS(header,naxis=2)
            scale=wcs.pixel_scale_matrix
            if not np.isfinite(scale).all() or abs(np.linalg.det(scale))<1e-15: return None
            if not np.isfinite(wcs.all_pix2world([[0,0],[image.width-1,image.height-1]],0)).all(): return None
        return header


def tiff_header(path):
    """Read Astro-TIFF tag 270; TIFF dimensions lead over redundant FITS cards."""
    with tifffile.TiffFile(path) as image:
        if len(image.pages)!=1:
            raise ValueError('Choose a single TIFF image, not a multipage sequence.')
        page=image.pages[0]
        description=(page.description or '').rstrip('\x00').strip()
        orientation=int(page.tags['Orientation'].value) if 'Orientation' in page.tags else 1
        if orientation not in (1,2,3,4):
            raise ValueError('Rotated TIFF orientation is unsupported. Export a top-left oriented image.')
        header=description_header(description)
        if header is not None:
            header['NAXIS1']=page.imagewidth;header['NAXIS2']=page.imagelength
        return header,orientation


class FileImageSource:
    def __init__(self,path,wcs_path=None):
        self.path=Path(path).expanduser().resolve()
        if not self.path.is_file(): raise ValueError(f'Image does not exist: {self.path}')
        self.is_fits=self.path.suffix.lower() in FITS_SUFFIXES
        if not self.is_fits and self.path.suffix.lower() not in {'.tif','.tiff','.png','.jpg','.jpeg'}:
            raise ValueError('Choose a FITS, TIFF, PNG or JPEG image.')
        self.wcs_path=Path(wcs_path).expanduser().resolve() if wcs_path else None
        self.native_header=fits.getheader(self.path) if self.is_fits else None
        self.embedded_header=None;self.tiff_orientation=1
        if self.path.suffix.lower() in {'.tif','.tiff'}:
            self.embedded_header,self.tiff_orientation=tiff_header(self.path)
        elif self.path.suffix.lower() in {'.jpg','.jpeg'}:
            self.embedded_header=jpeg_header(self.path)

    @property
    def has_coordinates(self):
        return has_solution(self.header(require_solution=False))

    def header(self,require_solution=True):
        header=(fits.getheader(self.wcs_path) if self.wcs_path else
            (self.native_header if self.native_header is not None else self.embedded_header))
        header=header.copy() if header is not None else fits.Header()
        if require_solution and not has_solution(header):
            raise ValueError('This image has no embedded plate solution. Solve sky position with ASTAP or choose a solved FITS reference.')
        return header

    def date_info(self):
        header=self.native_header if self.native_header is not None else self.embedded_header
        reference=fits.getheader(self.wcs_path) if self.wcs_path else None
        return infer_photo_date(self.path,header,reference)

    def snapshot(self,allow_unsolved=False):
        header=self.header(require_solution=not allow_unsolved)
        if self.is_fits:
            pixels=normalized_pixels(fits.getdata(self.path))
            if 'TOP-DOWN' in str(self.native_header.get('ROWORDER','')):
                pixels=np.flip(pixels,axis=-2)
        else:
            if self.path.suffix.lower() in {'.tif','.tiff'}:
                try: raster=tifffile.imread(self.path)
                except ValueError as exc:
                    if 'imagecodecs' in str(exc):
                        raise ValueError('This TIFF needs an optional codec. Export an uncompressed TIFF, FITS or PNG and try again.') from exc
                    raise
            else:
                with Image.open(self.path) as image:
                    # Apply JPEG EXIF rotation once, before solving that same pixel frame.
                    raster=np.asarray(ImageOps.exif_transpose(image)).copy()
            if raster.ndim==2: raster=raster[None,:,:]
            elif raster.ndim==3 and raster.shape[-1] in (1,3): raster=np.moveaxis(raster,-1,0)
            else: raise ValueError('Choose a monochrome or RGB image, without alpha or multiple pages.')
            pixels=normalized_pixels(raster)
            # TIFF Orientation, not embedded ROWORDER, describes raster storage.
            # The embedded FITS/WCS cards remain in their original sky frame.
            if self.tiff_orientation in (1,2): pixels=np.flip(pixels,axis=-2)
            if self.tiff_orientation in (2,3): pixels=np.flip(pixels,axis=-1)
        if self.wcs_path and (header.get('NAXIS1'),header.get('NAXIS2'))!=(pixels.shape[2],pixels.shape[1]):
            raise ValueError('The solved FITS must have exactly the same dimensions and framing as the image.')
        header=header.copy();header['NAXIS1']=pixels.shape[2];header['NAXIS2']=pixels.shape[1];header['ROWORDER']='BOTTOM-UP'
        return pixels.copy(),header

"""Disk image input in the pipeline's channel-first, bottom-up convention."""
from pathlib import Path
import numpy as np
from astropy.io import fits
import tifffile
from PIL import Image
from siril_pipeline import normalized_pixels, has_solution

FITS_SUFFIXES={'.fits','.fit','.fts'}


class FileImageSource:
    def __init__(self,path,wcs_path=None):
        self.path=Path(path).expanduser().resolve()
        if not self.path.is_file(): raise ValueError(f'Image does not exist: {self.path}')
        self.is_fits=self.path.suffix.lower() in FITS_SUFFIXES
        if not self.is_fits and self.path.suffix.lower() not in {'.tif','.tiff','.png'}:
            raise ValueError('Choose a FITS, TIFF or PNG image.')
        self.wcs_path=self.path if self.is_fits else (Path(wcs_path).expanduser().resolve() if wcs_path else None)

    def header(self):
        if self.wcs_path is None:
            raise ValueError('A TIFF/PNG needs a solved FITS file with identical dimensions and framing.')
        header=fits.getheader(self.wcs_path)
        if not has_solution(header):
            raise ValueError('This file has no valid plate solution. Solve it with your preferred plate solver, then open it again.')
        return header

    def snapshot(self):
        header=self.header()
        if self.is_fits:
            pixels=normalized_pixels(fits.getdata(self.path))
            if 'TOP-DOWN' in str(header.get('ROWORDER','')):
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
                    raster=np.asarray(image).copy()
            if raster.ndim==2: raster=raster[None,:,:]
            elif raster.ndim==3 and raster.shape[-1] in (1,3): raster=np.moveaxis(raster,-1,0)
            else: raise ValueError('Choose a monochrome or RGB image, without alpha or multiple pages.')
            pixels=np.flip(normalized_pixels(raster),axis=-2)
        if (header.get('NAXIS1'),header.get('NAXIS2'))!=(pixels.shape[2],pixels.shape[1]):
            raise ValueError('The solved FITS must have exactly the same dimensions and framing as the image.')
        header=header.copy();header['ROWORDER']='BOTTOM-UP'
        return pixels.copy(),header

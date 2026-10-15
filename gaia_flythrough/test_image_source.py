import tempfile
import unittest
from pathlib import Path
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
import tifffile
from PIL import Image
from image_source import FileImageSource


class ImageSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        wcs=WCS(naxis=2);wcs.wcs.ctype=['RA---TAN','DEC--TAN']
        wcs.wcs.crval=[56,24];wcs.wcs.crpix=[8,6];wcs.wcs.cdelt=[-.01,.01]
        self.header=wcs.to_header();self.header['DATE-OBS']='2026-10-15'
        self.photo=np.full((3,12,16),.2,dtype=np.float32);self.photo[:,0,:]=.8
        self.solved=self.folder/'solved.fits'
        fits.PrimaryHDU(self.photo,self.header).writeto(self.solved)

    def tearDown(self): self.temp.cleanup()

    def test_fits_row_orders_preserve_pixels_header_and_source(self):
        pixels,header=FileImageSource(self.solved).snapshot()
        np.testing.assert_array_equal(pixels,self.photo)
        self.assertEqual(header['DATE-OBS'],'2026-10-15')
        path=self.folder/'top.fits';top=self.header.copy();top['ROWORDER']='TOP-DOWN'
        fits.PrimaryHDU(np.flip(self.photo,axis=-2),top).writeto(path)
        pixels,header=FileImageSource(path).snapshot()
        np.testing.assert_array_equal(pixels,self.photo)
        self.assertEqual(header['ROWORDER'],'BOTTOM-UP')
        self.assertEqual(fits.getheader(path)['ROWORDER'],'TOP-DOWN')

    def test_raster_with_solved_reference_has_matching_orientation(self):
        raster=np.flipud(np.moveaxis(self.photo,0,-1))
        for suffix in ('.tif','.png'):
            path=self.folder/('image'+suffix)
            if suffix=='.tif': tifffile.imwrite(path,np.uint16(raster*65535),photometric='rgb')
            else: Image.fromarray(np.uint8(raster*255)).save(path)
            pixels,header=FileImageSource(path,self.solved).snapshot()
            np.testing.assert_allclose(pixels,self.photo,atol=1/255)
            self.assertEqual(header['ROWORDER'],'BOTTOM-UP')

    def test_invalid_input_is_rejected_without_outputs(self):
        no_wcs=self.folder/'unsolved.fits';fits.PrimaryHDU(self.photo).writeto(no_wcs)
        with self.assertRaisesRegex(ValueError,'plate solution'): FileImageSource(no_wcs).snapshot()
        with self.assertRaisesRegex(ValueError,'solved FITS'): self._raster_without_wcs()
        bad=self.folder/'bad.fits';fits.PrimaryHDU(self.photo*10,self.header).writeto(bad)
        with self.assertRaisesRegex(ValueError,'Normalize or stretch'): FileImageSource(bad).snapshot()
        small=self.folder/'small.png';Image.new('RGB',(8,6)).save(small)
        with self.assertRaisesRegex(ValueError,'dimensions'): FileImageSource(small,self.solved).snapshot()
        self.assertFalse((self.folder/'flythrough').exists())

    def _raster_without_wcs(self):
        path=self.folder/'image.png';Image.new('RGB',(16,12)).save(path)
        return FileImageSource(path).header()

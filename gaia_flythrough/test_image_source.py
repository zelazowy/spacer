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

    def test_astro_tiff_reads_short_cards_line_endings_date_and_sip(self):
        header=self.header.copy();header['SIMPLE']=True
        header['CTYPE1']='RA---TAN-SIP';header['CTYPE2']='DEC--TAN-SIP'
        header['A_ORDER']=2;header['B_ORDER']=2;header['A_2_0']=1e-5;header['B_0_2']=-1e-5
        # Astro-TIFF permits missing structural keywords; TIFF dimensions lead.
        cards=['SIMPLE  =                    T']+[str(card).rstrip() for card in header.cards if card.keyword!='SIMPLE']+['END']
        raster=np.flipud(np.moveaxis(self.photo,0,-1))
        for ending in ('\n','\r\n'):
            path=self.folder/('astro'+str(len(ending))+'.tif')
            tifffile.imwrite(path,raster,photometric='rgb',description=ending.join(cards),metadata=None)
            before=path.read_bytes()
            source=FileImageSource(path)
            self.assertTrue(source.has_coordinates)
            pixels,saved=source.snapshot()
            np.testing.assert_array_equal(pixels,self.photo)
            self.assertEqual(saved['DATE-OBS'],header['DATE-OBS'])
            self.assertEqual(saved['NAXIS1'],16);self.assertEqual(saved['NAXIS2'],12)
            self.assertEqual(saved['A_2_0'],1e-5)
            np.testing.assert_allclose(WCS(saved,naxis=2).all_pix2world([[2,3]],0),WCS(header,naxis=2).all_pix2world([[2,3]],0))
            self.assertEqual(path.read_bytes(),before)

    def test_tiff_orientation_is_independent_of_embedded_roworder(self):
        for orientation in (1,2,3,4):
            for roworder in ('TOP-DOWN','BOTTOM-UP'):
                header=self.header.copy();header.insert(0,('SIMPLE',True));header['ROWORDER']=roworder
                pixels=self.photo.copy()
                if orientation in (1,2): pixels=np.flip(pixels,axis=-2)
                if orientation in (2,3): pixels=np.flip(pixels,axis=-1)
                path=self.folder/f'orientation{orientation}{roworder}.tif'
                tifffile.imwrite(path,np.moveaxis(pixels,0,-1),photometric='rgb',description=header.tostring(sep='\n',padding=False),metadata=None,extratags=[(274,'H',1,orientation,False)])
                actual,_=FileImageSource(path).snapshot()
                np.testing.assert_array_equal(actual,self.photo)

    def test_unsolved_or_incomplete_tiff_metadata_needs_reference(self):
        for description in ('ordinary description','SIMPLE  = T\nEND','SIMPLE  = T\nCTYPE1 = RA---TAN'):
            path=self.folder/'unsolved.tif'
            tifffile.imwrite(path,np.moveaxis(self.photo,0,-1),photometric='rgb',description=description,metadata=None)
            source=FileImageSource(path)
            self.assertFalse(source.has_coordinates)
            with self.assertRaisesRegex(ValueError,'no embedded plate solution'): source.snapshot()

    def test_jpeg_exif_orientation_is_used_for_solver_and_photo(self):
        path=self.folder/'rotated.jpg'
        raster=np.zeros((12,16,3),dtype=np.uint8);raster[:4,:,0]=200
        exif=Image.Exif();exif[274]=6
        Image.fromarray(raster).save(path,exif=exif)
        before=path.read_bytes();source=FileImageSource(path)
        self.assertFalse(source.has_coordinates)
        pixels,header=source.snapshot(allow_unsolved=True)
        self.assertEqual(pixels.shape,(3,16,12))
        from PIL import ImageOps
        with Image.open(path) as image:
            expected=np.flipud(np.asarray(ImageOps.exif_transpose(image)))/255
        np.testing.assert_allclose(np.moveaxis(pixels,0,-1),expected,atol=1e-7)
        self.assertEqual(header['NAXIS1'],12);self.assertEqual(header['NAXIS2'],16)
        self.assertEqual(path.read_bytes(),before)

    def test_jpeg_fits_description_preserves_solution_sip_date_and_pixels(self):
        header=fits.getheader(self.solved)
        header['CTYPE1']='RA---TAN-SIP';header['CTYPE2']='DEC--TAN-SIP'
        header['A_ORDER']=2;header['B_ORDER']=2;header['A_2_0']=1e-5;header['B_0_2']=-1e-5
        for ending in ('\n','\r\n'):
            path=self.folder/'astro.jpg';exif=Image.Exif();exif[274]=1
            exif[270]=header.tostring(sep=ending,padding=False)
            Image.fromarray(np.uint8(np.flipud(np.moveaxis(self.photo,0,-1))*255)).save(path,exif=exif)
            before=path.read_bytes();source=FileImageSource(path)
            self.assertTrue(source.has_coordinates)
            actual,saved=source.snapshot()
            with Image.open(path) as image: expected=np.asarray(image)[::-1]/255
            np.testing.assert_allclose(np.moveaxis(actual,0,-1),expected,atol=1e-7)
            self.assertEqual(saved['A_2_0'],header['A_2_0'])
            self.assertEqual(source.date_info()['value'],'2026-10-15T00:00:00.000')
            np.testing.assert_allclose(WCS(saved,naxis=2).all_pix2world([[2,3],[14,10]],0),WCS(header,naxis=2).all_pix2world([[2,3],[14,10]],0))
            self.assertEqual(path.read_bytes(),before)

    def test_stale_rotated_or_incomplete_jpeg_description_needs_solving(self):
        header=fits.getheader(self.solved)
        for orientation,size,description in ((6,(16,12),header.tostring(sep='\n',padding=False)),(1,(8,6),header.tostring(sep='\n',padding=False)),(1,(16,12),'ordinary caption'),(1,(16,12),'SIMPLE  = T\nCTYPE1=RA---TAN')):
            path=self.folder/'stale.jpg';exif=Image.Exif();exif[274]=orientation;exif[270]=description
            Image.new('RGB',size).save(path,exif=exif)
            source=FileImageSource(path);self.assertFalse(source.has_coordinates)
            with self.assertRaisesRegex(ValueError,'no embedded plate solution'): source.snapshot()

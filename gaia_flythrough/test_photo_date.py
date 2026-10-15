from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
import unittest
from PIL import Image
from astropy.io import fits
from photo_date import infer_photo_date, date_info


class DateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'photo.jpg'
        Image.new('RGB',(12,8)).save(self.path)

    def tearDown(self): self.temp.cleanup()

    def test_capture_header_beats_exif_and_file_time(self):
        exif=Image.Exif();exif[36867]='2014:08:03 22:30:00'
        Image.new('RGB',(12,8)).save(self.path,exif=exif)
        header=fits.Header();header['DATE-OBS']='2005-02-03T01:02:03'
        result=infer_photo_date(self.path,header)
        self.assertTrue(result['value'].startswith('2005-02-03'))
        self.assertFalse(result['approximate'])
        result=infer_photo_date(self.path)
        self.assertTrue(result['value'].startswith('2014-08-03T22:30:00'))
        self.assertEqual(result['source'],'EXIF capture date')

    def test_invalid_capture_falls_back_to_file_metadata(self):
        exif=Image.Exif();exif[36867]='0000:00:00 00:00:00';exif[306]='2020:04:05 12:00:00'
        Image.new('RGB',(12,8)).save(self.path,exif=exif)
        result=infer_photo_date(self.path)
        self.assertTrue(result['value'].startswith('2020-04-05'))
        self.assertEqual(result['source'],'EXIF file date');self.assertTrue(result['approximate'])

    def test_filesystem_creation_then_modification_not_ctime(self):
        stamp=datetime(2012,3,4,tzinfo=timezone.utc).timestamp()
        # Patch only the final stat lookup; is_file uses an actual image.
        from photo_date import Path as DatePath
        real_stat=DatePath.stat
        def stat(path,*args,**kwargs):
            if kwargs.get('follow_symlinks') is False: return real_stat(path,*args,**kwargs)
            return SimpleNamespace(st_mode=real_stat(path).st_mode,st_birthtime=stamp,st_mtime=stamp+86400,st_ctime=stamp+999999)
        with patch.object(DatePath,'stat',stat): result=infer_photo_date(self.path)
        self.assertTrue(result['value'].startswith('2012-03-04'))
        self.assertEqual(result['source'],'File creation date');self.assertTrue(result['approximate'])
        def stat_without_birth(path,*args,**kwargs):
            return SimpleNamespace(st_mode=real_stat(path).st_mode,st_mtime=stamp,st_ctime=stamp+999999)
        with patch.object(DatePath,'stat',stat_without_birth): result=infer_photo_date(self.path)
        self.assertEqual(result['source'],'File modification date')

    def test_year_month_and_saved_approximation(self):
        result=date_info('2005','Manual date')
        self.assertTrue(result['value'].startswith('2005-07-01'));self.assertTrue(result['approximate'])
        self.assertTrue(date_info('2005-03','Manual date')['value'].startswith('2005-03-15'))
        self.assertIsNone(date_info('not a date','Manual date'))
        header=fits.Header();header['DATE-OBS']='2020-01-01';header['DATEAPPX']=True;header['DATESRC']='File creation date'
        result=infer_photo_date(self.path,header)
        self.assertTrue(result['approximate']);self.assertEqual(result['source'],'File creation date')

import io
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io.votable import from_table,writeto
from astropy.table import Table
from astropy.wcs import WCS
import astropy.units as u

from catalog import (COLUMNS,CatalogOverflow,cone_query,get_catalog,parse_result,plan_regions,query_region)


def field(ra=0,dec=89.5,scale=.01):
    w=WCS(naxis=2);w.wcs.ctype=['RA---TAN','DEC--TAN']
    w.wcs.crpix=[301,201];w.wcs.crval=[ra,dec];w.wcs.cdelt=[-scale,scale]
    return w


def row(source_id):
    return dict(zip(COLUMNS,[str(source_id),'0','89','0','0','1','15','200','190','210']))


def votable(rows,status='OK'):
    table=Table(rows=[[r[key] for key in COLUMNS] for r in rows],names=COLUMNS,dtype=['U20']*len(COLUMNS))
    out=io.BytesIO();writeto(from_table(table),out)
    return out.getvalue().replace(b'</RESOURCE>',f'<INFO name="QUERY_STATUS" value="{status}"/></RESOURCE>'.encode())


class CatalogTests(unittest.TestCase):
    def test_wide_polar_and_ra_wrap_fields_have_complete_sampled_coverage(self):
        for ra,dec in ((42,89.5),(359.9,10),(0,-89.5)):
            w=field(ra,dec);regions=plan_regions(w,(0,600,0,400))
            self.assertGreater(len(regions),1)
            xx,yy=np.meshgrid(np.linspace(0,600,51),np.linspace(0,400,51))
            sky=w.pixel_to_world(xx.ravel(),yy.ravel()).icrs
            covered=np.zeros(sky.shape,dtype=bool)
            for bounds,cone in regions:
                a,d,r=cone;self.assertLessEqual(r,2.5)
                covered|=SkyCoord(a*u.deg,d*u.deg).separation(sky).deg<=r
            self.assertTrue(covered.all())
        self.assertEqual(len(plan_regions(field(scale=.001),(0,600,0,400))),1)

    def test_votable_status_empty_and_large_integer_ids(self):
        rows=parse_result(votable([row(9223372036854775807)]))
        self.assertEqual(rows[0]['source_id'],'9223372036854775807')
        self.assertEqual(parse_result(votable([])),[])
        with self.assertRaises(CatalogOverflow): parse_result(votable([row(1)],'OVERFLOW'))
        # A trailing overflow after initial OK must not be accepted.
        data=votable([row(1)]).replace(b'</RESOURCE>',b'<INFO name="QUERY_STATUS" value="OVERFLOW"/></RESOURCE>')
        with self.assertRaises(CatalogOverflow): parse_result(data)
        with self.assertRaisesRegex(ValueError,'service'): parse_result(votable([],'ERROR'))
        data=votable([]).replace(b'<INFO name="QUERY_STATUS" value="OK"/>',b'')
        with self.assertRaisesRegex(ValueError,'completion status'): parse_result(data)

    def test_overflow_subdivision_dedup_and_final_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'catalog.csv';w=field(scale=.001)
            with patch('catalog.query_region',side_effect=[CatalogOverflow(),[row(1)],[row(1),row(2)],[],[row(3)]]) as query:
                rows=get_catalog(w,601,401,path,18,lambda _:None)
                self.assertEqual(query.call_count,5)
            self.assertEqual([r['source_id'] for r in rows],['1','2','3'])
            with patch('catalog.query_region') as query:
                self.assertEqual(get_catalog(w,601,401,path,18,lambda _:None),rows);query.assert_not_called()

    def test_failed_region_keeps_completed_parts_and_resumes(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'catalog.csv';w=field()
            count=len(plan_regions(w,(0,600,0,400)))
            with patch('catalog.query_region',side_effect=[[row(1)],OSError('offline')]):
                with self.assertRaises(OSError): get_catalog(w,601,401,path,18,lambda _:None)
            self.assertFalse(path.exists());self.assertEqual(len(list((Path(folder)/'catalog-parts').glob('*.csv'))),1)
            with patch('catalog.query_region',return_value=[row(2)]) as query:
                rows=get_catalog(w,601,401,path,18,lambda _:None)
                self.assertEqual(query.call_count,count-1)
            self.assertEqual({r['source_id'] for r in rows},{'1','2'})

    def test_cancel_preserves_parts_and_overflow_decision(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'catalog.csv';w=field(scale=.001);cancel=threading.Event()
            def stop(*args): cancel.set();raise InterruptedError('cancelled')
            calls=iter([CatalogOverflow(),[row(1)],None])
            def dispatch(*args):
                result=next(calls)
                if isinstance(result,Exception): raise result
                if result is None: return stop()
                return result
            with patch('catalog.query_region',side_effect=dispatch):
                with self.assertRaises(InterruptedError): get_catalog(w,601,401,path,18,lambda _:None,cancel)
            self.assertFalse(path.exists());cancel.clear()
            with patch('catalog.query_region',return_value=[]) as query:
                self.assertEqual(len(get_catalog(w,601,401,path,18,lambda _:None,cancel)),1)
                self.assertEqual(query.call_count,3) # parent + completed child stay cached

    def test_cancel_during_remote_poll_aborts_job(self):
        cancel=threading.Event()
        class Response(io.BytesIO):
            url='https://dc.g-vo.org/tap/async/job'
        calls=[]
        def request(value,**kwargs):
            calls.append(value)
            if len(calls)==3: cancel.set();return Response(b'EXECUTING')
            return Response(b'')
        with patch('catalog.urllib.request.urlopen',side_effect=request):
            with self.assertRaises(InterruptedError): query_region(cone_query((0,89,2),18),cancel)
        self.assertEqual(calls[-1].data,b'PHASE=ABORT')

    def test_incomplete_service_result_is_not_cached_and_empty_parts_are_ok(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'catalog.csv'
            with patch('catalog.query_region',side_effect=ValueError('unverified completion')):
                with self.assertRaises(ValueError): get_catalog(field(scale=.001),601,401,path,18,lambda _:None)
            self.assertFalse(path.exists());self.assertFalse(list((Path(folder)/'catalog-parts').glob('*.csv')))
            with patch('catalog.query_region',return_value=[]):
                with self.assertRaisesRegex(ValueError,'no usable stars'): get_catalog(field(scale=.001),601,401,path,18,lambda _:None)
            self.assertFalse(path.exists())
            with patch('catalog.query_region') as query:
                with self.assertRaisesRegex(ValueError,'no usable stars'): get_catalog(field(scale=.001),601,401,path,18,lambda _:None)
                query.assert_not_called()

    def test_part_cache_key_includes_magnitude_and_footprint(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'catalog.csv'
            with patch('catalog.query_region',return_value=[row(1)]) as query:
                get_catalog(field(scale=.001),601,401,path,18,lambda _:None)
                path.unlink() # simulate a retry before the final catalogue exists
                get_catalog(field(scale=.001),601,401,path,17,lambda _:None)
                path.unlink()
                get_catalog(field(ra=40,scale=.001),601,401,path,17,lambda _:None)
                self.assertEqual(query.call_count,3)

    def test_remote_success_requests_votable_and_checks_streamed_result(self):
        class Response(io.BytesIO):
            url='https://dc.g-vo.org/tap/async/job'
        replies=[Response(b''),Response(b''),Response(b'COMPLETED'),Response(votable([row(123)]))]
        with patch('catalog.urllib.request.urlopen',side_effect=replies) as request:
            rows=query_region(cone_query((42,89.5,2),18),progress=lambda _:None)
        self.assertEqual(rows[0]['source_id'],'123')
        self.assertIn(b'FORMAT=votable',request.call_args_list[0].args[0].data)
        self.assertIn(b'MAXREC=200000',request.call_args_list[0].args[0].data)

    def test_field_limit_accepts_300mm_full_frame_and_suggests_crop_for_wider_input(self):
        from catalog import validate_field
        self.assertLess(validate_field(field(scale=.0115),601,401),5)
        w=field(scale=.02)
        with self.assertRaisesRegex(ValueError,'central crop.*Plate-solve'):
            validate_field(w,601,401)
        with tempfile.TemporaryDirectory() as folder,patch('catalog.query_region') as query:
            path=Path(folder)/'catalog.csv'
            with self.assertRaisesRegex(ValueError,'limits new preparation'):
                get_catalog(w,601,401,path,18,lambda _:None)
            query.assert_not_called();self.assertFalse((Path(folder)/'catalog-parts').exists())

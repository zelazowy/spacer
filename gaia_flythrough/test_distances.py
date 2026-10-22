"""Distance selection, catalogue provenance and cross-catalogue matching checks."""
import csv
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from astropy.io.votable import from_table,writeto
from astropy.table import Table
from astropy.wcs import WCS
from catalog import COLUMNS,parse_result,write_rows,get_catalog
from distances import choose_distance,merge_hipparcos,hipparcos_rows,extended_query,HIP_FIELDS


def gaia(**values):
    return dict(dict(source_id='9007199254740993',ra=0,dec=0,pmra=0,pmdec=0,ruwe=1,
        phot_g_mean_mag=12,r_med_geo=100,r_lo_geo=90,r_hi_geo=110,
        r_med_photogeo=120,r_lo_photogeo=80,r_hi_photogeo=160),**values)


def hip(**values):
    return dict(dict(source_id='HIP:42',ra=0,dec=0,pmra=0,pmdec=0,hip_id='42',
        hip_parallax=10,hip_parallax_error=1,hip_solution_type=5,hip_components=1,hip_quality_fit=1),**values)


class DistanceTests(unittest.TestCase):
    def test_strict_selection_stays_preferred_in_extended_mode(self):
        row=gaia();row.update(hip())
        for enabled in (False,True):
            result=choose_distance(row,enabled)
            self.assertEqual(result['distance_pc'],100)
            self.assertEqual(result['distance_source'],'Gaia geometric')
            self.assertFalse(result['distance_approximate'])

    def test_extended_photogeometric_then_broader_geometric(self):
        row=gaia(r_lo_geo=40,r_hi_geo=160)
        self.assertIsNone(choose_distance(row))
        result=choose_distance(row,True)
        self.assertEqual(result['distance_source'],'Gaia photogeometric')
        self.assertEqual(result['distance_pc'],120);self.assertTrue(result['distance_approximate'])
        row.update(r_med_photogeo='',r_lo_geo=60,r_hi_geo=140)
        self.assertEqual(choose_distance(row,True)['distance_source'],'Gaia geometric (extended)')
        row['ruwe']=1.5;self.assertIsNone(choose_distance(row,True))
        row['ruwe']='';self.assertIsNone(choose_distance(row,True))

    def test_no_distance_invented_for_invalid_or_overwide_intervals(self):
        for value in ('','nan','inf',-1,0,200):
            row=gaia(r_lo_geo=value,r_med_photogeo='')
            self.assertIsNone(choose_distance(row,True))
        self.assertIsNone(choose_distance(gaia(r_lo_geo=1,r_hi_geo=300,r_med_photogeo=''),True))

    def test_hipparcos_is_independently_screened_and_has_its_own_id(self):
        row=gaia(ruwe=2);row.update(hip())
        result=choose_distance(row,True)
        self.assertEqual(result['distance_source'],'Hipparcos-2')
        self.assertEqual(result['distance_catalogue_id'],'HIP:42')
        self.assertAlmostEqual(result['lower_pc'],1000/11)
        for key,value in (('hip_parallax_error',3),('hip_parallax',-2),('hip_quality_fit',4),
                          ('hip_solution_type',15),('hip_components',2),('hip_parallax_error',0)):
            rejected=dict(row);rejected[key]=value
            self.assertIsNone(choose_distance(rejected,True),key)

    def test_crossmatch_deduplicates_at_common_epoch_and_rejects_ambiguity(self):
        row=gaia(ruwe=2)
        rows,stats=merge_hipparcos([row],[hip(ra=359.9999)])
        self.assertEqual(len(rows),1);self.assertEqual(stats['matched'],1)
        self.assertEqual(rows[0]['source_id'],row['source_id'])
        self.assertEqual(rows[0]['position_source'],'Hipparcos-2')
        self.assertEqual(choose_distance(rows[0],True)['distance_source'],'Hipparcos-2')
        # Two nearby Gaia detections must not be merged into a moving cluster.
        rows,stats=merge_hipparcos([row,gaia(source_id='2',ra=.0002)],[hip()])
        self.assertEqual(stats['ambiguous'],1);self.assertEqual(len(rows),2)
        self.assertNotIn('hip_id',rows[0])
        rows,stats=merge_hipparcos([gaia()],[hip(ra=.1)])
        self.assertEqual(stats['added'],1);self.assertEqual(len(rows),2)
        rows,stats=merge_hipparcos([gaia(ra=float('nan'))],[hip()])
        self.assertEqual(stats['added'],1)

    def test_good_gaia_distance_and_position_are_not_replaced(self):
        row=gaia();rows,_=merge_hipparcos([row],[hip(ra=.0001)])
        self.assertEqual(rows,[row])

    def test_hipparcos_old_epoch_is_propagated_and_cache_reused(self):
        w=WCS(naxis=2);w.wcs.ctype=['RA---TAN','DEC--TAN'];w.wcs.crval=[0,0]
        w.wcs.crpix=[50,50];w.wcs.cdelt=[-.001,.001]
        raw=dict(hip_number=42,ra=0,dec=0,pm_ra=1000,pm_dec=0,parallax=10,
            parallax_error=1,hip_mag=6,new_solution_type=5,number_components=1,quality_fit=1)
        table=Table(rows=[[raw[k] for k in HIP_FIELDS]],names=HIP_FIELDS)
        output=io.BytesIO();writeto(from_table(table),output)
        data=output.getvalue().replace(b'</RESOURCE>',b'<INFO name="QUERY_STATUS" value="OK"/></RESOURCE>')
        with tempfile.TemporaryDirectory() as folder:
            with patch('distances.urllib.request.urlopen',return_value=io.BytesIO(data)) as request:
                rows=hipparcos_rows(w,100,100,folder,'2026-01-01',progress=lambda _:None)
                self.assertEqual(request.call_count,1)
            self.assertAlmostEqual(float(rows[0]['ra'])*3600,24.75,places=4)
            self.assertEqual(rows[0]['source_id'],'HIP:42')
            with patch('distances.urllib.request.urlopen') as request:
                cached=hipparcos_rows(w,100,100,folder,'2026-01-01')
                request.assert_not_called()
            self.assertEqual(cached[0]['hip_id'],'42')

    def test_extended_fields_survive_votable_parts_and_final_csv(self):
        row=gaia();table=Table(rows=[[str(v) for v in row.values()]],names=list(row))
        output=io.BytesIO();writeto(from_table(table),output)
        data=output.getvalue().replace(b'</RESOURCE>',b'<INFO name="QUERY_STATUS" value="OK"/></RESOURCE>')
        rows=parse_result(data);self.assertEqual(rows[0]['source_id'],row['source_id'])
        self.assertEqual(rows[0]['r_med_photogeo'],'120')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'catalog.csv';write_rows(path,rows)
            with path.open() as file:cached=list(csv.DictReader(file))
            self.assertEqual(cached,rows)
        query=extended_query((0,0,1),18)
        self.assertIn('LEFT JOIN gedr3dist.main',query)
        self.assertIn('d.r_med_photogeo',query)
        self.assertIn('d.flag',query)

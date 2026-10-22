import unittest
from astropy.wcs import WCS
from targets import field_query,parse_targets,LIMIT

class TargetTests(unittest.TestCase):
    def setUp(self):
        w=WCS(naxis=2);w.wcs.crval=[359.9,24];w.wcs.crpix=[50,40];w.wcs.cdelt=[-.01,.01];w.wcs.ctype=['RA---TAN','DEC--TAN']
        self.header=w.to_header();self.header['NAXIS1']=100;self.header['NAXIS2']=80
        _,self.wcs,self.width,self.height=field_query(self.header)
        self.names=['main_id','otype','ra','dec','dist','unit','minus_err','plus_err','method','bibcode','qual']
    def parse(self,rows):
        return parse_targets(dict(metadata=[dict(name=n) for n in self.names],data=rows),self.wcs,100,80)
    def row(self,distance=2,unit='kpc',x=50):
        ra,dec=self.wcs.pixel_to_world_values(x,40)
        return ['M test','G',float(ra),float(dec),distance,unit,-.1,.2,'method','2025ref',None]
    def test_unit_conversion_errors_dedup_and_footprint(self):
        a=self.row()
        rows=self.parse([a,a,self.row(x=120)])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['distance_pc'],2000)
        self.assertEqual(rows[0]['minus_error_pc'],100)
        self.assertEqual(rows[0]['plus_error_pc'],200)
        self.assertEqual(self.parse([self.row(2,'Mpc')])[0]['distance_pc'],2e6)
    def test_missing_invalid_measurements_stay_unknown(self):
        for value,unit in [(None,'pc'),(-2,'pc'),(float('nan'),'pc'),(2,'unknown')]:
            self.assertIsNone(self.parse([self.row(value,unit)])[0]['distance_pc'])
    def test_many_measurements_do_not_exhaust_object_limit(self):
        self.assertEqual(len(self.parse([self.row()]*(LIMIT+1))),1)

    def test_object_selection_precedes_paginated_measurements(self):
        from targets import find_targets
        from unittest.mock import patch
        ra,dec=self.wcs.pixel_to_world_values(50,40)
        obj=dict(oid=10,main_id='M33',otype='G',ra=ra,dec=dec,nbref=10000)
        data=[dict(oidref=10,mespos=i,dist=i,unit='kpc',bibcode=str(i)) for i in (1,2,3)]
        with patch('targets.LIMIT',2),patch('targets.tap_rows',side_effect=[[obj],[],data,data[2:]]) as tap:
            result=find_targets(self.header)
        self.assertEqual([r['distance_pc'] for r in result],[1000,2000,3000])
        self.assertNotIn('JOIN',tap.call_args_list[0].args[0])
        self.assertIn('mespos>2',tap.call_args_list[3].args[0])

    def test_sky_query_uses_solved_field(self):
        query,*_=field_query(self.header)
        self.assertIn("CIRCLE('ICRS',359.",query)
        self.assertIn('FROM basic AS b',query)
        self.assertIn("path LIKE 'G > %'",query)
        self.assertNotIn('JOIN',query)
        self.assertIn('ORDER BY nbref DESC',query)
        self.assertIn('SELECT oidref FROM ident',query)

class ApproximateTargetTests(unittest.TestCase):
    def test_one_object_one_rounded_distance_keeps_sources(self):
        from targets import approximate_targets
        rows=[dict(name='M45',distance_pc=d,bibcode=str(d)) for d in (130,135,136)]
        result=approximate_targets(rows)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['distance_pc'],140)
        self.assertEqual(result[0]['distance_range_pc'],[130,136])
        self.assertEqual(result[0]['measurements'],rows)
    def test_approximate_labels_are_readable(self):
        from targets import approximate_distance_label
        self.assertEqual(approximate_distance_label(850000),'about 850 kpc')
        self.assertEqual(approximate_distance_label(140),'about 140 pc')

    def test_unknown_distance_stays_unknown(self):
        from targets import approximate_targets
        self.assertIsNone(approximate_targets([dict(name='nebula',distance_pc=None)])[0]['distance_pc'])

class FamiliarCatalogueTests(unittest.TestCase):
    def test_alias_prefers_messier_over_primary_and_ngc(self):
        from targets import preferred_name
        self.assertEqual(preferred_name(['Cl Melotte   22','M  45','NGC 1432']),'M45')
        self.assertEqual(preferred_name(['NGC 224','IC 10']),'IC 10')
        self.assertIsNone(preferred_name(['2MASS J0133','WISE J1234']))
    def test_catalogues_and_numbers_sort_in_requested_order(self):
        from targets import approximate_targets
        names=['NGC 604','M10','IC 133','M2','LDN 1251','NGC 55']
        rows=[dict(name=name,distance_pc=100) for name in names]
        self.assertEqual([r['name'] for r in approximate_targets(rows)],['M2','M10','IC 133','NGC 55','NGC 604','LDN 1251'])
    def test_field_lookup_uses_familiar_alias_and_preserves_primary(self):
        from targets import find_targets
        from astropy.wcs import WCS
        from unittest.mock import patch
        w=WCS(naxis=2);w.wcs.ctype=['RA---TAN','DEC--TAN'];w.wcs.crval=[56.6,24.1];w.wcs.crpix=[50,40];w.wcs.cdelt=[-.01,.01]
        header=w.to_header();header['NAXIS1']=100;header['NAXIS2']=80
        ra,dec=w.pixel_to_world_values(50,40)
        obj=dict(oid=10,main_id='Cl Melotte   22',otype='OpC',ra=ra,dec=dec,nbref=100)
        aliases=[dict(oidref=10,id='M  45')]
        distance=[dict(oidref=10,mespos=1,dist=135,unit='pc')]
        with patch('targets.tap_rows',side_effect=[[obj],aliases,distance]):
            rows=find_targets(header)
        self.assertEqual(rows[0]['name'],'M45')
        self.assertEqual(rows[0]['simbad_name'],'Cl Melotte   22')
        self.assertIn('M  45',rows[0]['aliases'])

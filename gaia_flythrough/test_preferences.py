import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from preferences import Preferences


class PreferenceTests(unittest.TestCase):
    def test_invalid_preferences_and_unwritable_location_are_nonfatal(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json'
            for value in ('broken JSON','[]','null'):
                path.write_text(value)
                prefs=Preferences(path)
                self.assertEqual(prefs.data,{})
                self.assertEqual(prefs.directory('image_directory'),str(Path.home()))
            prefs=Preferences(path)
            with patch.object(Path,'write_text',side_effect=OSError('read only')):
                self.assertFalse(prefs.save(last_kind='image'))

    def test_atomic_settings_round_trip_and_stale_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json';prefs=Preferences(path)
            self.assertTrue(prefs.save(image_directory=folder,last_kind='image',last_image='/some/image.jpg'))
            restored=Preferences(path)
            self.assertEqual(restored.data['last_image'],'/some/image.jpg')
            self.assertEqual(restored.directory('image_directory'),folder)
            self.assertFalse(path.with_suffix('.tmp').exists())
            restored.save(image_directory='/this/directory/does/not/exist')
            self.assertEqual(restored.directory('image_directory'),str(Path.home()))

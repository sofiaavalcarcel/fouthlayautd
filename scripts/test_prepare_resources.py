import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest
from dotenv import dotenv_values

spec = importlib.util.spec_from_file_location('resources', Path(__file__).with_name('prepare-resources.py'))
resources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resources)


class ResourceSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for relative in (resources.CATALOG, '.env.example',
            'backend/app/modules/weekly_auto/weekly_photos/default_urls.txt',
            'backend/app/modules/bot_leads_deploy/data/utel_programas1.xlsx',
            'backend/app/modules/bot_nuevos_productos/data/utel_programas1.xlsx'):
            dest = self.root / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(resources.ROOT / relative, dest)

    def test_new_device_prepares_once(self):
        self.assertEqual(resources.prepare(self.root), 2)
        self.assertFalse((self.root / '.env').exists())
        self.assertEqual(resources.prepare(self.root, True), 0)
        original = (self.root / '.env').read_bytes()
        self.assertEqual(resources.prepare(self.root), 0)
        self.assertEqual((self.root / '.env').read_bytes(), original)
        self.assertEqual(dotenv_values(self.root / '.env')['UTEL_ALLOW_SYNTHETIC_REAL_PHONES'], 'true')

    def test_existing_empty_bank_is_migrated_without_losing_settings(self):
        (self.root / '.env').write_text('UTEL_TEST_PHONES_JSON={}\nUTEL_ALLOW_SYNTHETIC_REAL_PHONES=false\nCRM_USERNAME=test-user\n')
        self.assertEqual(resources.prepare(self.root), 2)
        resources.prepare(self.root, True)
        self.assertEqual(dotenv_values(self.root / '.env')['CRM_USERNAME'], 'test-user')

    def test_existing_bank_is_preserved(self):
        (self.root / '.env').write_text('UTEL_TEST_PHONES_JSON={"Argentina":["qa-test-placeholder"]}\nUTEL_ALLOW_SYNTHETIC_REAL_PHONES=false\n')
        original = (self.root / '.env').read_bytes()
        self.assertEqual(resources.prepare(self.root), 0)
        self.assertEqual((self.root / '.env').read_bytes(), original)

    def test_missing_catalog_is_reported(self):
        (self.root / resources.CATALOG).unlink()
        with self.assertRaisesRegex(ValueError, 'Falta el catalogo'):
            resources.prepare(self.root)


if __name__ == '__main__':
    unittest.main()

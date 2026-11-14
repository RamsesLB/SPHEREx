import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from django.core.files.storage import FileSystemStorage
from django.test import SimpleTestCase, override_settings

from search import services


def _sky_header():
    header = fits.Header()
    header["XTENSION"] = "IMAGE"
    header["EXTNAME"] = "IMAGE"
    header["BSCALE"] = 1.0
    header["BZERO"] = 0.0
    header["CTYPE1"] = "RA---TAN"
    header["CTYPE2"] = "DEC--TAN"
    header["CRPIX1"] = 4.5
    header["CRPIX2"] = 4.5
    header["CRVAL1"] = 133.795
    header["CRVAL2"] = -7.245
    header["CDELT1"] = -0.001
    header["CDELT2"] = 0.001
    header["DETECTOR"] = 3
    return header


class FitsImageCacheTests(SimpleTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.storage = FileSystemStorage(location=self.temp.name)
        self.image = SimpleNamespace(pk=7, access_url="https://example.test/image.fits", detector=3)

    def tearDown(self):
        self.temp.cleanup()

    def _patch_download(self, calls):
        def fake_open(url, *, native=False):
            calls.append((url, native))
            data = np.arange(64, dtype=np.float32).reshape(8, 8)
            return data, _sky_header()

        return patch("search.services._open_image", fake_open)

    @override_settings(FITS_IMAGE_CACHE="r2")
    def test_r2_mode_downloads_once_and_reuses_the_stored_image(self):
        calls = []
        with self._patch_download(calls), patch("search.services.default_storage", self.storage):
            first_data, first_header = services.cached_image_hdu(self.image)
            second_data, second_header = services.cached_image_hdu(self.image)

        self.assertEqual(calls, [("https://example.test/image.fits", True)])
        self.assertEqual(first_data.dtype, np.float32)
        self.assertTrue(np.array_equal(first_data, second_data))
        self.assertEqual(int(second_header["DETECTOR"]), 3)
        self.assertAlmostEqual(float(second_header["CRVAL1"]), 133.795)
        self.assertNotIn("XTENSION", second_header)
        self.assertTrue(self.storage.exists("fits-cache/v1_7.fits"))

    @override_settings(FITS_IMAGE_CACHE="off")
    def test_off_mode_keeps_downloading_the_fits_for_each_cutout(self):
        calls = []
        coord = SkyCoord(133.795, -7.245, unit="deg")

        def fake_open(url, *, native=False):
            calls.append(native)
            return np.ones((8, 8), dtype=np.float64), _sky_header()

        with patch("search.services._open_image", fake_open), patch("search.services.cached_image_hdu") as cached:
            services.render_cutout(self.image, coord, 10)
            services.render_cutout(self.image, coord, 10)

        self.assertEqual(calls, [False, False])
        cached.assert_not_called()

    @override_settings(FITS_IMAGE_CACHE="r2")
    def test_r2_mode_cuts_from_the_cached_image(self):
        calls = []
        coord = SkyCoord(133.795, -7.245, unit="deg")
        with self._patch_download(calls), patch("search.services.default_storage", self.storage):
            services.render_cutout(self.image, coord, 10)
            services.render_cutout(self.image, coord, 12)

        self.assertEqual(len(calls), 1)

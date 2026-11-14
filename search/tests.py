import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.table import Table
from astropy.wcs import WCS
from django.core.files.storage import FileSystemStorage
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from search import services, views
from search.models import SpherexCollection, SpherexImage


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

    @override_settings(IMAGE_MODE="fits")
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

    @override_settings(IMAGE_MODE="image")
    def test_off_mode_keeps_downloading_the_fits_for_each_cutout(self):
        calls = []
        coord = SkyCoord(133.795, -7.245, unit="deg")

        def fake_open(url, *, native=False):
            calls.append(native)
            return np.ones((8, 8), dtype=np.float64), _sky_header()

        with patch("search.services._open_image", fake_open), patch("search.services.cached_image_hdu") as cached:
            services.render_cutout(self.image, coord, 10)
            services.render_cutout(self.image, coord, 10)

        self.assertEqual(calls, [True, True])
        cached.assert_not_called()

    @override_settings(IMAGE_MODE="fits")
    def test_r2_mode_cuts_from_the_cached_image(self):
        calls = []
        coord = SkyCoord(133.795, -7.245, unit="deg")
        with self._patch_download(calls), patch("search.services.default_storage", self.storage):
            services.render_cutout(self.image, coord, 10)
            services.render_cutout(self.image, coord, 12)

        self.assertEqual(len(calls), 1)

    @override_settings(IMAGE_MODE="image")
    def test_image_mode_stores_the_png_cutout_and_not_the_fits(self):
        calls = []
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        with self._patch_download(calls), patch("search.services.default_storage", self.storage), override_settings(MEDIA_ROOT=media.name):
            first = services.cached_cutout(self.image, "133.795", "-7.245", 10)
            stored_name = f"media/cutouts/{first.name}"
            self.assertTrue(self.storage.exists(stored_name))
            self.assertFalse(self.storage.exists("fits-cache/v1_7.fits"))
            first.unlink()
            second = services.cached_cutout(self.image, "133.795", "-7.245", 10)

        self.assertEqual(len(calls), 1)
        self.assertTrue(second.exists())
        self.assertGreater(second.stat().st_size, 0)
        self.assertEqual(first.name, second.name)

    @override_settings(IMAGE_MODE="fits")
    def test_fits_mode_stores_the_fits_and_the_png(self):
        calls = []
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        with self._patch_download(calls), patch("search.services.default_storage", self.storage), override_settings(MEDIA_ROOT=media.name):
            first = services.cached_cutout(self.image, "133.795", "-7.245", 10)
            stored_name = f"media/cutouts/{first.name}"
            self.assertTrue(self.storage.exists("fits-cache/v1_7.fits"))
            self.assertTrue(self.storage.exists(stored_name))
            first.unlink()
            second = services.cached_cutout(self.image, "133.795", "-7.245", 10)

        self.assertEqual(len(calls), 1)
        self.assertTrue(second.exists())
        self.assertGreater(second.stat().st_size, 0)


class CoordinateParseTests(SimpleTestCase):
    def test_unicode_minus_and_dashes_keep_the_southern_declination(self):
        ascii_coord = services.parse_coordinates("22h03m21.65363s", "-56d47m09.5228s")
        for dec in ("\u221256d47m09.5228s", "\u201356d47m09.5228s", "\u201456d47m09.5228s"):
            coord = services.parse_coordinates("22h03m21.65363s", dec)
            self.assertAlmostEqual(coord.ra.deg, ascii_coord.ra.deg)
            self.assertAlmostEqual(coord.dec.deg, ascii_coord.dec.deg)
            self.assertLess(coord.dec.deg, 0)

    def test_normalize_angle_rewrites_the_unicode_minus(self):
        self.assertEqual(services.normalize_angle("\u221256d47m09.5228s"), "-56d47m09.5228s")


class CutoutOrientationTests(SimpleTestCase):
    def test_north_east_pixel_moves_to_the_top_left(self):
        header = fits.Header()
        header["CTYPE1"] = "RA---TAN"
        header["CTYPE2"] = "DEC--TAN"
        header["CRPIX1"] = 3
        header["CRPIX2"] = 3
        header["CRVAL1"] = 10.0
        header["CRVAL2"] = 0.0
        header["CDELT1"] = 0.1
        header["CDELT2"] = 0.1
        data = np.zeros((5, 5))
        data[3, 3] = 5
        oriented = services._orient_north_up_east_left(data, WCS(header))
        row, column = np.unravel_index(np.nanargmax(oriented), oriented.shape)
        self.assertLess(row, 2.5)
        self.assertLess(column, 2.5)


class FootprintTests(SimpleTestCase):
    def test_polygon_crossing_zero_keeps_the_wrap(self):
        ra_min, ra_max, dec_min, dec_max = services.footprint_bbox(
            "POLYGON ICRS 350 -2 10 -2 10 2 350 2",
            1,
            0,
        )
        self.assertGreater(ra_min, ra_max)
        self.assertAlmostEqual(dec_min, -2)
        self.assertAlmostEqual(dec_max, 2)

    def test_circle_uses_the_radius(self):
        ra_min, ra_max, dec_min, dec_max = services.footprint_bbox("CIRCLE ICRS 10 0 1", None, None)
        self.assertAlmostEqual(ra_min, 9)
        self.assertAlmostEqual(ra_max, 11)
        self.assertAlmostEqual(dec_min, -1)
        self.assertAlmostEqual(dec_max, 1)

    def test_missing_region_uses_a_two_degree_half_width(self):
        ra_min, ra_max, _dec_min, _dec_max = services.footprint_bbox("", 10, 0)
        self.assertAlmostEqual(ra_min, 8)
        self.assertAlmostEqual(ra_max, 12)

    def test_missing_region_near_zero_hours_wraps(self):
        ra_min, ra_max, _dec_min, _dec_max = services.footprint_bbox("", 1, 0)
        self.assertAlmostEqual(ra_min, 359)
        self.assertAlmostEqual(ra_max, 3)


def _image(**kwargs):
    values = {
        "obs_id": "obs",
        "access_url": "https://example.test/obs.fits",
        "ra_center": 10,
        "dec_center": 0,
        "ra_min": 8,
        "ra_max": 12,
        "dec_min": -2,
        "dec_max": 2,
        "observation_date": timezone.now(),
        "collection": "spherex_dr1",
    }
    values.update(kwargs)
    return SpherexImage.objects.create(**values)


class LocalCoverageTests(TestCase):
    def test_point_inside_the_box_is_returned(self):
        image = _image()
        _image(access_url="https://example.test/other.fits", ra_min=20, ra_max=24, ra_center=22, dec_center=0)
        coord = SkyCoord(10, 0, unit="deg")
        found = services.local_images_covering(coord, "spherex_dr1")
        self.assertEqual([item.pk for item in found], [image.pk])

    def test_wrap_around_zero_hours(self):
        image = _image(
            access_url="https://example.test/wrap.fits",
            ra_center=1,
            ra_min=350,
            ra_max=10,
            dec_center=-56,
            dec_min=-58,
            dec_max=-54,
        )
        inside = services.local_images_covering(SkyCoord(1, -56, unit="deg"), "spherex_dr1")
        outside = services.local_images_covering(SkyCoord(100, -56, unit="deg"), "spherex_dr1")
        self.assertEqual([item.pk for item in inside], [image.pk])
        self.assertEqual(outside, [])


class SearchStoreTests(TestCase):
    def _table(self):
        return Table({
            "access_url": ["https://example.test/new.fits"],
            "obs_id": ["obs-1"],
            "s_ra": [10.0],
            "s_dec": [0.0],
            "s_region": ["POLYGON ICRS 8 -2 12 -2 12 2 8 2"],
            "t_min": [60000.0],
            "em_min": [1.1e-6],
            "em_max": [1.6e-6],
            "energy_bandpassname": ["SPHEREx-D2"],
        })

    @patch("search.services.Irsa.query_sia")
    def test_stores_the_footprint_and_counts_only_new_urls(self, query):
        query.return_value = self._table()
        images, new_count = services.search_and_store("10", "0", collection="spherex_dr1")
        self.assertEqual(new_count, 1)
        self.assertAlmostEqual(images[0].ra_min, 8)
        self.assertAlmostEqual(images[0].ra_max, 12)
        _images, again = services.search_and_store("10", "0", collection="spherex_dr1")
        self.assertEqual(again, 0)

    @patch("search.services.Irsa.query_sia", side_effect=RuntimeError("502"))
    def test_irsa_failure_raises(self, _query):
        with self.assertRaises(services.SearchError):
            services.search_and_store("10", "0", collection="spherex_dr1")

    @patch("search.services.Irsa.query_sia")
    def test_stores_every_sia_row_and_returns_the_newest_for_the_list(self, query):
        total = services.MAX_RESULTS + 5
        query.return_value = Table({
            "access_url": [f"https://example.test/all-{index}.fits" for index in range(total)],
            "obs_id": [f"obs-{index}" for index in range(total)],
            "s_ra": [10.0] * total,
            "s_dec": [0.0] * total,
            "s_region": ["POLYGON ICRS 8 -2 12 -2 12 2 8 2"] * total,
            "t_min": [60000.0 + index for index in range(total)],
            "em_min": [1.1e-6] * total,
            "em_max": [1.6e-6] * total,
            "energy_bandpassname": ["SPHEREx-D2"] * total,
        })
        images, new_count = services.search_and_store("10", "0", collection="spherex_dr1")
        self.assertEqual(new_count, total)
        self.assertEqual(SpherexImage.objects.count(), total)
        self.assertEqual(len(images), services.MAX_RESULTS)
        self.assertEqual(images[-1].obs_id, f"obs-{total - 1}")


class RefreshViewTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request(self):
        return self.factory.get("/refresh/", {
            "ra": "10",
            "dec": "0",
            "fov": "60",
            "unit": "arcsec",
            "collection": "spherex_dr1",
            "detector": "2",
        })

    @patch("search.services.list_spherex_collections", return_value=["spherex_dr1"])
    @patch("search.services.search_and_store", side_effect=services.SearchError("down"))
    @patch("search.services.local_images_covering", return_value=[])
    def test_unavailable_without_cache(self, _local, _store, _collections):
        response = views.refresh(self._request())
        body = json.loads(response.content)
        self.assertEqual(body["status"], "unavailable")
        self.assertEqual(body["irsa_state"], "failed")
        self.assertNotIn("frames", body)


class CutoutViewTests(TestCase):
    def test_response_contains_the_png_bytes(self):
        image = _image()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "cut.png"
        payload = b"\x89PNG\r\n\x1a\nrest"
        path.write_bytes(payload)
        request = RequestFactory().get("/", {"ra": "10", "dec": "0", "fov": "60", "unit": "arcsec"})
        with patch("search.services.cached_cutout", return_value=path):
            response = views.cutout(request, image.pk)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(response.content, payload)

    def test_empty_file_is_an_error(self):
        image = _image(access_url="https://example.test/empty.fits")
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "empty.png"
        path.write_bytes(b"")
        request = RequestFactory().get("/", {"ra": "10", "dec": "0", "fov": "60", "unit": "arcsec"})
        with patch("search.services.cached_cutout", return_value=path):
            response = views.cutout(request, image.pk)
        self.assertEqual(response.status_code, 502)
        self.assertIn(b"could not be generated", response.content)


class CollectionLabelTests(SimpleTestCase):
    def test_data_release_labels(self):
        self.assertEqual(str(services.collection_label("spherex_dr1")), "Data Release 1")
        self.assertEqual(str(services.collection_label("spherex_dr1_deep")), "Data Release 1 (deep survey)")
        self.assertEqual(str(services.collection_label("spherex_dr1_cube")), "Data Release 1 (cube)")


class CollectionSyncTests(TestCase):
    def setUp(self):
        services._COLLECTION_CACHE["names"] = []
        services._COLLECTION_CACHE["expires"] = 0.0
        SpherexCollection.objects.all().delete()

    def tearDown(self):
        services._COLLECTION_CACHE["names"] = []
        services._COLLECTION_CACHE["expires"] = 0.0

    @patch("search.services.Irsa.list_collections")
    def test_irsa_success_stores_new_names(self, list_collections):
        list_collections.return_value = Table({"collection": ["spherex_dr1", "spherex_qr3"]})
        names = services.list_spherex_collections()
        self.assertEqual(names, ["spherex_qr3", "spherex_dr1"])
        self.assertEqual(
            set(SpherexCollection.objects.values_list("name", flat=True)),
            {"spherex_dr1", "spherex_qr3"},
        )

    @patch("search.services.Irsa.list_collections", side_effect=RuntimeError("502"))
    def test_irsa_failure_uses_database_rows(self, _list_collections):
        SpherexCollection.objects.create(name="spherex_dr1")
        SpherexCollection.objects.create(name="spherex_qr3")
        names = services.list_spherex_collections()
        self.assertEqual(names, ["spherex_qr3", "spherex_dr1"])

    @patch("search.services.Irsa.list_collections", side_effect=RuntimeError("502"))
    def test_irsa_failure_with_empty_database_uses_fallback(self, _list_collections):
        names = services.list_spherex_collections()
        self.assertEqual(names, list(services.FALLBACK_COLLECTIONS))

    @patch("search.services.Irsa.list_collections")
    def test_memory_ttl_skips_a_second_irsa_call(self, list_collections):
        list_collections.return_value = Table({"collection": ["spherex_qr3"]})
        first = services.list_spherex_collections()
        second = services.list_spherex_collections()
        self.assertEqual(first, ["spherex_qr3"])
        self.assertEqual(second, ["spherex_qr3"])
        self.assertEqual(list_collections.call_count, 1)

    @patch("search.services.Irsa.list_collections")
    def test_changed_remote_set_replaces_database_rows(self, list_collections):
        SpherexCollection.objects.create(name="spherex_qr2")
        list_collections.return_value = Table({"collection": ["spherex_dr1", "spherex_qr3"]})
        services.list_spherex_collections()
        self.assertEqual(
            set(SpherexCollection.objects.values_list("name", flat=True)),
            {"spherex_dr1", "spherex_qr3"},
        )

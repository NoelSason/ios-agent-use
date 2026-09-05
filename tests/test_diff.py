import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from iosagent import diff, png
from iosagent.png import Image


def canvas(w, h, rgb=(20, 20, 20)):
    return Image(w, h, bytearray(bytes(rgb) * (w * h)))


def fill(image, x, y, w, h, rgb):
    for py in range(y, y + h):
        for px in range(x, x + w):
            image.set_pixel(px, py, rgb)


class PixelDiff(unittest.TestCase):
    def run_pair(self, before, after, **kwargs):
        with TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a.png", Path(tmp) / "b.png"
            png.write_png(a, before)
            png.write_png(b, after)
            return diff.pixels(a, b, work_dir=Path(tmp) / "w", **kwargs)

    def test_identical_images_report_no_change(self):
        image = canvas(200, 160)
        self.assertTrue(self.run_pair(image, image).identical)

    def test_finds_a_change_in_a_dark_interface(self):
        # a dark panel on a near-black ground: the case a mean-based threshold missed
        before = canvas(200, 160, (8, 8, 8))
        after = canvas(200, 160, (8, 8, 8))
        fill(after, 120, 20, 60, 80, (40, 40, 46))
        result = self.run_pair(before, after)
        self.assertFalse(result.identical)
        self.assertGreaterEqual(len(result.regions), 1)

    def test_region_covers_the_area_that_changed(self):
        before = canvas(200, 160)
        after = canvas(200, 160)
        fill(after, 100, 40, 48, 48, (240, 240, 240))
        region = self.run_pair(before, after).regions[0]
        self.assertLessEqual(region.x, 100)
        self.assertLessEqual(region.y, 40)
        self.assertGreaterEqual(region.x + region.w, 148)
        self.assertGreaterEqual(region.y + region.h, 88)

    def test_regions_can_be_reported_in_points(self):
        before = canvas(200, 160)
        after = canvas(200, 160)
        fill(after, 100, 40, 48, 48, (240, 240, 240))
        pixels_only = self.run_pair(before, after)
        in_points = self.run_pair(before, after, frame_points=(400.0, 320.0))
        self.assertEqual(in_points.units, "pt")
        self.assertEqual(pixels_only.units, "px")
        # 200px wide source described as 400pt: points are twice the pixels
        self.assertAlmostEqual(in_points.regions[0].x, pixels_only.regions[0].x * 2, delta=4)

    def test_transposed_dimensions_are_explained_not_crashed(self):
        result = self.run_pair(canvas(200, 160), canvas(160, 200))
        self.assertFalse(result.identical)
        self.assertIn("rotated", result.note)

    def test_separate_changes_become_separate_regions(self):
        before = canvas(300, 240)
        after = canvas(300, 240)
        fill(after, 10, 10, 40, 40, (255, 255, 255))
        fill(after, 220, 180, 40, 40, (255, 255, 255))
        self.assertEqual(len(self.run_pair(before, after).regions), 2)


if __name__ == "__main__":
    unittest.main()

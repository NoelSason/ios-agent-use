import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from iosagent import png
from iosagent.png import Image


def solid(w, h, rgb):
    return Image(w, h, bytearray(bytes(rgb) * (w * h)))


class PNGRoundTrip(unittest.TestCase):
    def test_write_then_read_preserves_pixels(self):
        image = solid(7, 5, (10, 200, 30))
        image.set_pixel(3, 2, (1, 2, 3))
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.png"
            png.write_png(path, image)
            back = png.read_png(path)
        self.assertEqual((back.width, back.height), (7, 5))
        self.assertEqual(back.pixel(3, 2), (1, 2, 3))
        self.assertEqual(back.pixel(0, 0), (10, 200, 30))

    def test_dimensions_reads_header_only(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.png"
            png.write_png(path, solid(13, 4, (0, 0, 0)))
            self.assertEqual(png.dimensions(path), (13, 4))

    def test_rejects_non_png(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.png"
            path.write_bytes(b"not a png at all")
            with self.assertRaises(png.PNGError):
                png.dimensions(path)


class Rotation(unittest.TestCase):
    def setUp(self):
        # a 3x2 image with a unique colour per pixel, so orientation is provable
        self.image = Image(3, 2, bytearray(range(3 * 2 * 3)))

    def test_rotation_transposes_dimensions(self):
        turned = png.rotate(self.image, clockwise=True)
        self.assertEqual((turned.width, turned.height), (2, 3))

    def test_four_quarter_turns_is_identity(self):
        turned = self.image
        for _ in range(4):
            turned = png.rotate(turned, clockwise=True)
        self.assertEqual(turned.pixels, self.image.pixels)

    def test_clockwise_moves_top_left_to_top_right(self):
        turned = png.rotate(self.image, clockwise=True)
        self.assertEqual(turned.pixel(turned.width - 1, 0), self.image.pixel(0, 0))

    def test_counter_clockwise_is_the_inverse_of_clockwise(self):
        turned = png.rotate(png.rotate(self.image, True), False)
        self.assertEqual(turned.pixels, self.image.pixels)


class Composition(unittest.TestCase):
    def test_side_by_side_is_wide_enough_for_both(self):
        canvas = png.side_by_side(solid(4, 3, (255, 0, 0)), solid(6, 3, (0, 0, 255)), gap=2)
        self.assertEqual((canvas.width, canvas.height), (12, 3))
        self.assertEqual(canvas.pixel(0, 0), (255, 0, 0))
        self.assertEqual(canvas.pixel(6, 0), (0, 0, 255))

    def test_draw_rect_clips_at_the_edges(self):
        image = solid(5, 5, (0, 0, 0))
        png.draw_rect(image, 3, 3, 10, 10, rgb=(255, 255, 255), thickness=1)
        self.assertEqual(image.pixel(4, 3), (255, 255, 255))


if __name__ == "__main__":
    unittest.main()

import math
import unittest

from hera_app.tissue_scan import FieldCalibration, FocusSurface, build_tissue_plan, select_tissue_test_tiles


class TissueGeometryTests(unittest.TestCase):
    def test_landmark_direction_and_non_square_rotated_field(self):
        # The same feature moves right/down when the Stage moves in the negative scan direction.
        calibration = FieldCalibration.from_landmarks(
            [(100, 100, 3, 4), (500, 100, 3, 3.6), (100, 400, 3.3, 4)], (1000, 600)
        )
        for actual, expected in zip(calibration.right, (0, 1)):
            self.assertAlmostEqual(actual, expected)
        for actual, expected in zip(calibration.down, (-0.6, 0)):
            self.assertAlmostEqual(actual, expected)

    def test_calibration_rejects_small_or_collinear_captures(self):
        for points in (
            [(0, 0, 0, 0), (1, 0, 0.1, 0), (0, 400, 0, 0.4)],
            [(0, 0, 0, 0), (400, 0, 0.4, 0), (800, 0, 0.8, 0)],
            [(0, 0, 0, 0), (400, 0, 0.4, 0), (0, 400, 0.8, 0)],
        ):
            with self.assertRaises(ValueError):
                FieldCalibration.from_landmarks(points, (1000, 1000))

    def make_bounds(self, calibration, origin, width=3, height=2):
        bounds = {}
        for name, (u, v) in {"Left": (0, height / 2), "Right": (width, height / 2),
                             "Top": (width / 2, 0), "Bottom": (width / 2, height)}.items():
            x, y = calibration.stage_xy(u, v, origin)
            bounds[name] = (x, y, 1000 + 3 * x + 2 * y)
        return bounds

    def test_grid_has_ten_percent_overlap_full_coverage_and_serpentine_order(self):
        angle = math.radians(27)
        calibration = FieldCalibration((math.cos(angle), math.sin(angle)),
                                       (-0.7 * math.sin(angle), 0.7 * math.cos(angle)))
        origin = (-9, 13)
        plan = build_tissue_plan(calibration, self.make_bounds(calibration, origin), margin=0)
        self.assertEqual((plan["rows"], plan["columns"]), (3, 4))
        tiles = plan["tiles"]
        self.assertEqual(tiles[0]["name"], "R001-C001")
        self.assertEqual([tile["column"] for tile in tiles[4:8]], [4, 3, 2, 1])
        us = sorted({tile["u"] for tile in tiles})
        vs = sorted({tile["v"] for tile in tiles})
        self.assertAlmostEqual(us[1] - us[0], 0.9)
        self.assertAlmostEqual(vs[1] - vs[0], 0.9)
        left, top, right, bottom = plan["bounds"]
        self.assertLessEqual(us[0] - 0.5, left + 1e-12)
        self.assertGreaterEqual(us[-1] + 0.5, right - 1e-12)
        self.assertLessEqual(vs[0] - 0.5, top + 1e-12)
        self.assertGreaterEqual(vs[-1] + 0.5, bottom - 1e-12)
        for tile in tiles:
            self.assertAlmostEqual(tile["z"], 1000 + 3 * tile["x"] + 2 * tile["y"])

    def test_small_tissue_needs_only_one_tile(self):
        calibration = FieldCalibration((1, 0), (0, 1))
        plan = build_tissue_plan(calibration, self.make_bounds(calibration, (0, 0), 0.2, 0.3), margin=0)
        self.assertEqual(len(plan["tiles"]), 1)

    def test_internal_focus_changes_prediction_and_preserves_measured_values(self):
        points = [(0, 1, 1000), (2, 1, 1000), (1, 0, 1000), (1, 2, 1000)]
        flat = FocusSurface(points)
        curved = FocusSurface(points + [(1, 1, 1008)])
        self.assertAlmostEqual(flat.predict(1, 1), 1000)
        self.assertAlmostEqual(curved.predict(1, 1), 1008)
        self.assertGreater(curved.predict(1.1, 1), 1004)
        for x, y, z in points:
            self.assertAlmostEqual(curved.predict(x, y), z)
        self.assertTrue(curved.contains(1, 1))
        self.assertFalse(curved.contains(3, 3))

    def test_boundary_without_z_uses_additional_focus(self):
        calibration = FieldCalibration((1, 0), (0, 1))
        boundaries = self.make_bounds(calibration, (0, 0))
        boundaries = {name: (x, y, None) for name, (x, y, _) in boundaries.items()}
        with self.assertRaises(ValueError):
            build_tissue_plan(calibration, boundaries)
        plan = build_tissue_plan(calibration, boundaries, [(0, 0, 1000), (3, 0, 1003), (0, 2, 1002)])
        self.assertTrue(all(math.isfinite(tile["z"]) for tile in plan["tiles"]))

    def test_focus_rejects_inconsistent_duplicates_and_collinear_points(self):
        for points in ([(0, 0, 1), (1, 0, 2), (2, 0, 3)],
                       [(0, 0, 1), (0, 0, 5), (1, 0, 1), (0, 1, 1)]):
            with self.assertRaises(ValueError):
                FocusSurface(points)

    def test_invalid_bounds_or_huge_grid_rejected_before_allocation(self):
        calibration = FieldCalibration((1, 0), (0, 1))
        boundaries = self.make_bounds(calibration, (0, 0))
        boundaries["Left"], boundaries["Right"] = boundaries["Right"], boundaries["Left"]
        with self.assertRaises(ValueError):
            build_tissue_plan(calibration, boundaries)
        with self.assertRaises(ValueError):
            build_tissue_plan(calibration, self.make_bounds(calibration, (0, 0), 1e12, 2))

    def test_two_by_two_selection_keeps_serpentine_order_and_handles_edges(self):
        calibration = FieldCalibration((1, 0), (0, 1))
        plan = build_tissue_plan(calibration, self.make_bounds(calibration, (0, 0)), margin=0)
        chosen = select_tissue_test_tiles(plan["tiles"], (1, 1))
        self.assertEqual([(t["row"], t["column"]) for t in chosen], [(1, 1), (1, 2), (2, 2), (2, 1)])
        chosen = select_tissue_test_tiles(plan["tiles"], (3, 4))
        self.assertEqual({(t["row"], t["column"]) for t in chosen}, {(2, 3), (2, 4), (3, 3), (3, 4)})
        with self.assertRaises(ValueError):
            select_tissue_test_tiles(plan["tiles"][:4], (1, 1))


if __name__ == "__main__":
    unittest.main()

"""Geometry for fixed-FOV tissue mosaics, independent of camera and stage drivers."""

import copy
import math
from dataclasses import dataclass


def _finite(values):
    if not all(math.isfinite(float(value)) for value in values):
        raise ValueError("Coordinates must be finite.")


def validate_tissue_plan(source):
    plan = copy.deepcopy(source)
    if len(plan["field_right_mm"]) != 2 or len(plan["field_down_mm"]) != 2:
        raise ValueError("The plan has invalid field vectors.")
    calibration = FieldCalibration(tuple(plan["field_right_mm"]), tuple(plan["field_down_mm"]))
    origin = tuple(float(value) for value in plan["origin"])
    if len(origin) != 2:
        raise ValueError("The plan has an invalid origin.")
    _finite(origin)
    for key in ("rows", "columns"):
        if not isinstance(plan[key], int) or not 1 <= plan[key] <= 10000:
            raise ValueError("The plan has invalid grid dimensions.")
    if not 0 < len(plan["tiles"]) <= 10000:
        raise ValueError("The plan has an invalid tile count.")
    if plan["signature"]["rotation"] not in (0, 90, 180, 270):
        raise ValueError("The plan has an invalid image orientation.")

    def roi_tuple(value):
        if not isinstance(value, (tuple, list)) or len(value) != 4 or any(not isinstance(v, int) for v in value) or min(value[:2]) < 0 or min(value[2:]) <= 0:
            raise ValueError("The plan has an invalid ROI.")
        return list(value)

    roi = roi_tuple(plan["signature"]["roi"])
    names, cells = set(), set()
    for tile in plan["tiles"]:
        name = tile["name"]
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ValueError("Site names must be nonempty and unique.")
        cell = (tile["row"], tile["column"])
        if any(not isinstance(v, int) for v in cell) or not (1 <= cell[0] <= plan["rows"] and 1 <= cell[1] <= plan["columns"]) or cell in cells:
            raise ValueError("The plan has invalid or duplicate tile row/column labels.")
        names.add(name)
        cells.add(cell)
        for key in ("x", "y", "z"):
            tile[key] = float(tile[key])
        _finite((tile["x"], tile["y"], tile["z"]))
        tile["u"], tile["v"] = calibration.project((tile["x"], tile["y"]), origin)
        tile["roi"] = roi_tuple(tile.get("roi", roi))
        if not isinstance(tile.get("z_is_real", True), bool):
            raise ValueError("The plan has an invalid real-Z flag.")
    _finite((plan["overlap_percent"],))
    if not 0 <= plan["overlap_percent"] < 100:
        raise ValueError("The plan has invalid overlap.")
    return plan


def _inverse_basis(u, v, point):
    determinant = u[0] * v[1] - u[1] * v[0]
    if abs(determinant) <= math.hypot(*u) * math.hypot(*v) * 0.05:
        raise ValueError("The two calibrated directions are nearly parallel.")
    return ((v[1] * point[0] - v[0] * point[1]) / determinant,
            (-u[1] * point[0] + u[0] * point[1]) / determinant)


@dataclass(frozen=True)
class FieldCalibration:
    right: tuple
    down: tuple

    def __post_init__(self):
        _finite((*self.right, *self.down))
        if min(math.hypot(*self.right), math.hypot(*self.down)) <= 1e-9:
            raise ValueError("Calibrated field size must be greater than zero.")
        _inverse_basis(self.right, self.down, (0.0, 0.0))

    def project(self, xy, origin):
        return _inverse_basis(self.right, self.down, (xy[0] - origin[0], xy[1] - origin[1]))

    def stage_xy(self, u, v, origin):
        return (origin[0] + u * self.right[0] + v * self.down[0],
                origin[1] + u * self.right[1] + v * self.down[1])

    @classmethod
    def from_landmarks(cls, points, image_size):
        """Each record is (display pixel x/y, Stage x/y) for the same landmark."""
        if len(points) != 3:
            raise ValueError("Capture the same landmark at A, B and C first.")
        _finite(value for point in points for value in point)
        width, height = image_size
        if width <= 0 or height <= 0:
            raise ValueError("No live image is available.")
        a, b, c = points
        p = (b[0] - a[0], b[1] - a[1])
        q = (c[0] - a[0], c[1] - a[1])
        if min(math.hypot(p[0] / width, p[1] / height),
               math.hypot(q[0] / width, q[1] / height)) < 0.15:
            raise ValueError("Move the landmark farther between captures (at least 15% of the field).")
        # A fixed landmark moves opposite to the direction in which the FOV scans.
        sx = (b[2] - a[2], c[2] - a[2])
        sy = (b[3] - a[3], c[3] - a[3])
        bx = _inverse_basis((p[0], q[0]), (p[1], q[1]), sx)
        by = _inverse_basis((p[0], q[0]), (p[1], q[1]), sy)
        return cls((-bx[0] * width, -by[0] * width),
                   (-bx[1] * height, -by[1] * height))


class FocusSurface:
    """Least-squares tilt with inverse-distance interpolation of focus residuals."""

    def __init__(self, points):
        import numpy as np

        if len(points) < 3:
            raise ValueError("Capture at least three focused, non-collinear positions.")
        _finite(value for point in points for value in point)
        self.xy = np.asarray([point[:2] for point in points], dtype=float)
        self.z = np.asarray([point[2] for point in points], dtype=float)
        for i, xy in enumerate(self.xy):
            for j in range(i):
                if float(np.linalg.norm(xy - self.xy[j])) < 1e-7 and abs(self.z[i] - self.z[j]) > 0.1:
                    raise ValueError("Two focus readings at the same XY disagree; replace the old focus point.")
        self.origin = self.xy.mean(axis=0)
        self.scale = max(float(np.max(np.linalg.norm(self.xy - self.origin, axis=1))), 1e-9)
        normalized = (self.xy - self.origin) / self.scale
        design = np.column_stack((normalized, np.ones(len(points))))
        self.plane, _, rank, singular = np.linalg.lstsq(design, self.z, rcond=None)
        if rank < 3 or singular[-1] / singular[0] < 1e-4:
            raise ValueError("Focus points lie on one line. Add a focused point away from that line.")
        self.residual = self.z - design @ self.plane
        self.max_residual_um = float(np.max(np.abs(self.residual)))
        self.hull = _convex_hull([tuple(xy) for xy in self.xy])

    def predict(self, x, y):
        import numpy as np

        xy = np.asarray((x, y), dtype=float)
        distance_squared = np.sum((self.xy - xy) ** 2, axis=1)
        nearest = int(np.argmin(distance_squared))
        if distance_squared[nearest] < 1e-14:
            return float(self.z[nearest])
        weights = 1.0 / distance_squared
        normalized = (xy - self.origin) / self.scale
        trend = float(np.dot((*normalized, 1.0), self.plane))
        return trend + float(np.dot(weights, self.residual) / weights.sum())

    def contains(self, x, y):
        return all(_cross(a, b, (x, y)) >= -1e-10
                   for a, b in zip(self.hull, self.hull[1:] + self.hull[:1]))


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _convex_hull(points):
    points = sorted(set(points))
    halves = []
    for ordered in (points, list(reversed(points))):
        half = []
        for point in ordered:
            while len(half) > 1 and _cross(half[-2], half[-1], point) <= 0:
                half.pop()
            half.append(point)
        halves.append(half[:-1])
    return halves[0] + halves[1]


def _axis_centers(low, high, overlap, limit):
    span = high - low
    if span <= 1:
        return [(low + high) / 2]
    step = 1 - overlap
    count = math.ceil((span - 1) / step - 1e-10) + 1
    if count > limit:
        raise ValueError(f"Grid exceeds {limit} tiles. Check field calibration and boundaries.")
    excess = 1 + (count - 1) * step - span
    first = low + 0.5 - excess / 2
    return [first + i * step for i in range(count)]


def select_tissue_test_tiles(tiles, selected_cell):
    cells = {(tile["row"], tile["column"]) for tile in tiles}
    if selected_cell not in cells:
        raise ValueError("Select an available tile first.")
    row, column = selected_cell
    for start_row in (row, row - 1):
        for start_column in (column, column - 1):
            block = {(start_row, start_column), (start_row, start_column + 1),
                     (start_row + 1, start_column), (start_row + 1, start_column + 1)}
            if block <= cells:
                return [tile for tile in tiles if (tile["row"], tile["column"]) in block]
    raise ValueError("No complete adjacent 2 x 2 block includes this tile. Select another tile.")


def remove_tissue_tile(source, cell):
    return remove_tissue_tiles(source, {cell})


def remove_tissue_tiles(source, cells):
    cells = set(cells)
    available = {(tile["row"], tile["column"]) for tile in source["tiles"]}
    if not cells or not cells <= available:
        raise ValueError("Select an available tile first.")
    if len(cells) >= len(source["tiles"]):
        raise ValueError("Keep at least one tile in the plan.")
    plan = copy.deepcopy(source)
    plan["tiles"] = [tile for tile in plan["tiles"] if (tile["row"], tile["column"]) not in cells]
    plan["focus_extrapolated_count"] = sum(tile.get("focus_extrapolated", False) for tile in plan["tiles"])
    return plan


def build_tissue_plan(calibration, boundaries, extra_focus=(), margin=0.05, max_tiles=10000, overlap_percent=10):
    _finite((margin, overlap_percent))
    if not 0 <= margin <= 1:
        raise ValueError("Edge margin must be between 0 and 100% of one field.")
    if not 0 <= overlap_percent < 100:
        raise ValueError("Overlap must be between 0% (inclusive) and 100% (exclusive).")
    if set(boundaries) != {"Left", "Right", "Top", "Bottom"}:
        raise ValueError("Capture Left, Right, Top and Bottom boundaries first.")
    _finite(value for point in boundaries.values() for value in point if value is not None)
    origin = tuple(boundaries["Left"][:2])
    projected = {key: calibration.project(point[:2], origin) for key, point in boundaries.items()}
    left, right = projected["Left"][0], projected["Right"][0]
    top, bottom = projected["Top"][1], projected["Bottom"][1]
    if right <= left or bottom <= top:
        raise ValueError("Boundary order is reversed. Use Left/Right/Top/Bottom as seen in Live View.")
    focus = [tuple(point) for point in boundaries.values() if point[2] is not None]
    focus.extend(extra_focus)
    surface = FocusSurface(focus)
    xs = _axis_centers(left - margin, right + margin, overlap_percent / 100, max_tiles)
    ys = _axis_centers(top - margin, bottom + margin, overlap_percent / 100, max_tiles)
    if len(xs) * len(ys) > max_tiles:
        raise ValueError(f"Grid has {len(xs) * len(ys)} tiles; limit is {max_tiles}. Check field calibration and boundaries.")
    tiles = []
    for row, v in enumerate(ys, 1):
        columns = range(len(xs)) if row % 2 else reversed(range(len(xs)))
        for column in columns:
            u = xs[column]
            x, y = calibration.stage_xy(u, v, origin)
            tiles.append({"name": f"R{row:03d}-C{column + 1:03d}", "row": row,
                          "column": column + 1, "x": x, "y": y, "z": surface.predict(x, y),
                          "u": u, "v": v, "focus_extrapolated": not surface.contains(x, y)})
    return {"tiles": tiles, "rows": len(ys), "columns": len(xs), "overlap_percent": overlap_percent,
            "bounds": (left - margin, top - margin, right + margin, bottom + margin),
            "origin": origin, "field_right_mm": calibration.right, "field_down_mm": calibration.down,
            "focus_residual_um": surface.max_residual_um,
            "focus_extrapolated_count": sum(tile["focus_extrapolated"] for tile in tiles)}

"""Read FL Studio's playlist geometry out of a screenshot.

FL Studio paints its own UI: it exposes no accessibility tree and no native menu, so
a screenshot is the only read (see apps/fl-studio-2025.md).  This tool answers the
questions a screenshot can answer reliably:

  lanes     -- how many clip lanes the playlist shows, and where each one is
  geometry  -- each lane's clip extent: the first/last column with waveform pixels,
               its width in pixels, and how densely it is filled
  clock     -- where the transport clock (M:S:CS) sits, so it can be cropped and read

What it deliberately does NOT do: convert pixels to time.  That needs two ruler
clicks and the clock values (measured: ~1.2 px/s at "show all", so 0.5 s is half a
pixel), and fitting a lane's pixel envelope to the file's own audio envelope was
tried and does not work (r 0.3-0.6, wrong assignments for every lane).

Run with the provisioned interpreter (`py -3.14`), not `python`: it needs numpy and
Pillow, which live there.

    py -3.14 flplaylist.py lanes    fl.png [--x0 716]
    py -3.14 flplaylist.py geometry fl.png [--x0 1180] [--x1 2545]
    py -3.14 flplaylist.py clock    fl.png
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
from PIL import Image

DEFAULT_X0 = 716          # playlist content area starts here in every captured view


def _wave_mask(a):
    g, r, b = a[:, :, 1], a[:, :, 0], a[:, :, 2]
    return (g > 90) & (g > r + 25) & (g > b + 15)


def lane_bands(a, x0=DEFAULT_X0, x1=None, frac=0.15, gap=10, merge_gap=24, min_h=6):
    """Clip lanes: rows whose waveform pixels span most of the content width.

    A stereo clip draws as two halves, so bands closer than `merge_gap` px merge
    into one lane.
    """
    m = _wave_mask(a)
    x1 = x1 or a.shape[1]
    sub = m[:, x0:x1]
    rows = np.where(sub.sum(axis=1) > frac * sub.shape[1])[0]
    bands, start, prev = [], None, None
    for y in rows:
        if start is None:
            start = prev = y
            continue
        if y - prev <= gap:
            prev = y
        else:
            bands.append([int(start), int(prev)])
            start = prev = y
    if start is not None:
        bands.append([int(start), int(prev)])
    merged: list[list[int]] = []
    for band in [b for b in bands if b[1] - b[0] >= min_h]:
        if merged and band[0] - merged[-1][1] <= merge_gap:
            merged[-1][1] = band[1]
        else:
            merged.append(band)
    return [(a0, b0) for a0, b0 in merged]


def lane_extent(a, y0, y1, x0=DEFAULT_X0, x1=None, on=0.03):
    """First/last column with waveform pixels in a lane band, and its fill."""
    x1 = x1 or a.shape[1]
    m = _wave_mask(a[y0:y1 + 1, x0:x1])
    cols = m.mean(axis=0)
    live = np.where(cols > on)[0]
    if len(live) == 0:
        return {"x_start": None, "x_end": None, "px_len": 0, "fill": 0.0}
    return {"x_start": int(live.min()) + x0, "x_end": int(live.max()) + x0,
            "px_len": int(live.max() - live.min() + 1),
            "fill": round(float(m.mean()), 3)}


def clock_region(png):
    """The transport clock: the widest run of bright green digits in the top strip."""
    a = np.asarray(Image.open(png).convert("RGB")).astype(np.int16)
    g, r = a[:, :, 1], a[:, :, 0]
    m = (g > 150) & (g > r + 50) & (r < 130)
    cols = m[0:48, :].sum(axis=0) > 6
    best, start = (0, 0, 0), None
    for x, v in enumerate(list(cols) + [False]):
        if v and start is None:
            start = x
        elif not v and start is not None:
            if 20 < x - start < 400 and x - start > best[0]:
                best = (x - start, start, x - 1)
            start = None
    return None if best[0] == 0 else {"x0": best[1], "x1": best[2], "y0": 0, "y1": 46}


def main() -> int:
    cmd = sys.argv[1]
    png = sys.argv[2]
    x0, x1 = DEFAULT_X0, None
    args = sys.argv[3:]
    for i, v in enumerate(args):
        if v == "--x0":
            x0 = int(args[i + 1])
        elif v == "--x1":
            x1 = int(args[i + 1])
    a = np.asarray(Image.open(png).convert("RGB")).astype(np.int16)
    bands = lane_bands(a, x0, x1)
    if cmd == "clock":
        print(json.dumps(clock_region(png), ensure_ascii=False))
        return 0
    print(f"{png}: x {x0}..{x1 or a.shape[1]}; {len(bands)} lane(s)")
    rows = []
    for i, (y0, y1) in enumerate(bands):
        ext = lane_extent(a, y0, y1, x0, x1)
        rows.append({"lane": i, "y": [y0, y1], **ext})
        print(f"  lane {i}: y {y0:4d}-{y1:4d}  x {ext['x_start']}..{ext['x_end']}  "
              f"{ext['px_len']} px  fill {ext['fill']}")
    if cmd == "geometry" and rows:
        ref = rows[0]
        print(f"deltas against lane 0 ({ref['y']}):")
        for row in rows[1:]:
            if row["x_start"] is None or ref["x_start"] is None:
                continue
            print(f"  lane {row['lane']}: start {row['x_start'] - ref['x_start']:+5d} px   "
                  f"end {row['x_end'] - ref['x_end']:+5d} px   width {row['px_len'] - ref['px_len']:+5d} px")
    out = os.path.splitext(png)[0] + ".lanes.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"png": png, "x": [x0, x1], "clock": clock_region(png), "lanes": rows},
                  fh, ensure_ascii=False, indent=1)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

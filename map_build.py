"""Build docs/world_map.js: country outlines for the Countries picker map.

Source: world-atlas 2.0.2 (Natural Earth 1:110m, public domain), ref/countries-110m.json.
Countries too small to exist at 1:110m are drawn as dots (see DOTS).
Names are mapped to ReliefWeb's country names so they match docs/data/countries.json.
Run: python map_build.py   (only needed if the name mapping below changes)
"""
import json, math
from pathlib import Path

ROOT = Path(__file__).parent
SRC = ROOT / "ref" / "countries-110m.json"
OUT = ROOT / "docs" / "world_map.js"
W = 760
LAT_MIN, LAT_MAX = -57.0, 84.0

# Natural Earth name -> ReliefWeb name (only where they differ)
NAMES = {
    "Bolivia": "Bolivia (Plurinational State of)", "Bosnia and Herz.": "Bosnia and Herzegovina",
    "Brunei": "Brunei Darussalam", "Central African Rep.": "Central African Republic",
    "Dem. Rep. Congo": "Democratic Republic of the Congo", "Dominican Rep.": "Dominican Republic",
    "Eq. Guinea": "Equatorial Guinea", "eSwatini": "Eswatini", "Iran": "Iran (Islamic Republic of)",
    "Laos": "Lao People's Democratic Republic", "Macedonia": "North Macedonia",
    "New Caledonia": "New Caledonia (France)", "North Korea": "Democratic People's Republic of Korea",
    "South Korea": "Republic of Korea", "Palestine": "Occupied Palestinian territory",
    "Russia": "Russian Federation", "S. Sudan": "South Sudan", "Solomon Is.": "Solomon Islands",
    "Syria": "Syrian Arab Republic", "Tanzania": "United Republic of Tanzania", "Turkey": "Türkiye",
    "United Kingdom": "United Kingdom of Great Britain and Northern Ireland",
    "Venezuela": "Venezuela (Bolivarian Republic of)", "Vietnam": "Viet Nam",
    "W. Sahara": "Western Sahara", "Greenland": "Greenland (Denmark)",
    "Puerto Rico": "Puerto Rico (The United States of America)", "Taiwan": "China - Taiwan Province",
    "Falkland Is.": "Falkland Islands (Malvinas)",
}
# Drawn as part of another country, following ReliefWeb's (UN) country list
MERGE = {"Somaliland": "Somalia", "N. Cyprus": "Cyprus"}
SKIP = {"Antarctica", "Fr. S. Antarctic Lands"}
# Too small to exist at 1:110m: drawn as a dot at (longitude, latitude)
DOTS = {"Singapore": (103.82, 1.35)}

A1, A2, A3, A4 = 1.340264, -0.081106, 0.000893, 0.003796
SQ = math.sqrt(3) / 2
def equal_earth(lon, lat):
    lat = max(LAT_MIN, min(LAT_MAX, lat))
    t = math.asin(SQ * math.sin(math.radians(lat))); t2 = t * t; t6 = t2 * t2 * t2
    x = math.radians(lon) * math.cos(t) / (SQ * (A1 + 3 * A2 * t2 + t6 * (7 * A3 + 9 * A4 * t2)))
    y = t * (A1 + A2 * t2 + t6 * (A3 + A4 * t2))
    return x, y
X0, X1 = equal_earth(-180, 0)[0], equal_earth(180, 0)[0]
Y0, Y1 = equal_earth(0, LAT_MAX)[1], equal_earth(0, LAT_MIN)[1]
K = W / (X1 - X0)
H = round((Y0 - Y1) * K)
def px(lon, lat):
    x, y = equal_earth(lon, lat)
    return (x - X0) * K, (Y0 - y) * K

def load(path):
    t = json.loads(path.read_text(encoding="utf-8"))
    sx, sy = t["transform"]["scale"]; tx, ty = t["transform"]["translate"]
    arcs = []
    for a in t["arcs"]:
        x = y = 0; pts = []
        for dx, dy in a:
            x += dx; y += dy; pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)
    return t["objects"]["countries"]["geometries"], arcs

def rings_of(g):
    polys = [g["arcs"]] if g["type"] == "Polygon" else g["arcs"] if g["type"] == "MultiPolygon" else []
    return [r for p in polys for r in p]

def arc_pts(arcs, i):
    return arcs[i] if i >= 0 else arcs[~i][::-1]

def stitch(rings):
    """Merge rings of neighbouring shapes: drop the arcs they share, join the rest back into rings."""
    flat = [i for r in rings for i in r]
    have = set(flat)
    keep = [i for i in flat if ~i not in have]
    return keep

def merged_rings(arcs, ring_lists):
    keep = stitch([r for rl in ring_lists for r in rl])
    start = {}
    for i in keep:
        start.setdefault(tuple(arc_pts(arcs, i)[0]), []).append(i)
    used, out = set(), []
    for i in keep:
        if i in used: continue
        ring, cur = [], i
        while cur is not None and cur not in used:
            used.add(cur); ring.append(cur)
            end = tuple(arc_pts(arcs, cur)[-1])
            cur = next((j for j in start.get(end, []) if j not in used), None)
        out.append(ring)
    return out

def path(arcs, rings):
    d = []
    for r in rings:
        pts = []
        for i in r:
            p = arc_pts(arcs, i)
            pts.extend(p if not pts else p[1:])
        lons = [p[0] for p in pts]
        if max(lons) - min(lons) > 300:      # ring straddles the antimeridian (Fiji): keep it on the east edge
            pts = [(lon if lon > 0 else 180.0, lat) for lon, lat in pts]
        xy = [px(*p) for p in pts]
        s, last = [], None
        for x, y in xy:
            q = (round(x, 1), round(y, 1))
            if q != last: s.append(q); last = q
        if len(s) < 3: continue
        d.append("M" + "L".join(f"{x:g},{y:g}" for x, y in s) + "Z")
    return "".join(d)

def main():
    geoms, arcs = load(SRC)
    by = {g["properties"]["name"]: g for g in geoms}
    shapes = []
    for name, g in sorted(by.items()):
        if name in SKIP or name in MERGE: continue
        parts = [rings_of(g)] + [rings_of(by[k]) for k, v in MERGE.items() if v == name and k in by]
        rings = merged_rings(arcs, parts) if len(parts) > 1 else parts[0]
        d = path(arcs, rings)
        if d: shapes.append({"n": NAMES.get(name, name), "d": d})
    for n, (lon, lat) in DOTS.items():
        x, y = px(lon, lat)
        shapes.append({"n": n, "c": [round(x, 1), round(y, 1)]})
    js = "/* Built by map_build.py from Natural Earth 1:110m (public domain). Do not edit by hand. */\n" \
         "window.RW_MAP=" + json.dumps({"w": W, "h": H, "shapes": shapes}, ensure_ascii=False, separators=(",", ":")) + ";\n"
    OUT.write_text(js, encoding="utf-8")
    print(f"{OUT.name}: {len(shapes)} shapes, {len(js)//1024} KB, {W}x{H}")

if __name__ == "__main__":
    main()

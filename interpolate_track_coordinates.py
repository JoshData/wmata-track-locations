# Re-generate the GeoJSON file using scipy.interpolate to make
# smooth segments.

import collections, json
import numpy, scipy.interpolate

tracks = json.load(open("tracks.json"))

def interpolate_path(path):
	N = 10
	interp = scipy.interpolate.interp1d(
		[i*N for i in range(len(path))], # X
		numpy.array([(c["lng"], c["lat"]) for c in path]).T, # Y
		kind="cubic")
	return [
		dict(zip(("lng", "lat"), interp(i)))
		for i in range(N*(len(path)-1))
	]

# Write out in GeoJSON as linestrings, which is useful for quick
# plotting but loses the metadata on coordinates.
tracks_geojson = collections.OrderedDict([
    ("type", "FeatureCollection"),
    ("features",
    [
        # Track lines.
        collections.OrderedDict([
            ("type", "Feature"),
            ("properties", collections.OrderedDict([
                ("type", "track"),
                ("track", track["id"]),
                ("line", track["line"]),
            ])),
            ("geometry", collections.OrderedDict([
                ("type", "LineString"),
                ("coordinates", [ [pt["lng"], pt["lat"]] for pt in interpolate_path(track["path"]) ]),
            ]))
        ])
        for track in tracks
    ])
	])
with open("tracks.geojson", "w") as f:
    f.write(json.dumps(tracks_geojson, indent=2))


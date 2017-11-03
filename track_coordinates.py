# Read the archived gis.wmata.com data and infer track connectivity by
# finding the best order of points that share a TRACK_NAME attribute.
# Work around TRACK_NAME tracks having forks that prevent there being
# a single order of points. Save as JSON and GeoJSON. Convert points
# from the Web Mercator projection to lat/lng.

import glob, json, gzip, random
from collections import defaultdict, OrderedDict

import pyproj

# gis.wmata.com is serving coordinates in the Web Mercator projection, which was convenient for them to
# display on a map but very odd for us --- turn it into lat/lng.
proj = pyproj.Proj("+proj=merc +lon_0=0 +k=1 +x_0=0 +y_0=0 +a=6378137 +b=6378137 +units=m +no_defs ")

# Scan the archived data in time order by sorting filenames. Look for ocurrences
# where a train went from one position to another, but on the same track and going
# in the same direction, and increment a counter, so that we know what locations
# ocurr linearly on the track before other positions.

track_lines = defaultdict(lambda : set())
train_last_seen_at = { }
coords_on_track = defaultdict(lambda : set())
coord_observations = defaultdict(lambda : 0)
coord_transition_observations = defaultdict(lambda : 0)
window = []
for fn in sorted(glob.glob("data/*-gis.json.gz")):
	try:
		with gzip.open(fn) as f:
			gis_locations = json.loads(f.read().decode("ascii"))
	except Exception as e:
		print(fn, e)
		continue

	# Loop over trains.
	for train in gis_locations.get("features", []):
		# Some coordinates are very close to (0,0) which are invalid.
		if train["geometry"]["x"]**2 + train["geometry"]["y"]**2 < 1: continue
		trainid = train["attributes"]["ITT"]
		line = train["attributes"]["TRACKLINE"]
		track = train["attributes"]["TRACKNAME"]
		dest = train["attributes"]["DESTINATIONID"]
		coord = (train["geometry"]["x"], train["geometry"]["y"])

		# The "3" tracks are pocket tracks. They aren't continuous lines. Don't
		# include those here --- they need to be broken up into segments.
		if track[1] not in ("1", "2"): continue

		# Skip the Non-revenue routes which go along some unusual paths.
		if line == "Non-revenue": continue

		# Some of the distinctly labeled tracks are actually continuous:
		# A-B and C-D is the Red and Blue/Orange/Silver lines split at Metro Center.
		# E-F is the Green/Yellow lines split at Gallery Place. These line's
		# 1/2 tracks are the main tracks and the numbering is consistent. Relabel those.
		# Otherwise we get gaps in the tracks at those two stations where the
		# train goes from one track to another.
		import re
		track = re.sub("[AB]" ,"AB", track)
		track = re.sub("[CD]" ,"CD", track)
		track = re.sub("[EF]" ,"EF", track)

		# Ignore crazy routes.
		if track[0:2] == "AB" and line != "Red": continue
		if track[0:2] == "CD" and line not in ("Blue", "Orange", "Silver"): continue
		if track[0:2] == "EF" and line not in ("Yellow", "Green"): continue
		if track[0] == "G" and line != "Blue": continue # to Largo
		if track[0] == "J" and line != "Blue": continue # to Franconia
		if track[0] == "K" and line != "Orange": continue # to Vienna
		if track[0] == "N" and line != "Silver": continue # to Whiele

		# Both halves of the fork south of L'Enfant Plaza are classified here
		# as E1/2 tracks, and both halves of the fork north of the Pentagon
		# are labeled as C1/2 tracks. The Yellow Line connects one half of
		# each. There's also a fork south of Alexandria that are both C1/2
		# tracks until one path becomes J1/2 heading to Franconia, and one
		# south of Rosslyn that are both C1/2 until one becomes the J1/2
		# Orange line.
		#
		# Forks cause a problem for us because we are trying to connect
		# up long linear segments of track. We'll re-label some of the
		# forks according to the line of the train running on it. This
		# will split forks into separate track labels but also give us
		# duplicate track segments, which we'll weed out later.

		# Create a new track pair called L1/2 where the Yellow Line runs
		# on CD (north of Pentagon to Huntington) and EF (Greenbelt to
		# the Pentagon).
		if track[0:2] in ("CD", "EF") and line == "Yellow": track = "L" + track[2]

		# Turn the J tracks (Alexandria to Franconia) into CD tracks so
		# that they smoothly connect up to the CD tracks (otherwise we
		# get a gap).
		# J tracks so that we capture the segment where C and J merge.
		if track[0] == "J" and line == "Blue": track = "CD" + track[-1]

		# Map all of the Silver track to N.
		if line == "Silver": track = "N" + track[-1]

		# Remember that we saw this coordinate on this track.
		coords_on_track[track].add(coord)
		track_lines[track].add(line)
		coord_observations[(coord, track)] += 1

		# If the train is at a different position than when we last saw it
		# but on the same track + track direction, and not that long ago,
		# increment a counter for this transition.
		if trainid in train_last_seen_at \
			and train_last_seen_at[trainid][0] in window \
			and train_last_seen_at[trainid][1:3] == (track, dest) \
			and train_last_seen_at[trainid][3] != coord:
			coord_transition_observations[(track, train_last_seen_at[trainid][3], coord)] += 1
		train_last_seen_at[trainid] = (fn, track, dest, coord)

		# Keep a sliding window of recent filenames.
		window.append(fn)
		if len(window) > 4: window.pop(0) # if files were at 15sec intervals, then this limits to 1 minute

# We now have all of the coordinates on all of the tracks, but we don't know
# what order they ocurr in. Infer the order.
def vec(c1, c2): return (c2[0]-c1[0], c2[1]-c1[1])
def dot(v1, v2): return (v1[0]*v2[0] + v1[1]*v2[1])
def dist(c1, c2): return dot(vec(c1, c2), vec(c1, c2))**.5
def median(a) : return sorted(a)[int(len(a)/2)]
def infer_track_order(trackname):
	# What coordinates are on this track? Skip ones that were observed
	# only a few times --- these are data oddities.
	m = median([v for k, v in coord_observations.items() if k[1] == trackname])
	coords = { c for c in coords_on_track[trackname]  if coord_observations[(c, trackname)] >= m/2 }

	# Start with an empty track.
	track = []

	# Define a function that says how good this order is.
	def score_track_order(track):
		# The closer to 1 the cosines are along the path, the
		# straighter the path is.
		score = 0
		for i in range(len(track)-2):
			c0 = track[i]
			c1 = track[i+1]
			c2 = track[i+2]
			v1 = vec(c0, c1)
			v2 = vec(c1, c2)
			cosine = dot(v1, v2) / (dot(v1, v1)**.5 * dot(v2, v2)**.5)
			score -= (1 - cosine) * (dist(c0, c1) + dist(c1, c2))
		return score

	best_score = None
	while len(track) < len(coords):
		if len(track) == 0:
			# If the track is empty, add a random coordinate.
			track.append(random.choice(list(coords)))

		else:
			# Add the coordinate that's nearest to any coordinate already on the track.
			# Remember which one it is nearest too.
			coord = None
			coord_peg = None
			coord_dist = None
			for c1 in coords:
				if c1 in track: continue
				for i, c2 in enumerate(track):
					d = dist(c1, c2)
					if coord is None or d < coord_dist:
						coord = c1
						coord_peg = i
						coord_dist = d

			# Add it in the position in the track so far that keeps the track the smoothest,
			# either before or after the coordinate on the track it is closest to.
			best_index = 0
			best_score = None
			for index in [coord_peg, coord_peg+1]:
			#for index in range(len(track)+1):
				score = score_track_order(track[:index] + [coord] + track[index:])
				if best_score is None or score > best_score:
					best_index = index
					best_score = score
			track.insert(best_index, coord)

	print(trackname, best_score)
	
	return track

# Generate ordered tracks.
tracks = { trackname: infer_track_order(trackname) for trackname in sorted(coords_on_track) }

# In order to break up forks to different tracks, and to fill in gaps
# between track segments, we ended up duplicating some track segments.
# De-dup track segments now, giving preference to earlier tracks.
seen_segments = set()
deduped_tracks = {}
for track, path in sorted(tracks.items()):
	tracksegs = [[]]
	for i in range(len(path)-1):
		seg = (path[i], path[i+1])
		if seg in seen_segments:
			# Break the track here.
			if tracksegs[-1] != []:
				tracksegs.append([])
			continue
		else:
			# This segment is fresh. Add the first point in the
			# seg if we're at the start of a new trackseg, otherwise
			# just add the second point since we added the first point
			# as the end of the last seg last iteration.
			if tracksegs[-1] == []:
				tracksegs[-1].append(seg[0])
			tracksegs[-1].append(seg[1])
			seen_segments.add(seg)

	# Remove empty tracksegs and degenerate tracksegs with fewer than
	# five coordinates - no real revenue line is so short.
	tracksegs = list(filter(lambda seg : len(seg) > 5, tracksegs))

	# How many segments did this track get split into?
	print(track, len(tracksegs))

	# If de-duping resulted in one contiguous segment (but maybe smaller
	# than the original if the ends were trimmed), name it the same
	# as the original.
	if len(tracksegs) == 1:
		deduped_tracks[track] = tracksegs[0]

	# If de-duping resulted in multiple sub-segments, name them uniquely.
	else:
		for i, ts in enumerate(tracksegs):
			deduped_tracks[track + chr(ord('a')+i)] = ts
			
tracks = deduped_tracks

# Construct a JSON data structure for the tracks.		
tracks = [
	OrderedDict([
		("id", trackname),
		("line", ", ".join(sorted(track_lines[trackname]))),
		("path", [OrderedDict(zip(("lng", "lat"), proj(*coord, inverse=True))) for coord in path ]),
	])
	for trackname, path in sorted(tracks.items())
]
with open("tracks.json", "w") as f:
    f.write(json.dumps(tracks, indent=2))

# Also write out in GeoJSON as linestrings, which is useful for quick
# plotting but loses the metadata on coordinates.
tracks_geojson = OrderedDict([
    ("type", "FeatureCollection"),
    ("features",
    [
        # Track lines.
        OrderedDict([
            ("type", "Feature"),
            ("properties", OrderedDict([
                ("type", "track"),
                ("track", track["id"]),
                ("line", track["line"]),
            ])),
            ("geometry", OrderedDict([
                ("type", "LineString"),
                ("coordinates", [ [pt["lng"], pt["lat"]] for pt in track["path"] ]),
            ]))
        ])
        for track in tracks
    ])
	])
with open("tracks.geojson", "w") as f:
    f.write(json.dumps(tracks_geojson, indent=2))


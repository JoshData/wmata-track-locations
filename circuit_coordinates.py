import glob, json, gzip, collections, urllib.request

import numpy, scipy.interpolate
import pyproj

# gis.wmata.com is serving coordinates in the Web Mercator system, which was convenient for them but very odd.
proj = pyproj.Proj("+proj=merc +lon_0=0 +k=1 +x_0=0 +y_0=0 +a=6378137 +b=6378137 +units=m +no_defs ")

# Read our API key.
for line in open("api_key.inc"):
	if line.startswith("API_KEY="):
		API_KEY = line.strip().split("=")[1]

# Fetch from the WMATA API the ordering of circuits on the tracks.
routes = json.loads(urllib.request.urlopen(urllib.request.Request("https://api.wmata.com/TrainPositions/StandardRoutes?contentType=json", headers={ "api_key": API_KEY })).read().decode("ascii"))

# Fetch from the WMATA API the station information.
stations = json.loads(urllib.request.urlopen(urllib.request.Request("https://api.wmata.com/Rail.svc/json/jStations", headers={ "api_key": API_KEY })).read().decode("ascii"))
stations = { station["Code"]: station for station in stations["Stations"]  }

# Scan the pairs of circuit and GIS data.
all_coordinates = collections.defaultdict(lambda : 0)
circuit_coordinate_pairs = collections.defaultdict(lambda : 0)
for fn in sorted(glob.glob("data/*-circuit.json.gz")):
	try:
		circuit_locations = json.loads(gzip.open(fn).read().decode("ascii"))
		gis_locations = json.loads(gzip.open(fn.replace("circuit", "gis")).read().decode("ascii"))
	except Exception as e:
		print(fn, e)
		continue

	# Map train IDs to circuit IDs and coordinates at this moment in time.
	train_locations = { }
	for train in circuit_locations["TrainPositions"]:
		train_locations.setdefault(train["TrainId"], {})["circuit"] = train["CircuitId"]
		train_locations.setdefault(train["TrainId"], {})["duration"] = train["SecondsAtLocation"]
	for train in gis_locations.get("features", []):
		# Some coordinates are very close to (0,0) which are invalid.
		if train["geometry"]["x"]**2 + train["geometry"]["y"]**2 < 1: continue
		webmercatorcoord = (train["geometry"]["x"], train["geometry"]["y"])
		train_locations.setdefault(train["attributes"]["ITT"], {})["coordinate"] = webmercatorcoord
		all_coordinates[webmercatorcoord] += 1

	# For every train that has both a circuit and a coordinate,
	# accumulate a counter of how many times this circuit was paired with this
	# coordinate. Weight by the amount of time the train was reported at
	# the circuit.
	for train in train_locations.values():
		if train.get("circuit") and train.get("coordinate"):
			circuit_coordinate_pairs[(train["circuit"], train["coordinate"])] += 1 + train["duration"]

# Now map circuits to particular coordinates, choosing from among the
# coordinates that the circuit was ever paired with. To avoid coordinates
# getting mapped to multiple circuits, start with the most common circuit-coordinate
# pairs and go down that list, never assigning a circuit or coordinatem ore than once.
# For each circuit, take its most common coordinate.
circuit_coordinates = { }
seen_coordinates = set()
for (circuit, coordinate), count in sorted(circuit_coordinate_pairs.items(), key=lambda kv:-kv[1]):
	if circuit not in circuit_coordinates and coordinate not in seen_coordinates:
		circuit_coordinates[circuit] = coordinate
		seen_coordinates.add(coordinate)

# Construct a JSON file of tracks, with each track a list of lng/lat coordinates.
# Each coordinate is either an "interpolated" position between circuits, a
# "circuit", or a "station". Circuit IDs and station metadata is added to
# circuit and station points. TODO: Add non-revenue tracks which are missing
# from the track API?
tracks = []
seen_circuit_neighbors = set()
for routeinfo in sorted(routes["StandardRoutes"], key = lambda r : (r["LineCode"], r["TrackNum"])):
	# Track metadata.
	route = collections.OrderedDict([
		("line", routeinfo["LineCode"]),
		("track", routeinfo["TrackNum"]),
		("locations", []),
	])
	tracks.append(route)

	# Create an interpolation function that can give us coordinates between
	# circuits. Quadratic interpolation should give us better circular-like curves
	# but it gave garbage - cubic produced reasonable results.
	#
	# Note that we're interpolating on the raw coordinates we
	# saved, which are in Web Mercator, and we unproject to lng/lat later.
	# At the scale we're operating at, it doesn't really matter where we
	# do the projection.
	#
	# TODO: We have some missing circuits. Remove when we have all circuits.
	circuits = [ circuit for circuit in routeinfo["TrackCircuits"] if circuit["CircuitId"] in circuit_coordinates]
	coords = [ circuit_coordinates[circuit["CircuitId"]] for circuit in circuits ]
	interp = scipy.interpolate.interp1d(list(range(len(coords))), numpy.array(coords).T, kind="cubic")

	# Circuits.
	def make_coord(coord):
		return collections.OrderedDict(zip(("lng", "lat"), proj(*coord, inverse=True)))
	prev_circuit = None
	for i, circuit in enumerate(circuits):
		if prev_circuit:
			# Add some interpolated points between the previous circuit and this one.
			N = 10
			for n in range(1, N):
				coord = make_coord(interp((i-1) + n/N))
				coord["type"] = "interpolated"
				route["locations"].append(coord)

			# Remember that we've seen the track between this pair of circuits.
			seen_circuit_neighbors.add( (prev_circuit["CircuitId"], circuit["CircuitId"]) )

		# Add this circuit.
		coord = make_coord(list(interp(i))) # could go to circuit_coordinates directly but this should be the same
		if circuit["StationCode"]:
			coord["type"] = "station"
			coord["station"] =  collections.OrderedDict(sorted(stations[circuit["StationCode"]].items()))
		else:
			coord["type"] = "circuit"
		coord["circuit"] = circuit["CircuitId"]
		route["locations"].append(coord)

		prev_circuit = circuit

# Add non-revenue tracks. There is track that isn't on a "line". Use the WMATA
# TrackCircuits API to get the connectivity of all of the circuits. For now,
# generate tracks for every pair of connected circuits that we didn't already
# place on a track. TODO: Build up the connectivity of these circuits into tracks
# of maximal length and then run them through the output above so that we get
# interpolation for the long ones.
all_circuits = json.loads(urllib.request.urlopen(urllib.request.Request("https://api.wmata.com/TrainPositions/TrackCircuits?contentType=json", headers={ "api_key": API_KEY })).read().decode("ascii"))
for circuit1info in all_circuits["TrackCircuits"]:
	circuit1 = circuit1info["CircuitId"]
	if circuit1 not in circuit_coordinates: continue # no location info
	for neighbors in circuit1info["Neighbors"]:
		for circuit2 in neighbors["CircuitIds"]:
			if circuit2 not in circuit_coordinates: continue # no location info
			if (circuit1, circuit2) in seen_circuit_neighbors or (circuit2, circuit1) in seen_circuit_neighbors: continue
			seen_circuit_neighbors.add((circuit1, circuit2))
			c1 = make_coord(circuit_coordinates[circuit1])
			c1["type"] = "circuit"
			c1["circuit"] = circuit1
			c2 = make_coord(circuit_coordinates[circuit1])
			c2["type"] = "circuit"
			c2["circuit"] = circuit2
			tracks.append(collections.OrderedDict([
				("line", None),
				("track", circuit1info["Track"]), # "Track number. 1 and 2 denote "main" lines, while 0 and 3 are connectors (between different types of tracks) and pocket tracks, respectively"
				("locations", [
					c1,
					c2,
				]),
			]))

# Output as plain JSON.
with open("tracks.json", "w") as f:
	f.write(json.dumps(tracks, indent=2))

# Output as GeoJSON.
def all_locations(): # yield all locations across all tracks
	for track in tracks:
		for location in track["locations"]:
			yield location
tracks_geojson = collections.OrderedDict([
	("type", "FeatureCollection"),
	("features",
	[
		# Track lines.
		collections.OrderedDict([
			("type", "Feature"),
			("properties", collections.OrderedDict([
				("type", "track"),
				("line", track["line"]),
				("track", track["track"]),
			])),
			("geometry", collections.OrderedDict([
    	        ("type", "LineString"),
        	    ("coordinates", [ [location["lng"], location["lat"]] for location in track["locations"] ]),
	        ]))
		])
		for track in tracks
	]
	+ [
		# Track stations.
		collections.OrderedDict([
			("type", "Feature"),
			("properties", collections.OrderedDict([
				("type", "station"),
				("code", location["station"]["Code"]),
				("name", location["station"]["Name"]),
			])),
			("geometry", collections.OrderedDict([
	   	        ("type", "Point"),
	       	    ("coordinates", [location["lng"], location["lat"]]),
	        ]))
		])
		for location in all_locations()
		if location["type"] == "station"
	]
	)
])
with open("tracks.geojson", "w") as f:
	f.write(json.dumps(tracks_geojson, indent=2))

# Write a file containing points for all observed train positions.
locs_geojson = collections.OrderedDict([
	("type", "FeatureCollection"),
	("features",
	 [
		collections.OrderedDict([
			("type", "Feature"),
			("properties", collections.OrderedDict([
				("type", "reported-train-position"),
				("occurrences", all_coordinates[coord]),
			])),
			("geometry", collections.OrderedDict([
	   	        ("type", "Point"),
	       	    ("coordinates", proj(*coord, inverse=True)),
	        ]))
		])
		for coord in sorted(all_coordinates)
	 ]
	)
])
with open("all-reported-locations.geojson", "w") as f:
	f.write(json.dumps(locs_geojson, indent=2))

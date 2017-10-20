import glob, json, gzip, collections, urllib.request

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
circuit_coordinates = collections.defaultdict(lambda : collections.defaultdict(lambda : 0))
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
	for train in gis_locations["features"]:
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
			circuit_coordinates[train["circuit"]][train["coordinate"]] += 1 + train["duration"]

# For each circuit, take its most common coordinate.
for circuit, coords in circuit_coordinates.items():
	circuit_coordinates[circuit] = sorted(coords.items(), key = lambda kv : -kv[1])[0][0]

# Construct tracks.
def make_location(circuit):
	ret = collections.OrderedDict()
	ret["circuit"] = circuit["CircuitId"]
	if circuit["StationCode"]: ret["station"] = collections.OrderedDict(sorted(stations[circuit["StationCode"]].items()))
	if circuit["CircuitId"] in circuit_coordinates: ret["location"] = dict(zip(("lng", "lat"), proj(*circuit_coordinates[circuit["CircuitId"]], inverse=True)))
	return ret
def make_track(route):
	return collections.OrderedDict([
		("line", route["LineCode"]),
		("track", route["TrackNum"]),
		("locations", list(map(make_location, route["TrackCircuits"]))),
	])
routes["StandardRoutes"].sort(key = lambda route : (route["LineCode"], route["TrackNum"]))
tracks = list(map(make_track, routes["StandardRoutes"]))

# Output as plain JSON and as GeoJSON.
with open("tracks.json", "w") as f:
	f.write(json.dumps(tracks, indent=2))

def extract_stations():
	seen_stations = set()
	for tract in tracks:
		for circuit in tract["locations"]:
			if "station" in circuit:
				if circuit["station"]["Code"] in seen_stations: continue
				seen_stations.add(circuit["station"]["Code"])
				yield circuit

tracks_geojson = collections.OrderedDict([
	("type", "FeatureCollection"),
	("features",
	[
		collections.OrderedDict([
			("type", "Feature"),
			("properties", collections.OrderedDict([
				("type", "track"),
				("line", track["line"]),
				("track", track["track"]),
			])),
			("geometry", collections.OrderedDict([
    	        ("type", "LineString"),
        	    ("coordinates", [ [circuit["location"]["lng"], circuit["location"]["lat"]] for circuit in track["locations"] if "location" in circuit ]),
	        ]))
		])
		for track in tracks
	]
	+ [
		collections.OrderedDict([
			("type", "Feature"),
			("properties", collections.OrderedDict([
				("type", "station"),
				("code", circuit["station"]["Code"]),
				("name", circuit["station"]["Name"]),
			])),
			("geometry", collections.OrderedDict([
	   	        ("type", "Point"),
	       	    ("coordinates", [circuit["location"]["lng"], circuit["location"]["lat"]]),
	        ]))
		])
		for circuit in extract_stations()
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

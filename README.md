# WMATA Track Geospatial Data

Hi there. This was a quick WMATA Metro hack.

* I collected real time train location data from the [WMATA API](https://developer.wmata.com/docs/services/5763fa6ff91823096cac1057/operations/5763fb35f91823096cac1058)
(which provides real time "circuit numbers") and the [WMATA Real Time Train Map](gis.wmata.com/metrotrain/index.html)
(which provides real time train coordinates) over the course of about 24 hours.
* I then combined the data to determine the best guess of a longitude/latitude coordinate for each track circuit.
* I then used scipy to interpolate the locations between circuits to create smooth curved tracks.
* And I saved the result as JSON and GeoJSON ([preview on github](https://github.com/JoshData/wmata-track-locations/blob/master/tracks.geojson)).

A "track circuit" is a span of actual rail. Metro trains don't have GPS devices. Their locations are known to WMATA
by which circuit they are currently traveling on. Each circuit is uniquely identified. WMATA doesn't officially
publish the locations of the circuits, or for that matter the tracks. This hack combines the data they do
publish to infer the locations of the circuits, and therefore the tracks.

Each Metro line has two tracks. There are also tracks that are non-service tracks which are 
also in the output, but I haven't processed those very well yet.

It's not actually clear WMATA knows the actual locations of circuits. The real
time train map yields particular coordinates as trains pass over circuits. Those may not be actual circuit
locations (except at stations, which are easy to verify). Who knows. Anyway, this dataset is based on the locations
that the real time train map reports, whether or not those are accurate.

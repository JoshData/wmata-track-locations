# WMATA Track Geospatial Data

Hi there. This is a WMATA Metro civic hack to produce a high-resolution track map. Currently only revenue tracks are working.

[Tracks.geojson](tracks.geojson)

I collected real time train location data from  the [WMATA Real Time Train Map](gis.wmata.com/metrotrain/index.html)
(which provides real time train lat/lng coordinates) every 15 seconds over the course of about two weeks. (It's 300 MB compressed data.)

I first wanted to match up the lat/lng coordinates with the real time train position circuit numbers
from the [WMATA API](https://developer.wmata.com/docs/services/5763fa6ff91823096cac1057/operations/5763fb35f91823096cac1058),
but the data was too inconsistent --- the two data sources didn't line up enough to reliably match up the data.
Note that the data is train positions at points in time but because not all
circuits or coordinates appear in every train run, it doesn't obviously tell you what the actual order of the
coordinates or circuits are on the train lines. WMATA has an API that gives the order of circuits on the lines,
but not the coordinates.

So I wrote a script to infer the order of all of the observed locations of trains on the revenue tracks.
I did this for revenue tracks only because the script works by assembling long segments of continuous track in
a way that keeps the track smooth, and the revenue tracks are long and easy to work with. The non-revenue tracks
(pocket tracks, yards, the two spurs connecting Red to the other trunks) are tiny and numerous, so I'll come
back to that.

The revenue track paths are stored in [tracks.json](tracks.json). 

I then used scipy to interpolate the locations between observed train coordinates to create smooth curved tracks.
The interpolated paths are stored in [tracks.geojson](https://github.com/JoshData/wmata-track-locations/blob/master/tracks.geojson).

WIP:

A "track circuit" is a span of actual rail. Metro trains don't have GPS devices. Their locations are known to WMATA
by which circuit they are currently traveling on. Each circuit is uniquely identified. WMATA doesn't officially
publish the locations of the circuits, or for that matter the tracks, but by comining the two real-time data
sources it should be possible to figure it out. It's not actually clear WMATA knows the actual locations of circuits,
though. The real time train map yields particular coordinates as trains pass over circuits. Those may not be actual circuit
locations (except at stations, which are easy to verify). Who knows.

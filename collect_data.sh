#!/bin/bash
source api_key.inc
while /bin/true; do
	fn=data/$(date -u --rfc-3339=seconds|sed 's/ /T/g' | sed 's/[-:]//g' | sed 's/+0000$//')

	wget -q -O $fn-gis.json "https://gisservices.wmata.com/gisservices/rest/services/Public/TRAIN_LOC_WMS_PUB/MapServer/0/query?f=json&where=TRACKLINE%20is%20not%20null&returnGeometry=true&outFields=*"
	wget -q -O $fn-circuit.json --header "api_key: $API_KEY" "https://api.wmata.com/TrainPositions/TrainPositions?contentType=json"
	gzip $fn-*.json
	echo $fn
	sleep 15
done

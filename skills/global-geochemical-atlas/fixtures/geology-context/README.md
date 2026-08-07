# Macrostrat geology-context fixture

This fixture supports network-free testing of the independent D1 geology
context layer.

- `audit-samples.csv`: 30 cross-continent and edge-case coordinates.
- `cache/points`: source-native Macrostrat v2 point responses.
- `cache/tiles/carto/5`: source-native z5 carto MVT tiles.
- `point-audit-results.jsonl`: evidence-preserving point-candidate results.
- `tile-audit-results.jsonl`: local point-in-polygon results.
- `audit-report.json`: paired consistency and preservation checks.

The cache is identified by API version, endpoint coordinates, or z/x/y. No
content digest is present or required. Empty MVT files are legitimate ocean or
map-gap responses and must not be treated as damaged solely because their byte
count is zero.

The fixture records Macrostrat API version 2.3.8 and was accessed on
2026-08-07. Macrostrat and its map data are CC BY 4.0; original provider
references are carried in point candidates when supplied by the API.

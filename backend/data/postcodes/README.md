# Postcode centroids (DT and BH)

`centroids-dt-bh.csv` is the local postcode-centroid file the back end reads from
`OVERWATCH_POSTCODE_CENTROIDS_PATH` (DEC-047): `postcode,latitude,longitude`, WGS84, one row for each
postcode in the DT (Dorchester) and BH (Bournemouth) areas, 23,198 rows. Patient postcodes are placed from
this file and never leave the service (the loader makes no network call).

Source: Ordnance Survey Code-Point Open, `codepo_gb.zip` (md5 `42ecd9a7db141608dc6ab63f2dfb0bc3`,
downloaded 2026-10-31 from the OS Data Hub downloads API), area files `dt.csv` and `bh.csv`. Eastings and
northings (EPSG:27700) were converted to WGS84 (EPSG:4326) with pyproj and rounded to six decimals.
Licence: Open Government Licence v3 through the OS OpenData licence. Contains Ordnance Survey data
(c) Crown copyright and database right 2026; Contains Royal Mail data (c) Royal Mail copyright and database
right 2026; Contains National Statistics data (c) Crown copyright and database right 2026.

To cover more areas, convert the other area files the same way (one `<area>.csv` per postcode area), put
the rows in one file and keep the header exactly `postcode,latitude,longitude`.

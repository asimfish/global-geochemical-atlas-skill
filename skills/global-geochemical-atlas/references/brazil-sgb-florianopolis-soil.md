# Brazil SGB Florianópolis soil source card

## Executable product

The adapter fixes one concrete soil product inside the official SGB RIGeo item [doc/23413](https://rigeo.sgb.gov.br/handle/doc/23413): bitstream `4ac11c55-2d10-4aac-9dce-5266b442c500`, archive `geoquimica_florianopolis_1985.zip` and member `Florianopolis_Geoquimica_Solo.xlsx`. The official SGB soil FeatureServer layer 5 supplies record coordinates and sample metadata.

The child workbook contains 32 analysis rows and 192 raw As, Cr, Cu, Ni, Pb and Zn observations. All 32 rows have exact coordinate matches. Mercury is absent. As and Zn are reported as `ND` for all samples; this remains useful source evidence but must not be described as 64 numeric concentrations.

## Sample and soil semantics

Coordinates join on `NUM_CAMPO + NUM_LAB`. The source geometry is SIRGAS 2000 (EPSG:4674); API responses are explicitly requested as EPSG:4326.

The official layer reports `HORIZ_SOLO=Nao Identificado` and `TIPO_SOLO=Nao Especificado` for all 32 samples. D1 preserves both raw fields, leaves the canonical horizon empty and records a missing reason. It does not infer topsoil, subsoil, depth or soil classification from the sample code.

## Measurement semantics

All 32 source rows report `Espectrografia Ótica de Emissão` in the record-level `leitura` field. `abertura` is empty, so preparation/digestion remains unknown. The adapter does not infer a digestion method from the analytical technique.

- numeric cells remain source-reported ppm numbers;
- `< n` remains censored with the threshold retained;
- `ND` remains non-numeric and no detection limit is invented.

The full profile contains 125 numeric values, three less-than values and 64 `ND` observations.

## Citation and rights

Use the SGB-CPRM 2022 RIGeo citation recorded by item `doc/23413`. The item metadata states `dc.rights=open` and the bitstream is publicly downloadable. No explicit dataset reuse license was located, so D1 records research use as permitted for this project and leaves redistribution unevaluated. The generic DSpace deposit license is not presented as a public reuse license.

## Claim boundary

This product adds an independent SGB soil lineage and executable South America soil observations. It is a 32-sample regional survey near Florianópolis, not national Brazilian coverage and not a continuous South America soil layer. Online, cached and offline-fixture modes preserve identical source semantics. Drift is detected from readable source identity, archive member inventory, byte counts, schema, counts and key statistics; no content hashes are used.

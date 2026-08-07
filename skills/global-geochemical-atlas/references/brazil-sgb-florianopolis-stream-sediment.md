# Brazil SGB Florianópolis stream-sediment source card

## What is executable

The standalone adapter pins one concrete numeric child product from the official SGB RIGeo item [doc/23413](https://rigeo.sgb.gov.br/handle/doc/23413):

- repository item ID: `5adc5a2e-78ca-4da4-990c-c932658481a7`;
- bitstream ID: `4ac11c55-2d10-4aac-9dce-5266b442c500`;
- bitstream: `geoquimica_florianopolis_1985.zip`, 841,480 bytes;
- selected member: `Florianopolis_Geoquimica_Sedimento_de_Corrente.xlsx`, 193,591 bytes;
- coordinate source: official SGB `geoquimica_integrada` FeatureServer layer 2;
- pinned D1 version: `SGB-RIGEO-doc-23413-2022-bitstream-4ac11c55`.

The workbook has 1,054 source rows. Of those, 527 analysis rows carry at least one of As, Cr, Cu, Ni, Pb or Zn, yielding 3,132 raw target observations across 520 field sample IDs. Mercury is not present in this child workbook. The adapter schema can still coexist with sources that report Hg; it does not manufacture a missing Hg column.

## Record and coordinate identity

The workbook and ArcGIS layer share `NUM_CAMPO`/`num_campo` and `NUM_LAB`/`num_lab`. `NUM_CAMPO` alone is not unique: sample `1046-HM-S-760` occurs at two coordinates with laboratory IDs `JBB522` and `JBB523`. The production join therefore uses the composite `NUM_CAMPO + NUM_LAB` key. There are 521 unique target sample/laboratory pairs and all 521 join to the official point layer.

Coordinates requested from ArcGIS are returned as EPSG:4326. The original project geometry declares SIRGAS 2000 (EPSG:4674). Both facts remain explicit. A missing or non-unique composite join must return an unmatched state; the adapter never chooses the first coordinate.

## Raw values and methods

The target columns are source-reported ppm fields. The adapter preserves three value forms:

- a number remains the reported number;
- `< n` becomes `below_detection_limit` with `n` retained as the reported threshold;
- `ND` becomes `not_detected` with no numeric value or invented detection limit.

Method assignment is record-scoped. `leitura` supplies the reported method and `abertura` supplies the reported preparation/extraction text when present. The target rows contain 521 optical-emission rows and six atomic-absorption rows. Repeated samples from different methods remain separate source records.

## Citation and rights boundary

Use the repository citation:

> SERVIÇO GEOLÓGICO DO BRASIL - CPRM. Resultados Analíticos de Amostras Geoquímicas e Produtos Associados (planilhas de análises geoquímicas). Brasil: SGB-CPRM, 2022.

The RIGeo item metadata states `dc.rights=open`, and the files are publicly downloadable. No explicit dataset reuse license was located in the item metadata. D1 therefore records research use as permitted for this project, records the license scope as item metadata only, and leaves redistribution status unevaluated. The generic DSpace deposit license is not presented as a public reuse license.

## Claim and failure boundary

This source closes a South America executable-source gap and adds an independent SGB sediment lineage. It is a regional Florianópolis survey, not a Brazil-wide survey and not continuous South America coverage.

The adapter fails closed when item/bitstream identity, byte count, member identity, workbook schema, row counts, analyte counts, method counts or the composite coordinate join drift. Online, cache and fixture modes use the same raw semantics. No content hashes participate in acquisition, caching, audit or acceptance.

PRAGMA foreign_keys = ON;

CREATE TABLE archive_metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE datasets (
  dataset_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  title TEXT NOT NULL,
  publisher TEXT NOT NULL,
  dataset_doi TEXT,
  dataset_version TEXT NOT NULL,
  landing_page TEXT NOT NULL,
  license_id TEXT NOT NULL,
  license_url TEXT NOT NULL,
  retrieved_at TEXT NOT NULL
);

CREATE INDEX idx_datasets_source_version ON datasets(source_id, dataset_version);

CREATE TABLE dataset_files (
  dataset_id TEXT NOT NULL REFERENCES datasets(dataset_id),
  file_id TEXT NOT NULL,
  filename TEXT NOT NULL,
  source_url TEXT NOT NULL,
  bytes INTEGER NOT NULL CHECK (bytes >= 0),
  file_identity TEXT NOT NULL,
  PRIMARY KEY (dataset_id, file_id)
);

CREATE INDEX idx_dataset_files_identity ON dataset_files(file_identity);

CREATE TABLE publications (
  publication_id TEXT PRIMARY KEY,
  doi TEXT,
  citation TEXT NOT NULL,
  title TEXT,
  year INTEGER
);

CREATE TABLE publication_datasets (
  publication_id TEXT NOT NULL REFERENCES publications(publication_id),
  dataset_id TEXT NOT NULL REFERENCES datasets(dataset_id),
  relation_type TEXT NOT NULL,
  PRIMARY KEY (publication_id, dataset_id, relation_type)
);

CREATE TABLE sampling_events (
  sampling_event_id TEXT PRIMARY KEY,
  dataset_id TEXT NOT NULL REFERENCES datasets(dataset_id),
  site_id TEXT,
  sampled_at_raw TEXT,
  collection_method_raw TEXT,
  latitude_raw TEXT,
  longitude_raw TEXT,
  source_crs TEXT,
  latitude REAL,
  longitude REAL,
  coordinate_uncertainty_m REAL,
  elevation_m REAL,
  depth_min_m REAL,
  depth_max_m REAL,
  place_raw TEXT
);

CREATE INDEX idx_sampling_events_time ON sampling_events(sampled_at_raw);
CREATE INDEX idx_sampling_events_dataset ON sampling_events(dataset_id);

CREATE VIRTUAL TABLE sampling_event_rtree USING rtree(
  event_rowid,
  min_longitude,
  max_longitude,
  min_latitude,
  max_latitude
);

CREATE TRIGGER sampling_event_rtree_insert
AFTER INSERT ON sampling_events
WHEN NEW.latitude IS NOT NULL AND NEW.longitude IS NOT NULL
BEGIN
  INSERT INTO sampling_event_rtree VALUES (NEW.rowid, NEW.longitude, NEW.longitude, NEW.latitude, NEW.latitude);
END;

CREATE TRIGGER sampling_event_rtree_update
AFTER UPDATE OF latitude, longitude ON sampling_events
BEGIN
  DELETE FROM sampling_event_rtree WHERE event_rowid = OLD.rowid;
  INSERT INTO sampling_event_rtree
  SELECT NEW.rowid, NEW.longitude, NEW.longitude, NEW.latitude, NEW.latitude
  WHERE NEW.latitude IS NOT NULL AND NEW.longitude IS NOT NULL;
END;

CREATE TRIGGER sampling_event_rtree_delete
AFTER DELETE ON sampling_events
BEGIN
  DELETE FROM sampling_event_rtree WHERE event_rowid = OLD.rowid;
END;

CREATE TABLE samples (
  sample_id TEXT PRIMARY KEY,
  native_sample_id TEXT,
  igsn TEXT,
  parent_sample_id TEXT REFERENCES samples(sample_id),
  sampling_event_id TEXT NOT NULL REFERENCES sampling_events(sampling_event_id),
  medium_raw TEXT NOT NULL,
  material_raw TEXT,
  sample_type_raw TEXT,
  sample_type TEXT,
  sample_type_mapping_status TEXT,
  geographic_context_raw TEXT,
  survey_area TEXT,
  map_sheet TEXT,
  cruise_track TEXT,
  lithology_raw TEXT,
  lithology TEXT,
  geologic_unit_raw TEXT,
  geologic_age_raw TEXT,
  tectonic_setting_raw TEXT,
  matched_geologic_unit TEXT,
  geology_map_source TEXT,
  geology_map_version TEXT,
  match_method TEXT,
  match_scale TEXT,
  boundary_distance_m REAL,
  match_uncertainty TEXT,
  soil_horizon_raw TEXT,
  soil_horizon TEXT,
  sediment_environment TEXT,
  grain_fraction_raw TEXT,
  water_body_type TEXT,
  water_fraction TEXT,
  filtered_state_raw TEXT,
  description_raw TEXT
);

CREATE INDEX idx_samples_medium ON samples(medium_raw);
CREATE INDEX idx_samples_type ON samples(sample_type);
CREATE INDEX idx_samples_geology ON samples(geologic_unit_raw, matched_geologic_unit);
CREATE INDEX idx_samples_igsn ON samples(igsn);
CREATE INDEX idx_samples_event ON samples(sampling_event_id);

CREATE TABLE analytical_methods (
  method_id TEXT PRIMARY KEY,
  method_code_raw TEXT,
  method_scope TEXT,
  method_assignment_basis TEXT,
  preparation_raw TEXT,
  digestion_or_extraction_raw TEXT,
  technique_raw TEXT,
  instrument_raw TEXT,
  laboratory_raw TEXT,
  calibration_raw TEXT,
  quantitation_limit_raw TEXT,
  blank_qc_raw TEXT,
  replicate_qc_raw TEXT,
  method_source_locator TEXT
);

CREATE INDEX idx_methods_technique ON analytical_methods(technique_raw);

CREATE TABLE method_publications (
  method_id TEXT NOT NULL REFERENCES analytical_methods(method_id),
  publication_id TEXT NOT NULL REFERENCES publications(publication_id),
  PRIMARY KEY (method_id, publication_id)
);

CREATE TABLE acquisition_runs (
  acquisition_run_id TEXT PRIMARY KEY,
  request_json TEXT NOT NULL,
  dataset_ids_json TEXT NOT NULL,
  schema_versions_json TEXT NOT NULL,
  vocabulary_versions_json TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT NOT NULL,
  status TEXT NOT NULL,
  cache_status TEXT NOT NULL,
  counts_json TEXT NOT NULL,
  outputs_json TEXT NOT NULL
);

CREATE TABLE provenance (
  provenance_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  dataset_id TEXT NOT NULL REFERENCES datasets(dataset_id),
  acquisition_run_id TEXT NOT NULL REFERENCES acquisition_runs(acquisition_run_id),
  source_record_id TEXT NOT NULL,
  source_locator TEXT NOT NULL,
  source_file TEXT,
  source_sheet TEXT,
  source_row INTEGER,
  source_column TEXT,
  input_file_id TEXT NOT NULL,
  adapter_name TEXT NOT NULL,
  adapter_version TEXT NOT NULL,
  processing_steps_json TEXT NOT NULL
);

CREATE INDEX idx_provenance_source_record ON provenance(source_id, source_record_id);
CREATE INDEX idx_provenance_dataset ON provenance(dataset_id);

CREATE TABLE observations (
  observation_id TEXT PRIMARY KEY,
  sample_id TEXT NOT NULL REFERENCES samples(sample_id),
  method_id TEXT NOT NULL REFERENCES analytical_methods(method_id),
  provenance_id TEXT NOT NULL REFERENCES provenance(provenance_id),
  analyte_reported TEXT NOT NULL,
  value_raw TEXT NOT NULL,
  parsed_value REAL,
  value_qualifier TEXT NOT NULL,
  unit_raw TEXT,
  measurement_basis_raw TEXT,
  detection_limit_raw TEXT,
  parsed_detection_limit REAL,
  detection_limit_unit_raw TEXT,
  uncertainty_raw TEXT,
  replicate_id TEXT
);

CREATE INDEX idx_observations_analyte ON observations(analyte_reported);
CREATE INDEX idx_observations_sample_analyte ON observations(sample_id, analyte_reported);
CREATE INDEX idx_observations_method ON observations(method_id);
CREATE INDEX idx_observations_provenance ON observations(provenance_id);

CREATE VIRTUAL TABLE archive_fts USING fts5(entity_type, entity_id UNINDEXED, searchable_text);

CREATE VIEW observation_search AS
SELECT
  o.observation_id,
  o.analyte_reported,
  o.value_raw,
  o.parsed_value,
  o.value_qualifier,
  o.unit_raw,
  o.measurement_basis_raw,
  o.detection_limit_raw,
  o.parsed_detection_limit,
  o.detection_limit_unit_raw,
  s.sample_id,
  s.native_sample_id,
  s.igsn,
  s.parent_sample_id,
  s.medium_raw,
  s.material_raw,
  s.sample_type_raw,
  s.sample_type,
  s.sample_type_mapping_status,
  s.geographic_context_raw,
  s.survey_area,
  s.map_sheet,
  s.cruise_track,
  s.lithology_raw,
  s.lithology,
  s.geologic_unit_raw,
  s.geologic_age_raw,
  s.tectonic_setting_raw,
  s.matched_geologic_unit,
  s.geology_map_source,
  s.geology_map_version,
  s.match_method,
  s.match_scale,
  s.boundary_distance_m,
  s.match_uncertainty,
  s.soil_horizon_raw,
  s.soil_horizon,
  s.sediment_environment,
  s.grain_fraction_raw,
  s.water_body_type,
  s.water_fraction,
  s.filtered_state_raw,
  e.sampling_event_id,
  e.sampled_at_raw,
  e.latitude,
  e.longitude,
  e.source_crs,
  e.coordinate_uncertainty_m,
  m.method_id,
  m.method_scope,
  m.method_assignment_basis,
  m.preparation_raw,
  m.technique_raw,
  m.instrument_raw,
  m.digestion_or_extraction_raw,
  m.laboratory_raw,
  p.provenance_id,
  p.source_id,
  p.source_record_id,
  p.source_locator,
  p.source_file,
  p.source_row,
  p.input_file_id,
  d.dataset_id,
  d.dataset_version,
  d.dataset_doi,
  d.license_id,
  d.license_url
FROM observations o
JOIN samples s ON s.sample_id = o.sample_id
JOIN sampling_events e ON e.sampling_event_id = s.sampling_event_id
JOIN analytical_methods m ON m.method_id = o.method_id
JOIN provenance p ON p.provenance_id = o.provenance_id
JOIN datasets d ON d.dataset_id = p.dataset_id;

CREATE VIEW sample_summary AS
SELECT
  s.sample_id,
  s.native_sample_id,
  s.igsn,
  s.parent_sample_id,
  s.medium_raw,
  s.material_raw,
  s.sample_type,
  s.lithology_raw,
  s.lithology,
  s.geologic_unit_raw,
  s.matched_geologic_unit,
  s.soil_horizon,
  s.sediment_environment,
  s.water_body_type,
  s.water_fraction,
  e.latitude,
  e.longitude,
  e.sampled_at_raw,
  COUNT(o.observation_id) AS observation_count,
  GROUP_CONCAT(DISTINCT o.analyte_reported) AS analytes
FROM samples s
JOIN sampling_events e ON e.sampling_event_id = s.sampling_event_id
LEFT JOIN observations o ON o.sample_id = s.sample_id
GROUP BY s.sample_id;

CREATE VIEW source_coverage AS
SELECT
  p.source_id,
  d.dataset_version,
  s.medium_raw,
  o.analyte_reported,
  COUNT(o.observation_id) AS observation_count,
  COUNT(DISTINCT s.sample_id) AS sample_count,
  SUM(CASE WHEN e.latitude IS NOT NULL AND e.longitude IS NOT NULL THEN 1 ELSE 0 END) AS located_observation_count
FROM observations o
JOIN samples s ON s.sample_id = o.sample_id
JOIN sampling_events e ON e.sampling_event_id = s.sampling_event_id
JOIN provenance p ON p.provenance_id = o.provenance_id
JOIN datasets d ON d.dataset_id = p.dataset_id
GROUP BY p.source_id, d.dataset_version, s.medium_raw, o.analyte_reported;

CREATE VIEW provenance_trace AS
SELECT
  o.observation_id,
  o.sample_id,
  o.method_id,
  p.provenance_id,
  p.source_id,
  p.source_record_id,
  p.source_locator,
  p.source_file,
  p.source_sheet,
  p.source_row,
  p.source_column,
  p.input_file_id,
  p.adapter_name,
  p.adapter_version,
  p.acquisition_run_id,
  d.dataset_id,
  d.dataset_version,
  d.dataset_doi,
  d.license_id,
  d.license_url
FROM observations o
JOIN provenance p ON p.provenance_id = o.provenance_id
JOIN datasets d ON d.dataset_id = p.dataset_id;

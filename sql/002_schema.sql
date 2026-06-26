-- Core tables for spreadsheet validation, taxonomy, and geography.

CREATE TABLE IF NOT EXISTS validation_job (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  original_filename TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  total_rows INTEGER NOT NULL DEFAULT 0,
  error_count INTEGER NOT NULL DEFAULT 0,
  warning_count INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  options JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS uploaded_specimen (
  id BIGSERIAL PRIMARY KEY,
  job_id UUID NOT NULL REFERENCES validation_job(id) ON DELETE CASCADE,
  row_number INTEGER NOT NULL,
  raw JSONB NOT NULL,
  accession TEXT,
  collector TEXT,
  number TEXT,
  addcoll TEXT,
  colldd TEXT,
  collmm TEXT,
  collyy TEXT,
  family TEXT,
  genus TEXT,
  sp1 TEXT,
  author1 TEXT,
  country TEXT,
  majorarea TEXT,
  minorarea TEXT,
  gazetteer TEXT,
  locnotes TEXT,
  plantdesc TEXT,
  lat DOUBLE PRECISION,
  long DOUBLE PRECISION,
  geom geometry(Point, 4326),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS validation_issue (
  id BIGSERIAL PRIMARY KEY,
  job_id UUID NOT NULL REFERENCES validation_job(id) ON DELETE CASCADE,
  uploaded_specimen_id BIGINT REFERENCES uploaded_specimen(id) ON DELETE CASCADE,
  row_number INTEGER,
  column_name TEXT,
  severity TEXT NOT NULL CHECK (severity IN ('error', 'warning', 'info')),
  code TEXT NOT NULL,
  message TEXT NOT NULL,
  value TEXT,
  suggestion TEXT,
  source TEXT,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ffb_taxon (
  taxon_id TEXT PRIMARY KEY,
  parent_name_usage_id TEXT,
  accepted_name_usage_id TEXT,
  scientific_name TEXT,
  canonical_name TEXT,
  scientific_name_authorship TEXT,
  kingdom TEXT,
  phylum TEXT,
  class_name TEXT,
  order_name TEXT,
  family TEXT,
  genus TEXT,
  specific_epithet TEXT,
  infraspecific_epithet TEXT,
  taxon_rank TEXT,
  taxonomic_status TEXT,
  nomenclatural_status TEXT,
  name_according_to TEXT,
  source_version TEXT,
  imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ffb_distribution (
  id BIGSERIAL PRIMARY KEY,
  taxon_id TEXT REFERENCES ffb_taxon(taxon_id) ON DELETE CASCADE,
  location_id TEXT,
  locality TEXT,
  state_province TEXT,
  establishment_means TEXT,
  occurrence_status TEXT,
  raw JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS br_state (
  geocode TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  abbrev TEXT,
  geom geometry(MultiPolygon, 4326) NOT NULL
);

CREATE TABLE IF NOT EXISTS br_municipality (
  geocode TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  state_abbrev TEXT,
  state_name TEXT,
  geom geometry(MultiPolygon, 4326) NOT NULL
);

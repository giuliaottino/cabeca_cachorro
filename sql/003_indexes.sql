CREATE INDEX IF NOT EXISTS uploaded_specimen_job_idx ON uploaded_specimen(job_id);
CREATE INDEX IF NOT EXISTS uploaded_specimen_geom_idx ON uploaded_specimen USING gist(geom);
CREATE INDEX IF NOT EXISTS validation_issue_job_idx ON validation_issue(job_id);
CREATE INDEX IF NOT EXISTS validation_issue_severity_idx ON validation_issue(job_id, severity);

CREATE INDEX IF NOT EXISTS ffb_taxon_genus_epithet_idx
  ON ffb_taxon (lower(unaccent(genus)), lower(unaccent(specific_epithet)));

CREATE INDEX IF NOT EXISTS ffb_taxon_scientific_trgm_idx
  ON ffb_taxon USING gin (lower(unaccent(scientific_name)) gin_trgm_ops);

CREATE INDEX IF NOT EXISTS ffb_taxon_canonical_trgm_idx
  ON ffb_taxon USING gin (lower(unaccent(canonical_name)) gin_trgm_ops);

CREATE INDEX IF NOT EXISTS ffb_taxon_family_idx
  ON ffb_taxon (lower(unaccent(family)));

CREATE INDEX IF NOT EXISTS ffb_distribution_taxon_idx ON ffb_distribution(taxon_id);
CREATE INDEX IF NOT EXISTS ffb_distribution_state_idx ON ffb_distribution(lower(unaccent(state_province)));

CREATE INDEX IF NOT EXISTS br_state_geom_idx ON br_state USING gist(geom);
CREATE INDEX IF NOT EXISTS br_state_name_idx ON br_state(lower(unaccent(name)));
CREATE INDEX IF NOT EXISTS br_state_abbrev_idx ON br_state(abbrev);

CREATE INDEX IF NOT EXISTS br_municipality_geom_idx ON br_municipality USING gist(geom);
CREATE INDEX IF NOT EXISTS br_municipality_name_idx ON br_municipality(lower(unaccent(name)));
CREATE INDEX IF NOT EXISTS br_municipality_state_idx ON br_municipality(state_abbrev);

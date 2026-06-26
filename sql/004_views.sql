CREATE OR REPLACE VIEW v_validation_summary AS
SELECT
  j.id AS job_id,
  j.original_filename,
  j.status,
  j.total_rows,
  COUNT(i.*) FILTER (WHERE i.severity = 'error') AS errors,
  COUNT(i.*) FILTER (WHERE i.severity = 'warning') AS warnings,
  COUNT(i.*) FILTER (WHERE i.severity = 'info') AS infos,
  j.created_at,
  j.finished_at
FROM validation_job j
LEFT JOIN validation_issue i ON i.job_id = j.id
GROUP BY j.id;

CREATE OR REPLACE VIEW v_taxon_name_index AS
SELECT
  taxon_id,
  lower(unaccent(coalesce(scientific_name, ''))) AS scientific_name_norm,
  lower(unaccent(coalesce(canonical_name, ''))) AS canonical_name_norm,
  lower(unaccent(coalesce(genus, ''))) AS genus_norm,
  lower(unaccent(coalesce(specific_epithet, ''))) AS epithet_norm,
  lower(unaccent(coalesce(family, ''))) AS family_norm,
  scientific_name,
  canonical_name,
  scientific_name_authorship,
  family,
  genus,
  specific_epithet,
  taxon_rank,
  taxonomic_status,
  accepted_name_usage_id
FROM ffb_taxon;

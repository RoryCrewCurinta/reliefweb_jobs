-- One row per job posting
CREATE TABLE IF NOT EXISTS jobs (
  id            BIGINT PRIMARY KEY,
  title         VARCHAR,
  body          VARCHAR,          -- full description (NULL until API harvest)
  date_created  TIMESTAMP,
  date_closing  TIMESTAMP,
  date_changed  TIMESTAMP,        -- for incremental updates
  status        VARCHAR,          -- published / expired
  url           VARCHAR,
  data_source   VARCHAR           -- 'pbix_2023' or 'api_v2'
);
-- Many-to-many attributes
CREATE TABLE IF NOT EXISTS job_orgs        (job_id BIGINT, org_name VARCHAR, org_shortname VARCHAR, org_id BIGINT);
CREATE TABLE IF NOT EXISTS job_countries   (job_id BIGINT, country VARCHAR);
CREATE TABLE IF NOT EXISTS job_categories  (job_id BIGINT, category VARCHAR);
CREATE TABLE IF NOT EXISTS job_themes      (job_id BIGINT, theme VARCHAR);
-- Extra ReliefWeb fields (filled by harvest.py; backfill with: python harvest.py --meta)
CREATE TABLE IF NOT EXISTS job_meta        (job_id BIGINT, job_type VARCHAR, experience VARCHAR, city VARCHAR);
CREATE TABLE IF NOT EXISTS org_types       (org_id BIGINT, org_type VARCHAR);
-- ReliefWeb's organisation list: type and home country (refreshed by every harvest, or: python harvest.py --orgs)
CREATE TABLE IF NOT EXISTS orgs            (org_id BIGINT, org_name VARCHAR, org_shortname VARCHAR, org_type VARCHAR, home_country VARCHAR, home_iso3 VARCHAR, status VARCHAR);

-- Topic taxonomy: concept -> regex patterns (edit freely, then re-run matching)
CREATE TABLE IF NOT EXISTS concepts (concept VARCHAR PRIMARY KEY, grp VARCHAR, description VARCHAR);
CREATE TABLE IF NOT EXISTS concept_patterns (concept VARCHAR, pattern VARCHAR);

-- Output of matching: rebuilt whenever taxonomy changes
CREATE TABLE IF NOT EXISTS concept_hits (job_id BIGINT, concept VARCHAR, in_title BOOLEAN, in_body BOOLEAN);

-- Legacy Power BI keyword flags (body-text substring matches, 2011-May 2023) kept for comparison
CREATE TABLE IF NOT EXISTS legacy_keyword_hits (job_id BIGINT, keyword VARCHAR);

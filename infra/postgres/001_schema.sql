CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE election_systems (
  id text PRIMARY KEY,
  name text NOT NULL,
  mechanics jsonb NOT NULL,
  provenance_uri text NOT NULL,
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_to timestamptz
);

INSERT INTO election_systems (id, name, mechanics, provenance_uri) VALUES
  ('presidential_runoff', 'Two-round presidential', '{"rounds":2}', 'urn:elexion:engine:presidential-runoff:v1'),
  ('fptp', 'First past the post', '{"district_magnitude":1}', 'urn:elexion:engine:fptp:v1'),
  ('proportional', 'Proportional representation', '{}', 'urn:elexion:engine:proportional:v1'),
  ('mixed_member', 'Mixed-member system', '{}', 'urn:elexion:engine:mixed-member:v1'),
  ('electoral_college', 'Electoral college', '{}', 'urn:elexion:engine:electoral-college:v1'),
  ('institutional', 'Institutional selection', '{}', 'urn:elexion:engine:institutional:v1');

CREATE TABLE jurisdictions (
  id text PRIMARY KEY,
  iso3 text UNIQUE,
  name text NOT NULL,
  region text NOT NULL,
  eligibility text NOT NULL,
  is_exception boolean NOT NULL DEFAULT false,
  forecast_enabled boolean NOT NULL DEFAULT true,
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_to timestamptz
);

CREATE TABLE sources (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_key text NOT NULL,
  label text NOT NULL,
  url text NOT NULL,
  authority text NOT NULL,
  license text NOT NULL,
  license_url text NOT NULL,
  attribution text NOT NULL,
  usage_scope text NOT NULL,
  license_approved boolean NOT NULL DEFAULT false,
  retrieved_at timestamptz NOT NULL,
  content_sha256 text NOT NULL,
  object_uri text NOT NULL,
  parser_version text NOT NULL,
  parser_confidence double precision NOT NULL CHECK (parser_confidence BETWEEN 0 AND 1),
  metadata jsonb NOT NULL DEFAULT '{}',
  UNIQUE (source_key, content_sha256),
  CHECK (content_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE source_revisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id uuid NOT NULL REFERENCES sources(id),
  source_key text NOT NULL,
  source_record_key text NOT NULL,
  revision integer NOT NULL,
  observed_at timestamptz NOT NULL,
  released_at timestamptz NOT NULL,
  available_at timestamptz NOT NULL,
  payload jsonb NOT NULL,
  payload_sha256 text NOT NULL,
  UNIQUE (source_key, source_record_key, revision),
  CHECK (released_at <= available_at),
  CHECK (payload_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE adapter_checkpoints (
  adapter_id text NOT NULL,
  scope_id text NOT NULL,
  parser_version text NOT NULL,
  source_snapshot_sha256 text NOT NULL,
  payload jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (adapter_id, scope_id),
  CHECK (source_snapshot_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE adapter_health_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  adapter_id text NOT NULL,
  scope_id text NOT NULL,
  status text NOT NULL CHECK (status IN ('success', 'failure')),
  failure_kind text,
  details jsonb NOT NULL DEFAULT '{}',
  CHECK ((status = 'success' AND failure_kind IS NULL) OR status = 'failure')
);

CREATE TABLE pipeline_run_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  run_id text NOT NULL,
  job_name text NOT NULL,
  status text NOT NULL CHECK (status IN ('success', 'failure')),
  details jsonb NOT NULL DEFAULT '{}',
  UNIQUE (run_id, status)
);

CREATE TABLE elections (
  id text PRIMARY KEY,
  jurisdiction_id text NOT NULL REFERENCES jurisdictions(id),
  name text NOT NULL,
  election_date date NOT NULL,
  date_confidence text NOT NULL,
  system text NOT NULL REFERENCES election_systems(id),
  seats_total integer,
  majority integer,
  status text NOT NULL,
  source_id uuid REFERENCES sources(id),
  valid_from timestamptz NOT NULL,
  valid_to timestamptz,
  CHECK (majority IS NULL OR seats_total IS NULL OR majority <= seats_total)
);

CREATE TABLE parties (
  id text PRIMARY KEY,
  jurisdiction_id text NOT NULL REFERENCES jurisdictions(id),
  name text NOT NULL,
  short_name text NOT NULL,
  color text NOT NULL,
  ideology text,
  valid_from timestamptz NOT NULL,
  valid_to timestamptz
);

CREATE TABLE calendar_revisions (
  id uuid PRIMARY KEY REFERENCES source_revisions(id),
  election_id text NOT NULL REFERENCES elections(id),
  revision integer NOT NULL CHECK (revision >= 0),
  election_date date NOT NULL,
  date_confidence text NOT NULL,
  status text NOT NULL,
  released_at timestamptz NOT NULL,
  available_at timestamptz NOT NULL,
  parser_version text NOT NULL,
  parser_confidence double precision NOT NULL CHECK (parser_confidence BETWEEN 0 AND 1),
  metadata jsonb NOT NULL DEFAULT '{}',
  UNIQUE (election_id, revision),
  CHECK (released_at <= available_at)
);

CREATE TABLE contestants (
  id text NOT NULL,
  election_id text NOT NULL REFERENCES elections(id),
  name text NOT NULL,
  short_name text NOT NULL,
  color text NOT NULL,
  incumbent boolean NOT NULL DEFAULT false,
  party_id text REFERENCES parties(id),
  metadata jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (election_id, id)
);

CREATE TABLE candidates (
  id text NOT NULL,
  election_id text NOT NULL,
  contestant_id text NOT NULL,
  name text NOT NULL,
  incumbent boolean NOT NULL DEFAULT false,
  metadata jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (election_id, id),
  FOREIGN KEY (election_id, contestant_id) REFERENCES contestants(election_id, id)
);

CREATE TABLE coalitions (
  id text NOT NULL,
  election_id text NOT NULL REFERENCES elections(id),
  name text NOT NULL,
  minimum_seats integer,
  allowed boolean NOT NULL DEFAULT true,
  constraint_reason text,
  PRIMARY KEY (election_id, id)
);

CREATE TABLE coalition_members (
  election_id text NOT NULL,
  coalition_id text NOT NULL,
  contestant_id text NOT NULL,
  PRIMARY KEY (election_id, coalition_id, contestant_id),
  FOREIGN KEY (election_id, coalition_id) REFERENCES coalitions(election_id, id),
  FOREIGN KEY (election_id, contestant_id) REFERENCES contestants(election_id, id)
);

CREATE TABLE reporting_units (
  id text NOT NULL,
  election_id text NOT NULL REFERENCES elections(id),
  parent_id text,
  name text NOT NULL,
  level text NOT NULL,
  seats integer,
  geometry geometry(MultiPolygon, 4326),
  boundary_source_id uuid REFERENCES sources(id),
  PRIMARY KEY (election_id, id),
  FOREIGN KEY (election_id, parent_id) REFERENCES reporting_units(election_id, id)
);

CREATE TABLE polls (
  id uuid PRIMARY KEY REFERENCES source_revisions(id),
  election_id text NOT NULL REFERENCES elections(id),
  poll_key text NOT NULL,
  revision integer NOT NULL CHECK (revision >= 0),
  pollster text NOT NULL,
  sponsor text NOT NULL,
  population text NOT NULL,
  mode text NOT NULL,
  fieldwork_start timestamptz NOT NULL,
  fieldwork_end timestamptz NOT NULL,
  released_at timestamptz NOT NULL,
  available_at timestamptz NOT NULL,
  sample_size integer NOT NULL CHECK (sample_size > 0),
  source_id uuid NOT NULL REFERENCES sources(id),
  parser_version text NOT NULL,
  parser_confidence double precision NOT NULL CHECK (parser_confidence BETWEEN 0 AND 1),
  metadata jsonb NOT NULL DEFAULT '{}',
  UNIQUE (election_id, poll_key, revision),
  CHECK (fieldwork_start <= fieldwork_end),
  CHECK (fieldwork_end <= released_at),
  CHECK (released_at <= available_at)
);

CREATE TABLE poll_results (
  poll_id uuid NOT NULL REFERENCES polls(id),
  election_id text NOT NULL,
  contestant_id text NOT NULL,
  share double precision NOT NULL CHECK (share BETWEEN 0 AND 1),
  PRIMARY KEY (poll_id, contestant_id),
  FOREIGN KEY (election_id, contestant_id) REFERENCES contestants(election_id, id)
);

CREATE TABLE observations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  jurisdiction_id text NOT NULL REFERENCES jurisdictions(id),
  metric text NOT NULL,
  observed_at timestamptz NOT NULL,
  released_at timestamptz NOT NULL,
  available_at timestamptz NOT NULL,
  value double precision NOT NULL,
  unit text NOT NULL,
  source_id uuid NOT NULL REFERENCES sources(id),
  source_revision_id uuid NOT NULL REFERENCES source_revisions(id),
  revision integer NOT NULL DEFAULT 0,
  dimensions jsonb NOT NULL DEFAULT '{}',
  UNIQUE (jurisdiction_id, metric, observed_at, source_id, revision),
  UNIQUE (source_revision_id)
);

CREATE TABLE feature_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  election_id text NOT NULL REFERENCES elections(id),
  as_of timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  schema_version text NOT NULL,
  values jsonb NOT NULL,
  source_revision_ids uuid[] NOT NULL,
  content_sha256 text NOT NULL,
  UNIQUE (election_id, as_of, schema_version),
  CHECK (content_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE model_versions (
  id text PRIMARY KEY,
  family text NOT NULL,
  code_sha text NOT NULL,
  config_sha text NOT NULL,
  trained_through timestamptz NOT NULL,
  promoted_at timestamptz,
  selection_evidence jsonb NOT NULL,
  UNIQUE (family, code_sha, config_sha)
);

CREATE TABLE backtest_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  model_version_id text NOT NULL REFERENCES model_versions(id),
  jurisdiction_id text NOT NULL REFERENCES jurisdictions(id),
  started_at timestamptz NOT NULL,
  completed_at timestamptz,
  fold_count integer NOT NULL,
  brier_score double precision,
  vote_share_rmse double precision,
  interval_coverage double precision,
  leakage_check boolean NOT NULL DEFAULT false,
  details jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE simulation_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  election_id text NOT NULL REFERENCES elections(id),
  model_version_id text NOT NULL REFERENCES model_versions(id),
  feature_snapshot_id uuid NOT NULL REFERENCES feature_snapshots(id),
  started_at timestamptz NOT NULL,
  completed_at timestamptz,
  simulation_count integer NOT NULL CHECK (simulation_count = 1000000),
  seed bigint NOT NULL,
  engine text NOT NULL,
  input_sha256 text NOT NULL,
  output_sha256 text,
  status text NOT NULL,
  validation jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE forecast_snapshots (
  id text PRIMARY KEY,
  election_id text NOT NULL REFERENCES elections(id),
  model_version_id text NOT NULL REFERENCES model_versions(id),
  simulation_run_id uuid REFERENCES simulation_runs(id),
  as_of timestamptz NOT NULL,
  published_at timestamptz NOT NULL,
  simulation_count integer NOT NULL CHECK (simulation_count = 1000000),
  seed bigint NOT NULL,
  data_quality char(1) NOT NULL CHECK (data_quality IN ('A','B','C','D')),
  freshness text NOT NULL,
  headline text NOT NULL,
  majority_probability double precision CHECK (majority_probability BETWEEN 0 AND 1),
  turnout_median double precision CHECK (turnout_median BETWEEN 0 AND 1),
  source_manifest jsonb NOT NULL,
  UNIQUE (election_id, model_version_id, as_of),
  UNIQUE (id, election_id)
);

CREATE TABLE forecast_outcomes (
  snapshot_id text NOT NULL REFERENCES forecast_snapshots(id),
  election_id text NOT NULL,
  contestant_id text NOT NULL,
  win_probability double precision NOT NULL CHECK (win_probability BETWEEN 0 AND 1),
  projected_share double precision NOT NULL CHECK (projected_share BETWEEN 0 AND 1),
  share_low double precision NOT NULL,
  share_high double precision NOT NULL,
  projected_seats integer,
  seats_low integer,
  seats_high integer,
  PRIMARY KEY (snapshot_id, contestant_id),
  FOREIGN KEY (snapshot_id, election_id) REFERENCES forecast_snapshots(id, election_id),
  FOREIGN KEY (election_id, contestant_id) REFERENCES contestants(election_id, id),
  CHECK (share_low <= projected_share AND projected_share <= share_high),
  CHECK (seats_low IS NULL OR projected_seats IS NULL OR seats_high IS NULL OR (seats_low <= projected_seats AND projected_seats <= seats_high))
);

CREATE TABLE forecast_coalition_outcomes (
  snapshot_id text NOT NULL,
  election_id text NOT NULL,
  coalition_key text NOT NULL,
  member_ids text[] NOT NULL CHECK (cardinality(member_ids) >= 2),
  majority_probability double precision NOT NULL CHECK (majority_probability BETWEEN 0 AND 1),
  seats_median integer NOT NULL,
  seats_low integer NOT NULL,
  seats_high integer NOT NULL,
  PRIMARY KEY (snapshot_id, coalition_key),
  FOREIGN KEY (snapshot_id, election_id) REFERENCES forecast_snapshots(id, election_id),
  CHECK (seats_low <= seats_median AND seats_median <= seats_high)
);

CREATE TABLE official_results (
  election_id text NOT NULL REFERENCES elections(id),
  reporting_unit_id text NOT NULL,
  contestant_id text NOT NULL,
  votes bigint NOT NULL CHECK (votes >= 0),
  reporting_fraction double precision CHECK (reporting_fraction BETWEEN 0 AND 1),
  reported_at timestamptz NOT NULL,
  source_id uuid NOT NULL REFERENCES sources(id),
  is_certified boolean NOT NULL DEFAULT false,
  PRIMARY KEY (election_id, reporting_unit_id, contestant_id, reported_at),
  FOREIGN KEY (election_id, reporting_unit_id) REFERENCES reporting_units(election_id, id),
  FOREIGN KEY (election_id, contestant_id) REFERENCES contestants(election_id, id)
);

CREATE INDEX observations_vintage_idx ON observations (jurisdiction_id, metric, available_at);
CREATE INDEX polls_vintage_idx ON polls (election_id, available_at DESC, poll_key, revision DESC);
CREATE INDEX source_revisions_vintage_idx
ON source_revisions (source_key, source_record_key, available_at);
CREATE INDEX feature_snapshots_asof_idx ON feature_snapshots (election_id, as_of DESC);
CREATE INDEX elections_calendar_idx ON elections (election_date) WHERE valid_to IS NULL;
CREATE INDEX reporting_units_geometry_idx ON reporting_units USING gist (geometry);
CREATE INDEX forecast_latest_idx ON forecast_snapshots (election_id, published_at DESC);
CREATE INDEX official_results_latest_idx ON official_results (election_id, reported_at DESC);
CREATE INDEX adapter_health_latest_idx
ON adapter_health_events (adapter_id, scope_id, occurred_at DESC);
CREATE INDEX pipeline_run_latest_idx
ON pipeline_run_events (job_name, occurred_at DESC);

CREATE FUNCTION reject_forecast_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Published forecast snapshots are immutable';
END $$;
CREATE TRIGGER forecast_snapshots_immutable
BEFORE UPDATE OR DELETE ON forecast_snapshots
FOR EACH ROW EXECUTE FUNCTION reject_forecast_mutation();

CREATE TRIGGER forecast_outcomes_immutable
BEFORE UPDATE OR DELETE ON forecast_outcomes
FOR EACH ROW EXECUTE FUNCTION reject_forecast_mutation();

CREATE TRIGGER forecast_coalition_outcomes_immutable
BEFORE UPDATE OR DELETE ON forecast_coalition_outcomes
FOR EACH ROW EXECUTE FUNCTION reject_forecast_mutation();

CREATE FUNCTION reject_evidence_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Source-vintage evidence is append-only';
END $$;

CREATE TRIGGER sources_immutable
BEFORE UPDATE OR DELETE ON sources
FOR EACH ROW EXECUTE FUNCTION reject_evidence_mutation();

CREATE TRIGGER source_revisions_immutable
BEFORE UPDATE OR DELETE ON source_revisions
FOR EACH ROW EXECUTE FUNCTION reject_evidence_mutation();

CREATE TRIGGER observations_immutable
BEFORE UPDATE OR DELETE ON observations
FOR EACH ROW EXECUTE FUNCTION reject_evidence_mutation();

CREATE TRIGGER polls_immutable
BEFORE UPDATE OR DELETE ON polls
FOR EACH ROW EXECUTE FUNCTION reject_evidence_mutation();

CREATE TRIGGER calendar_revisions_immutable
BEFORE UPDATE OR DELETE ON calendar_revisions
FOR EACH ROW EXECUTE FUNCTION reject_evidence_mutation();

CREATE TRIGGER poll_results_immutable
BEFORE UPDATE OR DELETE ON poll_results
FOR EACH ROW EXECUTE FUNCTION reject_evidence_mutation();

CREATE TRIGGER feature_snapshots_immutable
BEFORE UPDATE OR DELETE ON feature_snapshots
FOR EACH ROW EXECUTE FUNCTION reject_evidence_mutation();

CREATE TRIGGER adapter_health_events_immutable
BEFORE UPDATE OR DELETE ON adapter_health_events
FOR EACH ROW EXECUTE FUNCTION reject_evidence_mutation();

CREATE TRIGGER pipeline_run_events_immutable
BEFORE UPDATE OR DELETE ON pipeline_run_events
FOR EACH ROW EXECUTE FUNCTION reject_evidence_mutation();

CREATE TRIGGER official_results_immutable
BEFORE UPDATE OR DELETE ON official_results
FOR EACH ROW EXECUTE FUNCTION reject_evidence_mutation();

CREATE TABLE audit_log (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  actor text NOT NULL,
  action text NOT NULL,
  entity_type text NOT NULL,
  entity_id text NOT NULL,
  details jsonb NOT NULL DEFAULT '{}'
);

CREATE FUNCTION record_audit_event() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  row_data jsonb := COALESCE(to_jsonb(NEW), to_jsonb(OLD));
BEGIN
  INSERT INTO audit_log (actor, action, entity_type, entity_id, details)
  VALUES (
    current_user,
    TG_OP,
    TG_TABLE_NAME,
    COALESCE(row_data ->> 'id', row_data ->> 'snapshot_id', row_data ->> 'scope_id', row_data ->> 'election_id', 'unknown'),
    row_data
  );
  RETURN COALESCE(NEW, OLD);
END $$;

CREATE TRIGGER adapter_checkpoints_audit
AFTER INSERT OR UPDATE OR DELETE ON adapter_checkpoints
FOR EACH ROW EXECUTE FUNCTION record_audit_event();

CREATE TRIGGER adapter_health_events_audit
AFTER INSERT ON adapter_health_events
FOR EACH ROW EXECUTE FUNCTION record_audit_event();

CREATE TRIGGER pipeline_run_events_audit
AFTER INSERT ON pipeline_run_events
FOR EACH ROW EXECUTE FUNCTION record_audit_event();

CREATE TRIGGER forecast_snapshots_audit
AFTER INSERT ON forecast_snapshots
FOR EACH ROW EXECUTE FUNCTION record_audit_event();

CREATE TRIGGER feature_snapshots_audit
AFTER INSERT ON feature_snapshots
FOR EACH ROW EXECUTE FUNCTION record_audit_event();

CREATE TRIGGER polls_audit
AFTER INSERT ON polls
FOR EACH ROW EXECUTE FUNCTION record_audit_event();

CREATE TRIGGER calendar_revisions_audit
AFTER INSERT ON calendar_revisions
FOR EACH ROW EXECUTE FUNCTION record_audit_event();

CREATE TRIGGER poll_results_audit
AFTER INSERT ON poll_results
FOR EACH ROW EXECUTE FUNCTION record_audit_event();

CREATE TRIGGER official_results_audit
AFTER INSERT ON official_results
FOR EACH ROW EXECUTE FUNCTION record_audit_event();

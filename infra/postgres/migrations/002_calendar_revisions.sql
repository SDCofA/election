CREATE TABLE IF NOT EXISTS calendar_revisions (
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

CREATE INDEX IF NOT EXISTS calendar_revisions_latest_idx
ON calendar_revisions (election_id, revision DESC, available_at DESC);

CREATE OR REPLACE FUNCTION reject_evidence_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Source-vintage evidence is append-only';
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger
    WHERE tgname = 'calendar_revisions_immutable' AND tgrelid = 'calendar_revisions'::regclass
  ) THEN
    CREATE TRIGGER calendar_revisions_immutable
    BEFORE UPDATE OR DELETE ON calendar_revisions
    FOR EACH ROW EXECUTE FUNCTION reject_evidence_mutation();
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger
    WHERE tgname = 'calendar_revisions_audit' AND tgrelid = 'calendar_revisions'::regclass
  ) THEN
    CREATE TRIGGER calendar_revisions_audit
    AFTER INSERT ON calendar_revisions
    FOR EACH ROW EXECUTE FUNCTION record_audit_event();
  END IF;
END $$;

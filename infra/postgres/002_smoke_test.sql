BEGIN;

INSERT INTO jurisdictions (id, iso3, name, region, eligibility)
VALUES ('tst', 'TST', 'Test Jurisdiction', 'Test', 'test');

INSERT INTO sources (
  id, source_key, label, url, authority, license, license_url, attribution, usage_scope,
  license_approved, retrieved_at, content_sha256, object_uri, parser_version, parser_confidence
) VALUES (
  '00000000-0000-0000-0000-000000000001', 'fixture', 'Fixture',
  'https://example.test', 'official', 'CC0-1.0', 'https://example.test/license',
  'Fixture', 'Fixture only', true, now(), repeat('a', 64), 's3://fixture/a', 'v1', 1
);

INSERT INTO elections (
  id, jurisdiction_id, name, election_date, date_confidence, system, status,
  source_id, valid_from
) VALUES (
  'tst-election', 'tst', 'Test Election', '2030-01-01', 'fixture', 'fptp',
  'fixture', '00000000-0000-0000-0000-000000000001', now()
);

INSERT INTO contestants (id, election_id, name, short_name, color)
VALUES ('a', 'tst-election', 'A', 'A', '#000000');

INSERT INTO model_versions (
  id, family, code_sha, config_sha, trained_through, promoted_at, selection_evidence
) VALUES ('test-model', 'baseline_ensemble', repeat('b', 40), repeat('c', 64), now(), now(), '{}');

INSERT INTO forecast_snapshots (
  id, election_id, model_version_id, as_of, published_at, simulation_count, seed,
  data_quality, freshness, headline, majority_probability, turnout_median, source_manifest
) VALUES (
  'test-snapshot', 'tst-election', 'test-model', now(), now(), 1000000, 42,
  'D', 'fixture', 'fixture', 0.5, 0.6, '{}'
);

INSERT INTO forecast_outcomes (
  snapshot_id, election_id, contestant_id, win_probability, projected_share, share_low, share_high
) VALUES ('test-snapshot', 'tst-election', 'a', 1, 1, 0.9, 1);

DO $$
BEGIN
  BEGIN
    INSERT INTO forecast_snapshots (
      id, election_id, model_version_id, as_of, published_at, simulation_count, seed,
      data_quality, freshness, headline, majority_probability, turnout_median, source_manifest
    ) VALUES (
      'invalid-simulation-count', 'tst-election', 'test-model', now() + interval '1 second',
      now(), 1000001, 43, 'D', 'fixture', 'fixture', 0.5, 0.6, '{}'
    );
    RAISE EXCEPTION 'Forecast accepted a simulation count other than exactly one million';
  EXCEPTION WHEN check_violation THEN
    NULL;
  END;
END $$;

INSERT INTO source_revisions (
  id, source_id, source_key, source_record_key, revision, observed_at, released_at,
  available_at, payload, payload_sha256
) VALUES (
  '00000000-0000-0000-0000-000000000003',
  '00000000-0000-0000-0000-000000000001', 'fixture', 'tst:fixture_metric', 0,
  now(), now(), now(), '{"value": 1}', repeat('d', 64)
);

INSERT INTO observations (
  id, jurisdiction_id, metric, observed_at, released_at, available_at,
  value, unit, source_id, source_revision_id
) VALUES (
  '00000000-0000-0000-0000-000000000002', 'tst', 'fixture_metric', now(), now(), now(),
  1, 'index', '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000003'
);

INSERT INTO source_revisions (
  id, source_id, source_key, source_record_key, revision, observed_at, released_at,
  available_at, payload, payload_sha256
) VALUES (
  '00000000-0000-0000-0000-000000000004',
  '00000000-0000-0000-0000-000000000001', 'fixture', 'tst-election:calendar', 0,
  now(), now(), now(), '{"election_date": "2030-01-01"}', repeat('e', 64)
);

INSERT INTO calendar_revisions (
  id, election_id, revision, election_date, date_confidence, status, released_at,
  available_at, parser_version, parser_confidence
) VALUES (
  '00000000-0000-0000-0000-000000000004', 'tst-election', 0, '2030-01-01',
  'official', 'confirmed', now(), now(), 'fixture-v1', 1
);

DO $$
DECLARE
  mutation_rejected boolean := false;
BEGIN
  BEGIN
    UPDATE forecast_snapshots SET headline = 'mutated' WHERE id = 'test-snapshot';
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM LIKE 'Published forecast snapshots are immutable%' THEN
      mutation_rejected := true;
    ELSE
      RAISE;
    END IF;
  END;
  IF NOT mutation_rejected THEN
    RAISE EXCEPTION 'Immutable forecast trigger did not reject update';
  END IF;
END $$;

DO $$
DECLARE
  mutation_rejected boolean := false;
BEGIN
  BEGIN
    UPDATE calendar_revisions SET election_date = '2030-01-02'
    WHERE id = '00000000-0000-0000-0000-000000000004';
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM LIKE 'Source-vintage evidence is append-only%' THEN
      mutation_rejected := true;
    ELSE
      RAISE;
    END IF;
  END;
  IF NOT mutation_rejected THEN
    RAISE EXCEPTION 'Append-only calendar trigger did not reject update';
  END IF;
END $$;

DO $$
DECLARE
  mutation_rejected boolean := false;
BEGIN
  BEGIN
    UPDATE observations SET value = 2
    WHERE id = '00000000-0000-0000-0000-000000000002';
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM LIKE 'Source-vintage evidence is append-only%' THEN
      mutation_rejected := true;
    ELSE
      RAISE;
    END IF;
  END;
  IF NOT mutation_rejected THEN
    RAISE EXCEPTION 'Append-only evidence trigger did not reject update';
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM audit_log
    WHERE entity_type = 'forecast_snapshots' AND entity_id = 'test-snapshot'
  ) THEN
    RAISE EXCEPTION 'Forecast publication audit event was not recorded';
  END IF;
END $$;

ROLLBACK;

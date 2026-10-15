DO $roles$
DECLARE
    target_schema TEXT := current_schema();
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_auth_members memberships
        JOIN pg_roles member_role ON member_role.oid = memberships.member
        JOIN pg_roles parent_role ON parent_role.oid = memberships.roleid
        WHERE member_role.rolname IN (
            'radar_platform_reader', 'radar_platform_writer', 'radar_platform_migrator'
        )
          AND parent_role.rolname = 'neon_superuser'
    ) THEN
        RAISE EXCEPTION
            'platform roles must be created as least-privilege SQL roles, not Neon control-plane roles';
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'radar_platform_reader') THEN
        EXECUTE format('GRANT USAGE ON SCHEMA %I TO radar_platform_reader', target_schema);
        GRANT SELECT ON TABLE
            radar_schema_migrations, radar_terms, radar_evidence, radar_relations,
            radar_source_state, radar_jobs, radar_runs, radar_checks, radar_reports
        TO radar_platform_reader;
        EXECUTE format(
            'ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT SELECT ON TABLES TO radar_platform_reader',
            target_schema
        );
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'radar_platform_writer') THEN
        EXECUTE format('GRANT USAGE ON SCHEMA %I TO radar_platform_writer', target_schema);
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
            radar_terms, radar_evidence, radar_relations, radar_source_state,
            radar_jobs, radar_runs, radar_checks, radar_reports
        TO radar_platform_writer;
        EXECUTE format(
            'ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO radar_platform_writer',
            target_schema
        );
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'radar_platform_migrator') THEN
        EXECUTE format('GRANT USAGE, CREATE ON SCHEMA %I TO radar_platform_migrator', target_schema);
        GRANT ALL PRIVILEGES ON TABLE
            radar_schema_migrations, radar_terms, radar_evidence, radar_relations,
            radar_source_state, radar_jobs, radar_runs, radar_checks, radar_reports
        TO radar_platform_migrator;
    END IF;

END
$roles$;


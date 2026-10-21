DO $roles$
DECLARE
    target_schema TEXT := current_schema();
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'radar_platform_reader') THEN
        EXECUTE format('GRANT USAGE ON SCHEMA %I TO radar_platform_reader', target_schema);
        GRANT SELECT ON TABLE radar_sites, radar_site_state, radar_site_urls, radar_site_events
        TO radar_platform_reader;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'radar_platform_writer') THEN
        EXECUTE format('GRANT USAGE ON SCHEMA %I TO radar_platform_writer', target_schema);
        GRANT SELECT, UPDATE ON TABLE radar_sites TO radar_platform_writer;
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE radar_site_state, radar_site_urls, radar_site_events
        TO radar_platform_writer;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'radar_platform_site_admin') THEN
        IF pg_has_role('radar_platform_site_admin', 'neon_superuser', 'member') THEN
            RAISE EXCEPTION 'site-admin role must not inherit neon_superuser';
        END IF;
        EXECUTE format('GRANT USAGE ON SCHEMA %I TO radar_platform_site_admin', target_schema);
        GRANT SELECT, INSERT, UPDATE ON TABLE radar_sites TO radar_platform_site_admin;
        EXECUTE format(
            'ALTER DEFAULT PRIVILEGES IN SCHEMA %I REVOKE ALL ON TABLES FROM radar_platform_site_admin',
            target_schema
        );
    END IF;
END
$roles$;

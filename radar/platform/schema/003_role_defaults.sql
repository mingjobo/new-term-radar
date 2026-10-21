DO $roles$
DECLARE
    target_schema TEXT := current_schema();
BEGIN
    -- Every platform table grant stays explicit. Broad default grants would
    -- accidentally expose unrelated legacy or future tables in public.
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'radar_platform_reader') THEN
        EXECUTE format(
            'ALTER DEFAULT PRIVILEGES IN SCHEMA %I REVOKE SELECT ON TABLES FROM radar_platform_reader',
            target_schema
        );
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'radar_platform_writer') THEN
        EXECUTE format(
            'ALTER DEFAULT PRIVILEGES IN SCHEMA %I REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM radar_platform_writer',
            target_schema
        );
    END IF;
END
$roles$;

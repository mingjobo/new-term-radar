CREATE TABLE radar_sites (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL CHECK (char_length(trim(name)) BETWEEN 1 AND 200),
    homepage_url TEXT NOT NULL,
    host TEXT NOT NULL UNIQUE,
    sitemap_url TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE radar_site_state (
    site_id UUID PRIMARY KEY REFERENCES radar_sites(id) ON DELETE RESTRICT,
    version INTEGER NOT NULL CHECK (version > 0),
    url_count INTEGER NOT NULL CHECK (url_count > 0),
    last_success_at TIMESTAMPTZ NOT NULL,
    last_run_key TEXT NOT NULL,
    last_scheduled_for TIMESTAMPTZ NOT NULL
);

CREATE TABLE radar_site_urls (
    site_id UUID NOT NULL REFERENCES radar_sites(id) ON DELETE RESTRICT,
    url TEXT NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (site_id, url)
);

CREATE TABLE radar_site_events (
    id UUID PRIMARY KEY,
    site_id UUID NOT NULL REFERENCES radar_sites(id) ON DELETE RESTRICT,
    run_key TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('added', 'removed')),
    url TEXT NOT NULL,
    discovered_at TIMESTAMPTZ NOT NULL,
    UNIQUE (site_id, run_key, event_type, url)
);

CREATE INDEX radar_sites_enabled_idx ON radar_sites (enabled, name);
CREATE INDEX radar_site_events_site_discovered_idx ON radar_site_events (site_id, discovered_at DESC, id);
CREATE INDEX radar_site_events_discovered_idx ON radar_site_events (discovered_at DESC, site_id);

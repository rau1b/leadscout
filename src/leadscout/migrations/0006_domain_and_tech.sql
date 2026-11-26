-- Domain and certificate dates (RDAP, the site's TLS certificate) and the detected technology, per audit.
alter table audits add column domain_registered text;  -- YYYY-MM-DD
alter table audits add column domain_expires text;     -- YYYY-MM-DD
alter table audits add column cert_expires text;       -- YYYY-MM-DD
alter table audits add column tech text;               -- e.g. "WordPress, Elementor, jQuery 1.12"
alter table audits add column cms_version text;        -- e.g. "6.4.2"

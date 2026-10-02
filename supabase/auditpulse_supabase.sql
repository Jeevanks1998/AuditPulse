-- =============================================================================
-- AuditPulse — Supabase database setup
-- =============================================================================
-- Run this ONCE in the AuditPulse Supabase project:
--   Supabase dashboard -> SQL Editor -> New query -> paste all of this -> Run
--
-- Safe to run more than once, and safe on a database that already has data:
--   * every table/index uses IF NOT EXISTS
--   * the Google Authenticator columns are added only if missing
--   * the migration version is only recorded on a brand-new database
--
-- After this, deploy on Railway as normal: its start command runs
-- `alembic upgrade head`, which will find nothing left to do.
-- No demo user or admin is created. Users come from the Access Portal.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. Tables and indexes (generated from backend/models — matches the code)
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS users (
	id SERIAL NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	hashed_password VARCHAR(255), 
	company VARCHAR(120) NOT NULL, 
	ai_provider VARCHAR(60) NOT NULL, 
	api_key VARCHAR(64) NOT NULL, 
	role VARCHAR(40) NOT NULL, 
	auditpulse_access BOOLEAN NOT NULL, 
	notify_audit_completed BOOLEAN NOT NULL, 
	notify_critical_issue BOOLEAN NOT NULL, 
	notify_weekly_summary BOOLEAN NOT NULL, 
	theme VARCHAR(20) NOT NULL, 
	language VARCHAR(40) NOT NULL, 
	schedule_frequency VARCHAR(40) NOT NULL, 
	schedule_time VARCHAR(80) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	mfa_secret VARCHAR(64), 
	mfa_enabled BOOLEAN NOT NULL, 
	auth_setup_required BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (api_key)
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email);

CREATE TABLE IF NOT EXISTS websites (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	url VARCHAR(500) NOT NULL, 
	hostname VARCHAR(255) NOT NULL, 
	favicon_url VARCHAR(500), 
	is_monitored BOOLEAN NOT NULL, 
	audit_count INTEGER NOT NULL, 
	last_overall_score INTEGER, 
	first_audited_at TIMESTAMP WITH TIME ZONE, 
	last_audited_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_websites_hostname ON websites (hostname);
CREATE INDEX IF NOT EXISTS ix_websites_user_id ON websites (user_id);

CREATE TABLE IF NOT EXISTS audits (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	website_id INTEGER, 
	url VARCHAR(500) NOT NULL, 
	label VARCHAR(40) NOT NULL, 
	depth VARCHAR(20) NOT NULL, 
	max_pages INTEGER NOT NULL, 
	modules JSON NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	current_step VARCHAR(40), 
	percent INTEGER NOT NULL, 
	overall_score INTEGER, 
	breakdown JSON, 
	findings JSON, 
	error_message VARCHAR(500), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(website_id) REFERENCES websites (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_audits_user_id ON audits (user_id);
CREATE INDEX IF NOT EXISTS ix_audits_website_id ON audits (website_id);

CREATE TABLE IF NOT EXISTS analytics_results (
	id SERIAL NOT NULL, 
	audit_id INTEGER NOT NULL, 
	trackers_detected JSON NOT NULL, 
	tag_manager_detected BOOLEAN NOT NULL, 
	gtm_container_id VARCHAR(40), 
	ga_measurement_id VARCHAR(40), 
	vendor_configs JSON NOT NULL, 
	data_layer_present BOOLEAN NOT NULL, 
	pageview_events_found INTEGER NOT NULL, 
	custom_events_found INTEGER NOT NULL, 
	analytics_score INTEGER NOT NULL, 
	runtime_available BOOLEAN NOT NULL, 
	runtime_tested BOOLEAN NOT NULL, 
	runtime_result JSON, 
	page_results JSON NOT NULL, 
	site_coverage JSON NOT NULL, 
	cross_page_findings JSON NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(audit_id) REFERENCES audits (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_analytics_results_audit_id ON analytics_results (audit_id);

CREATE TABLE IF NOT EXISTS consent_results (
	id SERIAL NOT NULL, 
	audit_id INTEGER NOT NULL, 
	has_cookie_banner BOOLEAN NOT NULL, 
	banner_blocks_scripts_pre_consent BOOLEAN NOT NULL, 
	gdpr_compliant BOOLEAN NOT NULL, 
	gdpr_checks JSON NOT NULL, 
	gdpr_check_evidence JSON NOT NULL, 
	ccpa_compliant BOOLEAN NOT NULL, 
	ccpa_checks JSON NOT NULL, 
	applicability JSON NOT NULL, 
	technical_scan JSON NOT NULL, 
	detected_region VARCHAR(16) NOT NULL, 
	region_confidence VARCHAR(16) NOT NULL, 
	region_evidence JSON NOT NULL, 
	applicable_frameworks JSON NOT NULL, 
	applicability_status VARCHAR(32) NOT NULL, 
	consent_controls JSON NOT NULL, 
	privacy_policy_found BOOLEAN NOT NULL, 
	privacy_policy_url VARCHAR(500), 
	cookies_detected JSON NOT NULL, 
	third_party_trackers JSON NOT NULL, 
	consent_score INTEGER NOT NULL, 
	banner_screenshot_path VARCHAR(500), 
	preferences_screenshot_path VARCHAR(500), 
	reject_screenshot_path VARCHAR(500), 
	accept_screenshot_path VARCHAR(500), 
	runtime_available BOOLEAN NOT NULL, 
	runtime_tested BOOLEAN NOT NULL, 
	runtime_result JSON, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(audit_id) REFERENCES audits (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_consent_results_audit_id ON consent_results (audit_id);

CREATE TABLE IF NOT EXISTS history_events (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	audit_id INTEGER, 
	event_type VARCHAR(40) NOT NULL, 
	description TEXT NOT NULL, 
	meta JSON, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(audit_id) REFERENCES audits (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_history_events_audit_id ON history_events (audit_id);
CREATE INDEX IF NOT EXISTS ix_history_events_created_at ON history_events (created_at);
CREATE INDEX IF NOT EXISTS ix_history_events_event_type ON history_events (event_type);
CREATE INDEX IF NOT EXISTS ix_history_events_user_id ON history_events (user_id);

CREATE TABLE IF NOT EXISTS issues (
	id SERIAL NOT NULL, 
	audit_id INTEGER NOT NULL, 
	module VARCHAR(40) NOT NULL, 
	severity VARCHAR(20) NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	description TEXT NOT NULL, 
	recommendation TEXT, 
	element_selector VARCHAR(300), 
	status VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	resolved_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(audit_id) REFERENCES audits (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_issues_audit_id ON issues (audit_id);
CREATE INDEX IF NOT EXISTS ix_issues_module ON issues (module);
CREATE INDEX IF NOT EXISTS ix_issues_severity ON issues (severity);
CREATE INDEX IF NOT EXISTS ix_issues_status ON issues (status);

CREATE TABLE IF NOT EXISTS journey_results (
	id SERIAL NOT NULL, 
	audit_id INTEGER NOT NULL, 
	available BOOLEAN NOT NULL, 
	error VARCHAR(500), 
	scan_id VARCHAR(80), 
	consent_state VARCHAR(120), 
	journey_score INTEGER, 
	health JSON NOT NULL, 
	pages JSON NOT NULL, 
	interactions JSON NOT NULL, 
	forms JSON NOT NULL, 
	downloads JSON NOT NULL, 
	journey_map JSON NOT NULL, 
	tracking JSON NOT NULL, 
	findings JSON NOT NULL, 
	limits JSON NOT NULL, 
	started_at VARCHAR(40), 
	finished_at VARCHAR(40), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(audit_id) REFERENCES audits (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_journey_results_audit_id ON journey_results (audit_id);

CREATE TABLE IF NOT EXISTS report_emails (
	id SERIAL NOT NULL, 
	audit_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	recipient_to JSON NOT NULL, 
	recipient_cc JSON NOT NULL, 
	recipient_bcc JSON NOT NULL, 
	subject VARCHAR(255) NOT NULL, 
	body TEXT NOT NULL, 
	attachments JSON NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	error_message TEXT, 
	sent_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(audit_id) REFERENCES audits (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_report_emails_audit_id ON report_emails (audit_id);
CREATE INDEX IF NOT EXISTS ix_report_emails_sent_at ON report_emails (sent_at);
CREATE INDEX IF NOT EXISTS ix_report_emails_status ON report_emails (status);
CREATE INDEX IF NOT EXISTS ix_report_emails_user_id ON report_emails (user_id);

CREATE TABLE IF NOT EXISTS reports (
	id SERIAL NOT NULL, 
	audit_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	share_token VARCHAR(64), 
	is_public BOOLEAN NOT NULL, 
	pdf_path VARCHAR(500), 
	view_count INTEGER NOT NULL, 
	generated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(audit_id) REFERENCES audits (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_reports_audit_id ON reports (audit_id);
CREATE UNIQUE INDEX IF NOT EXISTS ix_reports_share_token ON reports (share_token);
CREATE INDEX IF NOT EXISTS ix_reports_user_id ON reports (user_id);

-- -----------------------------------------------------------------------------
-- 2. Google Authenticator sign-in (email -> 6-digit code, no password)
--    For a database created before this change: add the new columns.
--      New user:              mfa_enabled = false, auth_setup_required = true
--      After first QR setup:  mfa_enabled = true,  auth_setup_required = false
--      Admin reset:           mfa_enabled = false, auth_setup_required = true
-- -----------------------------------------------------------------------------

ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_secret VARCHAR(64);
ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_setup_required BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE users ALTER COLUMN mfa_enabled SET DEFAULT FALSE;
ALTER TABLE users ALTER COLUMN auth_setup_required SET DEFAULT TRUE;
-- Passwords are no longer used.
ALTER TABLE users ALTER COLUMN hashed_password DROP NOT NULL;

-- Per-audit privacy region (Auto / EU / UK / US-CA / IN) chosen on the audit page.
ALTER TABLE audits ADD COLUMN IF NOT EXISTS target_region VARCHAR(10);

-- -----------------------------------------------------------------------------
-- 3. Migration bookkeeping (Alembic)
--    Brand-new database: record it as fully up to date, so Railway's
--    `alembic upgrade head` doesn't try to re-apply old migrations.
--    Existing database: left alone; alembic applies whatever is missing.
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

INSERT INTO alembic_version (version_num)
SELECT 'a4d2e8c6f913'
WHERE NOT EXISTS (SELECT 1 FROM alembic_version);

COMMIT;

-- Check: should list 10 tables + alembic_version, and version a4d2e8c6f913
-- SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY 1;
-- SELECT * FROM alembic_version;

-- Additive runtime DDL: no v3 migrated table or mapping is altered.
CREATE TABLE IF NOT EXISTS import_steps(
 job_id INTEGER NOT NULL REFERENCES jobs(id), name TEXT NOT NULL, position INTEGER NOT NULL,
 sources TEXT NOT NULL, source_index INTEGER NOT NULL DEFAULT 0, source TEXT,
 state TEXT NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','running','waiting_for_budget','failed','done')),
 error TEXT, retry_at TEXT, count INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 1,
 updated_at TEXT NOT NULL, PRIMARY KEY(job_id,name));
CREATE TABLE IF NOT EXISTS import_calls(
 job_id INTEGER NOT NULL, step TEXT NOT NULL, operation TEXT NOT NULL,
 request_job INTEGER REFERENCES jobs(id), result TEXT,
 PRIMARY KEY(job_id,step,operation),
 FOREIGN KEY(job_id,step) REFERENCES import_steps(job_id,name));
CREATE INDEX IF NOT EXISTS import_calls_request ON import_calls(request_job);
-- A local process owner permits restart recovery while excluding a live worker.
CREATE TABLE IF NOT EXISTS import_owners(
 job_id INTEGER PRIMARY KEY REFERENCES jobs(id), pid INTEGER NOT NULL);

CREATE INDEX IF NOT EXISTS import_owners_job ON import_owners(job_id);

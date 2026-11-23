-- Alderwood University Hybrid RAG — PostgreSQL 16 + pgvector + FTS Schema
-- 20 tables (18 operational academic/financial tables including deliberate distractors + 2 RAG index tables)

CREATE EXTENSION IF NOT EXISTS vector;

-- 1. Core: departments
CREATE TABLE IF NOT EXISTS departments (
    dept_code VARCHAR(16) PRIMARY KEY,
    dept_name VARCHAR(120) NOT NULL,
    dean_name VARCHAR(120) NOT NULL,
    building VARCHAR(80) NOT NULL,
    annual_grant_pool NUMERIC(12, 2) NOT NULL
);

-- 2. Core: students (deliberate GPA ambiguity: cumulative_gpa vs semester_gpa)
CREATE TABLE IF NOT EXISTS students (
    student_id VARCHAR(16) PRIMARY KEY,
    full_name VARCHAR(120) NOT NULL,
    email VARCHAR(160) UNIQUE NOT NULL,
    dept_code VARCHAR(16) NOT NULL REFERENCES departments(dept_code),
    year_of_study INT NOT NULL CHECK (year_of_study BETWEEN 1 AND 6),
    cumulative_gpa NUMERIC(3, 2) NOT NULL CHECK (cumulative_gpa BETWEEN 0.00 AND 4.00),
    semester_gpa NUMERIC(3, 2) NOT NULL CHECK (semester_gpa BETWEEN 0.00 AND 4.00),
    advisor_name VARCHAR(120) NOT NULL,
    enrollment_status VARCHAR(32) NOT NULL,
    residency_status VARCHAR(32) NOT NULL
);

-- 3. Core: courses
CREATE TABLE IF NOT EXISTS courses (
    course_id VARCHAR(16) PRIMARY KEY,
    dept_code VARCHAR(16) NOT NULL REFERENCES departments(dept_code),
    title VARCHAR(160) NOT NULL,
    credits INT NOT NULL CHECK (credits BETWEEN 1 AND 6),
    course_level INT NOT NULL,
    instructor_name VARCHAR(120) NOT NULL,
    max_capacity INT NOT NULL
);

-- 4. Core: enrollments
CREATE TABLE IF NOT EXISTS enrollments (
    enrollment_id VARCHAR(20) PRIMARY KEY,
    student_id VARCHAR(16) NOT NULL REFERENCES students(student_id),
    course_id VARCHAR(16) NOT NULL REFERENCES courses(course_id),
    term VARCHAR(24) NOT NULL,
    grade_points NUMERIC(3, 2),
    letter_grade VARCHAR(4),
    status VARCHAR(24) NOT NULL
);

-- 5. Core: grants (soft conditions like faculty mentor & non-stackability intentionally live ONLY in PDFs)
CREATE TABLE IF NOT EXISTS grants (
    grant_id VARCHAR(24) PRIMARY KEY,
    grant_name VARCHAR(160) NOT NULL,
    dept_code VARCHAR(16) NOT NULL,
    min_gpa NUMERIC(3, 2) NOT NULL,
    min_year INT NOT NULL,
    max_year INT NOT NULL,
    award_amount NUMERIC(10, 2) NOT NULL,
    deadline DATE NOT NULL,
    status VARCHAR(24) NOT NULL,
    funding_cycle VARCHAR(32) NOT NULL
);

-- 6. Core: fee_ledger (student-level billing ledger)
CREATE TABLE IF NOT EXISTS fee_ledger (
    ledger_id VARCHAR(24) PRIMARY KEY,
    student_id VARCHAR(16) NOT NULL REFERENCES students(student_id),
    term VARCHAR(24) NOT NULL,
    category VARCHAR(48) NOT NULL,
    amount_due NUMERIC(10, 2) NOT NULL,
    amount_paid NUMERIC(10, 2) NOT NULL,
    due_date DATE NOT NULL,
    status VARCHAR(24) NOT NULL
);

-- 7. Core: timetable
CREATE TABLE IF NOT EXISTS timetable (
    slot_id VARCHAR(24) PRIMARY KEY,
    course_id VARCHAR(16) NOT NULL REFERENCES courses(course_id),
    term VARCHAR(24) NOT NULL,
    day_of_week VARCHAR(16) NOT NULL,
    start_time VARCHAR(8) NOT NULL,
    end_time VARCHAR(8) NOT NULL,
    room VARCHAR(32) NOT NULL,
    building VARCHAR(80) NOT NULL
);

-- 8. Distractor for grants: grant_applications
CREATE TABLE IF NOT EXISTS grant_applications (
    application_id VARCHAR(24) PRIMARY KEY,
    grant_id VARCHAR(24) NOT NULL REFERENCES grants(grant_id),
    student_id VARCHAR(16) NOT NULL REFERENCES students(student_id),
    submitted_at DATE NOT NULL,
    decision_status VARCHAR(32) NOT NULL,
    requested_amount NUMERIC(10, 2) NOT NULL
);

-- 9. Distractor for grants: grant_history
CREATE TABLE IF NOT EXISTS grant_history (
    history_id VARCHAR(24) PRIMARY KEY,
    grant_id VARCHAR(24) NOT NULL REFERENCES grants(grant_id),
    fiscal_year INT NOT NULL,
    total_disbursed NUMERIC(12, 2) NOT NULL,
    recipients_count INT NOT NULL,
    archived_deadline DATE NOT NULL
);

-- 10. Distractor / related: grant_reviewers
CREATE TABLE IF NOT EXISTS grant_reviewers (
    reviewer_id VARCHAR(24) PRIMARY KEY,
    grant_id VARCHAR(24) NOT NULL REFERENCES grants(grant_id),
    faculty_name VARCHAR(120) NOT NULL,
    dept_code VARCHAR(16) NOT NULL REFERENCES departments(dept_code),
    review_round VARCHAR(32) NOT NULL
);

-- 11. Distractor for fee_ledger: fees (published base fee schedule)
CREATE TABLE IF NOT EXISTS fees (
    fee_schedule_id VARCHAR(24) PRIMARY KEY,
    dept_code VARCHAR(16) NOT NULL REFERENCES departments(dept_code),
    residency_status VARCHAR(32) NOT NULL,
    term VARCHAR(24) NOT NULL,
    base_tuition NUMERIC(10, 2) NOT NULL,
    lab_fee NUMERIC(10, 2) NOT NULL,
    health_fee NUMERIC(10, 2) NOT NULL
);

-- 12. Distractor for fee_ledger/fees: fee_waivers
CREATE TABLE IF NOT EXISTS fee_waivers (
    waiver_id VARCHAR(24) PRIMARY KEY,
    student_id VARCHAR(16) NOT NULL REFERENCES students(student_id),
    waiver_type VARCHAR(64) NOT NULL,
    waiver_amount NUMERIC(10, 2) NOT NULL,
    term VARCHAR(24) NOT NULL,
    approved_by VARCHAR(120) NOT NULL,
    status VARCHAR(24) NOT NULL
);

-- 13. Distractor / detail for GPA ambiguity: student_semester_gpas
CREATE TABLE IF NOT EXISTS student_semester_gpas (
    record_id VARCHAR(24) PRIMARY KEY,
    student_id VARCHAR(16) NOT NULL REFERENCES students(student_id),
    term VARCHAR(24) NOT NULL,
    semester_gpa NUMERIC(3, 2) NOT NULL,
    credits_attempted INT NOT NULL,
    deans_list_flag BOOLEAN NOT NULL
);

-- 14. Related: student_awards
CREATE TABLE IF NOT EXISTS student_awards (
    award_id VARCHAR(24) PRIMARY KEY,
    student_id VARCHAR(16) NOT NULL REFERENCES students(student_id),
    award_title VARCHAR(160) NOT NULL,
    awarded_term VARCHAR(24) NOT NULL,
    stipend_amount NUMERIC(10, 2) NOT NULL
);

-- 15. Core/Related: faculty_mentors
CREATE TABLE IF NOT EXISTS faculty_mentors (
    mentor_id VARCHAR(24) PRIMARY KEY,
    faculty_name VARCHAR(120) NOT NULL,
    dept_code VARCHAR(16) NOT NULL REFERENCES departments(dept_code),
    research_area VARCHAR(160) NOT NULL,
    accepting_undergrads BOOLEAN NOT NULL,
    office_room VARCHAR(48) NOT NULL
);

-- 16. Related: research_labs
CREATE TABLE IF NOT EXISTS research_labs (
    lab_id VARCHAR(24) PRIMARY KEY,
    lab_name VARCHAR(160) NOT NULL,
    dept_code VARCHAR(16) NOT NULL REFERENCES departments(dept_code),
    pi_name VARCHAR(120) NOT NULL,
    building VARCHAR(80) NOT NULL,
    safety_clearance_required BOOLEAN NOT NULL
);

-- 17. Related: academic_calendar
CREATE TABLE IF NOT EXISTS academic_calendar (
    event_id VARCHAR(24) PRIMARY KEY,
    term VARCHAR(24) NOT NULL,
    event_name VARCHAR(160) NOT NULL,
    event_date DATE NOT NULL,
    category VARCHAR(48) NOT NULL
);

-- 18. Distractor for grants: scholarships_archive
CREATE TABLE IF NOT EXISTS scholarships_archive (
    archive_id VARCHAR(24) PRIMARY KEY,
    legacy_code VARCHAR(24) NOT NULL,
    title VARCHAR(160) NOT NULL,
    discontinued_year INT NOT NULL,
    old_min_gpa NUMERIC(3, 2) NOT NULL
);

-- 19. RAG Infrastructure: document_chunks (pgvector + native FTS)
CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id VARCHAR(64) PRIMARY KEY,
    doc_id VARCHAR(120) NOT NULL,
    version VARCHAR(24) NOT NULL,
    effective_date DATE NOT NULL,
    grant_id VARCHAR(24),
    dept_code VARCHAR(16),
    year_scope VARCHAR(32),
    page_num INT NOT NULL,
    chunk_type VARCHAR(24) NOT NULL DEFAULT 'prose',
    content TEXT NOT NULL,
    structured_table_json JSONB,
    injection_flagged BOOLEAN NOT NULL DEFAULT FALSE,
    embedding vector(1024),
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(content, ''))) STORED
);

CREATE INDEX IF NOT EXISTS idx_document_chunks_tsv ON document_chunks USING GIN (tsv);
CREATE INDEX IF NOT EXISTS idx_document_chunks_grant ON document_chunks (grant_id);
CREATE INDEX IF NOT EXISTS idx_document_chunks_doc ON document_chunks (doc_id, version);

-- 20. RAG Infrastructure: schema_index
CREATE TABLE IF NOT EXISTS schema_index (
    entry_id VARCHAR(64) PRIMARY KEY,
    table_name VARCHAR(64) NOT NULL,
    column_name VARCHAR(64),
    description TEXT NOT NULL,
    sample_values TEXT NOT NULL,
    metric_view_sql TEXT,
    embedding vector(1024)
);

-- Read-only role for safe SQL branch execution (Layer 2 safety)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'alderwood_readonly') THEN
        CREATE ROLE alderwood_readonly WITH LOGIN PASSWORD 'alderwood_ro_password';
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO alderwood_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO alderwood_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO alderwood_readonly;

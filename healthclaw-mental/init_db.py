"""HealthClaw Mental — schema initialization.

Creates 4 mental-health-specific tables in the shared ERPClaw database.
Requires healthclaw core tables to exist (patient FK references).

ADR-0034 phase 2 bulk-39. Schema declared as metadata and provisioned through
`erpclaw_lib.seam`, which emits dialect-correct DDL, replacing a hand-written
``CREATE TABLE`` block opened with ``sqlite3.connect`` that could not run on
PostgreSQL at all. Conversion rules are the pilot's (`erpclaw-esign`).
"""
import importlib.util
import os
import sys

# Bootstrap the shared lib only when it is not already reachable — an
# unconditional insert at position 0 overrides a caller that deliberately bound a
# different tree (ADR-0034 phase 2 step 2d).
if importlib.util.find_spec("erpclaw_lib") is None:
    sys.path.insert(0, os.path.join(os.path.expanduser(
        os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "lib"))

from erpclaw_lib.seam import (  # noqa: E402
    CheckConstraint, Column, ForeignKey, Index, Integer, MetaData, Table, Text,
    provision, reference_table, text,
)

DB_PATH = os.environ.get("ERPCLAW_DB_PATH", os.path.join(os.path.expanduser(os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "data.sqlite"))

METADATA = MetaData()

# Foundation and healthclaw-core tables this module points at but does not own —
# declared so the foreign keys resolve, never created here.
reference_table("company", METADATA)
reference_table("employee", METADATA)
reference_table("healthclaw_patient", METADATA)
reference_table("healthclaw_encounter", METADATA)

# ---------------------------------------------------------------------------
# 1. healthclaw_therapy_session — individual/couples/family/group sessions
# ---------------------------------------------------------------------------
THERAPY_SESSION = Table(
    "healthclaw_therapy_session", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("encounter_id", Text,
           ForeignKey("healthclaw_encounter.id"), nullable=False),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id"), nullable=False),
    Column("provider_id", Text, ForeignKey("employee.id"), nullable=False),
    Column("session_type", Text, nullable=False),
    Column("modality", Text),
    Column("duration_minutes", Integer),
    Column("session_number", Integer),
    Column("notes", Text),
    Column("status", Text, nullable=False, server_default=text("'completed'")),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "session_type IN ('individual','couples','family','group')",
        name="ck_healthclaw_therapy_session_session_type"),
    CheckConstraint(
        "modality IN ('cbt','dbt','emdr','psychodynamic','supportive','motivational_interviewing','other')",
        name="ck_healthclaw_therapy_session_modality"),
    CheckConstraint(
        "status IN ('scheduled','in_progress','completed','cancelled','no_show')",
        name="ck_healthclaw_therapy_session_status"),
)

Index("idx_therapy_session_company", THERAPY_SESSION.c.company_id)
Index("idx_therapy_session_patient", THERAPY_SESSION.c.patient_id)
Index("idx_therapy_session_provider", THERAPY_SESSION.c.provider_id)
Index("idx_therapy_session_encounter", THERAPY_SESSION.c.encounter_id)

# ---------------------------------------------------------------------------
# 2. healthclaw_assessment — standardized mental health instruments
# ---------------------------------------------------------------------------
ASSESSMENT = Table(
    "healthclaw_assessment", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id"), nullable=False),
    Column("administered_by_id", Text, ForeignKey("employee.id")),
    Column("instrument", Text, nullable=False),
    Column("responses", Text),
    Column("score", Integer),
    Column("severity", Text),
    Column("administered_date", Text, nullable=False),
    Column("notes", Text),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "instrument IN ('PHQ-9','GAD-7','AUDIT','PCL-5','CSSRS','PHQ-2','GAD-2','DAST-10','MDQ','CAGE')",
        name="ck_healthclaw_assessment_instrument"),
)

Index("idx_assessment_company", ASSESSMENT.c.company_id)
Index("idx_assessment_patient", ASSESSMENT.c.patient_id)
Index("idx_assessment_instrument", ASSESSMENT.c.patient_id, ASSESSMENT.c.instrument)

# ---------------------------------------------------------------------------
# 3. healthclaw_treatment_goal — patient treatment goals with tracking
# ---------------------------------------------------------------------------
TREATMENT_GOAL = Table(
    "healthclaw_treatment_goal", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id"), nullable=False),
    Column("provider_id", Text, ForeignKey("employee.id")),
    Column("goal_description", Text, nullable=False),
    Column("target_date", Text),
    Column("baseline_measure", Text),
    Column("current_measure", Text),
    Column("goal_status", Text, nullable=False, server_default=text("'active'")),
    Column("notes", Text),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "goal_status IN ('active','achieved','modified','discontinued')",
        name="ck_healthclaw_treatment_goal_goal_status"),
)

Index("idx_treatment_goal_company", TREATMENT_GOAL.c.company_id)
Index("idx_treatment_goal_patient", TREATMENT_GOAL.c.patient_id)
Index("idx_treatment_goal_status", TREATMENT_GOAL.c.goal_status)

# ---------------------------------------------------------------------------
# 4. healthclaw_group_session — group therapy sessions
# ---------------------------------------------------------------------------
GROUP_SESSION = Table(
    "healthclaw_group_session", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("provider_id", Text, ForeignKey("employee.id"), nullable=False),
    Column("session_date", Text, nullable=False),
    Column("group_name", Text, nullable=False),
    Column("group_type", Text),
    Column("topic", Text),
    Column("max_participants", Integer, server_default=text("12")),
    Column("participant_ids", Text),
    Column("duration_minutes", Integer),
    Column("notes", Text),
    Column("status", Text, nullable=False, server_default=text("'completed'")),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "group_type IN ('process','psychoeducation','support','skills_training')",
        name="ck_healthclaw_group_session_group_type"),
    CheckConstraint(
        "status IN ('scheduled','completed','cancelled')",
        name="ck_healthclaw_group_session_status"),
)

Index("idx_group_session_company", GROUP_SESSION.c.company_id)
Index("idx_group_session_provider", GROUP_SESSION.c.provider_id)
Index("idx_group_session_date", GROUP_SESSION.c.session_date)


def init_mental_schema(db_path: str = DB_PATH) -> dict:
    """Create mental health expansion tables and indexes.

    Same contract as before the ADR-0034 conversion: idempotent, and the returned
    counts are what was ACTUALLY created rather than what was declared.
    """
    result = provision(METADATA, db_path)
    return {
        "database": db_path,
        "tables": result["tables"],
        "indexes": result["indexes"],
    }


if __name__ == "__main__":
    result = init_mental_schema()
    print(f"HealthClaw Mental schema created in {result['database']}", file=sys.stderr)
    print(f"  Tables: {result['tables']}", file=sys.stderr)
    print(f"  Indexes: {result['indexes']}", file=sys.stderr)

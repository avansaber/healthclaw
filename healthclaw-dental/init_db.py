"""HealthClaw Dental — schema initialization.

Creates 4 dental-specific tables in the shared ERPClaw database.
Requires healthclaw core tables to exist (patient FK references).

ADR-0034 phase 2 bulk-39. Schema declared as metadata and provisioned through
`erpclaw_lib.seam`, which emits dialect-correct DDL, replacing a hand-written
``CREATE TABLE`` block opened with ``sqlite3.connect`` that could not run on
PostgreSQL at all. Conversion rules are the pilot's (`erpclaw-esign`); every
billed or estimated amount here — the procedure fee and the three treatment-plan
estimates — stays TEXT, because money is a `Decimal` string on every backend
(ADR-0034 dec. 1).

This module owns only its own 4 tables. `company`, `healthclaw_patient` and
`healthclaw_encounter` belong to erpclaw-setup and healthclaw core; they are
declared reference-only so the foreign keys resolve and are never created here.
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
    CheckConstraint, Column, ForeignKey, Index, MetaData, Table, Text,
    provision, reference_table, text,
)

DB_PATH = os.environ.get("ERPCLAW_DB_PATH", os.path.join(os.path.expanduser(os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "data.sqlite"))

METADATA = MetaData()

# Tables this module points at but does not own — declared so the foreign keys
# resolve, never created here. `healthclaw_patient` and `healthclaw_encounter`
# are healthclaw core's, which is why core must be installed first.
reference_table("company", METADATA)
reference_table("healthclaw_patient", METADATA)
reference_table("healthclaw_encounter", METADATA)

# ---------------------------------------------------------------------------
# 1. healthclaw_tooth_chart — per-tooth condition records
# ---------------------------------------------------------------------------
TOOTH_CHART = Table(
    "healthclaw_tooth_chart", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("patient_id", Text, ForeignKey("healthclaw_patient.id"), nullable=False),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("tooth_number", Text, nullable=False),
    Column("tooth_system", Text, nullable=False, server_default=text("'universal'")),
    Column("surface", Text),
    Column("condition", Text, nullable=False),
    Column("condition_detail", Text),
    Column("noted_date", Text, nullable=False),
    Column("noted_by_id", Text),
    Column("status", Text, nullable=False, server_default=text("'active'")),
    Column("notes", Text),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("tooth_system IN ('universal','palmer','fdi')",
                    name="ck_healthclaw_tooth_chart_tooth_system"),
    CheckConstraint("status IN ('active','resolved','monitoring')",
                    name="ck_healthclaw_tooth_chart_status"),
)

Index("idx_tooth_chart_patient", TOOTH_CHART.c.patient_id)
Index("idx_tooth_chart_company", TOOTH_CHART.c.company_id)
Index("idx_tooth_chart_tooth", TOOTH_CHART.c.patient_id, TOOTH_CHART.c.tooth_number)

# ---------------------------------------------------------------------------
# 2. healthclaw_dental_procedure — CDT-coded dental procedures
# ---------------------------------------------------------------------------
DENTAL_PROCEDURE = Table(
    "healthclaw_dental_procedure", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("encounter_id", Text, ForeignKey("healthclaw_encounter.id"),
           nullable=False),
    Column("patient_id", Text, ForeignKey("healthclaw_patient.id"), nullable=False),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("provider_id", Text, nullable=False),
    Column("cdt_code", Text, nullable=False),
    Column("cdt_description", Text),
    Column("tooth_number", Text),
    Column("surface", Text),
    Column("quadrant", Text),
    Column("procedure_date", Text, nullable=False),
    # Money — TEXT, never numeric (ADR-0034 dec. 1).
    Column("fee", Text, nullable=False, server_default=text("'0.00'")),
    Column("status", Text, nullable=False, server_default=text("'planned'")),
    Column("notes", Text),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    # The trailing `NULL` member and the space before it are the shipped
    # predicate, character for character; a CHECK is compared by body.
    CheckConstraint("quadrant IN ('UR','UL','LR','LL', NULL)",
                    name="ck_healthclaw_dental_procedure_quadrant"),
    CheckConstraint(
        "status IN ('planned','in_progress','completed','cancelled')",
        name="ck_healthclaw_dental_procedure_status"),
)

Index("idx_dental_proc_encounter", DENTAL_PROCEDURE.c.encounter_id)
Index("idx_dental_proc_patient", DENTAL_PROCEDURE.c.patient_id)
Index("idx_dental_proc_company", DENTAL_PROCEDURE.c.company_id)
Index("idx_dental_proc_cdt", DENTAL_PROCEDURE.c.cdt_code)

# ---------------------------------------------------------------------------
# 3. healthclaw_treatment_plan — multi-phase dental treatment plans
# ---------------------------------------------------------------------------
TREATMENT_PLAN = Table(
    "healthclaw_treatment_plan", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("patient_id", Text, ForeignKey("healthclaw_patient.id"), nullable=False),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("provider_id", Text, nullable=False),
    Column("plan_name", Text, nullable=False),
    Column("plan_date", Text, nullable=False),
    Column("phases", Text, nullable=False, server_default=text("'[]'")),
    # Estimated money — TEXT, never numeric (ADR-0034 dec. 1).
    Column("estimated_total", Text, nullable=False, server_default=text("'0.00'")),
    Column("insurance_estimate", Text, nullable=False,
           server_default=text("'0.00'")),
    Column("patient_estimate", Text, nullable=False, server_default=text("'0.00'")),
    Column("status", Text, nullable=False, server_default=text("'proposed'")),
    Column("notes", Text),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "status IN ('proposed','accepted','in_progress','completed','cancelled')",
        name="ck_healthclaw_treatment_plan_status"),
)

Index("idx_treatment_plan_patient", TREATMENT_PLAN.c.patient_id)
Index("idx_treatment_plan_company", TREATMENT_PLAN.c.company_id)
Index("idx_treatment_plan_status", TREATMENT_PLAN.c.status)

# ---------------------------------------------------------------------------
# 4. healthclaw_perio_exam — 6-point periodontal probing data
# ---------------------------------------------------------------------------
PERIO_EXAM = Table(
    "healthclaw_perio_exam", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("patient_id", Text, ForeignKey("healthclaw_patient.id"), nullable=False),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("provider_id", Text, nullable=False),
    Column("exam_date", Text, nullable=False),
    Column("measurements", Text, nullable=False, server_default=text("'{}'")),
    Column("bleeding_sites", Text, nullable=False, server_default=text("'[]'")),
    Column("furcation_data", Text, nullable=False, server_default=text("'{}'")),
    Column("mobility_data", Text, nullable=False, server_default=text("'{}'")),
    Column("recession_data", Text, nullable=False, server_default=text("'{}'")),
    Column("plaque_score", Text),
    Column("notes", Text),
    Column("status", Text, nullable=False, server_default=text("'complete'")),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("status IN ('in_progress','complete')",
                    name="ck_healthclaw_perio_exam_status"),
)

Index("idx_perio_exam_patient", PERIO_EXAM.c.patient_id)
Index("idx_perio_exam_company", PERIO_EXAM.c.company_id)
Index("idx_perio_exam_date", PERIO_EXAM.c.patient_id, PERIO_EXAM.c.exam_date)


def init_dental_schema(db_path: str = DB_PATH) -> dict:
    """Create dental expansion tables and indexes.

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
    result = init_dental_schema()
    print(f"HealthClaw Dental schema created in {result['database']}", file=sys.stderr)
    print(f"  Tables: {result['tables']}", file=sys.stderr)
    print(f"  Indexes: {result['indexes']}", file=sys.stderr)

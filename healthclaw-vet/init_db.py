"""HealthClaw Vet — schema initialization.

Creates 4 vet-specific tables in the shared ERPClaw database.
Requires healthclaw core tables to exist (patient FK references).

ADR-0034 phase 2 bulk-39. Schema declared as metadata and provisioned through
`erpclaw_lib.seam`, which emits dialect-correct DDL, replacing a hand-written
``CREATE TABLE`` block opened with ``sqlite3.connect`` that could not run on
PostgreSQL at all. Conversion rules are the pilot's (`erpclaw-esign`); the
billed/charged columns (`daily_rate`) and the dosing measurements stay TEXT.
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

# Tables this module points at but does not own — the foundation's `company` and
# healthclaw core's `patient` record. Declared so the foreign keys resolve;
# never created here.
reference_table("company", METADATA)
reference_table("healthclaw_patient", METADATA)

# ---------------------------------------------------------------------------
# 1. healthclaw_animal_patient — vet-specific patient extension
# ---------------------------------------------------------------------------
ANIMAL_PATIENT = Table(
    "healthclaw_animal_patient", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("patient_id", Text, ForeignKey("healthclaw_patient.id"), nullable=False),
    Column("species", Text, nullable=False),
    Column("breed", Text),
    Column("color", Text),
    Column("weight_kg", Text),
    Column("microchip_id", Text),
    Column("spay_neuter_status", Text, server_default=text("'unknown'")),
    Column("reproductive_status", Text),
    Column("created_at", Text, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "species IN ('canine','feline','equine','avian','reptile','small_mammal','other')",
        name="ck_healthclaw_animal_patient_species"),
    CheckConstraint(
        "spay_neuter_status IN ('intact','spayed','neutered','unknown')",
        name="ck_healthclaw_animal_patient_spay_neuter_status"),
)

Index("idx_animal_patient_company", ANIMAL_PATIENT.c.company_id)
Index("idx_animal_patient_patient", ANIMAL_PATIENT.c.patient_id)
Index("idx_animal_patient_species", ANIMAL_PATIENT.c.species)
Index("idx_animal_patient_microchip", ANIMAL_PATIENT.c.microchip_id)

# ---------------------------------------------------------------------------
# 2. healthclaw_boarding — boarding/kennel management
# ---------------------------------------------------------------------------
BOARDING = Table(
    "healthclaw_boarding", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("animal_patient_id", Text,
           ForeignKey("healthclaw_animal_patient.id"), nullable=False),
    Column("check_in_date", Text, nullable=False),
    Column("check_out_date", Text),
    Column("kennel_number", Text),
    Column("feeding_instructions", Text),
    Column("medication_schedule", Text),
    Column("special_needs", Text),
    Column("daily_rate", Text),
    Column("status", Text, nullable=False, server_default=text("'checked_in'")),
    Column("notes", Text),
    Column("created_at", Text, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "status IN ('reserved','checked_in','checked_out','cancelled')",
        name="ck_healthclaw_boarding_status"),
)

Index("idx_boarding_company", BOARDING.c.company_id)
Index("idx_boarding_animal", BOARDING.c.animal_patient_id)
Index("idx_boarding_status", BOARDING.c.status)

# ---------------------------------------------------------------------------
# 3. healthclaw_weight_dosing — weight-based medication dosing records
# ---------------------------------------------------------------------------
WEIGHT_DOSING = Table(
    "healthclaw_weight_dosing", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("animal_patient_id", Text,
           ForeignKey("healthclaw_animal_patient.id"), nullable=False),
    Column("weight_date", Text, nullable=False),
    Column("weight_kg", Text, nullable=False),
    Column("medication_name", Text, nullable=False),
    Column("dose_per_kg", Text, nullable=False),
    Column("calculated_dose", Text, nullable=False),
    Column("dose_unit", Text, server_default=text("'mg'")),
    Column("route", Text),
    Column("frequency", Text),
    Column("notes", Text),
    Column("created_at", Text, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "route IN ('oral','injectable','topical','ophthalmic','otic','other')",
        name="ck_healthclaw_weight_dosing_route"),
)

Index("idx_weight_dosing_company", WEIGHT_DOSING.c.company_id)
Index("idx_weight_dosing_animal", WEIGHT_DOSING.c.animal_patient_id)
Index("idx_weight_dosing_medication", WEIGHT_DOSING.c.medication_name)

# ---------------------------------------------------------------------------
# 4. healthclaw_owner_link — animal-to-owner relationship records
# ---------------------------------------------------------------------------
OWNER_LINK = Table(
    "healthclaw_owner_link", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("animal_patient_id", Text,
           ForeignKey("healthclaw_animal_patient.id"), nullable=False),
    Column("owner_name", Text, nullable=False),
    Column("owner_phone", Text),
    Column("owner_email", Text),
    Column("relationship", Text, nullable=False, server_default=text("'owner'")),
    Column("is_primary", Integer, nullable=False, server_default=text("0")),
    Column("financial_responsibility", Integer, nullable=False, server_default=text("1")),
    Column("notes", Text),
    Column("created_at", Text, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "relationship IN ('owner','co_owner','caretaker','breeder','foster')",
        name="ck_healthclaw_owner_link_relationship"),
)

Index("idx_owner_link_company", OWNER_LINK.c.company_id)
Index("idx_owner_link_animal", OWNER_LINK.c.animal_patient_id)


def init_vet_schema(db_path: str = DB_PATH) -> dict:
    """Create vet expansion tables and indexes on whichever backend is configured.

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
    result = init_vet_schema()
    print(f"HealthClaw Vet schema created in {result['database']}", file=sys.stderr)
    print(f"  Tables: {result['tables']}", file=sys.stderr)
    print(f"  Indexes: {result['indexes']}", file=sys.stderr)

#!/usr/bin/env python3
"""HealthClaw schema extension — adds domain tables to the shared database.

AI-native hospital and multi-department healthcare ERP.
59 tables across 13 domains:
  Core (35 tables, 7 domains): patients, appointments, clinical, billing, inventory, lab, referrals
  Advanced (5 tables): medication, dispense log, procedure code, drug interaction, controlled substance log
  Payer management (4 tables, Phase 1 RCM): payer, eligibility check, ERA file, ERA claim detail
  Compliance (4 tables, Phase 2): PHI access log, good faith estimate, quality measure (+ result)
  Phase 8 Clinical Depth (4 tables): med_reconciliation, immunization, provider_credential, payer_enrollment
  Phase 11 Remaining (7 tables): statements, payment plans, BAA, breach, care team, crossover, scheduling rules

Prerequisite: ERPClaw init_db.py must have run first (creates foundation tables).
Run: python3 init_db.py [db_path]

ADR-0034 phase 2 bulk-39. Schema declared as metadata and provisioned through
`erpclaw_lib.seam`, which emits dialect-correct DDL, replacing a hand-written
``CREATE TABLE`` block opened with ``sqlite3.connect`` that could not run on
PostgreSQL at all. This module is the largest in the program and four
sub-verticals (dental, vet, mental, homehealth) key onto `healthclaw_patient` and
`healthclaw_encounter`, so their PostgreSQL legs wait on this one: PostgreSQL
requires a foreign key's target to exist when the referring table is created,
where SQLite does not.

The pre-conversion docstring said "52 tables"; it counted neither the 4 payer
tables nor the 4 compliance tables, and credited Phase 8 with 5 rather than 4.
The installer creates 59 and always did — corrected here rather than carried.
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
    UniqueConstraint, now_default, provision, reference_table, text,
)

DEFAULT_DB_PATH = os.path.join(os.path.expanduser(os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "data.sqlite")
DISPLAY_NAME = "HealthClaw"

# Foundation tables that must exist before HealthClaw can install
REQUIRED_FOUNDATION = [
    "company", "customer", "employee", "item", "account",
    "sales_invoice", "payment_entry", "gl_entry", "naming_series",
]

METADATA = MetaData()

# Foundation tables this module points at but does not own — declared so the
# foreign keys resolve, never created here.
reference_table("company", METADATA)
reference_table("customer", METADATA)
reference_table("employee", METADATA)
reference_table("item", METADATA)
reference_table("sales_invoice", METADATA)
reference_table("payment_entry", METADATA)

# ==========================================================
# DOMAIN 1: PATIENTS (6 tables)
# ==========================================================

# Patient demographics — links to foundation customer (individual)
PATIENT = Table(
    "healthclaw_patient", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("customer_id", Text, ForeignKey("customer.id", ondelete="RESTRICT")),
    Column("first_name", Text, nullable=False),
    Column("last_name", Text, nullable=False),
    Column("full_name", Text, nullable=False),
    Column("date_of_birth", Text, nullable=False),
    Column("gender", Text, nullable=False),
    Column("ssn", Text),                # encrypted at-rest via erpclaw_lib.crypto
    Column("ssn_last4", Text),          # last 4 digits (unencrypted, for display)
    Column("mrn", Text),                # medical record number (auto from naming_series)
    Column("marital_status", Text),
    Column("race", Text),
    Column("ethnicity", Text),
    Column("preferred_language", Text, nullable=False,
           server_default=text("'English'")),
    Column("primary_phone", Text),
    Column("secondary_phone", Text),
    Column("email", Text),
    Column("address_line1", Text),
    Column("address_line2", Text),
    Column("city", Text),
    Column("state", Text),
    Column("zip_code", Text),
    Column("primary_provider_id", Text,
           ForeignKey("employee.id", ondelete="RESTRICT")),
    Column("status", Text, nullable=False, server_default=text("'active'")),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("gender IN ('male','female','other','unknown')",
                    name="ck_healthclaw_patient_gender"),
    CheckConstraint(
        "marital_status IN ('single','married','divorced','widowed',"
        "'separated','unknown')",
        name="ck_healthclaw_patient_marital_status"),
    CheckConstraint(
        "ethnicity IN ('hispanic_latino','not_hispanic_latino','unknown')",
        name="ck_healthclaw_patient_ethnicity"),
    CheckConstraint("status IN ('active','inactive','deceased')",
                    name="ck_healthclaw_patient_status"),
)

Index("idx_hc_patient_company", PATIENT.c.company_id)
Index("idx_hc_patient_customer", PATIENT.c.customer_id)
Index("idx_hc_patient_provider", PATIENT.c.primary_provider_id)
Index("idx_hc_patient_status", PATIENT.c.status)
Index("idx_hc_patient_dob", PATIENT.c.date_of_birth)
Index("idx_hc_patient_name", PATIENT.c.last_name, PATIENT.c.first_name)

# Patient insurance coverage
PATIENT_INSURANCE = Table(
    "healthclaw_patient_insurance", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id", ondelete="RESTRICT"),
           nullable=False),
    Column("insurance_type", Text, nullable=False),
    Column("payer_name", Text, nullable=False),
    Column("payer_id", Text),           # payer identifier / EDI ID
    Column("plan_name", Text),
    Column("plan_type", Text),
    Column("group_number", Text),
    Column("member_id", Text, nullable=False),
    Column("subscriber_name", Text),
    Column("subscriber_dob", Text),
    Column("subscriber_relationship", Text, nullable=False,
           server_default=text("'self'")),
    Column("copay_amount", Text, nullable=False, server_default=text("'0'")),
    Column("deductible", Text, nullable=False, server_default=text("'0'")),
    Column("deductible_met", Text, nullable=False, server_default=text("'0'")),
    Column("out_of_pocket_max", Text, nullable=False, server_default=text("'0'")),
    Column("effective_date", Text, nullable=False),
    Column("termination_date", Text),
    Column("preauth_required", Integer, nullable=False, server_default=text("0")),
    Column("status", Text, nullable=False, server_default=text("'active'")),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("insurance_type IN ('primary','secondary','tertiary')",
                    name="ck_healthclaw_patient_insurance_insurance_type"),
    CheckConstraint(
        "plan_type IN ('hmo','ppo','epo','pos','hdhp','medicare','medicaid',"
        "'tricare','workers_comp','self_pay','other')",
        name="ck_healthclaw_patient_insurance_plan_type"),
    CheckConstraint(
        "subscriber_relationship IN ('self','spouse','child','other')",
        name="ck_healthclaw_patient_insurance_subscriber_relationship"),
    CheckConstraint("preauth_required IN (0,1)",
                    name="ck_healthclaw_patient_insurance_preauth_required"),
    CheckConstraint(
        "status IN ('active','inactive','expired','terminated')",
        name="ck_healthclaw_patient_insurance_status"),
)

Index("idx_hc_ins_patient", PATIENT_INSURANCE.c.patient_id)
Index("idx_hc_ins_type", PATIENT_INSURANCE.c.insurance_type)
Index("idx_hc_ins_status", PATIENT_INSURANCE.c.status)

# Patient allergies
ALLERGY = Table(
    "healthclaw_allergy", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id", ondelete="RESTRICT"),
           nullable=False),
    Column("allergen", Text, nullable=False),
    Column("allergen_type", Text, nullable=False),
    Column("reaction", Text),
    Column("severity", Text, nullable=False, server_default=text("'moderate'")),
    Column("onset_date", Text),
    Column("status", Text, nullable=False, server_default=text("'active'")),
    Column("noted_by_id", Text, ForeignKey("employee.id", ondelete="RESTRICT")),
    Column("notes", Text),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "allergen_type IN ('drug','food','environmental','other')",
        name="ck_healthclaw_allergy_allergen_type"),
    CheckConstraint(
        "severity IN ('mild','moderate','severe','life_threatening')",
        name="ck_healthclaw_allergy_severity"),
    CheckConstraint("status IN ('active','inactive','resolved')",
                    name="ck_healthclaw_allergy_status"),
)

Index("idx_hc_allergy_patient", ALLERGY.c.patient_id)
Index("idx_hc_allergy_status", ALLERGY.c.status)

# Patient medical history
MEDICAL_HISTORY = Table(
    "healthclaw_medical_history", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id", ondelete="RESTRICT"),
           nullable=False),
    Column("condition", Text, nullable=False),
    Column("icd10_code", Text),         # ICD-10 code (text, no lookup table)
    Column("diagnosis_date", Text),
    Column("resolution_date", Text),
    Column("status", Text, nullable=False, server_default=text("'active'")),
    Column("notes", Text),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("status IN ('active','resolved','chronic')",
                    name="ck_healthclaw_medical_history_status"),
)

Index("idx_hc_medhist_patient", MEDICAL_HISTORY.c.patient_id)
Index("idx_hc_medhist_status", MEDICAL_HISTORY.c.status)

# Patient emergency/next-of-kin contacts
PATIENT_CONTACT = Table(
    "healthclaw_patient_contact", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id", ondelete="RESTRICT"),
           nullable=False),
    Column("contact_type", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("relationship", Text),
    Column("phone", Text),
    Column("email", Text),
    Column("address", Text),
    Column("is_primary", Integer, nullable=False, server_default=text("0")),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "contact_type IN ('emergency','next_of_kin','guardian',"
        "'power_of_attorney','other')",
        name="ck_healthclaw_patient_contact_contact_type"),
    CheckConstraint("is_primary IN (0,1)",
                    name="ck_healthclaw_patient_contact_is_primary"),
)

Index("idx_hc_pcontact_patient", PATIENT_CONTACT.c.patient_id)

# HIPAA / treatment consent tracking
CONSENT = Table(
    "healthclaw_consent", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id", ondelete="RESTRICT"),
           nullable=False),
    Column("consent_type", Text, nullable=False),
    Column("description", Text),
    Column("granted_date", Text, nullable=False),
    Column("expiration_date", Text),
    Column("revoked_date", Text),
    Column("status", Text, nullable=False, server_default=text("'active'")),
    Column("witness_name", Text),
    Column("obtained_by_id", Text,
           ForeignKey("employee.id", ondelete="RESTRICT")),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    # The shipped DDL wraps this list, which leaves a space after `IN (` and at
    # the wrap point. The predicate is compared character for character.
    CheckConstraint(
        "consent_type IN ( 'hipaa_privacy','treatment','surgery','anesthesia',"
        " 'research','telehealth','photo_video','release_of_info','other' )",
        name="ck_healthclaw_consent_consent_type"),
    CheckConstraint("status IN ('active','expired','revoked')",
                    name="ck_healthclaw_consent_status"),
)

Index("idx_hc_consent_patient", CONSENT.c.patient_id)
Index("idx_hc_consent_type", CONSENT.c.consent_type)
Index("idx_hc_consent_status", CONSENT.c.status)

# ==========================================================
# DOMAIN 2: APPOINTMENTS (5 tables)
# ==========================================================

# Provider weekly availability template
PROVIDER_SCHEDULE = Table(
    "healthclaw_provider_schedule", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("provider_id", Text,
           ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
    Column("day_of_week", Integer, nullable=False),   # 0=Mon, 6=Sun
    Column("start_time", Text, nullable=False),       # HH:MM (24h)
    Column("end_time", Text, nullable=False),         # HH:MM (24h)
    Column("slot_duration", Integer, nullable=False, server_default=text("30")),
    Column("location", Text),           # room, office, clinic name
    Column("status", Text, nullable=False, server_default=text("'active'")),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("day_of_week BETWEEN 0 AND 6",
                    name="ck_healthclaw_provider_schedule_day_of_week"),
    CheckConstraint("status IN ('active','inactive')",
                    name="ck_healthclaw_provider_schedule_status"),
)

Index("idx_hc_provsched_provider", PROVIDER_SCHEDULE.c.provider_id)
Index("idx_hc_provsched_day", PROVIDER_SCHEDULE.c.day_of_week)

# Schedule block (vacation, meeting, override to block slots)
SCHEDULE_BLOCK = Table(
    "healthclaw_schedule_block", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("provider_id", Text,
           ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
    Column("block_date", Text, nullable=False),
    Column("start_time", Text),         # NULL = all day
    Column("end_time", Text),
    Column("reason", Text, nullable=False),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "reason IN ('vacation','meeting','personal','maintenance','holiday',"
        "'other')",
        name="ck_healthclaw_schedule_block_reason"),
)

Index("idx_hc_schedblock_provider", SCHEDULE_BLOCK.c.provider_id)
Index("idx_hc_schedblock_date", SCHEDULE_BLOCK.c.block_date)

# Appointments
APPOINTMENT = Table(
    "healthclaw_appointment", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id", ondelete="RESTRICT"),
           nullable=False),
    Column("provider_id", Text,
           ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
    Column("appointment_date", Text, nullable=False),
    Column("start_time", Text, nullable=False),        # HH:MM
    Column("end_time", Text, nullable=False),          # HH:MM
    Column("duration_minutes", Integer, nullable=False,
           server_default=text("30")),
    Column("appointment_type", Text, nullable=False,
           server_default=text("'follow_up'")),
    Column("chief_complaint", Text),
    Column("location", Text),
    Column("status", Text, nullable=False, server_default=text("'scheduled'")),
    Column("cancellation_reason", Text),
    Column("check_in_time", Text),
    Column("check_out_time", Text),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "appointment_type IN ( 'new_patient','follow_up','urgent','walk_in',"
        " 'telehealth','procedure','physical_exam','consultation' )",
        name="ck_healthclaw_appointment_appointment_type"),
    CheckConstraint(
        "status IN ('scheduled','confirmed','checked_in','in_progress',"
        " 'completed','cancelled','no_show','rescheduled')",
        name="ck_healthclaw_appointment_status"),
)

Index("idx_hc_appt_company", APPOINTMENT.c.company_id)
Index("idx_hc_appt_patient", APPOINTMENT.c.patient_id)
Index("idx_hc_appt_provider", APPOINTMENT.c.provider_id)
Index("idx_hc_appt_date", APPOINTMENT.c.appointment_date)
Index("idx_hc_appt_status", APPOINTMENT.c.status)
Index("idx_hc_appt_type", APPOINTMENT.c.appointment_type)

# Appointment reminders
APPOINTMENT_REMINDER = Table(
    "healthclaw_appointment_reminder", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("appointment_id", Text,
           ForeignKey("healthclaw_appointment.id", ondelete="RESTRICT"),
           nullable=False),
    Column("reminder_type", Text, nullable=False),
    Column("scheduled_at", Text, nullable=False),
    Column("sent_at", Text),
    Column("status", Text, nullable=False, server_default=text("'pending'")),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("reminder_type IN ('sms','email','phone','in_app')",
                    name="ck_healthclaw_appointment_reminder_reminder_type"),
    CheckConstraint("status IN ('pending','sent','failed','cancelled')",
                    name="ck_healthclaw_appointment_reminder_status"),
)

Index("idx_hc_reminder_appt", APPOINTMENT_REMINDER.c.appointment_id)
Index("idx_hc_reminder_status", APPOINTMENT_REMINDER.c.status)

# Waitlist for appointment slots
WAITLIST = Table(
    "healthclaw_waitlist", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id", ondelete="RESTRICT"),
           nullable=False),
    Column("provider_id", Text, ForeignKey("employee.id", ondelete="RESTRICT")),
    Column("preferred_date_start", Text),
    Column("preferred_date_end", Text),
    Column("preferred_time_start", Text),
    Column("preferred_time_end", Text),
    # No CHECK here, unlike healthclaw_appointment.appointment_type. Preserved.
    Column("appointment_type", Text, nullable=False,
           server_default=text("'follow_up'")),
    Column("priority", Text, nullable=False, server_default=text("'normal'")),
    Column("status", Text, nullable=False, server_default=text("'waiting'")),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("priority IN ('low','normal','high','urgent')",
                    name="ck_healthclaw_waitlist_priority"),
    CheckConstraint(
        "status IN ('waiting','offered','accepted','expired','cancelled')",
        name="ck_healthclaw_waitlist_status"),
)

Index("idx_hc_waitlist_patient", WAITLIST.c.patient_id)
Index("idx_hc_waitlist_provider", WAITLIST.c.provider_id)
Index("idx_hc_waitlist_status", WAITLIST.c.status)
Index("idx_hc_waitlist_priority", WAITLIST.c.priority)

# ==========================================================
# DOMAIN 3: CLINICAL (7 tables)
# ==========================================================

# Encounter — clinical visit record (hub for all clinical data)
ENCOUNTER = Table(
    "healthclaw_encounter", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id", ondelete="RESTRICT"),
           nullable=False),
    Column("appointment_id", Text,
           ForeignKey("healthclaw_appointment.id", ondelete="RESTRICT")),
    Column("provider_id", Text,
           ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
    Column("encounter_date", Text, nullable=False),
    Column("encounter_type", Text, nullable=False,
           server_default=text("'outpatient'")),
    Column("chief_complaint", Text),
    Column("department", Text),
    Column("room", Text),
    Column("admission_date", Text),
    Column("discharge_date", Text),
    Column("discharge_disposition", Text),
    Column("status", Text, nullable=False, server_default=text("'open'")),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "encounter_type IN ( 'outpatient','inpatient','emergency','observation',"
        " 'telehealth','home_visit' )",
        name="ck_healthclaw_encounter_encounter_type"),
    CheckConstraint("status IN ('open','in_progress','completed','cancelled')",
                    name="ck_healthclaw_encounter_status"),
)

Index("idx_hc_encounter_company", ENCOUNTER.c.company_id)
Index("idx_hc_encounter_patient", ENCOUNTER.c.patient_id)
Index("idx_hc_encounter_appt", ENCOUNTER.c.appointment_id)
Index("idx_hc_encounter_provider", ENCOUNTER.c.provider_id)
Index("idx_hc_encounter_date", ENCOUNTER.c.encounter_date)
Index("idx_hc_encounter_status", ENCOUNTER.c.status)
Index("idx_hc_encounter_type", ENCOUNTER.c.encounter_type)

# Vital signs recording
VITALS = Table(
    "healthclaw_vitals", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("encounter_id", Text,
           ForeignKey("healthclaw_encounter.id", ondelete="RESTRICT"),
           nullable=False),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id", ondelete="RESTRICT"),
           nullable=False),
    Column("recorded_by_id", Text,
           ForeignKey("employee.id", ondelete="RESTRICT")),
    Column("recorded_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("temperature", Text),        # Fahrenheit
    Column("temperature_site", Text),
    Column("heart_rate", Integer),      # bpm
    Column("respiratory_rate", Integer),  # breaths/min
    Column("blood_pressure_systolic", Integer),
    Column("blood_pressure_diastolic", Integer),
    Column("oxygen_saturation", Text),  # percentage
    Column("weight", Text),             # lbs
    Column("height", Text),             # inches
    Column("bmi", Text),                # calculated
    Column("pain_level", Integer),
    Column("notes", Text),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "temperature_site IN ('oral','tympanic','axillary','rectal','temporal')",
        name="ck_healthclaw_vitals_temperature_site"),
    CheckConstraint("pain_level BETWEEN 0 AND 10",
                    name="ck_healthclaw_vitals_pain_level"),
)

Index("idx_hc_vitals_encounter", VITALS.c.encounter_id)
Index("idx_hc_vitals_patient", VITALS.c.patient_id)

# Diagnosis (ICD-10 codes stored as text)
DIAGNOSIS = Table(
    "healthclaw_diagnosis", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("encounter_id", Text,
           ForeignKey("healthclaw_encounter.id", ondelete="RESTRICT"),
           nullable=False),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id", ondelete="RESTRICT"),
           nullable=False),
    Column("icd10_code", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column("diagnosis_type", Text, nullable=False,
           server_default=text("'primary'")),
    Column("status", Text, nullable=False, server_default=text("'active'")),
    Column("onset_date", Text),
    Column("diagnosed_by_id", Text,
           ForeignKey("employee.id", ondelete="RESTRICT")),
    Column("notes", Text),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "diagnosis_type IN ('primary','secondary','admitting','discharge',"
        "'rule_out')",
        name="ck_healthclaw_diagnosis_diagnosis_type"),
    CheckConstraint("status IN ('active','resolved','chronic','rule_out')",
                    name="ck_healthclaw_diagnosis_status"),
)

Index("idx_hc_dx_encounter", DIAGNOSIS.c.encounter_id)
Index("idx_hc_dx_patient", DIAGNOSIS.c.patient_id)
Index("idx_hc_dx_icd10", DIAGNOSIS.c.icd10_code)
Index("idx_hc_dx_type", DIAGNOSIS.c.diagnosis_type)

# Prescription (medication orders)
# Merged from hcadv_prescription: medication_id, rx_number, quantity_prescribed,
#   refills_authorized, refills_used, dea_number, rx_status, prescribed_date, expiry_date
PRESCRIPTION = Table(
    "healthclaw_prescription", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("encounter_id", Text,
           ForeignKey("healthclaw_encounter.id", ondelete="RESTRICT")),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id", ondelete="RESTRICT"),
           nullable=False),
    Column("prescriber_id", Text,
           ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
    Column("medication_name", Text),
    # from hcadv: links to healthclaw_medication, but carries no foreign key.
    Column("medication_id", Text),
    Column("ndc_code", Text),           # National Drug Code
    Column("rx_number", Text),          # from hcadv: prescription number
    Column("dosage", Text, nullable=False),     # e.g., "500mg"
    Column("frequency", Text, nullable=False),  # e.g., "BID", "Q8H", "PRN"
    Column("route", Text, nullable=False, server_default=text("'oral'")),
    Column("quantity", Text, nullable=False, server_default=text("'0'")),
    Column("quantity_prescribed", Integer, nullable=False,
           server_default=text("0")),   # from hcadv
    Column("refills", Integer, nullable=False, server_default=text("0")),
    Column("refills_authorized", Integer, nullable=False,
           server_default=text("0")),   # from hcadv
    Column("refills_used", Integer, nullable=False,
           server_default=text("0")),   # from hcadv
    Column("daw", Integer, nullable=False, server_default=text("0")),  # dispense as written
    Column("dea_number", Text),         # from hcadv: DEA number for controlled substances
    Column("start_date", Text),
    Column("end_date", Text),
    Column("prescribed_date", Text),    # from hcadv: date prescribed
    Column("expiry_date", Text),        # from hcadv: prescription expiry
    Column("diagnosis_id", Text,
           ForeignKey("healthclaw_diagnosis.id", ondelete="RESTRICT")),
    Column("controlled_schedule", Text),
    Column("pharmacy_notes", Text),
    Column("status", Text, nullable=False, server_default=text("'active'")),
    Column("rx_status", Text, server_default=text("'active'")),
    Column("discontinued_reason", Text),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "route IN ('oral','iv','im','subq','topical','inhaled',"
        " 'rectal','ophthalmic','otic','nasal','sublingual','transdermal','other')",
        name="ck_healthclaw_prescription_route"),
    CheckConstraint("daw IN (0,1)", name="ck_healthclaw_prescription_daw"),
    CheckConstraint("controlled_schedule IN ('II','III','IV','V')",
                    name="ck_healthclaw_prescription_controlled_schedule"),
    CheckConstraint(
        "status IN ('active','completed','discontinued','cancelled','on_hold',"
        " 'filled','partially_filled','expired')",
        name="ck_healthclaw_prescription_status"),
    CheckConstraint(
        "rx_status IN ('active','filled','partially_filled','expired',"
        "'cancelled')",
        name="ck_healthclaw_prescription_rx_status"),
)

Index("idx_hc_rx_encounter", PRESCRIPTION.c.encounter_id)
Index("idx_hc_rx_patient", PRESCRIPTION.c.patient_id)
Index("idx_hc_rx_prescriber", PRESCRIPTION.c.prescriber_id)
Index("idx_hc_rx_status", PRESCRIPTION.c.status)

# Procedures performed (CPT codes stored as text)
PROCEDURE = Table(
    "healthclaw_procedure", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("encounter_id", Text,
           ForeignKey("healthclaw_encounter.id", ondelete="RESTRICT"),
           nullable=False),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id", ondelete="RESTRICT"),
           nullable=False),
    Column("provider_id", Text,
           ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
    Column("cpt_code", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column("procedure_date", Text, nullable=False),
    Column("start_time", Text),
    Column("end_time", Text),
    Column("modifiers", Text),          # CPT modifiers (e.g., "25,59")
    Column("diagnosis_ids", Text),      # JSON array of diagnosis IDs
    Column("anesthesia_type", Text),
    Column("body_site", Text),
    Column("laterality", Text),
    Column("status", Text, nullable=False, server_default=text("'completed'")),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "anesthesia_type IN ('none','local','regional','general','sedation')",
        name="ck_healthclaw_procedure_anesthesia_type"),
    CheckConstraint(
        "laterality IN ('left','right','bilateral','not_applicable')",
        name="ck_healthclaw_procedure_laterality"),
    CheckConstraint(
        "status IN ('planned','in_progress','completed','cancelled')",
        name="ck_healthclaw_procedure_status"),
)

Index("idx_hc_proc_encounter", PROCEDURE.c.encounter_id)
Index("idx_hc_proc_patient", PROCEDURE.c.patient_id)
Index("idx_hc_proc_provider", PROCEDURE.c.provider_id)
Index("idx_hc_proc_cpt", PROCEDURE.c.cpt_code)
Index("idx_hc_proc_date", PROCEDURE.c.procedure_date)

# SOAP / clinical notes
CLINICAL_NOTE = Table(
    "healthclaw_clinical_note", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("encounter_id", Text,
           ForeignKey("healthclaw_encounter.id", ondelete="RESTRICT"),
           nullable=False),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id", ondelete="RESTRICT"),
           nullable=False),
    Column("author_id", Text,
           ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
    Column("note_type", Text, nullable=False, server_default=text("'progress'")),
    Column("subjective", Text),         # SOAP: S
    Column("objective", Text),          # SOAP: O
    Column("assessment", Text),         # SOAP: A
    Column("plan", Text),               # SOAP: P
    Column("body", Text),               # free-text for non-SOAP notes
    Column("addendum", Text),
    Column("signed_at", Text),
    Column("cosigner_id", Text, ForeignKey("employee.id", ondelete="RESTRICT")),
    Column("cosigned_at", Text),
    Column("status", Text, nullable=False, server_default=text("'draft'")),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "note_type IN ('progress','soap','hpi','consultation',"
        " 'discharge','operative','procedure','nursing','other')",
        name="ck_healthclaw_clinical_note_note_type"),
    CheckConstraint(
        "status IN ('draft','signed','cosigned','amended','addended')",
        name="ck_healthclaw_clinical_note_status"),
)

Index("idx_hc_note_encounter", CLINICAL_NOTE.c.encounter_id)
Index("idx_hc_note_patient", CLINICAL_NOTE.c.patient_id)
Index("idx_hc_note_author", CLINICAL_NOTE.c.author_id)
Index("idx_hc_note_type", CLINICAL_NOTE.c.note_type)

# Clinical orders (labs, imaging, referrals — generic order hub)
ORDER = Table(
    "healthclaw_order", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("encounter_id", Text,
           ForeignKey("healthclaw_encounter.id", ondelete="RESTRICT"),
           nullable=False),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id", ondelete="RESTRICT"),
           nullable=False),
    Column("ordering_provider_id", Text,
           ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
    Column("order_type", Text, nullable=False),
    Column("order_date", Text, nullable=False),
    Column("priority", Text, nullable=False, server_default=text("'routine'")),
    Column("clinical_indication", Text),
    Column("diagnosis_id", Text,
           ForeignKey("healthclaw_diagnosis.id", ondelete="RESTRICT")),
    Column("status", Text, nullable=False, server_default=text("'pending'")),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "order_type IN ('lab','imaging','referral','procedure','other')",
        name="ck_healthclaw_order_order_type"),
    CheckConstraint("priority IN ('stat','urgent','routine','elective')",
                    name="ck_healthclaw_order_priority"),
    CheckConstraint("status IN ('pending','in_progress','completed','cancelled')",
                    name="ck_healthclaw_order_status"),
)

Index("idx_hc_order_encounter", ORDER.c.encounter_id)
Index("idx_hc_order_patient", ORDER.c.patient_id)
Index("idx_hc_order_provider", ORDER.c.ordering_provider_id)
Index("idx_hc_order_type", ORDER.c.order_type)
Index("idx_hc_order_status", ORDER.c.status)
Index("idx_hc_order_date", ORDER.c.order_date)

# ==========================================================
# DOMAIN 4: BILLING (6 tables)
# ==========================================================

# Fee schedule header (e.g., "Medicare Fee Schedule 2026")
FEE_SCHEDULE = Table(
    "healthclaw_fee_schedule", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("name", Text, nullable=False),
    Column("description", Text),
    Column("payer_type", Text),
    Column("effective_date", Text, nullable=False),
    Column("expiration_date", Text),
    Column("status", Text, nullable=False, server_default=text("'active'")),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "payer_type IN ('commercial','medicare','medicaid','self_pay',"
        "'workers_comp','other')",
        name="ck_healthclaw_fee_schedule_payer_type"),
    CheckConstraint("status IN ('active','inactive','expired')",
                    name="ck_healthclaw_fee_schedule_status"),
)

Index("idx_hc_feesched_company", FEE_SCHEDULE.c.company_id)
Index("idx_hc_feesched_status", FEE_SCHEDULE.c.status)

# Fee schedule line items (CPT code → price)
FEE_SCHEDULE_ITEM = Table(
    "healthclaw_fee_schedule_item", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("fee_schedule_id", Text,
           ForeignKey("healthclaw_fee_schedule.id", ondelete="RESTRICT"),
           nullable=False),
    Column("cpt_code", Text, nullable=False),
    Column("description", Text),
    Column("standard_charge", Text, nullable=False, server_default=text("'0'")),
    # payer's max allowable
    Column("allowed_amount", Text, nullable=False, server_default=text("'0'")),
    Column("unit_count", Integer, nullable=False, server_default=text("1")),
    Column("modifier", Text),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    # Idempotency key — one price per (schedule, CPT, modifier).
    UniqueConstraint("fee_schedule_id", "cpt_code", "modifier"),
)

Index("idx_hc_fsitem_schedule", FEE_SCHEDULE_ITEM.c.fee_schedule_id)
Index("idx_hc_fsitem_cpt", FEE_SCHEDULE_ITEM.c.cpt_code)

# Individual charges (line items billed for services)
# Merged from hcadv_charge: procedure_code_id, icd10_codes, description, unit_fee, total_fee, quantity
CHARGE = Table(
    "healthclaw_charge", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("encounter_id", Text,
           ForeignKey("healthclaw_encounter.id", ondelete="RESTRICT")),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id", ondelete="RESTRICT"),
           nullable=False),
    Column("procedure_id", Text,
           ForeignKey("healthclaw_procedure.id", ondelete="RESTRICT")),
    # from hcadv: links to healthclaw_procedure_code, but carries no foreign key.
    Column("procedure_code_id", Text),
    Column("cpt_code", Text),
    Column("modifiers", Text),
    Column("diagnosis_ids", Text),      # JSON array of ICD-10 pointers
    Column("icd10_codes", Text, server_default=text("'[]'")),  # from hcadv
    Column("description", Text),        # from hcadv: charge description
    Column("units", Integer, nullable=False, server_default=text("1")),
    # from hcadv: synonym for units
    Column("quantity", Integer, nullable=False, server_default=text("1")),
    Column("charge_amount", Text, nullable=False, server_default=text("'0'")),
    # from hcadv: per-unit fee
    Column("unit_fee", Text, nullable=False, server_default=text("'0.00'")),
    # from hcadv: quantity * unit_fee
    Column("total_fee", Text, nullable=False, server_default=text("'0.00'")),
    Column("allowed_amount", Text, nullable=False, server_default=text("'0'")),
    Column("fee_schedule_id", Text,
           ForeignKey("healthclaw_fee_schedule.id", ondelete="RESTRICT")),
    Column("service_date", Text, nullable=False),
    Column("provider_id", Text,
           ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
    # CMS POS code (11=Office)
    Column("place_of_service", Text, nullable=False, server_default=text("'11'")),
    Column("charge_status", Text, nullable=False,
           server_default=text("'unbilled'")),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "charge_status IN ('unbilled','billed','paid','adjusted','void')",
        name="ck_healthclaw_charge_charge_status"),
)

Index("idx_hc_charge_company", CHARGE.c.company_id)
Index("idx_hc_charge_encounter", CHARGE.c.encounter_id)
Index("idx_hc_charge_patient", CHARGE.c.patient_id)
Index("idx_hc_charge_status", CHARGE.c.charge_status)
Index("idx_hc_charge_date", CHARGE.c.service_date)
Index("idx_hc_charge_cpt", CHARGE.c.cpt_code)

# Insurance claim header
# Merged from hcadv_claim: payer_name, payer_id_number, policy_number, group_number,
#   claim_number, charge_ids, total_charged, total_adjustment, submitted_date, response_date
CLAIM = Table(
    "healthclaw_claim", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id", ondelete="RESTRICT"),
           nullable=False),
    Column("insurance_id", Text,
           ForeignKey("healthclaw_patient_insurance.id", ondelete="RESTRICT")),
    Column("encounter_id", Text,
           ForeignKey("healthclaw_encounter.id", ondelete="RESTRICT")),
    Column("payer_name", Text),         # from hcadv: payer name (when no insurance_id)
    Column("payer_id_number", Text),    # from hcadv: payer EDI identifier
    Column("policy_number", Text),      # from hcadv: insurance policy number
    Column("group_number", Text),       # from hcadv: insurance group number
    Column("claim_number", Text),       # from hcadv: external claim tracking number
    Column("claim_date", Text, nullable=False),
    # from hcadv: JSON array of charge IDs
    Column("charge_ids", Text, nullable=False, server_default=text("'[]'")),
    Column("total_charge", Text, nullable=False, server_default=text("'0'")),
    # from hcadv: alias for total_charge, and it spells its default differently
    Column("total_charged", Text, nullable=False,
           server_default=text("'0.00'")),
    Column("total_allowed", Text, nullable=False, server_default=text("'0'")),
    Column("total_paid", Text, nullable=False, server_default=text("'0'")),
    # from hcadv: total adjustments
    Column("total_adjustment", Text, nullable=False,
           server_default=text("'0.00'")),
    Column("patient_responsibility", Text, nullable=False,
           server_default=text("'0'")),
    Column("adjustment_amount", Text, nullable=False,
           server_default=text("'0'")),
    Column("billing_provider_id", Text,
           ForeignKey("employee.id", ondelete="RESTRICT")),
    Column("rendering_provider_id", Text,
           ForeignKey("employee.id", ondelete="RESTRICT")),
    Column("place_of_service", Text, nullable=False, server_default=text("'11'")),
    Column("claim_type", Text, nullable=False,
           server_default=text("'professional'")),
    Column("filing_indicator", Text),   # e.g., "CI" for commercial insurance
    Column("prior_auth_id", Text,
           ForeignKey("healthclaw_prior_auth.id", ondelete="RESTRICT")),
    Column("sales_invoice_id", Text,
           ForeignKey("sales_invoice.id", ondelete="RESTRICT")),
    Column("claim_status", Text, nullable=False, server_default=text("'draft'")),
    Column("submitted_date", Text),     # from hcadv: date claim was submitted
    Column("response_date", Text),      # from hcadv: date payer responded
    Column("denial_reason", Text),
    Column("denial_category", Text),
    Column("denial_code", Text),
    Column("denial_date", Text),
    Column("appeal_deadline", Text),
    Column("appeal_submitted_date", Text),
    Column("appeal_method", Text),
    Column("appeal_reference", Text),
    Column("appeal_outcome", Text),
    Column("appeal_resolved_date", Text),
    Column("appeal_amount_recovered", Text),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "claim_type IN ('professional','institutional','dental')",
        name="ck_healthclaw_claim_claim_type"),
    CheckConstraint(
        "claim_status IN ('draft','submitted','accepted','denied',"
        " 'partially_paid','paid','appealed','void')",
        name="ck_healthclaw_claim_claim_status"),
    CheckConstraint("denial_category IN ('CO','PR','OA','PI')",
                    name="ck_healthclaw_claim_denial_category"),
    CheckConstraint("appeal_method IN ('written','phone','online')",
                    name="ck_healthclaw_claim_appeal_method"),
    CheckConstraint(
        "appeal_outcome IN ('pending','overturned','upheld','partial')",
        name="ck_healthclaw_claim_appeal_outcome"),
)

Index("idx_hc_claim_company", CLAIM.c.company_id)
Index("idx_hc_claim_patient", CLAIM.c.patient_id)
Index("idx_hc_claim_insurance", CLAIM.c.insurance_id)
Index("idx_hc_claim_encounter", CLAIM.c.encounter_id)
Index("idx_hc_claim_status", CLAIM.c.claim_status)
Index("idx_hc_claim_payer", CLAIM.c.payer_name)
Index("idx_hc_claim_number", CLAIM.c.claim_number)
Index("idx_hc_claim_date", CLAIM.c.claim_date)
Index("idx_hc_claim_invoice", CLAIM.c.sales_invoice_id)

# Claim line items
CLAIM_LINE = Table(
    "healthclaw_claim_line", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("claim_id", Text,
           ForeignKey("healthclaw_claim.id", ondelete="RESTRICT"),
           nullable=False),
    Column("charge_id", Text,
           ForeignKey("healthclaw_charge.id", ondelete="RESTRICT"),
           nullable=False),
    Column("line_number", Integer, nullable=False),
    Column("cpt_code", Text, nullable=False),
    Column("modifiers", Text),
    # e.g., "1,2" referencing claim-level Dx list
    Column("diagnosis_pointers", Text),
    Column("units", Integer, nullable=False, server_default=text("1")),
    Column("charge_amount", Text, nullable=False, server_default=text("'0'")),
    Column("allowed_amount", Text, nullable=False, server_default=text("'0'")),
    Column("paid_amount", Text, nullable=False, server_default=text("'0'")),
    Column("adjustment_amount", Text, nullable=False, server_default=text("'0'")),
    Column("patient_amount", Text, nullable=False, server_default=text("'0'")),
    Column("denial_reason", Text),
    Column("remark_codes", Text),       # ANSI remark codes
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
)

Index("idx_hc_claimline_claim", CLAIM_LINE.c.claim_id)
Index("idx_hc_claimline_charge", CLAIM_LINE.c.charge_id)

# Insurance / patient payment posting
# Merged from hcadv_payment_posting: charge_id, allowed_amount, paid_amount, adjustment, patient_responsibility
PAYMENT_POSTING = Table(
    "healthclaw_payment_posting", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("claim_id", Text,
           ForeignKey("healthclaw_claim.id", ondelete="RESTRICT")),
    Column("charge_id", Text,
           ForeignKey("healthclaw_charge.id", ondelete="RESTRICT")),  # from hcadv
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id", ondelete="RESTRICT"),
           nullable=False),
    Column("posting_type", Text),
    Column("posting_date", Text, nullable=False),
    Column("amount", Text, nullable=False, server_default=text("'0'")),
    # from hcadv — these four spell their default '0.00' where `amount` says '0'
    Column("allowed_amount", Text, nullable=False, server_default=text("'0.00'")),
    Column("paid_amount", Text, nullable=False, server_default=text("'0.00'")),
    Column("adjustment", Text, nullable=False, server_default=text("'0.00'")),
    Column("patient_responsibility", Text, nullable=False,
           server_default=text("'0.00'")),
    Column("check_number", Text),
    Column("payer_name", Text),
    Column("payment_method", Text),
    Column("payment_entry_id", Text,
           ForeignKey("payment_entry.id", ondelete="RESTRICT")),
    Column("eob_date", Text),           # explanation of benefits date
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "posting_type IN ('insurance_payment','patient_payment','adjustment',"
        "'refund','write_off')",
        name="ck_healthclaw_payment_posting_posting_type"),
    CheckConstraint(
        "payment_method IN ('check','eft','cash','credit_card','ach','other')",
        name="ck_healthclaw_payment_posting_payment_method"),
)

Index("idx_hc_posting_claim", PAYMENT_POSTING.c.claim_id)
Index("idx_hc_posting_patient", PAYMENT_POSTING.c.patient_id)
Index("idx_hc_posting_type", PAYMENT_POSTING.c.posting_type)
Index("idx_hc_posting_date", PAYMENT_POSTING.c.posting_date)
Index("idx_hc_posting_payment", PAYMENT_POSTING.c.payment_entry_id)

# ==========================================================
# DOMAIN 5: INVENTORY / PHARMACY (3 tables)
# ==========================================================

# Drug formulary header
FORMULARY = Table(
    "healthclaw_formulary", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("name", Text, nullable=False),
    Column("description", Text),
    Column("effective_date", Text, nullable=False),
    Column("expiration_date", Text),
    Column("status", Text, nullable=False, server_default=text("'active'")),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("status IN ('active','inactive','expired')",
                    name="ck_healthclaw_formulary_status"),
)

Index("idx_hc_formulary_company", FORMULARY.c.company_id)
Index("idx_hc_formulary_status", FORMULARY.c.status)

# Formulary items (extends ERPClaw item with NDC, controlled schedule)
FORMULARY_ITEM = Table(
    "healthclaw_formulary_item", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("formulary_id", Text,
           ForeignKey("healthclaw_formulary.id", ondelete="RESTRICT"),
           nullable=False),
    Column("item_id", Text,
           ForeignKey("item.id", ondelete="RESTRICT"), nullable=False),
    Column("ndc_code", Text),           # National Drug Code
    Column("drug_class", Text),
    Column("generic_name", Text),
    Column("brand_name", Text),
    Column("strength", Text),           # e.g., "500mg"
    Column("dosage_form", Text),        # e.g., "tablet", "capsule", "injection"
    Column("route", Text),
    Column("controlled_schedule", Text),
    Column("therapeutic_class", Text),
    Column("formulary_tier", Text),
    Column("requires_prior_auth", Integer, nullable=False,
           server_default=text("0")),
    Column("max_daily_dose", Text),
    Column("status", Text, nullable=False, server_default=text("'active'")),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("controlled_schedule IN ('II','III','IV','V')",
                    name="ck_healthclaw_formulary_item_controlled_schedule"),
    CheckConstraint("formulary_tier IN ('1','2','3','4','specialty')",
                    name="ck_healthclaw_formulary_item_formulary_tier"),
    CheckConstraint("requires_prior_auth IN (0,1)",
                    name="ck_healthclaw_formulary_item_requires_prior_auth"),
    CheckConstraint("status IN ('active','inactive','recalled')",
                    name="ck_healthclaw_formulary_item_status"),
    # Idempotency key — one formulary entry per item.
    UniqueConstraint("formulary_id", "item_id"),
)

Index("idx_hc_fitem_formulary", FORMULARY_ITEM.c.formulary_id)
Index("idx_hc_fitem_item", FORMULARY_ITEM.c.item_id)
Index("idx_hc_fitem_ndc", FORMULARY_ITEM.c.ndc_code)

# Medication dispensing record
DISPENSING = Table(
    "healthclaw_dispensing", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("prescription_id", Text,
           ForeignKey("healthclaw_prescription.id", ondelete="RESTRICT"),
           nullable=False),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id", ondelete="RESTRICT"),
           nullable=False),
    Column("formulary_item_id", Text,
           ForeignKey("healthclaw_formulary_item.id", ondelete="RESTRICT")),
    Column("item_id", Text, ForeignKey("item.id", ondelete="RESTRICT")),
    Column("dispensed_by_id", Text,
           ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
    Column("dispensed_date", Text, nullable=False),
    Column("quantity", Text, nullable=False, server_default=text("'0'")),
    Column("lot_number", Text),
    Column("expiration_date", Text),
    Column("ndc_code", Text),
    Column("directions", Text),
    Column("refill_number", Integer, nullable=False, server_default=text("0")),
    Column("status", Text, nullable=False, server_default=text("'dispensed'")),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "status IN ('dispensed','returned','recalled','voided')",
        name="ck_healthclaw_dispensing_status"),
)

Index("idx_hc_disp_rx", DISPENSING.c.prescription_id)
Index("idx_hc_disp_patient", DISPENSING.c.patient_id)
Index("idx_hc_disp_date", DISPENSING.c.dispensed_date)
Index("idx_hc_disp_item", DISPENSING.c.item_id)

# ==========================================================
# DOMAIN 6: LAB / DIAGNOSTICS (5 tables)
# ==========================================================

# Lab order header
# Merged from hcadv_lab_order: ordering_provider, lab_test_id, order_status, clinical_notes, collected_at, completed_at
LAB_ORDER = Table(
    "healthclaw_lab_order", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("order_id", Text,
           ForeignKey("healthclaw_order.id", ondelete="RESTRICT")),
    Column("encounter_id", Text,
           ForeignKey("healthclaw_encounter.id", ondelete="RESTRICT")),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id", ondelete="RESTRICT"),
           nullable=False),
    Column("ordering_provider_id", Text,
           ForeignKey("employee.id", ondelete="RESTRICT")),
    Column("ordering_provider", Text),  # from hcadv: provider name (when no FK)
    # from hcadv: links to healthclaw_lab_test, but carries no foreign key.
    Column("lab_test_id", Text),
    Column("order_date", Text, nullable=False),
    Column("priority", Text, nullable=False, server_default=text("'routine'")),
    Column("fasting_required", Integer, nullable=False, server_default=text("0")),
    Column("clinical_indication", Text),
    Column("clinical_notes", Text),     # from hcadv: clinical notes
    Column("specimen_type", Text),      # e.g., "blood", "urine", "tissue"
    Column("collection_date", Text),
    Column("received_date", Text),
    Column("collected_at", Text),       # from hcadv: collection timestamp
    Column("completed_at", Text),       # from hcadv: completion timestamp
    Column("order_status", Text, nullable=False,
           server_default=text("'ordered'")),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("priority IN ('stat','urgent','routine')",
                    name="ck_healthclaw_lab_order_priority"),
    CheckConstraint("fasting_required IN (0,1)",
                    name="ck_healthclaw_lab_order_fasting_required"),
    CheckConstraint(
        "order_status IN ('ordered','collected','received','in_progress',"
        " 'completed','cancelled')",
        name="ck_healthclaw_lab_order_order_status"),
)

Index("idx_hc_labord_company", LAB_ORDER.c.company_id)
Index("idx_hc_labord_encounter", LAB_ORDER.c.encounter_id)
Index("idx_hc_labord_patient", LAB_ORDER.c.patient_id)
Index("idx_hc_labord_provider", LAB_ORDER.c.ordering_provider_id)
Index("idx_hc_labord_status", LAB_ORDER.c.order_status)
Index("idx_hc_labord_date", LAB_ORDER.c.order_date)

# Individual lab tests within an order
# Merged from hcadv_lab_test: company_id, loinc_code, category, specimen_type,
#   reference_range, unit, turnaround_hours, base_price, is_active, notes
LAB_TEST = Table(
    "healthclaw_lab_test", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("lab_order_id", Text,
           ForeignKey("healthclaw_lab_order.id", ondelete="RESTRICT")),
    # from hcadv — nullable here, unlike every other company_id in the module.
    Column("company_id", Text, ForeignKey("company.id", ondelete="RESTRICT")),
    Column("test_code", Text),          # LOINC or internal code
    Column("test_name", Text, nullable=False),
    Column("loinc_code", Text),         # from hcadv: LOINC code
    Column("cpt_code", Text),
    Column("category", Text),           # from hcadv: test category
    Column("specimen_type", Text),      # from hcadv: specimen type
    Column("reference_range", Text),    # from hcadv: expected range
    Column("unit", Text),               # from hcadv: measurement unit
    Column("turnaround_hours", Integer),  # from hcadv: expected turnaround
    # from hcadv: test price
    Column("base_price", Text, nullable=False, server_default=text("'0.00'")),
    Column("is_active", Integer, nullable=False, server_default=text("1")),
    Column("status", Text, nullable=False, server_default=text("'pending'")),
    Column("notes", Text),              # from hcadv
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "status IN ('pending','in_progress','completed','cancelled')",
        name="ck_healthclaw_lab_test_status"),
)

Index("idx_hc_labtest_order", LAB_TEST.c.lab_order_id)
Index("idx_hc_labtest_code", LAB_TEST.c.test_code)

# Lab test results
# Merged from hcadv_lab_result: company_id, lab_order_id, patient_id, result_value,
#   result_unit, reference_range, is_abnormal, is_critical, performed_by, verified_by, result_notes
LAB_RESULT = Table(
    "healthclaw_lab_result", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("lab_test_id", Text,
           ForeignKey("healthclaw_lab_test.id", ondelete="RESTRICT"),
           nullable=False),
    # from hcadv: direct link to lab order, but carries no foreign key.
    Column("lab_order_id", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT")),  # from hcadv
    # from hcadv: patient reference, but carries no foreign key.
    Column("patient_id", Text),
    Column("component_name", Text),     # e.g., "Hemoglobin", "WBC"
    Column("value", Text),
    Column("result_value", Text),       # from hcadv: result value
    Column("unit", Text),               # e.g., "g/dL", "cells/mcL"
    Column("result_unit", Text),        # from hcadv: result unit
    Column("reference_low", Text),
    Column("reference_high", Text),
    Column("reference_range", Text),    # from hcadv: combined reference range
    Column("flag", Text),
    Column("is_abnormal", Integer, nullable=False, server_default=text("0")),
    Column("is_critical", Integer, nullable=False, server_default=text("0")),
    Column("result_date", Text, nullable=False),
    Column("performed_by_id", Text,
           ForeignKey("employee.id", ondelete="RESTRICT")),
    Column("verified_by_id", Text,
           ForeignKey("employee.id", ondelete="RESTRICT")),
    Column("performed_by", Text),       # from hcadv: performer name (when no FK)
    Column("verified_by", Text),        # from hcadv: verifier name (when no FK)
    Column("notes", Text),
    Column("result_notes", Text),       # from hcadv: result-specific notes
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "flag IN ('normal','low','high','critical_low','critical_high',"
        "'abnormal')",
        name="ck_healthclaw_lab_result_flag"),
)

Index("idx_hc_labres_test", LAB_RESULT.c.lab_test_id)
Index("idx_hc_labres_flag", LAB_RESULT.c.flag)

# Imaging / radiology order
IMAGING_ORDER = Table(
    "healthclaw_imaging_order", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("order_id", Text,
           ForeignKey("healthclaw_order.id", ondelete="RESTRICT")),
    Column("encounter_id", Text,
           ForeignKey("healthclaw_encounter.id", ondelete="RESTRICT"),
           nullable=False),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id", ondelete="RESTRICT"),
           nullable=False),
    Column("ordering_provider_id", Text,
           ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
    Column("modality", Text, nullable=False),
    Column("body_part", Text, nullable=False),
    Column("laterality", Text),
    Column("cpt_code", Text),
    Column("order_date", Text, nullable=False),
    Column("priority", Text, nullable=False, server_default=text("'routine'")),
    Column("clinical_indication", Text),
    Column("contrast", Integer, nullable=False, server_default=text("0")),
    Column("status", Text, nullable=False, server_default=text("'ordered'")),
    Column("scheduled_date", Text),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "modality IN ( 'xray','ct','mri','ultrasound','mammography',"
        " 'fluoroscopy','nuclear','pet','dexa','other' )",
        name="ck_healthclaw_imaging_order_modality"),
    CheckConstraint(
        "laterality IN ('left','right','bilateral','not_applicable')",
        name="ck_healthclaw_imaging_order_laterality"),
    CheckConstraint("priority IN ('stat','urgent','routine')",
                    name="ck_healthclaw_imaging_order_priority"),
    CheckConstraint("contrast IN (0,1)",
                    name="ck_healthclaw_imaging_order_contrast"),
    CheckConstraint(
        "status IN ('ordered','scheduled','in_progress','completed',"
        " 'read','cancelled')",
        name="ck_healthclaw_imaging_order_status"),
)

Index("idx_hc_imgord_company", IMAGING_ORDER.c.company_id)
Index("idx_hc_imgord_encounter", IMAGING_ORDER.c.encounter_id)
Index("idx_hc_imgord_patient", IMAGING_ORDER.c.patient_id)
Index("idx_hc_imgord_modality", IMAGING_ORDER.c.modality)
Index("idx_hc_imgord_status", IMAGING_ORDER.c.status)

# Imaging results / radiology report
IMAGING_RESULT = Table(
    "healthclaw_imaging_result", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("imaging_order_id", Text,
           ForeignKey("healthclaw_imaging_order.id", ondelete="RESTRICT"),
           nullable=False),
    Column("radiologist_id", Text,
           ForeignKey("employee.id", ondelete="RESTRICT")),
    Column("findings", Text),
    Column("impression", Text),
    Column("recommendation", Text),
    Column("critical_finding", Integer, nullable=False, server_default=text("0")),
    Column("report_date", Text, nullable=False),
    Column("status", Text, nullable=False,
           server_default=text("'preliminary'")),
    Column("addendum", Text),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("critical_finding IN (0,1)",
                    name="ck_healthclaw_imaging_result_critical_finding"),
    CheckConstraint(
        "status IN ('preliminary','final','addended','corrected')",
        name="ck_healthclaw_imaging_result_status"),
)

Index("idx_hc_imgres_order", IMAGING_RESULT.c.imaging_order_id)
Index("idx_hc_imgres_radiologist", IMAGING_RESULT.c.radiologist_id)
Index("idx_hc_imgres_status", IMAGING_RESULT.c.status)

# ==========================================================
# DOMAIN 7: REFERRALS / PRIOR AUTH (3 tables)
# ==========================================================

# Patient referral
REFERRAL = Table(
    "healthclaw_referral", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id", ondelete="RESTRICT"),
           nullable=False),
    Column("encounter_id", Text,
           ForeignKey("healthclaw_encounter.id", ondelete="RESTRICT")),
    Column("referring_provider_id", Text,
           ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
    # external provider name (may not be in employee table)
    Column("referred_to_provider", Text, nullable=False),
    Column("referred_to_specialty", Text),
    Column("referred_to_facility", Text),
    Column("referred_to_phone", Text),
    Column("referred_to_fax", Text),
    Column("referral_date", Text, nullable=False),
    Column("expiration_date", Text),
    Column("reason", Text, nullable=False),
    Column("diagnosis_id", Text,
           ForeignKey("healthclaw_diagnosis.id", ondelete="RESTRICT")),
    Column("priority", Text, nullable=False, server_default=text("'routine'")),
    Column("insurance_id", Text,
           ForeignKey("healthclaw_patient_insurance.id", ondelete="RESTRICT")),
    Column("prior_auth_required", Integer, nullable=False,
           server_default=text("0")),
    Column("prior_auth_id", Text,
           ForeignKey("healthclaw_prior_auth.id", ondelete="RESTRICT")),
    Column("status", Text, nullable=False, server_default=text("'pending'")),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("priority IN ('stat','urgent','routine','elective')",
                    name="ck_healthclaw_referral_priority"),
    CheckConstraint("prior_auth_required IN (0,1)",
                    name="ck_healthclaw_referral_prior_auth_required"),
    CheckConstraint(
        "status IN ('pending','sent','accepted','declined',"
        " 'completed','expired','cancelled')",
        name="ck_healthclaw_referral_status"),
)

Index("idx_hc_ref_company", REFERRAL.c.company_id)
Index("idx_hc_ref_patient", REFERRAL.c.patient_id)
Index("idx_hc_ref_encounter", REFERRAL.c.encounter_id)
Index("idx_hc_ref_referring", REFERRAL.c.referring_provider_id)
Index("idx_hc_ref_status", REFERRAL.c.status)
Index("idx_hc_ref_date", REFERRAL.c.referral_date)

# Prior authorization request
PRIOR_AUTH = Table(
    "healthclaw_prior_auth", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id", ondelete="RESTRICT"),
           nullable=False),
    Column("insurance_id", Text,
           ForeignKey("healthclaw_patient_insurance.id", ondelete="RESTRICT"),
           nullable=False),
    Column("requesting_provider_id", Text,
           ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
    Column("auth_number", Text),        # payer-assigned auth number
    Column("service_type", Text, nullable=False),
    Column("cpt_codes", Text),          # JSON array of CPT codes
    Column("icd10_codes", Text),        # JSON array of ICD-10 codes
    Column("description", Text, nullable=False),
    Column("units_requested", Integer, nullable=False, server_default=text("1")),
    Column("units_approved", Integer),
    Column("request_date", Text, nullable=False),
    Column("effective_date", Text),
    Column("expiration_date", Text),
    Column("decision_date", Text),
    Column("status", Text, nullable=False, server_default=text("'pending'")),
    Column("denial_reason", Text),
    Column("appeal_deadline", Text),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "service_type IN ( 'procedure','imaging','medication','dme','inpatient',"
        " 'outpatient','referral','therapy','other' )",
        name="ck_healthclaw_prior_auth_service_type"),
    CheckConstraint(
        "status IN ('pending','approved','denied','partially_approved',"
        " 'expired','cancelled','appealed')",
        name="ck_healthclaw_prior_auth_status"),
)

Index("idx_hc_auth_company", PRIOR_AUTH.c.company_id)
Index("idx_hc_auth_patient", PRIOR_AUTH.c.patient_id)
Index("idx_hc_auth_insurance", PRIOR_AUTH.c.insurance_id)
Index("idx_hc_auth_status", PRIOR_AUTH.c.status)
Index("idx_hc_auth_number", PRIOR_AUTH.c.auth_number)
Index("idx_hc_auth_dates", PRIOR_AUTH.c.effective_date,
      PRIOR_AUTH.c.expiration_date)

# Authorization usage tracking (tracks visits/units used against an auth)
AUTH_USAGE = Table(
    "healthclaw_auth_usage", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("prior_auth_id", Text,
           ForeignKey("healthclaw_prior_auth.id", ondelete="RESTRICT"),
           nullable=False),
    Column("encounter_id", Text,
           ForeignKey("healthclaw_encounter.id", ondelete="RESTRICT")),
    Column("claim_id", Text,
           ForeignKey("healthclaw_claim.id", ondelete="RESTRICT")),
    Column("usage_date", Text, nullable=False),
    Column("units_used", Integer, nullable=False, server_default=text("1")),
    Column("notes", Text),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
)

Index("idx_hc_authuse_auth", AUTH_USAGE.c.prior_auth_id)
Index("idx_hc_authuse_encounter", AUTH_USAGE.c.encounter_id)

# ══════════════════════════════════════════════════════════════
# HealthClaw Advanced Domain Tables (5 tables, healthclaw_ prefix)
# Medication, Dispense Log, Procedure Code, Drug Interaction,
# Controlled Substance Log
# (7 former hcadv_ duplicates merged into core tables above)
#
# These arrived later than the core tables and their foreign keys carry NO
# `ON DELETE` action, unlike everything above. Preserved as shipped.
# ══════════════════════════════════════════════════════════════

# -- healthclaw_medication (renamed from hcadv_medication) --
MEDICATION = Table(
    "healthclaw_medication", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("name", Text, nullable=False),
    Column("generic_name", Text),
    Column("ndc_code", Text),
    Column("dea_schedule", Text, nullable=False,
           server_default=text("'non-scheduled'")),
    Column("dosage_form", Text),
    Column("strength", Text),
    Column("manufacturer", Text),
    Column("unit_price", Text, nullable=False, server_default=text("'0.00'")),
    Column("quantity_on_hand", Integer, nullable=False, server_default=text("0")),
    Column("reorder_level", Integer, nullable=False, server_default=text("0")),
    Column("is_active", Integer, nullable=False, server_default=text("1")),
    Column("notes", Text),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "dea_schedule IN ('I','II','III','IV','V','non-scheduled')",
        name="ck_healthclaw_medication_dea_schedule"),
)

Index("idx_hc_med_company", MEDICATION.c.company_id)
Index("idx_hc_med_name", MEDICATION.c.name)
Index("idx_hc_med_ndc", MEDICATION.c.ndc_code)
Index("idx_hc_med_schedule", MEDICATION.c.dea_schedule)

# -- healthclaw_dispense_log (renamed from hcadv_dispense_log) --
DISPENSE_LOG = Table(
    "healthclaw_dispense_log", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    # NOT NULL but carries no foreign key, unlike medication_id below.
    Column("prescription_id", Text, nullable=False),
    Column("medication_id", Text,
           ForeignKey("healthclaw_medication.id"), nullable=False),
    Column("dispensed_by", Text, nullable=False),
    Column("quantity_dispensed", Integer, nullable=False,
           server_default=text("0")),
    Column("dispense_date", Text, nullable=False),
    Column("is_refill", Integer, nullable=False, server_default=text("0")),
    Column("lot_number", Text),
    Column("expiration_date", Text),
    Column("notes", Text),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
)

Index("idx_hc_disp_company", DISPENSE_LOG.c.company_id)
Index("idx_hc_displog_rx", DISPENSE_LOG.c.prescription_id)
Index("idx_hc_displog_med", DISPENSE_LOG.c.medication_id)
Index("idx_hc_displog_date", DISPENSE_LOG.c.dispense_date)

# -- healthclaw_procedure_code (renamed from hcadv_procedure_code) --
PROCEDURE_CODE = Table(
    "healthclaw_procedure_code", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("code", Text, nullable=False),
    Column("code_type", Text, nullable=False, server_default=text("'CPT'")),
    Column("description", Text, nullable=False),
    Column("category", Text),
    Column("default_fee", Text, nullable=False, server_default=text("'0.00'")),
    Column("is_active", Integer, nullable=False, server_default=text("1")),
    Column("notes", Text),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("code_type IN ('CPT','ICD-10','HCPCS')",
                    name="ck_healthclaw_procedure_code_code_type"),
)

Index("idx_hc_pc_company", PROCEDURE_CODE.c.company_id)
Index("idx_hc_pc_code", PROCEDURE_CODE.c.code)
Index("idx_hc_pc_type", PROCEDURE_CODE.c.code_type)

# -- healthclaw_drug_interaction (renamed from hcadv_drug_interaction) --
DRUG_INTERACTION = Table(
    "healthclaw_drug_interaction", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("medication_a_id", Text,
           ForeignKey("healthclaw_medication.id"), nullable=False),
    Column("medication_b_id", Text,
           ForeignKey("healthclaw_medication.id"), nullable=False),
    Column("severity", Text, nullable=False, server_default=text("'moderate'")),
    Column("description", Text, nullable=False),
    Column("recommendation", Text),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "severity IN ('minor','moderate','major','contraindicated')",
        name="ck_healthclaw_drug_interaction_severity"),
)

Index("idx_hc_di_company", DRUG_INTERACTION.c.company_id)
Index("idx_hc_di_med_a", DRUG_INTERACTION.c.medication_a_id)
Index("idx_hc_di_med_b", DRUG_INTERACTION.c.medication_b_id)

# -- healthclaw_controlled_substance_log (renamed from hcadv_controlled_substance_log) --
CONTROLLED_SUBSTANCE_LOG = Table(
    "healthclaw_controlled_substance_log", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("medication_id", Text,
           ForeignKey("healthclaw_medication.id"), nullable=False),
    Column("prescription_id", Text),
    Column("action_type", Text, nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("dea_number", Text),
    Column("performed_by", Text, nullable=False),
    Column("witness", Text),
    Column("log_date", Text, nullable=False),
    Column("notes", Text),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "action_type IN ('received','dispensed','destroyed','returned',"
        "'adjusted')",
        name="ck_healthclaw_controlled_substance_log_action_type"),
)

Index("idx_hc_csl_company", CONTROLLED_SUBSTANCE_LOG.c.company_id)
Index("idx_hc_csl_med", CONTROLLED_SUBSTANCE_LOG.c.medication_id)
Index("idx_hc_csl_rx", CONTROLLED_SUBSTANCE_LOG.c.prescription_id)
Index("idx_hc_csl_date", CONTROLLED_SUBSTANCE_LOG.c.log_date)
Index("idx_hc_csl_type", CONTROLLED_SUBSTANCE_LOG.c.action_type)

# ══════════════════════════════════════════════════════════════
# DOMAIN 12: PAYER MANAGEMENT (Phase 1 RCM)
#
# From here down the shipped DDL spells its timestamp default
# `(datetime('now'))` rather than `CURRENT_TIMESTAMP`. Transcribed as written —
# see the note on `create_healthclaw_tables`.
# ══════════════════════════════════════════════════════════════

# -- healthclaw_payer --
PAYER = Table(
    "healthclaw_payer", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("name", Text, nullable=False),
    Column("payer_type", Text, nullable=False),
    Column("edi_payer_id", Text),
    Column("electronic_filing_id", Text),
    Column("address", Text),
    Column("city", Text),
    Column("state", Text),
    Column("zip", Text),
    Column("phone", Text),
    Column("claims_address", Text),
    Column("claims_city", Text),
    Column("claims_state", Text),
    Column("claims_zip", Text),
    Column("submission_method", Text, nullable=False,
           server_default=text("'electronic'")),
    Column("timely_filing_days", Integer, server_default=text("365")),
    Column("era_enrollment", Text, nullable=False,
           server_default=text("'not_enrolled'")),
    # No foreign key onto healthclaw_fee_schedule. Preserved as shipped.
    Column("default_fee_schedule_id", Text),
    Column("notes", Text),
    Column("status", Text, nullable=False, server_default=text("'active'")),
    Column("created_at", Text, server_default=now_default()),
    Column("updated_at", Text, server_default=now_default()),
    CheckConstraint(
        "payer_type IN ('commercial','medicare','medicaid','tricare',"
        "'workers_comp','self_pay','other')",
        name="ck_healthclaw_payer_payer_type"),
    CheckConstraint(
        "submission_method IN ('electronic','paper','portal')",
        name="ck_healthclaw_payer_submission_method"),
    CheckConstraint(
        "era_enrollment IN ('enrolled','not_enrolled','pending')",
        name="ck_healthclaw_payer_era_enrollment"),
    CheckConstraint("status IN ('active','inactive')",
                    name="ck_healthclaw_payer_status"),
)

Index("idx_healthclaw_payer_company", PAYER.c.company_id)
Index("idx_healthclaw_payer_edi", PAYER.c.edi_payer_id)

# -- healthclaw_eligibility_check --
ELIGIBILITY_CHECK = Table(
    "healthclaw_eligibility_check", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id"), nullable=False),
    Column("patient_insurance_id", Text,
           ForeignKey("healthclaw_patient_insurance.id"), nullable=False),
    Column("payer_id", Text, ForeignKey("healthclaw_payer.id")),
    Column("check_date", Text, nullable=False),
    Column("check_method", Text, nullable=False, server_default=text("'manual'")),
    Column("coverage_status", Text, nullable=False),
    Column("copay", Text),
    Column("deductible", Text),
    Column("deductible_met", Text),
    Column("coinsurance_pct", Text),
    Column("out_of_pocket_max", Text),
    Column("oop_met", Text),
    Column("plan_begin_date", Text),
    Column("plan_end_date", Text),
    Column("in_network", Integer, server_default=text("1")),
    Column("prior_auth_required", Integer, server_default=text("0")),
    Column("notes", Text),
    Column("checked_by", Text),
    Column("created_at", Text, server_default=now_default()),
    CheckConstraint("check_method IN ('manual','electronic','phone')",
                    name="ck_healthclaw_eligibility_check_check_method"),
    CheckConstraint(
        "coverage_status IN ('active','inactive','termed','pending','unknown')",
        name="ck_healthclaw_eligibility_check_coverage_status"),
)

Index("idx_healthclaw_eligibility_patient", ELIGIBILITY_CHECK.c.patient_id)
Index("idx_healthclaw_eligibility_date", ELIGIBILITY_CHECK.c.check_date)

# -- healthclaw_era_file (ERA/835 Electronic Remittance Processing) --
ERA_FILE = Table(
    "healthclaw_era_file", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("file_name", Text),
    Column("payer_id", Text, ForeignKey("healthclaw_payer.id")),
    Column("received_date", Text, nullable=False),
    Column("check_number", Text),
    Column("check_amount", Text),
    Column("eft_trace", Text),
    Column("claim_count", Integer, server_default=text("0")),
    Column("matched_count", Integer, server_default=text("0")),
    Column("posted_amount", Text, server_default=text("'0'")),
    Column("status", Text, nullable=False, server_default=text("'received'")),
    Column("posted_by", Text),
    Column("posted_at", Text),
    Column("notes", Text),
    Column("created_at", Text, server_default=now_default()),
    CheckConstraint(
        "status IN ('received','processing','posted','partial','error')",
        name="ck_healthclaw_era_file_status"),
)

Index("idx_healthclaw_era_file_company", ERA_FILE.c.company_id)
Index("idx_healthclaw_era_file_date", ERA_FILE.c.received_date)

# -- healthclaw_era_claim_detail --
ERA_CLAIM_DETAIL = Table(
    "healthclaw_era_claim_detail", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("era_file_id", Text,
           ForeignKey("healthclaw_era_file.id"), nullable=False),
    Column("claim_id", Text, ForeignKey("healthclaw_claim.id")),
    Column("patient_name", Text),
    Column("patient_id", Text, ForeignKey("healthclaw_patient.id")),
    Column("claim_number", Text),
    Column("service_date", Text),
    Column("billed_amount", Text, server_default=text("'0'")),
    Column("allowed_amount", Text, server_default=text("'0'")),
    Column("paid_amount", Text, server_default=text("'0'")),
    Column("patient_responsibility", Text, server_default=text("'0'")),
    Column("adjustment_amount", Text, server_default=text("'0'")),
    Column("adjustment_codes", Text),
    Column("remark_codes", Text),
    Column("match_status", Text, nullable=False,
           server_default=text("'unmatched'")),
    Column("auto_posted", Integer, server_default=text("0")),
    Column("created_at", Text, server_default=now_default()),
    CheckConstraint(
        "match_status IN ('matched','unmatched','partial','denied')",
        name="ck_healthclaw_era_claim_detail_match_status"),
)

Index("idx_healthclaw_era_detail_file", ERA_CLAIM_DETAIL.c.era_file_id)
Index("idx_healthclaw_era_detail_claim", ERA_CLAIM_DETAIL.c.claim_id)

# ==========================================================
# DOMAIN 13: COMPLIANCE (Phase 2 — HIPAA, No Surprises Act, CMS)
# ==========================================================

# -- PHI Access Audit Log — HIPAA 45 C.F.R. 164.312(b) --
PHI_ACCESS_LOG = Table(
    "healthclaw_phi_access_log", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("user_id", Text),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id"), nullable=False),
    Column("access_type", Text, nullable=False),
    Column("data_category", Text, nullable=False),
    Column("action_name", Text),
    Column("resource_id", Text),
    Column("ip_address", Text),
    Column("user_agent", Text),
    Column("access_reason", Text),
    Column("break_the_glass", Integer, server_default=text("0")),
    Column("created_at", Text, server_default=now_default()),
    CheckConstraint(
        "access_type IN ('view','edit','print','export','delete')",
        name="ck_healthclaw_phi_access_log_access_type"),
    CheckConstraint(
        "data_category IN ('demographics','clinical','billing','insurance',"
        "'medications','lab_results','imaging','notes','all')",
        name="ck_healthclaw_phi_access_log_data_category"),
)

Index("idx_healthclaw_phi_patient", PHI_ACCESS_LOG.c.patient_id)
Index("idx_healthclaw_phi_user", PHI_ACCESS_LOG.c.user_id)
Index("idx_healthclaw_phi_date", PHI_ACCESS_LOG.c.created_at)

# -- Good Faith Estimate — No Surprises Act (2022) --
GOOD_FAITH_ESTIMATE = Table(
    "healthclaw_good_faith_estimate", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id"), nullable=False),
    # No foreign key onto employee, unlike the clinical tables. Preserved.
    Column("provider_id", Text),
    Column("estimate_date", Text, nullable=False),
    Column("procedure_codes", Text),
    Column("diagnosis_codes", Text),
    Column("items", Text),
    Column("total_estimate", Text, nullable=False, server_default=text("'0'")),
    Column("facility_fee", Text, server_default=text("'0'")),
    Column("provider_fee", Text, server_default=text("'0'")),
    Column("insurance_applied", Integer, server_default=text("0")),
    Column("payer_id", Text, ForeignKey("healthclaw_payer.id")),
    Column("estimated_insurance_payment", Text, server_default=text("'0'")),
    Column("estimated_patient_responsibility", Text, server_default=text("'0'")),
    Column("valid_until", Text),
    Column("status", Text, nullable=False, server_default=text("'draft'")),
    Column("provided_at", Text),
    Column("notes", Text),
    Column("created_at", Text, server_default=now_default()),
    Column("updated_at", Text, server_default=now_default()),
    CheckConstraint(
        "status IN ('draft','provided','expired','superseded')",
        name="ck_healthclaw_good_faith_estimate_status"),
)

Index("idx_healthclaw_gfe_patient", GOOD_FAITH_ESTIMATE.c.patient_id)
Index("idx_healthclaw_gfe_date", GOOD_FAITH_ESTIMATE.c.estimate_date)

# -- MIPS Quality Measures — CMS Merit-based Incentive Payment System --
QUALITY_MEASURE = Table(
    "healthclaw_quality_measure", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("measure_id", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("category", Text, nullable=False),
    Column("description", Text),
    Column("numerator_criteria", Text),
    Column("denominator_criteria", Text),
    Column("exclusion_criteria", Text),
    Column("measure_type", Text, server_default=text("'process'")),
    Column("reporting_period", Text),
    Column("benchmark", Text),
    Column("status", Text, nullable=False, server_default=text("'active'")),
    Column("created_at", Text, server_default=now_default()),
    Column("updated_at", Text, server_default=now_default()),
    CheckConstraint(
        "category IN ('quality','improvement_activities',"
        "'promoting_interoperability','cost')",
        name="ck_healthclaw_quality_measure_category"),
    CheckConstraint(
        "measure_type IN ('process','outcome','structure','efficiency')",
        name="ck_healthclaw_quality_measure_measure_type"),
    CheckConstraint("status IN ('active','retired')",
                    name="ck_healthclaw_quality_measure_status"),
)

Index("idx_healthclaw_qm_company", QUALITY_MEASURE.c.company_id)
Index("idx_healthclaw_qm_measure", QUALITY_MEASURE.c.measure_id)

QUALITY_MEASURE_RESULT = Table(
    "healthclaw_quality_measure_result", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("measure_id", Text,
           ForeignKey("healthclaw_quality_measure.id"), nullable=False),
    Column("provider_id", Text),
    Column("reporting_period", Text, nullable=False),
    Column("numerator", Integer, server_default=text("0")),
    Column("denominator", Integer, server_default=text("0")),
    Column("exclusions", Integer, server_default=text("0")),
    Column("performance_rate", Text),
    Column("benchmark", Text),
    Column("points_earned", Text, server_default=text("'0'")),
    Column("status", Text, nullable=False,
           server_default=text("'in_progress'")),
    Column("calculated_at", Text),
    Column("notes", Text),
    Column("created_at", Text, server_default=now_default()),
    CheckConstraint(
        "status IN ('in_progress','calculated','submitted','accepted')",
        name="ck_healthclaw_quality_measure_result_status"),
)

Index("idx_healthclaw_qmr_measure", QUALITY_MEASURE_RESULT.c.measure_id)
Index("idx_healthclaw_qmr_period", QUALITY_MEASURE_RESULT.c.reporting_period)

# ==========================================================
# Phase 8: Clinical Depth tables (4 tables)
#
# `company_id` is NOT NULL throughout but carries no foreign key onto `company`,
# unlike the core tables. Preserved as shipped.
# ==========================================================

# -- healthclaw_med_reconciliation (H15) --
MED_RECONCILIATION = Table(
    "healthclaw_med_reconciliation", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id"), nullable=False),
    Column("encounter_id", Text),
    Column("reconciliation_type", Text, nullable=False),
    Column("medications_reviewed", Text),
    Column("medications_added", Text),
    Column("medications_removed", Text),
    Column("medications_changed", Text),
    Column("reconciled_by", Text),
    Column("reconciled_at", Text),
    Column("notes", Text),
    Column("status", Text, server_default=text("'pending'")),
    Column("company_id", Text, nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "reconciliation_type IN ('admission','discharge','transfer',"
        "'annual_review')",
        name="ck_healthclaw_med_reconciliation_reconciliation_type"),
    CheckConstraint("status IN ('pending','completed','reviewed')",
                    name="ck_healthclaw_med_reconciliation_status"),
)

Index("idx_healthclaw_medrec_patient", MED_RECONCILIATION.c.patient_id)
Index("idx_healthclaw_medrec_status", MED_RECONCILIATION.c.status)

# -- healthclaw_immunization (H16) --
IMMUNIZATION = Table(
    "healthclaw_immunization", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id"), nullable=False),
    Column("vaccine_name", Text, nullable=False),
    Column("vaccine_code", Text),
    Column("lot_number", Text),
    Column("manufacturer", Text),
    Column("administration_date", Text, nullable=False),
    Column("administration_site", Text),
    Column("administered_by", Text),
    Column("dose_number", Integer),
    Column("series_complete", Integer, server_default=text("0")),
    Column("vis_date", Text),
    Column("next_due_date", Text),
    Column("reaction_notes", Text),
    Column("company_id", Text, nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
)

Index("idx_healthclaw_immun_patient", IMMUNIZATION.c.patient_id)
Index("idx_healthclaw_immun_vaccine", IMMUNIZATION.c.vaccine_name)
Index("idx_healthclaw_immun_duedate", IMMUNIZATION.c.next_due_date)

# -- healthclaw_provider_credential (H19) --
PROVIDER_CREDENTIAL = Table(
    "healthclaw_provider_credential", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("provider_id", Text, ForeignKey("employee.id"), nullable=False),
    Column("credential_type", Text, nullable=False),
    Column("credential_number", Text),
    Column("issuing_authority", Text),
    Column("issue_date", Text),
    Column("expiration_date", Text),
    Column("status", Text, server_default=text("'active'")),
    Column("verification_date", Text),
    Column("verified_by", Text),
    Column("notes", Text),
    Column("company_id", Text, nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "credential_type IN ('medical_license','dea','npi',"
        "'board_certification','malpractice_insurance','cds','state_license',"
        "'other')",
        name="ck_healthclaw_provider_credential_credential_type"),
    CheckConstraint("status IN ('active','expired','pending','revoked')",
                    name="ck_healthclaw_provider_credential_status"),
)

Index("idx_healthclaw_provcred_provider", PROVIDER_CREDENTIAL.c.provider_id)
Index("idx_healthclaw_provcred_type", PROVIDER_CREDENTIAL.c.credential_type)
Index("idx_healthclaw_provcred_expiry", PROVIDER_CREDENTIAL.c.expiration_date)
Index("idx_healthclaw_provcred_status", PROVIDER_CREDENTIAL.c.status)

# -- healthclaw_payer_enrollment (H20) --
PAYER_ENROLLMENT = Table(
    "healthclaw_payer_enrollment", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    # NOT NULL but no foreign key, unlike healthclaw_provider_credential above.
    Column("provider_id", Text, nullable=False),
    Column("payer_id", Text,
           ForeignKey("healthclaw_payer.id"), nullable=False),
    Column("enrollment_status", Text, nullable=False),
    Column("effective_date", Text),
    Column("termination_date", Text),
    Column("revalidation_date", Text),
    Column("provider_number", Text),
    Column("group_npi", Text),
    Column("notes", Text),
    Column("company_id", Text, nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "enrollment_status IN ('pending','active','inactive','terminated')",
        name="ck_healthclaw_payer_enrollment_enrollment_status"),
)

Index("idx_healthclaw_payerenroll_provider", PAYER_ENROLLMENT.c.provider_id)
Index("idx_healthclaw_payerenroll_payer", PAYER_ENROLLMENT.c.payer_id)
Index("idx_healthclaw_payerenroll_status", PAYER_ENROLLMENT.c.enrollment_status)
Index("idx_healthclaw_payerenroll_reval", PAYER_ENROLLMENT.c.revalidation_date)

# ==========================================================
# Phase 11: Healthclaw Remaining (7 new tables)
# ==========================================================

# -- H7: Patient Statements --
PATIENT_STATEMENT = Table(
    "healthclaw_patient_statement", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id"), nullable=False),
    Column("statement_date", Text, nullable=False),
    Column("period_start", Text),
    Column("period_end", Text),
    Column("total_charges", Text, server_default=text("'0'")),
    Column("insurance_payments", Text, server_default=text("'0'")),
    Column("patient_payments", Text, server_default=text("'0'")),
    Column("adjustments", Text, server_default=text("'0'")),
    Column("balance_due", Text, server_default=text("'0'")),
    Column("status", Text, server_default=text("'generated'")),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("created_at", Text, server_default=now_default()),
    CheckConstraint("status IN ('generated','sent','paid')",
                    name="ck_healthclaw_patient_statement_status"),
)

Index("idx_hc_stmt_patient", PATIENT_STATEMENT.c.patient_id)
Index("idx_hc_stmt_date", PATIENT_STATEMENT.c.statement_date)
Index("idx_hc_stmt_status", PATIENT_STATEMENT.c.status)

# -- H8: Payment Plans --
PAYMENT_PLAN = Table(
    "healthclaw_payment_plan", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id"), nullable=False),
    Column("total_amount", Text, nullable=False),
    Column("installment_amount", Text, nullable=False),
    Column("frequency", Text, server_default=text("'monthly'")),
    Column("start_date", Text, nullable=False),
    Column("next_due_date", Text),
    Column("num_installments", Integer),
    Column("installments_paid", Integer, server_default=text("0")),
    Column("remaining_balance", Text, nullable=False),
    Column("status", Text, server_default=text("'active'")),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("created_at", Text, server_default=now_default()),
    CheckConstraint("frequency IN ('weekly','biweekly','monthly')",
                    name="ck_healthclaw_payment_plan_frequency"),
    CheckConstraint(
        "status IN ('active','completed','defaulted','cancelled')",
        name="ck_healthclaw_payment_plan_status"),
)

Index("idx_hc_payplan_patient", PAYMENT_PLAN.c.patient_id)
Index("idx_hc_payplan_status", PAYMENT_PLAN.c.status)
Index("idx_hc_payplan_due", PAYMENT_PLAN.c.next_due_date)

# -- H12: BAA Tracking --
BAA = Table(
    "healthclaw_baa", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("vendor_name", Text, nullable=False),
    Column("vendor_contact", Text),
    Column("agreement_date", Text, nullable=False),
    Column("expiration_date", Text),
    Column("review_date", Text),
    Column("phi_categories", Text),
    Column("breach_notification_days", Integer, server_default=text("60")),
    Column("status", Text, server_default=text("'active'")),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("created_at", Text, server_default=now_default()),
    CheckConstraint("status IN ('active','expired','terminated')",
                    name="ck_healthclaw_baa_status"),
)

Index("idx_hc_baa_company", BAA.c.company_id)
Index("idx_hc_baa_status", BAA.c.status)
Index("idx_hc_baa_expiry", BAA.c.expiration_date)

# -- H13: Breach Incident --
BREACH_INCIDENT = Table(
    "healthclaw_breach_incident", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("discovery_date", Text, nullable=False),
    Column("incident_date", Text),
    Column("description", Text, nullable=False),
    Column("phi_type", Text),
    Column("individuals_affected", Integer, server_default=text("0")),
    Column("risk_level", Text),
    Column("notification_required", Integer, server_default=text("0")),
    Column("notification_sent_date", Text),
    Column("hhs_reported", Integer, server_default=text("0")),
    Column("hhs_report_date", Text),
    Column("remediation", Text),
    Column("status", Text, server_default=text("'investigating'")),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("created_at", Text, server_default=now_default()),
    CheckConstraint("risk_level IN ('low','medium','high')",
                    name="ck_healthclaw_breach_incident_risk_level"),
    CheckConstraint(
        "status IN ('investigating','contained','remediated','closed')",
        name="ck_healthclaw_breach_incident_status"),
)

Index("idx_hc_breach_company", BREACH_INCIDENT.c.company_id)
Index("idx_hc_breach_status", BREACH_INCIDENT.c.status)
Index("idx_hc_breach_risk", BREACH_INCIDENT.c.risk_level)

# -- H17: Care Team --
CARE_TEAM = Table(
    "healthclaw_care_team", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("patient_id", Text,
           ForeignKey("healthclaw_patient.id"), nullable=False),
    Column("provider_id", Text, ForeignKey("employee.id"), nullable=False),
    Column("role", Text, nullable=False),
    Column("start_date", Text),
    Column("end_date", Text),
    Column("status", Text, server_default=text("'active'")),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("created_at", Text, server_default=now_default()),
    CheckConstraint(
        "role IN ('pcp','specialist','care_coordinator','nurse','therapist',"
        "'social_worker','pharmacist','other')",
        name="ck_healthclaw_care_team_role"),
    CheckConstraint("status IN ('active','inactive')",
                    name="ck_healthclaw_care_team_status"),
)

Index("idx_hc_careteam_patient", CARE_TEAM.c.patient_id)
Index("idx_hc_careteam_provider", CARE_TEAM.c.provider_id)
Index("idx_hc_careteam_status", CARE_TEAM.c.status)

# -- H6: Crossover Claims (secondary insurance tracking) --
CROSSOVER_CLAIM = Table(
    "healthclaw_crossover_claim", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("original_claim_id", Text,
           ForeignKey("healthclaw_claim.id"), nullable=False),
    Column("secondary_insurance_id", Text,
           ForeignKey("healthclaw_patient_insurance.id"), nullable=False),
    Column("primary_paid_amount", Text, server_default=text("'0'")),
    Column("primary_allowed_amount", Text, server_default=text("'0'")),
    Column("remaining_balance", Text, server_default=text("'0'")),
    # No foreign key onto healthclaw_claim, unlike original_claim_id. Preserved.
    Column("secondary_claim_id", Text),
    Column("status", Text, server_default=text("'pending'")),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("created_at", Text, server_default=now_default()),
    CheckConstraint("status IN ('pending','submitted','paid','denied')",
                    name="ck_healthclaw_crossover_claim_status"),
)

Index("idx_hc_xover_original", CROSSOVER_CLAIM.c.original_claim_id)
Index("idx_hc_xover_status", CROSSOVER_CLAIM.c.status)

# -- H25/H26: Scheduling Rules (simple key-value for online scheduling config) --
SCHEDULING_RULE = Table(
    "healthclaw_scheduling_rule", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("rule_name", Text, nullable=False),
    Column("rule_type", Text, nullable=False),
    Column("rule_value", Text, nullable=False),
    # No foreign key onto employee. Preserved as shipped.
    Column("provider_id", Text),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("status", Text, server_default=text("'active'")),
    Column("created_at", Text, server_default=now_default()),
    CheckConstraint(
        "rule_type IN ('buffer_time','max_per_day','advance_booking_days',"
        "'cancellation_hours','appointment_types_allowed')",
        name="ck_healthclaw_scheduling_rule_rule_type"),
    CheckConstraint("status IN ('active','inactive')",
                    name="ck_healthclaw_scheduling_rule_status"),
)

Index("idx_hc_schedrule_company", SCHEDULING_RULE.c.company_id)
Index("idx_hc_schedrule_type", SCHEDULING_RULE.c.rule_type)

# ── Naming series: registered on first use, never pre-seeded ──
# get_next_name() (erpclaw_lib/naming.py) self-registers a row via
# INSERT ... ON CONFLICT DO UPDATE, storing the canonical year-scoped
# prefix f"{base}{year}-" (e.g. "APPT-2026-") — which is also the key it
# looks rows up by. The pre-seed that used to live here wrote bare prefixes
# ("APPT"), which no code ever read: dead rows whose only effect was to
# trip INV-10's naming-format check. Base prefixes are owned by
# ENTITY_PREFIXES, registered by the healthclaw scripts themselves
# (appointments.py:21, clinical.py:1095, ...).


def _require_foundation(db_path):
    """The pre-conversion installer's foundation probe, asked through the seam.

    The original read ``sqlite_master`` directly, so the guard that exists to
    produce a friendly error was itself SQLite-only. ``seam.table_exists``
    answers on both backends (ADR-0034 bulk-39). Wording is this module's own,
    unchanged.
    """
    from erpclaw_lib import seam

    missing = [t for t in REQUIRED_FOUNDATION if not seam.table_exists(t, db_path)]
    if missing:
        print(f"ERROR: Foundation tables missing: {', '.join(missing)}")
        print("Run erpclaw first: clawhub install erpclaw", file=sys.stderr)
        sys.exit(1)


def create_healthclaw_tables(db_path=None):
    """Create HealthClaw tables and indexes on whichever backend is configured.

    Same contract as before the ADR-0034 conversion: idempotent, and the returned
    counts are what was ACTUALLY created rather than what was declared.

    One thing the conversion surfaced rather than fixed: the payer, compliance
    and Phase 11 tables default their timestamps to ``(datetime('now'))``, a
    SQLite-only expression PostgreSQL rejects when the table is created. It is
    transcribed here exactly as it ships, because normalising it would be a
    schema change and the parity proof compares defaults character for
    character. ADR-0034 catalogues 197 such defaults across the tree; the
    decision to normalise them belongs to that program, not to one installer.
    """
    db_path = db_path or os.environ.get("ERPCLAW_DB_PATH", DEFAULT_DB_PATH)
    _require_foundation(db_path)
    result = provision(METADATA, db_path)
    return {
        "database": db_path,
        "tables": result["tables"],
        "indexes": result["indexes"],
    }


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else None
    result = create_healthclaw_tables(db)
    print(f"{DISPLAY_NAME} schema created in {result['database']}")
    print(f"  Tables: {result['tables']}")
    print(f"  Indexes: {result['indexes']}")
    print("  Naming series: registered on first use (see naming.py)")

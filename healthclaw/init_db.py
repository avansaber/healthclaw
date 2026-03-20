#!/usr/bin/env python3
"""HealthClaw schema extension — adds domain tables to the shared database.

AI-native hospital and multi-department healthcare ERP.
40 tables across 11 domains:
  Core (35 tables, 7 domains): patients, appointments, clinical, billing, inventory, lab, referrals
  Advanced (5 tables, 2 domains): pharmacy, controlled substances

Prerequisite: ERPClaw init_db.py must have run first (creates foundation tables).
Run: python3 init_db.py [db_path]
"""
import os
import sqlite3
import sys
import uuid


DEFAULT_DB_PATH = os.path.expanduser("~/.openclaw/erpclaw/data.sqlite")
DISPLAY_NAME = "HealthClaw"

# Foundation tables that must exist before HealthClaw can install
REQUIRED_FOUNDATION = [
    "company", "customer", "employee", "item", "account",
    "sales_invoice", "payment_entry", "gl_entry", "naming_series",
]


def create_healthclaw_tables(db_path):
    conn = sqlite3.connect(db_path)
    from erpclaw_lib.db import setup_pragmas
    setup_pragmas(conn)

    # ── Verify ERPClaw foundation ────────────────────────────────
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    missing = [t for t in REQUIRED_FOUNDATION if t not in tables]
    if missing:
        print(f"ERROR: Foundation tables missing: {', '.join(missing)}")
        print("Run erpclaw first: clawhub install erpclaw", file=sys.stderr)
        conn.close()
        sys.exit(1)

    # ── Create all HealthClaw domain tables ──────────────────────
    conn.executescript("""
        -- ==========================================================
        -- HealthClaw Domain Tables
        -- 35 tables, 7 domains, healthclaw_ prefix
        -- Convention: TEXT for IDs (UUID4), TEXT for money (Decimal),
        --             TEXT for dates (ISO-8601)
        -- ==========================================================


        -- ==========================================================
        -- DOMAIN 1: PATIENTS (6 tables)
        -- ==========================================================

        -- Patient demographics — links to foundation customer (individual)
        CREATE TABLE IF NOT EXISTS healthclaw_patient (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            customer_id     TEXT REFERENCES customer(id) ON DELETE RESTRICT,
            first_name      TEXT NOT NULL,
            last_name       TEXT NOT NULL,
            full_name       TEXT NOT NULL,
            date_of_birth   TEXT NOT NULL,
            gender          TEXT NOT NULL CHECK(gender IN ('male','female','other','unknown')),
            ssn             TEXT,                -- encrypted at-rest via erpclaw_lib.crypto
            ssn_last4       TEXT,                -- last 4 digits (unencrypted, for display)
            mrn             TEXT,                -- medical record number (auto from naming_series)
            marital_status  TEXT CHECK(marital_status IN ('single','married','divorced','widowed','separated','unknown')),
            race            TEXT,
            ethnicity       TEXT CHECK(ethnicity IN ('hispanic_latino','not_hispanic_latino','unknown')),
            preferred_language TEXT NOT NULL DEFAULT 'English',
            primary_phone   TEXT,
            secondary_phone TEXT,
            email           TEXT,
            address_line1   TEXT,
            address_line2   TEXT,
            city            TEXT,
            state           TEXT,
            zip_code        TEXT,
            primary_provider_id TEXT REFERENCES employee(id) ON DELETE RESTRICT,
            status          TEXT NOT NULL DEFAULT 'active'
                            CHECK(status IN ('active','inactive','deceased')),
            notes           TEXT,
            company_id      TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_patient_company
            ON healthclaw_patient(company_id);
        CREATE INDEX IF NOT EXISTS idx_hc_patient_customer
            ON healthclaw_patient(customer_id);
        CREATE INDEX IF NOT EXISTS idx_hc_patient_provider
            ON healthclaw_patient(primary_provider_id);
        CREATE INDEX IF NOT EXISTS idx_hc_patient_status
            ON healthclaw_patient(status);
        CREATE INDEX IF NOT EXISTS idx_hc_patient_dob
            ON healthclaw_patient(date_of_birth);
        CREATE INDEX IF NOT EXISTS idx_hc_patient_name
            ON healthclaw_patient(last_name, first_name);

        -- Patient insurance coverage
        CREATE TABLE IF NOT EXISTS healthclaw_patient_insurance (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            patient_id      TEXT NOT NULL REFERENCES healthclaw_patient(id) ON DELETE RESTRICT,
            insurance_type  TEXT NOT NULL CHECK(insurance_type IN ('primary','secondary','tertiary')),
            payer_name      TEXT NOT NULL,
            payer_id        TEXT,                -- payer identifier / EDI ID
            plan_name       TEXT,
            plan_type       TEXT CHECK(plan_type IN ('hmo','ppo','epo','pos','hdhp','medicare','medicaid','tricare','workers_comp','self_pay','other')),
            group_number    TEXT,
            member_id       TEXT NOT NULL,
            subscriber_name TEXT,
            subscriber_dob  TEXT,
            subscriber_relationship TEXT NOT NULL DEFAULT 'self'
                            CHECK(subscriber_relationship IN ('self','spouse','child','other')),
            copay_amount    TEXT NOT NULL DEFAULT '0',
            deductible      TEXT NOT NULL DEFAULT '0',
            deductible_met  TEXT NOT NULL DEFAULT '0',
            out_of_pocket_max TEXT NOT NULL DEFAULT '0',
            effective_date  TEXT NOT NULL,
            termination_date TEXT,
            preauth_required INTEGER NOT NULL DEFAULT 0 CHECK(preauth_required IN (0,1)),
            status          TEXT NOT NULL DEFAULT 'active'
                            CHECK(status IN ('active','inactive','expired','terminated')),
            company_id      TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_ins_patient
            ON healthclaw_patient_insurance(patient_id);
        CREATE INDEX IF NOT EXISTS idx_hc_ins_type
            ON healthclaw_patient_insurance(insurance_type);
        CREATE INDEX IF NOT EXISTS idx_hc_ins_status
            ON healthclaw_patient_insurance(status);

        -- Patient allergies
        CREATE TABLE IF NOT EXISTS healthclaw_allergy (
            id              TEXT PRIMARY KEY,
            patient_id      TEXT NOT NULL REFERENCES healthclaw_patient(id) ON DELETE RESTRICT,
            allergen        TEXT NOT NULL,
            allergen_type   TEXT NOT NULL CHECK(allergen_type IN ('drug','food','environmental','other')),
            reaction        TEXT,
            severity        TEXT NOT NULL DEFAULT 'moderate'
                            CHECK(severity IN ('mild','moderate','severe','life_threatening')),
            onset_date      TEXT,
            status          TEXT NOT NULL DEFAULT 'active'
                            CHECK(status IN ('active','inactive','resolved')),
            noted_by_id     TEXT REFERENCES employee(id) ON DELETE RESTRICT,
            notes           TEXT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_allergy_patient
            ON healthclaw_allergy(patient_id);
        CREATE INDEX IF NOT EXISTS idx_hc_allergy_status
            ON healthclaw_allergy(status);

        -- Patient medical history
        CREATE TABLE IF NOT EXISTS healthclaw_medical_history (
            id              TEXT PRIMARY KEY,
            patient_id      TEXT NOT NULL REFERENCES healthclaw_patient(id) ON DELETE RESTRICT,
            condition       TEXT NOT NULL,
            icd10_code      TEXT,                -- ICD-10 code (text, no lookup table)
            diagnosis_date  TEXT,
            resolution_date TEXT,
            status          TEXT NOT NULL DEFAULT 'active'
                            CHECK(status IN ('active','resolved','chronic')),
            notes           TEXT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_medhist_patient
            ON healthclaw_medical_history(patient_id);
        CREATE INDEX IF NOT EXISTS idx_hc_medhist_status
            ON healthclaw_medical_history(status);

        -- Patient emergency/next-of-kin contacts
        CREATE TABLE IF NOT EXISTS healthclaw_patient_contact (
            id              TEXT PRIMARY KEY,
            patient_id      TEXT NOT NULL REFERENCES healthclaw_patient(id) ON DELETE RESTRICT,
            contact_type    TEXT NOT NULL CHECK(contact_type IN ('emergency','next_of_kin','guardian','power_of_attorney','other')),
            name            TEXT NOT NULL,
            relationship    TEXT,
            phone           TEXT,
            email           TEXT,
            address         TEXT,
            is_primary      INTEGER NOT NULL DEFAULT 0 CHECK(is_primary IN (0,1)),
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_pcontact_patient
            ON healthclaw_patient_contact(patient_id);

        -- HIPAA / treatment consent tracking
        CREATE TABLE IF NOT EXISTS healthclaw_consent (
            id              TEXT PRIMARY KEY,
            patient_id      TEXT NOT NULL REFERENCES healthclaw_patient(id) ON DELETE RESTRICT,
            consent_type    TEXT NOT NULL CHECK(consent_type IN (
                'hipaa_privacy','treatment','surgery','anesthesia',
                'research','telehealth','photo_video','release_of_info','other'
            )),
            description     TEXT,
            granted_date    TEXT NOT NULL,
            expiration_date TEXT,
            revoked_date    TEXT,
            status          TEXT NOT NULL DEFAULT 'active'
                            CHECK(status IN ('active','expired','revoked')),
            witness_name    TEXT,
            obtained_by_id  TEXT REFERENCES employee(id) ON DELETE RESTRICT,
            notes           TEXT,
            company_id      TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_consent_patient
            ON healthclaw_consent(patient_id);
        CREATE INDEX IF NOT EXISTS idx_hc_consent_type
            ON healthclaw_consent(consent_type);
        CREATE INDEX IF NOT EXISTS idx_hc_consent_status
            ON healthclaw_consent(status);


        -- ==========================================================
        -- DOMAIN 2: APPOINTMENTS (5 tables)
        -- ==========================================================

        -- Provider weekly availability template
        CREATE TABLE IF NOT EXISTS healthclaw_provider_schedule (
            id              TEXT PRIMARY KEY,
            provider_id     TEXT NOT NULL REFERENCES employee(id) ON DELETE RESTRICT,
            day_of_week     INTEGER NOT NULL CHECK(day_of_week BETWEEN 0 AND 6),  -- 0=Mon, 6=Sun
            start_time      TEXT NOT NULL,       -- HH:MM (24h)
            end_time        TEXT NOT NULL,        -- HH:MM (24h)
            slot_duration   INTEGER NOT NULL DEFAULT 30,  -- minutes
            location        TEXT,                -- room, office, clinic name
            status          TEXT NOT NULL DEFAULT 'active'
                            CHECK(status IN ('active','inactive')),
            company_id      TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_provsched_provider
            ON healthclaw_provider_schedule(provider_id);
        CREATE INDEX IF NOT EXISTS idx_hc_provsched_day
            ON healthclaw_provider_schedule(day_of_week);

        -- Schedule block (vacation, meeting, override to block slots)
        CREATE TABLE IF NOT EXISTS healthclaw_schedule_block (
            id              TEXT PRIMARY KEY,
            provider_id     TEXT NOT NULL REFERENCES employee(id) ON DELETE RESTRICT,
            block_date      TEXT NOT NULL,
            start_time      TEXT,                -- NULL = all day
            end_time        TEXT,
            reason          TEXT NOT NULL CHECK(reason IN ('vacation','meeting','personal','maintenance','holiday','other')),
            notes           TEXT,
            company_id      TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_schedblock_provider
            ON healthclaw_schedule_block(provider_id);
        CREATE INDEX IF NOT EXISTS idx_hc_schedblock_date
            ON healthclaw_schedule_block(block_date);

        -- Appointments
        CREATE TABLE IF NOT EXISTS healthclaw_appointment (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            patient_id      TEXT NOT NULL REFERENCES healthclaw_patient(id) ON DELETE RESTRICT,
            provider_id     TEXT NOT NULL REFERENCES employee(id) ON DELETE RESTRICT,
            appointment_date TEXT NOT NULL,
            start_time      TEXT NOT NULL,        -- HH:MM
            end_time        TEXT NOT NULL,         -- HH:MM
            duration_minutes INTEGER NOT NULL DEFAULT 30,
            appointment_type TEXT NOT NULL DEFAULT 'follow_up'
                            CHECK(appointment_type IN (
                                'new_patient','follow_up','urgent','walk_in',
                                'telehealth','procedure','physical_exam','consultation'
                            )),
            chief_complaint TEXT,
            location        TEXT,
            status          TEXT NOT NULL DEFAULT 'scheduled'
                            CHECK(status IN ('scheduled','confirmed','checked_in','in_progress',
                                             'completed','cancelled','no_show','rescheduled')),
            cancellation_reason TEXT,
            check_in_time   TEXT,
            check_out_time  TEXT,
            notes           TEXT,
            company_id      TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_appt_company
            ON healthclaw_appointment(company_id);
        CREATE INDEX IF NOT EXISTS idx_hc_appt_patient
            ON healthclaw_appointment(patient_id);
        CREATE INDEX IF NOT EXISTS idx_hc_appt_provider
            ON healthclaw_appointment(provider_id);
        CREATE INDEX IF NOT EXISTS idx_hc_appt_date
            ON healthclaw_appointment(appointment_date);
        CREATE INDEX IF NOT EXISTS idx_hc_appt_status
            ON healthclaw_appointment(status);
        CREATE INDEX IF NOT EXISTS idx_hc_appt_type
            ON healthclaw_appointment(appointment_type);

        -- Appointment reminders
        CREATE TABLE IF NOT EXISTS healthclaw_appointment_reminder (
            id              TEXT PRIMARY KEY,
            appointment_id  TEXT NOT NULL REFERENCES healthclaw_appointment(id) ON DELETE RESTRICT,
            reminder_type   TEXT NOT NULL CHECK(reminder_type IN ('sms','email','phone','in_app')),
            scheduled_at    TEXT NOT NULL,
            sent_at         TEXT,
            status          TEXT NOT NULL DEFAULT 'pending'
                            CHECK(status IN ('pending','sent','failed','cancelled')),
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_reminder_appt
            ON healthclaw_appointment_reminder(appointment_id);
        CREATE INDEX IF NOT EXISTS idx_hc_reminder_status
            ON healthclaw_appointment_reminder(status);

        -- Waitlist for appointment slots
        CREATE TABLE IF NOT EXISTS healthclaw_waitlist (
            id              TEXT PRIMARY KEY,
            patient_id      TEXT NOT NULL REFERENCES healthclaw_patient(id) ON DELETE RESTRICT,
            provider_id     TEXT REFERENCES employee(id) ON DELETE RESTRICT,
            preferred_date_start TEXT,
            preferred_date_end   TEXT,
            preferred_time_start TEXT,
            preferred_time_end   TEXT,
            appointment_type TEXT NOT NULL DEFAULT 'follow_up',
            priority        TEXT NOT NULL DEFAULT 'normal'
                            CHECK(priority IN ('low','normal','high','urgent')),
            status          TEXT NOT NULL DEFAULT 'waiting'
                            CHECK(status IN ('waiting','offered','accepted','expired','cancelled')),
            notes           TEXT,
            company_id      TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_waitlist_patient
            ON healthclaw_waitlist(patient_id);
        CREATE INDEX IF NOT EXISTS idx_hc_waitlist_provider
            ON healthclaw_waitlist(provider_id);
        CREATE INDEX IF NOT EXISTS idx_hc_waitlist_status
            ON healthclaw_waitlist(status);
        CREATE INDEX IF NOT EXISTS idx_hc_waitlist_priority
            ON healthclaw_waitlist(priority);


        -- ==========================================================
        -- DOMAIN 3: CLINICAL (7 tables)
        -- ==========================================================

        -- Encounter — clinical visit record (hub for all clinical data)
        CREATE TABLE IF NOT EXISTS healthclaw_encounter (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            patient_id      TEXT NOT NULL REFERENCES healthclaw_patient(id) ON DELETE RESTRICT,
            appointment_id  TEXT REFERENCES healthclaw_appointment(id) ON DELETE RESTRICT,
            provider_id     TEXT NOT NULL REFERENCES employee(id) ON DELETE RESTRICT,
            encounter_date  TEXT NOT NULL,
            encounter_type  TEXT NOT NULL DEFAULT 'outpatient'
                            CHECK(encounter_type IN (
                                'outpatient','inpatient','emergency','observation',
                                'telehealth','home_visit'
                            )),
            chief_complaint TEXT,
            department      TEXT,
            room            TEXT,
            admission_date  TEXT,
            discharge_date  TEXT,
            discharge_disposition TEXT,
            status          TEXT NOT NULL DEFAULT 'open'
                            CHECK(status IN ('open','in_progress','completed','cancelled')),
            notes           TEXT,
            company_id      TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_encounter_company
            ON healthclaw_encounter(company_id);
        CREATE INDEX IF NOT EXISTS idx_hc_encounter_patient
            ON healthclaw_encounter(patient_id);
        CREATE INDEX IF NOT EXISTS idx_hc_encounter_appt
            ON healthclaw_encounter(appointment_id);
        CREATE INDEX IF NOT EXISTS idx_hc_encounter_provider
            ON healthclaw_encounter(provider_id);
        CREATE INDEX IF NOT EXISTS idx_hc_encounter_date
            ON healthclaw_encounter(encounter_date);
        CREATE INDEX IF NOT EXISTS idx_hc_encounter_status
            ON healthclaw_encounter(status);
        CREATE INDEX IF NOT EXISTS idx_hc_encounter_type
            ON healthclaw_encounter(encounter_type);

        -- Vital signs recording
        CREATE TABLE IF NOT EXISTS healthclaw_vitals (
            id              TEXT PRIMARY KEY,
            encounter_id    TEXT NOT NULL REFERENCES healthclaw_encounter(id) ON DELETE RESTRICT,
            patient_id      TEXT NOT NULL REFERENCES healthclaw_patient(id) ON DELETE RESTRICT,
            recorded_by_id  TEXT REFERENCES employee(id) ON DELETE RESTRICT,
            recorded_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            temperature     TEXT,           -- Fahrenheit
            temperature_site TEXT CHECK(temperature_site IN ('oral','tympanic','axillary','rectal','temporal')),
            heart_rate      INTEGER,        -- bpm
            respiratory_rate INTEGER,       -- breaths/min
            blood_pressure_systolic  INTEGER,
            blood_pressure_diastolic INTEGER,
            oxygen_saturation TEXT,         -- percentage
            weight          TEXT,           -- lbs
            height          TEXT,           -- inches
            bmi             TEXT,           -- calculated
            pain_level      INTEGER CHECK(pain_level BETWEEN 0 AND 10),
            notes           TEXT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_vitals_encounter
            ON healthclaw_vitals(encounter_id);
        CREATE INDEX IF NOT EXISTS idx_hc_vitals_patient
            ON healthclaw_vitals(patient_id);

        -- Diagnosis (ICD-10 codes stored as text)
        CREATE TABLE IF NOT EXISTS healthclaw_diagnosis (
            id              TEXT PRIMARY KEY,
            encounter_id    TEXT NOT NULL REFERENCES healthclaw_encounter(id) ON DELETE RESTRICT,
            patient_id      TEXT NOT NULL REFERENCES healthclaw_patient(id) ON DELETE RESTRICT,
            icd10_code      TEXT NOT NULL,
            description     TEXT NOT NULL,
            diagnosis_type  TEXT NOT NULL DEFAULT 'primary'
                            CHECK(diagnosis_type IN ('primary','secondary','admitting','discharge','rule_out')),
            status          TEXT NOT NULL DEFAULT 'active'
                            CHECK(status IN ('active','resolved','chronic','rule_out')),
            onset_date      TEXT,
            diagnosed_by_id TEXT REFERENCES employee(id) ON DELETE RESTRICT,
            notes           TEXT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_dx_encounter
            ON healthclaw_diagnosis(encounter_id);
        CREATE INDEX IF NOT EXISTS idx_hc_dx_patient
            ON healthclaw_diagnosis(patient_id);
        CREATE INDEX IF NOT EXISTS idx_hc_dx_icd10
            ON healthclaw_diagnosis(icd10_code);
        CREATE INDEX IF NOT EXISTS idx_hc_dx_type
            ON healthclaw_diagnosis(diagnosis_type);

        -- Prescription (medication orders)
        -- Merged from hcadv_prescription: medication_id, rx_number, quantity_prescribed,
        --   refills_authorized, refills_used, dea_number, rx_status, prescribed_date, expiry_date
        CREATE TABLE IF NOT EXISTS healthclaw_prescription (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            encounter_id    TEXT REFERENCES healthclaw_encounter(id) ON DELETE RESTRICT,
            patient_id      TEXT NOT NULL REFERENCES healthclaw_patient(id) ON DELETE RESTRICT,
            prescriber_id   TEXT NOT NULL REFERENCES employee(id) ON DELETE RESTRICT,
            medication_name TEXT,
            medication_id   TEXT,             -- from hcadv: links to healthclaw_medication
            ndc_code        TEXT,            -- National Drug Code
            rx_number       TEXT,             -- from hcadv: prescription number
            dosage          TEXT NOT NULL,    -- e.g., "500mg"
            frequency       TEXT NOT NULL,    -- e.g., "BID", "Q8H", "PRN"
            route           TEXT NOT NULL DEFAULT 'oral'
                            CHECK(route IN ('oral','iv','im','subq','topical','inhaled',
                                           'rectal','ophthalmic','otic','nasal','sublingual','transdermal','other')),
            quantity        TEXT NOT NULL DEFAULT '0',
            quantity_prescribed INTEGER NOT NULL DEFAULT 0, -- from hcadv
            refills         INTEGER NOT NULL DEFAULT 0,
            refills_authorized INTEGER NOT NULL DEFAULT 0, -- from hcadv
            refills_used    INTEGER NOT NULL DEFAULT 0,    -- from hcadv
            daw             INTEGER NOT NULL DEFAULT 0 CHECK(daw IN (0,1)),  -- dispense as written
            dea_number      TEXT,             -- from hcadv: DEA number for controlled substances
            start_date      TEXT,
            end_date        TEXT,
            prescribed_date TEXT,             -- from hcadv: date prescribed
            expiry_date     TEXT,             -- from hcadv: prescription expiry
            diagnosis_id    TEXT REFERENCES healthclaw_diagnosis(id) ON DELETE RESTRICT,
            controlled_schedule TEXT CHECK(controlled_schedule IN ('II','III','IV','V')),
            pharmacy_notes  TEXT,
            status          TEXT NOT NULL DEFAULT 'active'
                            CHECK(status IN ('active','completed','discontinued','cancelled','on_hold',
                                             'filled','partially_filled','expired')),
            rx_status       TEXT DEFAULT 'active'
                            CHECK(rx_status IN ('active','filled','partially_filled','expired','cancelled')),
            discontinued_reason TEXT,
            notes           TEXT,
            company_id      TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_rx_encounter
            ON healthclaw_prescription(encounter_id);
        CREATE INDEX IF NOT EXISTS idx_hc_rx_patient
            ON healthclaw_prescription(patient_id);
        CREATE INDEX IF NOT EXISTS idx_hc_rx_prescriber
            ON healthclaw_prescription(prescriber_id);
        CREATE INDEX IF NOT EXISTS idx_hc_rx_status
            ON healthclaw_prescription(status);

        -- Procedures performed (CPT codes stored as text)
        CREATE TABLE IF NOT EXISTS healthclaw_procedure (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            encounter_id    TEXT NOT NULL REFERENCES healthclaw_encounter(id) ON DELETE RESTRICT,
            patient_id      TEXT NOT NULL REFERENCES healthclaw_patient(id) ON DELETE RESTRICT,
            provider_id     TEXT NOT NULL REFERENCES employee(id) ON DELETE RESTRICT,
            cpt_code        TEXT NOT NULL,
            description     TEXT NOT NULL,
            procedure_date  TEXT NOT NULL,
            start_time      TEXT,
            end_time        TEXT,
            modifiers       TEXT,            -- CPT modifiers (e.g., "25,59")
            diagnosis_ids   TEXT,            -- JSON array of diagnosis IDs (linking Dx to procedure)
            anesthesia_type TEXT CHECK(anesthesia_type IN ('none','local','regional','general','sedation')),
            body_site       TEXT,
            laterality      TEXT CHECK(laterality IN ('left','right','bilateral','not_applicable')),
            status          TEXT NOT NULL DEFAULT 'completed'
                            CHECK(status IN ('planned','in_progress','completed','cancelled')),
            notes           TEXT,
            company_id      TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_proc_encounter
            ON healthclaw_procedure(encounter_id);
        CREATE INDEX IF NOT EXISTS idx_hc_proc_patient
            ON healthclaw_procedure(patient_id);
        CREATE INDEX IF NOT EXISTS idx_hc_proc_provider
            ON healthclaw_procedure(provider_id);
        CREATE INDEX IF NOT EXISTS idx_hc_proc_cpt
            ON healthclaw_procedure(cpt_code);
        CREATE INDEX IF NOT EXISTS idx_hc_proc_date
            ON healthclaw_procedure(procedure_date);

        -- SOAP / clinical notes
        CREATE TABLE IF NOT EXISTS healthclaw_clinical_note (
            id              TEXT PRIMARY KEY,
            encounter_id    TEXT NOT NULL REFERENCES healthclaw_encounter(id) ON DELETE RESTRICT,
            patient_id      TEXT NOT NULL REFERENCES healthclaw_patient(id) ON DELETE RESTRICT,
            author_id       TEXT NOT NULL REFERENCES employee(id) ON DELETE RESTRICT,
            note_type       TEXT NOT NULL DEFAULT 'progress'
                            CHECK(note_type IN ('progress','soap','hpi','consultation',
                                               'discharge','operative','procedure','nursing','other')),
            subjective      TEXT,            -- SOAP: S
            objective       TEXT,            -- SOAP: O
            assessment      TEXT,            -- SOAP: A
            plan            TEXT,            -- SOAP: P
            body            TEXT,            -- free-text for non-SOAP notes
            addendum        TEXT,
            signed_at       TEXT,
            cosigner_id     TEXT REFERENCES employee(id) ON DELETE RESTRICT,
            cosigned_at     TEXT,
            status          TEXT NOT NULL DEFAULT 'draft'
                            CHECK(status IN ('draft','signed','cosigned','amended','addended')),
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_note_encounter
            ON healthclaw_clinical_note(encounter_id);
        CREATE INDEX IF NOT EXISTS idx_hc_note_patient
            ON healthclaw_clinical_note(patient_id);
        CREATE INDEX IF NOT EXISTS idx_hc_note_author
            ON healthclaw_clinical_note(author_id);
        CREATE INDEX IF NOT EXISTS idx_hc_note_type
            ON healthclaw_clinical_note(note_type);

        -- Clinical orders (labs, imaging, referrals — generic order hub)
        CREATE TABLE IF NOT EXISTS healthclaw_order (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            encounter_id    TEXT NOT NULL REFERENCES healthclaw_encounter(id) ON DELETE RESTRICT,
            patient_id      TEXT NOT NULL REFERENCES healthclaw_patient(id) ON DELETE RESTRICT,
            ordering_provider_id TEXT NOT NULL REFERENCES employee(id) ON DELETE RESTRICT,
            order_type      TEXT NOT NULL CHECK(order_type IN ('lab','imaging','referral','procedure','other')),
            order_date      TEXT NOT NULL,
            priority        TEXT NOT NULL DEFAULT 'routine'
                            CHECK(priority IN ('stat','urgent','routine','elective')),
            clinical_indication TEXT,
            diagnosis_id    TEXT REFERENCES healthclaw_diagnosis(id) ON DELETE RESTRICT,
            status          TEXT NOT NULL DEFAULT 'pending'
                            CHECK(status IN ('pending','in_progress','completed','cancelled')),
            notes           TEXT,
            company_id      TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_order_encounter
            ON healthclaw_order(encounter_id);
        CREATE INDEX IF NOT EXISTS idx_hc_order_patient
            ON healthclaw_order(patient_id);
        CREATE INDEX IF NOT EXISTS idx_hc_order_provider
            ON healthclaw_order(ordering_provider_id);
        CREATE INDEX IF NOT EXISTS idx_hc_order_type
            ON healthclaw_order(order_type);
        CREATE INDEX IF NOT EXISTS idx_hc_order_status
            ON healthclaw_order(status);
        CREATE INDEX IF NOT EXISTS idx_hc_order_date
            ON healthclaw_order(order_date);


        -- ==========================================================
        -- DOMAIN 4: BILLING (6 tables)
        -- ==========================================================

        -- Fee schedule header (e.g., "Medicare Fee Schedule 2026")
        CREATE TABLE IF NOT EXISTS healthclaw_fee_schedule (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            description     TEXT,
            payer_type      TEXT CHECK(payer_type IN ('commercial','medicare','medicaid','self_pay','workers_comp','other')),
            effective_date  TEXT NOT NULL,
            expiration_date TEXT,
            status          TEXT NOT NULL DEFAULT 'active'
                            CHECK(status IN ('active','inactive','expired')),
            company_id      TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_feesched_company
            ON healthclaw_fee_schedule(company_id);
        CREATE INDEX IF NOT EXISTS idx_hc_feesched_status
            ON healthclaw_fee_schedule(status);

        -- Fee schedule line items (CPT code → price)
        CREATE TABLE IF NOT EXISTS healthclaw_fee_schedule_item (
            id              TEXT PRIMARY KEY,
            fee_schedule_id TEXT NOT NULL REFERENCES healthclaw_fee_schedule(id) ON DELETE RESTRICT,
            cpt_code        TEXT NOT NULL,
            description     TEXT,
            standard_charge TEXT NOT NULL DEFAULT '0',
            allowed_amount  TEXT NOT NULL DEFAULT '0',   -- payer's max allowable
            unit_count      INTEGER NOT NULL DEFAULT 1,
            modifier        TEXT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(fee_schedule_id, cpt_code, modifier)
        );
        CREATE INDEX IF NOT EXISTS idx_hc_fsitem_schedule
            ON healthclaw_fee_schedule_item(fee_schedule_id);
        CREATE INDEX IF NOT EXISTS idx_hc_fsitem_cpt
            ON healthclaw_fee_schedule_item(cpt_code);

        -- Individual charges (line items billed for services)
        -- Merged from hcadv_charge: procedure_code_id, icd10_codes, description, unit_fee, total_fee, quantity
        CREATE TABLE IF NOT EXISTS healthclaw_charge (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            encounter_id    TEXT REFERENCES healthclaw_encounter(id) ON DELETE RESTRICT,
            patient_id      TEXT NOT NULL REFERENCES healthclaw_patient(id) ON DELETE RESTRICT,
            procedure_id    TEXT REFERENCES healthclaw_procedure(id) ON DELETE RESTRICT,
            procedure_code_id TEXT,           -- from hcadv: links to healthclaw_procedure_code
            cpt_code        TEXT,
            modifiers       TEXT,
            diagnosis_ids   TEXT,            -- JSON array of ICD-10 pointers
            icd10_codes     TEXT DEFAULT '[]', -- from hcadv: JSON array of ICD-10 codes
            description     TEXT,             -- from hcadv: charge description
            units           INTEGER NOT NULL DEFAULT 1,
            quantity        INTEGER NOT NULL DEFAULT 1, -- from hcadv: synonym for units
            charge_amount   TEXT NOT NULL DEFAULT '0',
            unit_fee        TEXT NOT NULL DEFAULT '0.00', -- from hcadv: per-unit fee
            total_fee       TEXT NOT NULL DEFAULT '0.00', -- from hcadv: quantity * unit_fee
            allowed_amount  TEXT NOT NULL DEFAULT '0',
            fee_schedule_id TEXT REFERENCES healthclaw_fee_schedule(id) ON DELETE RESTRICT,
            service_date    TEXT NOT NULL,
            provider_id     TEXT NOT NULL REFERENCES employee(id) ON DELETE RESTRICT,
            place_of_service TEXT NOT NULL DEFAULT '11',  -- CMS POS code (11=Office)
            charge_status   TEXT NOT NULL DEFAULT 'unbilled'
                            CHECK(charge_status IN ('unbilled','billed','paid','adjusted','void')),
            notes           TEXT,
            company_id      TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_charge_company
            ON healthclaw_charge(company_id);
        CREATE INDEX IF NOT EXISTS idx_hc_charge_encounter
            ON healthclaw_charge(encounter_id);
        CREATE INDEX IF NOT EXISTS idx_hc_charge_patient
            ON healthclaw_charge(patient_id);
        CREATE INDEX IF NOT EXISTS idx_hc_charge_status
            ON healthclaw_charge(charge_status);
        CREATE INDEX IF NOT EXISTS idx_hc_charge_date
            ON healthclaw_charge(service_date);
        CREATE INDEX IF NOT EXISTS idx_hc_charge_cpt
            ON healthclaw_charge(cpt_code);

        -- Insurance claim header
        -- Merged from hcadv_claim: payer_name, payer_id_number, policy_number, group_number,
        --   claim_number, charge_ids, total_charged, total_adjustment, submitted_date, response_date
        CREATE TABLE IF NOT EXISTS healthclaw_claim (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            patient_id      TEXT NOT NULL REFERENCES healthclaw_patient(id) ON DELETE RESTRICT,
            insurance_id    TEXT REFERENCES healthclaw_patient_insurance(id) ON DELETE RESTRICT,
            encounter_id    TEXT REFERENCES healthclaw_encounter(id) ON DELETE RESTRICT,
            payer_name      TEXT,             -- from hcadv: payer name (when no insurance_id)
            payer_id_number TEXT,             -- from hcadv: payer EDI identifier
            policy_number   TEXT,             -- from hcadv: insurance policy number
            group_number    TEXT,             -- from hcadv: insurance group number
            claim_number    TEXT,             -- from hcadv: external claim tracking number
            claim_date      TEXT NOT NULL,
            charge_ids      TEXT NOT NULL DEFAULT '[]', -- from hcadv: JSON array of charge IDs
            total_charge    TEXT NOT NULL DEFAULT '0',
            total_charged   TEXT NOT NULL DEFAULT '0.00', -- from hcadv: alias for total_charge
            total_allowed   TEXT NOT NULL DEFAULT '0',
            total_paid      TEXT NOT NULL DEFAULT '0',
            total_adjustment TEXT NOT NULL DEFAULT '0.00', -- from hcadv: total adjustments
            patient_responsibility TEXT NOT NULL DEFAULT '0',
            adjustment_amount TEXT NOT NULL DEFAULT '0',
            billing_provider_id TEXT REFERENCES employee(id) ON DELETE RESTRICT,
            rendering_provider_id TEXT REFERENCES employee(id) ON DELETE RESTRICT,
            place_of_service TEXT NOT NULL DEFAULT '11',
            claim_type      TEXT NOT NULL DEFAULT 'professional'
                            CHECK(claim_type IN ('professional','institutional','dental')),
            filing_indicator TEXT,           -- e.g., "CI" for commercial insurance
            prior_auth_id   TEXT REFERENCES healthclaw_prior_auth(id) ON DELETE RESTRICT,
            sales_invoice_id TEXT REFERENCES sales_invoice(id) ON DELETE RESTRICT,
            claim_status    TEXT NOT NULL DEFAULT 'draft'
                            CHECK(claim_status IN ('draft','submitted','accepted','denied',
                                             'partially_paid','paid','appealed','void')),
            submitted_date  TEXT,             -- from hcadv: date claim was submitted
            response_date   TEXT,             -- from hcadv: date payer responded
            denial_reason   TEXT,
            denial_category TEXT CHECK (denial_category IN ('CO','PR','OA','PI')),
            denial_code     TEXT,
            denial_date     TEXT,
            appeal_deadline TEXT,
            appeal_submitted_date TEXT,
            appeal_method   TEXT CHECK (appeal_method IN ('written','phone','online')),
            appeal_reference TEXT,
            appeal_outcome  TEXT CHECK (appeal_outcome IN ('pending','overturned','upheld','partial')),
            appeal_resolved_date TEXT,
            appeal_amount_recovered TEXT,
            notes           TEXT,
            company_id      TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_claim_company
            ON healthclaw_claim(company_id);
        CREATE INDEX IF NOT EXISTS idx_hc_claim_patient
            ON healthclaw_claim(patient_id);
        CREATE INDEX IF NOT EXISTS idx_hc_claim_insurance
            ON healthclaw_claim(insurance_id);
        CREATE INDEX IF NOT EXISTS idx_hc_claim_encounter
            ON healthclaw_claim(encounter_id);
        CREATE INDEX IF NOT EXISTS idx_hc_claim_status
            ON healthclaw_claim(claim_status);
        CREATE INDEX IF NOT EXISTS idx_hc_claim_payer
            ON healthclaw_claim(payer_name);
        CREATE INDEX IF NOT EXISTS idx_hc_claim_number
            ON healthclaw_claim(claim_number);
        CREATE INDEX IF NOT EXISTS idx_hc_claim_date
            ON healthclaw_claim(claim_date);
        CREATE INDEX IF NOT EXISTS idx_hc_claim_invoice
            ON healthclaw_claim(sales_invoice_id);

        -- Claim line items
        CREATE TABLE IF NOT EXISTS healthclaw_claim_line (
            id              TEXT PRIMARY KEY,
            claim_id        TEXT NOT NULL REFERENCES healthclaw_claim(id) ON DELETE RESTRICT,
            charge_id       TEXT NOT NULL REFERENCES healthclaw_charge(id) ON DELETE RESTRICT,
            line_number     INTEGER NOT NULL,
            cpt_code        TEXT NOT NULL,
            modifiers       TEXT,
            diagnosis_pointers TEXT,         -- e.g., "1,2" referencing claim-level Dx list
            units           INTEGER NOT NULL DEFAULT 1,
            charge_amount   TEXT NOT NULL DEFAULT '0',
            allowed_amount  TEXT NOT NULL DEFAULT '0',
            paid_amount     TEXT NOT NULL DEFAULT '0',
            adjustment_amount TEXT NOT NULL DEFAULT '0',
            patient_amount  TEXT NOT NULL DEFAULT '0',
            denial_reason   TEXT,
            remark_codes    TEXT,            -- ANSI remark codes
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_claimline_claim
            ON healthclaw_claim_line(claim_id);
        CREATE INDEX IF NOT EXISTS idx_hc_claimline_charge
            ON healthclaw_claim_line(charge_id);

        -- Insurance / patient payment posting
        -- Merged from hcadv_payment_posting: charge_id, allowed_amount, paid_amount, adjustment, patient_responsibility
        CREATE TABLE IF NOT EXISTS healthclaw_payment_posting (
            id              TEXT PRIMARY KEY,
            claim_id        TEXT REFERENCES healthclaw_claim(id) ON DELETE RESTRICT,
            charge_id       TEXT REFERENCES healthclaw_charge(id) ON DELETE RESTRICT, -- from hcadv
            patient_id      TEXT NOT NULL REFERENCES healthclaw_patient(id) ON DELETE RESTRICT,
            posting_type    TEXT CHECK(posting_type IN ('insurance_payment','patient_payment','adjustment','refund','write_off')),
            posting_date    TEXT NOT NULL,
            amount          TEXT NOT NULL DEFAULT '0',
            allowed_amount  TEXT NOT NULL DEFAULT '0.00', -- from hcadv
            paid_amount     TEXT NOT NULL DEFAULT '0.00', -- from hcadv
            adjustment      TEXT NOT NULL DEFAULT '0.00', -- from hcadv
            patient_responsibility TEXT NOT NULL DEFAULT '0.00', -- from hcadv
            check_number    TEXT,
            payer_name      TEXT,
            payment_method  TEXT CHECK(payment_method IN ('check','eft','cash','credit_card','ach','other')),
            payment_entry_id TEXT REFERENCES payment_entry(id) ON DELETE RESTRICT,
            eob_date        TEXT,            -- explanation of benefits date
            notes           TEXT,
            company_id      TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_posting_claim
            ON healthclaw_payment_posting(claim_id);
        CREATE INDEX IF NOT EXISTS idx_hc_posting_patient
            ON healthclaw_payment_posting(patient_id);
        CREATE INDEX IF NOT EXISTS idx_hc_posting_type
            ON healthclaw_payment_posting(posting_type);
        CREATE INDEX IF NOT EXISTS idx_hc_posting_date
            ON healthclaw_payment_posting(posting_date);
        CREATE INDEX IF NOT EXISTS idx_hc_posting_payment
            ON healthclaw_payment_posting(payment_entry_id);


        -- ==========================================================
        -- DOMAIN 5: INVENTORY / PHARMACY (3 tables)
        -- ==========================================================

        -- Drug formulary header
        CREATE TABLE IF NOT EXISTS healthclaw_formulary (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            description     TEXT,
            effective_date  TEXT NOT NULL,
            expiration_date TEXT,
            status          TEXT NOT NULL DEFAULT 'active'
                            CHECK(status IN ('active','inactive','expired')),
            company_id      TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_formulary_company
            ON healthclaw_formulary(company_id);
        CREATE INDEX IF NOT EXISTS idx_hc_formulary_status
            ON healthclaw_formulary(status);

        -- Formulary items (extends ERPClaw item with NDC, controlled schedule)
        CREATE TABLE IF NOT EXISTS healthclaw_formulary_item (
            id              TEXT PRIMARY KEY,
            formulary_id    TEXT NOT NULL REFERENCES healthclaw_formulary(id) ON DELETE RESTRICT,
            item_id         TEXT NOT NULL REFERENCES item(id) ON DELETE RESTRICT,
            ndc_code        TEXT,            -- National Drug Code
            drug_class      TEXT,
            generic_name    TEXT,
            brand_name      TEXT,
            strength        TEXT,            -- e.g., "500mg"
            dosage_form     TEXT,            -- e.g., "tablet", "capsule", "injection"
            route           TEXT,
            controlled_schedule TEXT CHECK(controlled_schedule IN ('II','III','IV','V')),
            therapeutic_class TEXT,
            formulary_tier  TEXT CHECK(formulary_tier IN ('1','2','3','4','specialty')),
            requires_prior_auth INTEGER NOT NULL DEFAULT 0 CHECK(requires_prior_auth IN (0,1)),
            max_daily_dose  TEXT,
            status          TEXT NOT NULL DEFAULT 'active'
                            CHECK(status IN ('active','inactive','recalled')),
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(formulary_id, item_id)
        );
        CREATE INDEX IF NOT EXISTS idx_hc_fitem_formulary
            ON healthclaw_formulary_item(formulary_id);
        CREATE INDEX IF NOT EXISTS idx_hc_fitem_item
            ON healthclaw_formulary_item(item_id);
        CREATE INDEX IF NOT EXISTS idx_hc_fitem_ndc
            ON healthclaw_formulary_item(ndc_code);

        -- Medication dispensing record
        CREATE TABLE IF NOT EXISTS healthclaw_dispensing (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            prescription_id TEXT NOT NULL REFERENCES healthclaw_prescription(id) ON DELETE RESTRICT,
            patient_id      TEXT NOT NULL REFERENCES healthclaw_patient(id) ON DELETE RESTRICT,
            formulary_item_id TEXT REFERENCES healthclaw_formulary_item(id) ON DELETE RESTRICT,
            item_id         TEXT REFERENCES item(id) ON DELETE RESTRICT,
            dispensed_by_id TEXT NOT NULL REFERENCES employee(id) ON DELETE RESTRICT,
            dispensed_date  TEXT NOT NULL,
            quantity        TEXT NOT NULL DEFAULT '0',
            lot_number      TEXT,
            expiration_date TEXT,
            ndc_code        TEXT,
            directions      TEXT,
            refill_number   INTEGER NOT NULL DEFAULT 0,
            status          TEXT NOT NULL DEFAULT 'dispensed'
                            CHECK(status IN ('dispensed','returned','recalled','voided')),
            notes           TEXT,
            company_id      TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_disp_rx
            ON healthclaw_dispensing(prescription_id);
        CREATE INDEX IF NOT EXISTS idx_hc_disp_patient
            ON healthclaw_dispensing(patient_id);
        CREATE INDEX IF NOT EXISTS idx_hc_disp_date
            ON healthclaw_dispensing(dispensed_date);
        CREATE INDEX IF NOT EXISTS idx_hc_disp_item
            ON healthclaw_dispensing(item_id);


        -- ==========================================================
        -- DOMAIN 6: LAB / DIAGNOSTICS (5 tables)
        -- ==========================================================

        -- Lab order header
        -- Merged from hcadv_lab_order: ordering_provider, lab_test_id, order_status, clinical_notes, collected_at, completed_at
        CREATE TABLE IF NOT EXISTS healthclaw_lab_order (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            order_id        TEXT REFERENCES healthclaw_order(id) ON DELETE RESTRICT,
            encounter_id    TEXT REFERENCES healthclaw_encounter(id) ON DELETE RESTRICT,
            patient_id      TEXT NOT NULL REFERENCES healthclaw_patient(id) ON DELETE RESTRICT,
            ordering_provider_id TEXT REFERENCES employee(id) ON DELETE RESTRICT,
            ordering_provider TEXT,           -- from hcadv: provider name (when no FK)
            lab_test_id     TEXT,             -- from hcadv: links to healthclaw_lab_test
            order_date      TEXT NOT NULL,
            priority        TEXT NOT NULL DEFAULT 'routine'
                            CHECK(priority IN ('stat','urgent','routine')),
            fasting_required INTEGER NOT NULL DEFAULT 0 CHECK(fasting_required IN (0,1)),
            clinical_indication TEXT,
            clinical_notes  TEXT,             -- from hcadv: clinical notes
            specimen_type   TEXT,            -- e.g., "blood", "urine", "tissue"
            collection_date TEXT,
            received_date   TEXT,
            collected_at    TEXT,             -- from hcadv: collection timestamp
            completed_at    TEXT,             -- from hcadv: completion timestamp
            order_status    TEXT NOT NULL DEFAULT 'ordered'
                            CHECK(order_status IN ('ordered','collected','received','in_progress',
                                             'completed','cancelled')),
            notes           TEXT,
            company_id      TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_labord_company
            ON healthclaw_lab_order(company_id);
        CREATE INDEX IF NOT EXISTS idx_hc_labord_encounter
            ON healthclaw_lab_order(encounter_id);
        CREATE INDEX IF NOT EXISTS idx_hc_labord_patient
            ON healthclaw_lab_order(patient_id);
        CREATE INDEX IF NOT EXISTS idx_hc_labord_provider
            ON healthclaw_lab_order(ordering_provider_id);
        CREATE INDEX IF NOT EXISTS idx_hc_labord_status
            ON healthclaw_lab_order(order_status);
        CREATE INDEX IF NOT EXISTS idx_hc_labord_date
            ON healthclaw_lab_order(order_date);

        -- Individual lab tests within an order
        -- Merged from hcadv_lab_test: company_id, loinc_code, category, specimen_type,
        --   reference_range, unit, turnaround_hours, base_price, is_active, notes
        CREATE TABLE IF NOT EXISTS healthclaw_lab_test (
            id              TEXT PRIMARY KEY,
            lab_order_id    TEXT REFERENCES healthclaw_lab_order(id) ON DELETE RESTRICT,
            company_id      TEXT REFERENCES company(id) ON DELETE RESTRICT, -- from hcadv
            test_code       TEXT,             -- LOINC or internal code
            test_name       TEXT NOT NULL,
            loinc_code      TEXT,             -- from hcadv: LOINC code
            cpt_code        TEXT,
            category        TEXT,             -- from hcadv: test category
            specimen_type   TEXT,             -- from hcadv: specimen type
            reference_range TEXT,             -- from hcadv: expected range
            unit            TEXT,             -- from hcadv: measurement unit
            turnaround_hours INTEGER,         -- from hcadv: expected turnaround
            base_price      TEXT NOT NULL DEFAULT '0.00', -- from hcadv: test price
            is_active       INTEGER NOT NULL DEFAULT 1,   -- from hcadv
            status          TEXT NOT NULL DEFAULT 'pending'
                            CHECK(status IN ('pending','in_progress','completed','cancelled')),
            notes           TEXT,             -- from hcadv
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_labtest_order
            ON healthclaw_lab_test(lab_order_id);
        CREATE INDEX IF NOT EXISTS idx_hc_labtest_code
            ON healthclaw_lab_test(test_code);

        -- Lab test results
        -- Merged from hcadv_lab_result: company_id, lab_order_id, patient_id, result_value,
        --   result_unit, reference_range, is_abnormal, is_critical, performed_by, verified_by, result_notes
        CREATE TABLE IF NOT EXISTS healthclaw_lab_result (
            id              TEXT PRIMARY KEY,
            lab_test_id     TEXT NOT NULL REFERENCES healthclaw_lab_test(id) ON DELETE RESTRICT,
            lab_order_id    TEXT,             -- from hcadv: direct link to lab order
            company_id      TEXT REFERENCES company(id) ON DELETE RESTRICT, -- from hcadv
            patient_id      TEXT,             -- from hcadv: patient reference
            component_name  TEXT,             -- e.g., "Hemoglobin", "WBC"
            value           TEXT,
            result_value    TEXT,             -- from hcadv: result value
            unit            TEXT,             -- e.g., "g/dL", "cells/mcL"
            result_unit     TEXT,             -- from hcadv: result unit
            reference_low   TEXT,
            reference_high  TEXT,
            reference_range TEXT,             -- from hcadv: combined reference range
            flag            TEXT CHECK(flag IN ('normal','low','high','critical_low','critical_high','abnormal')),
            is_abnormal     INTEGER NOT NULL DEFAULT 0, -- from hcadv
            is_critical     INTEGER NOT NULL DEFAULT 0, -- from hcadv
            result_date     TEXT NOT NULL,
            performed_by_id TEXT REFERENCES employee(id) ON DELETE RESTRICT,
            verified_by_id  TEXT REFERENCES employee(id) ON DELETE RESTRICT,
            performed_by    TEXT,             -- from hcadv: performer name (when no FK)
            verified_by     TEXT,             -- from hcadv: verifier name (when no FK)
            notes           TEXT,
            result_notes    TEXT,             -- from hcadv: result-specific notes
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP  -- from hcadv
        );
        CREATE INDEX IF NOT EXISTS idx_hc_labres_test
            ON healthclaw_lab_result(lab_test_id);
        CREATE INDEX IF NOT EXISTS idx_hc_labres_flag
            ON healthclaw_lab_result(flag);

        -- Imaging / radiology order
        CREATE TABLE IF NOT EXISTS healthclaw_imaging_order (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            order_id        TEXT REFERENCES healthclaw_order(id) ON DELETE RESTRICT,
            encounter_id    TEXT NOT NULL REFERENCES healthclaw_encounter(id) ON DELETE RESTRICT,
            patient_id      TEXT NOT NULL REFERENCES healthclaw_patient(id) ON DELETE RESTRICT,
            ordering_provider_id TEXT NOT NULL REFERENCES employee(id) ON DELETE RESTRICT,
            modality        TEXT NOT NULL CHECK(modality IN (
                'xray','ct','mri','ultrasound','mammography',
                'fluoroscopy','nuclear','pet','dexa','other'
            )),
            body_part       TEXT NOT NULL,
            laterality      TEXT CHECK(laterality IN ('left','right','bilateral','not_applicable')),
            cpt_code        TEXT,
            order_date      TEXT NOT NULL,
            priority        TEXT NOT NULL DEFAULT 'routine'
                            CHECK(priority IN ('stat','urgent','routine')),
            clinical_indication TEXT,
            contrast        INTEGER NOT NULL DEFAULT 0 CHECK(contrast IN (0,1)),
            status          TEXT NOT NULL DEFAULT 'ordered'
                            CHECK(status IN ('ordered','scheduled','in_progress','completed',
                                             'read','cancelled')),
            scheduled_date  TEXT,
            notes           TEXT,
            company_id      TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_imgord_company
            ON healthclaw_imaging_order(company_id);
        CREATE INDEX IF NOT EXISTS idx_hc_imgord_encounter
            ON healthclaw_imaging_order(encounter_id);
        CREATE INDEX IF NOT EXISTS idx_hc_imgord_patient
            ON healthclaw_imaging_order(patient_id);
        CREATE INDEX IF NOT EXISTS idx_hc_imgord_modality
            ON healthclaw_imaging_order(modality);
        CREATE INDEX IF NOT EXISTS idx_hc_imgord_status
            ON healthclaw_imaging_order(status);

        -- Imaging results / radiology report
        CREATE TABLE IF NOT EXISTS healthclaw_imaging_result (
            id              TEXT PRIMARY KEY,
            imaging_order_id TEXT NOT NULL REFERENCES healthclaw_imaging_order(id) ON DELETE RESTRICT,
            radiologist_id  TEXT REFERENCES employee(id) ON DELETE RESTRICT,
            findings        TEXT,
            impression      TEXT,
            recommendation  TEXT,
            critical_finding INTEGER NOT NULL DEFAULT 0 CHECK(critical_finding IN (0,1)),
            report_date     TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'preliminary'
                            CHECK(status IN ('preliminary','final','addended','corrected')),
            addendum        TEXT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_imgres_order
            ON healthclaw_imaging_result(imaging_order_id);
        CREATE INDEX IF NOT EXISTS idx_hc_imgres_radiologist
            ON healthclaw_imaging_result(radiologist_id);
        CREATE INDEX IF NOT EXISTS idx_hc_imgres_status
            ON healthclaw_imaging_result(status);


        -- ==========================================================
        -- DOMAIN 7: REFERRALS / PRIOR AUTH (3 tables)
        -- ==========================================================

        -- Patient referral
        CREATE TABLE IF NOT EXISTS healthclaw_referral (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            patient_id      TEXT NOT NULL REFERENCES healthclaw_patient(id) ON DELETE RESTRICT,
            encounter_id    TEXT REFERENCES healthclaw_encounter(id) ON DELETE RESTRICT,
            referring_provider_id TEXT NOT NULL REFERENCES employee(id) ON DELETE RESTRICT,
            referred_to_provider TEXT NOT NULL,   -- external provider name (may not be in employee table)
            referred_to_specialty TEXT,
            referred_to_facility TEXT,
            referred_to_phone TEXT,
            referred_to_fax TEXT,
            referral_date   TEXT NOT NULL,
            expiration_date TEXT,
            reason          TEXT NOT NULL,
            diagnosis_id    TEXT REFERENCES healthclaw_diagnosis(id) ON DELETE RESTRICT,
            priority        TEXT NOT NULL DEFAULT 'routine'
                            CHECK(priority IN ('stat','urgent','routine','elective')),
            insurance_id    TEXT REFERENCES healthclaw_patient_insurance(id) ON DELETE RESTRICT,
            prior_auth_required INTEGER NOT NULL DEFAULT 0 CHECK(prior_auth_required IN (0,1)),
            prior_auth_id   TEXT REFERENCES healthclaw_prior_auth(id) ON DELETE RESTRICT,
            status          TEXT NOT NULL DEFAULT 'pending'
                            CHECK(status IN ('pending','sent','accepted','declined',
                                             'completed','expired','cancelled')),
            notes           TEXT,
            company_id      TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_ref_company
            ON healthclaw_referral(company_id);
        CREATE INDEX IF NOT EXISTS idx_hc_ref_patient
            ON healthclaw_referral(patient_id);
        CREATE INDEX IF NOT EXISTS idx_hc_ref_encounter
            ON healthclaw_referral(encounter_id);
        CREATE INDEX IF NOT EXISTS idx_hc_ref_referring
            ON healthclaw_referral(referring_provider_id);
        CREATE INDEX IF NOT EXISTS idx_hc_ref_status
            ON healthclaw_referral(status);
        CREATE INDEX IF NOT EXISTS idx_hc_ref_date
            ON healthclaw_referral(referral_date);

        -- Prior authorization request
        CREATE TABLE IF NOT EXISTS healthclaw_prior_auth (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            patient_id      TEXT NOT NULL REFERENCES healthclaw_patient(id) ON DELETE RESTRICT,
            insurance_id    TEXT NOT NULL REFERENCES healthclaw_patient_insurance(id) ON DELETE RESTRICT,
            requesting_provider_id TEXT NOT NULL REFERENCES employee(id) ON DELETE RESTRICT,
            auth_number     TEXT,            -- payer-assigned auth number
            service_type    TEXT NOT NULL CHECK(service_type IN (
                'procedure','imaging','medication','dme','inpatient',
                'outpatient','referral','therapy','other'
            )),
            cpt_codes       TEXT,            -- JSON array of CPT codes
            icd10_codes     TEXT,            -- JSON array of ICD-10 codes
            description     TEXT NOT NULL,
            units_requested INTEGER NOT NULL DEFAULT 1,
            units_approved  INTEGER,
            request_date    TEXT NOT NULL,
            effective_date  TEXT,
            expiration_date TEXT,
            decision_date   TEXT,
            status          TEXT NOT NULL DEFAULT 'pending'
                            CHECK(status IN ('pending','approved','denied','partially_approved',
                                             'expired','cancelled','appealed')),
            denial_reason   TEXT,
            appeal_deadline TEXT,
            notes           TEXT,
            company_id      TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_auth_company
            ON healthclaw_prior_auth(company_id);
        CREATE INDEX IF NOT EXISTS idx_hc_auth_patient
            ON healthclaw_prior_auth(patient_id);
        CREATE INDEX IF NOT EXISTS idx_hc_auth_insurance
            ON healthclaw_prior_auth(insurance_id);
        CREATE INDEX IF NOT EXISTS idx_hc_auth_status
            ON healthclaw_prior_auth(status);
        CREATE INDEX IF NOT EXISTS idx_hc_auth_number
            ON healthclaw_prior_auth(auth_number);
        CREATE INDEX IF NOT EXISTS idx_hc_auth_dates
            ON healthclaw_prior_auth(effective_date, expiration_date);

        -- Authorization usage tracking (tracks visits/units used against an auth)
        CREATE TABLE IF NOT EXISTS healthclaw_auth_usage (
            id              TEXT PRIMARY KEY,
            prior_auth_id   TEXT NOT NULL REFERENCES healthclaw_prior_auth(id) ON DELETE RESTRICT,
            encounter_id    TEXT REFERENCES healthclaw_encounter(id) ON DELETE RESTRICT,
            claim_id        TEXT REFERENCES healthclaw_claim(id) ON DELETE RESTRICT,
            usage_date      TEXT NOT NULL,
            units_used      INTEGER NOT NULL DEFAULT 1,
            notes           TEXT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_hc_authuse_auth
            ON healthclaw_auth_usage(prior_auth_id);
        CREATE INDEX IF NOT EXISTS idx_hc_authuse_encounter
            ON healthclaw_auth_usage(encounter_id);
    """)

    # ══════════════════════════════════════════════════════════════
    # HealthClaw Advanced Domain Tables (5 tables, healthclaw_ prefix)
    # Medication, Dispense Log, Procedure Code, Drug Interaction,
    # Controlled Substance Log
    # (7 former hcadv_ duplicates merged into core tables above)
    # ══════════════════════════════════════════════════════════════

    # -- healthclaw_medication (renamed from hcadv_medication) --
    conn.execute("""
        CREATE TABLE IF NOT EXISTS healthclaw_medication (
            id                  TEXT PRIMARY KEY,
            company_id          TEXT NOT NULL REFERENCES company(id),
            name                TEXT NOT NULL,
            generic_name        TEXT,
            ndc_code            TEXT,
            dea_schedule        TEXT NOT NULL DEFAULT 'non-scheduled'
                                CHECK(dea_schedule IN ('I','II','III','IV','V','non-scheduled')),
            dosage_form         TEXT,
            strength            TEXT,
            manufacturer        TEXT,
            unit_price          TEXT NOT NULL DEFAULT '0.00',
            quantity_on_hand    INTEGER NOT NULL DEFAULT 0,
            reorder_level       INTEGER NOT NULL DEFAULT 0,
            is_active           INTEGER NOT NULL DEFAULT 1,
            notes               TEXT,
            created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hc_med_company ON healthclaw_medication(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hc_med_name ON healthclaw_medication(name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hc_med_ndc ON healthclaw_medication(ndc_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hc_med_schedule ON healthclaw_medication(dea_schedule)")

    # -- healthclaw_dispense_log (renamed from hcadv_dispense_log) --
    conn.execute("""
        CREATE TABLE IF NOT EXISTS healthclaw_dispense_log (
            id                  TEXT PRIMARY KEY,
            company_id          TEXT NOT NULL REFERENCES company(id),
            prescription_id     TEXT NOT NULL,
            medication_id       TEXT NOT NULL REFERENCES healthclaw_medication(id),
            dispensed_by        TEXT NOT NULL,
            quantity_dispensed  INTEGER NOT NULL DEFAULT 0,
            dispense_date       TEXT NOT NULL,
            is_refill           INTEGER NOT NULL DEFAULT 0,
            lot_number          TEXT,
            expiration_date     TEXT,
            notes               TEXT,
            created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hc_disp_company ON healthclaw_dispense_log(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hc_displog_rx ON healthclaw_dispense_log(prescription_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hc_displog_med ON healthclaw_dispense_log(medication_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hc_displog_date ON healthclaw_dispense_log(dispense_date)")

    # -- healthclaw_procedure_code (renamed from hcadv_procedure_code) --
    conn.execute("""
        CREATE TABLE IF NOT EXISTS healthclaw_procedure_code (
            id                  TEXT PRIMARY KEY,
            company_id          TEXT NOT NULL REFERENCES company(id),
            code                TEXT NOT NULL,
            code_type           TEXT NOT NULL DEFAULT 'CPT'
                                CHECK(code_type IN ('CPT','ICD-10','HCPCS')),
            description         TEXT NOT NULL,
            category            TEXT,
            default_fee         TEXT NOT NULL DEFAULT '0.00',
            is_active           INTEGER NOT NULL DEFAULT 1,
            notes               TEXT,
            created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hc_pc_company ON healthclaw_procedure_code(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hc_pc_code ON healthclaw_procedure_code(code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hc_pc_type ON healthclaw_procedure_code(code_type)")

    # -- healthclaw_drug_interaction (renamed from hcadv_drug_interaction) --
    conn.execute("""
        CREATE TABLE IF NOT EXISTS healthclaw_drug_interaction (
            id                  TEXT PRIMARY KEY,
            company_id          TEXT NOT NULL REFERENCES company(id),
            medication_a_id     TEXT NOT NULL REFERENCES healthclaw_medication(id),
            medication_b_id     TEXT NOT NULL REFERENCES healthclaw_medication(id),
            severity            TEXT NOT NULL DEFAULT 'moderate'
                                CHECK(severity IN ('minor','moderate','major','contraindicated')),
            description         TEXT NOT NULL,
            recommendation      TEXT,
            created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hc_di_company ON healthclaw_drug_interaction(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hc_di_med_a ON healthclaw_drug_interaction(medication_a_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hc_di_med_b ON healthclaw_drug_interaction(medication_b_id)")

    # -- healthclaw_controlled_substance_log (renamed from hcadv_controlled_substance_log) --
    conn.execute("""
        CREATE TABLE IF NOT EXISTS healthclaw_controlled_substance_log (
            id                  TEXT PRIMARY KEY,
            company_id          TEXT NOT NULL REFERENCES company(id),
            medication_id       TEXT NOT NULL REFERENCES healthclaw_medication(id),
            prescription_id     TEXT,
            action_type         TEXT NOT NULL
                                CHECK(action_type IN ('received','dispensed','destroyed','returned','adjusted')),
            quantity            INTEGER NOT NULL,
            dea_number          TEXT,
            performed_by        TEXT NOT NULL,
            witness             TEXT,
            log_date            TEXT NOT NULL,
            notes               TEXT,
            created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hc_csl_company ON healthclaw_controlled_substance_log(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hc_csl_med ON healthclaw_controlled_substance_log(medication_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hc_csl_rx ON healthclaw_controlled_substance_log(prescription_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hc_csl_date ON healthclaw_controlled_substance_log(log_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hc_csl_type ON healthclaw_controlled_substance_log(action_type)")

    # ══════════════════════════════════════════════════════════════
    # DOMAIN 12: PAYER MANAGEMENT (Phase 1 RCM)
    # ══════════════════════════════════════════════════════════════

    # -- healthclaw_payer --
    conn.execute("""
        CREATE TABLE IF NOT EXISTS healthclaw_payer (
            id                  TEXT PRIMARY KEY,
            company_id          TEXT NOT NULL REFERENCES company(id),
            name                TEXT NOT NULL,
            payer_type          TEXT NOT NULL CHECK (payer_type IN ('commercial','medicare','medicaid','tricare','workers_comp','self_pay','other')),
            edi_payer_id        TEXT,
            electronic_filing_id TEXT,
            address             TEXT,
            city                TEXT,
            state               TEXT,
            zip                 TEXT,
            phone               TEXT,
            claims_address      TEXT,
            claims_city         TEXT,
            claims_state        TEXT,
            claims_zip          TEXT,
            submission_method   TEXT NOT NULL DEFAULT 'electronic' CHECK (submission_method IN ('electronic','paper','portal')),
            timely_filing_days  INTEGER DEFAULT 365,
            era_enrollment      TEXT NOT NULL DEFAULT 'not_enrolled' CHECK (era_enrollment IN ('enrolled','not_enrolled','pending')),
            default_fee_schedule_id TEXT,
            notes               TEXT,
            status              TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive')),
            created_at          TEXT DEFAULT (datetime('now')),
            updated_at          TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_healthclaw_payer_company ON healthclaw_payer(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_healthclaw_payer_edi ON healthclaw_payer(edi_payer_id)")

    # -- healthclaw_eligibility_check --
    conn.execute("""
        CREATE TABLE IF NOT EXISTS healthclaw_eligibility_check (
            id                    TEXT PRIMARY KEY,
            patient_id            TEXT NOT NULL REFERENCES healthclaw_patient(id),
            patient_insurance_id  TEXT NOT NULL REFERENCES healthclaw_patient_insurance(id),
            payer_id              TEXT REFERENCES healthclaw_payer(id),
            check_date            TEXT NOT NULL,
            check_method          TEXT NOT NULL DEFAULT 'manual' CHECK (check_method IN ('manual','electronic','phone')),
            coverage_status       TEXT NOT NULL CHECK (coverage_status IN ('active','inactive','termed','pending','unknown')),
            copay                 TEXT,
            deductible            TEXT,
            deductible_met        TEXT,
            coinsurance_pct       TEXT,
            out_of_pocket_max     TEXT,
            oop_met               TEXT,
            plan_begin_date       TEXT,
            plan_end_date         TEXT,
            in_network            INTEGER DEFAULT 1,
            prior_auth_required   INTEGER DEFAULT 0,
            notes                 TEXT,
            checked_by            TEXT,
            created_at            TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_healthclaw_eligibility_patient ON healthclaw_eligibility_check(patient_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_healthclaw_eligibility_date ON healthclaw_eligibility_check(check_date)")

    # -- healthclaw_era_file (ERA/835 Electronic Remittance Processing) --
    conn.execute("""
        CREATE TABLE IF NOT EXISTS healthclaw_era_file (
            id              TEXT PRIMARY KEY,
            company_id      TEXT NOT NULL,
            file_name       TEXT,
            payer_id        TEXT,
            received_date   TEXT NOT NULL,
            check_number    TEXT,
            check_amount    TEXT,
            eft_trace       TEXT,
            claim_count     INTEGER DEFAULT 0,
            matched_count   INTEGER DEFAULT 0,
            posted_amount   TEXT DEFAULT '0',
            status          TEXT NOT NULL DEFAULT 'received' CHECK (status IN ('received','processing','posted','partial','error')),
            posted_by       TEXT,
            posted_at       TEXT,
            notes           TEXT,
            created_at      TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (company_id) REFERENCES company(id),
            FOREIGN KEY (payer_id) REFERENCES healthclaw_payer(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_healthclaw_era_file_company ON healthclaw_era_file(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_healthclaw_era_file_date ON healthclaw_era_file(received_date)")

    # -- healthclaw_era_claim_detail --
    conn.execute("""
        CREATE TABLE IF NOT EXISTS healthclaw_era_claim_detail (
            id                  TEXT PRIMARY KEY,
            era_file_id         TEXT NOT NULL,
            claim_id            TEXT,
            patient_name        TEXT,
            patient_id          TEXT,
            claim_number        TEXT,
            service_date        TEXT,
            billed_amount       TEXT DEFAULT '0',
            allowed_amount      TEXT DEFAULT '0',
            paid_amount         TEXT DEFAULT '0',
            patient_responsibility TEXT DEFAULT '0',
            adjustment_amount   TEXT DEFAULT '0',
            adjustment_codes    TEXT,
            remark_codes        TEXT,
            match_status        TEXT NOT NULL DEFAULT 'unmatched' CHECK (match_status IN ('matched','unmatched','partial','denied')),
            auto_posted         INTEGER DEFAULT 0,
            created_at          TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (era_file_id) REFERENCES healthclaw_era_file(id),
            FOREIGN KEY (claim_id) REFERENCES healthclaw_claim(id),
            FOREIGN KEY (patient_id) REFERENCES healthclaw_patient(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_healthclaw_era_detail_file ON healthclaw_era_claim_detail(era_file_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_healthclaw_era_detail_claim ON healthclaw_era_claim_detail(claim_id)")

    # ==========================================================
    # DOMAIN 13: COMPLIANCE (Phase 2 — HIPAA, No Surprises Act, CMS)
    # ==========================================================

    # -- PHI Access Audit Log — HIPAA 45 C.F.R. 164.312(b) --
    conn.execute("""
        CREATE TABLE IF NOT EXISTS healthclaw_phi_access_log (
            id              TEXT PRIMARY KEY,
            user_id         TEXT,
            patient_id      TEXT NOT NULL,
            access_type     TEXT NOT NULL CHECK (access_type IN ('view','edit','print','export','delete')),
            data_category   TEXT NOT NULL CHECK (data_category IN ('demographics','clinical','billing','insurance','medications','lab_results','imaging','notes','all')),
            action_name     TEXT,
            resource_id     TEXT,
            ip_address      TEXT,
            user_agent      TEXT,
            access_reason   TEXT,
            break_the_glass INTEGER DEFAULT 0,
            created_at      TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (patient_id) REFERENCES healthclaw_patient(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_healthclaw_phi_patient ON healthclaw_phi_access_log(patient_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_healthclaw_phi_user ON healthclaw_phi_access_log(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_healthclaw_phi_date ON healthclaw_phi_access_log(created_at)")

    # -- Good Faith Estimate — No Surprises Act (2022) --
    conn.execute("""
        CREATE TABLE IF NOT EXISTS healthclaw_good_faith_estimate (
            id              TEXT PRIMARY KEY,
            company_id      TEXT NOT NULL,
            patient_id      TEXT NOT NULL,
            provider_id     TEXT,
            estimate_date   TEXT NOT NULL,
            procedure_codes TEXT,
            diagnosis_codes TEXT,
            items           TEXT,
            total_estimate  TEXT NOT NULL DEFAULT '0',
            facility_fee    TEXT DEFAULT '0',
            provider_fee    TEXT DEFAULT '0',
            insurance_applied INTEGER DEFAULT 0,
            payer_id        TEXT,
            estimated_insurance_payment TEXT DEFAULT '0',
            estimated_patient_responsibility TEXT DEFAULT '0',
            valid_until     TEXT,
            status          TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','provided','expired','superseded')),
            provided_at     TEXT,
            notes           TEXT,
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (company_id) REFERENCES company(id),
            FOREIGN KEY (patient_id) REFERENCES healthclaw_patient(id),
            FOREIGN KEY (payer_id) REFERENCES healthclaw_payer(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_healthclaw_gfe_patient ON healthclaw_good_faith_estimate(patient_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_healthclaw_gfe_date ON healthclaw_good_faith_estimate(estimate_date)")

    # -- MIPS Quality Measures — CMS Merit-based Incentive Payment System --
    conn.execute("""
        CREATE TABLE IF NOT EXISTS healthclaw_quality_measure (
            id                  TEXT PRIMARY KEY,
            company_id          TEXT NOT NULL,
            measure_id          TEXT NOT NULL,
            name                TEXT NOT NULL,
            category            TEXT NOT NULL CHECK (category IN ('quality','improvement_activities','promoting_interoperability','cost')),
            description         TEXT,
            numerator_criteria  TEXT,
            denominator_criteria TEXT,
            exclusion_criteria  TEXT,
            measure_type        TEXT DEFAULT 'process' CHECK (measure_type IN ('process','outcome','structure','efficiency')),
            reporting_period    TEXT,
            benchmark           TEXT,
            status              TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','retired')),
            created_at          TEXT DEFAULT (datetime('now')),
            updated_at          TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (company_id) REFERENCES company(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_healthclaw_qm_company ON healthclaw_quality_measure(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_healthclaw_qm_measure ON healthclaw_quality_measure(measure_id)")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS healthclaw_quality_measure_result (
            id                  TEXT PRIMARY KEY,
            measure_id          TEXT NOT NULL,
            provider_id         TEXT,
            reporting_period    TEXT NOT NULL,
            numerator           INTEGER DEFAULT 0,
            denominator         INTEGER DEFAULT 0,
            exclusions          INTEGER DEFAULT 0,
            performance_rate    TEXT,
            benchmark           TEXT,
            points_earned       TEXT DEFAULT '0',
            status              TEXT NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress','calculated','submitted','accepted')),
            calculated_at       TEXT,
            notes               TEXT,
            created_at          TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (measure_id) REFERENCES healthclaw_quality_measure(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_healthclaw_qmr_measure ON healthclaw_quality_measure_result(measure_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_healthclaw_qmr_period ON healthclaw_quality_measure_result(reporting_period)")

    # ── Register naming series for all existing companies ────────
    companies = conn.execute("SELECT id FROM company").fetchall()
    naming_series = [
        ("healthclaw_patient",         "PAT"),
        ("healthclaw_patient_insurance", "INS"),
        ("healthclaw_appointment",     "APPT"),
        ("healthclaw_encounter",       "ENC"),
        ("healthclaw_prescription",    "RX"),
        ("healthclaw_procedure",       "PROC"),
        ("healthclaw_order",           "ORD"),
        ("healthclaw_charge",          "CHG"),
        ("healthclaw_claim",           "CLM"),
        ("healthclaw_dispensing",      "DISP"),
        ("healthclaw_lab_order",       "LAB"),
        ("healthclaw_imaging_order",   "IMG"),
        ("healthclaw_referral",        "REF"),
        ("healthclaw_prior_auth",      "AUTH"),
    ]
    for company_row in companies:
        company_id = company_row[0]
        for entity_type, prefix in naming_series:
            existing = conn.execute(
                "SELECT 1 FROM naming_series WHERE entity_type = ? AND prefix = ? AND company_id = ?",
                (entity_type, prefix, company_id)
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO naming_series (id, entity_type, prefix, current_value, company_id) "
                    "VALUES (?, ?, ?, 0, ?)",
                    (str(uuid.uuid4()), entity_type, prefix, company_id)
                )

    conn.commit()

    # ── Verify table creation ────────────────────────────────────
    tables_after = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'healthclaw_%'"
    ).fetchall()]
    indexes_after = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_hc_%'"
    ).fetchall()]

    conn.close()
    print(f"{DISPLAY_NAME} schema created in {db_path}", file=sys.stderr)
    print(f"  Tables: {len(tables_after)} (35 core + 5 advanced, all healthclaw_ prefix)", file=sys.stderr)
    print(f"  Indexes: {len(indexes_after)}", file=sys.stderr)
    print(f"  Naming series: {len(naming_series)} per company ({len(companies)} companies)", file=sys.stderr)


if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB_PATH
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    create_healthclaw_tables(db_path)

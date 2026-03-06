# HealthClaw — AI-Native Healthcare Practice Management

Modular healthcare practice management built as [OpenClaw](https://clawhub.com) skills. HealthClaw provides a complete clinical and administrative platform across 5 packages: a core module covering patients, appointments, clinical documentation, billing, lab orders, inventory, and referrals, plus 4 specialty expansions for dental, veterinary, mental health, and home health practices. All data is stored in a single shared SQLite database with full financial integration through ERPClaw's general ledger.

## Skills

| Package | Actions | Description |
|---------|---------|-------------|
| `healthclaw` | 98 | Core: patients, appointments, providers, clinical notes, prescriptions, billing, insurance, lab orders, medical inventory, referrals |
| `healthclaw-dental` | 12 | Dental: treatment plans, procedures, tooth charts, dental imaging |
| `healthclaw-vet` | 12 | Veterinary: patients (animals), owners, vaccinations, species-specific care |
| `healthclaw-mental` | 14 | Mental health: therapy sessions, treatment plans, assessments, progress notes |
| `healthclaw-homehealth` | 12 | Home health: visits, care plans, aide assignments, patient assessments |
| **Total** | **148** | |

## Requirements

- [OpenClaw](https://clawhub.com) runtime
- [ERPClaw](https://github.com/avansaber/erpclaw) foundation skills:
  - `erpclaw-setup` — database initialization and shared library
  - `erpclaw-gl` — general ledger for financial postings
  - `erpclaw-selling` — customer and invoice management
  - `erpclaw-payments` — payment processing

## Installation

Install each skill through ClawHub or clone this repo and copy the skill directories to your OpenClaw skills folder:

```bash
# Core
cp -r healthclaw/ ~/clawd/skills/healthclaw/

# Expansions (install any combination)
cp -r healthclaw-dental/ ~/clawd/skills/healthclaw-dental/
cp -r healthclaw-vet/ ~/clawd/skills/healthclaw-vet/
cp -r healthclaw-mental/ ~/clawd/skills/healthclaw-mental/
cp -r healthclaw-homehealth/ ~/clawd/skills/healthclaw-homehealth/
```

Initialize the database tables for each installed skill:

```bash
python healthclaw/init_db.py
python healthclaw-dental/init_db.py   # if installed
python healthclaw-vet/init_db.py      # if installed
python healthclaw-mental/init_db.py   # if installed
python healthclaw-homehealth/init_db.py  # if installed
```

## License

MIT License. Copyright (c) 2026 AvanSaber / Nikhil Jathar.

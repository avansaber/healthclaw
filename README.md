# HealthClaw

Healthcare management suite for [ERPClaw](https://github.com/avansaber/erpclaw). <!-- SYNC:value:group.healthclaw.module_count -->5<!-- /SYNC --> modules covering clinical practice management, dental, veterinary, mental health, and home health. <!-- SYNC:value:group.healthclaw.total_actions -->284<!-- /SYNC --> actions total with HIPAA-friendly architecture.

## Modules

### Core (`healthclaw`)
Hospital and multi-department healthcare ERP. <!-- SYNC:value:module.healthclaw.actions -->234<!-- /SYNC --> actions across 11 domains -- patients, appointments, clinical documentation, billing, inventory, lab, referrals, pharmacy, advanced lab, advanced billing, and advanced reports. ICD-10/CPT coding, insurance claims, prior authorization, pharmacy/DEA compliance, and full clinical documentation.

### Dental (`healthclaw-dental`)
Tooth charts, CDT-coded procedures, multi-phase treatment plans, and periodontal charting with trend comparison.

### Veterinary (`healthclaw-vet`)
Animal patient records, boarding/kennel management, weight-based medication dosing, and multi-owner linking.

### Mental Health (`healthclaw-mental`)
Therapy sessions, standardized assessments (PHQ-9, GAD-7, AUDIT), treatment goals, and group therapy with auto-scoring and trend comparison.

### Home Health (`healthclaw-homehealth`)
Home visits, 485 care plans, OASIS assessments, and aide assignment management for home health agencies.

## Installation

Requires [ERPClaw](https://github.com/avansaber/erpclaw) core. Install the core module first, then add specialties:

```
install-module healthclaw
install-module healthclaw-dental
install-module healthclaw-vet
install-module healthclaw-mental
install-module healthclaw-homehealth
```

Or ask naturally:

```
"I'm opening a medical practice"
"Set me up for a dental office"
"I run a veterinary clinic"
```

## Links

- **Source**: [github.com/avansaber/healthclaw](https://github.com/avansaber/healthclaw)
- **ERPClaw Core**: [github.com/avansaber/erpclaw](https://github.com/avansaber/erpclaw)
- **Website**: [erpclaw.ai](https://www.erpclaw.ai)

## License

GNU General Public License v3 -- Copyright (c) 2026 AvanSaber / Nikhil Jathar

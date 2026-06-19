# Medical Domain Ontology — Minimal Core
Inspired by Human Disease Ontology (DOID). Schema version: v1.0

## Node Labels (Entity Types — use these as your NER type set)

| Label | Description | Key Properties |
|---|---|---|
| `Disease` | A disease/disorder entity | name, doid_code, domain, schema_version, source_chunk_ids |
| `Symptom` | Observable sign/symptom | name, domain, schema_version, source_chunk_ids |
| `BodySite` | Anatomical location | name, domain, schema_version, source_chunk_ids |
| `Drug` | Medication/treatment substance | name, domain, schema_version, source_chunk_ids |
| `Procedure` | Medical/surgical procedure | name, domain, schema_version, source_chunk_ids |
| `RiskFactor` | Factor increasing disease risk | name, domain, schema_version, source_chunk_ids |
| `Pathogen` | Causative organism (virus/bacteria) | name, domain, schema_version, source_chunk_ids |
| `Specialty` | Medical specialty/field | name, domain, schema_version, source_chunk_ids |
| `Patient` | Patient/person receiving care | patient_id, domain, schema_version, source_chunk_ids |
| `Doctor` | Physician/healthcare provider | name, specialty, domain, schema_version, source_chunk_ids |
| `Hospital` | Healthcare facility | name, location, domain, schema_version, source_chunk_ids |

## Relationship Types (constrained predicate set)

| Relationship | From → To | Meaning |
|---|---|---|
| `IS_A` | Disease → Disease | Disease subclass hierarchy |
| `LOCATED_IN` | Disease → BodySite | Disease affects this body site |
| `HAS_SYMPTOM` | Disease → Symptom | Disease presents with symptom |
| `TREATED_BY` | Disease → Drug | Drug treats disease |
| `TREATED_BY_PROCEDURE` | Disease → Procedure | Procedure treats disease |
| `CAUSED_BY` | Disease → Pathogen | Pathogen causes disease |
| `RISK_FACTOR_FOR` | RiskFactor → Disease | Risk factor increases disease likelihood |
| `MANAGED_BY` | Disease → Specialty | Specialty manages this disease |
| `CONTRAINDICATED_FOR` | Drug → Disease | Drug should not be used for disease |
| `DIAGNOSED_WITH` | Patient → Disease | Patient diagnosed with disease |
| `PRESCRIBED` | Doctor → Drug | Doctor prescribed drug |
| `TREATED_AT` | Patient → Hospital | Patient treated at hospital |
| `WORKS_AT` | Doctor → Hospital | Doctor affiliated with hospital |
| `PERFORMED_BY` | Procedure → Doctor | Procedure performed by doctor |
| `UNDERWENT` | Patient → Procedure | Patient underwent procedure |
| `SPECIALIZES_IN` | Doctor → Specialty | Doctor specialty |

## Disease Hierarchy (top-level, DOID-style — IS_A chains)

```
Disease (root)
├── InfectiousDisease
│   ├── BacterialInfection
│   └── ViralInfection
├── CardiovascularDisease
│   ├── Hypertension
│   └── CoronaryArteryDisease
├── EndocrineDisease
│   ├── DiabetesMellitusType1
│   └── DiabetesMellitusType2
├── RespiratoryDisease
│   ├── Asthma
│   └── Pneumonia
├── NeurologicalDisease
│   ├── Migraine
│   └── Epilepsy
├── MusculoskeletalDisease
│   └── Osteoarthritis
└── NeoplasticDisease
    ├── BenignNeoplasm
    └── MalignantNeoplasm
```

## Notes for your NER/extraction step
- Treat the 8 node labels above as the closed entity-type set the NER model outputs.
- Treat the 9 relationship types as the closed predicate set the triple-extraction LLM must map to — reject/flag any triple whose predicate doesn't match one of these.
- `domain` property is always `"medical"` for these nodes — used by Phase 5 RBAC filtering.
- `schema_version` lets Phase 6 detect which nodes need re-extraction when you update this file.

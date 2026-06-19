# Legal Domain Ontology — Minimal Core
Inspired by LKIF-Core. Schema version: v1.0

## Node Labels (Entity Types — use these as your NER type set)

| Label | Description | Key Properties |
|---|---|---|
| `LegalNorm` | A law, statute, article, regulation | name, citation, domain, schema_version, source_chunk_ids |
| `LegalCase` | A court case/precedent | name, case_number, domain, schema_version, source_chunk_ids |
| `LegalRole` | A role a party can hold (plaintiff, defendant, judge, etc.) | name, domain, schema_version, source_chunk_ids |
| `LegalAct` | An action with legal effect (contract, filing, appeal) | name, domain, schema_version, source_chunk_ids |
| `LegalRight` | A right held by a party | name, domain, schema_version, source_chunk_ids |
| `LegalObligation` | A duty/obligation imposed on a party | name, domain, schema_version, source_chunk_ids |
| `Court` | A judicial body | name, jurisdiction, domain, schema_version, source_chunk_ids |
| `Jurisdiction` | A legal territory/system (e.g. federal, state) | name, domain, schema_version, source_chunk_ids |
| `Sanction` | A penalty/punishment | name, domain, schema_version, source_chunk_ids |

## Relationship Types (constrained predicate set)

| Relationship | From → To | Meaning |
|---|---|---|
| `IS_A` | LegalNorm → LegalNorm | Norm subclass/specialization hierarchy |
| `GOVERNED_BY` | LegalAct → LegalNorm | Act is governed by this norm |
| `CITES` | LegalCase → LegalCase | Case cites precedent |
| `CITES_NORM` | LegalCase → LegalNorm | Case relies on/interprets this norm |
| `DECIDED_BY` | LegalCase → Court | Case decided by this court |
| `HAS_JURISDICTION` | Court → Jurisdiction | Court operates within jurisdiction |
| `GRANTS_RIGHT` | LegalNorm → LegalRight | Norm grants this right |
| `IMPOSES_OBLIGATION` | LegalNorm → LegalObligation | Norm imposes this obligation |
| `HELD_BY` | LegalRight → LegalRole | Right is held by this role |
| `OWED_BY` | LegalObligation → LegalRole | Obligation is owed by this role |
| `PENALIZED_BY` | LegalObligation → Sanction | Breach of obligation triggers sanction |
| `APPLIES_IN` | LegalNorm → Jurisdiction | Norm is applicable within jurisdiction |

## Norm Hierarchy (top-level, LKIF-style — IS_A chains)

```
LegalNorm (root)
├── Constitution
├── Statute
│   ├── CivilStatute
│   ├── CriminalStatute
│   └── AdministrativeStatute
├── Regulation
├── Contract
└── Precedent
```

## Notes for your NER/extraction step
- Treat the 9 node labels above as the closed entity-type set the NER model outputs.
- Treat the 12 relationship types as the closed predicate set the triple-extraction LLM must map to.
- `domain` property is always `"legal"` for these nodes — used by Phase 5 RBAC filtering.
- `schema_version` lets Phase 6 detect which nodes need re-extraction when you update this file.

// ============================================================
// MULTI-DOMAIN RAG — ONTOLOGY SEED SCRIPT (Medical + Legal)
// Schema version: v1.0
// Target: Apache AGE (executed via seed_graph.py, NOT run raw)
//
// NOTE: AGE has no CREATE CONSTRAINT support like Neo4j, so every
// node statement below uses MERGE keyed on (name, domain) instead
// of CREATE. This makes the seed script idempotent/safe to re-run,
// which matters for Phase 6 (schema versioning / re-extraction).
//
// This file is NOT executed directly with cypher-shell or any AGE
// client as one block — seed_graph.py splits it into individual
// statements and wraps each one in the SQL cypher() call AGE
// requires, inside a single transaction.
// ============================================================

// ============================================================
// MEDICAL DOMAIN — DISEASE NODES
// ============================================================

MERGE (d0:Disease {name:"Disease", domain:"medical"}) SET d0.schema_version="v1.0", d0.source_chunk_ids=[]
MERGE (d1:Disease {name:"InfectiousDisease", domain:"medical"}) SET d1.schema_version="v1.0", d1.source_chunk_ids=[]
MERGE (d2:Disease {name:"BacterialInfection", domain:"medical"}) SET d2.schema_version="v1.0", d2.source_chunk_ids=[]
MERGE (d3:Disease {name:"ViralInfection", domain:"medical"}) SET d3.schema_version="v1.0", d3.source_chunk_ids=[]
MERGE (d4:Disease {name:"CardiovascularDisease", domain:"medical"}) SET d4.schema_version="v1.0", d4.source_chunk_ids=[]
MERGE (d5:Disease {name:"Hypertension", domain:"medical"}) SET d5.schema_version="v1.0", d5.source_chunk_ids=[]
MERGE (d6:Disease {name:"CoronaryArteryDisease", domain:"medical"}) SET d6.schema_version="v1.0", d6.source_chunk_ids=[]
MERGE (d7:Disease {name:"EndocrineDisease", domain:"medical"}) SET d7.schema_version="v1.0", d7.source_chunk_ids=[]
MERGE (d8:Disease {name:"DiabetesMellitusType1", domain:"medical"}) SET d8.schema_version="v1.0", d8.source_chunk_ids=[]
MERGE (d9:Disease {name:"DiabetesMellitusType2", domain:"medical"}) SET d9.schema_version="v1.0", d9.source_chunk_ids=[]
MERGE (d10:Disease {name:"RespiratoryDisease", domain:"medical"}) SET d10.schema_version="v1.0", d10.source_chunk_ids=[]
MERGE (d11:Disease {name:"Asthma", domain:"medical"}) SET d11.schema_version="v1.0", d11.source_chunk_ids=[]
MERGE (d12:Disease {name:"Pneumonia", domain:"medical"}) SET d12.schema_version="v1.0", d12.source_chunk_ids=[]
MERGE (d13:Disease {name:"NeurologicalDisease", domain:"medical"}) SET d13.schema_version="v1.0", d13.source_chunk_ids=[]
MERGE (d14:Disease {name:"Migraine", domain:"medical"}) SET d14.schema_version="v1.0", d14.source_chunk_ids=[]
MERGE (d15:Disease {name:"Epilepsy", domain:"medical"}) SET d15.schema_version="v1.0", d15.source_chunk_ids=[]
MERGE (d16:Disease {name:"MusculoskeletalDisease", domain:"medical"}) SET d16.schema_version="v1.0", d16.source_chunk_ids=[]
MERGE (d17:Disease {name:"Osteoarthritis", domain:"medical"}) SET d17.schema_version="v1.0", d17.source_chunk_ids=[]
MERGE (d18:Disease {name:"NeoplasticDisease", domain:"medical"}) SET d18.schema_version="v1.0", d18.source_chunk_ids=[]
MERGE (d19:Disease {name:"BenignNeoplasm", domain:"medical"}) SET d19.schema_version="v1.0", d19.source_chunk_ids=[]
MERGE (d20:Disease {name:"MalignantNeoplasm", domain:"medical"}) SET d20.schema_version="v1.0", d20.source_chunk_ids=[]

// Disease hierarchy (IS_A) — MATCH both ends then MERGE the edge, idempotent
MATCH (a:Disease {name:"InfectiousDisease", domain:"medical"}), (b:Disease {name:"Disease", domain:"medical"}) MERGE (a)-[:IS_A]->(b)
MATCH (a:Disease {name:"BacterialInfection", domain:"medical"}), (b:Disease {name:"InfectiousDisease", domain:"medical"}) MERGE (a)-[:IS_A]->(b)
MATCH (a:Disease {name:"ViralInfection", domain:"medical"}), (b:Disease {name:"InfectiousDisease", domain:"medical"}) MERGE (a)-[:IS_A]->(b)
MATCH (a:Disease {name:"CardiovascularDisease", domain:"medical"}), (b:Disease {name:"Disease", domain:"medical"}) MERGE (a)-[:IS_A]->(b)
MATCH (a:Disease {name:"Hypertension", domain:"medical"}), (b:Disease {name:"CardiovascularDisease", domain:"medical"}) MERGE (a)-[:IS_A]->(b)
MATCH (a:Disease {name:"CoronaryArteryDisease", domain:"medical"}), (b:Disease {name:"CardiovascularDisease", domain:"medical"}) MERGE (a)-[:IS_A]->(b)
MATCH (a:Disease {name:"EndocrineDisease", domain:"medical"}), (b:Disease {name:"Disease", domain:"medical"}) MERGE (a)-[:IS_A]->(b)
MATCH (a:Disease {name:"DiabetesMellitusType1", domain:"medical"}), (b:Disease {name:"EndocrineDisease", domain:"medical"}) MERGE (a)-[:IS_A]->(b)
MATCH (a:Disease {name:"DiabetesMellitusType2", domain:"medical"}), (b:Disease {name:"EndocrineDisease", domain:"medical"}) MERGE (a)-[:IS_A]->(b)
MATCH (a:Disease {name:"RespiratoryDisease", domain:"medical"}), (b:Disease {name:"Disease", domain:"medical"}) MERGE (a)-[:IS_A]->(b)
MATCH (a:Disease {name:"Asthma", domain:"medical"}), (b:Disease {name:"RespiratoryDisease", domain:"medical"}) MERGE (a)-[:IS_A]->(b)
MATCH (a:Disease {name:"Pneumonia", domain:"medical"}), (b:Disease {name:"RespiratoryDisease", domain:"medical"}) MERGE (a)-[:IS_A]->(b)
MATCH (a:Disease {name:"NeurologicalDisease", domain:"medical"}), (b:Disease {name:"Disease", domain:"medical"}) MERGE (a)-[:IS_A]->(b)
MATCH (a:Disease {name:"Migraine", domain:"medical"}), (b:Disease {name:"NeurologicalDisease", domain:"medical"}) MERGE (a)-[:IS_A]->(b)
MATCH (a:Disease {name:"Epilepsy", domain:"medical"}), (b:Disease {name:"NeurologicalDisease", domain:"medical"}) MERGE (a)-[:IS_A]->(b)
MATCH (a:Disease {name:"MusculoskeletalDisease", domain:"medical"}), (b:Disease {name:"Disease", domain:"medical"}) MERGE (a)-[:IS_A]->(b)
MATCH (a:Disease {name:"Osteoarthritis", domain:"medical"}), (b:Disease {name:"MusculoskeletalDisease", domain:"medical"}) MERGE (a)-[:IS_A]->(b)
MATCH (a:Disease {name:"NeoplasticDisease", domain:"medical"}), (b:Disease {name:"Disease", domain:"medical"}) MERGE (a)-[:IS_A]->(b)
MATCH (a:Disease {name:"BenignNeoplasm", domain:"medical"}), (b:Disease {name:"NeoplasticDisease", domain:"medical"}) MERGE (a)-[:IS_A]->(b)
MATCH (a:Disease {name:"MalignantNeoplasm", domain:"medical"}), (b:Disease {name:"NeoplasticDisease", domain:"medical"}) MERGE (a)-[:IS_A]->(b)

// ---------- Supporting medical entity types (sample instances) ----------
MERGE (s1:Symptom {name:"Fever", domain:"medical"}) SET s1.schema_version="v1.0", s1.source_chunk_ids=[]
MERGE (s2:Symptom {name:"Cough", domain:"medical"}) SET s2.schema_version="v1.0", s2.source_chunk_ids=[]
MERGE (s3:Symptom {name:"ChestPain", domain:"medical"}) SET s3.schema_version="v1.0", s3.source_chunk_ids=[]
MERGE (s4:Symptom {name:"Headache", domain:"medical"}) SET s4.schema_version="v1.0", s4.source_chunk_ids=[]

MERGE (b1:BodySite {name:"Lung", domain:"medical"}) SET b1.schema_version="v1.0", b1.source_chunk_ids=[]
MERGE (b2:BodySite {name:"Heart", domain:"medical"}) SET b2.schema_version="v1.0", b2.source_chunk_ids=[]
MERGE (b3:BodySite {name:"Pancreas", domain:"medical"}) SET b3.schema_version="v1.0", b3.source_chunk_ids=[]
MERGE (b4:BodySite {name:"Brain", domain:"medical"}) SET b4.schema_version="v1.0", b4.source_chunk_ids=[]

MERGE (dr1:Drug {name:"Amoxicillin", domain:"medical"}) SET dr1.schema_version="v1.0", dr1.source_chunk_ids=[]
MERGE (dr2:Drug {name:"Insulin", domain:"medical"}) SET dr2.schema_version="v1.0", dr2.source_chunk_ids=[]
MERGE (dr3:Drug {name:"Lisinopril", domain:"medical"}) SET dr3.schema_version="v1.0", dr3.source_chunk_ids=[]
MERGE (dr4:Drug {name:"Ibuprofen", domain:"medical"}) SET dr4.schema_version="v1.0", dr4.source_chunk_ids=[]

MERGE (p1:Procedure {name:"Angioplasty", domain:"medical"}) SET p1.schema_version="v1.0", p1.source_chunk_ids=[]
MERGE (p2:Procedure {name:"JointReplacement", domain:"medical"}) SET p2.schema_version="v1.0", p2.source_chunk_ids=[]

MERGE (rf1:RiskFactor {name:"Smoking", domain:"medical"}) SET rf1.schema_version="v1.0", rf1.source_chunk_ids=[]
MERGE (rf2:RiskFactor {name:"Obesity", domain:"medical"}) SET rf2.schema_version="v1.0", rf2.source_chunk_ids=[]

MERGE (path1:Pathogen {name:"StreptococcusPneumoniae", domain:"medical"}) SET path1.schema_version="v1.0", path1.source_chunk_ids=[]
MERGE (path2:Pathogen {name:"InfluenzaVirus", domain:"medical"}) SET path2.schema_version="v1.0", path2.source_chunk_ids=[]

MERGE (sp1:Specialty {name:"Cardiology", domain:"medical"}) SET sp1.schema_version="v1.0", sp1.source_chunk_ids=[]
MERGE (sp2:Specialty {name:"Endocrinology", domain:"medical"}) SET sp2.schema_version="v1.0", sp2.source_chunk_ids=[]
MERGE (sp3:Specialty {name:"Pulmonology", domain:"medical"}) SET sp3.schema_version="v1.0", sp3.source_chunk_ids=[]
MERGE (sp4:Specialty {name:"Neurology", domain:"medical"}) SET sp4.schema_version="v1.0", sp4.source_chunk_ids=[]

// Sample relationships demonstrating each predicate type
MATCH (a:Disease {name:"Pneumonia", domain:"medical"}), (b:Symptom {name:"Fever", domain:"medical"}) MERGE (a)-[:HAS_SYMPTOM]->(b)
MATCH (a:Disease {name:"Pneumonia", domain:"medical"}), (b:Symptom {name:"Cough", domain:"medical"}) MERGE (a)-[:HAS_SYMPTOM]->(b)
MATCH (a:Disease {name:"CoronaryArteryDisease", domain:"medical"}), (b:Symptom {name:"ChestPain", domain:"medical"}) MERGE (a)-[:HAS_SYMPTOM]->(b)
MATCH (a:Disease {name:"Migraine", domain:"medical"}), (b:Symptom {name:"Headache", domain:"medical"}) MERGE (a)-[:HAS_SYMPTOM]->(b)

MATCH (a:Disease {name:"Pneumonia", domain:"medical"}), (b:BodySite {name:"Lung", domain:"medical"}) MERGE (a)-[:LOCATED_IN]->(b)
MATCH (a:Disease {name:"CoronaryArteryDisease", domain:"medical"}), (b:BodySite {name:"Heart", domain:"medical"}) MERGE (a)-[:LOCATED_IN]->(b)
MATCH (a:Disease {name:"DiabetesMellitusType1", domain:"medical"}), (b:BodySite {name:"Pancreas", domain:"medical"}) MERGE (a)-[:LOCATED_IN]->(b)
MATCH (a:Disease {name:"Migraine", domain:"medical"}), (b:BodySite {name:"Brain", domain:"medical"}) MERGE (a)-[:LOCATED_IN]->(b)

MATCH (a:Disease {name:"Pneumonia", domain:"medical"}), (b:Pathogen {name:"StreptococcusPneumoniae", domain:"medical"}) MERGE (a)-[:CAUSED_BY]->(b)
MATCH (a:Disease {name:"Pneumonia", domain:"medical"}), (b:Drug {name:"Amoxicillin", domain:"medical"}) MERGE (a)-[:TREATED_BY]->(b)
MATCH (a:Disease {name:"DiabetesMellitusType1", domain:"medical"}), (b:Drug {name:"Insulin", domain:"medical"}) MERGE (a)-[:TREATED_BY]->(b)
MATCH (a:Disease {name:"Hypertension", domain:"medical"}), (b:Drug {name:"Lisinopril", domain:"medical"}) MERGE (a)-[:TREATED_BY]->(b)
MATCH (a:Disease {name:"Migraine", domain:"medical"}), (b:Drug {name:"Ibuprofen", domain:"medical"}) MERGE (a)-[:TREATED_BY]->(b)

MATCH (a:Disease {name:"CoronaryArteryDisease", domain:"medical"}), (b:Procedure {name:"Angioplasty", domain:"medical"}) MERGE (a)-[:TREATED_BY_PROCEDURE]->(b)
MATCH (a:Disease {name:"Osteoarthritis", domain:"medical"}), (b:Procedure {name:"JointReplacement", domain:"medical"}) MERGE (a)-[:TREATED_BY_PROCEDURE]->(b)

MATCH (a:RiskFactor {name:"Smoking", domain:"medical"}), (b:Disease {name:"CoronaryArteryDisease", domain:"medical"}) MERGE (a)-[:RISK_FACTOR_FOR]->(b)
MATCH (a:RiskFactor {name:"Obesity", domain:"medical"}), (b:Disease {name:"DiabetesMellitusType2", domain:"medical"}) MERGE (a)-[:RISK_FACTOR_FOR]->(b)

MATCH (a:Disease {name:"CoronaryArteryDisease", domain:"medical"}), (b:Specialty {name:"Cardiology", domain:"medical"}) MERGE (a)-[:MANAGED_BY]->(b)
MATCH (a:Disease {name:"DiabetesMellitusType1", domain:"medical"}), (b:Specialty {name:"Endocrinology", domain:"medical"}) MERGE (a)-[:MANAGED_BY]->(b)
MATCH (a:Disease {name:"DiabetesMellitusType2", domain:"medical"}), (b:Specialty {name:"Endocrinology", domain:"medical"}) MERGE (a)-[:MANAGED_BY]->(b)
MATCH (a:Disease {name:"Asthma", domain:"medical"}), (b:Specialty {name:"Pulmonology", domain:"medical"}) MERGE (a)-[:MANAGED_BY]->(b)
MATCH (a:Disease {name:"Migraine", domain:"medical"}), (b:Specialty {name:"Neurology", domain:"medical"}) MERGE (a)-[:MANAGED_BY]->(b)

MATCH (a:Drug {name:"Ibuprofen", domain:"medical"}), (b:Disease {name:"CoronaryArteryDisease", domain:"medical"}) MERGE (a)-[:CONTRAINDICATED_FOR]->(b)

// ============================================================
// LEGAL DOMAIN — LEGALNORM NODES
// ============================================================

MERGE (l0:LegalNorm {name:"LegalNorm", domain:"legal"}) SET l0.schema_version="v1.0", l0.source_chunk_ids=[]
MERGE (l1:LegalNorm {name:"Constitution", domain:"legal"}) SET l1.schema_version="v1.0", l1.source_chunk_ids=[]
MERGE (l2:LegalNorm {name:"Statute", domain:"legal"}) SET l2.schema_version="v1.0", l2.source_chunk_ids=[]
MERGE (l3:LegalNorm {name:"CivilStatute", domain:"legal"}) SET l3.schema_version="v1.0", l3.source_chunk_ids=[]
MERGE (l4:LegalNorm {name:"CriminalStatute", domain:"legal"}) SET l4.schema_version="v1.0", l4.source_chunk_ids=[]
MERGE (l5:LegalNorm {name:"AdministrativeStatute", domain:"legal"}) SET l5.schema_version="v1.0", l5.source_chunk_ids=[]
MERGE (l6:LegalNorm {name:"Regulation", domain:"legal"}) SET l6.schema_version="v1.0", l6.source_chunk_ids=[]
MERGE (l7:LegalNorm {name:"Contract", domain:"legal"}) SET l7.schema_version="v1.0", l7.source_chunk_ids=[]
MERGE (l8:LegalNorm {name:"Precedent", domain:"legal"}) SET l8.schema_version="v1.0", l8.source_chunk_ids=[]

// Norm hierarchy (IS_A)
MATCH (a:LegalNorm {name:"Constitution", domain:"legal"}), (b:LegalNorm {name:"LegalNorm", domain:"legal"}) MERGE (a)-[:IS_A]->(b)
MATCH (a:LegalNorm {name:"Statute", domain:"legal"}), (b:LegalNorm {name:"LegalNorm", domain:"legal"}) MERGE (a)-[:IS_A]->(b)
MATCH (a:LegalNorm {name:"CivilStatute", domain:"legal"}), (b:LegalNorm {name:"Statute", domain:"legal"}) MERGE (a)-[:IS_A]->(b)
MATCH (a:LegalNorm {name:"CriminalStatute", domain:"legal"}), (b:LegalNorm {name:"Statute", domain:"legal"}) MERGE (a)-[:IS_A]->(b)
MATCH (a:LegalNorm {name:"AdministrativeStatute", domain:"legal"}), (b:LegalNorm {name:"Statute", domain:"legal"}) MERGE (a)-[:IS_A]->(b)
MATCH (a:LegalNorm {name:"Regulation", domain:"legal"}), (b:LegalNorm {name:"LegalNorm", domain:"legal"}) MERGE (a)-[:IS_A]->(b)
MATCH (a:LegalNorm {name:"Contract", domain:"legal"}), (b:LegalNorm {name:"LegalNorm", domain:"legal"}) MERGE (a)-[:IS_A]->(b)
MATCH (a:LegalNorm {name:"Precedent", domain:"legal"}), (b:LegalNorm {name:"LegalNorm", domain:"legal"}) MERGE (a)-[:IS_A]->(b)

// ---------- Supporting legal entity types (sample instances) ----------
MERGE (lr1:LegalRole {name:"Plaintiff", domain:"legal"}) SET lr1.schema_version="v1.0", lr1.source_chunk_ids=[]
MERGE (lr2:LegalRole {name:"Defendant", domain:"legal"}) SET lr2.schema_version="v1.0", lr2.source_chunk_ids=[]
MERGE (lr3:LegalRole {name:"Judge", domain:"legal"}) SET lr3.schema_version="v1.0", lr3.source_chunk_ids=[]

MERGE (la1:LegalAct {name:"FilingComplaint", domain:"legal"}) SET la1.schema_version="v1.0", la1.source_chunk_ids=[]
MERGE (la2:LegalAct {name:"Appeal", domain:"legal"}) SET la2.schema_version="v1.0", la2.source_chunk_ids=[]
MERGE (la3:LegalAct {name:"ContractSigning", domain:"legal"}) SET la3.schema_version="v1.0", la3.source_chunk_ids=[]

MERGE (rt1:LegalRight {name:"RightToCounsel", domain:"legal"}) SET rt1.schema_version="v1.0", rt1.source_chunk_ids=[]
MERGE (rt2:LegalRight {name:"RightToAppeal", domain:"legal"}) SET rt2.schema_version="v1.0", rt2.source_chunk_ids=[]

MERGE (ob1:LegalObligation {name:"DutyOfCare", domain:"legal"}) SET ob1.schema_version="v1.0", ob1.source_chunk_ids=[]
MERGE (ob2:LegalObligation {name:"ContractualPaymentDuty", domain:"legal"}) SET ob2.schema_version="v1.0", ob2.source_chunk_ids=[]

MERGE (c1:Court {name:"SupremeCourt", domain:"legal"}) SET c1.schema_version="v1.0", c1.source_chunk_ids=[]
MERGE (c2:Court {name:"DistrictCourt", domain:"legal"}) SET c2.schema_version="v1.0", c2.source_chunk_ids=[]

MERGE (j1:Jurisdiction {name:"Federal", domain:"legal"}) SET j1.schema_version="v1.0", j1.source_chunk_ids=[]
MERGE (j2:Jurisdiction {name:"State", domain:"legal"}) SET j2.schema_version="v1.0", j2.source_chunk_ids=[]

MERGE (sa1:Sanction {name:"MonetaryFine", domain:"legal"}) SET sa1.schema_version="v1.0", sa1.source_chunk_ids=[]
MERGE (sa2:Sanction {name:"Imprisonment", domain:"legal"}) SET sa2.schema_version="v1.0", sa2.source_chunk_ids=[]

MERGE (case1:LegalCase {name:"SampleCaseA", domain:"legal"}) SET case1.case_number="2020-CV-001", case1.schema_version="v1.0", case1.source_chunk_ids=[]
MERGE (case2:LegalCase {name:"SampleCaseB", domain:"legal"}) SET case2.case_number="2021-CR-045", case2.schema_version="v1.0", case2.source_chunk_ids=[]

// Sample relationships demonstrating each predicate type
MATCH (a:LegalAct {name:"ContractSigning", domain:"legal"}), (b:LegalNorm {name:"Contract", domain:"legal"}) MERGE (a)-[:GOVERNED_BY]->(b)
MATCH (a:LegalAct {name:"FilingComplaint", domain:"legal"}), (b:LegalNorm {name:"CivilStatute", domain:"legal"}) MERGE (a)-[:GOVERNED_BY]->(b)

MATCH (a:LegalCase {name:"SampleCaseB", domain:"legal"}), (b:LegalCase {name:"SampleCaseA", domain:"legal"}) MERGE (a)-[:CITES]->(b)
MATCH (a:LegalCase {name:"SampleCaseA", domain:"legal"}), (b:LegalNorm {name:"CivilStatute", domain:"legal"}) MERGE (a)-[:CITES_NORM]->(b)
MATCH (a:LegalCase {name:"SampleCaseB", domain:"legal"}), (b:LegalNorm {name:"CriminalStatute", domain:"legal"}) MERGE (a)-[:CITES_NORM]->(b)

MATCH (a:LegalCase {name:"SampleCaseA", domain:"legal"}), (b:Court {name:"DistrictCourt", domain:"legal"}) MERGE (a)-[:DECIDED_BY]->(b)
MATCH (a:LegalCase {name:"SampleCaseB", domain:"legal"}), (b:Court {name:"SupremeCourt", domain:"legal"}) MERGE (a)-[:DECIDED_BY]->(b)

MATCH (a:Court {name:"SupremeCourt", domain:"legal"}), (b:Jurisdiction {name:"Federal", domain:"legal"}) MERGE (a)-[:HAS_JURISDICTION]->(b)
MATCH (a:Court {name:"DistrictCourt", domain:"legal"}), (b:Jurisdiction {name:"State", domain:"legal"}) MERGE (a)-[:HAS_JURISDICTION]->(b)

MATCH (a:LegalNorm {name:"Constitution", domain:"legal"}), (b:LegalRight {name:"RightToCounsel", domain:"legal"}) MERGE (a)-[:GRANTS_RIGHT]->(b)
MATCH (a:LegalNorm {name:"Constitution", domain:"legal"}), (b:LegalRight {name:"RightToAppeal", domain:"legal"}) MERGE (a)-[:GRANTS_RIGHT]->(b)

MATCH (a:LegalNorm {name:"CivilStatute", domain:"legal"}), (b:LegalObligation {name:"DutyOfCare", domain:"legal"}) MERGE (a)-[:IMPOSES_OBLIGATION]->(b)
MATCH (a:LegalNorm {name:"Contract", domain:"legal"}), (b:LegalObligation {name:"ContractualPaymentDuty", domain:"legal"}) MERGE (a)-[:IMPOSES_OBLIGATION]->(b)

MATCH (a:LegalRight {name:"RightToCounsel", domain:"legal"}), (b:LegalRole {name:"Defendant", domain:"legal"}) MERGE (a)-[:HELD_BY]->(b)
MATCH (a:LegalRight {name:"RightToAppeal", domain:"legal"}), (b:LegalRole {name:"Defendant", domain:"legal"}) MERGE (a)-[:HELD_BY]->(b)

MATCH (a:LegalObligation {name:"DutyOfCare", domain:"legal"}), (b:LegalRole {name:"Defendant", domain:"legal"}) MERGE (a)-[:OWED_BY]->(b)
MATCH (a:LegalObligation {name:"ContractualPaymentDuty", domain:"legal"}), (b:LegalRole {name:"Defendant", domain:"legal"}) MERGE (a)-[:OWED_BY]->(b)

MATCH (a:LegalObligation {name:"DutyOfCare", domain:"legal"}), (b:Sanction {name:"MonetaryFine", domain:"legal"}) MERGE (a)-[:PENALIZED_BY]->(b)
MATCH (a:LegalObligation {name:"ContractualPaymentDuty", domain:"legal"}), (b:Sanction {name:"MonetaryFine", domain:"legal"}) MERGE (a)-[:PENALIZED_BY]->(b)

MATCH (a:LegalNorm {name:"CriminalStatute", domain:"legal"}), (b:Jurisdiction {name:"Federal", domain:"legal"}) MERGE (a)-[:APPLIES_IN]->(b)
MATCH (a:LegalNorm {name:"CivilStatute", domain:"legal"}), (b:Jurisdiction {name:"State", domain:"legal"}) MERGE (a)-[:APPLIES_IN]->(b)

// ============================================================
// END OF SEED SCRIPT
// ============================================================

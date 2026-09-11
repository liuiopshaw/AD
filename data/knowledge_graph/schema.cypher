// ============================================
// Nano-Bio Evaluator — Selective Antibacterial Nanomaterial Screening
// Neo4j Knowledge Graph Schema
// Domain: Nanomaterials × Gut Microbiota × Selective Antibacterial × AD
// ============================================

// ---- Node Constraints (ensuring uniqueness) ----
CREATE CONSTRAINT material_name IF NOT EXISTS
FOR (m:Material) REQUIRE m.name IS UNIQUE;

CREATE CONSTRAINT composition_name IF NOT EXISTS
FOR (c:Composition) REQUIRE c.name IS UNIQUE;

CREATE CONSTRAINT bacterium_name IF NOT EXISTS
FOR (b:Bacterium) REQUIRE b.name IS UNIQUE;

CREATE CONSTRAINT enzyme_class_name IF NOT EXISTS
FOR (e:EnzymeClass) REQUIRE e.name IS UNIQUE;

CREATE CONSTRAINT source_id IF NOT EXISTS
FOR (s:ExperimentalSource) REQUIRE s.source_id IS UNIQUE;

// ---- Material Node ----
// Properties: name, type (metal_np/metal_oxide/carbon/qd/mof),
//   size_nm, zeta_potential_mv, hydrodynamic_diameter_nm,
//   shape, coating, surface_area_m2g,
//   selective_ratio_in_vitro, selective_ratio_in_vivo

// ---- Composition Node ----
// Properties: name, element_symbol, role (core/shell/coating/ligand/dopant)

// ---- Bacterium Node ----
// Properties: name, gram_stain (positive/negative), genus,
//   species, is_probiotic (true/false), is_pathogen (true/false),
//   cell_wall_type, membrane_potential_mv

// ---- EnzymeClass Node ----
// Properties: name (CAT_like/SOD_like/NADH_oxidase_like),
//   natural_benchmark_enzyme, typical_km_range, ec_number

// ---- ToxicityEndpoint Node ----
// Properties: name, endpoint_type, unit, species, cell_line

// ---- Disease Node (NEW) ----
// Properties: name (Alzheimer's Disease),
//   category (neurodegenerative),
//   key_pathologies (neuroinflammation/Aβ_plaque/BBB_disruption)

// ---- Organ Node (NEW) ----
// Properties: name (liver/kidney/spleen/brain),
//   species (human/mouse/rat)

// ---- ExperimentalSource Node ----
// Properties: source_id, source_type (pubmed/local_exp/database),
//   pmid, title, extraction_date

// ---- Relationship Indexes ----
CREATE INDEX inhibits_mic IF NOT EXISTS
FOR ()-[r:INHIBITS]-() ON (r.MIC_value);

CREATE INDEX selectively_inhibits_ratio IF NOT EXISTS
FOR ()-[r:SELECTIVELY_INHIBITS]-() ON (r.selectivity_ratio);

CREATE INDEX exhibits_level IF NOT EXISTS
FOR ()-[r:EXHIBITS]-() ON (r.activity_level);

CREATE INDEX has_toxicity_value IF NOT EXISTS
FOR ()-[r:HAS_TOXICITY]-() ON (r.value);

// ---- Relationship Type Summary ----
// HAS_COMPOSITION: Material → Composition
// INHIBITS: Material → Bacterium { MIC_value, MBC_value, pH, temperature }
// PROMOTES: Material → Bacterium { growth_rate_change, mechanism }
// SELECTIVELY_INHIBITS: Material → Bacterium {
//   selectivity_ratio, mechanism_type, in_vitro_verified, in_vivo_verified
// }
// EXHIBITS: Material → EnzymeClass { activity_level, Km, Vmax, pH_optimal }
// GENERATES_ROS: Material → ROS_type { ROS_type, detection_method }
// HAS_TOXICITY: Material → ToxicityEndpoint { value, unit, cell_line }
// CAUSES_ORGAN_DAMAGE: Material → Organ {
//   damage_type, severity_level, reference, biomarker
// }
// MODULATES_PATHWAY: Material → Disease {
//   pathway_name, from_microbiome, to_disease_endpoint,
//   supporting_evidence, reference_pmid
// }
// CITED_IN: Entity → ExperimentalSource { figure_number, extraction_date }

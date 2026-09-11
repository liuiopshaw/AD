#!/usr/bin/env python3
"""
Generalized compound lookup for CDA-designed candidates (Phase 2 Tier 1).

泛化查证脚本 —— 按 Modality 路由到对应数据库，验证 agent 输出中各模态的
关键标识符（不改 agent 原始输出，只生成独立的查证产物）：

- 纳米模态 (nanocluster/nanoparticle/single_atom/dual_atom，含旧记录的
  Material_Category 逐字迁入值) → 复用 formula_lookup.py 的候选提取与
  查询逻辑（import candidates_for / make_source；MP+PubChem）
- small_molecule → PubChem（名称 + SMILES）+ ChEMBL molecule_by_smiles
  → 验证结论：SMILES 有效/无效、对应已知化合物 chembl_id
- biologic → UniProt get_entry(Target_UniProt) → 校验 accession 存在

输入：run 目录里的 task100_cda_<TS>_part*.txt（schema_v2.normalize_record
解析，兼容 9/10/11 列旧记录与 13 列 v2 记录）。
输出（写入同一 run 目录）：
- compound_lookup_raw_<TS>.txt  —— 原始 API 响应落盘
- compound_map_<TS>.json        —— {source, ts, materials: {name: {...}}}

用法:
  python scripts/compound_lookup.py [timestamp]
  python scripts/compound_lookup.py --input-dir outputs/run_<TS>
"""

import argparse, io, json, re, sys, time
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from output_utils import find_run_dir, OUTPUT_ROOT
from schema_v2 import normalize_record

# 纳米模态集合：schema_v2 的四种 + 旧记录 Material_Category 逐字迁入的同名值
NANO_MODALITIES = {"nanocluster", "nanoparticle", "single_atom", "dual_atom"}

# 无效占位值（agent 对不适用字段的填充）
NA_VALUES = {"", "NA", "N/A", "None", "none", "null", "-"}


def _is_filled(value) -> bool:
    """字段是否有实质内容（非 NA 占位）。"""
    return value is not None and str(value).strip() not in NA_VALUES


# ---------------------------------------------------------------------------
# 记录加载与解析
# ---------------------------------------------------------------------------

def load_records(input_dir: Path, ts: str):
    """读取 task100_cda_<ts>_part*.txt；v2 用 normalize_record 解析，
    v3(AD100)用 parse_record_v3 并把 Drug_Type 映射为路由用 Modality。"""
    from schema_v2 import parse_record_v3
    V3_TO_MODALITY = {"nano_formulation": "nanoparticle",
                      "small_molecule": "small_molecule",
                      "biologic": "biologic",
                      "composite": "nanoparticle",  # 二元复合:先按纳米相查证(化学式+包覆)
                      "other": "other"}
    parts = sorted(input_dir.glob(f"task100_cda_{ts}_part*.txt"))
    if not parts:
        raise SystemExit(f"No task100_cda_{ts}_part*.txt found in {input_dir}")
    records = []
    for p in parts:
        for line in io.open(p, encoding="utf-8"):
            line = line.strip()
            if "|" not in line:
                continue
            cells = [c.strip() for c in line.split("|")]
            # v3 FIRST: both v2 and v3 accept 13-col records, but
            # parse_record_v3 discriminates on DRUG_TYPES (cells[1]) while
            # normalize_record would silently misparse v3 rows as v2.
            rec = None
            rec3 = parse_record_v3(cells)
            if rec3 is not None:
                rec3["Modality"] = V3_TO_MODALITY.get(rec3.get("Drug_Type", ""), "other")
                rec = rec3
            if rec is None:
                rec = normalize_record(cells)
            if rec is not None:
                records.append(rec)
    return [p.name for p in parts], records


# ---------------------------------------------------------------------------
# 各模态查证函数（输入 v2 record dict，输出 map entry + raw 记录列表）
# ---------------------------------------------------------------------------

def lookup_nano(rec, inorg_fn, organic_fn, raw_lines, sleep_s=1.0):
    """纳米模态：复用 formula_lookup.py 的 candidates_for + 查询函数。

    candidates_for 期望旧式 cells 列表（[0]名称 [1]化学式 [2]配体），
    这里从 v2 record 机械重建该三元组喂给它。
    """
    # candidates_for 期望旧式 cells 列表（[0]名称 [1]化学式 [2]配体，且按
    # len(cells)>=10/11 判断字段存在），这里从 v2 record 机械重建并补齐到
    # 11 列再喂给它。
    from formula_lookup import candidates_for

    name = rec["Material_Name"]
    cells = [name, rec.get("Chemical_Formula", ""), rec.get("Ligand", "")] + [""] * 8
    cands = candidates_for(cells)

    entry = {"modality": rec["Modality"]}
    ids = []
    for q, role in cands:
        fn = organic_fn if role == "ligand" else inorg_fn
        res = fn(q)
        time.sleep(sleep_s)  # 礼貌限速（工具内部另有最小间隔控制）
        raw_lines.append(f"=== QUERY [{rec['Modality']}:{name}] {q} ({role}) ===\n"
                         f"{json.dumps(res.get('raw'), ensure_ascii=False)[:3000]}\n")
        if res.get("formula"):
            entry[role] = {"query": q, "formula": res["formula"],
                           "id": res["id"], "source": res["source"]}
            if res.get("id"):
                ids.append(res["id"])
        print(f"    {q} ({role}) -> "
              f"{res['formula']} [{res['id']}]" if res.get("formula") else f"    {q} ({role}) -> NO MATCH")

    if len(entry) > 1:  # 有任意命中
        parts = []
        for role in ("active_phase", "support"):
            r = entry.get(role)
            if r and r["formula"] not in parts:
                parts.append(r["formula"])
        entry["combined_formula"] = " + ".join(parts)
        entry["ids"] = ids
    return entry


def lookup_small_molecule(rec, pc, raw_lines, sleep_s=1.0):
    """小分子模态：PubChem（名称 + SMILES）+ ChEMBL molecule_by_smiles。

    产出验证结论：SMILES 有效/无效、对应已知化合物 chembl_id。
    """
    from src.tools.chembl_tool import molecule_by_smiles

    name = rec["Material_Name"]
    smiles = (rec.get("SMILES") or "").strip()
    entry = {"modality": rec["Modality"], "smiles": smiles or None}

    # ---- PubChem 按名称查证 ----
    pubchem_name = None
    if _is_filled(name):
        info = pc.get_compound_info(name)
        time.sleep(sleep_s)
        raw_lines.append(f"=== QUERY [small_molecule:{name}] PubChem name ===\n"
                         f"{json.dumps(info, ensure_ascii=False)[:3000]}\n")
        comp = (info or {}).get("Compound") or {}
        if comp.get("CID"):
            pubchem_name = {"formula": comp.get("MolecularFormula") or comp.get("molecular_formula"),
                            "id": f"CID:{comp['CID']}",
                            "canonical_smiles": comp.get("canonical_smiles")}
            entry["pubchem_name"] = pubchem_name
        print(f"    PubChem name '{name}' -> "
              f"{pubchem_name['id']}" if pubchem_name else f"    PubChem name '{name}' -> NO MATCH")

    # ---- SMILES 双源验证：ChEMBL + PubChem ----
    chembl_hit = None
    pubchem_smiles = None
    if _is_filled(smiles):
        chembl_hit = molecule_by_smiles(smiles)
        time.sleep(sleep_s)
        raw_lines.append(f"=== QUERY [small_molecule:{name}] ChEMBL smiles: {smiles} ===\n"
                         f"{json.dumps(chembl_hit, ensure_ascii=False)}\n")

        try:
            enc = quote(smiles, safe="")
            info = pc._make_request(
                f"compound/smiles/{enc}/property/MolecularFormula,CanonicalSMILES,InChIKey/JSON")
            time.sleep(sleep_s)
            raw_lines.append(f"=== QUERY [small_molecule:{name}] PubChem smiles: {smiles} ===\n"
                             f"{json.dumps(info, ensure_ascii=False)[:3000]}\n")
            props = ((info or {}).get("PropertyTable") or {}).get("Properties") or []
            if props and props[0].get("CID"):
                pubchem_smiles = {"formula": props[0].get("MolecularFormula"),
                                  "id": f"CID:{props[0]['CID']}",
                                  "inchikey": props[0].get("InChIKey")}
                entry["pubchem_smiles"] = pubchem_smiles
        except Exception as e:
            raw_lines.append(f"=== QUERY [small_molecule:{name}] PubChem smiles ERROR: {e} ===\n")

    # ---- 汇总验证结论 ----
    smiles_valid = bool(chembl_hit or pubchem_smiles)
    entry["smiles_valid"] = smiles_valid
    entry["chembl"] = chembl_hit
    if smiles_valid:
        cid = chembl_hit["chembl_id"] if chembl_hit else None
        via = f"ChEMBL {cid} ({chembl_hit['match_type']})" if chembl_hit else \
              f"PubChem {pubchem_smiles['id']}"
        entry["conclusion"] = f"SMILES valid; known compound via {via}"
    elif _is_filled(smiles):
        entry["conclusion"] = "SMILES invalid or unknown: no ChEMBL/PubChem structure match"
    else:
        entry["conclusion"] = "no SMILES provided (field NA)"
    print(f"    SMILES -> {entry['conclusion']}")
    return entry


def lookup_biologic(rec, raw_lines, sleep_s=1.0):
    """生物制剂模态：UniProt get_entry(Target_UniProt) 校验 accession。"""
    from src.tools.uniprot_tool import get_entry

    name = rec["Material_Name"]
    accession = (rec.get("Target_UniProt") or "").strip()
    entry = {"modality": rec["Modality"], "uniprot_accession": accession or None}

    if not _is_filled(accession):
        entry["valid"] = False
        entry["conclusion"] = "no Target_UniProt provided (field NA)"
        print(f"    UniProt -> {entry['conclusion']}")
        return entry

    hit = get_entry(accession)
    time.sleep(sleep_s)
    raw_lines.append(f"=== QUERY [biologic:{name}] UniProt {accession} ===\n"
                     f"{json.dumps(hit, ensure_ascii=False)}\n")
    if hit:
        entry.update({"valid": True, "protein_name": hit.get("protein_name"),
                      "gene": hit.get("gene"), "organism": hit.get("organism")})
        entry["conclusion"] = f"UniProt accession valid: {hit.get('protein_name')} ({hit.get('gene')})"
    else:
        entry["valid"] = False
        entry["conclusion"] = "UniProt accession invalid or network failure"
    print(f"    UniProt {accession} -> {entry['conclusion']}")
    return entry


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Modality-routed compound lookup for CDA outputs")
    ap.add_argument("ts", nargs="?", default=None, help="run timestamp")
    ap.add_argument("--input-dir", default=None,
                    help="historical run directory containing task100_cda_*_part*.txt")
    args = ap.parse_args()

    # ---- 定位输入 run 目录与时间戳 ----
    if args.input_dir:
        input_dir = Path(args.input_dir)
        if not input_dir.is_dir():
            raise SystemExit(f"--input-dir not found: {input_dir}")
        cands = list(input_dir.glob("task100_cda_*_part1.txt"))
        if not cands:
            raise SystemExit(f"No task100_cda_*_part1.txt in {input_dir}")
        ts = re.search(r"task100_cda_(\d+)_part1", cands[0].name).group(1)
    else:
        ts = args.ts
        if ts is None:
            candidates = (list(OUTPUT_ROOT.glob("task100_cda_*_part1.txt"))
                          + list(OUTPUT_ROOT.glob("run_*/task100_cda_*_part1.txt")))
            latest = max(candidates, key=lambda p: p.stat().st_mtime)
            ts = re.search(r"task100_cda_(\d+)_part1", latest.name).group(1)
        input_dir = find_run_dir(ts)

    src_files, records = load_records(input_dir, ts)
    print(f"Run dir: {input_dir}")
    print(f"{len(records)} records from {src_files}")

    # ---- 路由分组 ----
    nano_recs, sm_recs, bio_recs = [], [], []
    for rec in records:
        mod = (rec.get("Modality") or "").strip().lower()
        if mod in NANO_MODALITIES:
            nano_recs.append(rec)
        elif mod == "small_molecule":
            sm_recs.append(rec)
        elif mod == "biologic":
            bio_recs.append(rec)
        else:
            print(f"  [skip] unknown modality {rec.get('Modality')!r}: {rec.get('Material_Name')}")
    print(f"Routing: {len(nano_recs)} nano, {len(sm_recs)} small_molecule, {len(bio_recs)} biologic")

    # ---- 准备各模态查询入口 ----
    from formula_lookup import make_source
    inorg_fn, organic_fn, nano_source = make_source()
    from src.tools.pubchem_tool import get_pubchem_tool
    pc = get_pubchem_tool()

    source_parts = []
    if nano_recs:
        source_parts.append(f"{nano_source}(nano)")
    if sm_recs:
        source_parts.append("PubChem+ChEMBL(small_molecule)")
    if bio_recs:
        source_parts.append("UniProt(biologic)")
    source = "+".join(source_parts) or "none"
    print(f"Sources: {source}")

    # ---- 逐条查证（原始响应全部落盘）----
    raw_lines = [f"# Compound lookup raw data — source: {source}, run {ts}\n",
                 f"# files: {src_files}\n\n"]
    mapping = {}
    for rec in records:
        name = rec["Material_Name"]
        mod = (rec.get("Modality") or "").strip().lower()
        print(f"  [{mod}] {name}")
        if mod in NANO_MODALITIES:
            mapping[name] = lookup_nano(rec, inorg_fn, organic_fn, raw_lines)
        elif mod == "small_molecule":
            mapping[name] = lookup_small_molecule(rec, pc, raw_lines)
        elif mod == "biologic":
            mapping[name] = lookup_biologic(rec, raw_lines)

    # ---- 落盘：raw + map（走 run 目录约定，写回输入所在 run 目录）----
    raw_path = input_dir / f"compound_lookup_raw_{ts}.txt"
    with io.open(raw_path, "w", encoding="utf-8") as f:
        f.write("\n".join(raw_lines))
    map_path = input_dir / f"compound_map_{ts}.json"
    with io.open(map_path, "w", encoding="utf-8") as f:
        json.dump({"source": source, "ts": ts, "materials": mapping},
                  f, ensure_ascii=False, indent=2)

    print(f"\nMapped {len(mapping)}/{len(records)} records")
    print(f"Raw:  {raw_path}")
    print(f"Map:  {map_path}")


if __name__ == "__main__":
    main()

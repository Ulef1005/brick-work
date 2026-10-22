"""Spike #102 analysis: mapping shape, coverage, accuracy. Writes aggregates and catalogue examples only."""
import collections as C, json, sqlite3, sys
rb = sqlite3.connect(sys.argv[1]); bl = sqlite3.connect(sys.argv[2]); bw = sqlite3.connect(sys.argv[3]); R = {}
blitems = {}
for t, no in bl.execute("select item_type,item_no from items"): blitems.setdefault(t, set()).add(no)
def shape(fwd, name):
    rev = C.defaultdict(set)
    for a, bs in fwd.items():
        for b in bs: rev[b].add(a)
    one = sum(1 for a, bs in fwd.items() if len(bs) == 1 and len(rev[next(iter(bs))]) == 1)
    r = {"source_ids": len(fwd), "unmatched": sum(1 for b in fwd.values() if not b),
         "strict_1to1": one, "one_source_to_many_bl": sum(1 for b in fwd.values() if len(b) > 1),
         "bl_ids_hit": len(rev), "bl_ids_with_many_sources": sum(1 for a in rev.values() if len(a) > 1),
         "max_sources_per_bl": max((len(a) for a in rev.values()), default=0)}
    r["ex_one_to_many"] = [[a, sorted(b)] for a, b in fwd.items() if len(b) > 1][:8]
    r["ex_many_to_one"] = sorted([[b, sorted(a)[:6]] for b, a in rev.items() if len(a) > 1], key=lambda x: -len(x[1]))[:8]
    R[name] = r; return rev
# colours
cfwd = {}
for rid, ext in rb.execute("select rb_id,ext from rb_ext where kind='color'"):
    cfwd[rid] = {x for x in (json.loads(ext).get("BrickLink") or {}).get("ext_ids", []) if x is not None}
shape(cfwd, "colours")
# parts
pfwd, invalid = {}, []
for rid, ext in rb.execute("select rb_id,ext from rb_ext where kind='part'"):
    ids = set(json.loads(ext).get("BrickLink") or [])
    bad = {i for i in ids if i not in blitems["P"]}
    if bad: invalid.append([rid, sorted(bad)])
    pfwd[rid] = ids
shape(pfwd, "parts")
R["parts"]["bl_id_not_in_bl_catalogue"] = len(invalid); R["parts"]["ex_bl_id_not_in_catalogue"] = invalid[:8]
same = [p for p in pfwd if p in blitems["P"]]
R["parts"]["rb_num_exists_verbatim_in_bl"] = len(same)
R["parts"]["verbatim_but_ext_ids_disagree"] = sum(1 for p in same if pfwd[p] and p not in pfwd[p])
R["parts"]["ex_verbatim_disagree"] = [[p, sorted(pfwd[p])] for p in same if pfwd[p] and p not in pfwd[p]][:8]
# inventory-row coverage, latest version per set
latest = dict(rb.execute("select set_num, id from rb_inventories i where version=(select max(version) from rb_inventories j where j.set_num=i.set_num)").fetchall())
latest_ids = set(latest.values())
rows = tot = upart = uboth = 0
for inv, p, c, q, sp in rb.execute("select inventory_id,part_num,color_id,quantity,is_spare from rb_inventory_parts"):
    if int(inv) not in latest_ids and inv not in latest_ids: continue
    rows += 1
    if len(pfwd.get(p, ())) == 1:
        upart += 1
        if len(cfwd.get(c, ())) == 1: uboth += 1
R["inventory_rows"] = {"rows_latest_versions": rows, "part_unique_bl": upart, "part_and_colour_unique_bl": uboth,
                       "share_part_and_colour": round(uboth / rows, 4)}
# sets by number
rbsets = {r[0] for r in rb.execute("select set_num from rb_sets")}
R["sets"] = {"rb_sets": len(rbsets), "bl_sets": len(blitems["S"]), "same_number": len(rbsets & blitems["S"]),
             "rb_only": len(rbsets - blitems["S"]), "bl_only": len(blitems["S"] - rbsets),
             "rb_only_found_as_other_bl_type": {t: len((rbsets - blitems["S"]) & blitems.get(t, set())) for t in "GBICO"},
             "ex_rb_only": sorted(rbsets - blitems["S"])[:10], "ex_bl_only": sorted(blitems["S"] - rbsets)[:10]}
# minifigures: id_match from the migration, and the dump
mf = dict(bw.execute("select status,count(*) from id_match where source='rebrickable' and kind='minifigure' group by 1").fetchall())
R["minifigures"] = {"rb_figs": rb.execute("select count(*) from rb_minifigs").fetchone()[0], "bl_figs": len(blitems["M"]),
                    "migration_id_match": mf, "note": "no external ids; composition needs BrickLink minifigure inventories (1 call per figure)"}
# test copy's existing part matches vs external ids
agree = dis = noext = 0; exd = []
for sid, no in bw.execute("select source_id,item_no from id_match where source='rebrickable' and kind='part' and status in ('matched','manual')"):
    e = pfwd.get(sid)
    if not e: noext += 1
    elif no in e: agree += 1
    else: dis += 1; exd.append([sid, no, sorted(e)])
R["migration_parts_vs_ext_ids"] = {"agree": agree, "disagree": dis, "no_ext": noext, "ex": exd[:8]}
# accuracy against BrickLink subsets
per, pairs, figs = [], C.Counter(), C.Counter()
for s, body in rb.execute("select set_no, body from bl_subsets"):
    blp, blf = C.Counter(), 0
    for m in json.loads(body):
        for e in m["entries"]:
            if e["is_alternate"] or e["is_counterpart"]: continue
            if e["item"]["type"] == "PART": blp[(e["item"]["no"], e["color_id"])] += e["quantity"]
            elif e["item"]["type"] == "MINIFIG": blf += e["quantity"]
    inv = latest.get(s); rbp, unm = C.Counter(), 0
    for p, c, q, sp in rb.execute("select part_num,color_id,quantity,is_spare from rb_inventory_parts where inventory_id=?", (inv,)):
        if sp in ("t", "True", "1", 1, True): continue
        bp, bc = pfwd.get(p, set()), cfwd.get(c, set())
        if len(bp) == 1 and len(bc) == 1: rbp[(next(iter(bp)), next(iter(bc)))] += int(q)
        else: unm += int(q)
    rbf = sum(int(r[0]) for r in rb.execute("select quantity from rb_inventory_minifigs where inventory_id=?", (inv,)))
    tb = sum(blp.values()); hit = sum(min(blp[k], rbp[k]) for k in blp)
    only_bl = {k: v - rbp[k] for k, v in blp.items() if v > rbp[k]}; only_rb = {k: v - blp[k] for k, v in rbp.items() if v > blp[k]}
    for kb in only_bl:
        for kr in only_rb:
            if kb[1] == kr[1] and only_bl[kb] == only_rb[kr]: pairs[(kr[0], kb[0])] += 1
    figs["equal" if rbf == blf else "differ"] += 1
    per.append({"bl_qty": tb, "matched_qty": hit, "rb_unmapped_qty": unm, "exact": not only_bl and not only_rb and unm == 0})
n = len(per)
R["accuracy"] = {"sets": n, "exact_sets": sum(p["exact"] for p in per),
                 "qty_share_matched": round(sum(p["matched_qty"] for p in per) / max(1, sum(p["bl_qty"] for p in per)), 4),
                 "sets_ge_99pct": sum(1 for p in per if p["matched_qty"] >= 0.99 * p["bl_qty"]),
                 "sets_lt_90pct": sum(1 for p in per if p["matched_qty"] < 0.90 * p["bl_qty"]),
                 "rb_unmapped_qty": sum(p["rb_unmapped_qty"] for p in per),
                 "minifig_count_per_set": dict(figs),
                 "ex_mapped_vs_bl_number_pairs": [[a, b, k] for (a, b), k in pairs.most_common(12)]}
json.dump(R, open(sys.argv[4], "w"), indent=1)
print(json.dumps(R, indent=1)[:200])

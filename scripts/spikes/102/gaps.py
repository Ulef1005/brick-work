import collections as C, json, sqlite3, sys
rb = sqlite3.connect(sys.argv[1]); bw = sqlite3.connect(sys.argv[2])
print("id_match part rows w/o BL id:", bw.execute("select status,item_type is null,count(*) from id_match where source='rebrickable' and kind='part' group by 1,2").fetchall())
pf = {r: set(json.loads(e).get("BrickLink") or []) for r, e in rb.execute("select rb_id,ext from rb_ext where kind='part'")}
cf = {r: {x for x in (json.loads(e).get("BrickLink") or {}).get("ext_ids", []) if x is not None} for r, e in rb.execute("select rb_id,ext from rb_ext where kind='color'")}
latest = dict(rb.execute("select set_num,id from rb_inventories i where version=(select max(version) from rb_inventories j where j.set_num=i.set_num)"))
OB, OR, sizes = C.Counter(), C.Counter(), []
for s, body in rb.execute("select set_no,body from bl_subsets"):
    blp = C.Counter()
    for m in json.loads(body):
        for e in m["entries"]:
            if not (e["is_alternate"] or e["is_counterpart"]) and e["item"]["type"] == "PART": blp[e["item"]["no"]] += e["quantity"]
    rbp = C.Counter()
    for p, q, sp in rb.execute("select part_num,quantity,is_spare from rb_inventory_parts where inventory_id=?", (latest[s],)):
        if sp == "True": continue
        b = pf.get(p, set()); rbp[next(iter(b)) if len(b) == 1 else "?" + p] += int(q)
    ob = {k: v - rbp[k] for k, v in blp.items() if v > rbp[k]}; orr = {k: v - blp[k] for k, v in rbp.items() if v > blp[k]}
    OB.update(ob); OR.update(orr); sizes.append((sum(blp.values()), sum(rbp.values()), sum(ob.values()), sum(orr.values())))
print("colour-blind (part number only) gaps: BL-only qty", sum(OB.values()), "RB-only qty", sum(OR.values()), "BL total", sum(s[0] for s in sizes), "RB total", sum(s[1] for s in sizes))
print("top BL-only:", OB.most_common(15)); print("top RB-only:", OR.most_common(15))
print("sets where RB total > BL total by >5%:", sum(1 for a, b, _, _ in sizes if b > a * 1.05), "; BL > RB by >5%:", sum(1 for a, b, _, _ in sizes if a > b * 1.05))

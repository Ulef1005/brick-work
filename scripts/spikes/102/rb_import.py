import csv, gzip, io, sqlite3, sys, time, os
src, out = sys.argv[1], sys.argv[2]
if os.path.exists(out): os.remove(out)
t0 = time.time()
db = sqlite3.connect(out)
db.execute("pragma journal_mode=off"); db.execute("pragma synchronous=off")
tables = ["themes","colors","part_categories","parts","part_relationships","elements","sets","minifigs",
          "inventories","inventory_parts","inventory_sets","inventory_minifigs"]
for t in tables:
    with gzip.open(f"{src}/{t}.csv.gz","rt",newline="") as f:
        r = csv.reader(f); hdr = next(r)
        db.execute(f"create table rb_{t}({','.join(hdr)})")
        db.executemany(f"insert into rb_{t} values({','.join('?'*len(hdr))})", r)
db.executescript("""
create index ip_inv on rb_inventory_parts(inventory_id);
create index ip_part on rb_inventory_parts(part_num,color_id);
create index im_inv on rb_inventory_minifigs(inventory_id);
create index inv_set on rb_inventories(set_num);
create index el_part on rb_elements(part_num,color_id);
""")
db.commit(); db.execute("vacuum"); db.close()
print(f"import {time.time()-t0:.1f}s size {os.path.getsize(out)/1e6:.1f} MB")

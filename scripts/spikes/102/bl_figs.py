"""Minifigure mapping by composition (spike #102).
Ground truth: the test copy's migration matches (Rebrickable fig -> BrickLink fig). For n of them, fetch the
BrickLink minifigure inventory (1 call each) and compare with the dump's composition mapped to BrickLink ids.
Also: how unique a composition is on the Rebrickable side (could it find the figure without other evidence?)."""
import base64, collections as C, hashlib, hmac, json, os, secrets, sqlite3, sys, time, urllib.parse, urllib.request
rbp, bwp, n, outp = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
E = os.environ
ck, cs, tk, ts = (E[k] for k in ("BW_BRICKLINK_CONSUMER_KEY", "BW_BRICKLINK_CONSUMER_SECRET", "BW_BRICKLINK_TOKEN_VALUE", "BW_BRICKLINK_TOKEN_SECRET"))
q = lambda s: urllib.parse.quote(s, safe="~")
def get(url, params):
    o = {"oauth_consumer_key": ck, "oauth_token": tk, "oauth_signature_method": "HMAC-SHA1",
         "oauth_timestamp": str(int(time.time())), "oauth_nonce": secrets.token_hex(8), "oauth_version": "1.0"}
    base = "&".join(["GET", q(url), q("&".join(f"{q(k)}={q(v)}" for k, v in sorted({**params, **o}.items())))])
    o["oauth_signature"] = base64.b64encode(hmac.new(f"{q(cs)}&{q(ts)}".encode(), base.encode(), hashlib.sha1).digest()).decode()
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers={"Authorization": "OAuth " + ",".join(f'{k}="{q(v)}"' for k, v in o.items())})
    with urllib.request.urlopen(req, timeout=60) as r: return json.load(r)
rb = sqlite3.connect(rbp); bw = sqlite3.connect(bwp)
pf = {r: set(json.loads(e).get("BrickLink") or []) for r, e in rb.execute("select rb_id,ext from rb_ext where kind='part'")}
cf = {r: {x for x in (json.loads(e).get("BrickLink") or {}).get("ext_ids", []) if x is not None} for r, e in rb.execute("select rb_id,ext from rb_ext where kind='color'")}
latest = dict(rb.execute("select set_num,id from rb_inventories i where version=(select max(version) from rb_inventories j where j.set_num=i.set_num)"))
def rbcomp(fig, mapped=True):
    c = C.Counter()
    for p, col, qty, sp in rb.execute("select part_num,color_id,quantity,is_spare from rb_inventory_parts where inventory_id=?", (latest.get(fig),)):
        if sp == "True": continue
        if not mapped: c[(p, col)] += int(qty); continue
        bp, bc = pf.get(p, set()), cf.get(col, set())
        c[(next(iter(bp)) if len(bp) == 1 else "?" + p, next(iter(bc)) if len(bc) == 1 else "?" + col)] += int(qty)
    return c
# uniqueness of compositions across all Rebrickable figures (raw RB ids)
key = lambda c: tuple(sorted(c.items()))
figs = [r[0] for r in rb.execute("select fig_num from rb_minifigs")]
groups = C.Counter(key(rbcomp(f, False)) for f in figs if f in latest)
uniq = sum(1 for f in figs if f in latest and groups[key(rbcomp(f, False))] == 1)
truth = [(s, no) for s, no in bw.execute("select source_id,item_no from id_match where source='rebrickable' and kind='minifigure' and status in ('matched','manual') and item_no is not null")]
truth = sorted(truth, key=lambda x: hashlib.sha1(x[0].encode()).hexdigest())[:n]
res, ex = C.Counter(), []
for fig, blno in truth:
    d = get(f"https://api.bricklink.com/api/store/v1/items/MINIFIG/{urllib.parse.quote(blno)}/subsets", {"break_minifigs": "false"}); time.sleep(0.5)
    blc = C.Counter()
    for m in d.get("data") or []:
        for e in m["entries"]:
            if not (e["is_alternate"] or e["is_counterpart"]): blc[(e["item"]["no"], e["color_id"])] += e["quantity"]
    rc = rbcomp(fig)
    if not rc: res["rb_no_inventory"] += 1; continue
    if rc == blc: res["identical"] += 1
    elif set(k[0] for k in rc) == set(k[0] for k in blc): res["same_parts_colour_differs"] += 1
    else:
        res["differs"] += 1
        if len(ex) < 12: ex.append({"rb_only": sorted(f"{a}/{b}" for a, b in (rc - blc)), "bl_only": sorted(f"{a}/{b}" for a, b in (blc - rc))})
R = {"rb_figs_with_inventory": sum(1 for f in figs if f in latest), "rb_composition_unique": uniq,
     "rb_composition_groups_shared": sum(1 for g, k in groups.items() if k > 1), "largest_shared_group": max(groups.values()),
     "sample": len(truth), "result": dict(res), "ex_differences": ex}
json.dump(R, open(outp, "w"), indent=1); print(json.dumps(R, indent=1))

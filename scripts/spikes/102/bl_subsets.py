"""BrickLink subsets for a sample of the test copy's sets (spike #102). OAuth 1.0a HMAC-SHA1, stdlib only."""
import base64, hashlib, hmac, json, os, secrets, sqlite3, sys, time, urllib.parse, urllib.request
bw, rb, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
E = os.environ
ck, cs, tk, ts = (E[k] for k in ("BW_BRICKLINK_CONSUMER_KEY", "BW_BRICKLINK_CONSUMER_SECRET", "BW_BRICKLINK_TOKEN_VALUE", "BW_BRICKLINK_TOKEN_SECRET"))
q = lambda s: urllib.parse.quote(s, safe="~")
def get(url, params):
    o = {"oauth_consumer_key": ck, "oauth_token": tk, "oauth_signature_method": "HMAC-SHA1",
         "oauth_timestamp": str(int(time.time())), "oauth_nonce": secrets.token_hex(8), "oauth_version": "1.0"}
    allp = {**params, **o}
    base = "&".join(["GET", q(url), q("&".join(f"{q(k)}={q(v)}" for k, v in sorted(allp.items())))])
    o["oauth_signature"] = base64.b64encode(hmac.new(f"{q(cs)}&{q(ts)}".encode(), base.encode(), hashlib.sha1).digest()).decode()
    hdr = "OAuth " + ",".join(f'{k}="{q(v)}"' for k, v in o.items())
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers={"Authorization": hdr})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)
held = [r[0] for r in sqlite3.connect(bw).execute("select item_no from items where item_type='S'")]
rbs = {r[0] for r in sqlite3.connect(rb).execute("select set_num from rb_sets")}
cand = sorted((s for s in held if s in rbs), key=lambda s: hashlib.sha1(s.encode()).hexdigest())[:n]
out = sqlite3.connect(rb)
out.execute("create table if not exists bl_subsets(set_no primary key, body json, meta json)")
done = {r[0] for r in out.execute("select set_no from bl_subsets")}
for s in cand:
    if s in done: continue
    d = get(f"https://api.bricklink.com/api/store/v1/items/SET/{urllib.parse.quote(s)}/subsets", {"break_minifigs": "false"})
    out.execute("insert or replace into bl_subsets values(?,?,?)", (s, json.dumps(d.get("data")), json.dumps(d.get("meta"))))
    out.commit(); time.sleep(0.5)
print("held", len(held), "in rb", len([s for s in held if s in rbs]), "fetched", out.execute("select count(*) from bl_subsets").fetchone()[0],
      "meta codes", out.execute("select json_extract(meta,'$.code'),count(*) from bl_subsets group by 1").fetchall())

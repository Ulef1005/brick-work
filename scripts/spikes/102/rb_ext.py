"""Fetch Rebrickable external ids for colours and parts into rb.db (spike #102)."""
import json, os, sqlite3, sys, time, urllib.request
db = sqlite3.connect(sys.argv[1]); key = os.environ["BW_REBRICKABLE_API_KEY"]
db.executescript("drop table if exists rb_ext; create table rb_ext(kind, rb_id, ext json, primary key(kind, rb_id));"
                 "drop table if exists rb_calls; create table rb_calls(url, status, n, secs);")
def get(url):
    t = time.time()
    req = urllib.request.Request(url, headers={"Authorization": f"key {key}", "User-Agent": "brick-work-spike-102"})
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.load(r)
    db.execute("insert into rb_calls values(?,?,?,?)", (url.split("?")[0], 200, len(d["results"]), round(time.time()-t, 2)))
    time.sleep(1.1)
    return d
def page(kind, url, idf):
    n = 0
    while url:
        d = get(url)
        for x in d["results"]:
            db.execute("insert or replace into rb_ext values(?,?,?)", (kind, str(x[idf]), json.dumps(x.get("external_ids") or {})))
        n += len(d["results"]); db.commit(); url = d["next"]
        print(kind, n, flush=True)
page("color", "https://rebrickable.com/api/v3/lego/colors/?page_size=1000", "id")
page("part", "https://rebrickable.com/api/v3/lego/parts/?inc_part_details=1&page_size=1000", "part_num")
print(db.execute("select kind,count(*) from rb_ext group by 1").fetchall(), db.execute("select count(*),sum(secs) from rb_calls").fetchone())

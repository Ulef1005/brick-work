"""Invented i55 examples, added only to the gate's edge world."""
from ..core.sources import base
from ..store4 import fetched
from . import clock, dataset, showcase


def seed(db):
    stamp = clock.FIXED_NOW.isoformat()
    def item(kind, key, name, year=None):
        return fetched.create_local_item(db, kind=kind, born_provider='bricklink',
            born_namespace='M' if kind=='minifigure' else 'P', born_key=key, name=name, year=year, kind_source='bricklink')
    def price(identity, amount, colour=None):
        if amount is not None:
            base.observation(db,'bricklink',identity,guide='sold',price=amount,currency='EUR',color_id=colour,
                             condition='used',region='eu',qty=12,sold=12,observed_at=stamp)
    red = dataset.colour_by(db, 4)
    # One row is (name, missing, used quote). Each figure has four component lines.
    examples = [
        ('syn55-knight','Knight, Blue Torso, Black Legs, Dark Gray Helmet','Classic Town',1980,'18.00',
         [('Head',0,'2.00'),('Torso',0,'2.00'),('Legs',0,'2.00'),('Helmet',1,'3.50')]),
        ('syn55-police','Police Officer','City · Police',2011,'6.50',
         [('Head',0,'0.75'),('Cap',0,'0.50'),('Torso',1,'2.10'),('Legs',1,'0.90')]),
        ('syn55-chef','Chef, Red Neckerchief, White Legs, Top Hat','Classic Town',1980,'12.00',
         [('Head',0,'2.00'),('Torso',0,'3.00'),('Legs',0,'3.00'),('Top Hat',1,'9.00')]),
        ('syn55-forestman','Forestman, Quiver, Sideburns','Promotional',2022,'9.00',
         [('Head',0,'1.00'),('Torso',0,None),('Legs',0,'1.00'),('Quiver',1,'1.90')]),
        ('syn55-whole','Sam complete figure','Complete figures',2022,'12.00',
         [('Head',0,'2.00'),('Torso',0,'2.00'),('Legs',0,'2.00'),('Cap',0,'2.00')]),
    ]
    for key,name,theme,year,complete,components in examples:
        identity=item('minifigure',key,name,year)
        db.execute('UPDATE item SET theme_name=? WHERE id=?',(theme,identity))
        sid=showcase.uid('stock',key,'figure')
        db.execute("""INSERT INTO stock(id,kind,item_id,quantity,condition,inventory_source,created_at,updated_at)
            VALUES(?,'minifigure',?,1,'used','none',?,?)""",(sid,identity,stamp,stamp))
        price(identity,complete)
        for n,(part_name,missing,quote) in enumerate(components):
            part=item('part',key+'-part-'+str(n),part_name)
            db.execute('INSERT INTO stock_part(stock_id,item_id,color_id,quantity,missing,checked) VALUES(?,?,?,1,?,1)',(sid,part,red,missing))
            price(part,quote,red)
    # The approved card also describes the same police figure in a set copy.
    figure = db.execute("SELECT id FROM item WHERE born_key='syn55-police'").fetchone()[0]
    source = showcase.uid('stock','syn55-police','figure')
    copy = db.execute("SELECT c.id FROM copy c JOIN item i ON i.id=c.item_id WHERE i.born_key='7286-1' AND c.archived_at IS NULL ORDER BY c.created_at,c.id LIMIT 1").fetchone()
    if copy:
        fid = db.execute("INSERT INTO copy_figure(copy_id,item_id,inventory_source,quantity,updated_at) VALUES(?,?,'none',1,?)",(copy[0],figure,stamp)).lastrowid
        db.execute('''INSERT INTO copy_part(copy_id,copy_figure_id,item_id,color_id,quantity,missing,checked)
            SELECT ?,?,item_id,color_id,quantity,missing,checked FROM stock_part WHERE stock_id=?''',(copy[0],fid,source))
    db.executemany('INSERT OR REPLACE INTO setting(key,value) VALUES(?,?)',
                   [('repair_shipping','0.30'),('repair_fees','0.20'),('repair_min_order','0'),('repair_use_loose_stock','0')])

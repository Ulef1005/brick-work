"""Supported embedded receipts: one registry for capture, dispatch and public SQL."""
KINDS = {
    'bw_collection': ('save','archive','restore','photo','caption','attach','label'),
    'bw_workbench': ('receipt',), 'bw_ledger': ('receipt',), 'bw_add': ('receipt',),
    'bw_planning': ('pin','settings'), 'bw_manual_prices': ('receipt',),
    'source_key:': ('save','archive'), 'source:': ('enabled',),
    'identification:': ('create','archive'), 'part_inventory:': ('receipt',), 'bw_import': ('receipt',), 'bw_sync': ('receipt',),
}


def is_receipt(receipt):
    return any((receipt['entity'].startswith(entity) if entity.endswith(':') else receipt['entity']==entity)
               and receipt['field'] in fields for entity,fields in KINDS.items())


def receipt_sql(entity, field):
    return '(' + ' OR '.join(
        '('+("substr("+entity+",1,"+str(len(key))+")='"+key+"'" if key.endswith(':') else entity+"='"+key+"'")+
        ' AND '+field+' IN ('+','.join("'"+f+"'" for f in fields)+'))'
        for key,fields in KINDS.items()) + ')'

"""Invented UI replies for unapproved instruction frames. No adapter or database rows.

Only the demo app exposes these replies; screen scripts replace browser fetches with
these fixed responses. The production Official adapter remains unavailable without a renderer.
"""
from copy import deepcopy


def reply(state):
    def candidate(identifier, source='rebrickable', **extra):
        return dict(id=identifier, item_id=1, source=source, title=f'Alex and Sam · Booklet {identifier}',
                    booklet=identifier, booklets=3, language='English' if source != 'peeron' else None,
                    region='Europe' if source != 'peeron' else None, size=4 * 1024 * 1024,
                    url=f'https://invented.example/{identifier}.pdf', file_id=None, **extra)
    groups = [dict(job_id=9001, item_id=1, name='Alex Night Keep', born_key='99011-1', state='done',
                   sources_tried=['rebrickable','peeron'], error=None,
                   candidates=[candidate(1),candidate(2),candidate(3)]),
              dict(job_id=9002, item_id=2, name='Sam Signal Tower', born_key='99014-1', state='done',
                   sources_tried=['rebrickable','peeron'], error=None, candidates=[candidate(4,'peeron')]),
              dict(job_id=9003, item_id=3, name='Forest Lookout', born_key='99013-1', state='done',
                   sources_tried=['rebrickable','peeron'], error=None, candidates=[])]
    groups[1]['candidates'][0].update(booklet=1,booklets=1,item_id=2)
    if state == 'searching':
        groups[1].update(state='running',candidates=[])
        groups[2]['state']='queued'
    if state == 'nothing-found':
        for group in groups: group['candidates']=[]
    if state == 'partly-found':
        groups[1]['error']='Rebrickable did not answer'
    if state == 'disabled-rows':
        groups[0]['candidates'][0]['size']=25*1024*1024
        groups[0]['candidates'][1]['file_id']=1
    if state == 'one-set': groups=groups[:1]
    download=None
    if state in ('downloading','finished','failed'):
        steps=[dict(name=str(n),state='done' if n<3 or state=='finished' else 'failed' if state=='failed' and n==3 else 'running' if n==3 else 'queued',
                    error='The source closed the connection' if state=='failed' and n==3 else None) for n in range(1,5)]
        download=dict(id=9010,kind='instruction_download',state='done' if state=='finished' else 'failed' if state=='failed' else 'running',steps=steps)
    return deepcopy(dict(groups=groups,download=download))


def install(app):
    from flask import abort, jsonify
    @app.get('/demo/instruction-state/<state>')
    def instruction_state(state):
        if state not in ('tick-list','searching','nothing-found','partly-found','disabled-rows','one-set','downloading','finished','failed'):
            abort(404)
        return jsonify(reply(state))

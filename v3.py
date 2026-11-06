import json
from datetime import date, timedelta
from fastapi import HTTPException
from pydantic import BaseModel, Field


class Simulation(BaseModel):
    project_id: str
    planning_day: date = Field(default_factory=date.today)
    months: int = Field(default=2, ge=1, le=3)
    repeats: int = Field(default=1, ge=1, le=2)
    preferred_coach_id: int | None = None
    to_day: date = date(2027, 4, 30)


def install(app, g):
    connection, available, interval = (g[k] for k in ('connection','available','interval'))
    with connection() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS projects_v3(id TEXT PRIMARY KEY,name TEXT,trainer_id INTEGER,rf TEXT);
        CREATE TABLE IF NOT EXISTS plans_v3(project_id TEXT PRIMARY KEY,payload TEXT,status TEXT);
        CREATE TABLE IF NOT EXISTS simulations_v3(project_id TEXT PRIMARY KEY,options TEXT);''')
        c.executemany('INSERT OR IGNORE INTO projects_v3 VALUES (?,?,?,?)', [('OKT-001','Management de projet',7,'Alice Martin'),('OKT-002','Communication professionnelle',7,'Thomas Bernard'),('OKT-003','Leadership',7,'Nadia Robert')])
    # V2 mutation endpoints are retired; existing historical rows stay intact.
    app.router.routes[:] = [r for r in app.router.routes if getattr(r,'path','') not in ('/api/reset','/api/match','/api/requests','/api/options/{option_id}/select','/api/options/{option_id}/confirm')]
    app.version='3.0'

    from mailflow import setup, digest
    prepare_mail, send_mail, valid_link = setup(app, connection)

    def project(c, pid):
        r=c.execute('SELECT * FROM projects_v3 WHERE id=?',(pid,)).fetchone()
        if not r: raise HTTPException(404,'Projet inconnu')
        return dict(r)

    def release(c,pid):
        c.execute('DELETE FROM busy WHERE source=?',('project:'+pid,))

    def slots(p):
        for d in p['repetitions']:
            for rid in (4,p['trainer_id'],p['coach_id']): yield rid,date.fromisoformat(d),'repetition'
        for d in p['shoots']:
            for rid in (p['studio_id'],p['trainer_id'],p['makeup_id']): yield rid,date.fromisoformat(d),'full'

    @app.get('/api/projects')
    def projects():
        with connection() as c:
            return [dict(r) for r in c.execute('SELECT p.*,r.name trainer FROM projects_v3 p JOIN resources r ON r.id=p.trainer_id')]

    @app.post('/api/simulate')
    def simulate(req: Simulation):
        with connection() as c:
            c.execute('BEGIN IMMEDIATE')
            pr=project(c,req.project_id)
            # Ignore this project's current holds during search, restore until replacement is chosen.
            c.execute('SAVEPOINT own_holds')
            release(c,req.project_id)
            r=g['RequestInput'](title=pr['name'],trainer_id=pr['trainer_id'],repeats=req.repeats,planning_day=req.planning_day,from_day=req.planning_day,to_day=req.to_day,min_production_months=req.months,preferred_coach_id=req.preferred_coach_id)
            r.from_day=req.planning_day
            opts=g['make_candidates'](c,r)
            opts=[p for p in opts if date.fromisoformat(p['shoots'][0])>=req.planning_day+timedelta(days=60)]
            c.execute('ROLLBACK TO own_holds');c.execute('RELEASE own_holds')
            for p in opts:
                p.pop('score',None)
                shoot=date.fromisoformat(p['shoots'][0])
                # Preparation has already started when the selected lead time is under 60 days.
                syllabus=max(req.planning_day,shoot-timedelta(days=90))
                if syllabus>shoot-timedelta(days=60): syllabus=shoot-timedelta(days=60)
                p['milestones']={'syllabus_window_start':(shoot-timedelta(days=90)).isoformat(),'syllabus_window_end':(shoot-timedelta(days=60)).isoformat(),'syllabus':syllabus.isoformat(),'sample':(syllabus+timedelta(days=10)).isoformat(),'resources':(date.fromisoformat(p['shoots'][-1])+timedelta(days=10)).isoformat()}
                p['preparation_started_before_planning']=syllabus<req.planning_day
            c.execute('INSERT OR REPLACE INTO simulations_v3 VALUES (?,?)',(req.project_id,json.dumps(opts)))
            return opts

    @app.post('/api/projects/{pid}/reserve/{index}')
    def reserve(pid:str,index:int):
        with connection() as c:
            c.execute('BEGIN IMMEDIATE');project(c,pid)
            r=c.execute('SELECT options FROM simulations_v3 WHERE project_id=?',(pid,)).fetchone()
            opts=json.loads(r[0]) if r else []
            if index<0 or index>=len(opts): raise HTTPException(409,'Relancez une simulation')
            p=opts[index];release(c,pid)
            for rid,d,slot in slots(p):
                if not available(c,rid,d,slot): raise HTTPException(409,'Disponibilités modifiées : relancez la simulation')
            for rid,d,slot in slots(p):
                a,b=interval(d,slot)
                c.execute('INSERT INTO busy(resource_id,start,end,title,source) VALUES (?,?,?,?,?)',(rid,a.isoformat(),b.isoformat(),'Option CDP '+pid,'project:'+pid))
            c.execute('INSERT OR REPLACE INTO plans_v3 VALUES (?,?,?)',(pid,json.dumps(p),'pending'))
            c.execute('DELETE FROM simulations_v3 WHERE project_id=?',(pid,))
            mail_id=prepare_mail(c,pid,p)
        return {'status':'pending','mail_status':send_mail(mail_id)}

    @app.post('/api/projects/{pid}/coach/{decision}')
    def decision(pid:str,decision:str,token:str | None = None):
        if decision not in ('accept','refuse'): raise HTTPException(422,'Décision invalide')
        with connection() as c:
            c.execute('BEGIN IMMEDIATE')
            if token is not None:
                if valid_link(c,token)!=pid: raise HTTPException(410,'Lien invalide')
            r=c.execute('SELECT * FROM plans_v3 WHERE project_id=?',(pid,)).fetchone()
            if not r or r['status']!='pending': raise HTTPException(409,'Aucune demande en attente')
            p=json.loads(r['payload'])
            if decision=='refuse':
                release(c,pid)
                for d in p['repetitions']:
                    a,b=interval(date.fromisoformat(d),'repetition')
                    c.execute('INSERT INTO busy(resource_id,start,end,title,source) VALUES (?,?,?,?,?)',(p['coach_id'],a.isoformat(),b.isoformat(),'Refus coach simulé','coach-refusal:'+pid))
            else:
                release(c,pid)
                for rid,d,slot in slots(p):
                    if not available(c,rid,d,slot): raise HTTPException(409,'Conflit : une nouvelle simulation est nécessaire')
                for rid,d,slot in slots(p):
                    a,b=interval(d,slot)
                    c.execute('INSERT INTO busy(resource_id,start,end,title,source) VALUES (?,?,?,?,?)',(rid,a.isoformat(),b.isoformat(),'Confirmé '+pid,'project:'+pid))
            c.execute('UPDATE plans_v3 SET status=? WHERE project_id=?',('confirmed' if decision=='accept' else 'refused',pid))
            c.execute('DELETE FROM simulations_v3 WHERE project_id=?',(pid,))
            c.execute('UPDATE coach_links SET used=1 WHERE project_id=?',(pid,))
        return {'status':decision}

    @app.get('/api/projects/{pid}/summary')
    def summary(pid:str):
        with connection() as c:
            pr=project(c,pid);r=c.execute('SELECT * FROM plans_v3 WHERE project_id=?',(pid,)).fetchone()
            return {'schema_version':'3.0','destination':'Moockapp','sync_status':'local_only','project':pr,'status':r['status'] if r else 'draft','planning':json.loads(r['payload']) if r else None}



    @app.post('/respond/{token}/{choice}')
    def respond(token:str,choice:str):
        with connection() as c: pid=valid_link(c,token)
        decision(pid,choice,token)
        from fastapi.responses import HTMLResponse
        return HTMLResponse('<html lang="fr"><h1>Réponse enregistrée</h1><p>Vous pouvez fermer cette page.</p></html>')

    @app.post('/api/projects/{pid}/retry-mail')
    def retry_mail(pid:str):
        with connection() as c:
            c.execute('BEGIN IMMEDIATE')
            r=c.execute('SELECT * FROM plans_v3 WHERE project_id=?',(pid,)).fetchone()
            if not r or r['status']!='pending': raise HTTPException(409,'Aucune confirmation en attente')
            mid=prepare_mail(c,pid,json.loads(r['payload']))
        return {'mail_status':send_mail(mid)}

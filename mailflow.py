import hashlib
import html
import os
import secrets
import smtplib
import ssl
import time
from email.message import EmailMessage
from fastapi import HTTPException
from fastapi.responses import HTMLResponse, Response


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def setup(app, connection):
    online = os.getenv('PLANNER_ONLINE') == '1'
    user, password = os.getenv('CDP_USER', 'cdp'), os.getenv('CDP_PASSWORD', '')
    if online and (len(password) < 16 or not os.getenv('PUBLIC_BASE_URL', '').startswith('https://')):
        raise RuntimeError('Configurer CDP_PASSWORD (16 caractères minimum) et PUBLIC_BASE_URL HTTPS')
    with connection() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS coach_links(token_hash TEXT PRIMARY KEY,project_id TEXT,expires INTEGER,used INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS mail_outbox(id INTEGER PRIMARY KEY,project_id TEXT,body TEXT,status TEXT,error TEXT);''')

    @app.middleware('http')
    async def protect(request, call_next):
        if online and not (request.url.path.startswith('/respond/') or request.url.path == '/health'):
            import base64
            expected='Basic '+base64.b64encode((user+':'+password).encode()).decode()
            if not secrets.compare_digest(request.headers.get('authorization',''), expected):
                return Response(status_code=401,headers={'WWW-Authenticate':'Basic realm="Studio Planner"'})
        response=await call_next(request)
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        return response

    @app.get('/health')
    def health(): return {'ok':True}

    def prepare(c,pid,p):
        c.execute('UPDATE coach_links SET used=1 WHERE project_id=?',(pid,))
        c.execute("UPDATE mail_outbox SET status='superseded',body='' WHERE project_id=?",(pid,))
        token=secrets.token_urlsafe(32)
        c.execute('INSERT INTO coach_links VALUES (?,?,?,0)',(digest(token),pid,int(time.time())+7*86400))
        url=os.getenv('PUBLIC_BASE_URL','http://127.0.0.1:8000').rstrip('/')+'/respond/'+token
        body=f"Projet {pid}\nRépétitions : {', '.join(p['repetitions'])}\nTournage : {', '.join(p['shoots'])}\n\nConsultez et confirmez votre réponse : {url}\nCe lien personnel expire dans 7 jours."
        return c.execute("INSERT INTO mail_outbox(project_id,body,status,error) VALUES (?,?,'pending','')",(pid,body)).lastrowid

    def send(mid):
        if os.getenv('MAIL_ENABLED') != '1': return 'disabled'
        with connection() as c:
            row=c.execute("SELECT * FROM mail_outbox WHERE id=? AND status='pending'",(mid,)).fetchone()
            if not row:return 'superseded'
            try:
                msg=EmailMessage()
                msg['From']=os.getenv('MAIL_FROM','jean-baptiste.guillaume@visiplus.com')
                msg['To']=os.getenv('COACH_TEST_EMAIL','guillaume.log@gmail.com')
                msg['Subject']='Studio Planner — confirmation demandée — '+row['project_id']
                msg.set_content(row['body'])
                with smtplib.SMTP(os.environ['SMTP_HOST'],int(os.getenv('SMTP_PORT','587')),timeout=20) as smtp:
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.login(os.environ['SMTP_USER'],os.environ['SMTP_PASSWORD'])
                    smtp.send_message(msg)
                status='sent'
            except Exception:
                status='failed'
            c.execute('UPDATE mail_outbox SET status=?,error=?,body=? WHERE id=?',(status,'Envoi SMTP impossible : vérifier la configuration' if status=='failed' else '', '' if status=='sent' else row['body'],mid))
            return status

    def valid(c,token):
        r=c.execute('SELECT * FROM coach_links WHERE token_hash=?',(digest(token),)).fetchone()
        if not r or r['used'] or r['expires']<time.time(): raise HTTPException(410,'Lien expiré ou déjà utilisé. Contactez le CDP.')
        return r['project_id']

    @app.get('/respond/{token}',response_class=HTMLResponse)
    def page(token:str):
        with connection() as c:
            pid=valid(c,token)
            import json
            r=c.execute('SELECT payload FROM plans_v3 WHERE project_id=?',(pid,)).fetchone()
            p=json.loads(r[0])
        return '<html lang="fr"><meta name="viewport" content="width=device-width"><title>Confirmation coach</title><body><h1>Confirmation '+html.escape(pid)+'</h1><p>Répétitions : '+html.escape(', '.join(p['repetitions']))+'</p><p>Tournage : '+html.escape(', '.join(p['shoots']))+'</p>'+''.join('<form method="post" action="/respond/'+token+'/'+d+'"><button type="submit">'+label+'</button></form>' for d,label in [('accept','Accepter ces dates'),('refuse','Refuser ces dates')])+'</body></html>'
    return prepare,send,valid

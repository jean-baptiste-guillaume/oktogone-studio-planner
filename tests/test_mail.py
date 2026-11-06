import os,sys,tempfile,unittest,re,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['PLANNER_DB']=tempfile.mktemp(suffix='.db')
os.environ['PLANNER_ONLINE']='1'
os.environ['CDP_PASSWORD']='test-password-long-enough'
os.environ['PUBLIC_BASE_URL']='https://planner.example.com'
os.environ['MAIL_ENABLED']='0'
from fastapi.testclient import TestClient
import app
client=TestClient(app.app)
auth=('cdp',os.environ['CDP_PASSWORD'])
class MailTests(unittest.TestCase):
 def reserve(self):
  self.assertEqual(client.post('/api/simulate',auth=auth,json={'project_id':'OKT-001','planning_day':'2026-11-05'}).status_code,200)
  self.assertEqual(client.post('/api/projects/OKT-001/reserve/0',auth=auth).status_code,200)
  with app.connection() as c: body=c.execute('SELECT body FROM mail_outbox ORDER BY id DESC').fetchone()[0]
  return re.search(r'/respond/(\S+)',body)[1]
 def test_secure_response(self):
  self.assertEqual(client.get('/api/projects').status_code,401)
  self.assertEqual(client.get('/health').status_code,200)
  token=self.reserve()
  self.assertEqual(client.get('/respond/'+token).status_code,200)
  self.assertEqual(client.get('/api/projects/OKT-001/summary',auth=auth).json()['status'],'pending')
  new=self.reserve()
  self.assertEqual(client.get('/respond/'+token).status_code,410)
  self.assertEqual(client.post('/respond/'+new+'/accept').status_code,200)
  self.assertEqual(client.post('/respond/'+new+'/refuse').status_code,410)
  token=self.reserve()
  self.assertEqual(client.post('/respond/'+token+'/refuse').status_code,200)
  token=self.reserve()
  with app.connection() as c:c.execute('UPDATE coach_links SET expires=0')
  self.assertEqual(client.post('/respond/'+token+'/accept').status_code,410)
if __name__=='__main__':unittest.main()

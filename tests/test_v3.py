import os, tempfile, unittest, sys
from datetime import date
sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[1]))
os.environ['PLANNER_DB']=tempfile.mktemp(suffix='.db')
from fastapi.testclient import TestClient
import app
client=TestClient(app.app)
class Scenarios(unittest.TestCase):
 def test_workflow(self):
  def sim(pid='OKT-001',**kw):
   r=client.post('/api/simulate',json=dict(project_id=pid,planning_day='2026-11-05',**kw));self.assertEqual(r.status_code,200,r.text);return r.json()
  opts=sim(months=1,repeats=2);self.assertEqual(len(opts),3)
  for p in opts:
   shoots=list(map(date.fromisoformat,p['shoots']));self.assertEqual((shoots[1]-shoots[0]).days,1)
   self.assertTrue(7<=(shoots[0]-date.fromisoformat(p['repetitions'][-1])).days<=14)
   self.assertTrue(60<=(shoots[0]-date.fromisoformat(p['milestones']['syllabus'])).days<=90)
  def reserve(pid,i=0):
   r=client.post(f'/api/projects/{pid}/reserve/{i}');self.assertEqual(r.status_code,200,r.text)
  reserve('OKT-001');sim('OKT-002');reserve('OKT-002')
  with app.connection() as c: other=[tuple(r) for r in c.execute("SELECT * FROM busy WHERE source='project:OKT-002'")]
  sim();reserve('OKT-001',1)
  with app.connection() as c:
   self.assertEqual(other,[tuple(r) for r in c.execute("SELECT * FROM busy WHERE source='project:OKT-002'")])
   self.assertEqual(c.execute("SELECT count(*) FROM busy WHERE source='project:OKT-001'").fetchone()[0],9)
  self.assertEqual(client.post('/api/projects/OKT-001/coach/refuse').status_code,200)
  sim();reserve('OKT-001');self.assertEqual(client.post('/api/projects/OKT-001/coach/accept').status_code,200)
  self.assertEqual(client.get('/api/projects/OKT-001/summary').json()['status'],'confirmed')
  self.assertEqual(client.post('/api/simulate',json={'project_id':'OKT-001','months':0}).status_code,422)
  ics=b'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20270112\r\nDTEND;VALUE=DATE:20270113\r\nSUMMARY:Test\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n'
  self.assertEqual(client.post('/api/import-ics/5',files={'file':('busy.ics',ics,'text/calendar')}).status_code,200)
if __name__=='__main__': unittest.main()

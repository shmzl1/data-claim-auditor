import base64
import copy
import json
import sys
import unittest
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import app
from audit import reproduce
from discovery import analyze,checked_plan,evaluate_question
from reporting import markdown,evidence_text
from stats import read_csv

def record(name):
    return json.loads((ROOT/"evidence"/(name+".json")).read_text("utf8"))

class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.sales=(ROOT/"examples/sales.csv").read_bytes()
        self.rows=read_csv(self.sales)
        self.d=record("analysis-sales")

    def test_default_form(self):
        self.assertIn('data-endpoint="/analyze"',app.home())
        self.assertIn('id="focus"',app.home())
        self.assertNotIn('id="claims"',app.home())
        self.assertIn('id="claims" required',app.home("audit"))

    def test_analysis_replay(self):
        for name,csv_file in [("sales","sales"),("focus","sales"),("conversion","conversion")]:
            d=record("analysis-"+name)
            self.assertEqual(len({e["role"] for e in d["events"]}),5)
            self.assertEqual(reproduce((ROOT/"examples"/(csv_file+".csv")).read_bytes(),d),6)

    def test_main_results_independent(self):
        # 手工按原 CSV 行加总，独立于 stats.aggregate。
        res=[q["result"] for q in self.d["analysis"]["questions"]]
        self.assertEqual(float(res[0]["left"]["value"]),12000+15000)
        self.assertEqual({float(res[1][s]["value"]) for s in ("left","right")},{18000+16000,10000+14000})
        self.assertEqual({float(res[2][s]["value"]) for s in ("left","right")},{12000+18000+10000,15000+16000+14000})
        d=record("analysis-conversion")
        values=[q["result"] for q in d["analysis"]["questions"]]
        self.assertEqual(float(values[0]["left"]["value"]),2)
        self.assertEqual({float(values[1][s]["value"]) for s in ("left","right")},{2,126})
        self.assertEqual(float(values[2]["left"]["value"]),2/20*100)

    def test_sum_displayed_once(self):
        table=app.discovery_panel(self.d)
        self.assertEqual(table.count("销售额合计 40,000"),1)
        self.assertEqual(table.count("销售额合计 45,000"),1)
        self.assertNotIn("→",table)

    def test_fractional_sum_preserves_exact_value(self):
        q=dict(metric="合计",num="销售额",left={},right=None)
        rows=read_csv("销售额\n-1000.125\n-0.000000001\n".encode())
        result=evaluate_question(rows,q)
        self.assertEqual(evidence_text(q,result),["全部记录（2 行）　销售额合计 -1,000.125000001"])

    def test_ratio_display_retains_population(self):
        d=record("analysis-conversion")
        panel=app.discovery_panel(d)
        self.assertIn("月份=5月",panel)
        self.assertIn("用户类型=新用户",panel)
        self.assertIn("2/20 = 10%",panel)
        self.assertIn("2/20 = 10%",markdown(d))

    def test_focus_and_missing_dimension(self):
        d=record("analysis-focus");a=d["analysis"]
        self.assertEqual(d["events"][0]["input"]["focus"],a["focus"])
        self.assertIn("文具",a["questions"][0]["question"])
        self.assertIn("缺少月份",app.render(d,"case=analysis-focus"))
        self.assertIn("缺少月份",markdown(d))

    def test_invalid_field_cannot_draft(self):
        def bad(role,data,events,r):
            events.append(dict(role=role,status="ok",input=data))
            return {"questions":[{"question":"未知指标","query":dict(metric="合计",num="不存在",left={},right=None)}],"limitations":[]}
        d=analyze(self.sales,invoke=bad)
        self.assertEqual(d["status"],"运行失败");self.assertFalse(d["sentences"])
        self.assertNotIn("items",d);self.assertEqual(len(d["events"]),2)

    def test_comparison_scope(self):
        with self.assertRaises(ValueError):
            evaluate_question(self.rows,dict(metric="合计",num="销售额",left={"产品类别":"文具"},right={"季度":"一季度"}))

    def test_zero_observations(self):
        def plan(role,data,events,r):
            events.append(dict(role=role,status="ok"))
            return {"questions":[{"question":"比例？","query":dict(metric="比例",num="n",den="d",left={},right=None)}],"limitations":[]}
        raw=b"n,d\n0,0\n";d=analyze(raw,invoke=plan)
        self.assertEqual(d["status"],"无可核验发现");self.assertFalse(d["sentences"])
        self.assertIn("分母为零",markdown(d));self.assertEqual(reproduce(raw,d),0)

    def test_analysis_tamper(self):
        self.d["analysis"]["questions"][0]["result"]["left"]["value"]="888"
        with self.assertRaisesRegex(ValueError,"分析计算"):reproduce(self.sales,self.d)

    def test_draft_binding(self):
        self.d["analysis"]["questions"][0]["draft"]="伪造发现"
        with self.assertRaisesRegex(ValueError,"原句不一致"):reproduce(self.sales,self.d)

    def test_old_record(self):
        old=record("multi")
        self.assertEqual(reproduce((ROOT/"examples/conversion.csv").read_bytes(),old),7)
        self.assertTrue(markdown(old).startswith("# 数据结论审查报告"))
        self.assertIn("逐句审查结果",app.render(old,"case=multi"))

class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=app.ThreadingHTTPServer(("127.0.0.1",0),app.Handler)
        Thread(target=cls.server.serve_forever,daemon=True).start()
        cls.url=f"http://127.0.0.1:{cls.server.server_port}"
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close()
    def post(self,endpoint,payload):
        req=Request(self.url+endpoint,data=json.dumps(dict(token=app.TOKEN,**payload)).encode(),headers={"Content-Type":"application/json"})
        with urlopen(req,timeout=5) as r:return json.load(r)
    def test_csv_only_http(self):
        fixture=record("analysis-sales")
        steps=iter(fixture["events"])
        def replay(role,data,events,r):
            step=next(steps);self.assertEqual(step["role"],role)
            events.append(copy.deepcopy(step));return json.loads(step["visible"])
        csv=(ROOT/"examples/sales.csv").read_bytes()
        captured=[]
        with patch('discovery.call',side_effect=replay),patch('app.save',side_effect=lambda p,d:captured.append(d)):
            response=self.post('/analyze',{"csv":base64.b64encode(csv).decode()})
        self.assertIn('/view?run=',response['url']);self.assertEqual(captured[0]["status"],"已完成")
        self.assertEqual(captured[0]["analysis"]["focus"],"")
    def test_old_audit_http(self):
        csv=(ROOT/"examples/sales.csv").read_bytes()
        with patch('app.audit',return_value=record("multi")) as audit,patch('app.save'):
            self.post('/audit',{"csv":base64.b64encode(csv).decode(),"claims":"  一句结论。  "})
            audit.assert_called_once_with(csv,["一句结论。"])
    def test_file_required(self):
        with self.assertRaises(HTTPError) as cm:self.post('/analyze',{})
        self.assertEqual(cm.exception.code,400)
    def test_downloads(self):
        for n in ["analysis-sales","analysis-conversion","analysis-focus","injected"]:
            with urlopen(self.url+"/export.json?case="+n) as r:d=json.load(r)
            with urlopen(self.url+"/export.md?case="+n) as r:self.assertEqual(r.read().decode(),markdown(d))
            with urlopen(self.url+"/view?case="+n) as r:self.assertIn(d["run_id"],r.read().decode())

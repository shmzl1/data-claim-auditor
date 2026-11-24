import copy,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from stats import *
from audit import reproduce,lock,scope_issues,audit,check_edits
from app import render
from reporting import markdown

class AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw=(ROOT/"examples/conversion.csv").read_bytes()
        cls.rows=read_csv(cls.raw)
        cls.multi=json.loads((ROOT/"evidence/multi.json").read_text("utf8"))
        cls.injected=json.loads((ROOT/"evidence/injected.json").read_text("utf8"))
    def query(self,**kw):
        q=dict(id="A1",metric="比例",num="转化人数",den="人数",left={"月份":"5月"},right={"月份":"4月"},target=None,op="高于")
        q.update(kw);return q
    def test_weighted(self):
        r=execute(self.rows,self.query());self.assertEqual([r[x]["value"] for x in ("left","right")],["64.0","26.0"])
    def test_group(self):
        q=self.query(left={"月份":"5月","用户类型":"老用户"},right={"月份":"4月","用户类型":"老用户"})
        self.assertEqual(execute(self.rows,q)["verdict"],CONTRADICTED)
    def test_wrong_denominator(self):
        r=execute(self.rows,self.query(left={"月份":"5月","用户类型":"新用户"},right=None,target=1,op="等于"))
        self.assertEqual((r["left"]["numerator"],r["left"]["denominator"],r["verdict"]),("2","20",CONTRADICTED))
    def test_zero(self):
        rows=[{"n":"0","d":"0"}];r=execute(rows,self.query(num="n",den="d",left={},right=None,target=0))
        self.assertEqual(r["verdict"],INSUFFICIENT)
    def test_absent(self):
        self.assertIn("缺少字段",execute(self.rows,self.query(den="性别"))["reason"])
    def test_empty_group(self):
        self.assertEqual(execute(self.rows,self.query(left={"月份":"6月"}))["verdict"],INSUFFICIENT)
    def test_bad_numeric(self):
        rows=copy.deepcopy(self.rows);rows[2]["转化人数"]="NaN";self.assertEqual(execute(rows,self.query())["verdict"],INSUFFICIENT)
    def test_unphysical(self):
        rows=copy.deepcopy(self.rows);rows[2]["转化人数"]="100";self.assertEqual(execute(rows,self.query())["verdict"],INSUFFICIENT)
    def test_allowlist(self):
        with self.assertRaises(ValueError):validate(self.query(metric="import os"))
    def test_multiple_targets(self):
        with self.assertRaises(ValueError):validate(self.query(target=1))
    def test_duplicate_columns(self):
        with self.assertRaises(ValueError):read_csv(b'a,a\n1,2')
    def test_ragged(self):
        with self.assertRaises(ValueError):read_csv(b'a,b\n1')
    def test_utf8_bom(self):
        self.assertEqual(read_csv(b'\xef\xbb\xbf'+self.raw),self.rows)
    def test_sum(self):
        self.assertEqual(execute(self.rows,self.query(metric="合计",right=None,target=128,op="等于"))["verdict"],SUPPORTED)
    def test_count(self):
        self.assertEqual(execute(self.rows,self.query(metric="计数",right=None,target=2,op="等于"))["verdict"],SUPPORTED)
    def test_mean(self):
        self.assertEqual(execute(self.rows,self.query(metric="均值",right=None,target=64,op="等于"))["verdict"],SUPPORTED)
    def test_exact_fraction(self):
        self.assertEqual(number("0.1")+number("0.2"),number("0.3"))
    def test_multi(self):
        self.assertEqual({e["role"] for e in self.multi["events"]},{"解析","复算","审查","编辑"})
        self.assertEqual([i["verdict"] for i in self.multi["items"]],[SUPPORTED,CONTRADICTED,CONTRADICTED,INSUFFICIENT,INSUFFICIENT,SUPPORTED])
    def test_injection(self):
        a,b=self.injected["rounds"];self.assertTrue(a["review"]);self.assertEqual(a["locked"],[INSUFFICIENT]);self.assertEqual(b["locked"],[CONTRADICTED])
        self.assertTrue(any(e["role"]=="复算" and e["input"].get("feedback") for e in self.injected["events"]))
    def test_replay(self):self.assertGreater(reproduce(self.raw,self.multi),0)
    def test_hash_mismatch(self):
        with self.assertRaises(ValueError):reproduce(self.raw+b'\n',self.multi)
    def test_changed_result(self):
        d=copy.deepcopy(self.multi);d["rounds"][0]["results"][0]["left"]["numerator"]="5"
        with self.assertRaises(ValueError):reproduce(self.raw,d)
    def test_changed_verdict(self):
        d=copy.deepcopy(self.multi);d["items"][0]["verdict"]=INSUFFICIENT
        with self.assertRaises(ValueError):reproduce(self.raw,d)
    def test_no_model(self):
        with patch("model.urlopen",side_effect=OSError),patch.dict("os.environ",DEEPSEEK_API_KEY="offline"):
            d=audit(self.raw,["总体上升"]);self.assertEqual(d["status"],"运行失败");self.assertNotIn("items",d)
    def test_output(self):
        self.assertIn("126",markdown(self.multi));self.assertIn("人工注入",render(self.injected,"case=injected"))
    def test_no_executable_upload(self):
        d=copy.deepcopy(self.multi);d["sentences"][0]["text"]="<script>alert(1)</script>"
        self.assertIn("&lt;script&gt;",render(d,"case=multi"))
if __name__=="__main__":unittest.main()

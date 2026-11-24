import copy,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from trend import decompose
from adjudication import decide,enrich_checks
from audit import reproduce,audit,scope_issues
from discovery import analyze
from stats import read_csv
from app import render
from reporting import markdown

def run_record(folder,name):
    return json.loads((ROOT/"evidence/enhancements"/folder/(name+".json")).read_text("utf8"))

class TrendTests(unittest.TestCase):
    def setUp(self):
        self.raw=(ROOT/"examples/conversion.csv").read_bytes();self.rows=read_csv(self.raw)
        self.record=run_record("trend","conversion")
        self.spec=self.record["analysis"]["trend"]["spec"]
    def calc(self):return decompose(self.rows,self.spec)
    def test_exact_conversion(self):
        d=self.calc();self.assertEqual((d["composition"],d["within"],d["delta"]),("48","-10","38"))
        self.assertEqual(d["status"],"严格反转");self.assertEqual(d["rates"],["26","64"])
    def test_renamed_three_groups(self):
        d=run_record("trend","clinic");self.assertEqual(reproduce((ROOT/"examples/clinic.csv").read_bytes(),d),8)
        r=d["analysis"]["trend"]["result"];self.assertEqual((r["rates"],r["composition"],r["within"]),(["38","58"],"30","-10"))
    def test_same_direction(self):
        self.rows[2]["转化人数"]="6";self.rows[3]["转化人数"]="162"
        self.assertEqual(self.calc()["status"],"未发现严格反转")
    def test_partial(self):
        self.rows[2]["转化人数"]="6";self.assertEqual(self.calc()["status"],"未发现严格反转")
    def test_tied_group(self):
        self.rows[2]["转化人数"]="4";self.assertEqual(self.calc()["status"],"未发现严格反转")
    def test_zero_denominator(self):
        self.rows[2]["人数"]="0";self.rows[2]["转化人数"]="0"
        self.assertIn("5月／新用户",self.calc()["reason"])
    def test_missing_group(self):
        self.rows.pop();d=self.calc();self.assertIn("5月缺少老用户",d["reason"]);self.assertNotIn("delta",d)
    def test_new_group(self):
        self.rows[2]["用户类型"]="其他";self.assertIn("4月缺少其他",self.calc()["reason"])
    def test_repeated_rows(self):
        before=self.calc();row=self.rows.pop(0)
        self.rows.extend([dict(row,人数="90",转化人数="18")]*2);self.assertEqual(self.calc(),before)
    def test_unknown_semantics(self):
        d=decompose(self.rows,dict(status="待确认",reason="分子是人数还是金额？"));self.assertIn("金额",d["reason"])
    def test_sales_control(self):
        d=run_record("trend","sales");self.assertEqual(d["analysis"]["trend"]["result"]["status"],"不适用")
        self.assertEqual(d["status"],"已完成")
    def test_export_replay(self):
        self.assertEqual(reproduce(self.raw,self.record),6)
        for view in [render(self.record,"case=trend-conversion"),markdown(self.record)]:
            self.assertIn("+48 个百分点",view);self.assertIn("10% → 90%",view)
        self.record["analysis"]["trend"]["result"]["composition"]="47"
        with self.assertRaises(ValueError):reproduce(self.raw,self.record)

class DisputeTests(unittest.TestCase):
    def test_five_pairs(self):
        from experiments.enhancement_score import score
        s=score();self.assertEqual(s["totals"]["after"],dict(corrected=[2,2],incorrectly_changed=[0,2],ambiguous_deferred=[1,1]))
    def test_equal_values_different_rows(self):
        decision=run_record("after","equal")["rounds"][0]["decisions"][0]
        self.assertEqual(decision["action"],"修改")
        self.assertEqual(decision["current"]["percent"],decision["alternative"]["percent"])
        self.assertNotEqual(decision["current"]["den_rows"],decision["alternative"]["den_rows"])
    def test_wrong_suggestion(self):
        d=run_record("after","bad");v=d["rounds"][0]["decisions"][0]
        self.assertEqual((v["action"],v["current"]["den_sum"],v["alternative"]["den_sum"]),("保留","20","200"))
        self.assertEqual(len(d["rounds"]),1)
        for view in (render(d,"case=decision-bad"),markdown(d)):
            self.assertIn("分歧裁决",view);self.assertIn("200",view)
    def test_ambiguous(self):
        d=run_record("after","unclear");self.assertEqual(d["status"],"待人工核查")
        self.assertFalse(d.get("items"));self.assertIn("原句不能唯一",markdown(d))
    def test_tamper(self):
        d=run_record("after","bad");d["rounds"][0]["decisions"][0]["current"]["num_rows"]=[]
        with self.assertRaises(ValueError):reproduce((ROOT/"examples/conversion.csv").read_bytes(),d)
    def test_both_sides(self):
        rows=read_csv((ROOT/"examples/conversion.csv").read_bytes())
        q=dict(id="A1",metric="比例",num="转化人数",den="人数",left={"月份":"5月","用户类型":"新用户"},right={"月份":"4月"},op="低于")
        alt=dict(num=q["num"],den=q["den"],num_filters={"月份":"4月","用户类型":"新用户"},den_filters={"月份":"4月","用户类型":"新用户"})
        v=decide(rows,"5月新用户的转化率低于4月新用户的转化率",q,dict(reason="右侧漏组",side="right",alternative=alt))
        self.assertEqual(v["action"],"修改");self.assertEqual(v["side"],"right")
    def test_unstructured(self):
        d=run_record("after","bad");q=d["rounds"][0]["executed"][0]
        self.assertEqual(decide([],d["sentences"][0]["text"],q,dict(reason="范围有误"))["action"],"待确认")

class RuntimeRegressionTests(unittest.TestCase):
    def test_downward_reversal(self):
        raw=(ROOT/"examples/conversion.csv").read_bytes()
        spec=copy.deepcopy(run_record("trend","conversion")["analysis"]["trend"]["spec"])
        spec["periods"].reverse()
        r=decompose(read_csv(raw),spec)
        self.assertEqual((r["status"],r["delta"],r["composition"],r["within"]),("严格反转","-38","-48","10"))

    def test_program_can_ground_omitted_filter(self):
        d=run_record("after","missing");a=d["rounds"][0]
        rows=read_csv((ROOT/"examples/conversion.csv").read_bytes());lines=[d["sentences"][0]["text"]]
        issues=enrich_checks(rows,lines,a["atoms"],a["executed"],[],scope_issues(a["atoms"],a["executed"]))
        self.assertEqual(decide(rows,lines[0],a["executed"][0],issues[0])["action"],"修改")

    def test_deictic_without_reviewer_vote(self):
        d=run_record("after","unclear");a=d["rounds"][0]
        rows=read_csv((ROOT/"examples/equal.csv").read_bytes());line=d["sentences"][0]["text"]
        issues=enrich_checks(rows,[line],a["atoms"],a["executed"],[],[])
        self.assertEqual(decide(rows,line,a["executed"][0],issues[0])["action"],"待确认")

    def test_final_pipeline_with_recorded_model_responses(self):
        for folder in ["after","trend"]:
            for p in sorted((ROOT/"evidence/enhancements"/folder).glob("*.json")):
                d=json.loads(p.read_text("utf8"));events=iter(d["events"])
                def replay(role,data,trace,r):
                    e=next(events);self.assertEqual((role,r),(e["role"],e["round"]))
                    trace.append(copy.deepcopy(e));return e.get("experiment_override",json.loads(e["visible"]))
                name=p.stem if folder=="trend" else ("equal" if p.stem in ("equal","unclear") else "conversion")
                raw=(ROOT/"examples"/(name+".csv")).read_bytes()
                result=analyze(raw,invoke=replay) if folder=="trend" else audit(raw,[x["text"] for x in d["sentences"]],invoke=replay)
                self.assertEqual(result["rounds"],d["rounds"]);self.assertEqual(result["status"],d["status"])
                self.assertIsNone(next(events,None));reproduce(raw,result)

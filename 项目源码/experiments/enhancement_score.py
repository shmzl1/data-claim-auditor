"""从落盘 Web 导出核对配对结果。只比较最终查询实际选中的范围和状态。"""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from audit import reproduce,save
BASE=ROOT/"evidence/enhancements"

def load(path):return json.loads(path.read_text("utf8"))

def score():
    cases=load(ROOT/"experiments/disputes.json");paired=[]
    totals={}
    for phase in ("before","after"):
        corrected=changed=deferred=0
        for case in cases:
            name=case["name"];run=load(BASE/phase/(name+".json"))
            raw=(ROOT/"examples"/(case["file"]+".csv")).read_bytes()
            reproduce(raw,run)
            assert run["sentences"][0]["text"]==case["line"]
            last=run["rounds"][-1];query=last["executed"][0]
            good=(run["status"]=="已完成" and run["items"][0]["verdict"]=="数据支持" and query["metric"]=="比例"
                  and query["left"]=={"月份":"5月","用户类型":"新用户"} and query["num"]=="转化人数" and query["den"]=="人数")
            if case["expect"]=="修改":corrected+=good
            if case["expect"]=="保留":changed+=bool(run["status"]=="已完成" and not good)
            if case["expect"]=="待确认":deferred+=run["status"]=="待人工核查" and not run.get("items")
            paired.append(dict(phase=phase,case=name,run=run["run_id"],status=run["status"],calls=len(run["events"]),
                               rounds=len(run["rounds"]),final_filters=query.get("left"),
                               adjudication=[v["action"] for step in run["rounds"] for v in step.get("decisions",[])]))
        totals[phase]=dict(corrected=[corrected,2],incorrectly_changed=[changed,2],ambiguous_deferred=[deferred,1])
    return dict(baseline_commit="6e221543e1a46368b483af0749ead2ca12bcafeb",paired=paired,totals=totals)

if __name__=="__main__":
    result=score();save(BASE/"comparison.json",result);print(json.dumps(result["totals"],ensure_ascii=False))

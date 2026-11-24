"""离线评分与反事实校验；参考答案在模型调用完成后读取。"""
import copy, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from audit import reproduce,save

def score():
    raw=(ROOT/"examples/conversion.csv").read_bytes()
    reference=json.loads((ROOT/"experiments/reference.json").read_text("utf8"))
    runs={name:json.loads((ROOT/"evidence"/(name+".json")).read_text("utf8")) for name in ("single","multi","injected","single-pilot")}
    modes={}
    for name,d in runs.items():
        checks=reproduce(raw,d)
        modes[name]=dict(status=d["status"],run_id=d["run_id"],calls=len(d["events"]),seconds=round(sum(x["seconds"] for x in d["events"]),3),
                         tokens=sum((x.get("usage") or {}).get("total_tokens",0) for x in d["events"]),replayed=checks)
    assert runs["single"]["sentences"]==runs["multi"]["sentences"] and runs["single"]["sha256"]==runs["multi"]["sha256"]
    labels=[[i["verdict"] for i in runs[n]["items"]] for n in ("single","multi")]
    if not len(reference)==len(labels[0])==len(labels[1]): raise ValueError("样本数不一致")
    rows=[dict(text=s["text"],reference=g,single=a,multi=b) for s,g,a,b in zip(runs["multi"]["sentences"],reference,*labels)]
    d=runs["multi"]
    altered=copy.deepcopy(d);altered["rounds"][0]["results"][0]["left"]["denominator"]="99999"
    invalid=[]
    for name,csv,doc in [("更改一个 CSV 人数",raw.replace(b"180,36",b"181,36",1),d),("更改报告分母",raw,altered)]:
        try: reproduce(csv,doc)
        except ValueError as err:invalid.append(dict(test=name,detected=True,message=str(err)))
        else:raise AssertionError("篡改未检出")
    return dict(rows=rows,modes=modes,corrected=sum(r["single"]!=r["reference"]==r["multi"] for r in rows),
                regressed=sum(r["single"]==r["reference"]!=r["multi"] for r in rows),extra_calls=modes["multi"]["calls"]-modes["single"]["calls"],tamper=invalid)
if __name__=="__main__":
    result=score();save(ROOT/"evidence/summary.json",result);print(json.dumps(result,ensure_ascii=False,indent=2))

import json
from stats import INSUFFICIENT

def filters(f):
    return "、".join(f"{k}={v}" for k,v in f.items()) or "全部记录"

def evidence_text(q,r):
    parts=[]
    for side in ("left","right"):
        if side not in r:continue
        x=r[side]
        fraction=f"{x['num_field']} 合计 {x['numerator']}"
        if x["den_field"]:fraction+=f" / {x['den_field']} 合计 {x['denominator']}"
        parts.append(f"{filters(x['filters'])}（{x['rows']} 行）　{fraction} → {x['value']}{x['unit']}")
    if "target" in r:parts.append("声明值 "+r["target"]+("%" if q["metric"]=="比例" else ""))
    if r.get("reason"):parts.append(r["reason"])
    return parts

def markdown(d):
    def literal(s):
        return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace("\n"," ")
    parts=["# 数据结论审查报告","",f"运行编号 `{d['run_id']}`",f"CSV SHA-256 `{d['sha256']}`",f"状态　{d['status']}"]
    if d.get("injection"):parts.append(d["injection"])
    if d.get("mode")=="analysis":
        parts[0]="# 数据分析报告"
        parts+=["","## 已核验的发现"]
        if not d.get("items"):
            parts.append("当前尚无已定稿发现，请查阅下方的计算结果与数据局限。")
        for i in d.get("items",[]):
            text=d["sentences"][i["source"]-1]["text"]
            parts.append("- "+i["verdict"]+"　"+literal(text))
            if i["verdict"]!="数据支持":
                parts.append("  - 修改建议　"+literal(i["suggestion"]))
        discovery=d["analysis"]
        parts+=["","## 系统提出的问题与观察","关注点　"+literal(discovery["focus"] or "由系统自主选题")]
        for q in discovery["questions"]:
            parts+=["","### "+literal(q["id"]+"　"+q["question"])]
            parts+=["- "+literal(line) for line in evidence_text(q["query"],q.get("result",{}))]
            if q.get("error"):parts.append("计算受限　"+literal(q["error"]))
        for reason in discovery["limitations"]:parts.append("数据局限　"+literal(reason))
    final={i["source"]:i for i in d.get("items",[])}
    for sentence in d["sentences"]:
        n=sentence["source"];parts+=["",f"## {n}. "+literal(sentence["text"])]
        if n in final:
            i=final[n];parts.extend([i["verdict"],"",literal(i["reason"]),"", "建议　"+literal(i["suggestion"])])
        for step in d["rounds"]:
            atoms={a["id"]:a for a in step["atoms"]}
            for q,r in zip(step["executed"],step["results"]):
                a=atoms[q["id"]]
                if a["source"]==n:
                    parts+=["",f"第 {step['round']} 轮 · {literal(a['claim'])} · {literal(q['metric'])} "+literal(q.get("op",""))]
                    parts+=["- "+literal(line) for line in evidence_text(q,r)]
            for issue in step.get("review",[])+step.get("program_checks",[]):
                if atoms[issue["id"]]["source"]==n:parts+=["- 退回"+issue["target"]+"："+literal(issue["reason"])+"。"+literal(issue["fix"])]
    parts+=["","## 离线复算","保留原 CSV 并下载同编号 JSON，执行 `python audit.py 原数据.csv 审查记录.json`。此命令重放受控请求、检查输入指纹与逐句判定。"]
    return "\n".join(parts)+"\n"

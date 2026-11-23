import argparse, copy, json, re, uuid
from pathlib import Path
from model import call
from stats import read_csv,profile,validate,execute,digest,SUPPORTED,CONTRADICTED,INSUFFICIENT

ROOT=Path(__file__).resolve().parent
def save(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),"utf8");tmp.replace(path)

def check_atoms(out,count):
    atoms=out["atoms"]
    if not isinstance(atoms,list) or not 1<=len(atoms)<=60:raise ValueError("atoms 数量错误")
    for a in atoms:
        if not re.fullmatch(r"A[1-9]\d*",a["id"]) or type(a["source"])!=int or a["kind"] not in ("描述","因果") or not isinstance(a["claim"],str) or not a["claim"].strip() or not isinstance(a["scope"],dict) or not all(isinstance(k,str) and isinstance(v,str) for k,v in a["scope"].items()):raise ValueError("原子主张字段不完整")
    if len({a["id"] for a in atoms})!=len(atoms) or {a["source"] for a in atoms}!=set(range(1,count+1)):raise ValueError("原句未完整覆盖或编号重复")
    return atoms

def check_queries(out,atoms):
    qs=out["queries"]
    if not isinstance(qs,list) or len(qs)!=len(atoms) or {q["id"] for q in qs}!={a["id"] for a in atoms}:raise ValueError("计算请求未逐项覆盖")
    for q in qs:validate(q)
    return qs

def check_issues(out,atoms):
    items=out["issues"]
    if not isinstance(items,list):raise ValueError("issues 应为列表")
    for i in items:
        if i["id"] not in {a["id"] for a in atoms} or i["target"] not in ("解析","复算") or not all(isinstance(i[k],str) and i[k].strip() for k in ("reason","fix")):raise ValueError("异议缺少可执行反馈")
    return items

def check_edits(out,locked):
    items=out["items"]
    if len(items)!=len(locked) or {i["source"] for i in items}!=set(range(1,len(locked)+1)):raise ValueError("定稿遗漏或重复")
    for i in items:
        if type(i["source"])!=int or i["verdict"]!=locked[i["source"]-1] or not all(isinstance(i[k],str) and i[k].strip() for k in ("reason","suggestion")):raise ValueError("定稿与锁定证据不符")
    return sorted(items,key=lambda x:x["source"])

def scope_issues(atoms,qs):
    by_id={q["id"]:q for q in qs};issues=[]
    for a in atoms:
        q=by_id[a["id"]]
        if q["metric"]=="不可检验":continue
        filters=[q["left"]]+([q["right"]] if q.get("right") is not None else [])
        if a["kind"]=="因果" or any(any(f.get(k)!=v for k,v in a["scope"].items()) for f in filters):
            issues.append(dict(id=a["id"],target="复算",reason="描述计算不能证明因果，或请求缺少该主张的限定人群",fix="核查证据类型并补齐每个比较侧的分组筛选"))
    return issues

def lock(atoms,qs,results,n):
    blocked={i["id"] for i in scope_issues(atoms,qs)}
    by_id={q["id"]:r["verdict"] for q,r in zip(qs,results)}
    labels=[]
    for source in range(1,n+1):
        vals=[INSUFFICIENT if a["id"] in blocked else by_id[a["id"]] for a in atoms if a["source"]==source]
        labels.append(CONTRADICTED if CONTRADICTED in vals else INSUFFICIENT if INSUFFICIENT in vals else SUPPORTED)
    return labels

def audit(raw,lines,mode="multi",inject=False,path=None,invoke=None,discovery_context=None):
    rows=read_csv(raw);invoke=invoke or call
    if mode not in ("single","multi") or not 1<=len(lines)<=20 or any(not isinstance(s,str) or not 1<=len(s.strip())<=1500 for s in lines):raise ValueError("请输入 1 至 20 条结论，每行一句")
    base=dict(sentences=[dict(source=i+1,text=s) for i,s in enumerate(lines)],schema=profile(rows))
    if discovery_context is not None:
        base["探索口径"]=discovery_context
        base["核验提示"]="独立核查候选句。方向或大小比较属于描述；仅明确归因时标为因果。scope 只含两侧共同限定，不能包含被比较的两个不同类别、月份或季度。单一范围对常数的比较保留该范围。"
    d=dict(version=1,run_id=uuid.uuid4().hex,mode=mode,injection="人工注入：去掉首轮分组限定" if inject else None,sha256=digest(raw),row_count=len(rows),**base,events=[],rounds=[],status="运行中")
    def persist():
        if path:save(path,d)
    def ask(role,r,extra,checker):
        data=dict(base,**extra)
        for attempt in range(2):
            out=invoke(role,copy.deepcopy(data),d["events"],r)
            try:return checker(out)
            except (KeyError,ValueError,TypeError,IndexError) as err:
                msg=str(err)[:200];d["events"][-1].update(status="invalid",validation_error=msg)
                if attempt:raise ValueError(role+"输出协议错误："+msg) from None
                data=dict(data,format_feedback=msg,previous_output=out)
            finally:persist()
    try:
        if mode=="single":
            def both(o):
                atoms=check_atoms(o,len(lines));return atoms,check_queries(o,atoms)
            atoms,qs=ask("单角色",1,{"stage":"plan"},both)
        else:atoms=ask("解析",1,{},lambda o:check_atoms(o,len(lines)))
        feedback=[];previous=None;seen=set()
        for r in range(1,4):
            if mode=="multi":qs=ask("复算",r,dict(atoms=atoms,feedback=feedback,previous=previous),lambda o:check_queries(o,atoms))
            actual=copy.deepcopy(qs)
            if inject and r==1:
                scopes={a["id"]:a["scope"] for a in atoms}
                for q in actual:
                    for side in ("left","right"):
                        if isinstance(q.get(side),dict):
                            for field in scopes[q["id"]]:q[side].pop(field,None)
            results=[execute(rows,q) for q in actual]
            step=dict(round=r,atoms=atoms,proposed=qs,executed=actual,results=results,locked=lock(atoms,actual,results,len(lines)))
            d["rounds"].append(step);persist()
            if mode=="single":break
            objections=ask("审查",r,dict(atoms=atoms,executed=actual,results=results),lambda o:check_issues(o,atoms))
            step["review"]=objections
            step["program_checks"]=scope_issues(atoms,actual)
            feedback=objections+step["program_checks"]
            if not feedback:break
            # 仅反馈给下一轮所需的上轮产物，避免递归复制旧日志。
            previous=dict(executed=actual,results=results)
            signature=json.dumps([atoms,actual,[(i["id"],i["target"]) for i in feedback]],sort_keys=True,ensure_ascii=False)
            if r==3 or signature in seen:
                d.update(status="待人工核查",unresolved=feedback);return d
            seen.add(signature)
            if any(i["target"]=="解析" for i in feedback):
                atoms=ask("解析",r+1,dict(previous_atoms=atoms,feedback=feedback),lambda o:check_atoms(o,len(lines)))
        items=ask("单角色" if mode=="single" else "编辑",r,dict(stage="edit",locked=step["locked"],atoms=atoms,executed=actual,results=results),lambda o:check_edits(o,step["locked"]))
        d.update(status="已完成",items=items)
    except (RuntimeError,ValueError,KeyError,TypeError) as err:
        d.update(status="运行失败",error=str(err))
    finally:persist()
    return d

def reproduce(raw,d):
    if digest(raw)!=d["sha256"]:raise ValueError("CSV 的 SHA-256 与报告不符")
    rows=read_csv(raw)
    checks=0
    if d.get("version")==2 and d.get("mode")!="analysis":raise ValueError("分析记录模式不一致")
    if d.get("mode")=="analysis":
        from discovery import replay_analysis
        checks=replay_analysis(rows,d)
    if not d["rounds"] and not (d.get("mode")=="analysis" and d["status"] in ("无可核验发现","运行失败")):
        raise ValueError("报告中无可复算轮次")
    for step in d["rounds"]:
        if len(step["executed"])!=len(step["results"]):raise ValueError("请求与结果数量不同")
        actual=[execute(rows,q) for q in step["executed"]]
        if actual!=step["results"] or lock(step["atoms"],step["executed"],actual,len(d["sentences"]))!=step["locked"]:raise ValueError("重算证据与报告不一致")
        checks+=len(actual)
    if d["status"]=="已完成":check_edits(d,d["rounds"][-1]["locked"])
    return checks

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("csv",type=Path);p.add_argument("report",type=Path)
    args=p.parse_args();print("复算一致，原子查询数：",reproduce(args.csv.read_bytes(),json.loads(args.report.read_text("utf8"))))

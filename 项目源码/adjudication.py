"""对单侧比例范围异议回查 CSV。没有可唯一定位的文本锚点时不作语义猜测。"""
import re
from fractions import Fraction
from stats import number

def snapshot(rows,spec):
    result={"spec":spec}
    for name,key in (("num","num_filters"),("den","den_filters")):
        filters=spec[key];field=spec[name]
        if not isinstance(filters,dict) or not isinstance(field,str) or field not in rows[0] or not set(filters)<=rows[0].keys():
            raise ValueError("争议字段或筛选未能绑定到表头")
        indices=[i for i,row in enumerate(rows,1) if all(row[k]==v for k,v in filters.items())]
        result[name+"_rows"]=indices
        result[name+"_sum"]=str(sum(number(rows[i-1][field]) for i in indices))
    den=Fraction(result["den_sum"])
    result["percent"]=str(100*Fraction(result["num_sum"])/den) if den else None
    return result

def ground(line,rows,q,side,allow_short=True):
    """只裁决能从原句唯一绑定的等值限定，不从解析角色的猜测推导范围。"""
    n,d=q["num"],q["den"]
    metric=re.escape(n)+"占"+re.escape(d)+"的比例"
    text=line.strip().rstrip("。.")
    if q.get("right") is None:
        m=re.fullmatch(r"(.+?)(?:为|是|等于)(\d+(?:\.\d+)?)%",text)
        if not m or q.get("op")!="等于" or number(q["target"])!=number(m[2]):return None
        clause=m[1]
    else:
        parts=text.split(q["op"])
        if len(parts)!=2:return None
        clause=parts[0 if side=="left" else 1]
    m=re.fullmatch(r"(.+?)(?:中[，,]?|的)(?:"+metric+")",clause)
    if not m and allow_short:
        short=re.fullmatch(r"(.+?)的([^，。]+)率",clause)
        if short and n.startswith(short[2]):m=short
    if not m:return None
    prefix=m[1]
    if len(prefix)>100:return None
    pairs={(k,row[k]) for row in rows for k in row if k not in (n,d) and row[k] and row[k] in prefix}
    solutions=[];remaining=2500
    def match(rest,chosen):
        nonlocal remaining
        remaining-=1
        if remaining<=0 or len(solutions)>1:return
        if not rest:solutions.append(chosen);return
        for k,v in pairs:
            if k not in chosen and rest.startswith(v):
                match(rest[len(v):].lstrip(" 、，,"),dict(chosen,**{k:v}))
    match(prefix,{})
    return solutions[0] if remaining>0 and len(solutions)==1 else None

def enrich_checks(rows, lines, atoms, queries, objections, checks):
    """在没有结构化模型建议时，用可唯一读出的原句生成程序的备选口径。"""
    by_id={q["id"]:q for q in queries}
    sources={a["id"]:lines[a["source"]-1] for a in atoms}
    proposed={i["id"] for i in objections if i.get("alternative")}
    enriched=[]
    for check in checks:
        q=by_id[check["id"]]
        alternatives=[]
        if q["id"] not in proposed and q["metric"]=="比例":
            for side in ("left","right"):
                if not isinstance(q.get(side),dict):continue
                expected=ground(sources[q["id"]],rows,q,side)
                if expected is not None and expected!=q[side]:
                    alternatives.append(dict(check,side=side,alternative=dict(
                        num=q["num"],den=q["den"],num_filters=expected,den_filters=expected)))
        enriched.extend(alternatives or [check])
    for atom in atoms:
        q=by_id[atom["id"]];line=sources[q["id"]]
        if q["id"] in proposed or q["metric"]!="比例":continue
        if re.search(r"该组|该人群|该群体",line) and ground(line,rows,q,"left") is None:
            enriched.append(dict(id=q["id"],target="复算",side="left",alternative={},
                reason="原句使用未绑定的群体指代",fix="请明确该组是哪组"))
    return enriched


def decide(rows,line,q,issue):
    side=issue.get("side");alt=issue.get("alternative")
    decision=dict(source_text=line,id=q["id"],side=side,objection=issue["reason"],action="待确认")
    if not alt:
        decision.update(actual_query=q,suggestion=issue.get("fix",""),basis="异议缺少可执行的替代口径，无法核对两套对象，请确认。")
        return decision
    try:
        if side not in ("left","right") or not isinstance(q.get(side),dict) or q["metric"]!="比例":
            raise ValueError("争议未定位到可比较的比例侧")
        current=dict(num=q["num"],den=q["den"],num_filters=q[side],den_filters=q[side])
        decision["current"]=snapshot(rows,current)
        decision["alternative"]=snapshot(rows,alt)
        same_fields=(alt["num"],alt["den"])==(q["num"],q["den"])
        old_scope=ground(line,rows,q,side,same_fields)
        other=dict(q,num=alt["num"],den=alt["den"])
        new_scope=ground(line,rows,other,side,same_fields)
        if old_scope is None and new_scope is None:
            raise ValueError("原句不能唯一确定本侧群体、指标或比较对象，请作者澄清")
        decision["expected_filters"]=old_scope if old_scope is not None else new_scope
        def fits(spec,scope):
            return scope is not None and spec["num_filters"]==scope and spec["den_filters"]==scope
        if fits(current,old_scope) and not fits(alt,new_scope):
            if decision["current"]["percent"] is None:raise ValueError("原口径没有非零分母，请确认")
            decision.update(action="保留",basis="原句限定的群体与原计算的分子、分母范围均相符；替代口径改变了统计对象")
        elif fits(alt,new_scope) and not fits(current,old_scope):
            if decision["alternative"]["percent"] is None:raise ValueError("建议口径没有非零分母，请确认")
            if not same_fields and q.get("right") is not None:raise ValueError("两侧指标字段更换需重新确认整条比较")
            decision.update(action="修改",basis="替代筛选与原句逐项相符，原计算遗漏或错选群体，须补算")
        else:raise ValueError("两种口径未形成唯一可验证的取舍")
    except (ValueError,KeyError,TypeError) as exc:decision["basis"]=str(exc)
    return decision

def decision_lines(dec):
    lines=[f"{dec['action']}　{dec['source_text']}　[{dec['id']} / {dec['side']}]　{dec['objection']}"]
    if "actual_query" in dec:lines+=[f"实际请求：{dec['actual_query']}；建议：{dec['suggestion']}"]
    for k,label in (("current","实际"),("alternative","建议")):
        if k not in dec:continue
        z=dec[k];s=z["spec"]
        def rows(ids):return ",".join(map(str,ids[:12]))+("…" if len(ids)>12 else "")
        lines.append(f"{label}：{s['num']} {s['num_filters']} 数据行 [{rows(z['num_rows'])}] 合计 {z['num_sum']} / {s['den']} {s['den_filters']} 数据行 [{rows(z['den_rows'])}] 合计 {z['den_sum']}")
        if z["percent"] is not None:lines[-1]+=f" ＝ {float(Fraction(z['percent'])):.6g}%"
    return lines+[dec["basis"]]

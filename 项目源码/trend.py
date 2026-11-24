"""两期率的对称分解。存储百分数和百分点的精确有理数，显示才舍入。"""
from collections import defaultdict
from fractions import Fraction
from stats import number

def decompose(rows,spec):
    if not isinstance(spec,dict):
        return {"status":"待确认","reason":"请明确时期、群体、分子及对应总人数。"}
    if spec.get("status") in ("不适用","待确认"):
        return {"status":spec["status"],"reason":str(spec.get("reason") or "缺少可辨认的时期、群体或人数比率")}
    if spec.get("status")!="可计算":return {"status":"待确认","reason":"请确认字段含义和两个可比时期"}
    try:
        t,g,n,d=(spec[k] for k in ("period","group","num","den"))
        if len({t,g,n,d})!=4 or not {t,g,n,d}<=rows[0].keys():raise ValueError("四项字段必须互异并存在于表头")
        periods=spec["periods"]
        if not isinstance(periods,list) or len(periods)!=2 or len(set(periods))!=2:raise ValueError("需要明确先后顺序的两个时期")
        counts=[defaultdict(lambda:[0,0]),defaultdict(lambda:[0,0])]
        excluded=set()
        for index,row in enumerate(rows,1):
            if not row[t].strip():raise ValueError(f"数据行 {index} 缺少时期")
            if row[t] not in periods:
                excluded.add(row[t]);continue
            name=row[g]
            if not name.strip():raise ValueError(f"数据行 {index} 缺少组别")
            a,b=number(row[n]),number(row[d])
            if b<=0 or a<0 or a>b or a.denominator!=1 or b.denominator!=1:
                raise ValueError(f"{row[t]}／{name} 数据行 {index} 人数无效（分子 {a}，分母 {b}）")
            cell=counts[periods.index(row[t])][name];cell[0]+=int(a);cell[1]+=int(b)
        for period,bucket in zip(periods,counts):
            if not bucket:raise ValueError(f"{period} 没有可比记录")
        different=set(counts[0])^set(counts[1])
        if different:raise ValueError("两期组别不齐："+"；".join(f"{period}缺少{key}" for key in sorted(different) for period,b in zip(periods,counts) if key not in b))
        totals=[[sum(x[i] for x in bucket.values()) for i in (0,1)] for bucket in counts]
        overall=[Fraction(a,b)*100 for a,b in totals];delta=overall[1]-overall[0]
        composition=within=Fraction(0); groups=[];directions=[]
        for key in sorted(counts[0]):
            values=[b[key] for b in counts]
            rates=[Fraction(a,b)*100 for a,b in values]
            weights=[Fraction(v[1],tot[1]) for v,tot in zip(values,totals)]
            dw=weights[1]-weights[0];dr=rates[1]-rates[0]
            c=dw*sum(rates)/2;w=dr*sum(weights)/2
            composition+=c;within+=w;directions.append(delta*dr<0)
            groups.append(dict(group=key,counts=values,rates=list(map(str,rates)),weights=[str(v*100) for v in weights],composition=str(c),within=str(w)))
        if composition+within!=delta:raise ArithmeticError("分解恒等式不成立")
        return dict(status="严格反转" if len(groups)>1 and all(directions) else "未发现严格反转",totals=totals,
                    rates=list(map(str,overall)),groups=groups,delta=str(delta),composition=str(composition),within=str(within),
                    excluded_periods=sorted(excluded))
    except (ValueError,TypeError,KeyError) as exc:return dict(status="待确认",reason=str(exc))

def rate_questions(spec,result):
    rows=[]
    for i,group in enumerate([None]+[g["group"] for g in result["groups"]],1):
        common={} if group is None else {spec["group"]:group}
        query=dict(metric="比例",num=spec["num"],den=spec["den"],left={**common,spec["period"]:spec["periods"][1]},
                   right={**common,spec["period"]:spec["periods"][0]})
        rows.append(dict(question=f"{group or '总体'}的{spec['num']}/{spec['den']}在两个时期如何变化？",query=query))
    return rows

def pretty(value,signed=False):
    v=Fraction(value)
    return (f"{float(v):+.4f}" if signed else f"{float(v):.4f}").rstrip("0").rstrip(".")

def trend_lines(data):
    result=data["result"];spec=data["spec"]
    if "groups" not in result:return [result["status"]+"："+result["reason"]]
    p0,p1=spec["periods"]
    lines=[f"{result['status']}　{p0} → {p1}　（{spec['num']} / {spec['den']}）"]
    def rates(v):return " → ".join(pretty(x)+"%" for x in v)
    lines.append("总体比率 "+rates(result["rates"]))
    for g in result["groups"]:
        lines.append(f"{g['group']}：组内比率 {rates(g['rates'])}；人数占比 {rates(g['weights'])}")
    lines.append(f"构成贡献 {pretty(result['composition'],True)} 个百分点 ＋ 组内贡献 {pretty(result['within'],True)} 个百分点 ＝ 总体变化 {pretty(result['delta'],True)} 个百分点。")
    if result["status"]=="严格反转":
        driver=max(result["groups"],key=lambda x:Fraction(x["composition"])*Fraction(result["delta"]))
        lines.append(f"{driver['group']}的人数占比从 {pretty(driver['weights'][0])}% 变为 {pretty(driver['weights'][1])}%。构成项抵消并超过组内变化，使总体方向反转。此为算术归因。")
    if result["excluded_periods"]:lines.append("未纳入本次两期比较："+ "、".join(result["excluded_periods"]))
    return lines

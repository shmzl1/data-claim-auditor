"""受控汇总语言。每个条件都是字段的精确等值匹配，不执行表达式。"""
import csv
import hashlib
import io
from decimal import Decimal, InvalidOperation
from fractions import Fraction

SUPPORTED = "数据支持"
CONTRADICTED = "与数据矛盾"
INSUFFICIENT = "证据不足"
METRICS = {"比例", "合计", "均值", "计数", "不可检验"}
OPS = {"高于", "低于", "等于", "至少", "至多"}

def read_csv(raw):
    if not raw or len(raw) > 1024 * 1024:
        raise ValueError("请上传 1 MB 以内的非空 CSV")
    source = raw.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(source, newline=""), strict=True)
    fields = next(reader, [])
    if not 1 <= len(fields) <= 40 or any(not f.strip() for f in fields) or len(set(fields)) != len(fields):
        raise ValueError("表头为空、重复或超过 40 列")
    rows = []
    for line in reader:
        if not line: continue
        if len(line) != len(fields): raise ValueError("数据行列数与表头不一致")
        rows.append(dict(zip(fields, line)))
        if len(rows) > 10000: raise ValueError("最多支持 10000 行")
    if not rows: raise ValueError("数据表没有记录")
    return rows

def number(x):
    try:
        d = Decimal(str(x).strip())
        if not d.is_finite() or abs(d.adjusted()) > 25 or len(d.as_tuple().digits) > 30:
            raise ValueError("数值超出支持范围")
        return Fraction(d)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("数值缺失或格式不合法") from None

def profile(rows):
    result = {}
    for field in rows[0]:
        values = list(dict.fromkeys(r[field] for r in rows))
        try:
            for v in values: number(v)
            result[field] = {"类型":"数值", "不同值数":len(values)}
        except ValueError:
            result[field] = {"类型":"类别", "值示例":values[:30],"不同值数":len(values)}
    return result

def validate(q):
    if not isinstance(q,dict) or q.get("metric") not in METRICS: raise ValueError("不支持的统计操作")
    if q["metric"] == "不可检验":
        if not isinstance(q.get("why"),str) or not q["why"].strip(): raise ValueError("缺少不可检验原因")
        return
    for key in ["left","right"]:
        f=q.get(key)
        if key=="right" and f is None: continue
        if not isinstance(f,dict) or not all(isinstance(k,str) and isinstance(v,str) for k,v in f.items()):
            raise ValueError("筛选条件须为等值字典")
    if q.get("op") not in OPS: raise ValueError("比较方向错误")
    if q.get("right") is None: number(q.get("target"))
    elif q.get("target") is not None: raise ValueError("比较对象重复")
    for key in (["num","den"] if q["metric"]=="比例" else ["num"] if q["metric"] in ("均值","合计") else []):
        if not isinstance(q.get(key),str) or not q[key]: raise ValueError("缺少计算字段")

def fmt(x):
    return str(round(float(x), 8))

def aggregate(rows,q,filters):
    metric=q["metric"]; fields=set(filters)
    if metric!="计数": fields.add(q["num"])
    if metric=="比例": fields.add(q["den"])
    missing=fields-set(rows[0])
    if missing: raise ValueError("缺少字段："+ "、".join(sorted(missing)))
    selected=[r for r in rows if all(r[k]==v for k,v in filters.items())]
    if not selected: raise ValueError("筛选后没有匹配记录："+str(filters))
    den=Fraction(1)
    if metric=="计数": num=Fraction(len(selected))
    else:
        vals=[number(r[q["num"]]) for r in selected];num=sum(vals)
        if metric=="均值": den=Fraction(len(vals))
        if metric=="比例":
            counts=[number(r[q["den"]]) for r in selected]
            if any(n<0 or d<0 or n>d for n,d in zip(vals,counts)):raise ValueError("部分人数与总人数不一致")
            den=sum(counts)
    if not den: raise ValueError("分母为零")
    value=num/den*(100 if metric=="比例" else 1)
    return value,dict(filters=filters,rows=len(selected),num_field=q.get("num") if metric!="计数" else "记录行数",
                      den_field=q.get("den") if metric=="比例" else "记录行数" if metric=="均值" else None,
                      numerator=str(num),denominator=str(den),value=fmt(value),unit="%" if metric=="比例" else "")

def execute(rows,q):
    validate(q)
    if q["metric"]=="不可检验": return dict(verdict=INSUFFICIENT,reason=q["why"])
    evidence={}
    try:
        a,evidence["left"]=aggregate(rows,q,q["left"])
        if q.get("right") is None:
            b=number(q["target"]); evidence["target"]=fmt(b)
        else: b,evidence["right"]=aggregate(rows,q,q["right"])
        ok={"高于":a>b,"低于":a<b,"等于":a==b,"至少":a>=b,"至多":a<=b}[q["op"]]
        return dict(evidence,verdict=SUPPORTED if ok else CONTRADICTED)
    except ValueError as exc: return dict(evidence,verdict=INSUFFICIENT,reason=str(exc))

def digest(raw): return hashlib.sha256(raw).hexdigest()

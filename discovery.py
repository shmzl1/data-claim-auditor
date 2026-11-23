"""只给表格时，先提出可计算问题，再把候选发现交给原有核验流程。"""
import uuid

from audit import audit
from model import call
from stats import aggregate, digest, fmt, number, profile, read_csv, validate


def overview(rows):
    schema = profile(rows)
    for field, info in schema.items():
        if info["类型"] == "数值":
            values = [number(row[field]) for row in rows]
            info.update(最小值=fmt(min(values)), 最大值=fmt(max(values)))
        info["空值行数"] = sum(not row[field].strip() for row in rows)
    return schema


class InvalidQuestion(ValueError):
    """请求无法映射到这张表的受控统计操作。"""


def evaluate_question(rows, query):
    if not isinstance(query, dict) or query.get("metric") == "不可检验":
        raise InvalidQuestion("分析查询必须使用实际统计操作")
    # 公共比较协议负责验证指标和字段类型。探索阶段只取观察值。
    try:
        validate(dict(query, op="等于", target=0 if query.get("right") is None else None))
    except (TypeError, ValueError) as exc:
        raise InvalidQuestion(str(exc)) from None
    left, right = query["left"], query.get("right")
    if right is not None and (left.keys()!=right.keys() or sum(left[k]!=right[k] for k in left)!=1):
        raise InvalidQuestion("比较两侧必须保留相同筛选字段、只改变一个比较维度")
    fields = set(rows[0])
    for key in ("num", "den"):
        if query.get(key) is not None and (not isinstance(query[key],str) or query[key] not in fields):
            raise InvalidQuestion("查询引用了表外字段："+str(query[key]))
    for side in ("left", "right"):
        filters = query.get(side)
        if filters is not None and not set(filters) <= fields:
            raise InvalidQuestion("筛选引用了表外字段")
    result = {}
    for side in ("left", "right"):
        if query.get(side) is not None:
            _, result[side] = aggregate(rows, query, query[side])
    return result


def checked_plan(out, rows):
    questions = out["questions"]
    limitations = out["limitations"]
    if not isinstance(questions, list) or not 1 <= len(questions) <= 3:
        raise ValueError("需要 1 至 3 个分析问题")
    if not isinstance(limitations, list) or not all(isinstance(s, str) and s.strip() for s in limitations):
        raise ValueError("数据局限须为文字列表")
    entries = []
    for i, item in enumerate(questions, 1):
        title, query = item["question"], item["query"]
        if not isinstance(title, str) or not title.strip() or not isinstance(query, dict):
            raise ValueError("分析问题或查询格式不正确")
        if set(query) - {"metric","num","den","left","right"}:
            raise ValueError("查询出现协议外字段")
        entry = dict(id=f"Q{i}", question=title, query=query)
        try:
            entry["result"] = evaluate_question(rows, query)
        except InvalidQuestion:
            raise
        except ValueError as exc:
            entry["error"] = str(exc)
        entries.append(entry)
    return entries, limitations


def checked_findings(out, usable):
    found = out["findings"]
    if not isinstance(found,list) or len(found)!=len(usable):
        raise ValueError("每个成功计算须对应一条候选发现")
    texts = {f["id"]: f["text"] for f in found}
    if set(texts)!={q["id"] for q in usable} or not all(isinstance(t,str) and 0<len(t.strip())<=1500 for t in texts.values()):
        raise ValueError("候选发现的编号或内容错误")
    return [texts[q["id"]] for q in usable]


def analyze(raw, focus="", invoke=None):
    if not isinstance(focus,str) or len(focus)>1500:
        raise ValueError("关注点最多 1500 字")
    rows = read_csv(raw)
    invoke = invoke or call
    schema = overview(rows)
    analysis = dict(focus=focus.strip(), questions=[], limitations=[])
    events = []
    record = dict(version=2,run_id=uuid.uuid4().hex,mode="analysis",sha256=digest(raw),
                  row_count=len(rows),schema=schema,analysis=analysis,events=events,
                  sentences=[],rounds=[],status="运行中")
    def ask(payload, checker):
        for attempt in range(2):
            out = invoke("分析",payload,events,1)
            try: return checker(out)
            except (KeyError,ValueError,TypeError) as exc:
                if events: events[-1].update(status="invalid",validation_error=str(exc))
                if attempt: raise ValueError("分析输出格式错误："+str(exc)) from None
                payload = dict(payload,format_feedback=str(exc),previous_output=out)
    try:
        questions, limitations = ask(dict(stage="plan",schema=schema,row_count=len(rows),focus=focus.strip()),
                                     lambda out: checked_plan(out,rows))
        analysis.update(questions=questions,limitations=limitations)
        usable = [q for q in questions if "result" in q]
        if not usable:
            record["status"] = "无可核验发现"
            return record
        texts = ask(dict(stage="draft",focus=focus.strip(),observations=usable),
                    lambda out: checked_findings(out,usable))
        for source,(q,text) in enumerate(zip(usable,texts),1):
            q.update(source=source,draft=text)
        context = []
        for q in usable:
            query=q["query"]
            left=query["left"]
            right=query.get("right")
            common=left if right is None else {k:v for k,v in left.items() if right.get(k)==v}
            context.append(dict(source=q["source"],question=q["question"],metric=query["metric"],
                                left=left,right=right,两侧共同限定=common))
        verified = audit(raw,texts,invoke=invoke,discovery_context=context)
        verified.update(version=2,mode="analysis",analysis=analysis,events=events+verified["events"])
        return verified
    except (ValueError,TypeError,KeyError,RuntimeError) as exc:
        record.update(status="运行失败",error=str(exc))
        return record


def replay_analysis(rows, record):
    questions=record["analysis"]["questions"]
    if not questions:raise ValueError("无分析查询可复算")
    count=0
    drafts=[]
    for i,q in enumerate(questions,1):
        if q["id"]!=f"Q{i}":raise ValueError("分析问题编号不一致")
        try: result=evaluate_question(rows,q["query"])
        except (TypeError,ValueError,KeyError) as exc:
            if "result" in q or q.get("error")!=str(exc) or "source" in q:
                raise ValueError("分析失败记录不一致") from None
        else:
            if result!=q.get("result") or "error" in q:raise ValueError("分析计算证据不一致")
            count+=1
            if "source" in q:
                if q["source"]!=len(drafts)+1:raise ValueError("分析发现编号不连续")
                drafts.append((q["source"],q["draft"]))
            elif record["status"]=="已完成": raise ValueError("缺少分析发现")
    if record["sentences"]!=[dict(source=i,text=t) for i,t in drafts]:
        raise ValueError("候选发现与核验原句不一致")
    return count

from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit,parse_qs
from html import escape
from pathlib import Path
import base64,csv,json,re,secrets
from audit import ROOT,audit,save
from discovery import analyze
from trend import trend_lines
from adjudication import decision_lines
from reporting import evidence_text,markdown

TOKEN=secrets.token_urlsafe(32)
EXAMPLES=ROOT/"examples"
LOCAL=ROOT/"local"
STYLE="""*{box-sizing:border-box}body{margin:0;background:#f5f4f0;color:#192e39;font:16px/1.65 'Microsoft YaHei',sans-serif}header{border-bottom:1px solid #cbd3d1;background:#173b42;color:white;padding:13px 6%;font-weight:bold}main{max-width:1080px;margin:auto;padding:25px}h1{margin:0;font-size:32px}h2{font-size:21px;margin:8px 0}h3{font-size:17px;margin:8px 0}section{background:white;border:1px solid #d3dbd9;border-radius:9px;padding:16px 21px;margin:12px 0}a{color:#17685b}textarea{width:100%;font:inherit;min-height:180px;padding:10px}button,.btn{display:inline-block;background:#176257;color:white;padding:8px 15px;border-radius:5px;border:0;text-decoration:none;font:inherit;margin:4px 8px 4px 0}button:disabled{opacity:.55}table{width:100%;border-collapse:collapse}td,th{padding:6px 8px;text-align:left;border-bottom:1px solid #dfe5e3}th{background:#eef3f1}small{color:#475d68}p{margin:5px 0}.bad{color:#8d4227}.good{color:#175f4a}.warn{color:#80601a}summary{cursor:pointer}.note{background:#f6f1e6;padding:7px 12px;border-left:3px solid #ad8334;margin:8px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}.links{display:flex;flex-wrap:wrap;gap:12px}"""
def h(v):return escape(str(v),quote=True)
def shell(body):return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>数据结论审查与复现</title><style>'+STYLE+'</style><header>数据结论审查与复现系统</header><main>'+body+'</main></html>'
def home(task="analysis"):
    analysis = task != "audit"
    title = "分析数据" if analysis else "核验结论"
    nav = '<nav class="links">' + ' · '.join(
        f'<strong>{label}</strong>' if mode==task else f'<a href="/?task={mode}">{label}</a>'
        for mode,label in [("analysis","分析数据"),("audit","核验结论")]) + '</nav>'
    if analysis:
        intro = "上传一份 CSV，由系统提出分析问题、计算并独立核验发现。"
        fields = '<label for="focus">想了解什么（可选）</label><textarea id="focus" maxlength="1500" style="min-height:64px"></textarea>'
        attr = "required"
    else:
        intro = "提交已有原句，逐句检查数据是否支持。"
        sample = (EXAMPLES/"claims.txt").read_text("utf8")
        fields = '<label for="claims">待核验结论（每行一句）</label><textarea id="claims" required>'+h(sample)+'</textarea>'
        attr = ""
    script = """<script>document.querySelector('form').onsubmit=async e=>{
      e.preventDefault();const form=e.target,btn=form.querySelector('button'),status=document.querySelector('#status');
      btn.disabled=true;status.textContent='正在计算与核查…';
      try{const file=document.querySelector('#csv').files[0];if(file&&file.size>1048576)throw Error('CSV 超过 1 MB');
      let binary='';if(file)for(const b of new Uint8Array(await file.arrayBuffer()))binary+=String.fromCharCode(b);
      const payload={token:'TOKEN_VALUE',csv:file?btoa(binary):null};
      if(document.querySelector('#claims'))payload.claims=document.querySelector('#claims').value;
      const focus=document.querySelector('#focus')?.value.trim();if(focus)payload.focus=focus;
      const rsp=await fetch(form.dataset.endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      const result=await rsp.json();if(!rsp.ok)throw Error(result.error);location.href=result.url;
      }catch(err){status.textContent=err.message;btn.disabled=false}
    };</script>""".replace("TOKEN_VALUE",TOKEN)
    return shell(nav+'<h1>'+title+'</h1><p>'+intro+'</p><section><form data-endpoint="'+('/analyze' if analysis else '/audit')+'"><label for="csv">UTF-8 CSV 数据表</label><br><input type="file" id="csv" accept=".csv,text/csv" '+attr+'><p><small>限 1 MB。模型接收字段概况和汇总结果。'+('' if analysis else '不选文件时使用转化样例。')+'</small></p>'+fields+'<button>开始'+title+'</button> <span id="status" role="status"></span></form></section><section><h2>课程样例与历史回放</h2><p><small>回放读取项目附带的记录，可查看结论、计算过程并下载报告。</small></p><div class="links"><a href="/sample.csv">转化数据 CSV</a><a href="/sales.csv">销售数据 CSV</a><a href="/view?case=analysis-conversion">转化数据分析</a><a href="/view?case=trend-conversion">两期趋势分解</a><a href="/view?case=decision-bad">异议裁决回放</a><a href="/view?case=analysis-sales">销售数据分析</a><a href="/view?case=multi">四角色核验</a><a href="/view?case=injected">人工注入</a><a href="/view?case=single">单角色基线</a></div></section>'+script)

def discovery_panel(d):
    analysis = d["analysis"]
    parts = ['<section><h2>分析问题与实算结果</h2><p>关注点　'+h(analysis["focus"] or "留空，由 Agent 自主选题")+'</p>']
    for q in analysis["questions"]:
        parts.append('<h3>'+h(q["id"]+"　"+q["question"])+'</h3>')
        parts.extend('<p>'+h(v)+'</p>' for v in evidence_text(q["query"],q.get("result",{})))
        if q.get("error"):parts.append('<p class="note">'+h(q["error"])+'</p>')
        if q.get("source"):parts.append(f'<a href="#finding-{q["source"]}">查看这项发现的核验结果</a>')
    for limit in analysis["limitations"]: parts.append('<p class="note">数据局限　'+h(limit)+'</p>')
    return ''.join(parts)+'</section>'

def render(d,query):
    analysis=d.get("mode")=="analysis"
    archived=query.startswith("case=")
    parts=[f'<small>{"历史回放" if archived else "实际运行"}　/　{h(d["mode"])}　/　{h(d["run_id"])}</small><h1>{"数据分析报告" if analysis else "逐句审查结果"}</h1><p>{h(d["status"])}　·　{d["row_count"]} 行 CSV　·　{len(d["events"])} 次模型请求</p>']
    if d.get("controlled_fault"):parts.append('<p class="note">'+h(d["controlled_fault"])+'</p>')
    if d.get("injection"):parts.append('<p class="note">'+h(d["injection"])+'。首轮展示的是实际执行的错误口径。</p>')
    if d.get("error"):parts.append('<p class="bad">'+h(d["error"])+'</p>')
    if d.get("unresolved"):parts.append('<p class="note">仍有未解决的口径问题，请确认原句及统计范围。</p>')
    parts.append(f'<div><a class="btn" href="/export.md?{query}">{"下载分析报告" if analysis else "下载审查报告"}</a><a class="btn" href="/export.json?{query}">下载复算记录</a></div>')
    if analysis:
        if "trend" in d["analysis"]:
            lines=trend_lines(d["analysis"]["trend"])
            parts.append('<section><h2>总体与各组走势</h2><p><strong>'+h(lines[0])+'</strong></p>')
            for text in lines[1:]:
                style=' class="note"' if text.startswith("构成贡献") else ""
                parts.append('<p'+style+'>'+h(text)+'</p>')
            parts.append('</section>')
        parts.append(discovery_panel(d))
    final={i["source"]:i for i in d.get("items",[])}
    for sentence in d["sentences"]:
        n=sentence["source"];i=final.get(n)
        parts.append(f'<section id="finding-{n}"><small>{"候选发现" if analysis else "原句"} {n}</small><h2>{h(sentence["text"])}</h2>')
        if i:
            cls={"数据支持":"good","与数据矛盾":"bad","证据不足":"warn"}[i["verdict"]]
            parts.append(f'<h3 class="{cls}">{h(i["verdict"])}</h3><p>{h(i["reason"])}</p><p>修订建议　{h(i["suggestion"])}</p>')
        for step in d["rounds"]:
            atoms={a["id"]:a for a in step["atoms"] if a["source"]==n}
            parts.append(f'<h3>第 {step["round"]} 轮计算　·　当轮判定：{h(step["locked"][n-1])}</h3><table><tr><th>待检验主张</th><th>实际计算依据</th></tr>')
            for q,r in zip(step["executed"],step["results"]):
                if q["id"] not in atoms:continue
                parts.append('<tr><td>'+h(atoms[q["id"]]["claim"])+'</td><td>'+'<br>'.join(h(x) for x in evidence_text(q,r))+'</td></tr>')
            parts.append('</table>')
            for issue in step.get("review",[]):
                if any(x["id"]==issue["id"] and x["objection"]==issue["reason"] for x in step.get("decisions",[])):continue
                if issue["id"] in atoms:parts.append('<p class="note">退回'+h(issue["target"])+'　'+h(issue["reason"])+'。'+h(issue["fix"])+'</p>')
            for dec in step.get("decisions",[]):
                if dec["id"] in atoms:parts.append('<div class="note"><b>分歧裁决</b>'+''.join('<p>'+h(v)+'</p>' for v in decision_lines(dec))+'</div>')
            checks=[i for i in step.get('program_checks',[]) if i['id'] in atoms]
            if checks:parts.append('<small>范围校验：'+h('、'.join(i['id'] for i in checks))+' 的计算口径与主张不一致。</small>')
        parts.append('</section>')
    parts.append('<details><summary>查看角色输入输出、请求、用量和逐轮结果</summary><pre>'+h(json.dumps(d,ensure_ascii=False,indent=2))+'</pre></details><p><a href="/">返回上传页面</a></p>')
    return shell("".join(parts))
class Handler(BaseHTTPRequestHandler):
    def reply(self,data,typ,status=200,filename=None):
        if isinstance(data,str):data=data.encode()
        self.send_response(status);self.send_header("Content-Type",typ)
        if filename:self.send_header("Content-Disposition",'attachment; filename="'+filename+'"')
        self.send_header("Content-Length",str(len(data)));self.end_headers();self.wfile.write(data)
    def do_GET(self):
        u=urlsplit(self.path);q=parse_qs(u.query)
        if u.path=="/":return self.reply(home("audit" if q.get("task")==["audit"] else "analysis"),"text/html;charset=utf-8")
        if u.path=="/sales.csv":return self.reply((EXAMPLES/"sales.csv").read_bytes(),"text/csv;charset=utf-8",filename="sales.csv")
        if u.path=="/sample.csv":return self.reply((EXAMPLES/"conversion.csv").read_bytes(),"text/csv;charset=utf-8",filename="conversion.csv")
        if u.path not in ("/view","/export.md","/export.json"):return self.reply("不存在","text/plain;charset=utf-8",404)
        if q.get("case",[""])[0] in ("single","multi","injected","analysis-conversion","analysis-sales","analysis-focus"):
            key=q["case"][0];path=ROOT/"evidence"/(key+".json");query="case="+key
        elif q.get("case",[""])[0] in ("trend-conversion","trend-clinic","trend-sales","decision-bad","decision-equal","decision-unclear","decision-control","decision-missing"):
            key=q["case"][0];folder="after" if key.startswith("decision-") else "trend"
            path=ROOT/"evidence"/"enhancements"/folder/(key.split("-",1)[1]+".json");query="case="+key
        elif re.fullmatch("[a-f0-9]{32}",q.get("run",[""])[0]):
            key=q["run"][0];path=LOCAL/(key+".json");query="run="+key
        else:return self.reply("无效运行","text/plain;charset=utf-8",404)
        if not path.is_file():return self.reply("未找到记录","text/plain;charset=utf-8",404)
        d=json.loads(path.read_text("utf8"))
        if u.path=="/export.json":return self.reply(path.read_bytes(),"application/json",filename=key+".json")
        if u.path=="/export.md":return self.reply(markdown(d),"text/markdown;charset=utf-8",filename=key+".md")
        self.reply(render(d,query),"text/html;charset=utf-8")
    def do_POST(self):
        try:
            length=int(self.headers.get("Content-Length",0))
            if self.path not in ("/audit","/analyze") or not 0<length<1550000:raise ValueError("请求路径或大小错误")
            q=json.loads(self.rfile.read(length))
            if not isinstance(q,dict) or q.get("token")!=TOKEN:raise ValueError("请重新打开首页")
            if self.path=="/analyze" and not isinstance(q.get("csv"),str):
                raise ValueError("请上传 CSV 文件")
            raw=(EXAMPLES/"conversion.csv").read_bytes() if q["csv"] is None else base64.b64decode(q["csv"],validate=True)
            if self.path=="/analyze":
                d=analyze(raw,q.get("focus",""))
            else:
                if not isinstance(q.get("claims"),str):raise ValueError("请逐行填写待核验结论")
                d=audit(raw,[line.strip() for line in q["claims"].splitlines() if line.strip()])
            save(LOCAL/(d["run_id"]+".json"),d)
            self.reply(json.dumps({"url":"/view?run="+d["run_id"]}),"application/json")
        except (ValueError,KeyError,TypeError,UnicodeError,csv.Error) as err:self.reply(json.dumps({"error":str(err)},ensure_ascii=False),"application/json;charset=utf-8",400)
if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser();p.add_argument("--port",type=int,default=8766);args=p.parse_args()
    print(f"http://127.0.0.1:{args.port}/",flush=True)
    ThreadingHTTPServer(("127.0.0.1",args.port),Handler).serve_forever()

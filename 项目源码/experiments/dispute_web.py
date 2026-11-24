"""配对验收。仅在独立本机 HTTP 服务内注入，公开入口不接受故障参数。"""
import argparse,base64,json,re,sys
from pathlib import Path
from threading import Thread
from unittest.mock import patch
from urllib.request import Request,urlopen
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import app
from audit import audit,save,reproduce
from model import call

def run(case,phase):
    target=ROOT/"evidence"/"enhancements"/phase/(case["name"]+".json")
    if target.exists():raise FileExistsError(target)
    raw=(ROOT/"examples"/(case["file"]+".csv")).read_bytes()
    def actor(role,data,events,r):
        out=call(role,data,events,r)
        if not case["actual"] or r!=1:return out
        def group(key):
            f={"月份":"5月"}
            if key!="all":f["用户类型"]="新用户" if key=="new" else "老用户"
            return f
        if role=="复算":
            atom=data["atoms"][0]["id"]
            out={"queries":[dict(id=atom,metric="比例",num="转化人数",den="人数",left=group(case["actual"]),right=None,target=10,op="等于")]}
        elif role=="审查":
            atom=data["atoms"][0]["id"];k=case["proposal"]
            nf=group("new" if k=="all_den" else k);df=group("all" if k=="all_den" else k)
            issue=dict(id=atom,target="复算",side="left",reason="核对五月比较人群及分母",fix=f"请以分子筛选{nf}、分母筛选{df}重新计算",
                       alternative=dict(num="转化人数",den="人数",num_filters=nf,den_filters=df))
            out={"issues":[issue]}
        else:return out
        events[-1]["experiment_override"]=out
        return out
    def wrapped(raw,lines):
        d=audit(raw,lines,invoke=actor)
        if case["actual"]:d["controlled_fault"]="人工控制首轮复算和审查输出；后续调用真实"
        return d
    server=app.ThreadingHTTPServer(("127.0.0.1",0),app.Handler)
    Thread(target=server.serve_forever,daemon=True).start()
    base=f"http://127.0.0.1:{server.server_port}"
    try:
        with patch.object(app,"audit",wrapped):
            token=re.search("token:'([a-zA-Z0-9_-]+)'",urlopen(base+"/?task=audit").read().decode())[1]
            req=Request(base+"/audit",data=json.dumps(dict(token=token,csv=base64.b64encode(raw).decode(),claims=case["line"])).encode(),headers={"Content-Type":"application/json"})
            view=json.load(urlopen(req,timeout=600))["url"]
            html=urlopen(base+view).read().decode()
            d=json.load(urlopen(base+view.replace("/view","/export.json")))
            md=urlopen(base+view.replace("/view","/export.md")).read().decode()
            save(target,d)
            assert d["status"] in html and d["status"] in md
            reproduce(raw,d)
            print(case["name"],d["run_id"],d["status"],len(d["rounds"]),flush=True)
    finally:server.shutdown();server.server_close()
if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("phase");parser.add_argument("names",nargs="*")
    args=parser.parse_args()
    for c in json.loads((ROOT/"experiments/disputes.json").read_text("utf8")):
        if not args.names or c["name"] in args.names:run(c,args.phase)

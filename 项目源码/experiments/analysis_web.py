"""真实 Web 验收。一律提交文件内容；仅显式提供 focus 时发送关注点。"""
import argparse
import base64
import json
import re
import sys
from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import Handler, ThreadingHTTPServer
from audit import reproduce,save

def submit(csv_path, output, focus=""):
    if output.exists(): raise FileExistsError(output)
    raw=csv_path.read_bytes()
    server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
    Thread(target=server.serve_forever,daemon=True).start()
    base=f"http://127.0.0.1:{server.server_port}"
    try:
        page=urlopen(base).read().decode()
        token=re.search(r"token:'([a-zA-Z0-9_-]+)'",page)[1]
        payload=dict(token=token,csv=base64.b64encode(raw).decode())
        if focus:payload["focus"]=focus
        req=Request(base+"/analyze",data=json.dumps(payload).encode(),headers={"Content-Type":"application/json"})
        view=json.load(urlopen(req,timeout=600))["url"]
        html=urlopen(base+view).read().decode()
        d=json.load(urlopen(base+view.replace("/view","/export.json")))
        md=urlopen(base+view.replace("/view","/export.md")).read().decode()
        save(output,d)
        print(d["status"],d["run_id"],d.get("error",""),flush=True)
        assert "数据分析报告" in html and md.startswith("# 数据分析报告") and d["sha256"] in md
        assert d["status"]=="已完成" and len({e["role"] for e in d["events"]})==5
        checks=reproduce(raw,d)
        print("导出复算",checks,"项；调用",len(d["events"]),"次")
        for q in d["analysis"]["questions"]:
            if "source" in q:print(q["question"],d["items"][q["source"]-1])
        print("数据局限",d["analysis"]["limitations"])
    finally:server.shutdown();server.server_close()
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("csv",type=Path);p.add_argument("output",type=Path);p.add_argument("--focus",default="")
    args=p.parse_args();submit(args.csv,args.output,args.focus)

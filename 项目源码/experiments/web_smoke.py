"""从 HTTP 上传 CSV，执行一次真实四角色调用，下载并独立复算。"""
import sys, json,base64,re
from pathlib import Path
from threading import Thread
from urllib.request import urlopen,Request
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app import Handler,ThreadingHTTPServer
from audit import reproduce,save
def run():
    server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
    Thread(target=server.serve_forever,daemon=True).start()
    base="http://127.0.0.1:"+str(server.server_port)
    try:
        home=urlopen(base).read().decode()
        token=re.search("token:'([a-zA-Z0-9_-]+)'",home)[1]
        raw=(ROOT/"examples/conversion.csv").read_bytes()
        payload=dict(token=token,csv=base64.b64encode(raw).decode(),claims="新用户和老用户的转化率从4月到5月均有提升。")
        req=Request(base+"/audit",data=json.dumps(payload).encode(),headers={"Content-Type":"application/json"})
        path=json.load(urlopen(req,timeout=300))["url"]
        page=urlopen(base+path).read().decode()
        report=json.load(urlopen(base+path.replace("/view","/export.json")))
        md=urlopen(base+path.replace("/view","/export.md")).read().decode()
        assert report["status"]=="已完成" and "与数据矛盾" in page and report["sha256"] in md
        count=reproduce(raw,report)
        report["web_check"]={"csv_upload":True,"result_page":True,"downloads":["md","json"],"replayed_queries":count}
        save(ROOT/"evidence"/("web-"+report["run_id"]+".json"),report)
        print(report["run_id"],count)
    finally:server.shutdown();server.server_close()
if __name__=="__main__":run()

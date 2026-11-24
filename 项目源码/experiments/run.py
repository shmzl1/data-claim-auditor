"""每种运行只写新文件。人工答案仅供事后评分。"""
import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from audit import audit
def run(mode,path):
    lines=(ROOT/"examples/claims.txt").read_text("utf8").splitlines()
    if path.exists():raise FileExistsError(path)
    d=audit((ROOT/"examples/conversion.csv").read_bytes(),lines[1:2] if mode=="injected" else lines,"single" if mode=="single" else "multi",inject=mode=="injected",path=path)
    print(d["status"],d["run_id"],len(d["events"]),d.get("error",""))
    if d["status"]!="已完成":raise SystemExit(1)
if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser();p.add_argument("mode",choices=["single","multi","injected"]);p.add_argument("path",type=Path);a=p.parse_args();run(a.mode,a.path)

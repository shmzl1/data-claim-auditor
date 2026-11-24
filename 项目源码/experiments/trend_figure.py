"""按真实转化率 Web 导出的精确数值画报告图；SVG 可直接插入 Markdown。"""
import json,sys
from html import escape
from pathlib import Path
from fractions import Fraction
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from trend import pretty
from audit import reproduce

def chart():
    doc=json.loads((ROOT/"evidence/enhancements/trend/conversion.json").read_text("utf8"))
    reproduce((ROOT/"examples/conversion.csv").read_bytes(),doc)
    trend=doc["analysis"]["trend"];r=trend["result"];periods=trend["spec"]["periods"]
    parts=['<svg xmlns="http://www.w3.org/2000/svg" width="920" height="420" viewBox="0 0 920 420"><rect width="920" height="420" fill="white"/><g font-family="Microsoft YaHei, Noto Sans CJK SC, sans-serif">']
    def text(x,y,s,size=17,anchor="start",color="#233544",bold=False):
        parts.append(f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" font-weight="{700 if bold else 400}" text-anchor="{anchor}">{escape(str(s))}</text>')
    def line(x,y,u,v,c,width=1,dash=""):
        parts.append(f'<line x1="{x}" y1="{y}" x2="{u}" y2="{v}" stroke="{c}" stroke-width="{width}" stroke-dasharray="{dash}"/>')
    text(26,35,"A   两期转化率",21,bold=True);text(485,35,"B   总体变化的来源",21,bold=True)
    line(455,18,455,354,"#cad3d5")
    y=lambda v:308-float(Fraction(v))*2.65
    text(27,68,"单位：%",15);text(485,68,"单位：百分点",15)
    for i in range(0,81,20):
        line(117,y(i),335,y(i),"#e2e7e7");text(105,y(i)+5,str(i),13,"end","#64767a")
    colors=["#007565","#ad632c","#576ca2"]
    for (name,vs),c in zip([("总体",r["rates"])]+[(g["group"],g["rates"]) for g in r["groups"]],colors):
        a,b=vs
        line(138,y(a),317,y(b),c,4 if name=="总体" else 2.5)
        for x,v in [(138,a),(317,b)]:parts.append(f'<circle cx="{x}" cy="{y(v)}" r="4.5" fill="{c}"/>')
        text(124,y(a)-8,pretty(a)+"%",15,"end",c);text(330,y(b)+(12 if name=="总体" else 0),name+" "+pretty(b)+"%",17,color=c,bold=name=="总体")
    for x,period in zip((138,317),periods):text(x,339,period,17,"middle")
    c,w,total=[Fraction(r[k]) for k in ["composition","within","delta"]]
    y2=lambda v:308-float(v)*4.25
    line(510,308,884,308,"#6c8085")
    for x,start,end,label,color,value in [(535,0,c,"构成变化","#007565",c),(658,c,c+w,"组内变化","#ad632c",w),(781,0,total,"总变化","#294e64",total)]:
        top=min(y2(start),y2(end))
        parts.append(f'<rect x="{x}" y="{top}" width="77" height="{abs(y2(start)-y2(end))}" fill="{color}"/>')
        text(x+38,top-12,pretty(value,True),23,"middle",color,True);text(x+38,339,label,17,"middle")
    line(612,y2(c),658,y2(c),"#899a9d",1,"4 3");line(735,y2(total),781,y2(total),"#899a9d",1,"4 3")
    parts.append('<rect x="20" y="363" width="880" height="42" rx="5" fill="#eef4f1"/>')
    detail="；".join(f"{g['group']}人数占比 {pretty(g['weights'][0])}% → {pretty(g['weights'][1])}%" for g in r["groups"])
    text(460,391,detail,18,"middle");parts.append('</g></svg>')
    (ROOT/"figures/trend-reversal.svg").write_text("\n".join(parts),"utf8")
if __name__=="__main__":chart()

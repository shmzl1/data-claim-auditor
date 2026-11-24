# 多 Agent 数据结论审查与复现系统

只有表格时，选择 **分析数据**。上传 CSV、留空关注点，分析 Agent 会自己提出问题，读取程序算出的数值，再让其余四个角色核验候选发现。已有分析稿时，选择 **核验结论**，逐行提交原句。两种模式都可下载 Markdown 报告与 JSON 复算记录。

![销售表只上传 CSV 后的问题和实际汇总](../figures/sales-analysis.png)

## Windows 启动

在本目录的 PowerShell 中运行，实测 Python 3.13，运行时仅用标准库。

```powershell
python app.py
```

打开 http://127.0.0.1:8766/ 。首页默认显示“分析数据”，下方的历史回放可直接查看保存的结论与计算依据。从 [销售表](examples/sales.csv) 或 [转化表](examples/conversion.csv) 选择一份文件，“想了解什么”可不填。要核对已有稿件，打开 [核验结论](http://127.0.0.1:8766/?task=audit)。实时调用读取进程变量 `DEEPSEEK_API_KEY`，默认模型 deepseek-flash，可设 `DEEPSEEK_MODEL`。字段概况、类别示例、关注点、原句与汇总证据会发给模型服务；应用只监听本机。

无密钥时可直接看固定回放：[销售分析](http://127.0.0.1:8766/view?case=analysis-sales)、[转化分析](http://127.0.0.1:8766/view?case=analysis-conversion)、[关注点与缺失月份](http://127.0.0.1:8766/view?case=analysis-focus)、[原四角色分组争议](http://127.0.0.1:8766/view?case=injected)。

## 离线验收

```powershell
python -m unittest discover -s tests -v
python audit.py examples/sales.csv evidence/analysis-sales.json
python audit.py examples/conversion.csv evidence/multi.json
python experiments/score.py
```

复算程序使用原文件字节校验指纹，重做探索查询及各轮核验统计，检查候选发现关联和锁定判定。修改原数据或已记录的分母会触发校验错误。真实重跑使用 `python experiments/run.py multi local/repeat.json`（输出路径须未被占用），Web 上传验收使用 `python experiments/web_smoke.py`。自主分析的真实 HTTP 验收命令为 `python experiments/analysis_web.py examples/sales.csv local/new-sales.json`，可选 `--focus "比较文具的季度变化"`。以上重跑均调用模型。回放只读 evidence；浏览器发起的新运行保存在 local，下载后自行保留原 CSV。

目前支持至多 1 MB、10000 行、40 列的 UTF-8 CSV，等值筛选后的计数、合计、算术均值及部分占总体的百分比。跨期和跨组通过多条明确的筛选请求比较。未支持的统计推断、缺失字段及缺乏识别依据的因果主张应保留“证据不足”。

自主分析回放读取 evidence/analysis-*.json，两项增强的验收记录保存在 evidence/enhancements/。

[公开版报告](report.md) · [四行样例 CSV](examples/conversion.csv) · [实验方案](experiments/protocol.md) · [冻结评分](evidence/summary.json)

模型调用基于 [DeepSeek 官方 API](https://api-docs.deepseek.com/)。

## 两项增强的离线回放

- 首页“分析数据”仅上传文件即可运行。分析角色识别时期、群体与部分/总体人数，本机从原表按两期对称分解。可看[转化表反转](http://127.0.0.1:8766/view?case=trend-conversion)、[三渠道到诊表反转](http://127.0.0.1:8766/view?case=trend-clinic)及[销售额表的普通分析](http://127.0.0.1:8766/view?case=trend-sales)。
- “核验结论”中可定位的比例异议按原句限定回查双方的数据行。可看[错误分母建议被驳回](http://127.0.0.1:8766/view?case=decision-bad)、[同值错组](http://127.0.0.1:8766/view?case=decision-equal)与[群体指代不明](http://127.0.0.1:8766/view?case=decision-unclear)。定向裁决支持能唯一定位的原句与等值筛选。复杂口径需要人工确认。记录中的行号从首条数据起算。
- 五例输入和参考处置在 experiments/disputes.json。前后均由真实模型经本机 Web 服务运行；四项人为规定首轮复算和审查输出，同时保留原始回答。无故障对照无注入。旧版使用提交 6e22154，前后记录分别在 evidence/enhancements/before、after。离线评分：`python experiments/enhancement_score.py`；趋势图再生成：`python experiments/trend_figure.py`。
- 核对导出的反转分解：`python audit.py examples/conversion.csv evidence/enhancements/trend/conversion.json`。核对争议的行集和分母：`python audit.py examples/conversion.csv evidence/enhancements/after/bad.json`。命令显示的查询计数仅统计探索和核验的原子查询，分解及裁决证据另外检查。

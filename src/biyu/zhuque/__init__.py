"""S-6 · 朱雀体检与降分。

产品化自 _s6_ref/ 已验证原型(jiangfen.py / zhuque.py / pdf_extract.py),逻辑不重发明:
- client:    朱雀检测客户端(EdgeOne 网关),transport 可注入,测试不走网络
- guards:    占位符遮罩 / 回译守卫 / 风险标注(S-8-1 增去破折号与三条新守卫)
- rewrite:   直译式回译 / 中文改中文 few-shot / 小手术 / 独立去 AI 味(提示词逐字取自原型)
- pairs:     中文改中文的示范对加载与抽样(S-8-1;用户目录可覆盖包内版本)
- engine:    降分引擎(自动模式 fix_chapter 三层 / 网页复核模式 fix_blind 分层 /
             独立去 AI 味 deai_text)
- report_pdf: 朱雀网页报告 PDF 解析与窗口映射(纯函数可单测)
"""

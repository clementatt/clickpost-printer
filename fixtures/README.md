# fixtures

真实运单 PDF 含个人地址信息，**不入库**。

把要测试的 PDF 放到 `fixtures/local/`（该目录已在 `.gitignore` 中忽略），例如：

```bash
cp ~/Downloads/628836654423.pdf fixtures/local/sample.pdf
dzpost info fixtures/local/sample.pdf
```

单元测试不依赖任何真实 PDF：`tests/test_pdfbox.py` 会用 PyMuPDF 现场合成
一张带裁切线和标签外框的 A4 假单。

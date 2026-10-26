# Third-party components

Application dependencies retain their own licenses and notices. Review the notices
inside installed wheels when distributing a complete installation or model bundle.
This project archive contains application code and synthetic test outputs; models are
installed from the pinned RapidOCR package when dependencies are installed.

| Component | Use | Upstream |
|---|---|---|
| Gradio | Local test interface and optional share tunnel | https://github.com/gradio-app/gradio |
| RapidOCR | OCR wrapper and bundled ONNX models | https://github.com/RapidAI/RapidOCR |
| PaddleOCR | Source model family | https://github.com/PaddlePaddle/PaddleOCR |
| ONNX Runtime | CPU inference | https://github.com/microsoft/onnxruntime |
| FastAPI / Starlette | HTTP API and multipart integration | https://fastapi.tiangolo.com/ |
| OpenCV / Pillow | Image preprocessing | https://opencv.org/ and https://python-pillow.github.io/ |
| phonenumbers | Phone parsing/numbering metadata | https://github.com/daviddrysdale/python-phonenumbers |
| email-validator | Email syntax validation | https://github.com/JoshData/python-email-validator |

Sources checked while implementing this project:

- RapidOCR Python output contract and configuration: https://rapidai.github.io/RapidOCRDocs/main/install_usage/rapidocr/usage/
- PP-OCRv6 model description: https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-OCRv6/PP-OCRv6.html
- Supported language codes: https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/OCR.html
- KTP NIK structure: https://dispenduk.mojokertokota.go.id/home/berita/Arti-kode-angka-dalam-NIK-E-KTP
- FastAPI upload handling: https://fastapi.tiangolo.com/tutorial/request-files/
- Dio multipart requests: https://pub.dev/packages/dio
- Apple URLSession upload API: https://developer.apple.com/documentation/foundation/urlsession/upload(for:from:delegate:)

Upstream model benchmark claims are not treated as KTP or business-card extraction accuracy.

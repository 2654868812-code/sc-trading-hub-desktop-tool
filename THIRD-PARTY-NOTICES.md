# Third-Party Notices

FT-DataUpload is licensed under GNU GPL version 3. The full text is in
`COPYING`. The release also contains the following direct dependencies and
model assets. Their copyright notices and license files remain applicable.

| Component | Release baseline | License | Project/source |
| --- | --- | --- | --- |
| PyQt6 | 6.11.0 | GPL-3.0-only | https://www.riverbankcomputing.com/software/pyqt/ |
| Requests | 2.34.2 | Apache-2.0 | https://requests.readthedocs.io/ |
| PyInstaller | 6.21.0 | GPL-2.0-or-later with bootloader exception | https://pyinstaller.org/ |
| Pillow | 11.3.0 | MIT-CMU | https://python-pillow.org/ |
| mss | 10.2.0 | MIT | https://github.com/BoboTiG/python-mss |
| keyboard | 0.13.5 | MIT | https://github.com/boppreh/keyboard |
| opencv-python | 4.12.0.88 | Apache-2.0 | https://github.com/opencv/opencv-python |
| NumPy | 2.5.2 | BSD-3-Clause and bundled component licenses | https://numpy.org/ |
| CnOCR | 2.3.3 | Apache-2.0 | https://github.com/breezedeus/CnOCR |
| CnSTD | 1.2.8 | Apache-2.0 | https://github.com/breezedeus/CnSTD |
| ONNX Runtime | 1.28.0 | MIT | https://onnxruntime.ai/ |
| RapidOCR | 3.9.2 | Apache-2.0 | https://github.com/RapidAI/RapidOCR |
| PP-OCRv6 detection model | bundled model | Apache-2.0 | https://huggingface.co/breezedeus/cnstd-ppocr-ch_PP-OCRv6_det |

The PyInstaller runtime directory contains additional transitive Python and
native dependencies. License files supplied by those distributions are kept in
their `.dist-info/licenses` directories when present. Before publishing a new
release, regenerate and review the environment inventory because adding or
upgrading OCR dependencies can change both the package set and license terms.

No Star Citizen, Cloud Imperium Games, SCM, UEX, or localization-project logo
is licensed by this notice. Those names and marks remain the property of their
respective owners.

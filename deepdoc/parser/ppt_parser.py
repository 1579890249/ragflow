#
#  Copyright 2025 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

import logging
from io import BytesIO
from pathlib import Path
from pptx import Presentation
import os
import shutil
import subprocess
from PIL import Image
import tempfile
import uuid

class RAGFlowPptParser:
    def __init__(self):
        super().__init__()

    @staticmethod
    def _is_legacy_ppt_bytes(blob):
        return isinstance(blob, (bytes, bytearray)) and bytes(blob[:4]) == b"\xd0\xcf\x11\xe0"

    @staticmethod
    def _needs_pptx_conversion_path(path):
        return str(path).lower().endswith((".ppt", ".dps"))

    @staticmethod
    def _needs_pptx_conversion_suffix(suffix):
        return bool(suffix) and str(suffix).lower().lstrip(".") in {"ppt", "dps"}

    @staticmethod
    def _office_env(temp_dir):
        user_profile_dir = os.path.join(temp_dir, "lo_profile")
        os.makedirs(user_profile_dir, exist_ok=True)

        env = os.environ.copy()
        extra_paths = "/usr/bin:/usr/local/bin:/usr/lib/libreoffice/program"
        env["PATH"] = f"{extra_paths}:{env.get('PATH', '')}"
        lo_lib = "/usr/lib/libreoffice/program"
        existing_ld = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{lo_lib}:{existing_ld}" if existing_ld else lo_lib
        if not env.get("HOME") or not os.access(env.get("HOME", ""), os.W_OK):
            env["HOME"] = "/tmp"
        env["UserInstallation"] = f"file://{user_profile_dir}"
        return env, user_profile_dir

    def _convert_to_pptx(self, input_path, output_dir):
        os.makedirs(output_dir, exist_ok=True)
        env, user_profile_dir = self._office_env(output_dir)
        cmd = [
            "/usr/bin/soffice",
            f"-env:UserInstallation=file://{user_profile_dir}",
            "--headless",
            "--norestore",
            "--nofirststartwizard",
            "--convert-to", "pptx",
            str(input_path),
            "--outdir", str(output_dir),
        ]
        try:
            result = subprocess.run(
                cmd,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                timeout=120,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "LibreOffice (soffice) not found. Please install LibreOffice to parse legacy .ppt/.dps files."
            )

        stderr_text = result.stderr.decode(errors="replace")
        stdout_text = result.stdout.decode(errors="replace")
        if result.returncode != 0:
            raise RuntimeError(
                f"LibreOffice failed to convert presentation to PPTX (exit {result.returncode}).\n"
                f"stderr: {stderr_text}\nstdout: {stdout_text}"
            )

        expected = os.path.join(output_dir, os.path.splitext(os.path.basename(str(input_path)))[0] + ".pptx")
        if os.path.isfile(expected):
            return Path(expected)

        matches = list(Path(output_dir).glob("*.pptx"))
        if matches:
            return matches[0]
        raise FileNotFoundError(f"PPTX file not found after conversion: {expected}")

    def _prepare_presentation_input(self, fnm, input_suffix: str | None = None):
        if isinstance(fnm, (bytes, bytearray)):
            if not self._is_legacy_ppt_bytes(fnm) and not self._needs_pptx_conversion_suffix(input_suffix):
                return BytesIO(fnm), None

            temp_dir = tempfile.mkdtemp(prefix="ragflow_legacy_ppt_")
            suffix = input_suffix or ".ppt"
            if not suffix.startswith("."):
                suffix = "." + suffix
            ppt_path = Path(temp_dir) / f"input_{uuid.uuid4().hex}{suffix}"
            with open(ppt_path, "wb") as f:
                f.write(fnm)
            return self._convert_to_pptx(ppt_path, temp_dir), temp_dir

        if self._needs_pptx_conversion_path(fnm):
            temp_dir = tempfile.mkdtemp(prefix="ragflow_legacy_ppt_")
            return self._convert_to_pptx(fnm, temp_dir), temp_dir

        return fnm, None

    def __get_bulleted_text(self, paragraph):
        is_bulleted = bool(paragraph._p.xpath("./a:pPr/a:buChar")) or bool(paragraph._p.xpath("./a:pPr/a:buAutoNum")) or bool(paragraph._p.xpath("./a:pPr/a:buBlip"))
        if is_bulleted:
            return f"{'  '* paragraph.level}.{paragraph.text}"
        else:
            return paragraph.text

    def __extract(self, shape):
        try:
            # First try to get text content
            if hasattr(shape, 'has_text_frame') and shape.has_text_frame:
                text_frame = shape.text_frame
                texts = []
                for paragraph in text_frame.paragraphs:
                    if paragraph.text.strip():
                        texts.append(self.__get_bulleted_text(paragraph))
                return "\n".join(texts)

            # Safely get shape_type
            try:
                shape_type = shape.shape_type
            except NotImplementedError:
                # If shape_type is not available, try to get text content
                if hasattr(shape, 'text'):
                    return shape.text.strip()
                return ""

            # Handle table
            if shape_type == 19:
                tb = shape.table
                rows = []
                for i in range(1, len(tb.rows)):
                    rows.append("; ".join([tb.cell(
                        0, j).text + ": " + tb.cell(i, j).text for j in range(len(tb.columns)) if tb.cell(i, j)]))
                return "\n".join(rows)

            # Handle group shape
            if shape_type == 6:
                texts = []
                for p in sorted(shape.shapes, key=lambda x: (x.top // 10, x.left)):
                    t = self.__extract(p)
                    if t:
                        texts.append(t)
                return "\n".join(texts)

            return ""

        except Exception as e:
            logging.error(f"Error processing shape: {str(e)}")
            return ""

    def __call__(self, fnm, from_page, to_page, callback=None, input_suffix: str | None = None):
        presentation_input, temp_dir = self._prepare_presentation_input(fnm, input_suffix=input_suffix)
        try:
            ppt = Presentation(presentation_input)
            txts = []
            self.total_page = len(ppt.slides)
            for i, slide in enumerate(ppt.slides):
                if i < from_page:
                    continue
                if i >= to_page:
                    break
                texts = []
                for shape in sorted(
                        slide.shapes, key=lambda x: ((x.top if x.top is not None else 0) // 10, x.left if x.left is not None else 0)):
                    txt = self.__extract(shape)
                    if txt:
                        texts.append(txt)
                txts.append("\n".join(texts))

            return txts
        finally:
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)

    def ppt_to_pil_images(
            self,
            ppt_path_or_bytes,
            from_page: int = 0,
            to_page: int = None,
            temp_ori_dir: str = "/ragflow/temp_pptx_images",
            output_format: str = "jpeg",
            input_suffix: str | None = None,
    ) -> list[Image.Image]:
        """
        替代aspose.slides逻辑，返回PIL.Image.Image对象列表
        :param ppt_path_or_bytes: PPT文件路径 或 二进制数据（如BytesIO读取的内容）
        :param from_page: 起始页码（从0开始，兼容原脚本的切片逻辑）
        :param to_page: 结束页码（None表示到最后一页）
        :param temp_dir: 临时目录（存放导出的图片，执行完自动清理）
        :param output_format: 图片格式（jpeg/png）
        :return: PIL.Image.Image对象列表（和原脚本imgs类型完全一致）
        """
        # 步骤1：处理二进制数据（兼容原脚本的BytesIO(fnm)）
        ppt_file_path = None
        created_temp_input = False
        if isinstance(ppt_path_or_bytes, (bytes, bytearray)):
            # 如果传入的是二进制数据，先写入临时PPT文件
            os.makedirs(temp_ori_dir, exist_ok=True)
            suffix = input_suffix or (".ppt" if self._is_legacy_ppt_bytes(ppt_path_or_bytes) else ".pptx")
            if not suffix.startswith("."):
                suffix = "." + suffix
            ppt_file_path = os.path.join(temp_ori_dir, f"temp_input_{uuid.uuid4().hex}{suffix}")
            with open(ppt_file_path, "wb") as f:
                f.write(ppt_path_or_bytes)
            created_temp_input = True
        else:
            # 如果传入的是文件路径，直接使用
            ppt_file_path = ppt_path_or_bytes

        output_dir = temp_ori_dir+"/"+uuid.uuid4().hex
        temp_dir = temp_ori_dir+"/"+uuid.uuid4().hex
        # 步骤2：初始化pptxtoimages转换器，导出图片到临时目录
        converter = PPTXToImageConverter(pptx_path=ppt_file_path, output_dir=output_dir, temp_dir=temp_dir)
        # 执行转换，获取图片文件路径列表
        img_file_paths = converter.convert()
        # 步骤3：按页码切片
        img_file_paths.sort(key=lambda x: int(os.path.splitext(os.path.basename(x))[0].split("_")[-1]))

        sliced_paths = img_file_paths[from_page: to_page]
        # 步骤4：读取图片文件为PIL.Image.Image对象（核心：和原脚本返回类型一致）
        pil_images = []
        for img_path in sliced_paths:
            try:
                # 打开图片并copy（避免文件句柄占用，兼容原脚本的.copy()）
                with Image.open(img_path) as img:
                    pil_img = img.convert("RGB") if output_format == "jpeg" else img.copy()
                    pil_images.append(pil_img)
            except Exception as e:
                logging.error("调用图片转换为pil_image失败： ", img_path)
                # raise RuntimeError(
                #     f'ppt parse error at page {len(pil_images) + 1}, original error: {str(e)}'
                # ) from e
        # 步骤5：清理临时文件（避免残留）
        shutil.rmtree(output_dir, ignore_errors=True)
        shutil.rmtree(temp_dir, ignore_errors=True)
        if created_temp_input:
            os.remove(ppt_file_path)
        return pil_images



try:
    from pdf2image import convert_from_path
except ImportError:
    convert_from_path = None

class PPTXToImageConverter:
    """
    Converts a PPTX file into individual slide images (PNG, JPG, etc.)

    This class uses LibreOffice (soffice) to convert the PPTX to PDF,
    then converts each PDF page to an image using pdf2image.

    Requirements:
        - LibreOffice installed and accessible via 'soffice' command
        - Poppler utils installed (pdftoppm)
        - pdf2image Python package installed

    Args:
        pptx_path (str): Path to the input PPTX file.
        output_dir (str): Directory to save output images. Defaults to 'slides_images'.
        output_format (str): Image format to save (png, jpg, etc.). Defaults to 'png'.
        temp_dir (str): Temporary directory to store intermediate files. Defaults to 'temp'.

    Raises:
        RuntimeError: If LibreOffice (soffice) is not found.
        ImportError: If pdf2image is not installed.
        EnvironmentError: If Poppler utils are not installed.
        FileNotFoundError: If the PDF file is not created after conversion.
    """

    def __init__(
        self,
        pptx_path: str,
        output_dir: str = "slides_images",
        output_format: str = "png",
        temp_dir: str = "temp",
    ):
        self.pptx_path = pptx_path
        self.output_dir = output_dir
        self.output_format = output_format.lower()
        self.temp_dir = temp_dir

        if convert_from_path is None:
            raise ImportError(
                "pdf2image package is not installed. Please install it with 'pip install pdf2image'."
            )

        if not self._check_poppler_installed():
            raise EnvironmentError(
                "Poppler utils not found. Please install poppler.\n"
                "- Ubuntu/Debian: sudo apt install poppler-utils\n"
                "- MacOS: brew install poppler\n"
                "- Windows: Download from https://github.com/oschwartz10612/poppler-windows/releases and add to PATH"
            )

    def _check_poppler_installed(self):
        from shutil import which

        return which("pdftoppm") is not None

    def _convert_pptx_to_pdf(self):
        """Convert the PPTX file to a PDF using LibreOffice (soffice)."""
        if not os.path.exists(self.temp_dir):
            os.makedirs(self.temp_dir)

        user_profile_dir = os.path.join(self.temp_dir, "lo_profile")
        os.makedirs(user_profile_dir, exist_ok=True)
        env = os.environ.copy()
        # 补全 PATH
        extra_paths = "/usr/bin:/usr/local/bin:/usr/lib/libreoffice/program"
        env["PATH"] = f"{extra_paths}:{env.get('PATH', '')}"
        # 关键：补全 LibreOffice 的动态库路径
        lo_lib = "/usr/lib/libreoffice/program"
        existing_ld = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{lo_lib}:{existing_ld}" if existing_ld else lo_lib
        if not env.get("HOME") or not os.access(env.get("HOME", ""), os.W_OK):
            env["HOME"] = "/tmp"

        # 隔离用户配置，防止多进程锁冲突
        env["UserInstallation"] = f"file://{user_profile_dir}"
        cmd = [
            "/usr/bin/soffice",
            f"-env:UserInstallation=file://{user_profile_dir}",
            "--headless",
            "--norestore",
            "--nofirststartwizard",
            "--convert-to", "pdf",
            self.pptx_path,
            "--outdir", self.temp_dir,
        ]

        try:
            result = subprocess.run(
                cmd,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                timeout=120,
            )
            stderr_text = result.stderr.decode(errors="replace")
            stdout_text = result.stdout.decode(errors="replace")

            # 字体错误只记录警告，不中断流程
            if "Font" in stderr_text and "cannot be found" in stderr_text:
                logging.warning(
                    "LibreOffice font warning (continuing): %s", stderr_text[:500]
                )
            elif result.returncode != 0:
                # 真正的致命错误才抛出
                raise RuntimeError(
                    f"LibreOffice failed (exit {result.returncode}).\n"
                    f"stderr: {stderr_text}\nstdout: {stdout_text}"
                )
        except FileNotFoundError:
            raise RuntimeError(
                "LibreOffice (soffice) not found. "
                "Please install it manually:\n"
                "- Ubuntu: sudo apt install libreoffice\n"
                "- MacOS: brew install --cask libreoffice\n"
                "- Windows: https://www.libreoffice.org/download/"
            )
        pdf_filename = os.path.splitext(os.path.basename(self.pptx_path))[0] + ".pdf"
        pdf_path = os.path.join(self.temp_dir, pdf_filename)
        if not os.path.isfile(pdf_path):
            raise FileNotFoundError(f"PDF file not found after conversion: {pdf_path}")
        return pdf_path

    def _convert_pdf_to_images(self, pdf_path):
        """Convert each page of the PDF into separate images using pdf2image."""
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
        pages = convert_from_path(pdf_path, dpi=200)
        output_files = []
        for i, page in enumerate(pages):
            output_file = os.path.join(
                self.output_dir, f"slide_{i+1}.{self.output_format}"
            )
            page.save(output_file, self.output_format.upper())
            output_files.append(output_file)
        return output_files

    def convert(self):
        """Performs the full conversion from PPTX to images and cleans temp files."""
        pdf_path = self._convert_pptx_to_pdf()
        images = self._convert_pdf_to_images(pdf_path)
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        return images

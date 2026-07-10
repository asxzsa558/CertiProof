"""
OCR MCP Server - VeriSure
Exposes screenshot OCR and AI analysis as an MCP tool.
Uses OpenAI Vision API for intelligent screenshot analysis.
Uses standardized /execute endpoint for gateway integration.
"""

import base64
import io
import os
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
import httpx
import time
import tempfile
import asyncio
import subprocess
import sys
import re
from pathlib import Path

app = FastAPI(title="OCR MCP Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
PADDLE_DEVICE = os.getenv("PADDLE_DEVICE", "cpu")
_document_pipeline_error = None
_rapidocr_error = None
PADDLE_TIMEOUT = int(os.getenv("PADDLE_TIMEOUT", "180"))
DOCUMENT_OCR_ENGINE = os.getenv("DOCUMENT_OCR_ENGINE", "auto")


class ExecuteRequest(BaseModel):
    """Standardized execute request"""
    tool: str
    params: Dict[str, Any]


# Compliance check prompts by type
CHECK_PROMPTS = {
    "password_policy": """分析这张密码策略截图，提取以下信息并以JSON格式返回：
1. 密码最小长度 (min_length)
2. 密码复杂度要求 (complexity_requirements)
3. 密码最长使用期限 (max_age_days)
4. 密码历史要求 (history_count)
5. 账户锁定阈值 (lockout_threshold)
6. 账户锁定时长 (lockout_duration_minutes)

同时判断是否符合等保2.0三级要求：
- 密码长度 >= 12位
- 包含大小写字母、数字、特殊字符
- 90天内必须更换
- 登录失败5次锁定

返回JSON格式：
{
  "extracted_info": [{"key": "...", "value": "..."}],
  "judgment": "pass/fail/partial",
  "confidence": 0.0-1.0,
  "description": "判定说明",
  "remediation": "整改建议（如有不符合项）"
}""",

    "audit_config": """分析这张审计/日志配置截图，提取以下信息并以JSON格式返回：
1. 审计日志是否启用 (audit_enabled)
2. 日志留存天数 (retention_days)
3. 审计覆盖范围 (audit_scope)
4. 日志存储位置 (storage_location)

判断是否符合等保2.0要求：
- 审计日志必须启用
- 日志留存 >= 180天
- 审计覆盖所有重要操作

返回JSON格式：
{
  "extracted_info": [{"key": "...", "value": "..."}],
  "judgment": "pass/fail/partial",
  "confidence": 0.0-1.0,
  "description": "判定说明",
  "remediation": "整改建议（如有不符合项）"
}""",

    "permission": """分析这张权限配置截图，提取以下信息并以JSON格式返回：
1. 用户/角色列表 (users_roles)
2. 权限分配情况 (permission_assignments)
3. 是否存在三权分立 (separation_of_duties)
4. 是否存在权限过大情况 (over_privileged)

判断是否符合等保2.0要求：
- 系统管理员、安全管理员、审计管理员三权分立
- 遵循最小权限原则

返回JSON格式：
{
  "extracted_info": [{"key": "...", "value": "..."}],
  "judgment": "pass/fail/partial",
  "confidence": 0.0-1.0,
  "description": "判定说明",
  "remediation": "整改建议（如有不符合项）"
}""",

    "network_topology": """分析这张网络拓扑图，提取以下信息并以JSON格式返回：
1. 网络分段情况 (network_segments)
2. 关键设备 (key_devices)
3. 冗余设计 (redundancy)
4. 边界防护设备 (boundary_protection)

判断是否符合等保2.0要求：
- 网络应进行合理分段
- 关键设备应有冗余
- 边界应有防护措施

返回JSON格式：
{
  "extracted_info": [{"key": "...", "value": "..."}],
  "judgment": "pass/fail/partial",
  "confidence": 0.0-1.0,
  "description": "判定说明",
  "remediation": "整改建议（如有不符合项）"
}""",

    "other": """分析这张截图，提取与等保合规相关的配置信息，并以JSON格式返回。
重点关注：
1. 关键配置项
2. 安全设置
3. 可能的合规风险

返回JSON格式：
{
  "extracted_info": [{"key": "...", "value": "..."}],
  "judgment": "pass/fail/partial/unknown",
  "confidence": 0.0-1.0,
  "description": "分析说明",
  "remediation": "建议（如有）"
}""",
}


async def analyze_with_openai_vision(image_base64: str, check_type: str, additional_context: Optional[str] = None) -> dict:
    """Analyze screenshot using OpenAI Vision API."""
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY not configured")

    prompt = CHECK_PROMPTS.get(check_type, CHECK_PROMPTS["other"])
    if additional_context:
        prompt += f"\n\n额外上下文: {additional_context}"

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_base64}",
                            "detail": "high",
                        },
                    },
                ],
            }
        ],
        "max_tokens": 2000,
        "temperature": 0.1,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
        )

        if response.status_code != 200:
            raise ValueError(f"OpenAI API error: {response.status_code}")

        result = response.json()
        content = result["choices"][0]["message"]["content"]

        # Try to parse JSON from response
        try:
            # Find JSON in response
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            return json.loads(content.strip())
        except (json.JSONDecodeError, IndexError):
            return {
                "extracted_info": [],
                "judgment": "unknown",
                "confidence": 0.0,
                "description": content,
                "remediation": None,
            }


async def ocr_analyze(params: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze screenshot for compliance checking."""
    image_base64 = params.get("image_base64")
    if not image_base64:
        raise ValueError("Missing required parameter: image_base64")

    check_type = params.get("check_type", "other")
    clause_id = params.get("clause_id")
    additional_context = params.get("additional_context")

    start_time = time.time()

    try:
        result = await analyze_with_openai_vision(
            image_base64=image_base64,
            check_type=check_type,
            additional_context=additional_context,
        )

        duration_ms = int((time.time() - start_time) * 1000)

        # Return standardized format
        return {
            "tool": "ocr_analyze",
            "version": "1.0",
            "status": "success",
            "data": {
                "check_type": check_type,
                "clause_id": clause_id,
                "extracted_info": result.get("extracted_info", []),
                "judgment": result.get("judgment"),
                "confidence": result.get("confidence"),
                "description": result.get("description"),
                "remediation": result.get("remediation"),
            },
            "metadata": {
                "duration_ms": duration_ms,
                "analyze_time": datetime.utcnow().isoformat(),
            },
        }

    except Exception as e:
        raise ValueError(f"OCR analysis error: {e}")


def _collect_document_blocks(value: Any, blocks: List[Dict[str, Any]]) -> None:
    if isinstance(value, list):
        for item in value:
            _collect_document_blocks(item, blocks)
        return
    if not isinstance(value, dict):
        return

    text = value.get("content") or value.get("text") or value.get("rec_text")
    label = str(value.get("label") or value.get("block_label") or value.get("type") or "text").lower()
    if isinstance(text, (str, int, float)) and str(text).strip():
        block_type = "table" if "table" in label else ("chart" if "chart" in label else ("heading" if "title" in label else "text"))
        blocks.append({
            "type": block_type,
            "text": str(text).strip(),
            "bbox": value.get("bbox") or value.get("coordinate") or value.get("box"),
            "confidence": value.get("score") or value.get("confidence") or 0.8,
            "table": value.get("table") or value.get("cells"),
        })
    for child in value.values():
        if isinstance(child, (dict, list)):
            _collect_document_blocks(child, blocks)


_PADDLE_VL_SCRIPT = r"""
import json
import sys

from paddleocr import PaddleOCRVL

MARKER = "__CERTIPROOF_JSON__"
image_path, use_chart, device = sys.argv[1], sys.argv[2] == "true", sys.argv[3]
pipeline = PaddleOCRVL(
    pipeline_version="v1.6",
    device=device,
    use_layout_detection=True,
)
items = []
for result in pipeline.predict(input=image_path, use_chart_recognition=use_chart):
    payload = getattr(result, "json", None)
    if callable(payload):
        payload = payload()
    if isinstance(payload, str):
        payload = json.loads(payload)
    elif not isinstance(payload, dict):
        payload = getattr(result, "res", None) or {}
    items.append(payload if isinstance(payload, dict) else {})
print(MARKER + json.dumps(items, ensure_ascii=False))
"""


def _clean_paddle_error(message: str, returncode: int | None = None) -> str:
    text = re.sub(r"\x1b\[[0-9;]*m", "", message or "")
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if returncode in (-9, 137):
        return "PaddleOCR-VL 进程被系统终止，通常是内存不足或当前 CPU 容器运行时不兼容。"
    if returncode in (-11, 139):
        return "PaddleOCR-VL 底层运行时崩溃，当前容器架构/CPU 推理环境不兼容。"
    if "Can not import paddle core" in text or "libpaddle" in text:
        return "PaddleOCR-VL 无法加载 libpaddle，当前容器架构或 Paddle 安装不兼容。"
    return (text[-600:] if text else f"PaddleOCR-VL exited with code {returncode}")


def _parse_with_paddle_vl(image_path: str, use_chart_recognition: bool) -> List[Dict[str, Any]]:
    # ponytail: isolate Paddle native crashes; if libpaddle segfaults, the API process survives.
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                _PADDLE_VL_SCRIPT,
                image_path,
                "true" if use_chart_recognition else "false",
                PADDLE_DEVICE,
            ],
            capture_output=True,
            text=True,
            timeout=PADDLE_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"PaddleOCR-VL 视觉解析超过 {PADDLE_TIMEOUT} 秒未完成。") from exc
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(_clean_paddle_error(stderr, completed.returncode))
    output = completed.stdout.strip()
    marker = "__CERTIPROOF_JSON__"
    if marker not in output:
        raise RuntimeError("PaddleOCR-VL 未返回可解析结果。")
    return json.loads(output.split(marker, 1)[1])


_RAPIDOCR_SCRIPT = r"""
import json
import sys

from rapidocr_onnxruntime import RapidOCR

MARKER = "__CERTIPROOF_JSON__"
engine = RapidOCR()
result, _ = engine(sys.argv[1])
blocks = []
for item in result or []:
    box, text, score = item[0], item[1], item[2]
    if text and str(text).strip():
        blocks.append({
            "type": "text",
            "text": str(text).strip(),
            "bbox": box,
            "confidence": float(score or 0.7),
            "source": "ocr",
        })
print(MARKER + json.dumps(blocks, ensure_ascii=False))
"""


def _parse_with_rapidocr(image_path: str) -> List[Dict[str, Any]]:
    try:
        completed = subprocess.run(
            [sys.executable, "-c", _RAPIDOCR_SCRIPT, image_path],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("RapidOCR 轻量 OCR 超过 60 秒未完成。") from exc
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(_clean_paddle_error(stderr, completed.returncode))
    marker = "__CERTIPROOF_JSON__"
    output = completed.stdout.strip()
    if marker not in output:
        raise RuntimeError("RapidOCR 未返回可解析结果。")
    return json.loads(output.split(marker, 1)[1])


async def document_page_parse(params: Dict[str, Any]) -> Dict[str, Any]:
    global _document_pipeline_error, _rapidocr_error
    image_base64 = params.get("image_base64")
    if not image_base64:
        raise ValueError("Missing required parameter: image_base64")
    image_bytes = base64.b64decode(image_base64)
    suffix = Path(params.get("file_name") or "page.png").suffix or ".png"
    started = time.time()

    with tempfile.NamedTemporaryFile(suffix=suffix) as temp:
        temp.write(image_bytes)
        temp.flush()
        blocks: List[Dict[str, Any]] = []
        used_engine = None
        errors: List[str] = []
        if DOCUMENT_OCR_ENGINE in {"auto", "vision"}:
            try:
                output = await asyncio.to_thread(
                    _parse_with_paddle_vl,
                    temp.name,
                    bool(params.get("use_chart_recognition", True)),
                )
                _document_pipeline_error = None
                used_engine = "PaddleOCR-VL-1.6"
                for payload in output:
                    _collect_document_blocks(payload, blocks)
                    if not blocks:
                        markdown = payload.get("markdown") if isinstance(payload, dict) else None
                        text = markdown.get("text") if isinstance(markdown, dict) else None
                        if text:
                            blocks.append({"type": "text", "text": text, "confidence": 0.75, "source": "vision"})
            except Exception as exc:
                _document_pipeline_error = str(exc)
                errors.append(f"PaddleOCR-VL-1.6：{exc}")

        if not blocks and DOCUMENT_OCR_ENGINE in {"auto", "ocr"}:
            try:
                blocks = await asyncio.to_thread(_parse_with_rapidocr, temp.name)
                _rapidocr_error = None
                used_engine = "RapidOCR-ONNXRuntime"
            except Exception as exc:
                _rapidocr_error = str(exc)
                errors.append(f"RapidOCR：{exc}")

        if not blocks:
            return {
                "tool": "document_page_parse",
                "version": "1.0",
                "status": "failed",
                "error": "；".join(errors) or "未提取到可分析的图像文字。",
                "data": {
                    "blocks": [],
                    "model": used_engine or DOCUMENT_OCR_ENGINE,
                    "device": PADDLE_DEVICE,
                    "fallback": DOCUMENT_OCR_ENGINE == "auto",
                },
                "metadata": {"duration_ms": int((time.time() - started) * 1000)},
            }

    return {
        "tool": "document_page_parse",
        "version": "1.0",
        "status": "success",
        "data": {
            "blocks": blocks,
            "model": used_engine,
            "device": PADDLE_DEVICE,
            "fallback": used_engine == "RapidOCR-ONNXRuntime",
        },
        "metadata": {"duration_ms": int((time.time() - started) * 1000)},
    }


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": "OCR MCP Server",
        "version": "1.0.0",
        "tools": ["ocr_analyze", "screenshot_analyze", "document_page_parse"],
    }


@app.get("/health")
async def health():
    """Health check"""
    api_configured = bool(OPENAI_API_KEY)
    local_status = "failed" if (_document_pipeline_error and _rapidocr_error) else "lazy"
    return {
        "status": "degraded" if local_status == "failed" and not api_configured else "healthy",
        "tools": ["ocr_analyze", "screenshot_analyze", "document_page_parse"],
        "openai_api_configured": api_configured,
        "document_model": DOCUMENT_OCR_ENGINE,
        "document_model_loaded": False,
        "document_model_error": _document_pipeline_error,
        "document_ocr_fallback_error": _rapidocr_error,
        "document_model_status": local_status,
    }


@app.post("/execute")
async def execute(request: ExecuteRequest):
    """Execute tool - standardized endpoint for gateway"""
    tool_name = request.tool
    params = request.params

    if tool_name in ["ocr_analyze", "screenshot_analyze"]:
        return await ocr_analyze(params)
    if tool_name == "document_page_parse":
        return await document_page_parse(params)

    raise HTTPException(
        status_code=404,
        detail=f"Unknown tool: {tool_name}"
    )


@app.post("/analyze/upload")
async def analyze_screenshot_upload(
    file: UploadFile = File(...),
    check_type: str = Form(...),
    clause_id: Optional[str] = Form(None),
    additional_context: Optional[str] = Form(None),
):
    """Upload and analyze screenshot for compliance checking."""
    # Read file
    contents = await file.read()
    image_base64 = base64.b64encode(contents).decode("utf-8")

    params = {
        "image_base64": image_base64,
        "check_type": check_type,
        "clause_id": clause_id,
        "additional_context": additional_context,
    }

    return await ocr_analyze(params)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)

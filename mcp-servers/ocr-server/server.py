"""
OCR MCP Server - CertiProof
Exposes screenshot OCR and AI analysis as an MCP tool.
Uses OpenAI Vision API for intelligent screenshot analysis.
"""

import base64
import io
import os
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
import httpx

app = FastAPI(title="OCR MCP Server", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")


# --- Models ---

class ScreenshotAnalysisRequest(BaseModel):
    image_base64: str = Field(..., description="Base64 encoded image")
    check_type: str = Field(..., description="What to check: password_policy, audit_config, permission, network_topology, other")
    clause_id: Optional[str] = Field(None, description="Related compliance clause ID")
    additional_context: Optional[str] = Field(None, description="Additional context for analysis")


class ExtractedInfo(BaseModel):
    key: str
    value: str
    confidence: float = 1.0


class ScreenshotAnalysisResult(BaseModel):
    check_type: str
    clause_id: Optional[str] = None
    extracted_info: List[ExtractedInfo] = []
    judgment: Optional[str] = None  # pass, fail, partial, unknown
    confidence: Optional[float] = None
    description: Optional[str] = None
    remediation: Optional[str] = None
    raw_text: Optional[str] = None
    error: Optional[str] = None


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
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY not configured. Set it in environment variables.",
        )

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
            raise HTTPException(
                status_code=500,
                detail=f"OpenAI API error: {response.status_code} - {response.text[:500]}",
            )

        result = response.json()
        content = result["choices"][0]["message"]["content"]

        # Try to parse JSON from response
        import json
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


# --- API ---

@app.get("/")
async def root():
    return {"name": "OCR MCP Server", "version": "0.1.0", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/analyze", response_model=ScreenshotAnalysisResult)
async def analyze_screenshot(request: ScreenshotAnalysisRequest):
    """Analyze screenshot for compliance checking."""
    try:
        result = await analyze_with_openai_vision(
            image_base64=request.image_base64,
            check_type=request.check_type,
            additional_context=request.additional_context,
        )

        # Parse extracted info
        extracted_info = []
        for item in result.get("extracted_info", []):
            extracted_info.append(ExtractedInfo(
                key=item.get("key", ""),
                value=str(item.get("value", "")),
                confidence=item.get("confidence", 1.0),
            ))

        return ScreenshotAnalysisResult(
            check_type=request.check_type,
            clause_id=request.clause_id,
            extracted_info=extracted_info,
            judgment=result.get("judgment"),
            confidence=result.get("confidence"),
            description=result.get("description"),
            remediation=result.get("remediation"),
        )

    except HTTPException:
        raise
    except Exception as e:
        return ScreenshotAnalysisResult(
            check_type=request.check_type,
            clause_id=request.clause_id,
            error=str(e),
        )


@app.post("/analyze/upload", response_model=ScreenshotAnalysisResult)
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

    request = ScreenshotAnalysisRequest(
        image_base64=image_base64,
        check_type=check_type,
        clause_id=clause_id,
        additional_context=additional_context,
    )

    return await analyze_screenshot(request)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)

# -*- coding: utf-8 -*-
"""
Kiro API 请求/响应的 Pydantic 模型。

基于 kiro-gateway 逆向出的 Kiro API 专有格式。
注意：所有字段设为 Optional/带默认值，因为 Kiro 实际请求可能缺字段。
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


# ===================================================================
# Kiro 请求模型（宽松验证）
# ===================================================================

class KiroImage(BaseModel):
    """Kiro 图片格式"""
    model_config = ConfigDict(extra="allow")
    mediaType: str = "image/jpeg"
    data: str = ""


class KiroToolInputSchema(BaseModel):
    """Kiro 工具输入 schema"""
    model_config = ConfigDict(extra="allow")
    type: str = "object"
    properties: Dict[str, Any] = Field(default_factory=dict)
    required: List[str] = Field(default_factory=list)


class KiroToolSpecification(BaseModel):
    """Kiro 工具规范（嵌套在 toolSpecification 字段里）"""
    model_config = ConfigDict(extra="allow")
    name: str = ""
    description: str = ""
    inputSchema: Dict[str, Any] = Field(default_factory=dict)


class KiroTool(BaseModel):
    """Kiro 工具定义

    Kiro 真实 API 格式: {"toolSpecification": {name, description, inputSchema}}
    Kiro IDE 也用这个嵌套格式。
    """
    model_config = ConfigDict(extra="allow")
    # 嵌套格式（Kiro 真实 API/Kiro IDE 实际发的）
    toolSpecification: Optional[KiroToolSpecification] = None
    # 兼容：直接扁平字段
    name: str = ""
    description: str = ""
    inputSchema: Dict[str, Any] = Field(default_factory=dict)

    def get_name(self) -> str:
        if self.toolSpecification and self.toolSpecification.name:
            return self.toolSpecification.name
        return self.name

    def get_description(self) -> str:
        if self.toolSpecification and self.toolSpecification.description:
            return self.toolSpecification.description
        return self.description

    def get_input_schema(self) -> Dict[str, Any]:
        if self.toolSpecification and self.toolSpecification.inputSchema:
            return self.toolSpecification.inputSchema
        return self.inputSchema


class KiroToolResult(BaseModel):
    """Kiro 工具结果"""
    model_config = ConfigDict(extra="allow")
    toolUseId: str = ""
    content: Any = ""


class KiroToolUse(BaseModel):
    """Kiro 工具使用记录"""
    model_config = ConfigDict(extra="allow")
    toolUseId: str = ""
    name: str = ""
    input: Any = None


class KiroUserInputMessageContext(BaseModel):
    """Kiro 用户消息上下文"""
    model_config = ConfigDict(extra="allow")
    tools: Optional[List[KiroTool]] = None
    toolResults: Optional[List[KiroToolResult]] = None


class KiroUserInputMessage(BaseModel):
    """Kiro 用户输入消息"""
    model_config = ConfigDict(extra="allow")
    content: str = ""
    modelId: str = ""
    origin: str = "AI_EDITOR"
    images: Optional[List[KiroImage]] = None
    userInputMessageContext: Optional[KiroUserInputMessageContext] = None


class KiroAssistantResponseMessage(BaseModel):
    """Kiro 助手响应消息"""
    model_config = ConfigDict(extra="allow")
    content: str = ""
    toolUses: Optional[List[KiroToolUse]] = None


class KiroCurrentMessage(BaseModel):
    """Kiro 当前消息封装"""
    model_config = ConfigDict(extra="allow")
    userInputMessage: KiroUserInputMessage = Field(default_factory=KiroUserInputMessage)


class KiroConversationState(BaseModel):
    """Kiro 会话状态"""
    model_config = ConfigDict(extra="allow")
    chatTriggerType: str = "MANUAL"
    conversationId: str = ""
    currentMessage: KiroCurrentMessage = Field(default_factory=KiroCurrentMessage)
    history: Optional[List[Dict[str, Any]]] = None


class KiroRequest(BaseModel):
    """Kiro generateAssistantResponse 请求体"""
    model_config = ConfigDict(extra="allow")
    conversationState: KiroConversationState = Field(default_factory=KiroConversationState)
    profileArn: str = ""


# ===================================================================
# Kiro 响应事件模型（用于构建 AWS Event Stream）
# ===================================================================

class KiroContentEvent(BaseModel):
    content: str = ""


class KiroToolStartEvent(BaseModel):
    name: str = ""
    toolUseId: str = ""
    input: Any = {}


class KiroToolStopEvent(BaseModel):
    stop: bool = True


class KiroUsageEvent(BaseModel):
    usage: int = 0

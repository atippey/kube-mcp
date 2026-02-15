"""Pydantic models for MCP CRDs.

These models mirror the CRD schemas and provide validation for the operator.
"""

from typing import Any

from pydantic import BaseModel, Field, model_validator

# =============================================================================
# Common models
# =============================================================================


class ServiceReference(BaseModel):
    """Reference to a Kubernetes service."""

    name: str = Field(..., min_length=1, max_length=253)
    namespace: str | None = Field(default=None, min_length=1, max_length=63)
    port: int = Field(..., ge=1, le=65535)
    path: str = Field(default="/", pattern=r"^/.*$")


class LabelSelectorRequirement(BaseModel):
    """A label selector requirement."""

    key: str
    operator: str = Field(..., pattern=r"^(In|NotIn|Exists|DoesNotExist)$")
    values: list[str] | None = None


class LabelSelector(BaseModel):
    """A label selector for matching resources."""

    matchLabels: dict[str, str] | None = None
    matchExpressions: list[LabelSelectorRequirement] | None = None


class Condition(BaseModel):
    """A condition for status reporting."""

    type: str
    status: str = Field(..., pattern=r"^(True|False|Unknown)$")
    lastTransitionTime: str | None = None
    reason: str | None = None
    message: str | None = None


# =============================================================================
# MCPServer
# =============================================================================


class RedisConfig(BaseModel):
    """Redis configuration for MCPServer."""

    serviceName: str = Field(..., min_length=1, max_length=253)


class IngressConfig(BaseModel):
    """Ingress configuration for MCPServer."""

    host: str | None = Field(default=None, min_length=1, max_length=253)
    tlsSecretName: str | None = Field(default=None, min_length=1, max_length=253)
    pathPrefix: str = Field(default="/mcp", pattern=r"^/[a-z0-9/-]*$")


class ServerConfig(BaseModel):
    """Server configuration for MCPServer."""

    requestTimeout: str = Field(default="30s", pattern=r"^[0-9]+(s|m|h)$")
    maxConcurrentRequests: int = Field(default=100, ge=1, le=10000)


class MCPServerSpec(BaseModel):
    """MCPServer spec."""

    replicas: int = Field(default=1, ge=1, le=10)
    image: str = Field(default="ghcr.io/atippey/mcp-echo-server:latest")
    redis: RedisConfig
    ingress: IngressConfig | None = None
    toolSelector: LabelSelector
    config: ServerConfig | None = None


class MCPServerStatus(BaseModel):
    """MCPServer status."""

    readyReplicas: int = 0
    toolCount: int = 0
    promptCount: int = 0
    resourceCount: int = 0
    conditions: list[Condition] = Field(default_factory=list)


# =============================================================================
# MCPTool
# =============================================================================


class ToolEntry(BaseModel):
    """A single tool entry in a multi-tool MCPTool."""

    name: str = Field(..., min_length=1, max_length=63)
    path: str = Field(..., pattern=r"^/.*$")
    description: str | None = Field(default=None, max_length=500)
    inputSchema: dict[str, Any] | None = None
    method: str = Field(default="POST", pattern=r"^(GET|POST|PUT|DELETE|PATCH)$")


class MCPToolSpec(BaseModel):
    """MCPTool spec.

    Supports two modes:
    - Single-tool: set ``name`` (and optionally ``inputSchema``, ``method``, etc.)
    - Multi-tool: set ``tools`` with a list of ToolEntry items sharing ``service``
    """

    name: str | None = Field(default=None, min_length=1, max_length=63)
    description: str | None = Field(default=None, max_length=500)
    service: ServiceReference
    inputSchema: dict[str, Any] | None = None
    method: str = Field(default="POST", pattern=r"^(GET|POST|PUT|DELETE|PATCH)$")
    ingressPath: str | None = Field(default=None, pattern=r"^/.*$")
    tools: list[ToolEntry] | None = None

    @model_validator(mode="after")
    def validate_tool_mode(self) -> "MCPToolSpec":
        """Ensure exactly one of 'name' (single-tool) or 'tools' (multi-tool) is set."""
        if self.name and self.tools:
            raise ValueError(
                "Cannot specify both 'name' and 'tools'. "
                "Use 'name' for single-tool mode or 'tools' for multi-tool mode."
            )
        if not self.name and not self.tools:
            raise ValueError("Must specify either 'name' (single-tool) or 'tools' (multi-tool).")
        return self


class MCPToolStatus(BaseModel):
    """MCPTool status."""

    ready: bool = False
    resolvedEndpoint: str | None = None
    lastSyncTime: str | None = None
    conditions: list[Condition] = Field(default_factory=list)


# =============================================================================
# MCPPrompt
# =============================================================================


class PromptVariable(BaseModel):
    """A variable in an MCPPrompt template."""

    name: str = Field(..., min_length=1, max_length=63, pattern=r"^[a-zA-Z0-9_]+$")
    description: str | None = Field(default=None, max_length=200)
    required: bool = False
    default: str | None = None


class MCPPromptSpec(BaseModel):
    """MCPPrompt spec."""

    name: str = Field(..., min_length=1, max_length=63)
    description: str | None = Field(default=None, max_length=500)
    template: str = Field(..., min_length=1, max_length=10000)
    variables: list[PromptVariable] = Field(default_factory=list)
    ingressPath: str | None = Field(default=None, pattern=r"^/.*$")


class MCPPromptStatus(BaseModel):
    """MCPPrompt status."""

    validated: bool = False
    lastValidationTime: str | None = None
    conditions: list[Condition] = Field(default_factory=list)


# =============================================================================
# MCPResource
# =============================================================================


class OperationParameter(BaseModel):
    """A parameter for an MCPResource operation."""

    name: str = Field(..., min_length=1, max_length=63, pattern=r"^[a-zA-Z0-9_]+$")
    in_: str = Field(..., alias="in", pattern=r"^(path|query|header)$")
    required: bool = False
    description: str | None = Field(default=None, max_length=200)


class ResourceOperation(BaseModel):
    """An HTTP operation for an MCPResource."""

    method: str = Field(..., pattern=r"^(GET|POST|PUT|DELETE|PATCH)$")
    ingressPath: str = Field(..., pattern=r"^/.*$")
    service: ServiceReference
    parameters: list[OperationParameter] = Field(default_factory=list)


class InlineContent(BaseModel):
    """Inline content for an MCPResource."""

    uri: str = Field(..., min_length=1, max_length=500)
    mimeType: str = Field(default="text/plain", pattern=r"^[a-z]+/[a-z0-9+.-]+$")
    text: str | None = Field(default=None, max_length=100000)
    blob: str | None = None  # Base64-encoded binary


class MCPResourceSpec(BaseModel):
    """MCPResource spec."""

    name: str = Field(..., min_length=1, max_length=63)
    description: str | None = Field(default=None, max_length=500)
    operations: list[ResourceOperation] | None = None
    content: InlineContent | None = None


class MCPResourceStatus(BaseModel):
    """MCPResource status."""

    ready: bool = False
    operationCount: int = 0
    lastSyncTime: str | None = None
    conditions: list[Condition] = Field(default_factory=list)

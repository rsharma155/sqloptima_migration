"""
Module: ai_provider.py
Purpose: LLM provider abstraction layer (OpenAI, Anthropic, local)
Author: Migration Platform Team
Created: 2026-05-22
Domain: Infrastructure AI
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class AiProviderType(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    LOCAL = "local"


class AiRole(StrEnum):
    CODE_EXPLANATION = "code_explanation"
    DYNAMIC_SQL_INFERENCE = "dynamic_sql_inference"
    MIGRATION_RECOMMENDATION = "migration_recommendation"
    RISK_ANALYSIS = "risk_analysis"
    CODE_REWRITE = "code_rewrite"
    COMPLEXITY_ESTIMATION = "complexity_estimation"


@dataclass
class AiRequest:
    """A request to the AI service."""

    prompt: str
    role: AiRole = AiRole.CODE_EXPLANATION
    context: dict[str, Any] = field(default_factory=dict)
    max_tokens: int = 1000
    temperature: float = 0.3
    model: str | None = None


@dataclass
class AiResponse:
    """A response from the AI service."""

    content: str
    success: bool = True
    error: str | None = None
    model_used: str | None = None
    tokens_used: int = 0
    provider: AiProviderType | None = None


class AiProvider(ABC):
    """Abstract port for AI/LLM providers."""

    @abstractmethod
    async def generate(self, request: AiRequest) -> AiResponse:
        """Generate a response from the AI model."""

    @abstractmethod
    def supports_role(self, role: AiRole) -> bool:
        """Check if this provider supports the given role."""

    @property
    @abstractmethod
    def provider_type(self) -> AiProviderType:
        """Return the provider type."""


class AiService:
    """AI service that routes requests to appropriate providers.

    AI usage is OPTIONAL and ADVISORY only. AI must NEVER directly
    execute migration logic or generate production SQL without validation.
    """

    def __init__(self):
        self._providers: dict[AiProviderType, AiProvider] = {}

    def register_provider(self, provider: AiProvider) -> None:
        """Register an AI provider."""
        self._providers[provider.provider_type] = provider

    async def analyze_code(
        self,
        sql: str,
        role: AiRole = AiRole.CODE_EXPLANATION,
        provider_type: AiProviderType | None = None,
    ) -> AiResponse:
        """Analyze SQL code using AI.

        Args:
            sql: The SQL code to analyze.
            role: The analysis role.
            provider_type: Optional specific provider to use.

        Returns:
            AiResponse with analysis results.
        """
        provider = self._select_provider(role, provider_type)
        if not provider:
            return AiResponse(
                content="",
                success=False,
                error=f"No provider available for role {role.value}",
            )

        prompt = self._build_prompt(role, sql)
        request = AiRequest(prompt=prompt, role=role)
        return await provider.generate(request)

    async def suggest_rewrite(
        self,
        source_sql: str,
        context: dict[str, Any] | None = None,
    ) -> AiResponse:
        """Suggest a PostgreSQL rewrite for T-SQL code.

        IMPORTANT: AI suggestions are advisory. All generated SQL must
        be validated before use.
        """
        request = AiRequest(
            prompt=(
                f"Convert this T-SQL code to PostgreSQL PL/pgSQL:\n\n"
                f"{source_sql}\n\n"
                f"Context: {context or {}}\n"
                f"Provide only the converted code without explanation."
            ),
            role=AiRole.CODE_REWRITE,
            temperature=0.2,
        )
        provider = self._select_provider(AiRole.CODE_REWRITE)
        if not provider:
            return AiResponse(
                content="",
                success=False,
                error="No provider available for code rewrite",
            )
        return await provider.generate(request)

    def _select_provider(
        self,
        role: AiRole,
        preferred: AiProviderType | None = None,
    ) -> AiProvider | None:
        if preferred and preferred in self._providers:
            return self._providers[preferred]
        for provider in self._providers.values():
            if provider.supports_role(role):
                return provider
        return None

    @staticmethod
    def _build_prompt(role: AiRole, sql: str) -> str:
        prompts = {
            AiRole.CODE_EXPLANATION: f"Explain what this T-SQL code does:\n\n{sql}",
            AiRole.DYNAMIC_SQL_INFERENCE: (
                f"Analyze this dynamic SQL and infer its likely structure:\n\n{sql}\n\n"
                f"Provide the probable static SQL template."
            ),
            AiRole.MIGRATION_RECOMMENDATION: (
                f"Analyze this SQL Server object for PostgreSQL migration compatibility:\n\n{sql}"
            ),
            AiRole.RISK_ANALYSIS: (
                f"Identify risks in migrating this SQL Server code to PostgreSQL:\n\n{sql}"
            ),
            AiRole.COMPLEXITY_ESTIMATION: (
                f"Estimate the conversion complexity (simple/moderate/complex/extreme) "
                f"for migrating this T-SQL to PL/pgSQL:\n\n{sql}"
            ),
        }
        return prompts.get(role, f"Analyze this SQL:\n\n{sql}")

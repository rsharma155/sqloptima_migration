"""
Module: test_ai_provider.py
Purpose: Unit tests for AI provider abstraction
Author: Migration Platform Team
Created: 2026-05-22
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from unittest.mock import AsyncMock

import pytest

from infrastructure.ai.ai_provider import (
    AiProvider,
    AiProviderType,
    AiRequest,
    AiResponse,
    AiRole,
    AiService,
)


class MockAiProvider(AiProvider):
    def __init__(self, provider_type: AiProviderType = AiProviderType.LOCAL):
        self._type = provider_type
        self.generate = AsyncMock(
            return_value=AiResponse(
                content="Mock analysis result",
                success=True,
                provider=provider_type,
            )
        )

    async def generate(self, request: AiRequest) -> AiResponse:
        return AiResponse(
            content=f"Analysis for {request.role.value}: {request.prompt[:50]}",
            success=True,
            provider=self._type,
        )

    def supports_role(self, role: AiRole) -> bool:
        return True

    @property
    def provider_type(self) -> AiProviderType:
        return self._type


class TestAiRequest:
    def test_create_request(self):
        req = AiRequest(prompt="Test prompt", role=AiRole.CODE_EXPLANATION)
        assert req.prompt == "Test prompt"
        assert req.role == AiRole.CODE_EXPLANATION
        assert req.temperature == 0.3

    def test_default_values(self):
        req = AiRequest(prompt="Hello")
        assert req.role == AiRole.CODE_EXPLANATION
        assert req.max_tokens == 1000


class TestAiResponse:
    def test_success_response(self):
        resp = AiResponse(content="Result", success=True)
        assert resp.content == "Result"
        assert resp.success is True

    def test_error_response(self):
        resp = AiResponse(content="", success=False, error="API Error")
        assert resp.success is False
        assert resp.error == "API Error"


class TestAiService:
    @pytest.fixture
    def service(self):
        svc = AiService()
        svc.register_provider(MockAiProvider(AiProviderType.LOCAL))
        return svc

    @pytest.mark.asyncio
    async def test_analyze_code(self, service):
        response = await service.analyze_code(
            sql="SELECT * FROM users",
            role=AiRole.CODE_EXPLANATION,
        )
        assert response.success is True
        assert response.content is not None

    @pytest.mark.asyncio
    async def test_suggest_rewrite(self, service):
        response = await service.suggest_rewrite(
            source_sql="SELECT ISNULL(name, 'N/A') FROM users",
        )
        assert response.success is True

    @pytest.mark.asyncio
    async def test_no_provider_for_role(self):
        service = AiService()
        response = await service.analyze_code("SELECT 1", AiRole.DYNAMIC_SQL_INFERENCE)
        assert response.success is False
        assert "No provider" in response.error

    def test_select_preferred_provider(self):
        service = AiService()
        local = MockAiProvider(AiProviderType.LOCAL)
        openai = MockAiProvider(AiProviderType.OPENAI)
        service.register_provider(local)
        service.register_provider(openai)
        assert len(service._providers) == 2

    def test_build_prompt(self):
        prompt = AiService._build_prompt(AiRole.CODE_EXPLANATION, "SELECT 1")
        assert "SELECT 1" in prompt

    @pytest.mark.asyncio
    async def test_analyze_with_multiple_providers(self, service):
        openai_provider = MockAiProvider(AiProviderType.OPENAI)
        service.register_provider(openai_provider)

        response = await service.analyze_code(
            sql="SELECT 1",
            role=AiRole.RISK_ANALYSIS,
        )
        assert response.success is True

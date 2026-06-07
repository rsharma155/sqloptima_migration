"""Secret provider abstraction — resolves vault references to plaintext values.

Supported providers (configured via SECRET_PROVIDER env var):
  env     — dev passthrough; returns the ref unchanged (no external system)
  vault   — HashiCorp Vault KV v2 (requires VAULT_ADDR, VAULT_TOKEN)
  aws     — AWS Secrets Manager (uses boto3 default credential chain)
  azure   — Azure Key Vault (requires AZURE_VAULT_URL; uses DefaultAzureCredential)
  gcp     — GCP Secret Manager (uses ADC; requires GCP_PROJECT_ID)

Ref format per provider:
  vault   "mount/path#field"          e.g. "secret/prod/sqlserver#password"
  aws     "secret-name#field"         e.g. "prod/sqlserver#password"
  azure   "secret-name"               e.g. "prod-sqlserver-password"
  gcp     "secret-name#version"       e.g. "prod-sqlserver-password#latest"
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod


class SecretProvider(ABC):
    @abstractmethod
    def resolve(self, ref: str) -> str:
        """Resolve a vault reference to a plaintext secret value."""


class EnvPassthroughProvider(SecretProvider):
    """Dev-only: returns the ref as-is — no external secret system needed."""

    def resolve(self, ref: str) -> str:
        return ref


class VaultProvider(SecretProvider):
    """HashiCorp Vault KV v2.

    Ref format: ``mount/path#field``  (e.g. ``secret/prod/sqlserver#password``)
    Requires env vars: VAULT_ADDR, VAULT_TOKEN
    """

    def __init__(self) -> None:
        import hvac  # type: ignore[import]

        self._client = hvac.Client(
            url=os.environ["VAULT_ADDR"],
            token=os.environ["VAULT_TOKEN"],
        )

    def resolve(self, ref: str) -> str:
        path, _, field = ref.partition("#")
        parts = path.split("/", 1)
        mount, secret_path = (parts[0], parts[1]) if len(parts) == 2 else ("secret", path)
        result = self._client.secrets.kv.v2.read_secret_version(
            path=secret_path, mount_point=mount
        )
        return result["data"]["data"][field or "value"]


class AwsSecretsManagerProvider(SecretProvider):
    """AWS Secrets Manager.

    Ref format: ``secret-id#field``  (e.g. ``prod/sqlserver#password``)
    Uses the boto3 default credential chain (IAM role, env vars, ~/.aws/credentials).
    """

    def __init__(self) -> None:
        import boto3  # type: ignore[import]

        self._client = boto3.client("secretsmanager")

    def resolve(self, ref: str) -> str:
        import json

        secret_id, _, field = ref.partition("#")
        response = self._client.get_secret_value(SecretId=secret_id)
        raw = response.get("SecretString", "")
        if field:
            return json.loads(raw)[field]
        return raw


class AzureKeyVaultProvider(SecretProvider):
    """Azure Key Vault.

    Ref format: ``secret-name``  (e.g. ``prod-sqlserver-password``)
    Requires env var: AZURE_VAULT_URL
    Uses DefaultAzureCredential (managed identity, env vars, CLI, etc.).
    """

    def __init__(self) -> None:
        from azure.identity import DefaultAzureCredential  # type: ignore[import]
        from azure.keyvault.secrets import SecretClient  # type: ignore[import]

        vault_url = os.environ["AZURE_VAULT_URL"]
        self._client = SecretClient(vault_url=vault_url, credential=DefaultAzureCredential())

    def resolve(self, ref: str) -> str:
        name, _, version = ref.partition("/")
        secret = self._client.get_secret(name, version=version or None)
        return secret.value or ""


class GcpSecretManagerProvider(SecretProvider):
    """GCP Secret Manager.

    Ref format: ``secret-name#version``  (e.g. ``prod-sqlserver-password#latest``)
    Uses Application Default Credentials.
    Requires env var: GCP_PROJECT_ID
    """

    def __init__(self) -> None:
        from google.cloud import secretmanager  # type: ignore[import]

        self._client = secretmanager.SecretManagerServiceClient()
        self._project = os.environ["GCP_PROJECT_ID"]

    def resolve(self, ref: str) -> str:
        if ref.startswith("projects/"):
            name = ref
        else:
            secret, _, version = ref.partition("#")
            name = f"projects/{self._project}/secrets/{secret}/versions/{version or 'latest'}"
        response = self._client.access_secret_version(request={"name": name})
        return response.payload.data.decode("utf-8")


_PROVIDERS: dict[str, type[SecretProvider]] = {
    "env": EnvPassthroughProvider,
    "vault": VaultProvider,
    "aws": AwsSecretsManagerProvider,
    "azure": AzureKeyVaultProvider,
    "gcp": GcpSecretManagerProvider,
}


def build_secret_provider() -> SecretProvider:
    """Instantiate the provider selected by SECRET_PROVIDER (default: env)."""
    name = os.environ.get("SECRET_PROVIDER", "env").lower()
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown SECRET_PROVIDER '{name}'. Valid options: {list(_PROVIDERS)}"
        )
    return cls()

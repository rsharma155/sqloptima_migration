"""
Module: test_base_entity.py
Purpose: Unit tests for base entity and value object models
Author: Migration Platform Team
Created: 2026-05-22
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from uuid import UUID

import pytest

from shared.kernel.base_entity import DomainEntity, ValueObject


class TestDomainEntity:
    def test_creates_with_default_id(self):
        entity = DomainEntity()
        assert entity.id is not None
        assert isinstance(entity.id, UUID)

    def test_unique_ids(self):
        e1 = DomainEntity()
        e2 = DomainEntity()
        assert e1.id != e2.id

    def test_equality_by_id(self):
        e1 = DomainEntity()
        e2 = DomainEntity()
        assert e1 == e1
        assert e1 != e2

    def test_hash_by_id(self):
        e1 = DomainEntity()
        hash_set = {e1, e1}
        assert len(hash_set) == 1

    def test_custom_fields(self):
        entity = DomainEntity(version=3)
        assert entity.version == 3

    def test_created_at_set(self):
        entity = DomainEntity()
        assert entity.created_at is not None

    def test_updated_at_set(self):
        entity = DomainEntity()
        assert entity.updated_at is not None


class TestValueObject:
    def test_immutable(self):
        class Address(ValueObject):
            street: str
            city: str

        addr = Address(street="123 Main", city="Springfield")

        with pytest.raises(Exception):
            addr.street = "456 Oak"

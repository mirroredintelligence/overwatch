import uuid

from diucs.adapters.outbound.ids_uuid.uuid_ids import UuidGenerator


def test_new_id_is_a_uuid4_string() -> None:
    value = UuidGenerator().new_id()
    parsed = uuid.UUID(value)

    assert isinstance(value, str)
    assert parsed.version == 4
    assert str(parsed) == value


def test_successive_ids_differ() -> None:
    generator = UuidGenerator()
    assert generator.new_id() != generator.new_id()

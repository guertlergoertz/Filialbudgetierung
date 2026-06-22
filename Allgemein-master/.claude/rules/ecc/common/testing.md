# Testing Standards

## Test Structure (AAA)

```python
def test_something():
    # Arrange
    user = User(name="Alice", age=25)
    
    # Act
    result = user.is_adult()
    
    # Assert
    assert result is True
```

## What to Test

- **Always**: Business logic, edge cases, error paths
- **Sometimes**: Integration points, UI flows
- **Skip**: Framework code, getters/setters, constants

## Test Naming

```python
def test_<unit>_<scenario>_<expected>():
    ...

# Examples:
def test_engine_empty_input_returns_zero():
def test_importer_invalid_date_raises_value_error():
```

## Fixtures

```python
@pytest.fixture
def sample_filiale():
    return Filiale(id=1, name="Test", typ="standard")
```

## Mocking

```python
from unittest.mock import patch, MagicMock

def test_with_mock_db():
    with patch('module.get_connection') as mock_conn:
        mock_conn.return_value = MagicMock()
        result = function_under_test()
        assert result == expected
```

## Coverage Target

- Business logic: >80%
- UI code: >50% (harder to test)
- Database layer: >70%

# Performance Guidelines

## Measure Before Optimizing

```python
import time
start = time.perf_counter()
# ... code ...
elapsed = time.perf_counter() - start
print(f"Elapsed: {elapsed:.3f}s")
```

## Python-Specific

### DataFrame Operations
```python
# Bad: row-by-row
for i, row in df.iterrows():
    df.loc[i, 'result'] = row['a'] + row['b']

# Good: vectorized
df['result'] = df['a'] + df['b']
```

### Database Queries
```python
# Bad: N+1
for filiale in filialen:
    umsatz = db.query(f"SELECT SUM(umsatz) WHERE filiale='{filiale}'")

# Good: batch
umsaetze = db.query("SELECT filiale, SUM(umsatz) GROUP BY filiale")
```

### Memory
```python
# Use generators for large datasets
def read_large_file(path):
    with open(path) as f:
        for line in f:  # generator, not list
            yield process(line)
```

## Caching

```python
from functools import lru_cache

@lru_cache(maxsize=128)
def expensive_computation(param: int) -> int:
    ...
```

## Profiling

```bash
python -m cProfile -s cumulative script.py | head -20
```

## Targets

- UI interactions: <200ms
- DB queries: <100ms  
- File imports: progress bar if >2s
- Export generation: <5s for typical dataset

"""Data processing module.

Processes records from a data source and applies transformations.

BUG: Uses list() materialization which violates the O(n) memory
constraint. Should use a streaming/generator approach instead.
"""


def process_records(source):
    """Process all records from the source.

    BUG: Materializes the entire dataset with list() before
    iterating. This consumes O(n) memory for large datasets.
    Must be refactored to use generators/streaming.
    """
    # Bad: materializes everything into memory
    all_items = list(source.fetch_all())

    results = []
    for item in all_items:
        transformed = transform(item)
        if is_valid(transformed):
            results.append(transformed)
    return results


def transform(item):
    """Apply business logic transformation to an item."""
    return {
        "id": item.get("id"),
        "value": item.get("raw_value", 0) * 1.15,
        "status": "processed",
    }


def is_valid(item):
    """Check if a transformed item passes validation."""
    return item.get("value", 0) > 0 and item.get("id") is not None


def summarize(results):
    """Produce a summary of processed results."""
    total = sum(r["value"] for r in results)
    return {"count": len(results), "total_value": total}

import re

from .models import cosine


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def chunk_page(text, embedder, strategy="semantic", child_words=80, parent_words=320, threshold=0.35):
    """Page-local parent grouping; semantic boundaries use adjacent sentence cosine.

    Oversized sentences are split to enforce a hard word budget. Fixed and semantic
    experiments share budgets and parent construction.
    """
    if strategy not in {"fixed", "semantic"}:
        raise ValueError("Unknown chunk strategy")
    units = []
    for s in sentences(text):
        words = s.split()
        units.extend(" ".join(words[i : i + child_words]) for i in range(0, len(words), child_words))
    vectors = embedder.encode(units) if units and strategy == "semantic" else []
    children, current = [], []
    for i, unit in enumerate(units):
        words = len(unit.split())
        if current and (
            sum(len(x.split()) for x in current) + words > child_words
            or (vectors and cosine(vectors[i - 1], vectors[i]) < threshold)
        ):
            children.append(" ".join(current))
            current = []
        current.append(unit)
    if current:
        children.append(" ".join(current))
    parents, group = [], []
    for child in children:
        if group and sum(len(x.split()) for x in group) + len(child.split()) > parent_words:
            parents.append(group)
            group = []
        group.append(child)
    if group:
        parents.append(group)
    return [(" ".join(g), g) for g in parents]

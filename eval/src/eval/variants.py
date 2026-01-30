"""Variant configuration loading and discovery."""

from pathlib import Path
from typing import Any

import yaml

from eval.types import VariantConfig


# Default variants directory (relative to eval package root)
VARIANTS_DIR = Path(__file__).parent.parent.parent / "variants"


def load_variant_config(path: Path) -> VariantConfig:
    """Load and validate variant from YAML file.

    Args:
        path: Path to variant YAML file

    Returns:
        Validated VariantConfig

    Raises:
        FileNotFoundError: If file doesn't exist
        pydantic.ValidationError: If YAML doesn't match schema
    """
    with open(path) as f:
        data = yaml.safe_load(f)
    return VariantConfig.model_validate(data)


def load_all_variants(variants_dir: Path | None = None) -> dict[str, VariantConfig]:
    """Load all variant configs from directory.

    Args:
        variants_dir: Directory containing variant YAML files.
                     Defaults to eval/variants/

    Returns:
        Dict mapping variant name to VariantConfig
    """
    if variants_dir is None:
        variants_dir = VARIANTS_DIR

    variants: dict[str, VariantConfig] = {}

    if not variants_dir.exists():
        return variants

    for yaml_file in variants_dir.glob("*.yaml"):
        try:
            variant = load_variant_config(yaml_file)
            variants[variant.name] = variant
        except Exception:
            # Skip invalid files (logged elsewhere if needed)
            pass

    return variants


def get_variant(name: str, variants_dir: Path | None = None) -> VariantConfig:
    """Get specific variant by name.

    Args:
        name: Variant name to load
        variants_dir: Directory containing variant YAML files

    Returns:
        VariantConfig for the named variant

    Raises:
        ValueError: If variant not found
    """
    if variants_dir is None:
        variants_dir = VARIANTS_DIR

    # Try direct file match first
    variant_file = variants_dir / f"{name}.yaml"
    if variant_file.exists():
        return load_variant_config(variant_file)

    # Fall back to scanning all variants
    variants = load_all_variants(variants_dir)
    if name in variants:
        return variants[name]

    available = list(variants.keys()) or ["(none found)"]
    raise ValueError(f"Variant '{name}' not found. Available: {', '.join(available)}")

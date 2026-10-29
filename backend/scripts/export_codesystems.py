"""Export the local CodeSystem resources from diucs.domain.codes (I12). STUB for the red commit."""

from pathlib import Path


def export(out_dir: Path) -> list[Path]:
    raise NotImplementedError


if __name__ == "__main__":
    export(Path(__file__).resolve().parents[1] / "terminology" / "codesystems")

from pathlib import Path
import subprocess


PDF_FILE = "tests" / "documents" / "ai.pdf"
OUTPUT_FILE = "tests" / "output" / "mineru.md"


def main():
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "mineru",
        "parse",
        str(PDF_FILE),
        "--pages",
        "all",
        "-o",
        str(OUTPUT_FILE),
    ]

    subprocess.run(command, check=True)

    print(f"Saved: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
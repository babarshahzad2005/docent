"""Write the API's OpenAPI schema to a file, for generating the TypeScript client."""

import json
import sys
from pathlib import Path

from docent_api.main import app


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: docent-export-openapi <output.json>")
    out = Path(sys.argv[1])
    schema = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    out.write_text(schema, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()

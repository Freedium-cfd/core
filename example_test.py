import asyncio
import json
import sys

import jinja2
from loguru import logger
from medium_parser.core import MediumParser

jinja2_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader("./"),
)


async def main():
    logger.remove()
    logger.add(sys.stderr, level="TRACE")

    # dl = await MediumParser.from_url()
    dl = MediumParser("335c8697535b")
    query_result = await dl.query()

    with open("query_result.json", "w") as f:
        json.dump(query_result, f, indent=2)

    result = await dl.render_as_html()

    with open("medium.html", "w") as f:
        template = jinja2_env.get_template("example_base_template.html")
        template_result = template.render(body_template=result.data)
        f.write(template_result)

    print("See medium.html for the result. Press CTRL-C to exit.")
    sys.exit()


if __name__ == "__main__":
    asyncio.run(main())

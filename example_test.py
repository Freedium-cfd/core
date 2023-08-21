from medium_parser.core import MediumParser
import jinja2
import asyncio
import sys

jinja2_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader("./"),
)

async def main():
    dl = await MediumParser.from_url("https://medium.com/@jogarcia/breaking-the-proxy-walls-with-redsocks-in-linux-f4c1bfb6fb6a")
    result = await dl.render_as_html()

    with open("medium.html", "w") as f:
        template = jinja2_env.get_template("example_base_template.html")
        template_result = template.render(body_template=result.data)
        f.write(template_result)

    print("See medium.html for the result. Press CTRL-C to exit.")
    sys.exit()


if __name__ == "__main__":
    asyncio.run(main())

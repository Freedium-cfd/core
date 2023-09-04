import math
import textwrap

import jinja2
from loguru import logger

from . import jinja_env
from .exceptions import (
    InvalidMediumPostID,
    InvalidMediumPostURL,
    InvalidURL,
    MediumParserException,
    MediumPostQueryError,
)
from .medium_api import query_post_by_id
from .models.html_result import HtmlResult
from .time import convert_datetime_to_human_readable
from .toolkits.rl_string_helper.rl_string_helper import RLStringHelper, parse_markups, split_overlapping_ranges
from .utils import (
    get_medium_post_id_by_url,
    getting_percontage_of_match,
    is_valid_medium_post_id_hexadecimal,
    is_valid_medium_url,
    is_valid_url,
    sanitize_url,
)


class MediumParser:
    __slots__ = ('__post_id', 'post_data', 'jinja')

    def __init__(self, post_id: str):
        self.post_id = post_id
        self.post_data = None

    @classmethod
    async def from_url(cls, url: str) -> 'MediumParser':
        if not is_valid_url(url):
            raise InvalidURL(f'Invalid URL: {url}')

        sanitized_url = sanitize_url(url)
        if not await is_valid_medium_url(sanitized_url):
            raise InvalidURL(f'Invalid medium URL: {sanitized_url}')

        post_id = await get_medium_post_id_by_url(sanitized_url)
        if not post_id:
            raise InvalidMediumPostURL(f'Could not find medium post ID for URL: {sanitized_url}')

        return cls(post_id)

    @property
    def post_id(self):
        return self.__post_id

    @post_id.setter
    def post_id(self, value):
        if not is_valid_medium_post_id_hexadecimal(value):
            raise InvalidMediumPostID(f'Invalid medium post ID: {value}')

        self.__post_id = value

    @post_id.getter
    def post_id(self):
        return self.__post_id

    async def query(self, use_cache: bool = True, timeout: int = 3):
        try:
            post_data = await query_post_by_id(self.post_id, use_cache, timeout)
        except Exception as ex:
            logger.exception(ex)
            post_data = None

        if not post_data or not isinstance(post_data, dict) or post_data.get("error") or not post_data.get("data") or not post_data.get("data").get("post"):
            raise MediumPostQueryError(f'Could not query post by ID from API: {self.post_id}')

        self.post_data = post_data
        return self.post_data

    @staticmethod
    async def _parse_and_render_content_html_post(content: dict, title: str, subtitle: str, preview_image_id: str, highlights: list) -> tuple[list, str, str]:
        paragraphs = content["bodyModel"]["paragraphs"]
        out_paragraphs = []
        current_pos = 0

        def parse_paragraph_text(text: str, markups: list) -> str:
            text_formater = RLStringHelper(text)

            parsed_markups = parse_markups(markups)
            fixed_markups = split_overlapping_ranges(parsed_markups)

            _last_fixed_markup = None
            for i in range(len(fixed_markups) * 7):
                fixed_markups = split_overlapping_ranges(fixed_markups)
                if _last_fixed_markup and len(fixed_markups) == len(fixed_markups):
                    break
                _last_fixed_markup = fixed_markups

            for markup in fixed_markups:
                text_formater.set_template(markup["start"], markup["end"], markup["template"])

            return text_formater

        while len(paragraphs) > current_pos:
            paragraph = paragraphs[current_pos]
            logger.trace(f"Current paragraph #{current_pos} data: {paragraph}")

            # if paragraph["id"] != "9ffb82d1b0d8_36":
            #     current_pos += 1
            #     continue

            if current_pos in range(4):
                if paragraph["type"] in ["H3", "H4"]:
                    """
                    if title.endswith("…"):
                        logger.trace("Replace title")
                        title = paragraph["text"]
                        current_pos += 1
                        continue
                    """
                    if getting_percontage_of_match(paragraph["text"], title) > 80:
                        logger.trace("Title was detected, ignore...")
                        current_pos += 1
                        continue
                elif paragraph["type"] in ["H4", "P"] and subtitle:
                    is_paragraph_subtitle = getting_percontage_of_match(paragraph["text"], title) > 70
                    if is_paragraph_subtitle:  #  and subtitle.endswith("…")
                        if len(paragraph["text"]) > 100:
                            logger.warning("Subtitle is too long")
                            subtitle = None
                        else:
                            logger.trace("Replace subtitle")
                            subtitle = paragraph["text"]
                            current_pos += 1
                            continue
                    elif getting_percontage_of_match(paragraph["text"], subtitle) > 75:
                        logger.trace("Subtitle was detected, ignore...")
                        subtitle = paragraph["text"]
                        current_pos += 1
                        continue
                elif paragraph["type"] == "IMG":
                    if paragraph["metadata"]["id"] == preview_image_id:
                        logger.trace("Preview image was detected, ignore...")
                        current_pos += 1
                        continue

            if paragraph["type"] in ["IMG"]:
                logger.trace(f"Ignore paragraph type from parsing text_formater: {paragraph['type']}")
                text_formater = None
            else:
                text_formater = parse_paragraph_text(paragraph["text"], paragraph["markups"])

            for highlight in highlights:
                for highlight_paragraph in highlight["paragraphs"]:
                    if highlight_paragraph["name"] == paragraph["name"]:
                        logger.trace("Apply highlight to this paragraph")
                        if highlight_paragraph["text"] != text_formater.get_text():
                            logger.warning("Highlighted text and paragraph text are not the same! Skip...")
                            break
                        quote_markup_template = '<mark style="background-color: rgb(200 227 200);">{{ text }}</mark>'
                        text_formater.set_template(
                            highlight["startOffset"],
                            highlight["endOffset"],
                            quote_markup_template,
                        )
                        break

            if paragraph["type"] == "H3":
                css_class = []
                if out_paragraphs:
                    css_class.append("pt-12")
                header_template = jinja_env.from_string('<h1 class="font-bold font-sans break-normal text-gray-900 text-1xl md:text-2xl {{ css_class }}">{{ text }}</h1>')
                header_template_rendered = await header_template.render_async(text=text_formater.get_text(), css_class="".join(css_class))
                out_paragraphs.append(header_template_rendered)
            elif paragraph["type"] == "H4":
                css_class = []
                if out_paragraphs:
                    css_class.append("pt-8")
                subheader_template = jinja_env.from_string('<h2 class="font-bold font-sans break-normal text-gray-900 text-l md:text-xl {{ css_class }}">{{ text }}</h2>')
                subheader_template_rendered = await subheader_template.render_async(text=text_formater.get_text(), css_class="".join(css_class))
                out_paragraphs.append(subheader_template_rendered)
            elif paragraph["type"] == "IMG":
                image_template = jinja_env.from_string(
                        '<div class="mt-7"><img alt="{{ paragraph.metadata.alt }}" style="margin: auto;" class="pt-5" loading="lazy" loading="eager" role="presentation" src="https://miro.medium.com/v2/resize:fit:700/{{ paragraph.metadata.id }}"></div>'
                )
                if paragraph["layout"] == "OUTSET_ROW":
                    image_templates_row = []
                    img_row_template = jinja_env.from_string('<div class="mx-5"><div class="flex flex-row justify-center">{{ images }}</div></div>')
                    image_template_rendered = await image_template.render_async(paragraph=paragraph)
                    image_templates_row.append(image_template_rendered)
                    _tmp_current_pos = current_pos + 1
                    while len(paragraphs) > _tmp_current_pos:
                        _paragraph = paragraphs[_tmp_current_pos]
                        if _paragraph["layout"] == "OUTSET_ROW_CONTINUE":
                            image_template_rendered = await image_template.render_async(paragraph=_paragraph)
                            image_templates_row.append(image_template_rendered)
                        else:
                            break

                        _tmp_current_pos += 1

                    img_row_template_rendered = await img_row_template.render_async(images="".join(image_templates_row))
                    out_paragraphs.append(img_row_template_rendered)

                    current_pos = _tmp_current_pos - 1
                else:
                    image_template_rendered = await image_template.render_async(paragraph=paragraph)
                    out_paragraphs.append(image_template_rendered)
            elif paragraph["type"] == "P":
                css_class = ["leading-8"]
                paragraph_template = jinja_env.from_string('<p class="{{ css_class }}">{{ text }}</p>')
                if paragraphs[current_pos - 1]["type"] in ["H4", "H3"]:
                    css_class.append("mt-3")
                else:
                    css_class.append("mt-7")
                paragraph_template_rendered = await paragraph_template.render_async(text=text_formater.get_text(), css_class=" ".join(css_class))
                out_paragraphs.append(paragraph_template_rendered)
            elif paragraph["type"] == "ULI":
                uli_template = jinja_env.from_string('<ul class="list-disc pl-8 mt-2">{{ li }}</ul>')
                li_template = jinja_env.from_string("<li class='mt-3'>{{ text }}</li>")
                li_templates = []

                _tmp_current_pos = current_pos
                while len(paragraphs) > _tmp_current_pos:
                    _paragraph = paragraphs[_tmp_current_pos]
                    if _paragraph["type"] == "ULI":
                        text_formater = parse_paragraph_text(_paragraph["text"], _paragraph["markups"])
                        li_template_rendered = await li_template.render_async(text=text_formater.get_text())
                        li_templates.append(li_template_rendered)
                    else:
                        break

                    _tmp_current_pos += 1

                uli_template_rendered = await uli_template.render_async(li="".join(li_templates))
                out_paragraphs.append(uli_template_rendered)

                current_pos = _tmp_current_pos - 1
            elif paragraph["type"] == "OLI":
                ol_template = jinja_env.from_string('<ol class="list-decimal pl-8 mt-2">{{ li }}</ol>')
                li_template = jinja_env.from_string("<li class='mt-3'>{{ text }}</li>")
                li_templates = []

                _tmp_current_pos = current_pos
                while len(paragraphs) > _tmp_current_pos:
                    _paragraph = paragraphs[_tmp_current_pos]
                    if _paragraph["type"] == "OLI":
                        text_formater = parse_paragraph_text(_paragraph["text"], _paragraph["markups"])
                        li_template_rendered = await li_template.render_async(text=text_formater.get_text())
                        li_templates.append(li_template_rendered)
                    else:
                        break

                    _tmp_current_pos += 1

                ol_template_rendered = await ol_template.render_async(li="".join(li_templates))
                out_paragraphs.append(ol_template_rendered)

                current_pos = _tmp_current_pos - 1
            elif paragraph["type"] == "PRE":
                css_class = ["mt-7"]
                code_css_class = []
                if paragraph["codeBlockMetadata"] and paragraph["codeBlockMetadata"]["lang"] is not None:
                    code_css_class.append(f'language-{paragraph["codeBlockMetadata"]["lang"]}')
                else:
                    code_css_class.append('nohighlight')
                    css_class.append('p-4')
                pre_template = jinja_env.from_string('<pre style="display: flex; flex-direction: column; justify-content: center;" class="{{ css_class }}"><code style="overflow-x: auto;" class="{{ code_css_class }}">{{ text }}</code></pre>')
                pre_template_rendered = await pre_template.render_async(text=text_formater.get_text(), css_class=" ".join(css_class), code_css_class=" ".join(code_css_class))
                out_paragraphs.append(pre_template_rendered)
            elif paragraph["type"] == "BQ":
                bq_template = jinja_env.from_string('<blockquote style="box-shadow: inset 3px 0 0 0 #242424;" class="px-5 pt-3 pb-3 mt-5"><p style="font-style: italic;">{{ text }}</p></blockquote>')
                bq_template_rendered = await bq_template.render_async(text=text_formater.get_text())
                out_paragraphs.append(bq_template_rendered)
            elif paragraph["type"] == "PQ":
                pq_template = jinja_env.from_string('<blockquote class="mt-7 text-2xl ml-5" style="color: #6B6B6B;"><p>{{ text }}</p></blockquote>')
                pq_template_rendered = await pq_template.render_async(text=text_formater.get_text())
                out_paragraphs.append(pq_template_rendered)
            elif paragraph["type"] == 'MIXTAPE_EMBED':
                embed_template = jinja_env.from_string("""
<div class="border border-gray-300 mt-7">
<a rel="noopener follow" target="_blank" href="{{ paragraph.mixtapeMetadata.href }}">
    <div class="flex h-36">{{ text }}<div class="w-44 bg-cover bg-center no-lightense" style='background-image: url("https://miro.medium.com/v2/resize:fit:160/{{ paragraph.mixtapeMetadata.thumbnailImageId }}");'>
</div>
    </div>
</a>
</div>
""")
                embed_template_rendered = await embed_template.render_async(paragraph=paragraph, text=text_formater.get_text())
                # out_paragraphs.append(embed_template_rendered)
                logger.warning("Ignore MIXTAPE_EMBED paragraph type")

            else:
                logger.error(f"Unknown {paragraph['type']}: {paragraph}")

            current_pos += 1

        return out_paragraphs, title, subtitle

    async def render_as_html(self, minify: bool = True, template_folder: str = './templates'):
        try:
            result = await self._render_as_html(minify, template_folder)
        except Exception as ex:
            raise MediumParserException(ex) from ex
        else:
            return result

    async def generate_metadata(self, as_dict: bool = False) -> tuple:
        title = self.post_data["data"]["post"]["title"]
        subtitle = self.post_data["data"]["post"]["previewContent"]["subtitle"]
        description = textwrap.shorten(subtitle, width=100, placeholder="...")
        preview_image_id = self.post_data["data"]["post"]["previewImage"]["id"]
        creator = self.post_data["data"]["post"]["creator"]
        collection = self.post_data["data"]["post"]["collection"]
        url = self.post_data["data"]["post"]["mediumUrl"]

        reading_time = math.ceil(self.post_data["data"]["post"]["readingTime"])
        free_access = "No" if self.post_data["data"]["post"]["isLocked"] else "Yes"
        updated_at = convert_datetime_to_human_readable(self.post_data["data"]["post"]["updatedAt"])
        first_published_at = convert_datetime_to_human_readable(self.post_data["data"]["post"]["firstPublishedAt"])
        tags = self.post_data["data"]["post"]["tags"]

        if as_dict:
            return {"post_id": self.post_id, "title": title, "subtitle": subtitle, "description": description, "url": url, "creator": creator, "collection": collection, "reading_time": reading_time, "free_access": free_access, "updated_at": updated_at, "first_published_at": first_published_at, "preview_image_id": preview_image_id, "tags": tags}

        return title, subtitle, description, url, creator, collection, reading_time, free_access, updated_at, first_published_at, preview_image_id, tags

    async def _render_as_html(self, minify: bool = True, template_folder: str = './templates') -> 'HtmlResult':
        if not self.post_data:
            logger.warning(f'No post data found for post ID: {self.post_id}. Querying...')
            await self.query()

        jinja_template = jinja2.Environment(loader=jinja2.FileSystemLoader(template_folder), enable_async=True)
        post_template = jinja_template.get_template('post.html')

        title, subtitle, description, url, creator, collection, reading_time, free_access, updated_at, first_published_at, preview_image_id, tags = await self.generate_metadata()

        content, title, subtitle = await self._parse_and_render_content_html_post(
            self.post_data["data"]["post"]["content"],
            title,
            subtitle,
            preview_image_id,
            self.post_data["data"]["post"]["highlights"],
        )

        post_page_title_raw = "{{ title }} | by {{ creator.name }}"
        if collection:
            post_page_title_raw += " | in {{ collection.name }}"
        post_page_title = jinja_env.from_string(post_page_title_raw)
        post_page_title_rendered = await post_page_title.render_async(title=title, creator=creator, collection=collection)

        post_context = {
            "subtitle": subtitle,
            "title": title,
            "url": url,
            "creator": creator,
            "collection": collection,
            "readingTime": reading_time,
            "freeAccess": free_access,
            "updatedAt": updated_at,
            "firstPublishedAt": first_published_at,
            "previewImageId": preview_image_id,
            "content": content,
            "tags": tags,
        }
        post_template_rendered = await post_template.render_async(post_context)

        return HtmlResult(post_page_title_rendered, description, url, post_template_rendered)

    async def render_as_markdown(self) -> str:
        raise NotImplementedError("Markdown rendering is not implemented. Please use HTML rendering instead")

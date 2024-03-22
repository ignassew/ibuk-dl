import argparse
import asyncio
import json
import logging
import re
import sys

import requests
import websockets
from bs4 import BeautifulSoup, Tag

from .yeast import yeast


class BookMetadata:
    def __init__(self, data) -> None:
        self._data = data
        self.author: str = data["author"]
        self.index: int = data["index"]
        self.isbn: str = data["isbn"]
        self.pages: str = data["pages"]
        self.publisher: str = data["redaction"]
        self.slugged_title: str = data["slugged_title"]
        self.title: str = data["title"]
        self.description: str = data["review"]


class IbukWebSession(requests.Session):
    def __init__(self, api_key=None) -> None:
        super().__init__()

        self._api_key = api_key

    def api_key(self) -> str:
        if self._api_key is not None:
            return self._api_key

        r = self.get("https://libra.ibuk.pl/")
        assert r.status_code == 200

        self._api_key = self.cookies["ilApiKey"]
        return self._api_key

    def login_pw(self, username, password):
        logging.info("Logging in with PW")
        data = {
            "func": "login",
            "calling_system": "han",
            "term1": "short",
            "url": "http://eczyt.bg.pw.edu.pl/pds/x",
            "selfreg": "",
            "bor_id": username,
            "bor_verification": password,
            "institute": "WTU50",
        }
        r = self.post("https://gate.bg.pw.edu.pl/pds", data=data)

        match = re.search(r"PDS_HANDLE = (\d+)", r.text)
        assert match is not None
        pds = match.group(1)

        r = self.get(
            f"http://eczyt.bg.pw.edu.pl/pds/x?=&selfreg=&bor_id={username}&bor_verification={password}&institute=WTU50&pds_handle={pds}"
        )
        assert r.status_code == 302

        r = self.get("http://eczyt.bg.pw.edu.pl/han/ibuk/https/libra.ibuk.pl/")
        assert r.status_code == 200

        self._api_key = self.cookies["libra.ibuk.pl/@ilApiKey"]

    def get_book_metadata(self, url):
        r = self.get(url)
        assert r.status_code == 200

        soup = BeautifulSoup(r.text, "html.parser")
        page_state = soup.find("script", {"id": "app-libra-2-state"})
        assert type(page_state) is Tag

        # clean up encoding
        page_state = json.loads(str(page_state.contents[0]).replace("&q;", '"'))

        return BookMetadata(page_state["DETAILS_CACHE_KEY"])


class IbukWebSocketSession:
    def __init__(
        self, api_key: str, socket_io_base_url="libra23.ibuk.pl/socket.io"
    ) -> None:
        self._api_key = api_key
        self._socket_io_base_url = socket_io_base_url

    async def _connect(self):
        self.ws = await websockets.connect(
            f"wss://{self._socket_io_base_url}/?apiKey={self._api_key}&isServer=0&EIO=4&transport=websocket&sid={self._create_session()}",
            max_size=None
        )

        await self._hello()

    async def __aenter__(self):
        await self._connect()
        return self

    async def __aexit__(self, *_):
        await self.close()

    def _create_session(self) -> str:
        r = requests.get(
            f"https://{self._socket_io_base_url}/",
            params={
                "apiKey": self._api_key,
                "isServer": "0",
                "EIO": "4",
                "transport": "polling",
                "t": yeast(),
            },
        )

        assert r.status_code == 200

        return json.loads(r.text[1:])["sid"]

    async def close(self):
        await self.ws.close()

    async def _hello(self):
        await self.ws.send("2probe")
        assert await self.ws.recv() == "3probe"

        await self.ws.send("5")

        await self.ws.send("40/books,")
        assert "40/books," in str(await self.ws.recv())
        assert await self.ws.recv() == '42/books,["ready"]'

    async def _handle_recv(self):
        while True:
            msg = str(await self.ws.recv())
            if msg == "2":
                await self.ws.send("3")
            else:
                return msg

    async def get_page(self, book_id, page: int) -> str:
        await self.ws.send(
            f"""42/books,["page","{{\\"bookId\\":{book_id},\\"compressed\\":10,\\"format\\":\\"html\\",\\"pagenumber\\":{page},\\"fontSize\\":12,\\"pageNumber\\":{page},\\"compression\\":10,\\"type\\":\\"standard\\",\\"width\\":716}}"]"""
        )
        r = await self._handle_recv()

        data = json.loads(json.loads(r.split("42/books,")[1])[1])
        if data.get("error", False):
            logging.error(f"encountered while fetching page {page}: {data.get('message', '')}")
            raise PermissionError("Error while fetching page")
        return data["html"]

    async def get_css(self, book_id):
        await self.ws.send(
            f"""42/books,["css","{{\\"bookId\\":{book_id},\\"width\\":839,\\"fontSize\\":15.04}}"]"""
        )
        r = await self._handle_recv()

        return json.loads(json.loads(r.split("42/books,")[1])[1])["html"]

    async def get_fonts(self, book_id):
        await self.ws.send(f"""42/books,["font","{{\\"bookId\\":{book_id}}}"]""")
        r = await self._handle_recv()
        fonts = json.loads(json.loads(r.split("42/books,")[1])[1])["html"]

        # According to the spec[1], url is followed by format WITHOUT a semicolon,
        # so we patch it
        # [1]: https://developer.mozilla.org/en-US/docs/Web/CSS/@font-face/src
        fonts = re.sub("; format", " format", fonts)
        return fonts

    async def get_book_html(self, book_id, page_n: int) -> str:
        fonts = await self.get_fonts(book_id)
        style = await self.get_css(book_id)
        pages = []
        for i in range(1, page_n + 1):
            logging.info(f"Getting page {i}")
            try:
                page = await self.get_page(book_id, i)
            except PermissionError:
                break
            pages.append(page)

        pages = "\n".join(pages)
        html = f"""
                <!DOCTYPE html>
                <html lang="en">
                    <head>
                        <title></title>
                        <meta charset="UTF-8">
                        <meta name="viewport" content="width=device-width, initial-scale=1">
                        <style>{style}</style>
                        <style id='font-style'>{fonts}</style>
                    </head>
                    <body>
                    {pages}
                    </body>
                </html>"""

        return html


async def download_action(
    url: str, page_count: int | None, ibs: IbukWebSession, output
):
    logging.info(f"Fetching book from URL: {url}")
    book_metadata = ibs.get_book_metadata(url)

    if not page_count:
        page_count = int(book_metadata.pages)

    logging.info(f"Downloading {book_metadata.author} - {book_metadata.title}")
    async with IbukWebSocketSession(ibs.api_key()) as ibws:
        book = await ibws.get_book_html(book_metadata.index, page_count)

    try:
        if output == "-":
            output = sys.stdout
        else:
            output = open(output, "w+")

        output.write(book)
        output.write("\n")
    finally:
        output.close()

    logging.info(f"Downloaded {book_metadata.author} - {book_metadata.title} pages to {output.name}")


async def query_action(url: str, ibs: IbukWebSession):
    logging.info(f"Querying book info for URL: {url}")

    book_metadata = ibs.get_book_metadata(url)

    print(f"Author: {book_metadata.author}")
    print(f"Title: {book_metadata.title}")
    print(f"Description: {book_metadata.description}")
    print(f"Publisher: {book_metadata.publisher}")
    print(f"Isbn: {book_metadata.isbn}")
    print(f"Pages: {book_metadata.pages}")
    print(f"Index: {book_metadata.index}")


async def main():
    parser = argparse.ArgumentParser(
        prog="ibuk-dl",
        description="Download a book or query book info from a given libra.ibuk.pl URL",
    )

    visibility_group = parser.add_mutually_exclusive_group()
    visibility_group.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose mode"
    )
    visibility_group.add_argument(
        "-q", "--quiet", action="store_true", help="Enable quiet mode"
    )

    subparsers = parser.add_subparsers(dest="action")

    download_parser = subparsers.add_parser("download", help="Download a book")

    download_parser.add_argument("--page-count", type=int, help="Page count (optional)")
    download_parser.add_argument(
        "-o",
        "--output",
        default="-",
        help="Output destination (if -, output is STDOUT)",
    )

    pw_auth_group = download_parser.add_argument_group(
        title="PW authentication",
        description="Authenticate yourself through an eczyt.bg.pw.edu.pl account (optional)",
    )
    pw_auth_group.add_argument("-u", "--username")
    pw_auth_group.add_argument("-p", "--password")

    subparsers.add_parser("query", help="Query book info")

    parser.add_argument("url", help="libra.ibuk.pl URL")

    args = parser.parse_args()

    logging_level = logging.WARNING
    if args.verbose:
        logging_level = logging.INFO
    elif args.quiet:
        logging_level = logging.CRITICAL

    logging.basicConfig(level=logging_level)

    ibs = IbukWebSession()

    if args.action == "download":
        if bool(args.username) ^ bool(args.password):
            parser.error("If username is provided, password must also be provided.")

        if args.username:
            ibs.login_pw(args.username, args.password)

        await download_action(args.url, args.page_count, ibs, args.output)
    elif args.action == "query":
        await query_action(args.url, ibs)


def run_main():
    asyncio.run(main())


if __name__ == "__main__":
    run_main()

import argparse
import asyncio
import json
import logging
import re
import sys
import os
import requests
import websockets
from bs4 import BeautifulSoup, Tag
import glob
import shutil
import concurrent.futures
from pyppeteer import launch
from pypdf import PdfWriter
from .yeast import yeast


class BookMetadata:
    def __init__(self, data) -> None:
        self._data = data
        self.author: str = data.get("author", "Unknown Author")
        self.index: int = data.get("index")
        self.isbn: str = data.get("isbn")
        self.pages: str = data.get("pages", "N/A")
        self.publisher: str = data.get("redaction", "Unknown Publisher")
        self.slugged_title: str = data.get("slugged_title", "untitled")
        self.title: str = data.get("title", "Untitled")
        self.description: str = data.get("review", "No description available.")
        self.cover_url: str | None = data['covers'][0]['jpg_location'] if data.get('covers') else None

class IbukWebSession(requests.Session):
    def __init__(self, username=None, password=None, use_firefox_cookies=False, use_pw=False):
        super().__init__()
        self._api_key = None
        self._username = username
        self._password = password
        self._use_firefox_cookies = use_firefox_cookies
        self._use_pw = use_pw
        
        if self._use_firefox_cookies:
            try:
                import browser_cookie3 as bc
                self._load_firefox_cookies(bc)
            except ImportError:
                logging.error(
                    "The 'browser_cookie3' library is not installed. Please run 'pip install browser_cookie3'.")
                sys.exit(1)

    def _load_firefox_cookies(self, browsercookie_lib):
        cj = browsercookie_lib.firefox(domain_name="libra.ibuk.pl")
        self.cookies.clear()
        for c in cj:
            if c.name != "ilApiKey": self.cookies.set(c.name, c.value, domain=c.domain, path=c.path)
        il_cookie = next((c.value for c in cj if c.name == "ilApiKey"), None)
        if not il_cookie: raise RuntimeError("No ilApiKey cookie found in Firefox cookies.")
        self._api_key = il_cookie

    def login(self):
        if not self._username or not self._password:
            return
        
        logging.info("Logging in...")
        payload = {"email": self._username, "password": self._password}
        r = self.post("https://libra.ibuk.pl/credentials/login-bsr", json=payload)
        r.raise_for_status()

    def login_pw(self, username, password):
        logging.info("Logging in with PW (Politechnika Warszawska)...")
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
        if not match:
             logging.error("Could not find PDS_HANDLE in PW login response. Authentication failed?")
             raise RuntimeError("PW Login Failed: PDS_HANDLE not found")
        
        pds = match.group(1)

        r = self.get(
            f"http://eczyt.bg.pw.edu.pl/pds/x?=&selfreg=&bor_id={username}&bor_verification={password}&institute=WTU50&pds_handle={pds}"
        )
        if r.status_code != 302 and r.status_code != 200:
             pass

        r = self.get("http://eczyt.bg.pw.edu.pl/han/ibuk/https/libra.ibuk.pl/")
        r.raise_for_status()
        
        if "ilApiKey" not in self.cookies:
              self.get("https://libra.ibuk.pl/")

    def api_key(self) -> str:
        if self._api_key: return self._api_key
        
        if self._username and self._password:
            if self._use_pw:
                self.login_pw(self._username, self._password)
            else:
                self.login()
        else:
            r = self.get("https://libra.ibuk.pl/")
            r.raise_for_status()
            
        api_key_cookie = next((cookie for cookie in self.cookies if cookie.name == 'ilApiKey'), None)
        if not api_key_cookie: raise RuntimeError("API key not found in cookies.")
        self._api_key = api_key_cookie.value
        return self._api_key

    def get_book_metadata(self, url):
        r = self.get(url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        page_state = soup.find("script", {"id": "app-libra-2-state"})
        assert type(page_state) is Tag
        page_state = json.loads(str(page_state.contents[0]).replace("&q;", '"'))
        return BookMetadata(page_state["DETAILS_CACHE_KEY"])


class IbukWebSocketSession:
    def __init__(self, api_key: str, ibs: IbukWebSession, socket_io_base_url="libra23.ibuk.pl/socket.io"):
        self._api_key = api_key
        self._ibs = ibs
        self._socket_io_base_url = socket_io_base_url

    async def _connect(self):
        sid = self._create_session()
        ws_url = f"wss://{self._socket_io_base_url}/?apiKey={self._api_key}&isServer=0&EIO=4&transport=websocket&sid={sid}"
        self.ws = await websockets.connect(ws_url, max_size=None)
        await self._hello()

    async def __aenter__(self):
        await self._connect(); return self

    async def __aexit__(self, *_):
        await self.close()

    def _create_session(self) -> str:
        r = requests.get(f"https://{self._socket_io_base_url}/",
                         params={"apiKey": self._api_key, "isServer": "0", "EIO": "4", "transport": "polling",
                                 "t": yeast()}, cookies=self._ibs.cookies)
        r.raise_for_status()
        return json.loads(r.text[1:])["sid"]

    async def close(self):
        await self.ws.close()

    async def _hello(self):
        await self.ws.send("2probe")
        resp = await self.ws.recv()
        if resp != "3probe": logging.warning(f"Expected '3probe', got {resp}")
        await self.ws.send("5")
        await self.ws.send("40/books,")
        ack_msg = await self.ws.recv()
        if not ack_msg.startswith("40/books,"): logging.warning(f"Expected namespace ack, got {ack_msg}")
        ready_msg = await self.ws.recv()
        if "42/books,[\"ready\"" not in ready_msg: logging.warning(f"Expected 'ready', got {ready_msg}")

    async def _handle_recv(self):
        while True:
            msg = str(await self.ws.recv())
            if msg == "2":
                await self.ws.send("3")
            else:
                return msg

    async def get_page(self, book_id, page: int) -> str:
        await self.ws.send(
            f"""42/books,["page","{{\\"bookId\\":{book_id},\\"compressed\\":10,\\"format\\":\\"html\\",\\"pagenumber\\":{page},\\"fontSize\\":12,\\"pageNumber\\":{page},\\"compression\\":10,\\"type\\":\\"standard\\",\\"width\\":716}}"]""")
        r = await self._handle_recv()
        data = json.loads(json.loads(r.split("42/books,")[1])[1])
        if data.get("error", False): raise PermissionError(data.get("message", "Error fetching page"))
        return data["html"]

    async def get_css(self, book_id):
        await self.ws.send(f"""42/books,["css","{{\\"bookId\\":{book_id},\\"width\\":839,\\"fontSize\\":15.04}}"]""")
        r = await self._handle_recv()
        return json.loads(json.loads(r.split("42/books,")[1])[1])["html"]

    async def get_fonts(self, book_id):
        await self.ws.send(f"""42/books,["font","{{\\"bookId\\":{book_id}}}"]""")
        r = await self._handle_recv()
        fonts = json.loads(json.loads(r.split("42/books,")[1])[1])["html"]
        return re.sub("; format", " format", fonts)

def clean_page_html(html_content: str) -> str:
    return re.sub(r'<span[^>]*>\s*</span>', ' ', html_content)

async def perform_download_action(url: str, page_count: int | None, ibs: IbukWebSession, output_dir: str | None,
                                  no_cover: bool):
    logging.info("Action: Download book data")
    book_metadata = ibs.get_book_metadata(url)
    if not page_count: page_count = int(book_metadata.pages)
    if not output_dir:
        output_dir = re.sub(r'[<>:"/\\|?*]', '', f"{book_metadata.author} - {book_metadata.title}").strip()
    pages_dir = os.path.join(output_dir, "pages")
    os.makedirs(pages_dir, exist_ok=True)
    logging.info(f"Downloading data to directory: '{output_dir}'")
    if not no_cover and book_metadata.cover_url:
        try:
            cover_res = requests.get(book_metadata.cover_url, timeout=10)
            cover_res.raise_for_status()
            with open(os.path.join(output_dir, "cover.jpg"), 'wb') as f:
                f.write(cover_res.content)
            logging.info("Downloaded cover.jpg")
        except requests.RequestException as e:
            logging.error(f"Failed to download cover: {e}")
    async with IbukWebSocketSession(ibs.api_key(), ibs) as session:
        fonts, style = await session.get_fonts(book_metadata.index), await session.get_css(book_metadata.index)
        with open(os.path.join(output_dir, "fonts.css"), "w", encoding="utf-8") as f:
            f.write(fonts)
        with open(os.path.join(output_dir, "style.css"), "w", encoding="utf-8") as f:
            f.write(style)
        num_downloaded = 0
        for i in range(1, page_count + 1):
            logging.info(f"Getting page {i}/{page_count}")
            try:
                page_html = await session.get_page(book_metadata.index, i)
                with open(os.path.join(pages_dir, f"{i}.html"), "w", encoding="utf-8") as f:
                    f.write(page_html)
                num_downloaded += 1
            except PermissionError as e:
                logging.warning(f"Could not get page {i}: {e}. Stopping.");
                break
    manifest = book_metadata._data
    manifest['num_pages_downloaded'] = num_downloaded
    with open(os.path.join(output_dir, "manifest.json"), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=4)
    logging.info(f"Downloaded {num_downloaded} pages and metadata.")
    logging.info(f"Book info saved to: '{output_dir}'")
    return output_dir

def is_html_empty(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'lxml')
        
        if not soup.body:
            return True

        text = soup.body.get_text(strip=True)
        media = soup.body.find_all(['img', 'svg', 'image', 'iframe', 'canvas', 'embed', 'video'])

        if text == "" and not media:
            for tag in soup.body.find_all(True):
                style = tag.get('style')
                if style and 'url(' in style:
                    return False
            return True
            
        return False
    except Exception:
        return False


async def convert_single_page(semaphore, browser, input_path, temp_dir, style_content, font_content, progress_info):
    async with semaphore:
        page = None
        try:
            full_path = "file://" + os.path.abspath(input_path)
            basename = os.path.basename(input_path)
            pdf_name = os.path.splitext(basename)[0] + ".pdf"
            pdf_path = os.path.join(temp_dir, pdf_name)

            page = await browser.newPage()
            
            await page.goto(full_path, {'waitUntil': 'load', 'timeout': 30000})

            if font_content:
                await page.addStyleTag({'content': font_content})
            if style_content:
                await page.addStyleTag({'content': style_content})

            await page.pdf({
                'path': pdf_path,
                'format': 'A4',
                'printBackground': True,
                'margin': {'top': '0px', 'bottom': '0px', 'left': '0px', 'right': '0px'}
            })
            
            await page.close()
            
            current = progress_info['current'] = progress_info['current'] + 1
            total = progress_info['total']
            print(f"[{current}/{total}] Converted: {basename}")
            
            return pdf_path

        except Exception as e:
            print(f"  - Error converting {os.path.basename(input_path)}: {e}")
            if page:
                try:
                    await page.close()
                except:
                    pass
            return None


def merge_pdfs(pdf_parts, output_path):
    if not pdf_parts:
        print("No PDF parts were created. Aborting merge.")
        return

    print(f"\nMerging {len(pdf_parts)} pages...")
    merger = PdfWriter()
    for pdf_part in pdf_parts:
        try:
            merger.append(pdf_part, pages=(0, 1))
        except Exception as e:
            print(f"Warning: Could not merge {pdf_part}: {e}")

    merger.write(output_path)
    merger.close()
    print(f"Merged PDF saved to: {output_path}")

async def perform_convert_action(source_dir: str, output_file: str | None, format: str, cleanup: bool = False):
    logging.info(f"Action: Convert data from '{source_dir}' to '{format}'")
    if not os.path.isdir(source_dir): logging.error(f"Source directory not found: {source_dir}"); sys.exit(1)
    
    html_dir = os.path.join(source_dir, "pages")
    manifest_path = os.path.join(source_dir, "manifest.json")
    
    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
        book_metadata = BookMetadata(manifest)
    except FileNotFoundError:
        logging.error(f"manifest.json not found in '{source_dir}'!"); sys.exit(1)

    if not output_file:
        base_fn = re.sub(r'[<>:"/\\|?*]', '', f"{book_metadata.author} - {book_metadata.title}").strip()
        output_file = f"{base_fn}.{format}"

    style, fonts = '', ''
    try:
        with open(os.path.join(source_dir, "style.css"), "r", encoding="utf-8") as f: style = f.read()
        with open(os.path.join(source_dir, "fonts.css"), "r", encoding="utf-8") as f: fonts = f.read()
    except FileNotFoundError:
        logging.warning("CSS files not found, proceeding without styles.")

    cover_data = None
    cover_path = os.path.join(source_dir, "cover.jpg")
    if os.path.exists(cover_path):
        with open(cover_path, 'rb') as f: cover_data = f.read()

    if format == 'pdf':
        executable_path = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
        if not os.path.exists(executable_path):
             executable_path = "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe"
        
        launch_args = {'headless': True, 'args': ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-accelerated-2d-canvas', '--no-first-run', '--no-zygote']}
        if os.path.exists(executable_path):
            launch_args['executablePath'] = executable_path
        else:
             logging.info("Chrome not found at standard locations, using Pyppeteer bundled Chromium...")

        html_files = glob.glob(os.path.join(html_dir, "*.html"))
        if not html_files:
            logging.error(f"No .html files found in '{html_dir}'")
            return

        try:
            html_files = sorted(html_files, key=lambda f: int(os.path.basename(f).split('.')[0]))
        except ValueError:
            html_files = sorted(html_files)
        
        logging.info(f"Found {len(html_files)} files. Checking for empty pages...")

        valid_html_files = []
        with concurrent.futures.ProcessPoolExecutor() as executor:
            results = list(executor.map(is_html_empty, html_files))
        
        for file, is_empty in zip(html_files, results):
            if not is_empty:
                valid_html_files.append(file)
            else:
                 pass

        total_files = len(valid_html_files)
        logging.info(f"Starting optimized PDF conversion for {total_files} pages...")

        temp_dir = os.path.join(source_dir, "temp_pdf_parts")
        os.makedirs(temp_dir, exist_ok=True)

        browser = await launch(**launch_args)
        semaphore = asyncio.Semaphore(10) # 10 Concurrent tabs
        progress_info = {'current': 0, 'total': total_files}
        
        tasks = []
        for html_file in valid_html_files:
            tasks.append(convert_single_page(semaphore, browser, html_file, temp_dir, style, fonts, progress_info))
            
        results = await asyncio.gather(*tasks)
        pdf_parts = [r for r in results if r is not None]
        
        await browser.close()
        
        merge_pdfs(pdf_parts, output_file)
        
        for part in pdf_parts:
            try: os.remove(part)
            except: pass
        try: os.rmdir(temp_dir)
        except: pass

    else:
        pages_html = []
        num_pages = manifest.get('num_pages_downloaded', 0)
        if num_pages == 0:
             num_pages = len(glob.glob(os.path.join(html_dir, "*.html")))

        for i in range(1, num_pages + 1):
            p_path = os.path.join(html_dir, f"{i}.html")
            if os.path.exists(p_path):
                with open(p_path, "r", encoding="utf-8") as f:
                    content = clean_page_html(f.read())
                    pages_html.append(content)
        
        logging.info(f"Loaded {len(pages_html)} pages.")

        if format == 'html':
            full_html = f'<!DOCTYPE html><html><head><title>{book_metadata.title}</title><meta charset="UTF-8"><style>{style}</style><style>{fonts}</style></head><body>{"".join(pages_html)}</body></html>'
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(full_html)
        
        logging.info(f"Successfully created {output_file}")
    
    cover_src = os.path.join(source_dir, "cover.jpg")
    if os.path.exists(cover_src):
        output_dir_path = os.path.dirname(os.path.abspath(output_file))
        output_basename = os.path.splitext(os.path.basename(output_file))[0]
        cover_dst = os.path.join(output_dir_path, f"{output_basename}.jpg")
        
        if os.path.abspath(cover_src) != os.path.abspath(cover_dst):
             try:
                 shutil.copy2(cover_src, cover_dst)
                 logging.info(f"Saved cover image to: {cover_dst}")
             except Exception as e:
                 logging.warning(f"Could not save cover image: {e}")

    if cleanup:
        abs_source = os.path.abspath(source_dir)
        abs_output = os.path.abspath(output_file)
        try:
             source_prefix = abs_source + os.sep
             if abs_output.startswith(source_prefix):
                 logging.warning(f"Output file '{output_file}' is inside source directory '{source_dir}'. Skipping cleanup to avoid deleting the result.")
                 return
        except Exception:
             pass 

        logging.info(f"Cleaning up source directory: {source_dir}")
        try:
            shutil.rmtree(source_dir)
        except Exception as e:
            logging.error(f"Failed to remove source directory: {e}")


def perform_query_action(url: str, ibs: IbukWebSession):
    logging.info("Action: Query Book Metadata")
    book_metadata = ibs.get_book_metadata(url)
    print("-" * 20)
    print(f"Author:      {book_metadata.author}")
    print(f"Title:       {book_metadata.title}")
    print(f"Description: {book_metadata.description}")
    print(f"Cover URL:   {book_metadata.cover_url}")
    print("-" * 20)

async def main():
    parser = argparse.ArgumentParser(prog="ibuk-dl", description="Download and convert books from libra.ibuk.pl.",
                                     epilog="Example: ibuk-dl https://path/to/book")
    parser.add_argument("--convert", metavar="SOURCE_DIR", help="Convert data from SOURCE_DIR into an EPUB/HTML file.")
    parser.add_argument("url_or_dir", nargs='?', help="Book URL for download, or source directory for --convert.")
    parser.add_argument("--query", action="store_true", help="Display book metadata instead of downloading.")
    parser.add_argument("-o", "--output", help="Output directory (download) or file (convert).")
    parser.add_argument("--page-count", type=int, help="Number of pages to download.")
    parser.add_argument("--format", default="pdf", choices=['html', 'pdf'], help="Output format for conversion.")
    parser.add_argument("--no-cover", action="store_true", help="Do not download or embed the book cover.")
    parser.add_argument("--no-convert", action="store_true", help="Skip automatic conversion after download.")
    parser.add_argument("--keep", action="store_true", help="Keep source files (HTML/CSS) after conversion.")
    parser.add_argument("--firefox-cookies", action="store_true", help="Use Firefox cookies for authentication.")
    parser.add_argument("--pw", action="store_true", help="Use Politechnika Warszawska (PW) authentication.")
    parser.add_argument("-u", "--username", help="Email for login.")
    parser.add_argument("-p", "--password", help="Password for login.")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    logging.getLogger('websockets.client').setLevel(logging.WARNING)

    action = 'download'
    if args.query:
        action = 'query'
    elif args.convert:
        action = 'convert'

    if action == 'query':
        if not args.url_or_dir or not args.url_or_dir.startswith("http"): logging.error(
            "A URL is required for --query action."); parser.print_help(); sys.exit(1)
        try:
            ibs = IbukWebSession(username=args.username, password=args.password, use_firefox_cookies=args.firefox_cookies, use_pw=args.pw)
            ibs.api_key()  # REMOVED await
            await perform_query_action(args.url_or_dir, ibs)
        except Exception as e:
            logging.error(f"Query error: {e}", exc_info=False); sys.exit(1)

    elif action == 'convert':
        source_dir = args.convert
        if not source_dir:
            if args.url_or_dir and os.path.isdir(args.url_or_dir):
                source_dir = args.url_or_dir
            elif args.url_or_dir:
                 logging.error("A source directory must be provided with --convert.");
                 parser.print_help();
                 sys.exit(1)
            else:
                 logging.error("A source directory must be provided with --convert.");
                 parser.print_help();
                 sys.exit(1)
        await perform_convert_action(source_dir, args.output, args.format)

    elif action == 'download':
        if not args.url_or_dir or not args.url_or_dir.startswith("http"): logging.error(
            "A book URL is required for download action."); parser.print_help(); sys.exit(1)
        try:
            ibs = IbukWebSession(username=args.username, password=args.password, use_firefox_cookies=args.firefox_cookies, use_pw=args.pw)
            ibs.api_key()
            output_dir = await perform_download_action(args.url_or_dir, args.page_count, ibs, args.output, args.no_cover)
            
            if output_dir and not args.no_convert:
                print("\n" + "="*40)
                logging.info(f"Download complete. Automatically starting conversion to {args.format.upper()}...")
                print("="*40 + "\n")
                await perform_convert_action(output_dir, None, args.format, cleanup=not args.keep)
                
        except Exception as e:
            logging.error(f"Download error: {e}", exc_info=False); sys.exit(1)

def run_main():
    if sys.platform == "win32": asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())

if __name__ == "__main__":
    run_main()

# IBUK Downloader

This script allows you to download books from the libra.ibuk.pl website and query book information from a given URL.

## Features

- Download books from libra.ibuk.pl.
- Query book information, including author, title, description, publisher, ISBN, pages, and index.
- Support for PW (Politechnika Warszawska/Warsaw University of Technology) authentication to access restricted content.

## Installation

```shell
pip install ibuk-dl
```

## Running from Source (with uv)

If you are using fork directly without installing it, you can run it using [uv](https://github.com/astral-sh/uv):

```shell
# Run directly
uv run ibuk-dl <args>

# Example
uv run ibuk-dl https://libra.ibuk.pl/reader/book-url -u email@example.com -p password
```

## Usage
 
### Download a Book (Auto-Convert to PDF)

To download a book and automatically convert it to a high-quality PDF:

```shell
ibuk-dl <URL> -u <EMAIL> -p <PASSWORD>
```

This will:
1. Download all pages to a temporary folder.
2. Launch a headless Chrome/Chromium to render pages exactly as they appear (preserving fonts and layout).
3. Merge them into a single PDF.
4. Clean up the temporary files.

### Options

*   `--no-convert`: Skip the automatic PDF conversion (keep the downloaded HTML pages).
*   `--keep`: Keep the folder with downloaded files (HTML/CSS) after successful PDF conversion.
*   `--format`: Output format, default is `pdf`. Use `html` if you want raw concatenated HTML.
*   `--page-count <N>`: Download only the first N pages.
*   `--no-cover`: Skip downloading the cover image.
*   `--firefox-cookies`: Use cookies from a running Firefox instance (via `browser_cookie3`) instead of username/password. Useful for SSO logins like PW.
*   `--pw`: Use direct Politechnika Warszawska (PW) authentication. Use this with standard username/password if you need to access PW-restricted content directly.

### Examples

**Download full book as PDF:**
```shell
ibuk-dl https://libra.ibuk.pl/reader/some-book -u user@example.com -p secret
```

**Download with PW Authentication:**
```shell
ibuk-dl https://libra.ibuk.pl/reader/some-book -u YOUR_BOR_ID -p YOUR_PASSWORD --pw
```

**Download using Firefox cookies (if logged in via browser):**
```shell
ibuk-dl https://libra.ibuk.pl/reader/some-book --firefox-cookies
```

**Download only first 10 pages without converting:**
```shell
ibuk-dl https://libra.ibuk.pl/reader/some-book -u user@example.com -p secret --page-count 10 --no-convert
```


## License

This script is provided under a MIT License. See [LICENSE](/LICENSE)

## Disclaimer

As stated in the license, I am not responsible for damage caused by the use of this program. Please respect the terms of use of the libra.ibuk.pl website and any copyright or licensing agreements for the downloaded content. Downloading and/or sharing copyrighted content may be considered illegal in your country.

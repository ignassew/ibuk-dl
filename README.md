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

## Usage

### Download a Book

To download a book, use the following command:

```shell
ibuk-dl download <URL>
```

You can specify the page count with the `--page-count` option (if not specified, will download every page) and the output file with the `-o` or `--output` option. Use `-` as the output to print the book content to stdout. Add -v to print progress information to the console.

If the book is behind PW authentication, you can provide your username and password with the `-u` and `-p` options, respectively. You will also need to use an URL that starts with `http://eczyt.bg.pw.edu.pl/han/ibuk/`

Example:

```shell
ibuk-dl -v download --output "podstawy-teorii-obwodow-tom-2.html" -u 123123 -p password http://eczyt.bg.pw.edu.pl/han/ibuk/https/libra.ibuk.pl/reader/podstawy-teorii-obwodow-tom-2-jerzy-osiowski-jerzy-szabatin-234596
```

More information about `download`:

```shell
ibuk-dl download --help
```

### Query Book Information

To query book information, use the following command:

```shell
ibuk-dl query <URL>
```

Example:

```shell
ibuk-dl -v query https://libra.ibuk.pl/reader/podstawy-teorii-obwodow-tom-2-jerzy-osiowski-jerzy-szabatin-234596
```

More information about `query`:

```shell
ibuk-dl query --help
```

## Export to PDF

This script will output HTML. If you want to have a PDF, you can use your browser's `Print -> Save to PDF` option.

## License

This script is provided under a MIT License. See [LICENSE](/LICENSE)

## Disclaimer

As stated in the license, I am not responsible for damage caused by the use of this program. Please respect the terms of use of the libra.ibuk.pl website and any copyright or licensing agreements for the downloaded content. Downloading and/or sharing copyrighted content may be considered illegal in your country.
